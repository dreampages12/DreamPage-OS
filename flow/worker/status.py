# -*- coding: utf-8 -*-
"""Lettvekts, LESE-ONLY driftsstatus for EN DreamPage-server.

Dette er det ENESTE endepunktet som er ment aa naa ut av maskinen, og derfor
er det skilt ut i sin egen fil: grensen for hva som slipper ut skal kunne
leses paa ett sted.

Hva som ALDRI er med her - og hvorfor det maatte vaere en egen modul:

    `/api/health` og `/api/queue` er bygget for operatoeren og inneholder
    `argv` (hele filsystemstier), `child_name`, `woo_order_id` og job_key.
    Det er kundedata og intern topologi. De endepunktene skal IKKE ut.
    Herfra kommer bare tall, tilstander og navn paa komponenter.

Konkret filter:
  * ingen job_key, ordrenummer, barnenavn, adresse eller boktittel
  * ingen filstier, ingen argv, ingen tokens, ingen vertsnavn utover
    maskinens eget
  * ingen prompt, ingen bilder, ingen payload

Lettvekt paa ordentlig: ett probe-resultat caches i CACHE_TTL sekunder og
deles av alle som spoer. Ti overvaakere som poller hvert sekund gir altsaa
ett HTTP-kall til ComfyUI hvert femte sekund - ikke ti i sekundet. Ingenting
her tar GPU, laster en modell eller leser en bok.

Flere servere: `server.id` er en UUID som ligger i state/server_id.json og
foelger maskinen, ikke vertsnavnet. Doeper du om PC-en beholder den samme
identitet i flaaten; to PC-er som tilfeldigvis heter det samme er fortsatt
to forskjellige servere. `server.label` og `server.role` settes i
config/flow.json og er det mennesker leser.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from paths import CONFIG, ROOT, STATE  # noqa: E402

# Hvor lenge et probe-resultat gjenbrukes. Overvaakning skal ikke kunne
# koste noe maalbart, uansett hvor ofte den spoer.
CACHE_TTL = 5.0
# Versjon endres bare ved en deploy, saa den kan caches lenge. `git describe`
# er en subprosess, og den vil vi ikke starte per forespoersel.
VERSION_TTL = 600.0

# Naar denne modulen importeres, starter prosessen. Godt nok som oppetid for
# API-et, og gratis.
_STARTED = time.time()

_lock = threading.Lock()
_cache: dict = {"at": 0.0, "value": None}
_version_cache: dict = {"at": 0.0, "value": None}
_server_cache: dict | None = None


# ---------------------------------------------------------------------------
# Serveridentitet
# ---------------------------------------------------------------------------
def _server_id() -> str:
    """Stabil UUID for denne maskinen, lagret i state/server_id.json.

    Vertsnavn er ikke identitet: det kan byttes, og i en flaate kan to
    maskiner ha samme navn. Fila skrives en gang og leses deretter.
    """
    path = STATE / "server_id.json"
    try:
        with open(path, encoding="utf-8-sig") as fh:
            value = json.load(fh).get("server_id")
        if value:
            return str(value)
    except (OSError, ValueError):
        pass
    value = str(uuid.uuid4())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"server_id": value,
                       "_": "Stabil identitet for denne DreamPage-serveren. "
                            "Ikke rediger, og ikke kopier til en annen maskin "
                            "- to servere med samme id er usynlige for "
                            "hverandre i flaatevisningen.",
                       "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
                      fh, indent=2)
    except OSError:
        pass
    return value


def _server_conf() -> dict:
    try:
        with open(CONFIG / "flow.json", encoding="utf-8-sig") as fh:
            block = json.load(fh).get("server") or {}
        return block if isinstance(block, dict) else {}
    except (OSError, ValueError):
        return {}


def server() -> dict:
    """Hvem er denne serveren. Uforanderlig gjennom prosessens levetid."""
    global _server_cache
    if _server_cache is None:
        conf = _server_conf()
        _server_cache = {
            "id": _server_id(),
            "hostname": socket.gethostname(),
            "label": str(conf.get("label") or socket.gethostname()),
            "role": str(conf.get("role") or "production"),
            "region": str(conf.get("region") or "") or None,
        }
    return dict(_server_cache)


# ---------------------------------------------------------------------------
# Versjon
# ---------------------------------------------------------------------------
def _version() -> dict:
    now = time.monotonic()
    if _version_cache["value"] is not None and now - _version_cache["at"] < VERSION_TTL:
        return _version_cache["value"]
    out = {"describe": None, "commit": None, "branch": None, "dirty": None}
    try:
        res = subprocess.run(
            ["git", "-C", str(ROOT), "describe", "--tags", "--always", "--dirty"],
            capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            out["describe"] = res.stdout.strip() or None
            out["dirty"] = out["describe"].endswith("-dirty") if out["describe"] else None
        res = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            out["commit"] = res.stdout.strip() or None
        res = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--abbrev-ref", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            out["branch"] = res.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        pass
    _version_cache.update(at=now, value=out)
    return out


def _uptime_s() -> dict:
    """Oppetid for API-prosessen og for maskinen.

    GetTickCount64 er et enkelt kall inn i kernel32 - ingen avhengighet, og
    billigere enn aa lese noe fra disk.
    """
    machine = None
    try:
        import ctypes
        machine = int(ctypes.windll.kernel32.GetTickCount64() // 1000)
    except (AttributeError, OSError):
        pass
    return {"api_s": int(time.time() - _STARTED), "machine_s": machine}


# ---------------------------------------------------------------------------
# Selve statusen
# ---------------------------------------------------------------------------
def _image(runner) -> tuple[dict, str]:
    """DreamPage-image (ComfyUI). Ett HTTP-kall, ingen GPU-bruk."""
    if runner is None:
        return {"status": "unknown",
                "note": "API-et kjoerer uten runner (--no-api-modus)"}, "degraded"
    try:
        identity = runner.comfy.identity()
    except Exception as exc:                            # noqa: BLE001
        # Typen, ikke teksten: en feilmelding fra urllib inneholder URL-en,
        # altsaa intern topologi.
        return {"status": "down", "reachable": False,
                "error": type(exc).__name__}, "down"

    stats = identity.get("stats") or {}
    system = stats.get("system") or {}
    devices = stats.get("devices") or []
    gpu = None
    if devices:
        d = devices[0]
        name = str(d.get("name") or "")
        # ComfyUI gir "cuda:0 NVIDIA GeForce RTX 3090 : cudaMallocAsync".
        # Vi vil ha modellnavnet: lengste kolon-delen, uten enhetsindeksen
        # som blir hengende igjen foran ("0 NVIDIA ..." -> "NVIDIA ...").
        if ":" in name:
            parts = [part.strip() for part in name.split(":") if part.strip()]
            if parts:
                name = max(parts, key=len)
        head, _, rest = name.partition(" ")
        if head.isdigit() and rest:
            name = rest
        total = d.get("vram_total") or 0
        free = d.get("vram_free") or 0
        gpu = {
            "name": name or None,
            "vram_total_mb": int(total // 2**20) if total else None,
            "vram_free_mb": int(free // 2**20) if free else None,
            "vram_used_pct": (round(100.0 * (total - free) / total, 1)
                              if total else None),
        }

    # "ours" er poenget: at NOE svarer paa porten beviser ingenting. En
    # ComfyUI fra en annen mappe, uten modeller, svarte 16.09.2026 - og et
    # naivt helsesjekk sa "ok" mens ingen side kunne bygges.
    ours = bool(identity.get("from_image"))
    models = identity.get("unet_models")
    ok = bool(identity.get("ok"))
    try:
        queue_depth = runner.comfy.queue_depth()
    except Exception:                                   # noqa: BLE001
        queue_depth = None

    out = {
        "status": "ok" if ok else "degraded",
        "reachable": True,
        "is_dreampage_image": ours,
        "version": system.get("comfyui_version"),
        "python": (system.get("python_version") or "").split()[0] or None,
        "torch": system.get("pytorch_version"),
        "models_visible": models,
        "queue_depth": queue_depth,
        "gpu": gpu,
    }
    if not ok:
        out["reason"] = ("svarer, men er ikke DreamPage-image"
                         if not ours else "ser ingen modeller")
    return out, out["status"]


def _flow(runner) -> tuple[dict, str]:
    if runner is None:
        return {"status": "down", "worker_alive": False}, "down"
    snap = runner.snapshot()
    alive = bool(snap.get("alive"))
    # `snap["running"]` er job_key og skal IKKE ut. Bare om noe kjoerer.
    busy = snap.get("running") is not None
    return ({
        "status": "ok" if alive else "down",
        "worker_alive": alive,
        "busy": busy,
        "current_step": snap.get("running_step") if busy else None,
        "running_seconds": snap.get("running_seconds") if busy else None,
        "internal_queue_depth": snap.get("internal_queue_depth"),
    }, "ok" if alive else "down")


def _queue(consumer, runner) -> tuple[dict, str]:
    if consumer is None:
        return ({"status": "disabled", "connected": False,
                 "note": "workeren kjoerer med --no-mq"}, "degraded")
    snap = consumer.snapshot()
    connected = bool(snap.get("connected"))
    try:
        depth = consumer.broker_depth()
    except Exception:                                   # noqa: BLE001
        depth = None
    return ({
        "status": "ok" if connected else "down",
        "connected": connected,
        "name": snap.get("queue"),
        "broker_depth": depth,
        "unacked": snap.get("unacked"),
        "prefetch": snap.get("prefetch"),
        "internal_depth": runner.depth() if runner is not None else None,
        # Feilteksten fra broker kan inneholde vertsnavn og bruker.
        "last_error": bool(snap.get("last_error")) or None,
    }, "ok" if connected else "down")


def _rollup(parts: list[str]) -> str:
    if "down" in parts:
        return "down"
    if "degraded" in parts or "unknown" in parts:
        return "degraded"
    return "ok"


def _build(runner, consumer, store) -> dict:
    image, s_image = _image(runner)
    flow, s_flow = _flow(runner)
    queue, s_queue = _queue(consumer, runner)

    counts = {}
    s_jobs = "ok"
    try:
        counts = store.count_by_status()
    except Exception:                                   # noqa: BLE001
        s_jobs = "degraded"

    overall = _rollup([s_image, s_flow, s_queue, s_jobs])
    return {
        "schema": 1,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "status": overall,
        "server": server(),
        "dreampage_os": {"status": overall, "version": _version(),
                         "uptime": _uptime_s()},
        "api": {"status": "ok", "uptime_s": _uptime_s()["api_s"]},
        "flow": flow,
        "image": image,
        "queue": queue,
        # Bare tall. Ingen job_key, ingen ordrenummer, ingen navn.
        "jobs": {
            "pending": counts.get("pending", 0),
            "running": counts.get("running", 0),
            "done": counts.get("done", 0),
            "failed": counts.get("failed", 0),
            "cancelled": counts.get("cancelled", 0),
        },
        "workload": {
            "busy": bool(flow.get("busy")),
            # Waiting = det som staar i broker pluss det workeren har tatt
            # inn men ikke startet. En flaatestyrer trenger begge for aa vite
            # hvor en ny jobb boer sendes.
            "waiting": (queue.get("broker_depth") or 0) + (queue.get("internal_depth") or 0),
            "accepting_jobs": bool(queue.get("connected") and flow.get("worker_alive")),
        },
        "checks": [
            {"name": "flow", "status": s_flow},
            {"name": "image", "status": s_image},
            {"name": "queue", "status": s_queue},
            {"name": "jobs_db", "status": s_jobs},
        ],
    }


def snapshot(runner=None, consumer=None, store=None) -> dict:
    """Full status, cachet i CACHE_TTL sekunder.

    Laasen gjoer at samtidige forespoersler deler ETT probe-resultat i stedet
    for aa lage ett hver.
    """
    now = time.monotonic()
    with _lock:
        cached = _cache["value"]
        if cached is not None and now - _cache["at"] < CACHE_TTL:
            return {**cached, "cached": True,
                    "cache_age_s": round(now - _cache["at"], 2)}
        value = _build(runner, consumer, store)
        _cache.update(at=now, value=value)
        return {**value, "cached": False, "cache_age_s": 0.0}


def summary(runner=None, consumer=None, store=None) -> dict:
    """Det minste som er nyttig: en linje per server i en flaatevisning.

    Bygget paa samme cache som snapshot(), saa den koster ingenting ekstra.
    """
    full = snapshot(runner, consumer, store)
    return {
        "schema": 1,
        "at": full["at"],
        "server_id": full["server"]["id"],
        "label": full["server"]["label"],
        "hostname": full["server"]["hostname"],
        "role": full["server"]["role"],
        "status": full["status"],
        "busy": full["workload"]["busy"],
        "waiting": full["workload"]["waiting"],
        "accepting_jobs": full["workload"]["accepting_jobs"],
        "running": full["jobs"]["running"],
        "pending": full["jobs"]["pending"],
        "failed": full["jobs"]["failed"],
        "version": full["dreampage_os"]["version"]["describe"],
        "uptime_s": full["api"]["uptime_s"],
        "cached": full["cached"],
    }

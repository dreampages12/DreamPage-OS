# -*- coding: utf-8 -*-
"""Kommandolinja n8n kaller - flow som ÉN node.

Fase 2 bytter ut hele side-loekka (27 noder: Page Loop, Build Page Prompt,
HTTP Request ComfyUI, Init Poll, Get History, Parse History, If Error, Done
Check, Inc Tries, If Timed Out, Poll Wait, Check Page Output, Page Already
Done?, Fail Comfy Page, All Pages Done - pluss de fem laasenodene) med ett
`executeCommand`-kall, paa samme maate som workflowen alt kaller
"Run Text Script".

    python flow/worker/cli.py render --payload <fil.json>
    python flow/worker/cli.py render --job-key 1515      # payload fra state
    python flow/worker/cli.py status --job-key 1515
    python flow/worker/cli.py pipeline

Svaret er ÉN linje paa stdout, prefikset med en markoer, slik gelato_merge.py
alt gjoer mot n8n:

    DPFLOW_JSON {"status": "done", "job_key": "1515", "pages": 17, ...}

Alt annet - logg, fremdrift, feil - gaar til stderr. Da kan n8n lese svaret
med en JSON.parse av siste linje uten aa bli forstyrret av loggingen.

Kommandoen SENDER jobben til den kjoerende workeren hvis den svarer, og
venter. Er workeren nede, kjoerer den jobben selv i denne prosessen - men da
er serialiseringen borte, saa den nekter hvis ComfyUI-koen ikke er tom.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

from paths import CONFIG, order_state_path  # noqa: E402
import config as flow_config  # noqa: E402

MARKER = "DPFLOW_JSON"


def emit(payload: dict) -> int:
    """Eneste kanal ut til n8n. Alltid ASCII, alltid én linje."""
    print(MARKER + " " + json.dumps(payload, ensure_ascii=True))
    return 0 if payload.get("status") == "done" else 1


def note(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# API-klient
# ---------------------------------------------------------------------------
def _api_base() -> str:
    conf = flow_config.api()
    return f"http://{conf['host']}:{conf['port']}"


def _api_token() -> str:
    try:
        with open(CONFIG / "api.json", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return ""
    if isinstance(data.get("tokens"), dict) and data["tokens"]:
        # Foerste token holder; CLI-en er lokal og skal bare identifisere seg.
        return next(iter(data["tokens"]))
    return str(data.get("token") or "")


def _api(method: str, path: str, body: dict | None = None, timeout: float = 30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(_api_base() + path, data=data, method=method,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {_api_token()}"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8", "replace") or "{}")


def _worker_alive() -> bool:
    try:
        _api("GET", "/api/health", timeout=8)
        return True
    except Exception:                                # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# payload
# ---------------------------------------------------------------------------
def load_payload(args) -> dict:
    if args.payload:
        with open(args.payload, encoding="utf-8-sig") as fh:
            data = json.load(fh)
        # n8n sender av og til hele meldingen med `content` som streng.
        if isinstance(data.get("content"), str):
            data = json.loads(data["content"])
        return data
    if args.payload_stdin:
        return json.loads(sys.stdin.read())
    if args.job_key:
        path = order_state_path(args.job_key)
        if not path.is_file():
            raise SystemExit(f"fant ingen payload for {args.job_key} ({path})")
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)["payload"]
    raise SystemExit("oppgi --payload, --payload-stdin eller --job-key")


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------
def cmd_render(args) -> int:
    payload = load_payload(args)
    job_key = str(payload.get("job_key") or payload.get("order_id") or "").strip()
    if not job_key:
        return emit({"status": "failed",
                     "error": "payloaden mangler baade job_key og order_id"})

    if _worker_alive():
        return _render_via_worker(job_key, payload, args)
    return _render_locally(job_key, payload, args)


def _render_via_worker(job_key: str, payload: dict, args) -> int:
    """Normalveien: legg jobben paa workerens interne koe og vent.

    Det er DENNE veien som gjoer at to ordre samtidig kjoerer etter hverandre.
    Selv om n8n starter to executions parallelt, havner begge jobbene i den
    samme koeen i den samme prosessen.
    """
    note(f"[flow] sender {job_key} til workeren paa {_api_base()}")
    res = _api("POST", "/api/jobs", payload)
    if not res.get("accepted"):
        state = res.get("status")
        note(f"[flow] {job_key}: {res.get('reason')}")
        if state == "done":
            # Ordren er alt bygget. Det er et gyldig svar, ikke en feil - det
            # er hele poenget med at samme ordre kan komme to ganger.
            job = _api("GET", f"/api/jobs/{job_key}?log_lines=0")
            return emit({"status": "done", "job_key": job_key,
                         "pages": job.get("progress", {}).get("done"),
                         "already_done": True})
        return emit({"status": "failed", "job_key": job_key,
                     "error": res.get("reason"), "state": state})

    position = res.get("position")
    if position and position > 1:
        note(f"[flow] {job_key} staar som nr {position} i koeen - venter")

    last_step = last_done = None
    deadline = time.monotonic() + args.wait_timeout
    while time.monotonic() < deadline:
        time.sleep(args.poll)
        try:
            job = _api("GET", f"/api/jobs/{job_key}?log_lines=0")
        except Exception as exc:                     # noqa: BLE001
            note(f"[flow] kunne ikke lese status: {exc}")
            continue

        step = job.get("step")
        done = (job.get("progress") or {}).get("done")
        if (step, done) != (last_step, last_done):
            total = (job.get("progress") or {}).get("total")
            note(f"[flow] {job_key}: {step or '-'}"
                 + (f"  {done}/{total} sider" if total else ""))
            last_step, last_done = step, done

        if job["status"] == "done":
            return emit({"status": "done", "job_key": job_key,
                         "pages": done,
                         "book_slug": job.get("book_slug"),
                         "seconds": _seconds(job)})
        if job["status"] in ("failed", "cancelled"):
            return emit({"status": job["status"], "job_key": job_key,
                         "error": job.get("error"),
                         "step": _failed_step(job),
                         "pages": done, "permanent": job.get("permanent")})

    return emit({"status": "failed", "job_key": job_key,
                 "error": f"ventet {args.wait_timeout} s uten at jobben ble ferdig. "
                          f"Den kjoerer sannsynligvis fortsatt - se "
                          f"GET /api/jobs/{job_key}"})


def _render_locally(job_key: str, payload: dict, args) -> int:
    """Nødløsning naar workeren ikke kjoerer.

    Da finnes ikke den interne koeen, og to samtidige kall ville kjoert mot
    ComfyUI samtidig - noeyaktig det som gikk galt 14.09.2026. Derfor nekter
    den hvis ComfyUI har noe i koeen: det er et tegn paa at noen andre
    allerede jobber.
    """
    note("[flow] workeren svarer ikke - kjoerer jobben i denne prosessen")
    import comfy as comfy_mod
    import jobs as jobs_mod
    from runner import QueuedJob, Runner

    client = comfy_mod.Comfy()
    if not client.alive():
        return emit({"status": "failed", "job_key": job_key,
                     "error": f"verken flow-workeren eller ComfyUI "
                              f"({flow_config.comfy()['url']}) svarer"})
    depth = client.queue_depth()
    if depth and not args.force:
        return emit({"status": "failed", "job_key": job_key,
                     "error": f"ComfyUI har {depth} jobber i koeen, og "
                              f"flow-workeren kjoerer ikke. To ordre mot "
                              f"ComfyUI samtidig stjeler hverandres sider - "
                              f"start workeren, eller bruk --force hvis du vet "
                              f"at koeen er din egen."})

    store = jobs_mod.store()
    store.enqueue(job_key, payload)
    runner = Runner(store)
    result = runner.run_job(QueuedJob(job_key, payload))
    job = store.job(job_key) or {}
    return emit({"status": result["status"], "job_key": job_key,
                 "error": result.get("error"),
                 "pages": (job.get("progress_done") or 0),
                 "book_slug": job.get("book_slug"),
                 "local": True})


def _seconds(job: dict):
    a, b = job.get("started_at"), job.get("finished_at")
    if not (a and b):
        return None
    from datetime import datetime
    try:
        return round((datetime.fromisoformat(b) - datetime.fromisoformat(a))
                     .total_seconds(), 1)
    except ValueError:
        return None


def _failed_step(job: dict):
    for step in reversed(job.get("steps") or []):
        if step.get("status") == "failed":
            return step.get("name")
    return None


# ---------------------------------------------------------------------------
# status / pipeline
# ---------------------------------------------------------------------------
def cmd_status(args) -> int:
    import jobs as jobs_mod
    job = jobs_mod.store().job(args.job_key)
    if job is None:
        note(f"ingen jobb med job_key {args.job_key!r}")
        return 1
    note(f"{job['job_key']}  {job['status']}  bok={job['book_slug']}  "
         f"barn={job['child_name']}  forsoek={job['attempt']}")
    note(f"   koelagt  {job['queued_at']}")
    note(f"   startet  {job['started_at']}")
    note(f"   ferdig   {job['finished_at']}")
    if job.get("error"):
        note(f"   FEIL     {job['error']}")
    note("")
    for step in job.get("steps", []):
        note(f"   {step['name']:<20} {step['status']:<8} "
             f"{(step['seconds'] or 0):>8.1f}s  {step['error'] or ''}")
    return 0


def cmd_pipeline(args) -> int:
    import pipeline as pipeline_mod
    print(json.dumps(pipeline_mod.describe_all(), ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("render", help="bygg sidene for en ordre")
    r.add_argument("--payload", help="JSON-fil med jobb-payloaden")
    r.add_argument("--payload-stdin", action="store_true")
    r.add_argument("--job-key", help="hent payloaden fra state/orders/")
    r.add_argument("--poll", type=float, default=5,
                   help="sekunder mellom statussjekkene (standard 5)")
    r.add_argument("--wait-timeout", type=float, default=14 * 3600,
                   help="hvor lenge vi venter paa at jobben blir ferdig")
    r.add_argument("--force", action="store_true",
                   help="kjoer lokalt selv om ComfyUI-koen ikke er tom")
    r.set_defaults(func=cmd_render)

    s = sub.add_parser("status", help="hvor stoppet ordren, og hvorfor")
    s.add_argument("--job-key", required=True)
    s.set_defaults(func=cmd_status)

    p = sub.add_parser("pipeline", help="pipelinen som JSON")
    p.set_defaults(func=cmd_pipeline)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

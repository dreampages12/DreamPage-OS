# -*- coding: utf-8 -*-
"""Roeyktest: gaar en jobb gjennom RabbitMQ, og kjoerer flere én om gangen?

To spoersmaal, og bare det andre er interessant:

  1. Naar noen legger en jobb paa `dreampage-jobs`, plukker flow den opp,
     kjoerer den gjennom pipelinen og acker meldingen?
  2. Legger man flere samtidig, kjoerer de ETTER HVERANDRE - aldri parallelt
     mot ComfyUI?

Spoersmaal 2 er hele grunnen til at flow finnes. Det er alt bevist i
flow/worker/tests/test_flow.py med en falsk ComfyUI, men det beviser koden.
Dette beviser maskinen: ekte RabbitMQ, ekte ComfyUI, ekte GPU.

Hvordan det gjoeres trygt:

  * Egne job_keys (SMOKE-1, SMOKE-2, ...) saa ingen kundeordre roeres.
  * Alle sider UNNTATT én legges ferdig paa disk foerst, saa hver jobb rendrer
    noeyaktig én ekte side. Det gir maalbar varighet uten aa brenne en halv
    time GPU.
  * Pipelinen "pages" stopper etter sidene. Ingen PDF, ingen Drive, ingen
    Gelato, ingen Telegram. Ingenting forlater maskinen.

    python tools/smoke_test.py --jobs 3
    python tools/smoke_test.py --jobs 1 --render-pages 0   # uten GPU
    python tools/smoke_test.py --cleanup
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(os.environ.get("DP_ROOT") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(ROOT / "flow"))
sys.path.insert(0, str(ROOT / "flow" / "worker"))

PREFIX = "SMOKE-"
DUMMY_PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 512)


def api(path: str, method: str = "GET", body: dict | None = None):
    with open(ROOT / "config" / "api.json", encoding="utf-8-sig") as fh:
        conf = json.load(fh)
    token = next(iter(conf.get("tokens") or {}), None) or conf.get("token")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        "http://127.0.0.1:8765" + path, data=data, method=method,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode("utf-8", "replace") or "{}")


def source_order(slug: str) -> dict:
    """En ekte, ferdig ordre av samme bok - for payloadform og barnebilde."""
    import dp_order
    for path in sorted((ROOT / "state" / "orders").glob("*.json"), reverse=True):
        if path.stem.startswith(PREFIX) or path.stem.startswith("_"):
            continue
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        payload = rec.get("payload") or {}
        if not payload:
            continue
        try:
            if dp_order.resolve_slug(path.stem, payload) == slug:
                return {"job_key": path.stem, "payload": payload}
        except SystemExit:
            continue
    raise SystemExit(f"fant ingen ferdig ordre av {slug} aa laane payloadform fra")


def prepare(job_key: str, slug: str, payload: dict, render_pages: int) -> dict:
    """Legg barnebildet og de ferdige sidene paa plass."""
    import books
    job = books.build_job({**payload, "job_key": job_key, "order_id": job_key})
    pages = [p["page_key"] for p in books.build_pages(job) if not p.get("skipped")]

    # barnebildet
    src = ROOT / "input" / f"{payload.get('job_key') or payload.get('order_id')}.jpg"
    dst = ROOT / "input" / f"{job_key}.jpg"
    if not src.is_file():
        raise SystemExit(f"fant ikke barnebildet {src}")
    shutil.copy2(src, dst)

    # sidene: alle unntatt de siste `render_pages`
    out = books.comfy_output_dir(job)
    out.mkdir(parents=True, exist_ok=True)
    prefilled = pages[:len(pages) - render_pages] if render_pages else pages
    for key in prefilled:
        (out / f"{key}_00001_.png").write_bytes(DUMMY_PNG)

    return {"job_key": job_key, "book_slug": slug, "pages": len(pages),
            "prefilled": len(prefilled), "to_render": len(pages) - len(prefilled),
            "output_dir": str(out)}


def publish(payloads: list[dict]) -> None:
    """Legg jobbene paa koen. Samtidig, med vilje."""
    import dp_secrets
    import pika
    cred = dp_secrets.get("rabbitmq") or {}
    params = pika.ConnectionParameters(
        host=cred["hostname"], port=int(cred.get("port") or 5672),
        virtual_host=cred.get("vhost") or "/",
        credentials=pika.PlainCredentials(cred["username"], cred["password"]),
        socket_timeout=15, blocked_connection_timeout=15)
    con = pika.BlockingConnection(params)
    try:
        ch = con.channel()
        ch.queue_declare(queue="dreampage-jobs", passive=True)
        for payload in payloads:
            ch.basic_publish(
                exchange="", routing_key="dreampage-jobs",
                body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                properties=pika.BasicProperties(delivery_mode=2))
            print(f"  publisert {payload['job_key']}")
    finally:
        con.close()


def watch(job_keys: list[str], timeout: float) -> dict:
    """Foelg jobbene, og noter naar hver av dem var den som kjoerte."""
    deadline = time.time() + timeout
    seen_running: list[tuple[float, str | None, str | None]] = []
    last = None
    while time.time() < deadline:
        health = api("/api/health")
        worker = health.get("worker") or {}
        now = (worker.get("running"), worker.get("running_step"))
        if now != last:
            seen_running.append((time.time(), now[0], now[1]))
            if now[0]:
                print(f"    kjoerer: {now[0]}  steg={now[1]}")
            last = now

        jobs = {k: api(f"/api/jobs/{k}?log_lines=0") for k in job_keys
                if _exists(k)}
        if jobs and all(j["status"] in ("done", "failed", "cancelled")
                        for j in jobs.values()) and len(jobs) == len(job_keys):
            return {"jobs": jobs, "timeline": seen_running}
        time.sleep(2)
    return {"jobs": {k: api(f"/api/jobs/{k}?log_lines=0") for k in job_keys
                     if _exists(k)},
            "timeline": seen_running, "timeout": True}


def _exists(job_key: str) -> bool:
    try:
        api(f"/api/jobs/{job_key}?log_lines=0")
        return True
    except Exception:                                # noqa: BLE001
        return False


def overlaps(jobs: dict) -> list[tuple[str, str]]:
    """Par av jobber som var i gang samtidig. Skal vaere tomt."""
    spans = []
    for key, job in jobs.items():
        a, b = job.get("started_at"), job.get("finished_at")
        if not (a and b):
            continue
        spans.append((key, datetime.fromisoformat(a), datetime.fromisoformat(b)))
    bad = []
    for i in range(len(spans)):
        for j in range(i + 1, len(spans)):
            k1, s1, e1 = spans[i]
            k2, s2, e2 = spans[j]
            # Overlapp bare hvis begge STREKKER seg inn i den andre. To jobber
            # som deler ett sekund fordi den ene sluttet da den andre startet
            # er ikke parallellitet - tidsstemplene har sekundoppløsning.
            if s1 < e2 and s2 < e1 and (min(e1, e2) - max(s1, s2)).total_seconds() > 1:
                bad.append((k1, k2))
    return bad


def cleanup() -> int:
    import books
    import jobs as jobs_mod
    print("=== rydder ===")
    removed = 0
    for path in sorted((ROOT / "state" / "orders").glob(f"{PREFIX}*.json")):
        path.unlink(); removed += 1; print(f"  {path.name}")
    for path in sorted((ROOT / "input").glob(f"{PREFIX}*.jpg")):
        path.unlink(); removed += 1; print(f"  input/{path.name}")
    for base in (ROOT / "books", ROOT / "output"):
        for path in base.glob(f"*/orders/{PREFIX}*"):
            shutil.rmtree(path, ignore_errors=True); removed += 1
            print(f"  {path.relative_to(ROOT)}")
    for path in (ROOT / "state" / "log" / "jobs").glob(f"{PREFIX}*.log"):
        path.unlink(); removed += 1; print(f"  logg/{path.name}")
    store = jobs_mod.store()
    with store._write_lock:                          # noqa: SLF001
        con = store._conn()                          # noqa: SLF001
        for table in ("steps", "events", "actions", "jobs"):
            con.execute(f"DELETE FROM {table} WHERE job_key LIKE ?", (f"{PREFIX}%",))
    print(f"  jobb-DB: SMOKE-rader slettet")
    print(f"\n{removed} filer/mapper fjernet")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--book", default="den-skjulte-styrken",
                    help="bok som IKKE har uttrykksvarianter, saa testen ikke "
                         "drar med seg en ekstra ComfyUI-render")
    ap.add_argument("--render-pages", type=int, default=1,
                    help="hvor mange ekte sider hver jobb skal rendre")
    ap.add_argument("--timeout", type=float, default=1800)
    ap.add_argument("--cleanup", action="store_true")
    args = ap.parse_args()

    if args.cleanup:
        return cleanup()

    print("=== forhaandssjekk ===")
    health = api("/api/health")
    print(f"  flow      : worker alive={health['worker']['alive']}")
    print(f"  ComfyUI   : {health['comfy']['url']} ok={health['comfy']['ok']}")
    print(f"  RabbitMQ  : tilkoblet={health['rabbitmq']['connected']} "
          f"prefetch={health['rabbitmq']['prefetch']} "
          f"koe={health['rabbitmq']['broker_depth']}")
    if not health["rabbitmq"]["connected"]:
        raise SystemExit("flow er ikke koblet til RabbitMQ")
    if health["worker"].get("running"):
        raise SystemExit(f"flow bygger alt ordre {health['worker']['running']} "
                         f"- vent til den er ferdig")

    src = source_order(args.book)
    print(f"  laaner payloadform fra ordre {src['job_key']}")

    print("\n=== forbereder ===")
    payloads = []
    for i in range(1, args.jobs + 1):
        key = f"{PREFIX}{i}"
        info = prepare(key, args.book, src["payload"], args.render_pages)
        print(f"  {key}: {info['pages']} sider, {info['prefilled']} ferdige, "
              f"{info['to_render']} skal rendres")
        payloads.append({**src["payload"], "job_key": key, "order_id": key})

    print(f"\n=== publiserer {len(payloads)} jobber samtidig ===")
    t0 = time.time()
    publish(payloads)

    print("\n=== foelger ===")
    result = watch([p["job_key"] for p in payloads], args.timeout)
    elapsed = time.time() - t0

    print(f"\n=== resultat ({elapsed:.0f} s) ===")
    order = []
    for key, job in sorted(result["jobs"].items(),
                           key=lambda kv: kv[1].get("started_at") or ""):
        order.append(key)
        secs = ""
        if job.get("started_at") and job.get("finished_at"):
            secs = (f"{(datetime.fromisoformat(job['finished_at']) - datetime.fromisoformat(job['started_at'])).total_seconds():.0f} s")
        print(f"  {key:<10} {job['status']:<8} {job['progress']['done']}/"
              f"{job['progress']['total']} sider  {secs:>7}  "
              f"{job.get('started_at','')[11:19]} -> {job.get('finished_at','')[11:19]}"
              + (f"   FEIL: {job['error']}" if job.get("error") else ""))

    bad = overlaps(result["jobs"])
    failed = [k for k, j in result["jobs"].items() if j["status"] != "done"]
    depth = api("/api/health")["rabbitmq"]["broker_depth"]

    print()
    print(f"  rekkefoelge      : {' -> '.join(order)}")
    print(f"  alle ferdige     : {'JA' if not failed else 'NEI: ' + ', '.join(failed)}")
    print(f"  overlapp         : {'INGEN - kjoerte etter hverandre' if not bad else 'FANT: ' + str(bad)}")
    print(f"  koen drenert     : {'JA' if depth == 0 else f'NEI, {depth} igjen'}")

    ok = not failed and not bad and depth == 0 and not result.get("timeout")
    print(f"\n  {'ROEYKTEST BESTAATT' if ok else 'ROEYKTEST FEILET'}")
    print(f"\n  rydd opp med:  python tools/smoke_test.py --cleanup")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

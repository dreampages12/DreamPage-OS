# -*- coding: utf-8 -*-
"""Workeren: RabbitMQ-konsument + intern koe + REST-API i én prosess.

    python flow/worker/main.py
    python flow/worker/main.py --no-mq        # bare API-et (nyttig i test)
    python flow/worker/main.py --no-api

Én prosess, fordi det er det som fjerner laasen: den interne koeen kan bare
serialisere det den selv eier. API-et kjoerer i samme prosess og leser samme
jobb-DB, saa det finnes ikke to kopier av tilstanden.

Prosessen snakker med ComfyUI over HTTP og deler IKKE prosess med den.
ComfyUI restartes jevnlig - nye custom nodes, VRAM, oppdateringer - og delt
prosess ville gjort dagens bug permanent.
"""
from __future__ import annotations

import argparse
import signal
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as flow_config  # noqa: E402
import jobs as jobs_mod  # noqa: E402
from log import Log  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-mq", action="store_true",
                    help="ikke koble til RabbitMQ (API + intern koe alene)")
    ap.add_argument("--no-api", action="store_true", help="ikke start API-et")
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args()

    conf = flow_config.load()
    log = Log(None, conf["log"]["level"])

    # Modusen valideres FOERST, foer noe startes. En skrivefeil i "mode" skal
    # stoppe prosessen her, ikke bli til "da tar vi book" - en preview-PC som
    # stille koblet seg paa `dreampage-jobs` ville plukket opp ekte, betalte
    # bokordre og kjoert dem gjennom en pipeline som ikke bygger boeker.
    try:
        mode = flow_config.mode()
        queue_name = flow_config.queue()["name"]
        import pipeline as pipeline_mod
        pipeline_name = pipeline_mod.active_name()
    except (ValueError, KeyError) as exc:
        print(f"[flow] {exc}", file=sys.stderr)
        return 2

    store = jobs_mod.store()
    log.info("flow starter", modus=mode, koe=queue_name, pipeline=pipeline_name,
             root=str(Path(__file__).resolve().parent.parent.parent),
             comfy=conf["comfy"]["url"], db=str(store.path))

    from runner import Runner
    runner = Runner(store)
    runner.start()

    consumer = None
    if not args.no_mq:
        from mq import Consumer
        consumer = Consumer(runner, store)
        consumer.start()

    stopping = threading.Event()

    def shutdown(signum=None, frame=None):
        if stopping.is_set():
            return
        stopping.set()
        log.info("stopper...", signal=signum)
        if consumer is not None:
            # Konsumenten foerst: da slutter nye jobber aa komme inn mens den
            # som kjoerer faar gjoere seg ferdig.
            consumer.stop()
        runner.stop()
        log.info("stoppet")

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, shutdown)
        except (ValueError, OSError):
            pass

    if args.no_api:
        try:
            stopping.wait()
        except KeyboardInterrupt:
            shutdown()
        return 0

    import uvicorn
    from api import create_app
    app = create_app(runner, consumer)
    api_conf = conf["api"]
    port = args.port or api_conf["port"]

    # Status-lytteren, i en egen traad i SAMME prosess. Egen prosess ville
    # betydd en ny kopi av jobb-DB-handtaket og en ny ting for watchdogen aa
    # passe paa; her deler den runner/consumer/store med API-et og svarer fra
    # den samme 5-sekunders cachen, saa polling utenfra koster ingenting.
    #
    # Den har BARE /api/status* i seg - det er hele poenget, se status_api.py.
    status_port = api_conf.get("status_port")
    if status_port:
        from status_api import create_status_app
        status_app = create_status_app(runner, consumer)
        status_conf = uvicorn.Config(
            status_app, host=api_conf.get("status_host") or "127.0.0.1",
            port=int(status_port), log_level="warning", access_log=False)
        status_server = uvicorn.Server(status_conf)
        threading.Thread(target=status_server.run, name="status-api",
                         daemon=True).start()
        log.info("status-API lytter", host=status_conf.host,
                 port=status_conf.port, ruter="/api/status*")

    # Det fulle API-et paa tailnett-adressen, for kontrollpanelet paa en annen
    # maskin. Det trenger POST og det trenger koeen, saa det kan ikke bruke
    # statusporten - og 8765 skal aldri vaere offentlig. Tailnettet er den
    # tredje veien: ikke localhost, ikke internett.
    #
    # Feiler bindingen (Tailscale nede, adressen byttet), logger vi og gaar
    # videre. Ordreflyten gaar over RabbitMQ og er ikke avhengig av dette -
    # en worker som ikke starter fordi et panel ikke naas, er en verre feil.
    if api_conf.get("tailnet"):
        import net as net_mod
        ts_ips = net_mod.tailscale_ips()
        if not ts_ips:
            log.warn("tailnet er paa, men fant ingen 100.64.0.0/10-adresse "
                     "- er Tailscale nede? API-et svarer bare paa localhost")
        for ts_ip in ts_ips:
            try:
                ts_conf = uvicorn.Config(app, host=ts_ip, port=port,
                                         log_level="warning", access_log=False)
                ts_server = uvicorn.Server(ts_conf)
                threading.Thread(target=ts_server.run,
                                 name=f"api-tailnet-{ts_ip}",
                                 daemon=True).start()
                log.info("API lytter ogsaa paa tailnettet",
                         host=ts_ip, port=port)
            except OSError as exc:
                log.warn("kunne ikke binde til tailnett-adressen",
                         host=ts_ip, feil=str(exc))

    log.info("API lytter", host=api_conf["host"], port=port)
    try:
        uvicorn.run(app, host=api_conf["host"], port=port,
                    log_level="warning", access_log=False)
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())

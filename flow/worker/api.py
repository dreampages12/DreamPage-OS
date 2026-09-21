# -*- coding: utf-8 -*-
"""REST-API-et admin-dashbordet spoer.

Kjoerer I worker-prosessen og leser SAMME jobb-DB som runneren skriver til.
Det finnes ingen andre kopi av tilstanden - det er derfor /api/queue kan si
hva som kjoerer akkurat naa, ikke hva som kjoerte sist noen synkroniserte.

Krav som er oppfylt her, og hvorfor de staar slik:

  * Auth paa ALT, ogsaa /api/health. Et helseendepunkt uten auth forteller en
    fremmed at maskinen finnes, hvilken ComfyUI-versjon den kjoerer og hvor
    mange ordre som staar i koen.
  * GET leser. Alt som endrer noe er POST, og skrives til `actions` med hvem
    og naar. Forskjellen paa en retry en operatoer ba om og en retry systemet
    tok selv er verdt aa kunne se i ettertid.
  * Stabile feltnavn, ISO-tidsstempler med sone, og en eksplisitt status-enum
    (pending/running/done/failed/cancelled). Dashbordet skal ikke gjette.
  * CORS bare mot dashbordets origin. Aldri "*".
  * Rate limiting paa skrive-endepunktene.

Tunnelen er transport, ikke autentisering. Bearer-tokenet kreves uansett hvor
kallet kommer fra.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import deque
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from paths import BOOKS, CONFIG, PANEL, TEXT  # noqa: E402
import config as flow_config  # noqa: E402
import jobs as jobs_mod  # noqa: E402
import pipeline as pipeline_mod  # noqa: E402
import status as status_mod  # noqa: E402
from log import job_log_lines  # noqa: E402

API_CONFIG_PATH = CONFIG / "api.json"
_bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
# Rettigheter. "full" naar alt; "status" naar BARE /api/status*.
#
# Grunnen til at dette finnes: /api/status er det eneste endepunktet som er
# ment aa naa ut av maskinen. /api/jobs og /api/queue inneholder barnenavn og
# ordrenummer, og /api/health inneholder hele filsystemstier. Et
# overvaakingssystem som skal se om serveren lever, skal ikke kunne lese noe
# av det - og hvis dets token laekker, skal det ikke vaere en kundedatalekkasje.
SCOPE_FULL = "full"
SCOPE_STATUS = "status"


def _tokens() -> dict:
    """{token: {"name": ..., "scope": ...}}. config/api.json staar i .gitignore.

    Navnet er hvem-feltet i handlingsloggen, saa dashbordet og en operatoer
    med curl kan skilles fra hverandre i ettertid.

    To former godtas, og den gamle betyr fortsatt det samme:
        "tokens": {"<token>": "dashbord"}                      -> full
        "tokens": {"<token>": {"name": "flaate", "scope": "status"}}
    Et token uten scope er "full" - ellers ville en oppgradering av denne
    filen stille tatt fra dashbordet tilgangen det hadde i gaar.
    """
    try:
        with open(API_CONFIG_PATH, encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}
    raw = data.get("tokens")
    if not isinstance(raw, dict):
        raw = ({str(data["token"]): str(data.get("name") or "dashboard")}
               if data.get("token") else {})
    out = {}
    for token, value in raw.items():
        if isinstance(value, dict):
            scope = str(value.get("scope") or SCOPE_FULL).lower()
            name = str(value.get("name") or "ukjent")
        else:
            scope, name = SCOPE_FULL, str(value)
        if scope not in (SCOPE_FULL, SCOPE_STATUS):
            # Ukjent scope er ikke "alt lov". Snevreste rettighet vinner.
            scope = SCOPE_STATUS
        out[str(token)] = {"name": name, "scope": scope}
    return out


def _cors_origins() -> list[str]:
    try:
        with open(API_CONFIG_PATH, encoding="utf-8-sig") as fh:
            data = json.load(fh)
        if data.get("cors_origins"):
            return [str(o) for o in data["cors_origins"]]
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return list(flow_config.api()["cors_origins"])


# Origins paa tailnettet. Kontrollpanelet kjoerer paa en annen maskin, og vi
# vet ikke hvilken port det bruker - derfor et moenster i stedet for en liste.
#
# Hva som matcher:
#   http://100.78.242.12:3000        tailnett-IP (RFC 6598, 100.64-100.127)
#   http://dreampage-01:8080         MagicDNS-kortnavn
#   https://dreampage-01.tail1234.ts.net
#
# Hva som IKKE matcher: 192.168.x (hjemmenettet), alt offentlig, og "*".
#
# Merk hva som egentlig beskytter API-et: bearer-tokenet, og at porten bare
# er bundet til localhost + tailnett-adressen (worker/net.py). CORS er en
# nettleserregel, ikke en grense - en angriper med curl bryr seg ikke om den.
# Dette moensteret er derfor bekvemmelighet for panelet, ikke sikkerheten.
_TAILNET_ORIGIN = (
    r"https?://("
    r"100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}"   # tailnett-IP
    r"|(?:[A-Za-z0-9-]+\.)+ts\.net"                                  # MagicDNS
    r"|[A-Za-z0-9-]+"                                                # kortnavn
    r")(:\d{1,5})?$"
)


def _cors_origin_regex() -> str | None:
    """None naar tailnet er av, saa oppsettet ikke endres for andre servere."""
    if not flow_config.api().get("tailnet"):
        return None
    return _TAILNET_ORIGIN


def _authenticate(creds: HTTPAuthorizationCredentials | None) -> dict:
    tokens = _tokens()
    if not tokens:
        # Ingen tokens konfigurert betyr ikke "aapent for alle". Det betyr at
        # API-et ikke er satt opp, og da skal det ikke svare paa noe.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "API-et har ingen tokens. Lag config/api.json "
                            "(se api.example.json).")
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "mangler Authorization: Bearer <token>",
                            headers={"WWW-Authenticate": "Bearer"})
    entry = tokens.get(creds.credentials)
    if not entry:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "ukjent token")
    return entry


def caller(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    """Full tilgang. Alt som kan se kundedata henger paa denne."""
    entry = _authenticate(creds)
    if entry["scope"] != SCOPE_FULL:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "dette tokenet har bare tilgang til /api/status")
    return entry["name"]


def status_caller(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    """Statusendepunktene. Bade "full" og "status" slipper inn."""
    return _authenticate(creds)["name"]


# ---------------------------------------------------------------------------
# Rate limiting paa skriving
# ---------------------------------------------------------------------------
_hits: dict[str, deque] = {}


def rate_limit(request: Request, who: str = Depends(caller)) -> str:
    limit = int(flow_config.api().get("rate_limit_per_minute") or 30)
    key = f"{who}:{request.client.host if request.client else '?'}"
    window = _hits.setdefault(key, deque())
    now = time.monotonic()
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"maks {limit} skrivekall per minutt")
    window.append(now)
    return who


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
def create_app(runner=None, consumer=None) -> FastAPI:
    app = FastAPI(title="DreamPage flow", version="1.0",
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_origin_regex=_cors_origin_regex(),
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    store = jobs_mod.store()

    def _job_public(row: dict) -> dict:
        """Ett stabilt skjema for en jobb. Dashbordet leser disse navnene."""
        return {
            "job_key": row["job_key"],
            "order_id": row.get("woo_order_id") or None,
            "book_slug": row.get("book_slug") or None,
            "child_name": row.get("child_name") or None,
            "status": row["status"],
            "step": row.get("step"),
            "attempt": row.get("attempt"),
            "progress": {"done": row.get("progress_done") or 0,
                         "total": row.get("progress_total") or 0},
            "queued_at": row.get("queued_at"),
            "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
            "error": row.get("error"),
        }

    # -- status: det ENESTE som er ment aa naa ut av maskinen -------------
    #
    # Lettvekt og lese-only. Alt caches i status.CACHE_TTL sekunder, saa en
    # flaatevisning kan polle saa ofte den vil uten aa koste GPU, disk eller
    # en ComfyUI-forespoersel per kall. Ingen job_key, ingen ordrenummer,
    # ingen navn, ingen filstier - se flow/worker/status.py for filteret.
    @app.get("/api/status")
    def status_full(who: str = Depends(status_caller)):
        return status_mod.snapshot(runner, consumer, store)

    @app.get("/api/status/summary")
    def status_summary(who: str = Depends(status_caller)):
        """En linje per server. Bruk denne naar du poller mange maskiner."""
        return status_mod.summary(runner, consumer, store)

    @app.get("/api/status/id")
    def status_id(who: str = Depends(status_caller)):
        """Hvem er dette. Ingen probing i det hele tatt - svarer fra minne."""
        return {"schema": 1, "at": jobs_mod.now(), "server": status_mod.server()}

    # -- helse ------------------------------------------------------------
    @app.get("/api/health")
    def health(who: str = Depends(caller)):
        comfy_ok = comfy_version = None
        comfy_queue = None
        comfy_identity: dict = {}
        if runner is not None:
            try:
                comfy_identity = runner.comfy.identity()
                comfy_version = comfy_identity.get("version")
                comfy_queue = runner.comfy.queue_depth()
                # "ok" krever at det er VAAR instans, med modeller. At noe
                # svarer paa porten er ikke nok - se comfy.identity().
                comfy_ok = bool(comfy_identity.get("ok"))
            except Exception as exc:                 # noqa: BLE001
                comfy_ok = False
                comfy_version = str(exc)[:200]

        broker_depth = consumer.broker_depth() if consumer is not None else None
        return {
            "status": "ok" if (comfy_ok is not False) else "degraded",
            "at": jobs_mod.now(),
            # HVA denne maskinen er til. Foerste spoersmaal naar noe ser rart
            # ut: er dette i det hele tatt en bok-PC? En preview-PC lytter
            # paa en annen koe og kjoerer en annen pipeline, og en jobb som
            # "forsvant" kan vaere en melding som havnet paa feil maskin.
            "mode": status_mod.mode_block(),
            "worker": (runner.snapshot() if runner is not None
                       else {"alive": False, "note": "API-et kjoerer uten runner"}),
            "comfy": {"ok": comfy_ok, "version": comfy_version,
                      "queue_depth": comfy_queue,
                      "url": flow_config.comfy()["url"],
                      "from_image": comfy_identity.get("from_image"),
                      "unet_models": comfy_identity.get("unet_models"),
                      "argv": comfy_identity.get("argv")},
            "rabbitmq": ({**consumer.snapshot(), "broker_depth": broker_depth}
                         if consumer is not None else {"connected": False}),
            # Tunnelen kan ikke sjekkes innenfra uten aa gaa ut og inn igjen;
            # at DETTE svaret naadde fram utenfra er selve tunnel-sjekken.
            "tunnel": {"note": "svarer dette utenfra, virker tunnelen"},
            "jobs": store.count_by_status(),
        }

    # -- koe --------------------------------------------------------------
    @app.get("/api/queue")
    def queue(who: str = Depends(caller)):
        running = store.running()
        pending = store.pending()
        return {
            "at": jobs_mod.now(),
            "running": _job_public(running) if running else None,
            "pending": [
                {**_job_public(row), "position": index}
                for index, row in enumerate(pending, 1)
            ],
            "counts": store.count_by_status(),
            "internal_queue_depth": runner.depth() if runner is not None else None,
            "broker_depth": (consumer.broker_depth()
                             if consumer is not None else None),
        }

    # -- jobber -----------------------------------------------------------
    @app.get("/api/jobs")
    def list_jobs(who: str = Depends(caller),
                  status_filter: str | None = Query(None, alias="status"),
                  limit: int = Query(50, ge=1, le=500),
                  offset: int = Query(0, ge=0)):
        if status_filter and status_filter not in jobs_mod.STATUSES:
            raise HTTPException(400, f"status maa vaere en av "
                                     f"{', '.join(jobs_mod.STATUSES)}")
        rows = store.list_jobs(status_filter, limit, offset)
        return {"at": jobs_mod.now(), "limit": limit, "offset": offset,
                "counts": store.count_by_status(),
                "jobs": [_job_public(r) for r in rows]}

    @app.get("/api/jobs/{job_key}")
    def get_job(job_key: str, who: str = Depends(caller),
                log_lines: int = Query(200, ge=0, le=2000)):
        row = store.job(job_key)
        if row is None:
            raise HTTPException(404, f"ingen jobb med job_key {job_key!r}")
        out = _job_public(row)
        out["permanent"] = bool(row.get("permanent"))
        out["redelivered"] = bool(row.get("redelivered"))
        out["steps"] = [
            {"name": s["name"], "attempt": s["attempt"], "status": s["status"],
             "started_at": s["started_at"], "finished_at": s["finished_at"],
             "seconds": s["seconds"], "error": s["error"], "detail": s["detail"]}
            for s in row.get("steps", [])
        ]
        out["payload"] = row.get("payload") or {}
        if log_lines:
            out["log"] = job_log_lines(job_key, log_lines)
        return out

    @app.post("/api/jobs")
    def submit_job(payload: dict, who: str = Depends(rate_limit)):
        """Legg en jobb paa den interne koeen uten aa gaa via RabbitMQ.

        Dette er inngangen n8n bruker i fase 2: worker-workflowen kaller flow
        som ÉN node i stedet for aa eie side-loekka selv, paa samme maate som
        den alt kaller "Run Text Script". Jobben havner i den samme interne
        koeen som RabbitMQ-jobbene, saa den er serialisert mot dem - to ordre
        kan ikke naa ComfyUI samtidig uansett hvilken vei de kom inn.
        """
        job_key = str(payload.get("job_key") or payload.get("order_id") or "").strip()
        if not job_key:
            raise HTTPException(400, "payloaden mangler baade job_key og order_id")

        fresh = store.enqueue(job_key, payload)
        existing = store.job(job_key) or {}
        if not fresh:
            # Ikke en feil. Det er svaret paa "denne ordren er alt haandtert",
            # og det er noeyaktig det som skal skje naar samme ordre kommer to
            # ganger: én bok, ikke to.
            store.action(who, "submit-duplikat", job_key,
                         {"status": existing.get("status")})
            return {"job_key": job_key, "status": existing.get("status"),
                    "accepted": False,
                    "reason": f"jobben finnes alt med status "
                              f"{existing.get('status')}"
                              + (" (permanent feil - bruk /retry naar aarsaken "
                                 "er rettet)" if existing.get("permanent") else ""),
                    "at": jobs_mod.now()}

        store.action(who, "submit", job_key, {"book_slug": payload.get("book_slug")})
        if runner is not None:
            from runner import QueuedJob
            runner.submit(QueuedJob(job_key, payload))
        return {"job_key": job_key, "status": "pending", "accepted": True,
                "position": len(store.pending()),
                "at": jobs_mod.now()}

    @app.post("/api/jobs/{job_key}/retry")
    def retry_job(job_key: str, who: str = Depends(rate_limit),
                  pipeline: str | None = Query(
                      None, description="pipeline for DENNE kjoeringen "
                                        "(pages/full). Utelatt = den aktive.")):
        """Kjoer en jobb om igjen. Virker ogsaa paa en jobb som er `done`.

        `pipeline` gjelder bare denne ene kjoeringen og endrer IKKE
        pipeline.ACTIVE. Grunnen den finnes: fase 5 ("full") maa kunne
        proeves paa en ekte ordre foer den blir standard for alle, og
        alternativet - aa flippe ACTIVE - endrer hvordan hver framtidige
        ordre behandles paa et system med betalende kunder.

        Stegene er idempotente, saa en full kjoering av en ordre som alt har
        sidene sine hopper over renderingen ("already-on-disk") og gaar
        videre til PDF og utkast.
        """
        row = store.job(job_key)
        if row is None:
            raise HTTPException(404, f"ingen jobb med job_key {job_key!r}")
        if row["status"] == "running":
            raise HTTPException(409, "jobben kjoerer allerede")
        if pipeline is not None:
            # Valider FOER jobben settes til pending: et ukjent navn skal
            # gi 400 her, ikke en jobb som staar pending og aldri kjoerer.
            try:
                pipeline_mod.by_name(pipeline)
            except KeyError as exc:
                raise HTTPException(400, str(exc)) from exc
        if not store.retry(job_key):
            raise HTTPException(409, "kunne ikke settes til pending")
        store.action(who, "retry", job_key,
                     {"forrige_status": row["status"], "feil": row.get("error"),
                      "pipeline": pipeline or pipeline_mod.active_name()})
        if runner is not None:
            from runner import QueuedJob
            runner.submit(QueuedJob(job_key, row["payload"], pipeline=pipeline))
        return {"job_key": job_key, "status": "pending", "requested_by": who,
                "pipeline": pipeline or pipeline_mod.active_name(),
                "at": jobs_mod.now()}

    @app.post("/api/jobs/{job_key}/cancel")
    def cancel_job(job_key: str, who: str = Depends(rate_limit)):
        row = store.job(job_key)
        if row is None:
            raise HTTPException(404, f"ingen jobb med job_key {job_key!r}")
        if row["status"] in ("done", "cancelled"):
            raise HTTPException(409, f"jobben er alt {row['status']}")
        store.request_cancel(job_key)
        store.action(who, "cancel", job_key, {"forrige_status": row["status"]})
        if row["status"] == "pending":
            # Ikke startet: avslutt den med en gang.
            store.finish(job_key, "cancelled", f"avbrutt av {who}")
        # Kjoerer den, ser side-loekka flagget mellom to sider. En side som er
        # i gang hos ComfyUI blir ferdig - det er billigere aa kaste en ferdig
        # side enn aa etterlate en halvskrevet fil paa disk.
        return {"job_key": job_key, "status": "cancelling", "requested_by": who,
                "at": jobs_mod.now()}

    # -- pipelines og boeker ----------------------------------------------
    @app.get("/api/workflows")
    def workflows(who: str = Depends(caller)):
        # `active` er den pipelinen SERVEREN faktisk kjoerer, altsaa etter at
        # modusen har sagt sitt - ikke pipeline.ACTIVE, som bare gjelder
        # boeker. Panelet tegner den som "den aktive", og den maa stemme.
        return {"at": jobs_mod.now(), "active": pipeline_mod.active_name(),
                "mode": status_mod.mode_block(),
                "workflows": pipeline_mod.describe_all()}

    @app.get("/api/books")
    def books_list(who: str = Depends(caller)):
        """Bokene med et configsammendrag - og om de i det hele tatt kan bygges.

        `buildable` finnes paa grunn av ordre 1517: Hestestjernen er kjoepbar
        paa nettsiden, men books/hestestjernen/ har ingen config.json. Den
        ordren doede stille 2026-09-15 og n8n skrev `success`. Her er slike
        boeker synlige foer noen kjoeper dem.
        """
        out = []
        for path in sorted(BOOKS.iterdir()):
            if not path.is_dir():
                continue
            config_path = path / "config.json"
            item = {"slug": path.name, "buildable": False, "missing": []}
            if not config_path.is_file():
                item["missing"].append("config.json")
                out.append(item)
                continue
            try:
                with open(config_path, encoding="utf-8-sig") as fh:
                    cfg = json.load(fh)
            except (OSError, json.JSONDecodeError) as exc:
                item["missing"].append(f"config.json er ugyldig: {exc}")
                out.append(item)
                continue
            wf = cfg.get("workflowApi") or "workflow_api.json"
            if not (path / wf).is_file():
                item["missing"].append(wf)
            if not cfg.get("pages"):
                item["missing"].append("pages[]")
            languages = sorted(cfg.get("textScripts") or {})
            missing_scripts = [lang for lang, script in (cfg.get("textScripts") or {}).items()
                               if not Path(script).is_file()]
            item.update({
                "display_name": cfg.get("displayName"),
                "pages": len(cfg.get("pages") or []),
                "expected_inner_pages": cfg.get("expectedInnerPages"),
                "next_book_slug": cfg.get("nextBookSlug"),
                "drive_folder_id": cfg.get("driveFolderId"),
                "languages": languages,
                "workflow_api": wf,
                "patch_nodes": cfg.get("patchNodes"),
            })
            if missing_scripts:
                item["missing"].append(
                    "tekstskript mangler paa disk: " + ", ".join(sorted(missing_scripts)))

            # Ryggraden (bokryggen). Den ligger i flow/text/ryggrad/<slug>/ og
            # er ikke nevnt i config.json noe sted, saa den er lett aa glemme
            # naar en bok legges inn. Mangler den, bygges INNERSIDENE fint og
            # forsiden feiler med "Mangler: ryggrad.png" - altsaa ingen bok,
            # oppdaget flere steg for sent. kongerikets-hemmelighet mangler
            # den i dag; den har aldri blitt bygget.
            spine = TEXT / "ryggrad" / path.name
            if languages and not spine.is_dir():
                item["missing"].append(f"ryggrad ({spine.name}/) - forsiden "
                                       f"kan ikke bygges")
            item["buildable"] = not item["missing"]
            out.append(item)
        return {"at": jobs_mod.now(), "count": len(out),
                "buildable": sum(1 for b in out if b["buildable"]),
                "books": out}

    # -- hendelsesstroem --------------------------------------------------
    @app.get("/api/events")
    async def events(who: str = Depends(caller), after: int = Query(0, ge=0)):
        """SSE. Dashbordet abonnerer og slipper aa polle.

        `after` lar en klient som mistet forbindelsen hente det den gikk glipp
        av i stedet for aa begynne paa nytt.
        """
        async def stream():
            last = after
            # Si hei med en gang, saa klienten vet at forbindelsen lever
            # selv om det ikke skjer noe paa en halvtime.
            yield f": tilkoblet {jobs_mod.now()}\n\n"
            while True:
                rows = await asyncio.to_thread(store.events_since, last, 200)
                for row in rows:
                    last = row["id"]
                    payload = {"id": row["id"], "at": row["at"],
                               "kind": row["kind"], "job_key": row["job_key"],
                               "message": row["message"], "detail": row["detail"]}
                    yield (f"id: {row['id']}\nevent: {row['kind']}\n"
                           f"data: {json.dumps(payload, ensure_ascii=False)}\n\n")
                if not rows:
                    yield ": ping\n\n"
                await asyncio.sleep(2)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    # -- panelet ----------------------------------------------------------
    @app.get("/panel")
    def panel():
        """Selve siden, uten auth.

        Den inneholder ingen data og ingen hemmeligheter - bare markup og
        JavaScript. Hvert datakall den gjoer gaar til /api/* og krever
        bearer-token, som operatoeren limer inn én gang. En nettleser kan
        ikke sende en Authorization-header paa en vanlig sidelasting, saa
        alternativet ville vaert et token i URL-en - og det havner i
        historikk, logger og Referer-headere.
        """
        path = PANEL / "index.html"
        if not path.is_file():
            raise HTTPException(404, "panel/index.html finnes ikke")
        return FileResponse(path, media_type="text/html; charset=utf-8",
                            headers={"Cache-Control": "no-store"})

    return app

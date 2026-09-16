# -*- coding: utf-8 -*-
"""Status-API-et som sin EGEN lytter, paa sin egen port.

Hvorfor denne filen finnes, naar /api/status ogsaa henger i api.py:

Fram til na laa forsvaret mot at kundedata slapp ut i et *sti-regex* i
tunnel/config.yml. Det holdt sa lenge tunnelen var var egen, med ingress i en
fil vi eier. `tobias-pc.dreampage.store` ligger i en annen Cloudflare-konto,
og den tunnelen kjoerer med `--token` - altsa fjernstyrt ingress, der ruten
bare er "hostname -> service" UTEN sti-filter. Pekte vi den mot port 8765,
ville /api/jobs og /api/queue (barnenavn, ordrenummer) og /api/health
(filsystemstier) fulgt med ut, uten at noen hadde bedt om det.

Losningen er ikke et strammere regex. Det er at porten som eksponeres ikke
HAR noe annet aa naa: denne appen inneholder tre ruter, og resten av API-et
er ikke montert i den. Da er grensen en egenskap ved konstruksjonen i stedet
for en regel noen ma huske aa skrive riktig - samme resonnement som prefetch=1
i konsumenten.

Konkret: en feilkonfigurert ingress mot 8766 kan i verste fall gi 404.
En feilkonfigurert ingress mot 8765 kunne gitt ordrelista.

  port 8765  hele API-et      - kun 127.0.0.1/Tailscale, aldri i en tunnel
  port 8766  BARE status      - trygg aa peke en tunnel mot

Tokenet kreves fortsatt. Tunnelen er transport, ikke autentisering, og et
token med scope "status" far 403 paa alt annet i api.py. Dette er det tredje
laget, ikke en erstatning for de to andre.

Testen som holder loeftet er test_status_api_har_bare_statusruter i
tests/test_flow.py. Legger noen en rute til her, feiler den.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import Depends, FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import jobs as jobs_mod  # noqa: E402
import status as status_mod  # noqa: E402
from api import status_caller  # noqa: E402

# Rutene som far finnes i denne appen. Listen er bade dokumentasjon og det
# testen sammenligner mot.
ALLOWED_PATHS = ("/api/status", "/api/status/summary", "/api/status/id")


def create_status_app(runner=None, consumer=None) -> FastAPI:
    """Bare de tre statusrutene. Ingen CORS, ingen panel, ingen POST.

    Ingen CORS med vilje: dette er ikke et endepunkt en nettleser skal kalle
    fra en annen origin. Admin-dashbordet snakker med 8765.
    """
    app = FastAPI(title="DreamPage status", version="1.0",
                  docs_url=None, redoc_url=None, openapi_url=None)
    store = jobs_mod.store()

    @app.get("/api/status")
    def status_full(who: str = Depends(status_caller)):
        return status_mod.snapshot(runner, consumer, store)

    @app.get("/api/status/summary")
    def status_summary(who: str = Depends(status_caller)):
        return status_mod.summary(runner, consumer, store)

    @app.get("/api/status/id")
    def status_id(who: str = Depends(status_caller)):
        return {"schema": 1, "at": jobs_mod.now(), "server": status_mod.server()}

    return app

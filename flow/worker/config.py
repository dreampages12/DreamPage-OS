# -*- coding: utf-8 -*-
"""Kjoerekonfigurasjon for flow: timeouts, retry, koe, steg.

Oppdraget krever at retry og timeout er KONFIGURASJON, ikke tall spredt i
koden. Standardverdiene her er hentet fra n8n-nodene de erstatter, ikke
gjettet - referansen staar i kommentaren ved hver verdi, slik at ingen
"rydder opp" i et tall som en gang kostet en produksjonsordre.

`config/flow.json` overstyrer alt, og filen behoever bare inneholde det som
skal vaere annerledes. Miljoevariabler overstyrer den igjen (nyttig i tester).
"""
from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from paths import CONFIG, COMFY_URL  # noqa: E402

CONFIG_PATH = CONFIG / "flow.json"

# Hva denne server-PC-en er. Én maskin gjoer én ting:
#
#   book      hele bokproduksjonen: RabbitMQ `dreampage-jobs` -> sider ->
#             PDF -> Drive -> Gelato-UTKAST. Dagens oppfoersel, og standarden.
#   preview   forhaandsvisninger til nettbutikken: RabbitMQ `preview-jobs` ->
#             ÉN side -> tittel/tekst -> opplasting + callback. Bestiller
#             ingenting og trykker ingenting.
#
# Modusen staar i config/flow.json ("mode") og kan overstyres med DP_MODE i
# miljoeet. Den avgjoer TO ting, og bare de to: hvilken koe konsumenten lytter
# paa, og hvilken pipeline runneren kjoerer. Alt annet - jobb-DB, API, logg,
# status, ack-semantikk, serialiseringen mot ComfyUI - er felles, fordi det
# er infrastruktur og ikke arbeidsflyt.
#
# En ukjent verdi er en FEIL, ikke "da tar vi book". En preview-PC som stille
# faller tilbake til bokmodus ville koblet seg paa ordrekoeen for ekte,
# betalte boeker.
MODES = ("book", "preview")

DEFAULTS: dict = {
    "mode": "book",

    # Per modus: koenavn og pipeline. Dette er hele bryteren - den er DATA,
    # paa samme maate som pipelinen selv, saa en ny modus er en oppfoering
    # her og en liste i pipeline.py, ikke en if-gren i runneren.
    #
    # pipeline=null betyr "bruk pipeline.ACTIVE". Bokmodus staar slik med
    # vilje: hvilken bokpipeline som er aktiv ("pages"/"full") er et valg som
    # hoerer hjemme i pipeline.py, der begrunnelsen staar.
    "modes": {
        "book": {"queue": "dreampage-jobs", "pipeline": None},
        "preview": {"queue": "preview-jobs", "pipeline": "preview"},
    },

    "comfy": {
        "url": COMFY_URL,

        # 180 s. Hentet fra "HTTP Request ComfyUI" (timeoutMs = 180000).
        # ComfyUI kan bruke naer tre minutter paa aa svare paa /prompt under
        # minnepress: da lokal RAM-bruk sultet ut event-loopen, gikk en side
        # fra 69 s til 178 s og /prompt timet ut. Ikke sett denne lavere.
        "prompt_timeout_s": 180,

        # 10 s mellom hver /history-sjekk, fra "Init Poll" (intervalMs 10000).
        "poll_interval_s": 10,

        # 3240 forsoek x 10 s = 9 timer. Fra "Init Poll" (maxTries 3240).
        # Virker absurd hoeyt, og er det: det er en sikkerhetsventil, ikke en
        # forventning. En side tar 60-180 s.
        "poll_max_tries": 3240,

        # 15 s paa selve /history-kallet, fra "Get History".
        "history_timeout_s": 15,

        # Hvor mange /history-feil paa rad vi taaler foer siden regnes som
        # feilet. n8n telte dem i poll.historyErrors men brukte aldri tallet
        # til noe - en nettverksblip skulle ikke drepe en ordre. Her er det en
        # ekte grense, saa en ComfyUI som er DOED ikke poller i ni timer.
        "history_error_tolerance": 30,

        # Etter en /prompt maa filen dukke opp paa disk. ComfyUI skriver den
        # etter at /history sier "completed", saa det er et lite vindu der
        # begge er sanne men filen ikke er lukket enda.
        "disk_settle_s": 2,
    },

    "queue": {
        "name": "dreampage-jobs",

        # prefetch=1 + manuell ack. Dette er halve grunnen til at flow finnes:
        # n8n kjoerte executions parallelt uten delt minne, og ComfyUI taaler
        # én jobb. Med én konsument som henter én melding om gangen er
        # serialiseringen en egenskap ved konstruksjonen, ikke noe en laasefil
        # maa haandheve.
        "prefetch": 1,

        # Ack foerst naar ordren har naadd et varig sjekkpunkt. Til da staar
        # meldingen i koen, og en redelivery er kjedelig i stedet for farlig:
        # ordre 1499 kom tre ganger paa én dag.
        "ack_on": "checkpoint",
        "heartbeat_s": 600,
        "reconnect_delay_s": 10,
    },

    "api": {
        "host": "127.0.0.1",
        "port": 8765,

        # Status-API-et lytter i TILLEGG paa sin egen port, med bare de tre
        # /api/status-rutene i seg (flow/worker/status_api.py). Det er DENNE
        # porten en tunnel skal peke paa - 8765 har ogsaa /api/jobs og
        # /api/queue, og en fjernstyrt ingress har ikke noe sti-filter.
        # Sett status_port til null for aa slaa den av.
        "status_port": 8766,
        "status_host": "127.0.0.1",

        # Skal det fulle API-et ogsaa svare paa tailnett-adressen, slik at et
        # kontrollpanel paa en ANNEN maskin naar det? Standarden er false:
        # en ny server skal ikke bli naabar fordi den arver en config.
        # Denne maskinen slaar det paa i config/flow.json.
        #
        # Binder til tailnett-adressen spesifikt, ALDRI 0.0.0.0 - da ville
        # API-et ogsaa svart paa hjemmenettet (192.168.x). Se worker/net.py.
        "tailnet": False,

        # CORS-origin for admin-dashbordet. Aldri "*".
        "cors_origins": ["https://admin.dreampage.store"],
        "rate_limit_per_minute": 30,
    },

    # Per steg: skru av, endre retry og timeout. Panelet skriver hit.
    "steps": {},

    # Standard for et steg som ikke er nevnt i "steps".
    "step_defaults": {
        "enabled": True,
        "retries": 0,
        "timeout_s": 3600,
    },

    # ---------------------------------------------------------------
    # Bare PREVIEW-modus leser dette. En bok-PC har hele blokka staaende
    # ubrukt, og det er meningen: da er en modusbytte én linje, ikke en ny
    # configfil noen maa huske aa lage.
    # ---------------------------------------------------------------
    "preview": {
        # Hvor det ferdige bildet og statusfila skal. "supabase" er det
        # nettbutikken faktisk leser; "local" skriver bare til disk og er
        # for utvikling og test.
        #
        # Det finnes MED VILJE ingen standard som "prov supabase, faller
        # tilbake paa local". Et preview som havner paa en lokal disk i
        # stedet for hos kunden er en jobb som ser vellykket ut og ikke er
        # det - noeyaktig feilklassen i CLAUDE.md. Er sinken ikke satt opp,
        # skal jobben feile hoeyt.
        "sink": "supabase",

        # Under state/ og output/, relativt til ROOT.
        "status_dir": "state/preview_jobs",
        "output_dir": "output/preview",

        # Supabase Storage. url og service_key ligger i config/secrets.json
        # under "supabase" - aldri her, og aldri i kildekoden.
        "supabase": {
            # Statusfila frontenden poller: <bucket>/<status_prefix>/<job_id>.json
            "status_bucket": "uploads",
            "status_prefix": "preview-jobs",
            # Det ferdige bildet: <bucket>/<prefix>/<session>/<job_id>_preview.jpg
            "result_bucket": "storage",
            "result_prefix": "previews",
            "timeout_s": 60,
        },

        # Callbacken til WordPress. Feiler den, er jobben likevel ferdig -
        # bildet ligger hos Supabase og statusfila sier "completed".
        "callback_timeout_s": 30,

        # Telegram-varsel per ferdig preview. Av som standard: en
        # preview-PC kan gjoere hundrevis om dagen, og et varsel per stykk
        # er stoey - og stoey er det som gjorde at tolv ekte advarsler i
        # ordre 1528 saa ut som mer av det samme.
        "notify_each": False,
    },

    "log": {
        "level": "INFO",
        # Én loggfil per jobb, i tillegg til fellesloggen. Naar en ordre
        # feiler er det den eneste filen man vil se i.
        "per_job_files": True,
    },
}

_cache: dict | None = None


def _deep_update(base: dict, other: dict) -> dict:
    for key, value in other.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def load(refresh: bool = False) -> dict:
    global _cache
    if _cache is not None and not refresh:
        return _cache
    conf = deepcopy(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8-sig") as fh:
            _deep_update(conf, json.load(fh))
    except FileNotFoundError:
        pass
    except json.JSONDecodeError as exc:
        # En daarlig configfil skal ikke stoppe en ordre som staar i koen.
        # Den skal derimot vaere umulig aa overse.
        print(f"[flow] ADVARSEL: {CONFIG_PATH} er ugyldig JSON ({exc}) "
              f"- bruker standardverdiene", file=sys.stderr)

    if os.environ.get("DP_COMFY_URL"):
        conf["comfy"]["url"] = os.environ["DP_COMFY_URL"]
    if os.environ.get("DP_API_PORT"):
        conf["api"]["port"] = int(os.environ["DP_API_PORT"])
    _cache = conf
    return conf


def comfy() -> dict:
    return load()["comfy"]


def mode() -> str:
    """"book" eller "preview". DP_MODE i miljoeet vinner over fila.

    Kaster ValueError paa en ukjent verdi. Det er med vilje: en skrivefeil
    skal ikke bety at en preview-PC stille kobler seg paa koen med ekte,
    betalte bokordre. main.py fanger den ved oppstart og stopper prosessen
    med en setning som sier hva som er lov.
    """
    raw = (os.environ.get("DP_MODE") or load().get("mode") or "book")
    value = str(raw).strip().lower()
    if value not in MODES:
        raise ValueError(
            f"ukjent servermodus {raw!r}. Lov: {', '.join(MODES)}. "
            f"Sett den i {CONFIG_PATH} (\"mode\") eller i DP_MODE.")
    return value


def mode_conf(name: str | None = None) -> dict:
    """Koe og pipeline for en modus."""
    key = name or mode()
    conf = dict((load().get("modes") or {}).get(key) or {})
    if not conf:
        # Modusen er kjent (mode() har validert den), men mangler i tabellen.
        # Det er en configfeil, og den skal ikke gjettes bort.
        raise ValueError(f"modus {key!r} har ingen oppfoering under \"modes\" "
                         f"i {CONFIG_PATH}")
    return conf


def queue() -> dict:
    """Koeinnstillingene, med navnet hentet fra den aktive modusen.

    Navnet er DERFOR ikke noe mq.py trenger aa vite noe om: konsumenten
    spoer om "koen", og faar den koen denne serveren er satt til aa lytte
    paa. prefetch, ack-regel og heartbeat er de samme i begge moduser -
    ComfyUI taaler én jobb uansett hva jobben lager.
    """
    conf = dict(load()["queue"])
    name = mode_conf().get("queue")
    if name:
        conf["name"] = str(name)
    return conf


def preview() -> dict:
    return load()["preview"]


def api() -> dict:
    return load()["api"]


def step(name: str) -> dict:
    """BARE det config.json faktisk overstyrer for dette steget.

    Ikke slaa sammen med step_defaults her. Stegene erklaerer sine egne
    retries og timeouts i pipeline.py (render_pages har 14 timer, ikke én),
    og en sammenslaaing her sendte step_defaults tilbake som om det var en
    overstyring - saa koden sin erklaering ble alltid overskrevet av
    standardverdien. step_defaults gjelder steg som IKKE erklaerer noe.
    """
    return dict(load().get("steps", {}).get(name, {}))


def save(conf: dict) -> None:
    """Skriv config/flow.json. Brukes av panelet naar et steg skrus av eller
    en timeout endres. Atomisk: en halvskrevet configfil ville gjort at neste
    oppstart falt tilbake paa standardverdiene uten at noen skjoenner hvorfor."""
    global _cache
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(conf, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    os.replace(tmp, CONFIG_PATH)
    _cache = None

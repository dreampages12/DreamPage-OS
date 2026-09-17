# -*- coding: utf-8 -*-
"""Én Gelato-klient, med retry og med verifisering av utkastet.

Hvorfor denne fila finnes - to grunner, begge dyrekjoepte.

**1. Ingen retry.** `drive_upload.py` fikk full resumable retry 16.09.2026
etter at ordre 1512 doede paa én HTTP 500 fra Google. Gelato-kallet ETT steg
senere hadde ingen retry i det hele tatt. Samme skjoerhet, samme konsekvens:
en nettverksblip midt i `POST /v4/orders` og hele ordren stopper.

**2. Utkastet ble aldri lest tilbake.** Vi POSTet utkastet, tok `id` ut av
svaret, slettet det gamle utkastet og gikk videre. Ingen sjekket om Gelato
FAKTISK fikk tak i PDF-en.

Det er noeyaktig det som gikk galt paa ordre 1300 (105,7 MB): Drive sin
`/uc`-lenke svarte med en HTML-advarselside i stedet for fila, Gelato lastet
ned 2 kB HTML, og item-et stod igjen med `files[0].id = null`. Ingenting
varslet. Fiksen den gangen var aa bygge `drive.usercontent`-URL-en riktig -
altsaa aa unngaa aarsaken. Men DETEKSJONEN manglet fortsatt, saa neste gang
noen bygger en ny sti til Gelato gjentar feilen seg like stille.

`verify_draft()` er den deteksjonen: den leser utkastet tilbake og krever at
hvert item har en fil med en `id`. Da er lekkasjen umulig aa ikke oppdage,
uansett hva som gjorde at fila ikke kom fram.

Helperen laa foer i fire kopier - `finish_order.py`, `finish_merged_order.py`,
`gelato_merge.py` og indirekte `dp_merge.py` - med tre ulike timeouts
(90/120/60 s) og ulik feilhaandtering. Bare én av dem skrev ut hva Gelato
faktisk klaget over, og det var den som ble brukt minst.
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE = "https://order.gelatoapis.com/v4"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# Samme regel som i drive_upload.py: 408/429/5xx er "proev igjen", alt annet
# er var egen feil og skal opp med en gang. En 400 fra Gelato er en payload
# vi har bygget feil - ti forsoek gjoer den ikke gyldig.
RETRY_STATUS = {408, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 5
DEFAULT_TIMEOUT = 120

# verify_draft venter paa noe HELT annet enn call(): ikke at en nettverksfeil
# skal gi seg, men at Gelato skal rekke aa LASTE NED PDF-en fra Drive. Derfor
# egne tall.
#
# En samlet bok er 85-90 MB. Maalt 17.09.2026: den samme drive.usercontent-
# lenka tok 33,7 sekunder aa hente herfra. verify_draft ventet da 1+2+4+8 =
# 15 sekunder foer den ga opp - altsaa under halve tiden nedlastingen
# plausibelt tar. Det var ikke en Gelato-feil; vi spurte for tidlig.
#
# Konsekvensen var ikke bare en feilmelding: steget har retries=2, og hvert
# nye forsoek laster opp 170 MB til Drive paa nytt foer det spoer igjen.
# Ordre 1530 (89,5 MB) og 1532-b1 (89,4 MB) traff dette begge.
#
# 1+2+4+8+16+32+45+45 = ca 2,5 minutter, med god margin over de maalte 34 s.
VERIFY_ATTEMPTS = 8
VERIFY_SLEEP_CAP = 45


class GelatoError(RuntimeError):
    """Gelato svarte ikke som forventet.

    RuntimeError, IKKE SystemExit. Det er ikke en stilistisk detalj:
    SystemExit arver BaseException, og runner-loopen fanger `Exception`.
    17.09.2026 kastet verify_draft SystemExit for ordre 1532-b1, den gikk
    rett gjennom `except Exception` i baade _run_step, run_job OG _loop, og
    drepte arbeidstraaden. Jobben stod som "running" for alltid, to andre
    ordre laa fast i koeen, og /api/status meldte worker_alive: false. Ingen
    ordre ble behandlet paa 47 minutter.

    Modulen brukes baade som bibliotek i workeren og fra kommandolinje-
    skript. SystemExit passer det siste og er katastrofalt for det foerste.
    """


def _key() -> str:
    import dp_secrets
    return dp_secrets.gelato_api_key()


def _sleep(attempt: int, cap: int = 30, attempts: int = MAX_ATTEMPTS) -> None:
    delay = min(2 ** attempt, cap) + random.uniform(0, 1)
    print(f"[GELATO] venter {delay:.1f} s foer forsoek {attempt + 1}/{attempts}")
    time.sleep(delay)


def call(method: str, url_or_path: str, body=None,
         timeout: int = DEFAULT_TIMEOUT) -> tuple[int, dict]:
    """Ett Gelato-kall med retry paa transiente feil.

    `url_or_path` godtar bade en full URL og en sti som "/orders" - de fire
    gamle kopiene gjorde det forskjellig, og aa tvinge dem til én form ville
    vaert en unoedvendig endring paa fire kallsteder.

    Returnerer (http-status, json). Kaster HTTPError paa permanente feil, med
    feilkroppen fra Gelato lagt inn i meldingen - det var bare én av de fire
    kopiene som gjorde det, og det er den informasjonen man faktisk trenger.
    """
    url = url_or_path if url_or_path.startswith("http") else BASE + url_or_path
    data = json.dumps(body).encode() if body is not None else None
    last: Exception | None = None

    for attempt in range(MAX_ATTEMPTS):
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"X-API-KEY": _key(), "Content-Type": "application/json",
                     "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                raw = res.read().decode("utf-8", "replace")
                return res.status, (json.loads(raw) if raw.strip() else {})

        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:1000]
            except Exception:                       # noqa: BLE001
                pass
            if exc.code not in RETRY_STATUS:
                raise urllib.error.HTTPError(
                    exc.url, exc.code,
                    f"{exc.reason}: {detail}" if detail else exc.reason,
                    exc.headers, None) from None
            last = exc
            print(f"[GELATO] {method} {url} -> HTTP {exc.code} {detail[:200]}")

        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last = exc
            print(f"[GELATO] {method} {url} -> {type(exc).__name__}: {exc}")

        if attempt < MAX_ATTEMPTS - 1:
            _sleep(attempt)

    raise GelatoError(
        f"Gelato-kallet {method} {url} feilet etter {MAX_ATTEMPTS} forsoek. "
        f"Siste feil: {last}")


def get_order(order_id: str) -> dict:
    _, res = call("GET", f"/orders/{order_id}")
    return res


def verify_draft(draft_id: str, expect_items: int = 1) -> dict:
    """Leste Gelato faktisk inn PDF-en? Kaster hvis ikke.

    Dette er sjekken ordre 1300 manglet. Et item der `files[0].id` er null
    betyr at Gelato provde aa hente URL-en og fikk noe annet enn en PDF -
    typisk Drives HTML-advarselside for filer over 100 MB. Utkastet ser
    ferdig ut i dashbordet helt til noen prover aa bestille det.

    Kalles ETTER at utkastet er laget. Gelato bruker noen sekunder paa aa
    hente fila, saa den taaler at svaret ikke er klart med en gang.
    """
    last_state = None
    for attempt in range(VERIFY_ATTEMPTS):
        order = get_order(draft_id)
        items = order.get("items") or []
        if len(items) >= expect_items:
            bad = []
            for item in items:
                files = item.get("files") or []
                have = [f for f in files if f.get("id")]
                if not have:
                    bad.append(item.get("itemReferenceId") or item.get("id") or "?")
            if not bad:
                return {"draft_id": draft_id, "items": len(items),
                        "files_ok": True,
                        "fulfillmentStatus": order.get("fulfillmentStatus")}
            last_state = (f"{len(bad)} item(er) uten innlest fil: "
                          f"{', '.join(map(str, bad))}")
        else:
            last_state = f"utkastet har {len(items)} item(er), ventet {expect_items}"

        if attempt < VERIFY_ATTEMPTS - 1:
            _sleep(attempt, cap=VERIFY_SLEEP_CAP, attempts=VERIFY_ATTEMPTS)

    raise GelatoError(
        f"Gelato-utkast {draft_id}: {last_state}.\n"
        "Det betyr nesten alltid at Gelato ikke fikk lastet ned PDF-en fra "
        "Drive. Sjekk at URL-en er en drive.usercontent-lenke og at fila er "
        "delt offentlig - en /uc-lenke gir en HTML-advarselside for filer "
        "over 100 MB, og da staar item-et igjen uten fil (ordre 1300).")

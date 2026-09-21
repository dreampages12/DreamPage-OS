# -*- coding: utf-8 -*-
"""Én kilde til sannhet for stier i DreamPage OS.

Bakgrunn: `C:/ComfyUI` laa hardkodet 175 steder i 75 filer, i tillegg til 24
n8n-noder, to custom_nodes-ini-filer og en junction. Et navnebytte var derfor
ikke en flytting, men en skattejakt. Denne modulen finnes for at det aldri
skal skje igjen: ingen ny kode skal hardkode en sti, og gammel kode migreres
til aa spoerre her.

ROOT utledes fra denne filas egen plassering (`flow/paths.py` -> forelder),
saa hele treet kan flyttes eller doepes om uten aa redigere noe. `DP_ROOT` i
miljoeet overstyrer, slik at en testkjoering kan peke et annet sted.

Bruk:
    from paths import ROOT, BOOKS, OUTPUT, order_dir, comfy_dir
"""
from __future__ import annotations

import os
from pathlib import Path

# flow/paths.py -> flow/ -> DreamPage-OS/
ROOT = Path(os.environ.get("DP_ROOT") or Path(__file__).resolve().parent.parent)


# ---------------------------------------------------------------------------
# Stier som kommer UTENFRA: konfigurasjon, payloads, gamle filer
#
# `books/<slug>/config.json` og `config/next_book_titles.json` er fulle av
# absolutte stier som starter med `C:/DreamPage-OS/`. Det var riktig da alt
# bare fantes paa én Windows-maskin, og det er 435 av dem. Paa en Linux-
# server finnes ikke den disken, og hver eneste av dem ville pekt i tomme
# luften.
#
# Svaret er IKKE aa skrive om 435 stier i 30 configfiler. Det er aa oversette
# dem naar de leses: alt som ligger under den gamle roten, ligger under DENNE
# roten. Paa Windows er de to det samme, saa oversettelsen er en identitet og
# ingenting endrer seg. Paa Linux virker den samme configfila.
#
# Det gjoer ogsaa at en configfil kan skrives RELATIVT ("flow/text/nb/x.py"),
# og det er formen nye oppfoeringer skal ha.
# ---------------------------------------------------------------------------
LEGACY_ROOT = "c:/dreampage-os"

# Navnet foer 16.09.2026. I koden er det bare kommentarer igjen, men gamle
# ordre-payloads i state/orders/ kan fortsatt baere slike stier, og en
# reprint leser dem.
#
# `C:/ComfyUI` kan IKKE oversettes som én rot: mappa ble splittet i fire da
# den ble til DreamPage OS (se tools/migrate/rewrite_paths.py), og
# `C:/ComfyUI/script/nb/` ble `flow/text/nb/` - ikke `<ROOT>/script/nb/`.
# Derfor staar bare de mappene som BEHOLDT navnet sitt her. Alt annet under
# den roten lar vi ligge, slik at det feiler med sin egen sti i
# feilmeldingen i stedet for aa peke et sted som ser riktig ut og ikke er det.
LEGACY_COMFY_ROOT = "c:/comfyui"
LEGACY_COMFY_KEPT = ("input", "output", "models", "books", "state", "tmp")


def resolve(value, *, base: Path | None = None, root: Path | None = None) -> Path:
    """En sti fra konfigurasjon eller payload -> en sti paa DENNE maskinen.

    Tre tilfeller, i denne rekkefoelgen:

      1. Under en gammel, hardkodet rot  -> flyttes til ROOT.
         "C:/DreamPage-OS/flow/text/nb/x.py" -> <ROOT>/flow/text/nb/x.py
      2. Relativ                          -> under ROOT (eller `base`).
         "flow/text/nb/x.py"                 -> <ROOT>/flow/text/nb/x.py
      3. Absolutt ellers                  -> urort.
         En font i /usr/share eller C:/Windows er ikke vaar, og skal ikke
         flyttes. Peker den ingen steder, feiler den DER den brukes - med
         stien i feilmeldingen.

    Gjoer ingen I/O og sjekker ikke at fila finnes. Det er med vilje: den som
    kaller vet hva en manglende fil betyr hos seg, og `tools/check_assets.py`
    er stedet som sier fra foer noe rendres.

    `root` overstyrer ROOT. Trengs av verktoey som skal granske DEN
    installasjonen de selv ligger i, og ikke den DP_ROOT peker paa - ellers
    ville `tools/check_assets.py` granska en testsandkasse naar den kjoeres
    fra en test, og meldt at all kunst mangler.
    """
    here = root or ROOT
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return Path("")

    lowered = text.lower()
    if lowered == LEGACY_ROOT or lowered.startswith(LEGACY_ROOT + "/"):
        rest = text[len(LEGACY_ROOT):].lstrip("/")
        return (here / rest) if rest else here

    if lowered.startswith(LEGACY_COMFY_ROOT + "/"):
        rest = text[len(LEGACY_COMFY_ROOT):].lstrip("/")
        if rest.split("/", 1)[0].lower() in LEGACY_COMFY_KEPT:
            return here / rest
        # Resten av den gamle mappa ble splittet i fire. Ikke gjett.
        return Path(text)

    path = Path(text)
    # "/usr/share/..." er absolutt paa Linux, men `is_absolute()` er False paa
    # Windows fordi den mangler diskbokstav. Uten denne linja ville en
    # POSIX-sti i en configfil blitt til <ROOT>/usr/share/... naar den ble
    # lest paa Windows - altsaa en stille feil paa nettopp den maskinen der
    # stien ikke gir mening.
    if text.startswith("/") or path.is_absolute():
        return path
    # En "C:/..."-sti er absolutt paa Windows, men BARE et rart filnavn paa
    # Linux. Uten dette ville en ukjent Windows-rot blitt til en mappe som
    # heter "C:" under ROOT - altsaa en stille feil paa nettopp den maskinen
    # der stien ikke kan virke.
    if len(text) > 1 and text[1] == ":" and text[0].isalpha():
        return path
    return (base or here) / text


def resolve_str(value, *, base: Path | None = None,
                root: Path | None = None) -> str:
    """Som resolve(), men som streng med / - formen scriptene sender videre
    paa kommandolinja og skriver i JSON."""
    if not str(value or "").strip():
        # Tom inn, tom ut. Path("") blir til ".", og "." som filsti er en
        # mappe som finnes - altsaa en tom verdi som ser gyldig ut.
        return ""
    return str(resolve(value, base=base, root=root)).replace("\\", "/")


def under(*parts: str) -> str:
    """En sti under ROOT, som streng med PLATTFORMENS separator.

    Dette er erstatningen for de 116 hardkodede `r"C:\\DreamPage-OS\\..."` i
    koden. Den gir bevisst en `str` og ikke en `Path`: stedene som byttes ut
    sender verdien videre til `os.path.join`, `open`, en kommandolinje eller
    en f-streng, og en `Path` der ville endret oppfoerselen paa maater som
    ikke er synlige i diffen.

    Separatoren er plattformens, saa resultatet paa Windows er BYTE FOR BYTE
    det den hardkodede strengen var - se
    tools/migrate/unhardcode_paths.py --verify.
    """
    return str(ROOT.joinpath(*parts)) if parts else str(ROOT)

# ---------------------------------------------------------------------------
# Toppmapper
#
# IMAGE er ComfyUI selv. Innholdet der redigeres ALDRI - alt vi vil endre i
# ComfyUI skjer gjennom nodes/. Derfor ligger input/, output/ og models/ paa
# rota og settes paa ComfyUI sin kommandolinje med --input-directory,
# --output-directory og --extra-model-paths-config.
# ---------------------------------------------------------------------------
IMAGE = ROOT / "DreamPage-image"
FLOW = ROOT / "flow"
BOOKS = ROOT / "books"
NODES = ROOT / "nodes"
PANEL = ROOT / "panel"
TUNNEL = ROOT / "tunnel"
ARCHIVE = ROOT / "archive"
CONFIG = ROOT / "config"
SERVER = ROOT / "server"
DOCS = ROOT / "docs"

# Ikke i git.
MODELS = ROOT / "models"
STATE = ROOT / "state"
OUTPUT = ROOT / "output"
INPUT = ROOT / "input"
TMP = ROOT / "tmp"

# ---------------------------------------------------------------------------
# Under state/
# ---------------------------------------------------------------------------
ORDERS_STATE = STATE / "orders"          # <job_key>.json - payloadcachen
ORDERS_INDEX = ORDERS_STATE / "_index.json"
GELATO_DRAFTS = STATE / "gelato_drafts"
# Statusfilene for forhaandsvisninger (PREVIEW-modus). Én fil per job_id, med
# samme innhold som den som lastes opp til Supabase. Den lokale kopien er det
# eneste sporet som finnes naar nettet var nede da jobben ble ferdig.
PREVIEW_JOBS = STATE / "preview_jobs"
NEXT_COVER = STATE / "next_cover"
REPRINT_STATE = STATE / "reprint"
JOBS_DB = STATE / "jobs.sqlite"          # fase 3

# ---------------------------------------------------------------------------
# Tekstscript og assets
#
# Lokalemappene er selvstendige bunter: hver har egne kopier av gelato_cover.py,
# dream_pdf_guard.py, fontene og logoen, og tekstscriptene importerer
# soesknene sine bart (`from gelato_cover import ...`). De skal derfor ALDRI
# splittes opp - det ville knekt alle 80 tekstscriptene samtidig.
# ---------------------------------------------------------------------------
TEXT = FLOW / "text"
FACE_VARIANTS = FLOW / "face_variants"
TOOLS = FLOW / "tools"

# Delt kunst: logoer, bakside, ryggrad og lastpage-bilder.
#
# Disse laa en periode i `assets/` paa rota. Det var feil, og det brakk
# produksjonen to ganger:
#
#   1. Tekstscriptene finner dem RELATIVT til sin egen fil
#      (`os.path.dirname(__file__)` -> `flow/text/`), ikke gjennom denne
#      modulen. Flyttingen ga «Cover PDF ble IKKE laget. Mangler: ryggrad.png»
#      paa hver eneste bok.
#   2. `config/next_book_titles.json` pekte paa `assets/logo/...` med absolutt
#      sti. Da `assets/` ble ryddet bort igjen, forsvant line2-logoen fra
#      neste-bok-forsiden i stillhet - rendereren advarer og fortsetter med
#      exit 0. Ordre 1510 fikk en trykkeklar forside som bare sa «Henry og
#      det», uten boktittelen.
#
# Kunsten ligger derfor DER SCRIPTENE LETER, og disse konstantene peker dit.
# Flytt dem ikke uten aa kjoere `tools/check_assets.py` etterpaa.
LOGO = TEXT / "logo"
BAKSIDE = TEXT / "bakside"
RYGGRAD = TEXT / "ryggrad"
LASTPAGES = TEXT / "lastpages"

# ComfyUI, for de som maa snakke med prosessen eller lese loggen.
#
# Adressen staar ETT sted: config/flow.json -> comfy.url. Baade workeren,
# supervisoren (dreampage.ps1) og regen_page.py leser den herfra.
#
# Under overgangen kjoerte den nye ComfyUI paa 8189 mens den gamle elevette
# prosessen fortsatt eide 8188. Da regen_page hadde porten hardkodet, ville
# operatoerbotten stille snakket med en instans som ikke hadde modellene
# lenger - den ville svart, og laget en tom side.
def _comfy_url() -> str:
    if os.environ.get("DP_COMFY_URL"):
        return os.environ["DP_COMFY_URL"]
    try:
        import json
        with open(ROOT / "config" / "flow.json", encoding="utf-8-sig") as fh:
            url = (json.load(fh).get("comfy") or {}).get("url")
        if url:
            return str(url)
    except (OSError, ValueError):
        pass
    return "http://127.0.0.1:8188"


COMFY_URL = _comfy_url()
COMFY_USER = IMAGE / "user"
COMFY_CUSTOM_NODES = IMAGE / "custom_nodes"


# ---------------------------------------------------------------------------
# Ordrestier
#
# job_key, ikke order_id: en WooCommerce-ordre kan inneholde flere boeker, og
# da har alle samme order_id ("1411") mens bare job_key skiller dem
# ("1411-b1", "1411-b2"). job_key er mappe- og filnoekkelen overalt.
# ---------------------------------------------------------------------------
def book_dir(slug: str) -> Path:
    return BOOKS / slug


def order_dir(slug: str, job_key: str) -> Path:
    return BOOKS / slug / "orders" / str(job_key)


def order_input_dir(slug: str, job_key: str) -> Path:
    return order_dir(slug, job_key) / "input"


def order_pdf_dir(slug: str, job_key: str) -> Path:
    return order_dir(slug, job_key) / "pdf"


def comfy_dir(job_key: str, slug: str, comfy_output_prefix: str | None = None) -> Path:
    """Mappa ComfyUI skriver sidebildene til.

    Denne mappa er ogsaa svaret paa "er siden ferdig?", og det spoersmaalet
    maa BARE stilles her inne. Sidenoeklene (page00..page15) er like i alle
    boeker, saa da to samtidige ordre 14.09.2026 fikk lov aa se i hverandres
    mapper, hoppet de over hverandres sider - bildene var ikke feil, de var
    borte.
    """
    prefix = (comfy_output_prefix or f"{slug}/orders").replace("/", os.sep)
    return OUTPUT / prefix / str(job_key) / "comfy"


def order_state_path(job_key: str) -> Path:
    return ORDERS_STATE / f"{job_key}.json"


# ---------------------------------------------------------------------------
# PREVIEW-modus
#
# Forhaandsvisninger har ingen bokmappe og ingen ordre: de har en job_id fra
# nettbutikken og lever bare til bildet er levert. De faar derfor sin egen
# gren under output/, og hver jobb sin EGEN mappe.
#
# Det siste er ikke ryddighet, det er den samme regelen som for boeker:
# sidenoekkelen ("page00") er lik i alle boeker og i alle preview-jobber, og
# "er siden ferdig?" maa kunne stilles uten at to samtidige jobber ser
# hverandres filer. Da to bokordre fikk lov til det 14.09.2026, hoppet de
# over hverandres sider.
# ---------------------------------------------------------------------------
PREVIEW_CONFIG = CONFIG / "preview"       # markets/ og books/<market>/


def preview_dir(job_id: str) -> Path:
    return OUTPUT / "preview" / str(job_id)


def preview_comfy_dir(job_id: str) -> Path:
    return preview_dir(job_id) / "comfy"


def preview_state_path(job_id: str) -> Path:
    return PREVIEW_JOBS / f"{job_id}.json"

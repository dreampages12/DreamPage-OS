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
ASSETS = ROOT / "assets"
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

LOGO = ASSETS / "logo"
BAKSIDE = ASSETS / "bakside"
RYGGRAD = ASSETS / "ryggrad"
LASTPAGES = ASSETS / "lastpages"

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

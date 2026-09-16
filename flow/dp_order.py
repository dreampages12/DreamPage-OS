# -*- coding: utf-8 -*-
"""Slå opp en ordre uten å vite executionId.

finish_order.py og republish_job.py krever begge --execution, som betyr at man
må lete i n8n manuelt før man kan gjøre noe. Boten kan ikke det, så denne
modulen gjør oppslaget: order_id -> nyeste execution -> payload.

Payloaden caches i state/orders/<id>.json fordi n8n pruner gamle executions.
Når den er borte finnes adresse, e-post, cover_type og continue_code
ingen andre steder - og continue_code skal ALDRI gjettes (trykk er permanent,
se memory-notatet om QR-siste-side).

  python dp_order.py --order 1235
  python dp_order.py --order 1235 --refresh
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# Windows-konsollen her er cp1252 og kan ikke skrive æøå. Uten dette krasjer
# et hvilket som helst print med norsk tekst i en UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

DB = r"C:\Users\tobia\.n8n\database.sqlite"
WORKFLOW_ID = "xy8qiRUzcBpH52CI"
CACHE_DIR = r"C:\DreamPage-OS\state\orders"
BOOKS_DIR = r"C:\DreamPage-OS\books"

# Hvor mange executions vi ser bakover når vi leter. Blobbene er store, så
# vi filtrerer på ordrenummeret i SQL først og parser bare treffene.
SCAN_LIMIT = 600


def cache_path(order_id: str) -> str:
    return os.path.join(CACHE_DIR, f"{order_id}.json")


def read_cache(order_id: str) -> dict | None:
    path = cache_path(order_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def write_cache(order_id: str, record: dict) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = cache_path(order_id) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, cache_path(order_id))


INDEX_PATH = os.path.join(CACHE_DIR, "_index.json")


def read_index() -> dict:
    try:
        with open(INDEX_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        data = {}
    data.setdefault("orders", {})       # order_id -> executionId
    data.setdefault("scanned", [])      # executionId-er vi har sett på
    return data


def write_index(index: dict) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = INDEX_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=1)
    os.replace(tmp, INDEX_PATH)


def execution_ids() -> list[int]:
    """Ferdige executions, nyeste forst.

    `stoppedAt is null` betyr at jobben fortsatt kjorer. n8n skriver da ikke
    payloaden til execution_data enda, sa load_payload finner ingenting - og
    fordi indeksen husker hva den har sett, ble en execution som ble skannet
    MENS den kjorte svartelistet for alltid. Ordren ble da usynlig i boten selv
    om payloaden lag der noen minutter senere. Vi hopper over de som kjorer;
    neste runde plukker dem opp nar de er ferdige.
    """
    con = sqlite3.connect(DB)
    try:
        rows = con.execute(
            "select id from execution_entity where workflowId = ?"
            " and stoppedAt is not null"
            " order by id desc limit ?", (WORKFLOW_ID, SCAN_LIMIT)).fetchall()
    finally:
        con.close()
    return [row[0] for row in rows]


def claimed_execution(order_id: str) -> int | None:
    """executionId fra ordrens .post_comfy_claim.json paa disk.

    Siste utvei nar indeksen ikke kjenner ordren: workeren skriver claim-fila
    nar den tar jobben, sa den peker rett paa executionen uten aa skanne noe.
    """
    for slug in slugs_from_disk(str(order_id)):
        claim = os.path.join(BOOKS_DIR, slug, "orders", str(order_id),
                             ".post_comfy_claim.json")
        try:
            with open(claim, encoding="utf-8") as fh:
                value = json.load(fh).get("executionId")
        except Exception:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def payload_key(payload: dict) -> str:
    """Ordrenoekkelen en payload hoerer til - det som mappa heter paa disk.

    Fra 2026-08-31 kan en WooCommerce-ordre inneholde flere boeker. Da har
    ALLE boekene samme `order_id` ("1411"), og bare `job_key` skiller dem
    ("1411-b1", "1411-b2"). Workeren navngir mapper og input-bilder etter
    job_key, saa boten maa gjoere det samme - ellers slaar de to boekene i
    en ordre sammen til ett oppslag, og den ene blir uNaaelig.

    Enkeltbok-ordre har job_key lik order_id, saa dette endrer ingenting
    for dem. Mangler job_key helt (gamle payloads), faller vi tilbake.
    """
    return str(payload.get("job_key") or payload.get("order_id") or "")


def index_execution(execution_id: int, index: dict) -> str | None:
    """Parse en execution en gang for alle og noter hvilken ordre den gjelder."""
    from republish_job import load_payload
    try:
        payload = load_payload(execution_id)
    except (SystemExit, Exception):
        # Ferdig execution uten jobb-payload er et endelig svar - noter den som
        # skannet sa vi slipper aa parse 68 MB pa nytt hver gang.
        index["scanned"] = sorted(set(index["scanned"]) | {execution_id},
                                  reverse=True)
        # load_payload kaster SystemExit for executions uten jobb-payload
        # (delkjøringer, feilede jobber) - det er normalt, bare hopp over.
        return None
    index["scanned"] = sorted(set(index["scanned"]) | {execution_id}, reverse=True)
    order_id = payload_key(payload)
    if not order_id:
        return None
    # Nyeste execution vinner; vi går alltid gjennom listen synkende.
    index["orders"].setdefault(order_id, execution_id)
    # Blobben er alt parset her - lagre payloaden med en gang så senere
    # oppslag slipper de 1,1 sekundene det koster å parse 68 MB på nytt.
    if not read_cache(order_id):
        write_cache(order_id, {"order_id": order_id,
                               "execution_id": execution_id,
                               "payload": payload})
    return order_id


def find_execution(order_id: str) -> int | None:
    """Nyeste execution der jobb-payloaden har dette order_id.

    n8n lagrer ~68 MB per execution. Et `instr()`-søk måtte lest hele
    blob-kolonnen (3,7 GB, ~3 s) HVER gang, og hvert kandidattreff kostet en
    parsing til. Derfor indekserer vi i stedet: hver execution parses en eneste
    gang, nyeste først, og oppslaget stopper så snart ordren er funnet.
    """
    index = read_index()
    hit = index["orders"].get(str(order_id))
    if hit:
        return hit

    scanned = set(index["scanned"])
    try:
        for execution_id in execution_ids():
            if execution_id in scanned:
                continue
            found = index_execution(execution_id, index)
            if found == str(order_id):
                return execution_id
    finally:
        write_index(index)

    # Skanningen fant den ikke. Hvis ordremappa har en claim-fil, peker den
    # rett pa executionen - da trenger vi verken indeks eller sok.
    claimed = claimed_execution(order_id)
    if claimed is not None:
        from republish_job import load_payload
        try:
            payload = load_payload(claimed)
        except (SystemExit, Exception):
            return None
        if payload_key(payload) == str(order_id):
            index = read_index()
            index["orders"][str(order_id)] = claimed
            write_index(index)
            if not read_cache(order_id):
                write_cache(order_id, {"order_id": str(order_id),
                                       "execution_id": claimed,
                                       "payload": payload})
            return claimed
    return None


def build_index() -> int:
    """Indekser alt som gjenstår - kjøres i bakgrunnen ved oppstart."""
    index = read_index()
    scanned = set(index["scanned"])
    added = 0
    for execution_id in execution_ids():
        if execution_id in scanned:
            continue
        index_execution(execution_id, index)
        added += 1
    if added:
        write_index(index)
    return added


def slugs_from_disk(order_id: str) -> list[str]:
    """Hvilke bokmapper har en mappe for denne ordren?"""
    if not os.path.isdir(BOOKS_DIR):
        return []
    return [slug for slug in os.listdir(BOOKS_DIR)
            if os.path.isdir(os.path.join(BOOKS_DIR, slug, "orders", str(order_id)))]


def resolve_slug(order_id: str, payload: dict) -> str:
    """Finn bokas MAPPENAVN.

    payload["book_slug"] er tittel-slugen fra WooCommerce (f.eks.
    "enhjorningsdalen"), ikke mappenavnet ("enhjorning") - workeren oversetter
    den med TITLE_TO_SLUG. Vi trenger ikke den tabellen her: en reprint gjelder
    alltid en ordre som allerede ligger på disk, så mappa er fasiten.
    """
    candidates = slugs_from_disk(order_id)
    claimed = str(payload.get("book_slug") or "").strip()

    if claimed in candidates:
        return claimed
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        raise SystemExit(f"ordre {order_id} finnes i flere bokmapper: "
                         + ", ".join(sorted(candidates)))
    if claimed and os.path.isfile(os.path.join(BOOKS_DIR, claimed, "config.json")):
        return claimed
    raise SystemExit(f"fant ingen ordremappe for {order_id} under books/")


def read_overrides(order_id: str) -> dict:
    """Felter du har rettet for hånd, og som skal overleve alt annet."""
    return (read_cache(str(order_id).strip()) or {}).get("overrides") or {}


def set_override(order_id: str, key: str, value) -> dict:
    """Lagre en retting permanent. value=None fjerner den.

    Ligger i selve ordrecachen, ikke i en egen fil: cachen er uansett det
    eneste stedet payloaden finnes etter at n8n har prunet executionen.
    """
    order_id = str(order_id).strip()
    record = read_cache(order_id)
    if not record:
        resolve(order_id)                      # tvinger fram cachefila
        record = read_cache(order_id) or {"order_id": order_id}
    overrides = dict(record.get("overrides") or {})
    if value is None:
        overrides.pop(key, None)
    else:
        overrides[key] = value
    record["overrides"] = overrides
    write_cache(order_id, record)
    return overrides


def resolve(order_id: str, refresh: bool = False) -> dict:
    """Full ordrekontekst: payload, bokmappe, config, stier.

    Kaster SystemExit med en forklarende tekst hvis ordren ikke finnes -
    boten videreformidler den rett til Telegram.
    """
    order_id = str(order_id).strip()
    existing = read_cache(order_id)
    # Rettinger overlever også --refresh: henter vi payloaden på nytt fra
    # n8n, står det fortsatt VERSALER i den, og navnet du rettet ville
    # stille kommet tilbake ved neste bygg.
    overrides = (existing or {}).get("overrides") or {}
    cached = None if refresh else existing

    if cached and cached.get("payload"):
        payload = cached["payload"]
        execution_id = cached.get("execution_id")
    else:
        execution_id = find_execution(order_id)
        if execution_id is None:
            hits = slugs_from_disk(order_id)
            extra = (f"\nOrdremappa finnes under books/{hits[0]}/orders/{order_id}, "
                     "men payloaden er borte fra n8n." if hits else "")
            raise SystemExit(
                f"fant ingen n8n-execution for ordre {order_id}.{extra}\n"
                "Uten payload mangler adresse, e-post og continue_code.")
        from republish_job import load_payload
        payload = load_payload(execution_id)
        write_cache(order_id, {"order_id": order_id,
                               "execution_id": execution_id,
                               "payload": payload,
                               "overrides": overrides})

    slug = resolve_slug(order_id, payload)

    config_path = os.path.join(BOOKS_DIR, slug, "config.json")
    if not os.path.isfile(config_path):
        raise SystemExit(f"fant ingen config.json for bok {slug}")
    with open(config_path, encoding="utf-8-sig") as fh:
        config = json.load(fh)

    order_path = os.path.join(BOOKS_DIR, slug, "orders", order_id)
    comfy_dir = os.path.join(r"C:\DreamPage-OS\output",
                             config.get("comfyOutputPrefix", f"{slug}/orders").replace("/", os.sep),
                             order_id, "comfy")

    return {
        "order_id": order_id,
        "execution_id": execution_id,
        "payload": payload,
        "book_slug": slug,
        "config": config,
        "config_path": config_path,
        "order_path": order_path,
        "input_dir": os.path.join(order_path, "input"),
        "pdf_dir": os.path.join(order_path, "pdf"),
        "comfy_dir": comfy_dir,
        "variants_dir": os.path.join(os.path.dirname(comfy_dir), "variants"),
        "face_image": f"{order_id}.jpg",
        # Rettet navn slår alltid payloaden. ALT som bygger boka henter navnet
        # herfra - tekst-scriptet, QR-siden og PDF-filnavnene - så dette ene
        # stedet er nok til at rettingen gjelder i all framtidig bygging.
        "child_name": overrides.get("child_name") or payload.get("child_name") or "",
        "child_name_payload": payload.get("child_name") or "",
        "overrides": overrides,
        "cover_type": payload.get("cover_type") or "hardcover",
        "continue_code": str(payload.get("continue_code") or "").strip(),
        "next_book_slug": next_book_slug(config, payload),
        "next_book_title": next_book_title(config, payload),
        "text_script": text_script_for(config, payload),
    }


# --------------------------------------------------------------------------
# Neste bok
#
# WordPress sender next_book_slug/-title i payloaden, men bare naar oppsalget
# er satt opp der. Boka selv vet ogsaa hvem fortsettelsen er, saa configens
# nextBookSlug/nextBookTitle er fasit naar payloaden tier. Da virker
# fortsett-siden i boten og reprint for en bok som HAR en fortsettelse, selv om
# ordren kom inn uten feltene.
#
# Fortsett-KODEN faller aldri tilbake paa noe - den lages alltid i WordPress.
# --------------------------------------------------------------------------
def next_book_slug(config: dict, payload: dict) -> str:
    return (str(payload.get("next_book_slug") or "").strip()
            or str((payload.get("next_book") or {}).get("slug") or "").strip()
            or str(config.get("nextBookSlug") or "").strip())


def next_book_title(config: dict, payload: dict) -> str:
    return (str(payload.get("next_book_title") or "").strip()
            or str((payload.get("next_book") or {}).get("title") or "").strip()
            or str(config.get("nextBookTitle") or "").strip())


def text_script_for(config: dict, payload: dict) -> str:
    """Samme språkvalg som workerens Load Book Config-node."""
    scripts = config.get("textScripts") or {}
    lang = str(payload.get("script_language") or payload.get("language") or "nb").strip()
    return scripts.get(lang) or config.get("textScript") or ""


def page_entry(config: dict, page_key: str) -> dict | None:
    for page in config.get("pages", []):
        if page.get("page_key") == page_key:
            return page
    return None


# --------------------------------------------------------------------------
# Kroppsvarianter
#
# Samme bok, men malbilder der barnet har en yngre kropp. Variantfilene ligger
# side om side med de vanlige i C:/DreamPage-OS/input og heter det samme pluss et
# suffiks: "04(dinosaur).png" -> "04(dinosaur)2-4aar.png".
#
# En bok trenger IKKE ha varianter for alle sidene. Sider uten variantfil
# faller tilbake til standardmalen, saa en halvferdig serie er brukbar med en
# gang i stedet for aa maatte vente paa at hele boka er tegnet paa nytt.
# --------------------------------------------------------------------------
INPUT_DIR = r"C:\DreamPage-OS\input"

BODY_VARIANTS = {
    "standard": {"label": "Standard", "suffix": ""},
    "2-4": {"label": "Liten kropp (2\u20134 \u00e5r)", "suffix": "2-4\u00e5r"},
}
DEFAULT_BODY_VARIANT = "standard"


def body_variant(info: dict) -> str:
    """Hvilken kroppsvariant ordren er satt til."""
    value = (info.get("overrides") or {}).get("body_variant")
    return value if value in BODY_VARIANTS else DEFAULT_BODY_VARIANT


def variant_filename(filename: str, variant: str) -> str | None:
    """Variantnavnet for en malfil, eller None hvis fila ikke finnes."""
    suffix = BODY_VARIANTS.get(variant, {}).get("suffix") or ""
    if not filename or not suffix:
        return None
    stem, ext = os.path.splitext(filename)
    candidate = f"{stem}{suffix}{ext}"
    return candidate if os.path.isfile(os.path.join(INPUT_DIR, candidate)) else None


def apply_body_variant(page: dict, variant: str) -> dict:
    """Bytt mal- og maskefil til kroppsvarianten der den finnes.

    Malen og masken byttes SAMMEN eller ikke i det hele tatt: en variantmal
    med standardmasken treffer feil sted, siden kroppen - og dermed hodet -
    staar et annet sted i bildet.
    """
    if not page or variant == DEFAULT_BODY_VARIANT:
        return page
    template = variant_filename(page.get("template_image"), variant)
    if not template:
        return page
    mask = variant_filename(page.get("mask_image"), variant)
    if page.get("mask_image") and not mask:
        return page
    swapped = dict(page)
    swapped["template_image"] = template
    if mask:
        swapped["mask_image"] = mask
    return swapped


def variant_pages(config: dict, variant: str) -> list[str]:
    """Sidene som faktisk HAR denne varianten."""
    hits = []
    for page in config.get("pages", []):
        if apply_body_variant(page, variant) is not page:
            hits.append(page.get("page_key"))
    return hits


def available_body_variants(config: dict) -> list[str]:
    """Variantene denne boka kan tilby, standard alltid foerst."""
    out = [DEFAULT_BODY_VARIANT]
    for name in BODY_VARIANTS:
        if name != DEFAULT_BODY_VARIANT and variant_pages(config, name):
            out.append(name)
    return out


# --------------------------------------------------------------------------
# Haarvarianter
#
# Samme bok, men malbilder der figuren har kort haar. Er barnet en baby eller
# har kort haar, kan headswappen ikke fikse en mal med langt haar: haaret
# utenfor headmasken blir sydd tilbake uendret, saa det HENGER IGJEN uansett
# prompt og seed (ordre 1423). Loesningen er en mal der haaret alt er kort.
#
# Filnavn som kroppsvariantene: "08(havfrue).png" -> "08(havfrue)kort.png".
# Lages av script/make_shorthair_templates.py.
#
# EN forskjell fra kroppsvarianten: masken byttes IKKE. Hodet staar paa samme
# sted i samme stoerrelse - bare haaret under kjeven er borte - saa den
# manuelle headmasken gjelder uendret. Det er ogsaa poenget: vi lager aldri
# headmasker automatisk.
# --------------------------------------------------------------------------
HAIR_VARIANTS = {
    "langt": {"label": "Langt hår (standard)", "suffix": ""},
    "medium": {"label": "Halvlangt hår", "suffix": "medium"},
    "kort": {"label": "Kort hår", "suffix": "kort"},
}
DEFAULT_HAIR_VARIANT = "langt"

# Bare jentebøkene. Guttebøkene har kortklipte figurer alt - der finnes ikke
# problemet, og en kort-variant ville bare vaere en knapp som ikke gjoer noe.
# Avgjort ved aa se paa forsidemalene, ikke gjettet fra slug-navnet:
# "den-skjulte-styrken" og "skyggedalen" sier ingenting om kjoenn.
HAIR_VARIANT_BOOKS = {
    "den-magiske-bursdagen-jente",
    "den-magiske-reisen-jente",
    "enhjorning",
    "havfruen",
    "kongerikets-hemmelighet",
    "motet-i-hjertet",
    "skyggedalen",
}


def book_has_hair_variants(config: dict) -> bool:
    """Om boka i det hele tatt kan ha haarvarianter."""
    return (config or {}).get("slug") in HAIR_VARIANT_BOOKS


def hair_variant(info: dict) -> str:
    """Hvilken haarvariant ordren er satt til.

    En override paa en guttebok blir ignorert, ikke respektert: da kan en gammel
    override ikke overleve at en bok senere byttes ut.
    """
    if not book_has_hair_variants(info.get("config") or {}):
        return DEFAULT_HAIR_VARIANT
    value = (info.get("overrides") or {}).get("hair_variant")
    return value if value in HAIR_VARIANTS else DEFAULT_HAIR_VARIANT


def hair_variant_filename(filename: str, variant: str) -> str | None:
    """Variantnavnet for en malfil, eller None hvis fila ikke finnes."""
    suffix = HAIR_VARIANTS.get(variant, {}).get("suffix") or ""
    if not filename or not suffix:
        return None
    stem, ext = os.path.splitext(filename)
    candidate = f"{stem}{suffix}{ext}"
    return candidate if os.path.isfile(os.path.join(INPUT_DIR, candidate)) else None


def apply_hair_variant(page: dict, variant: str) -> dict:
    """Bytt malfila til haarvarianten der den finnes. Masken staar."""
    if not page or variant == DEFAULT_HAIR_VARIANT:
        return page
    template = hair_variant_filename(page.get("template_image"), variant)
    if not template:
        return page
    swapped = dict(page)
    swapped["template_image"] = template
    return swapped


def apply_variants(page: dict, body: str, hair: str,
                   skin: str | None = None) -> dict:
    """Kropp foerst, saa haar, saa hud.

    Rekkefoelgen bestemmer filnavnet paa kombinasjonen:
    "08(havfrue)2-4aarkortmork.png". Finnes ikke den fila, faller det siste
    leddet tilbake til malen foer det - samme naadeloese regel som ellers, saa
    en halvferdig serie er brukbar med en gang.
    """
    page = apply_hair_variant(apply_body_variant(page, body), hair)
    return apply_skin_variant(page, skin or DEFAULT_SKIN_VARIANT)


def hair_variant_pages(config: dict, variant: str, body: str | None = None) -> list[str]:
    """Sidene som faktisk HAR denne haarvarianten."""
    body = body or DEFAULT_BODY_VARIANT
    hits = []
    for page in config.get("pages", []):
        base = apply_body_variant(page, body)
        if apply_hair_variant(base, variant) is not base:
            hits.append(page.get("page_key"))
    return hits


def available_hair_variants(config: dict, body: str | None = None) -> list[str]:
    """Haarvariantene denne boka kan tilby, standard alltid foerst."""
    out = [DEFAULT_HAIR_VARIANT]
    if not book_has_hair_variants(config):
        return out
    for name in HAIR_VARIANTS:
        if name != DEFAULT_HAIR_VARIANT and hair_variant_pages(config, name, body):
            out.append(name)
    return out


# --------------------------------------------------------------------------
# Hudvarianter
#
# Samme bok, men malbilder der barnets KROPP har moerk hud. Headswappen bytter
# hodet, saa ansiktet faar barnets egen hudfarge - men hendene, armene, halsen
# og beina ligger utenfor headmasken og blir sydd tilbake uendret. Et moerkt
# barn fikk altsaa lyse hender, og ingen prompt eller seed kunne fikse det.
#
# Filnavn som de andre variantene: "01(magisk-resie-jente).png" ->
# "01(magisk-resie-jente)mork.png". Lages av script/make_darkskin_templates.py.
#
# Masken byttes IKKE - ingenting flytter seg, bare fargen paa huden endrer
# seg - saa den manuelle headmasken gjelder uendret.
# --------------------------------------------------------------------------
# Rekkefoelgen her er knapperekkefoelgen i botten, og den gaar lysest foerst:
# lys -> mixed -> moerk. Suffiksene er ASCII med vilje - filnavnene skal taale
# aa bli sendt gjennom n8n, Drive og Gelato uten at noen koder om ae, oe, aa.
SKIN_VARIANTS = {
    "lys": {"label": "Lys hud (standard)", "suffix": ""},
    "mixed": {"label": "Mixed hud", "suffix": "mixed"},
    "mork": {"label": "Mørk hud", "suffix": "mork"},
}
DEFAULT_SKIN_VARIANT = "lys"


def skin_variant(info: dict) -> str:
    """Hvilken hudvariant ordren er satt til."""
    value = (info.get("overrides") or {}).get("skin_variant")
    return value if value in SKIN_VARIANTS else DEFAULT_SKIN_VARIANT


def skin_variant_filename(filename: str, variant: str) -> str | None:
    """Variantnavnet for en malfil, eller None hvis fila ikke finnes."""
    suffix = SKIN_VARIANTS.get(variant, {}).get("suffix") or ""
    if not filename or not suffix:
        return None
    stem, ext = os.path.splitext(filename)
    candidate = f"{stem}{suffix}{ext}"
    return candidate if os.path.isfile(os.path.join(INPUT_DIR, candidate)) else None


def apply_skin_variant(page: dict, variant: str) -> dict:
    """Bytt malfila til hudvarianten der den finnes. Masken staar."""
    if not page or variant == DEFAULT_SKIN_VARIANT:
        return page
    template = skin_variant_filename(page.get("template_image"), variant)
    if not template:
        return page
    swapped = dict(page)
    swapped["template_image"] = template
    return swapped


def skin_variant_pages(config: dict, variant: str, body: str | None = None,
                       hair: str | None = None) -> list[str]:
    """Sidene som faktisk HAR denne hudvarianten, gitt kropp og haar."""
    body = body or DEFAULT_BODY_VARIANT
    hair = hair or DEFAULT_HAIR_VARIANT
    hits = []
    for page in config.get("pages", []):
        base = apply_hair_variant(apply_body_variant(page, body), hair)
        if apply_skin_variant(base, variant) is not base:
            hits.append(page.get("page_key"))
    return hits


def available_skin_variants(config: dict, body: str | None = None,
                            hair: str | None = None) -> list[str]:
    """Hudvariantene denne boka kan tilby, standard alltid foerst.

    Ingen bokliste her, i motsetning til haaret: hudfarge er ikke bundet til
    kjoennet paa figuren, saa enhver bok kan ha varianten saa snart malene
    finnes. Er de ikke laget, finnes knappen heller ikke.
    """
    out = [DEFAULT_SKIN_VARIANT]
    for name in SKIN_VARIANTS:
        if name != DEFAULT_SKIN_VARIANT and skin_variant_pages(config, name, body, hair):
            out.append(name)
    return out


def normalize_page_key(raw: str) -> str:
    """'3', '03', 'page03', 'forside' -> 'page03' / 'page00'."""
    value = str(raw).strip().lower()
    if value in ("forside", "cover", "front"):
        return "page00"
    if value.startswith("page"):
        value = value[4:]
    if value.isdigit():
        return f"page{int(value):02d}"
    return str(raw).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", required=True)
    ap.add_argument("--refresh", action="store_true",
                    help="hent payload fra n8n på nytt selv om den er cachet")
    args = ap.parse_args()

    info = resolve(args.order, refresh=args.refresh)
    print(f"ordre        {info['order_id']}")
    print(f"execution    {info['execution_id']}")
    print(f"bok          {info['book_slug']}")
    print(f"barn         {info['child_name']}"
          + (f"   (payload: {info['child_name_payload']})"
             if info["child_name"] != info["child_name_payload"] else ""))
    print(f"cover_type   {info['cover_type']}")
    print(f"tekst-script {info['text_script']}")
    print(f"continue     {info['continue_code'] or '(ingen)'}")
    print(f"ordremappe   {info['order_path']}  {'OK' if os.path.isdir(info['order_path']) else 'MANGLER'}")
    print(f"comfy-mappe  {info['comfy_dir']}  {'OK' if os.path.isdir(info['comfy_dir']) else 'MANGLER'}")
    print(f"sider        {len(info['config'].get('pages', []))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

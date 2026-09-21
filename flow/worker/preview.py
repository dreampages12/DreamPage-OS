# -*- coding: utf-8 -*-
"""Forhaandsvisning: melding fra `preview-jobs` -> bok, side, mal og tittel.

Dette er PREVIEW-modus sin motpart til books.py. Den gjoer ett skritt, og
bare ett: oversetter en jobb fra nettbutikken til noeyaktig det side-loekka
alt kan bygge. Selve rendringen er den SAMME koden som boeker bruker
(comfy.render_page + books.build_prompt), fordi en forhaandsvisning som ikke
ser ut som boka er verre enn ingen forhaandsvisning.

Tre ting er hentet fra forhaandsvisnings-PC-en og skal ikke endres uten at
nettbutikken endres samtidig:

  * Koen heter `preview-jobs`, og meldingen har `job_id` + `stored_image_url`
    som eneste PAAKREVDE felt.
  * `asset_type` (eller `/inner/` i callback-URL-en) skiller omslag fra
    innerside.
  * Marked utledes av language/site_language/market, og avgjoer hvilken
    configmappe boka slaas opp i: nb / en / sv / uk.

HVOR PER-BOK-DATAEN LIGGER - og hvorfor den IKKE er kopiert hit:

Forhaandsvisnings-PC-en holdt omslag, maske, workflow, logo og
tittelparametre i egne `preview-config`-filer. Paa denne maskinen finnes alt
det samme fra foer, fordi det er det boka trykkes fra:

    books/<slug>/config.json        mal + headmask per side, workflow,
                                    patchNodes  (page00 ER omslaget)
    config/next_book_titles.json    line1/line2/logo/font/gull per spraak
                                    - filen sier selv "source": "preview-worker"
    flow/text/<lokale>/<bok>-text-<lokale>.py
                                    HISTORIETEKSTEN. Side 7 i forhaands-
                                    visningen er side 7 i boka - alt annet
                                    ville vaert en loegn mot kunden, som
                                    kjoeper boka de ser.

En kopi av de samme verdiene ville vaert en kopi som gikk ut av synk, og da
ville forhaandsvisningen og den trykte boka sagt to forskjellige ting.
Derfor leses de DERFRA, og `config/preview/` inneholder bare det som ikke
finnes noe annet sted:

    config/preview/markets/<market>.json          alias + spraakvalg
    config/preview/books/<market>/<slug>.json     VALGFRI overstyring. For
                                                  innersider sier den HVILKEN
                                                  side som skal vises - ikke
                                                  hva som staar paa den.

Mangler noe, kaster vi. Ingen stille fallback til "en annen bok", "nabo-
spraaket" eller "malen uten logo" - det er noeyaktig feilklassen som ga
ordre 1510 en forside som bare sa "Henry og det".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from paths import (BOOKS, CONFIG, INPUT, PREVIEW_CONFIG,  # noqa: E402
                   preview_comfy_dir, resolve_str)
import books  # noqa: E402
from books import JobError  # noqa: E402

# Markedene forhaandsvisnings-PC-en kjenner. `uk` er britisk engelsk og
# gjenbruker `en` sine malfiler - bare teksten og logomappa er en annen.
MARKETS = ("nb", "en", "sv", "uk")

TITLES_PATH = CONFIG / "next_book_titles.json"


# ---------------------------------------------------------------------------
# Marked og spraak
# ---------------------------------------------------------------------------
def market_for(payload: dict) -> str:
    """nb / en / sv / uk, ut fra language, market og site_language.

    Samme rekkefoelge som "normalize"-noden paa forhaandsvisnings-PC-en:
    svensk foerst, saa britisk, saa amerikansk/generell engelsk, ellers
    norsk. Rekkefoelgen er betydningsfull - `en-gb` ville ellers truffet
    en-grenen og gitt amerikansk tekst til en britisk kunde.
    """
    def low(key: str) -> str:
        return str(payload.get(key) or "").strip().lower().replace("_", "-")

    lang = low("language") or low("language_variant")
    site = low("site_language")
    mkt = low("market")

    if (lang in ("sv", "se", "sv-se", "swedish", "svensk", "svenska")
            or site in ("sv", "sv-se", "se")
            or mkt in ("se", "swe", "sweden", "sverige")):
        return "sv"
    if (lang in ("en-gb", "en-uk", "uk", "gb") or site in ("en-gb", "en-uk")
            or mkt in ("gb", "uk", "united-kingdom")):
        return "uk"
    if lang.startswith("en") or site.startswith("en") or mkt in ("us", "usa", "en"):
        return "en"
    return "nb"


def asset_kind(payload: dict) -> str:
    """"cover" eller "innerpage".

    `asset_type` er det eksplisitte feltet. Callback-URL-en er med fordi
    nettbutikken skiller de to formene paa stien (`/inner/`) og ikke alltid
    setter asset_type - og en innerside som blir rendret som omslag er ikke
    en halvgod forhaandsvisning, den er feil bilde.
    """
    asset_type = str(payload.get("asset_type") or "").lower()
    callback = str(payload.get("preview_callback_url") or "").lower()
    if "inner" in asset_type or "/inner/" in callback:
        return "innerpage"
    return "cover"


# ---------------------------------------------------------------------------
# Configfilene
# ---------------------------------------------------------------------------
def _read_json(path: Path) -> dict:
    with open(path, encoding="utf-8-sig") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise JobError(f"{path} maa inneholde et objekt, ikke "
                       f"{type(data).__name__}")
    return data


def market_config(market: str) -> dict:
    """config/preview/markets/<market>.json.

    En manglende markedsfil er en HARD feil, ikke "da tar vi nb". Et svensk
    preview rendret med norsk tittel ser riktig nok ut til at ingen oppdager
    det foer kunden gjoer.
    """
    if market not in MARKETS:
        raise JobError(f"ukjent marked {market!r}. Lov: {', '.join(MARKETS)}")
    path = PREVIEW_CONFIG / "markets" / f"{market}.json"
    if not path.is_file():
        raise JobError(f"fant ingen markedsconfig for {market!r} ({path}). "
                       f"Uten den vet vi ikke hvilket spraak tittelen skal ha "
                       f"- og en forhaandsvisning paa feil spraak er verre "
                       f"enn ingen.")
    return _read_json(path)


def book_override(market: str, slug: str) -> dict:
    """config/preview/books/<market>/<slug>.json, eller {}.

    Valgfri med vilje: en bok som skal se ut som den trykte boka trenger
    ingen fil her i det hele tatt. Filen finnes for de tre tilfellene som
    IKKE kan utledes: innerside-tekst, en avvikende workflow, og en tittel
    som skal staa annerledes i forhaandsvisningen enn i boka.
    """
    path = PREVIEW_CONFIG / "books" / market / f"{slug}.json"
    return _read_json(path) if path.is_file() else {}


def resolve_slug(payload: dict, mconf: dict) -> str:
    """product_handle/book_title -> bokas MAPPENAVN.

    Aliasene i markedsfila gaar foerst (`regnbuens-skatt` -> `regnbuen`),
    deretter den samme tabellen boekene bruker. Aa gjenbruke
    books.resolve_slug er poenget: den kan alle handles, alle titler paa tre
    spraak og jente/gutt-utgavene, og den skal ikke finnes i to utgaver som
    kan gli fra hverandre.
    """
    handle = str(payload.get("product_handle") or payload.get("book_slug") or "")
    title = str(payload.get("book_title") or "")
    aliases = {str(k).strip().lower(): str(v)
               for k, v in (mconf.get("aliases") or {}).items()}

    key = handle.strip().lower()
    if key and key in aliases:
        handle = aliases[key]
    elif not handle and title.strip().lower() in aliases:
        handle = aliases[title.strip().lower()]

    slug = books.resolve_slug({"book_slug": handle, "book_title": title,
                               "gender": payload.get("gender")})
    if not (BOOKS / slug / "config.json").is_file():
        raise JobError(
            f"ukjent bok {slug!r} (product_handle="
            f"{payload.get('product_handle')!r}, book_title={title!r}). "
            f"books/{slug}/config.json finnes ikke. En ukjent bok er en hard "
            f"feil med vilje - alternativet er en forhaandsvisning av en "
            f"ANNEN bok.")
    return slug


# ---------------------------------------------------------------------------
# Tittelparametrene
# ---------------------------------------------------------------------------
def _genitive(name: str) -> str:
    """{child_name_s}: "Emma" -> "Emmas", "Mats" -> "Mats'".

    Norsk, svensk og engelsk gjoer det likt nok: et navn som alt slutter paa
    s/x/z faar apostrof i stedet for enda en s.
    """
    text = str(name or "").strip()
    if not text:
        return text
    return text + ("'" if text[-1].lower() in "sxz" else "s")


def _fill(text: str, child_name: str) -> str:
    return (str(text or "")
            .replace("{child_name_s}", _genitive(child_name))
            .replace("{child_name}", str(child_name or "")))


def _book_titles() -> dict:
    if not TITLES_PATH.is_file():
        return {}
    try:
        return _read_json(TITLES_PATH)
    except (OSError, ValueError):
        return {}


# Feltene forhaandsvisnings-PC-ens bokfil har paa toppnivaa. De speiler
# flaggene render-title-line2logo.py tar, og listen staar her slik at en fil
# derfra kan legges rett inn uten aa doepes om.
TITLE_KEYS = (
    "mode", "line1", "line2", "line2_image", "font_small", "font_large",
    "font_small_path", "font_large_path", "gold", "shadow", "top_margin",
    "line_spacing", "logo_scale", "logo_x_offset", "glow_color",
    "glow_opacity", "glow_radius_scale", "logo_shadow_opacity",
    "bottom_logo", "bottom_logo_scale", "bottom_logo_margin",
    "bottom_logo_x_offset", "line1_prefix", "line1_suffix",
)


def title_params(slug: str, title_lang: str, override: dict,
                 child_name: str) -> dict:
    """Alt render-title trenger, som ferdig utfylte verdier.

    Grunnlaget er `config/next_book_titles.json` - den samme filen boka sin
    egen "fortsett eventyret"-forside bruker, og den filen sier selv
    `"source": "preview-worker"`. Den er altsaa ikke en etterligning av
    forhaandsvisningen; den ER den, flyttet hit.

    Bokfila under config/preview/books/ kan overstyre hva som helst, og
    bruker da forhaandsvisnings-PC-ens egne feltnavn.
    """
    base = dict((_book_titles().get(slug) or {}).get(title_lang) or {})
    over = dict(override.get("title") or {})
    for key in TITLE_KEYS:
        if key in override:
            over.setdefault(key, override[key])

    params = {**base, **over}
    # Stiene i next_book_titles.json er absolutte `C:/DreamPage-OS/...` fra
    # den gangen alt fantes paa én Windows-maskin. Oversettes til denne
    # maskinens rot; paa Windows er det en identitet - se flow/paths.py.
    for key in ("line2_image", "font_small_path", "font_large_path",
                "bottom_logo"):
        if params.get(key):
            params[key] = resolve_str(params[key])
    if not params:
        raise JobError(
            f"boka {slug!r} har ingen tittelparametre for spraaket "
            f"{title_lang!r}. De hentes fra config/next_book_titles.json og "
            f"kan overstyres i config/preview/books/<marked>/{slug}.json. "
            f"Uten dem ville forsiden blitt rendret uten tittel.")

    # line1 er enten en ferdig mal fra bokfila ("{child_name} og"), eller
    # satt sammen av prefiks + navn + suffiks slik boka gjoer det.
    if params.get("line1"):
        line1 = _fill(params["line1"], child_name)
    else:
        line1 = " ".join(part for part in (
            str(params.get("line1_prefix") or "").strip(),
            str(child_name or "").strip(),
            str(params.get("line1_suffix") or "").strip(),
        ) if part)

    out = dict(params)
    out["line1"] = line1
    out["line2"] = _fill(params.get("line2") or "", child_name)
    out["line2_image"] = str(params.get("line2_image") or "").strip()
    return out


# ---------------------------------------------------------------------------
# Jobben
# ---------------------------------------------------------------------------
def face_filename(job_id: str) -> str:
    """`preview-<job_id>.jpg` i ComfyUI sin input-mappe.

    Prefikset er ikke pynt: en bokordre legger barnebildet sitt som
    `<job_key>.jpg` i den SAMME mappa, og en job_id fra nettbutikken kan
    kollidere med et ordrenummer. To jobber som deler ansiktsfil ville gitt
    feil barn paa et bilde - og det er en feil ingen oppdager, fordi ingen
    kjenner igjen et barn de aldri har sett.
    """
    return f"preview-{job_id}.jpg"


def build_job(payload: dict) -> dict:
    """Payload fra koen -> alt resten av preview-pipelinen trenger.

    Kaster JobError paa alt som mangler. En preview-jobb er billig aa kjoere
    om igjen, men umulig aa rette i ettertid: bildet er alt vist til kunden.
    """
    job_id = str(payload.get("job_id") or payload.get("job_key") or "").strip()
    if not job_id:
        raise JobError("preview-meldingen mangler job_id")
    image_url = str(payload.get("stored_image_url") or "").strip()
    if not image_url:
        raise JobError(f"preview-jobb {job_id} mangler stored_image_url - det "
                       f"er barnets bilde, og uten det finnes det ingenting "
                       f"aa sette inn i malen")

    market = market_for(payload)
    mconf = market_config(market)
    slug = resolve_slug(payload, mconf)
    override = book_override(market, slug)
    kind = asset_kind(payload)
    child_name = str(payload.get("child_name") or "").strip()

    config = books.load_config(slug)
    title_lang = str(override.get("title_lang")
                     or mconf.get("title_lang") or "nb")
    # Hvilket tekstscript historien hentes fra. Samme utvalgskjede som boka
    # bruker (books.select_text_script), saa en innerside-forhaandsvisning i
    # et marked faar noeyaktig den teksten boka trykkes med der.
    script_language = str(override.get("script_language")
                          or mconf.get("script_language") or "nb")
    text_script = books.select_text_script(config, script_language)

    return {
        "job_id": job_id,
        "job_key": job_id,
        "book_slug": slug,
        "asset_kind": kind,
        "market": market,
        "title_lang": title_lang,
        "script_language": script_language,
        "text_script": text_script,
        "logo_locale": str(override.get("logo_locale")
                           or mconf.get("logo_locale") or "nb"),
        "child_name": child_name,
        "gender": str(payload.get("gender") or ""),
        "image_url": image_url,
        "face_filename": face_filename(job_id),
        "face_image": str(INPUT / face_filename(job_id)).replace("\\", "/"),
        "session_id": str(payload.get("dp_session_id") or "").strip(),
        "callback_url": str(payload.get("preview_callback_url") or "").strip(),
        "preview_token": str(payload.get("preview_token") or ""),
        "book_title": str(payload.get("book_title") or ""),
        "config": config,
        "market_config": mconf,
        "override": override,
        "title": title_params(slug, title_lang, override, child_name),
        # Relativ sti under output/, slik ComfyUI sin filename_prefix vil ha
        # den. Egen mappe per jobb - se paths.preview_dir.
        "output_dir": f"preview/{job_id}/comfy",
        "payload": payload,
    }


def comfy_output_dir(job: dict) -> Path:
    return preview_comfy_dir(job["job_id"])


# ---------------------------------------------------------------------------
# Siden som skal rendres
# ---------------------------------------------------------------------------
def _page_from_book(config: dict, page_key: str, slug: str) -> dict:
    for page in config.get("pages") or []:
        if str(page.get("page_key")) == page_key:
            return dict(page)
    keys = ", ".join(str(p.get("page_key")) for p in (config.get("pages") or []))
    raise JobError(f"boka {slug!r} har ingen side {page_key!r}. Sidene i "
                   f"books/{slug}/config.json er: {keys or 'ingen'}")


def build_page(job: dict) -> dict:
    """Den ENE siden en preview-jobb rendrer.

    Omslag er alltid `page00` - forsiden i bokas egen config, altsaa
    noeyaktig den malen boka trykkes med.

    Innerside er den siden bokfila under config/preview/ peker paa. Det
    ENESTE den sier er HVILKEN side - hvilken scene som selger boka er en
    redaksjonell avgjoerelse og kan ikke utledes. Hva som STAAR paa sida
    kommer fra bokas eget tekstscript: side 7 i forhaandsvisningen er side 7
    i boka. Mangler seksjonen, feiler jobben med en setning som sier hvor
    sidevalget skal legges inn.
    """
    slug = job["book_slug"]
    config = job["config"]
    override = job["override"]
    workflow_file = (config.get("workflowApi")
                     or (config.get("workflowApis") or {}).get("default")
                     or "workflow_api.json")
    patch_nodes = dict(config.get("patchNodes")
                       or config.get("innerPatchNodes") or {})
    for key in ("template", "face", "output"):
        if not patch_nodes.get(key):
            raise JobError(f"config for {slug} mangler patchNodes.{key}")

    if job["asset_kind"] == "innerpage":
        inner = dict(override.get("innerpage") or {})
        if not inner:
            raise JobError(
                f"boka {slug!r} har ingen innerside-forhaandsvisning i marked "
                f"{job['market']!r}. Legg en \"innerpage\"-seksjon med "
                f"\"page_key\" i config/preview/books/{job['market']}/"
                f"{slug}.json. Teksten hentes fra bokas eget tekstscript - "
                f"det som mangler er hvilken SIDE som skal vises.")
        page_key = str(inner.get("page_key") or "").strip()
        if not page_key:
            raise JobError(f"innerpage for {slug} mangler page_key")
        base = _page_from_book(config, page_key, slug)
        template = str(inner.get("image") or base.get("template_image") or "")
        mask = str(inner.get("hair_mask") or base.get("mask_image") or "")
    else:
        page_key = "page00"
        base = _page_from_book(config, page_key, slug)
        template = str(override.get("cover_image")
                       or base.get("template_image") or "")
        mask = str(override.get("hair_mask") or base.get("mask_image") or "")

    if not template:
        raise JobError(f"{slug}/{page_key} har ingen template_image")

    # Uttrykksvarianter (smil/trist/glad) lages ikke for forhaandsvisninger:
    # én side, ett bilde, tjue sekunder. Originalbildet brukes alltid, og det
    # staar her slik at det er et VALG og ikke ser ut som en glemt linje.

    # Egen workflow for forhaandsvisning, hvis noen har satt en. Absolutt sti
    # virker: books.build_prompt setter den sammen med `BOOKS / slug /`, og
    # pathlib lar en absolutt sti vinne.
    wf = (override.get("workflow_api")
          or (job["market_config"].get("defaults") or {}).get("workflow_api")
          or workflow_file)

    return {
        "page_key": page_key,
        "template_image": template,
        "mask_image": mask,
        "face_image": job["face_filename"],
        "workflow_role": "frontpage" if page_key == "page00" else "page",
        "workflow_api_file": str(wf),
        "patch_nodes": patch_nodes,
    }


def innerpage_source(job: dict, page: dict) -> dict:
    """Hvor historieteksten til et innerside-preview kommer FRA.

    Ikke hva den sier - det vet bare boka. Dette er tekstscriptet og
    malfilnavnet, og `flow/pre/render-innerpage.py` slaar opp resten ved aa
    kalle bokas egen `build_pages()` og `render_page()`.

    Malfilnavnet er noekkelen mellom de to: `books/<slug>/config.json` kaller
    det `template_image`, tekstscriptet kaller det `filename`, og det er den
    samme strengen ("07(dyreparken).png"). Da kan ingen av dem endres uten at
    den andre foelger med.
    """
    script = str(job.get("text_script") or "").strip()
    if not script:
        raise JobError(
            f"boka {job['book_slug']!r} har ingen tekstscript for spraaket "
            f"{job['script_language']!r} (textScripts i "
            f"books/{job['book_slug']}/config.json). Uten det finnes det "
            f"ingen historietekst, og en innerside-forhaandsvisning uten "
            f"tekst er en tom side.")
    if not Path(script).is_file():
        raise JobError(
            f"tekstscriptet for {job['book_slug']!r} ({job['script_language']}) "
            f"finnes ikke paa disk: {script}")
    return {"script": script, "filename": page["template_image"]}

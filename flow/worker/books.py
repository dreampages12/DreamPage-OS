# -*- coding: utf-8 -*-
"""Bok- og jobbforstaaelse: payload -> bokmappe, spraak, sider, ComfyUI-prompt.

Portert fra n8n-nodene "Load Book Config", "Parse Config", "Pages Config" og
"Build Page Prompt". Oppfoerselen skal vaere identisk - der den ikke er, staar
det hvorfor i en kommentar.

Nøklene som IKKE maa endres (dyrekjoept domenekunnskap):

  * `job_key`, ikke `order_id`, er mappe- og filnoekkelen. En WooCommerce-ordre
    kan inneholde flere boeker; da har alle samme order_id ("1411") og bare
    job_key skiller dem ("1411-b1", "1411-b2").
  * Sidenoeklene (page00..page15) er LIKE i alle boeker. Derfor maa "er siden
    ferdig?" kun se i ordrens egen output-mappe.
  * `page99_next` er forsidebildet til "fortsett eventyret"-siden. Den er ikke
    en vanlig side og teller ikke i expectedInnerPages.
  * `continue_code` lages alltid i WordPress og faller aldri tilbake paa noe.
  * Bare hardcover selges, men softcover er default i koden - cover_type
    sendes derfor alltid eksplisitt.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from paths import BOOKS, INPUT, OUTPUT  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from book_titles import (  # noqa: E402
    GENDERED_TITLES, HANDLE_TO_SLUG, TITLE_TO_SLUG, normalize,
)


class JobError(Exception):
    """Feil som skyldes jobben, ikke systemet. Skal ikke retries."""


# ---------------------------------------------------------------------------
# Spraakvalg
#
# Ordrett fra chooseScriptLanguage() i "Load Book Config". Rekkefoelgen er
# betydningsfull: nn foer nb, fordi 'nn-no' ellers ville truffet nb-grenen.
# ---------------------------------------------------------------------------
def choose_script_language(language: str, site_language: str, market: str) -> str:
    lang = str(language or "").strip().lower().replace("_", "-")
    site = str(site_language or "").strip().lower().replace("_", "-")
    mkt = str(market or "").strip().lower()

    if lang in ("nn", "nynorsk") or site in ("nn", "nn-no"):
        return "nn"
    if (lang in ("sv", "se", "sv-se", "swedish", "svensk", "svenska")
            or site in ("sv", "sv-se", "se")
            or mkt in ("se", "swe", "sweden", "sverige")):
        return "sv"
    # "bokmal" med og uten aa: noden hadde to mangled varianter av samme ord.
    if lang in ("nb", "no", "bokmal", "bokmål") or site in ("nb-no", "no"):
        return "nb"
    if lang in ("en-gb", "en-uk") or site in ("en-gb", "en-uk") or mkt in ("gb", "uk"):
        return "en-GB"
    if lang == "en-us" or site == "en-us" or mkt in ("us", "usa"):
        return "en-US"
    if lang == "en":
        return "en-GB" if (mkt in ("gb", "uk") or site == "en-gb") else "en-US"
    return "nb"


# ---------------------------------------------------------------------------
# Bokmappe
# ---------------------------------------------------------------------------
_GENDER_GIRL = {"girl", "jente", "flicka", "tjej"}
_GENDER_BOY = {"boy", "gutt", "pojke", "kille"}


def _resolve_gendered(gender: str) -> str:
    key = str(gender or "").strip().lower()
    if key in _GENDER_GIRL:
        return "den-magiske-reisen-jente"
    if key in _GENDER_BOY:
        return "den-magiske-reisen-gutt"
    raise JobError("kan ikke avgjoere hvilken utgave av den-magiske-reisen: "
                   f"gender mangler eller er ukjent ({gender!r})")


def resolve_slug(payload: dict) -> str:
    """Bokas MAPPENAVN, fra handle eller tittel.

    Handle (`book_slug` fra WooCommerce) vinner over tittel. Det er ogsaa
    grunnen til at de 16 oedelagte noeklene i n8n sin tittel-tabell aldri ble
    oppdaget: handle-veien redder ordren foer tittelen proeves.
    """
    handle = normalize(payload.get("book_slug") or "")
    title = normalize(payload.get("book_title") or payload.get("book_tilte") or "")

    slug = ""
    if handle:
        if handle in ("den-magiske-reisen", "den-magiske-reisen-jente"):
            slug = _resolve_gendered(payload.get("gender"))
        else:
            slug = HANDLE_TO_SLUG.get(handle, handle)

    if not slug and title in GENDERED_TITLES:
        slug = _resolve_gendered(payload.get("gender"))
    if not slug:
        slug = TITLE_TO_SLUG.get(title, "")

    if not slug and title:
        # Siste utvei: slugify tittelen. Treffer sjelden, men er bedre enn
        # aa stoppe en betalt ordre paa en bok som nettopp er lagt til.
        slug = re.sub(r"-+", "-", re.sub(r"[^a-z0-9-]", "",
                                         title.replace(" ", "-"))).strip("-")

    if not slug:
        raise JobError(f"kan ikke avgjoere bokmappe. book_title={payload.get('book_title')!r} "
                       f"book_slug={payload.get('book_slug')!r}")
    return slug


def load_config(slug: str) -> dict:
    """books/<slug>/config.json. utf-8-sig fordi filene har BOM."""
    path = BOOKS / slug / "config.json"
    if not path.is_file():
        raise JobError(f"fant ingen config.json for bok {slug!r} ({path})")
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def select_text_script(config: dict, script_language: str) -> str:
    """Samme fallback-kjede som "Parse Config"-noden."""
    scripts = config.get("textScripts") or {}
    lang = str(script_language or "nb")
    for key in (lang, lang.lower(),
                "en-gb" if lang == "en-GB" else None,
                "en-us" if lang == "en-US" else None,
                "en" if lang.startswith("en") else None,
                "nb"):
        if key and scripts.get(key):
            return scripts[key]
    return config.get("textScript") or ""


# ---------------------------------------------------------------------------
# Jobbkontekst
# ---------------------------------------------------------------------------
def build_job(payload: dict) -> dict:
    """Payload fra koen -> alt resten av pipelinen trenger.

    Erstatter "Parse Job" + "Edit Fields" + "Load Book Config" + "Parse Config"
    i én funksjon. Feltnavnene er beholdt slik n8n hadde dem, fordi
    tekstscriptene, build_last_page.py og dp_bot.py leser dem.
    """
    job_key = str(payload.get("job_key") or payload.get("order_id") or "").strip()
    if not job_key:
        raise JobError("payloaden mangler baade job_key og order_id")

    language = str(payload.get("language") or "nb").strip()
    site_language = str(payload.get("site_language") or "no").strip()
    market = str(payload.get("market") or "no").strip()
    script_language = choose_script_language(language, site_language, market)

    slug = resolve_slug(payload)
    config = load_config(slug)
    text_script = select_text_script(config, script_language)
    if text_script:
        # Nedstroems kode leser config["textScript"], ikke textScripts.
        config = dict(config)
        config["textScript"] = text_script

    face_image = str(INPUT / f"{job_key}.jpg").replace("\\", "/")

    return {
        # order_id heter order_id gjennom hele pipelinen, men INNEHOLDER
        # job_key. Slik gjorde n8n det ("Edit Fields": order_id = job_key ||
        # order_id), og alle mappenavn, filnavn og claim-filer bygger paa det.
        # Aa doepe om feltet naa ville brutt dp_bot, reprint_order og
        # finish_order samtidig.
        "order_id": job_key,
        "job_key": job_key,
        "woo_order_id": str(payload.get("order_id") or "").strip(),
        "book_slug": slug,
        "child_name": payload.get("child_name") or "",
        "face_image": face_image,
        "face_filename": f"{job_key}.jpg",
        "cover_type": payload.get("cover_type") or "hardcover",
        "shipping": payload.get("shipping") or {},
        "customer": payload.get("customer") or {},
        "book_title": payload.get("book_title") or payload.get("book_tilte") or "",
        "language": language or "nb",
        "site_language": site_language or "no",
        "market": market or "no",
        "script_language": script_language,
        "gender": payload.get("gender") or "",
        "image_url": payload.get("image_url") or "",

        # Fortsett-eventyret. continue_code lages ALLTID i WordPress og skal
        # aldri gjettes eller regenereres - en reprint maa bruke samme kode,
        # for trykk er permanent.
        "continue_code": str(payload.get("continue_code") or "").strip(),
        "continue_url": payload.get("continue_url") or "",
        "continue_coupon": payload.get("continue_coupon") or "",
        "continue_callback": payload.get("continue_callback") or "",
        "next_book_id": payload.get("next_book_id") or "",
        "next_book_slug": (payload.get("next_book_slug")
                           or (payload.get("next_book") or {}).get("slug")
                           or config.get("nextBookSlug") or ""),
        "next_book_title": (payload.get("next_book_title")
                            or (payload.get("next_book") or {}).get("title")
                            or config.get("nextBookTitle") or ""),

        "config": config,
        "order_path": str(BOOKS / slug / "orders" / job_key).replace("\\", "/"),
        # Relativ sti under output/, slik ComfyUI sin filename_prefix vil ha den.
        "output_dir": f"{config.get('comfyOutputPrefix', slug + '/orders')}/{job_key}/comfy",
        "payload": payload,
    }


# ---------------------------------------------------------------------------
# Sidene
# ---------------------------------------------------------------------------
# "glad" kom 18.09.2026 (fotballstjernen side 14). Et uttrykk som ikke
# staar her, gir originalbildet uansett hva som ligger i input/.
FACE_EXPRESSIONS = ("noytral", "smil", "trist", "glad")


def face_for(face_filename: str, expression: str | None) -> str:
    """Uttrykksvarianten av barnebildet, eller originalen.

    build_face_variants.py legger <job_key>-<uttrykk>.jpg i input/. Mangler
    filen - scriptet feilet, eller en gammel ordre kjoeres om - brukes
    originalbildet. En side skal aldri feile fordi et uttrykk mangler.
    """
    base = str(face_filename or "")
    expr = str(expression or "noytral")
    stem = re.sub(r"\.[^.]+$", "", base)
    if not stem or expr not in FACE_EXPRESSIONS:
        return base
    candidate = f"{stem}-{expr}.jpg"
    return candidate if (INPUT / candidate).is_file() else base


def build_pages(job: dict) -> list[dict]:
    """Sidene som skal renderes, i rekkefoelge, page99_next til slutt."""
    config = job["config"]
    workflow_file = (config.get("workflowApi")
                     or (config.get("workflowApis") or {}).get("default")
                     or (config.get("workflowApis") or {}).get("innerpages")
                     or (config.get("workflowApis") or {}).get("frontpage")
                     or "workflow_api.json")
    patch_nodes = (config.get("patchNodes") or config.get("innerPatchNodes")
                   or {"template": "95", "face": "10", "output": "81"})
    for key in ("template", "face", "output"):
        if not patch_nodes.get(key):
            raise JobError(f"config for {job['book_slug']} mangler patchNodes.{key}")

    pages = []
    for page in config.get("pages", []):
        pages.append({
            "page_key": page.get("page_key"),
            "template_image": page.get("template_image"),
            "mask_image": page.get("mask_image"),
            "face_image": face_for(job["face_filename"], page.get("face_expression")),
            "workflow_role": "page",
            # Per side, med bokens fil som standard. build_prompt leste alt
            # denne noekkelen, men ingenting satte den - saa en bok kunne ikke
            # gi ÉN side en annen workflow. Hestestjernen trenger det:
            # forsiden bruker en variant som oppskalerer malen FOER inpaint,
            # og den varianten er maalt DAARLIGERE paa sidene der hodet er
            # lite. Se _workflow_note i den bokas config.
            "workflow_api_file": (page.get("workflow_api_file")
                                  or workflow_file),
            "patch_nodes": dict(patch_nodes),
        })
    if not pages:
        raise JobError(f"config for {job['book_slug']} har ingen sider")

    pages += _continue_page(job, workflow_file, patch_nodes)
    return pages


def _continue_page(job: dict, workflow_file: str, patch_nodes: dict) -> list[dict]:
    """page99_next - forsiden til NESTE bok, med DENNE ordrens barnebilde.

    Arver hele side-loekka (dispatch, polling, timeout, retry) ved aa vaere et
    helt vanlig element i listen. Uten continue_code skjer ingenting.

    Et oppsalg skal ALDRI blokkere en betalt ordre, saa alt her svelger sine
    egne feil - akkurat som try/catch-en i "Pages Config" gjorde.
    """
    code = str(job.get("continue_code") or "").strip()
    next_slug = str(job.get("next_book_slug") or "").strip()
    if not code or not next_slug or next_slug == job["book_slug"]:
        return []
    try:
        next_cfg = load_config(next_slug)
        front = next((p for p in next_cfg.get("pages", [])
                      if p.get("page_key") == "page00"), None)
        if not front:
            raise JobError(f"config for {next_slug} mangler page00")
        return [{
            "page_key": "page99_next",
            "template_image": front.get("template_image"),
            "mask_image": front.get("mask_image"),
            "face_image": face_for(job["face_filename"], front.get("face_expression")),
            "workflow_role": "frontpage",
            "workflow_api_file": ((next_cfg.get("workflowApis") or {}).get("frontpage")
                                  or next_cfg.get("workflowApi") or workflow_file),
            "patch_nodes": dict(next_cfg.get("patchNodes")
                                or next_cfg.get("innerPatchNodes") or patch_nodes),
            "optional": True,
        }]
    except Exception as exc:                      # noqa: BLE001
        return [{"page_key": "page99_next", "skipped": True,
                 "skip_reason": f"hopper over neste-forside for {next_slug}: {exc}"}]


# ---------------------------------------------------------------------------
# ComfyUI-prompten
#
# Portert fra "Build Page Prompt". Auto-deteksjonen av patch-noder ser
# overdrevet ut, og er det ikke: 24 boeker har hver sin workflow_api.json, de
# er redigert i ComfyUI sitt GUI over et halvt aar, og nodeIDene i config
# stemmer ikke alltid. Uten deteksjonen maatte hver bok rettes for haand hver
# gang noen flyttet en node.
# ---------------------------------------------------------------------------
def _has_inputs(prompt: dict, node_id: Any) -> bool:
    return bool(node_id and prompt.get(str(node_id), {}).get("inputs") is not None)


def _has_input(prompt: dict, node_id: Any, name: str) -> bool:
    return _has_inputs(prompt, node_id) and name in prompt[str(node_id)]["inputs"]


def _class_type(prompt: dict, node_id: Any) -> str:
    return str(prompt.get(str(node_id), {}).get("class_type") or "")


def _is_ref(value: Any, node_id: Any) -> bool:
    return isinstance(value, list) and value and str(value[0]) == str(node_id)


def _reference_score(prompt: dict, node_id: Any, class_matcher=None) -> int:
    score = 0
    for node in prompt.values():
        if not isinstance(node, dict) or not node.get("inputs"):
            continue
        if class_matcher and not class_matcher(str(node.get("class_type") or "")):
            continue
        for value in node["inputs"].values():
            if _is_ref(value, node_id):
                score += 1
    return score


def _load_image_nodes(prompt: dict) -> list[str]:
    return [nid for nid, node in prompt.items()
            if isinstance(node, dict) and node.get("inputs") is not None
            and node.get("class_type") == "LoadImage" and "image" in node["inputs"]]


def _detect_output(prompt: dict, configured: Any) -> str:
    if _has_input(prompt, configured, "filename_prefix"):
        return str(configured)
    candidates = [nid for nid, node in prompt.items()
                  if isinstance(node, dict) and node.get("inputs") is not None
                  and "filename_prefix" in node["inputs"]]
    save = next((nid for nid in candidates if _class_type(prompt, nid) == "SaveImage"), None)
    return str(save or (candidates[0] if candidates else ""))


def _template_consumer(class_type: str) -> bool:
    """Noder som bare en MAL kan vaere input til."""
    return (class_type in ("InpaintCropImproved", "ImpactSimpleDetectorSEGS",
                           "SAMDetectorCombined")
            or "GroundingDino" in class_type or "Segment" in class_type)


def _detect_template(prompt: dict, configured: Any, exclude: Any) -> str:
    if _has_input(prompt, configured, "image"):
        return str(configured)
    loaders = [n for n in _load_image_nodes(prompt) if str(n) != str(exclude or "")]
    # Malen er den LoadImage som flest maskerings-/beskjaeringsnoder bruker.
    loaders.sort(key=lambda n: (_reference_score(prompt, n, _template_consumer) * 100
                                + _reference_score(prompt, n)), reverse=True)
    return str(loaders[0]) if loaders else ""


def _detect_face(prompt: dict, configured: Any, exclude: Any) -> str:
    if _has_input(prompt, configured, "image"):
        return str(configured)
    loaders = [n for n in _load_image_nodes(prompt) if str(n) != str(exclude or "")]
    flux = next((n for n in loaders
                 if _reference_score(prompt, n, lambda t: "FluxKontext" in t) > 0), None)
    if flux:
        return str(flux)
    # Ansiktet er den MINST refererte: malen gaar til mange noder, ansiktet
    # til én.
    loaders.sort(key=lambda n: _reference_score(prompt, n))
    return str(loaders[0]) if loaders else ""


def _detect_mask(prompt: dict, configured: Any, template: Any, face: Any) -> str:
    """Headmask-loaderen, hvis workflowen HAR en.

    Boeker med auto-maske (SAM) har ingen, og da er dette et no-op. Vi lager
    aldri headmasker automatisk - de er tegnet for haand.
    """
    if _has_input(prompt, configured, "image"):
        return str(configured)
    for nid, node in prompt.items():
        if (isinstance(node, dict) and node.get("class_type") == "LoadImageMask"
                and "image" in (node.get("inputs") or {})):
            return str(nid)
    # Ellers: en LoadImage der ALLE referansene til den gaar til en
    # mask-input. Da kan den ikke vaere noe annet enn masken.
    for nid, node in prompt.items():
        if (not isinstance(node, dict) or node.get("class_type") != "LoadImage"
                or "image" not in (node.get("inputs") or {})):
            continue
        if str(nid) in (str(template), str(face)):
            continue
        refs = mask_refs = 0
        for other in prompt.values():
            if not isinstance(other, dict) or not other.get("inputs"):
                continue
            for name, value in other["inputs"].items():
                if _is_ref(value, nid):
                    refs += 1
                    if name == "mask":
                        mask_refs += 1
        if refs > 0 and refs == mask_refs:
            return str(nid)
    return ""


def build_prompt(job: dict, page: dict) -> tuple[dict, dict]:
    """(ComfyUI-prompt, faktisk brukte patch-noder).

    Kaster JobError hvis en paakrevd node ikke finnes - det er en feil i
    bokens workflow_api.json, og aa gjette videre ville produsert en side uten
    barnets ansikt.
    """
    wf_path = BOOKS / job["book_slug"] / (page.get("workflow_api_file") or "workflow_api.json")
    if not wf_path.is_file():
        raise JobError(f"fant ingen workflow: {wf_path}")
    with open(wf_path, encoding="utf-8-sig") as fh:
        prompt = json.load(fh)

    configured = dict(page.get("patch_nodes") or {})
    pn = dict(configured)
    pn["output"] = _detect_output(prompt, pn.get("output"))
    pn["template"] = _detect_template(prompt, pn.get("template"), pn.get("face"))
    pn["face"] = _detect_face(prompt, pn.get("face"), pn["template"])

    corrections = []
    for key, needed in (("template", "image"), ("face", "image"),
                        ("output", "filename_prefix")):
        if not _has_input(prompt, pn.get(key), needed):
            raise JobError(
                f"{wf_path.name} for {job['book_slug']}: fant ingen {key}-node med "
                f"input {needed!r}. config sa {configured.get(key) or 'ingenting'}")
        if configured.get(key) and str(configured[key]) != str(pn[key]):
            corrections.append(f"{key} {configured[key]} -> {pn[key]}")

    prompt[pn["template"]]["inputs"]["image"] = page["template_image"]
    prompt[pn["face"]]["inputs"]["image"] = page["face_image"]
    # Sidefilen: <output_dir>/<page_key> -> ComfyUI legger til _00001_.png
    prompt[pn["output"]]["inputs"]["filename_prefix"] = \
        f"{job['output_dir']}/{page['page_key']}"

    pn["mask"] = _detect_mask(prompt, pn.get("mask"), pn["template"], pn["face"])
    if pn["mask"] and page.get("mask_image") and _has_inputs(prompt, pn["mask"]):
        prompt[pn["mask"]]["inputs"]["image"] = page["mask_image"]

    # bong_tangent finnes ikke i denne ComfyUI-byggen. n8n byttet den stille
    # til ddim_uniform i stedet for aa la prompten feile; samme her.
    for node in prompt.values():
        if (isinstance(node, dict) and isinstance(node.get("inputs"), dict)
                and node["inputs"].get("scheduler") == "bong_tangent"):
            node["inputs"]["scheduler"] = "ddim_uniform"

    prompt_text = page.get("prompt_text") or job["config"].get("innerPrompt") or ""
    if pn.get("prompt") and prompt_text:
        if not _has_inputs(prompt, pn["prompt"]):
            raise JobError(f"{wf_path.name} mangler prompt-noden {pn['prompt']} "
                           f"for {job['book_slug']}")
        inputs = prompt[str(pn["prompt"])]["inputs"]
        if "text" in inputs:
            inputs["text"] = prompt_text
        elif "prompt" in inputs:
            inputs["prompt"] = prompt_text

    pn["_corrections"] = corrections
    return prompt, pn


def comfy_output_dir(job: dict) -> Path:
    """Den ABSOLUTTE mappa ComfyUI skriver sidene til.

    Og den eneste mappa "er siden ferdig?" faar lov aa se i. Sidenoeklene er
    like i alle boeker, saa da to samtidige ordre 14.09.2026 fikk se i
    hverandres mapper, hoppet de over hverandres sider - bildene var ikke
    feil, de var borte.
    """
    return OUTPUT / job["output_dir"].replace("/", os.sep)

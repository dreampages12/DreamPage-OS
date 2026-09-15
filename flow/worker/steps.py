# -*- coding: utf-8 -*-
"""Stegene. Én funksjon per steg, alle med samme signatur.

    def step(ctx: Context) -> dict

`ctx` er jobben under arbeid; returverdien blir lagret som stegets `detail` i
jobb-DB-en og er det man ser i panelet. Kaster funksjonen JobError, er det
jobbens feil og den retries ikke. Kaster den ComfyError eller noe annet, er
det systemets feil og retry-regelen i pipeline.py gjelder.

Rekkefoelge og retry ligger i pipeline.py, ikke her. Det er hele poenget med
at pipelinen er data.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from paths import (BOOKS, FACE_VARIANTS, INPUT, ORDERS_STATE, TOOLS,  # noqa: E402
                   order_input_dir, order_pdf_dir, order_state_path)
import books  # noqa: E402
import comfy as comfy_mod  # noqa: E402
from books import JobError  # noqa: E402

PYTHON = sys.executable


@dataclass
class Context:
    """Alt et steg trenger, og alt de deler."""
    job_key: str
    payload: dict
    job: dict = field(default_factory=dict)        # books.build_job()
    pages: list = field(default_factory=list)
    log: object = None
    store: object = None
    comfy: object = None
    # Settes av runneren mellom hvert steg; et langt steg skal se den.
    cancelled: callable = lambda: False

    def progress(self, done: int, total: int | None = None) -> None:
        if self.store:
            self.store.set_progress(self.job_key, done, total)


# ---------------------------------------------------------------------------
# 1. Forstaa jobben
# ---------------------------------------------------------------------------
def validate_job(ctx: Context) -> dict:
    """Payload -> bok, spraak, sider. Avviser en ubyggbar bok MED EN GANG.

    Dette steget finnes i denne formen paa grunn av ordre 1517: kunden kjoepte
    "Hestestjernen" 2026-09-15 kl 19:00, books/hestestjernen/ har ingen
    config.json, og n8n doede i "Read Config File" etter 1,3 sekunder - og
    skrev `status = success`. Ingen ble varslet, og kunden venter fortsatt.
    Her er en ubyggbar bok en FEILET jobb med en setning som sier hva som
    mangler.
    """
    job = books.build_job(ctx.payload)
    ctx.job = job

    slug = job["book_slug"]
    missing = []
    if not (BOOKS / slug / "config.json").is_file():
        missing.append("config.json")
    if not job["config"].get("pages"):
        missing.append("pages[] i config.json")
    wf = job["config"].get("workflowApi") or "workflow_api.json"
    if not (BOOKS / slug / wf).is_file():
        missing.append(wf)
    if not job["config"].get("textScript"):
        missing.append(f"textScript for {job['script_language']}")
    if missing:
        raise JobError(
            f"boka {slug!r} kan ikke bygges - mangler: {', '.join(missing)}. "
            f"Ordren er betalt, saa dette maa haandteres manuelt: enten legges "
            f"boka inn (se dreampage-add-new-book), eller kunden kontaktes.")

    ctx.pages = books.build_pages(job)
    real = [p for p in ctx.pages if not p.get("skipped")]
    ctx.progress(0, len(real))
    if ctx.store:
        ctx.store.set_meta(ctx.job_key, book_slug=slug,
                           child_name=job["child_name"],
                           woo_order_id=job["woo_order_id"])

    skipped = [p["skip_reason"] for p in ctx.pages if p.get("skipped")]
    for reason in skipped:
        ctx.log.warn(reason)

    return {
        "book_slug": slug,
        "child_name": job["child_name"],
        "script_language": job["script_language"],
        "cover_type": job["cover_type"],
        "continue_code": job["continue_code"],
        "next_book_slug": job["next_book_slug"],
        "pages": [p["page_key"] for p in real],
        "skipped": skipped,
        "text_script": job["config"].get("textScript"),
    }


def persist_payload(ctx: Context) -> dict:
    """Skriv state/orders/<job_key>.json.

    Dette er ikke bokfoering - det er det som gjoer at boten, reprint_order.py
    og finish_order.py fortsatt virker naar n8n er borte. De slaar opp en
    ordre via dp_order.resolve(), som leser n8n sin SQLite for aa finne
    payloaden. Cachefila har allerede formatet {order_id, execution_id,
    payload, overrides}, saa her skrives den med execution_id = null.

    Uten dette ville adresse, e-post, cover_type og - viktigst -
    `continue_code` forsvunnet med n8n. Koden lages bare i WordPress, og en
    reprint MAA bruke den samme: trykk er permanent.

    Eksisterende `overrides` bevares. Det er navnerettinger og hår-/hud-/
    kroppsvarianter operatoeren har satt fra Telegram, og de skal overleve alt.
    """
    path = order_state_path(ctx.job_key)
    existing = {}
    if path.is_file():
        try:
            with open(path, encoding="utf-8") as fh:
                existing = json.load(fh)
        except (OSError, json.JSONDecodeError):
            existing = {}

    record = {
        "order_id": ctx.job_key,
        "job_key": ctx.job_key,
        "woo_order_id": ctx.job.get("woo_order_id") or "",
        # Ingen n8n-execution bak denne lenger. Feltet beholdes fordi
        # dp_order.py leser det.
        "execution_id": existing.get("execution_id"),
        "source": "flow",
        "payload": ctx.payload,
        "overrides": existing.get("overrides") or {},
        "book_slug": ctx.job.get("book_slug") or "",
    }
    ORDERS_STATE.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return {"path": str(path), "overrides_bevart": list(record["overrides"])}


def setup_dirs(ctx: Context) -> dict:
    """books/<slug>/orders/<job_key>/{input,pdf} + comfy-mappa."""
    made = []
    for d in (order_input_dir(ctx.job["book_slug"], ctx.job_key),
              order_pdf_dir(ctx.job["book_slug"], ctx.job_key),
              books.comfy_output_dir(ctx.job)):
        d.mkdir(parents=True, exist_ok=True)
        made.append(str(d))
    return {"dirs": made}


# ---------------------------------------------------------------------------
# 2. Barnebildet
# ---------------------------------------------------------------------------
def fetch_child_image(ctx: Context) -> dict:
    """Last ned barnebildet til input/<job_key>.jpg.

    Finnes filen alt, roerer vi den ikke: en redelivery skal ikke laste ned
    bildet paa nytt, og en operatoer kan ha byttet det manuelt fra Telegram.
    """
    target = INPUT / f"{ctx.job_key}.jpg"
    if target.is_file() and target.stat().st_size > 0:
        return {"path": str(target), "source": "fantes-alt",
                "bytes": target.stat().st_size}

    url = str(ctx.job.get("image_url") or "").strip()
    if not url:
        raise JobError(f"input/{ctx.job_key}.jpg finnes ikke, og payloaden har "
                       f"ingen image_url aa laste den fra")

    INPUT.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".jpg.part")
    req = urllib.request.Request(url, headers={
        # Cloudflare svarer 403 "error code: 1010" paa urllib sin standard UA.
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/131.0.0.0 Safari/537.36"),
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as res, open(tmp, "wb") as fh:
            shutil.copyfileobj(res, fh)
    except (urllib.error.URLError, OSError) as exc:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"kunne ikke laste ned barnebildet fra {url}: {exc}") from exc
    if tmp.stat().st_size <= 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"barnebildet fra {url} var tomt")
    os.replace(tmp, target)
    return {"path": str(target), "source": "lastet-ned",
            "bytes": target.stat().st_size, "url": url}


def face_variants(ctx: Context) -> dict:
    """Bygg uttrykksvarianter av barnebildet (<job_key>-<uttrykk>.jpg).

    Rent sidespor. Mangler en variant, faller siden tilbake paa originalen -
    en side skal aldri feile fordi et uttrykk mangler. Derfor svelger dette
    steget sine egne feil i stedet for aa stoppe ordren, akkurat som
    "Build Face Variants" + "Photo Warning" gjorde.
    """
    script = FACE_VARIANTS / "build_trist_variant.py"
    if not script.is_file():
        return {"skipped": f"{script} finnes ikke"}
    cmd = [PYTHON, str(script), ctx.job_key, "--book", ctx.job["book_slug"]]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=900)
    except (OSError, subprocess.TimeoutExpired) as exc:
        ctx.log.warn(f"face_variants feilet, fortsetter: {exc}")
        return {"skipped": str(exc)}

    out = (proc.stdout or "") + (proc.stderr or "")
    # Advarsler om at barnebildet er lite egnet skal videre til operatoeren,
    # men boka lages likevel - det er operatoerens vurdering, ikke maskinens.
    warnings = [line.strip() for line in out.splitlines()
                if "ADVARSEL" in line or "MERK:" in line]
    for line in warnings:
        ctx.log.warn(f"[bilde] {line}")
    made = sorted(p.name for p in INPUT.glob(f"{ctx.job_key}-*.jpg"))
    return {"returncode": proc.returncode, "varianter": made,
            "advarsler": warnings}


# ---------------------------------------------------------------------------
# 3. Side-loekka - det som fjerner laasen
# ---------------------------------------------------------------------------
def render_pages(ctx: Context) -> dict:
    """Render alle sidene, én om gangen, i ordrens EGEN mappe.

    Her fantes det tidligere en laasefil med acquire/release/TTL/stale/token/
    eierskap - ~200 linjer JS over fire noder, og aarsaken til to
    produksjonsinsidenter paa to dager. Den er borte, og ikke erstattet med
    noe: workeren er én prosess med én intern koe, saa det finnes ingen andre
    aa serialisere mot.
    """
    output_dir = books.comfy_output_dir(ctx.job)
    real = [p for p in ctx.pages if not p.get("skipped")]
    done: list[dict] = []
    reused = rendered = 0

    for index, page in enumerate(real, 1):
        if ctx.cancelled():
            raise JobError(f"avbrutt av operatoer etter {index - 1} av {len(real)} sider")

        key = page["page_key"]
        ctx.log.bind("render_pages")

        try:
            prompt, patch_nodes = books.build_prompt(ctx.job, page)
        except JobError:
            # En valgfri side (page99_next) skal aldri stoppe en betalt ordre.
            if page.get("optional"):
                ctx.log.warn(f"{key}: kunne ikke bygge prompt, hopper over")
                continue
            raise

        for note in patch_nodes.get("_corrections") or []:
            ctx.log.info(f"{key}: patch-node korrigert automatisk ({note})")

        try:
            result = ctx.comfy.render_page(prompt, output_dir, key)
        except comfy_mod.PageFailed as exc:
            if page.get("optional"):
                ctx.log.warn(f"{key}: ComfyUI feilet, hopper over ({exc})")
                continue
            raise

        if result.source == "already-on-disk":
            reused += 1
        else:
            rendered += 1
        done.append({
            "page_key": key,
            "file": result.path.name if result.path else None,
            "source": result.source,
            "seconds": round(result.seconds, 1),
            "prompt_id": result.prompt_id,
            "template": page.get("template_image"),
            "face": page.get("face_image"),
        })
        ctx.progress(len(done), len(real))
        ctx.log.info(f"{key} ferdig ({result.source})",
                     seconds=round(result.seconds, 1),
                     nr=f"{index}/{len(real)}")

    return {
        "output_dir": str(output_dir),
        "sider": len(done),
        "forventet": len(real),
        "gjenbrukt": reused,
        "rendret": rendered,
        "detaljer": done,
    }


def verify_pages(ctx: Context) -> dict:
    """Alle ikke-valgfrie sider maa ligge paa disk, i ordrens egen mappe.

    Sjekken gjentas etter loekka fordi det er den som beskytter PDF-en: uten
    den kom feilen foerst i "Run Text Script" som
    `ValueError: Inner PDF page count must be one of [30, 31]; got 14`, og da
    var det ingen som visste HVILKEN side som manglet.
    """
    output_dir = books.comfy_output_dir(ctx.job)
    missing, found = [], []
    for page in ctx.pages:
        if page.get("skipped"):
            continue
        key = page["page_key"]
        path = comfy_mod.Comfy.existing_page(output_dir, key)
        if path:
            found.append(key)
        elif not page.get("optional"):
            missing.append(key)
    if missing:
        raise RuntimeError(f"{len(missing)} sider mangler i {output_dir}: "
                           + ", ".join(missing))
    return {"sider": len(found), "output_dir": str(output_dir)}

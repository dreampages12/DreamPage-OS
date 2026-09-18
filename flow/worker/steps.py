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
import net  # noqa: E402
from books import JobError  # noqa: E402

PYTHON = sys.executable

# <rot>/tools, der check_assets.py bor. paths.TOOLS peker paa flow/tools,
# som er noe annet - derfor utledes denne fra ROOT.
TOOLS_DIR = Path(__file__).resolve().parent.parent.parent / "tools"


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
# 0. Er kunsten paa plass?
# ---------------------------------------------------------------------------
def check_assets(ctx: Context) -> dict:
    """Alle delte kunst- og fontstier finnes FOER vi bygger noe.

    Dette er tredje forsoek paa aa lukke samme feilklasse, og de to foerste
    mislyktes paa samme maate: de fantes, men ingen kjoerte dem.

      ordre 1510  line2-logoen hadde flyttet seg. Rendereren skrev "ADVARSEL:
                  Fant ikke line2_image" og avsluttet med 0. Forsiden sa
                  "Henry og det" og gikk til trykkeklart utkast.
      ordre 1506  tekstscriptene pekte paa <rot>/flow/books/... etter
                  flyttingen. Alle boeker i alle fem spraak falt stille
                  tilbake paa den DELTE gamle aapningssida.

    Begge var fail-soft med vilje: et oppsalg skal aldri stoppe en betalt
    ordre. Da maa mangelen oppdages FOER rendringen, ikke under. Derfor staar
    sjekken her, som steg nummer én, og ikke i et verktoey noen maa huske.

    JobError, ikke en vanlig feil: en manglende fil blir ikke bedre av tre
    forsoek. Noen maa rette stien.
    """
    sys.path.insert(0, str(TOOLS_DIR))
    import check_assets as checker
    found, missing = checker.audit()
    if missing:
        lines = "\n".join(f"  {where}: {p}" for where, p in missing)
        raise JobError(
            f"{len(missing)} kunst-/fontsti(er) mangler - bygger ikke:\n{lines}\n"
            "Hele kunstkjeden er fail-soft og ville gaatt videre med feil "
            "bilde. Rett stien og kjoer ordren om igjen.")
    return {"paths": len(found), "missing": 0}


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

    # Nattbruddet 04:30-05:05 - se net.wait_for_internet. Uten denne bruker
    # steget opp forsoekene sine paa fem minutter og ordren er tapt.
    net.wait_for_internet(url, ctx.log, ctx.cancelled)

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
    except urllib.error.HTTPError as exc:
        tmp.unlink(missing_ok=True)
        # Serveren svarte, og svaret var nei. Ordre 1546 (18.09.2026): WP
        # svarte 404 paa bildet, og svarte fortsatt 404 sju timer senere.
        # Et nytt forsoek hjelper ikke, og med ventingen over ville det
        # holdt hele koeen i 45 minutter. Stopp med en gang, og si hva
        # operatoeren maa gjoere.
        if 400 <= exc.code < 500 and exc.code not in (408, 425, 429):
            raise JobError(
                f"serveren sier at barnebildet ikke kan hentes (HTTP "
                f"{exc.code}) fra {url}. Skaff bildet, legg det som "
                f"input/{ctx.job_key}.jpg og be om retry.") from exc
        raise RuntimeError(f"kunne ikke laste ned barnebildet fra {url}: {exc}") from exc
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
    script = FACE_VARIANTS / "build_variants.py"
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

def notify_pages_ready(ctx: Context) -> dict:
    """Si til operatoeren at sidene er klare til gjennomgang.

    HVORFOR DETTE STEGET FINNES:

    Den aktive pipelinen ("pages") stopper med vilje etter sidene - et
    menneske skal se paa dem foer PDF-en bygges og et Gelato-utkast lages.
    Men fram til 16.09.2026 var det INGEN som fikk beskjed naar de var
    klare. Jobben ble staaende "done" i DB-en, ordren var halvferdig, og
    kunden ventet.

    Ordre 1522 (Lilly) og 1524 (Ida) laa slik samtidig. Det er noeyaktig
    samme feilform som ordre 1517, der n8n skrev "success" etter 1,3
    sekunder og ingen merket at boka aldri ble laget: arbeidet stopper et
    sted der ingen ser det.

    Steget er OPTIONAL og svelger sine egne feil. En ordre der sidene er
    bygget, men varselet ikke kom fram, er ikke en feilet ordre - men den
    skal synes i loggen.
    """
    import urllib.error
    import urllib.request

    import dp_secrets
    import pipeline as pipeline_mod

    # Steget staar i PAGES_PIPELINE, og FULL_PIPELINE er PAGES + resten - saa i
    # full modus ville dette fyrt MIDT i kjoeringen og bedt operatoeren bygge
    # noe pipelinen bygger selv fire steg senere. Da er varselet feil, ikke
    # bare overfloedig.
    if getattr(pipeline_mod, "ACTIVE", "pages") != "pages":
        return {"sent": False, "reason": "ikke siste steg i aktiv pipeline"}

    token = dp_secrets.get("worker_bot_token")
    chat = dp_secrets.get("worker_chat_id")
    if not token or chat in (None, ""):
        ctx.log.warn("worker_bot_token/worker_chat_id mangler - ingen varsling")
        return {"sent": False, "reason": "mangler token eller chat_id"}

    job = ctx.job
    pages = len(ctx.pages or [])
    text = (
        "Sidene er klare til gjennomgang.\n\n"
        f"Ordre:   {ctx.job_key}\n"
        f"Barn:    {job.get('child_name')}\n"
        f"Bok:     {job.get('book_title') or job.get('book_slug')}\n"
        f"Sider:   {pages}\n"
        f"Omslag:  {job.get('cover_type')}\n\n"
        "PDF og Gelato-utkast er IKKE laget enda - det er med vilje.\n"
        f"Se sidene:      /vis {ctx.job_key}\n"
        f"Bytt en side:   /fix {ctx.job_key} <sidenr>\n"
        f"Bygg boka:      /bygg {ctx.job_key}"
    )
    body = json.dumps({"chat_id": chat, "text": text,
                       "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return {"sent": True, "http": res.status, "pages": pages}
    except (urllib.error.URLError, OSError) as exc:
        ctx.log.error(f"Telegram-varsel feilet: {exc}")
        return {"sent": False, "error": str(exc)}

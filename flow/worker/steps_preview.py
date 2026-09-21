# -*- coding: utf-8 -*-
"""Stegene i PREVIEW-modus. Samme form som steps.py: `def step(ctx) -> dict`.

Rekkefoelgen staar i pipeline.py under "preview", ikke her - pipelinen er
data i begge moduser.

Hva som er DELT med bokpipelinen, og hvorfor:

    comfy.render_page        side-loekka, disk-slaar-history, polling
    books.build_prompt       patch-node-deteksjonen i bokas workflow_api.json
    steps.download_child_image   Cloudflare-headeren, nattbruddet, 404-regelen
    runner / jobs / log      koe, status, per-jobb-logg, avbrudd

Det er den infrastrukturen som har kostet noe aa faa riktig, og den skal
ikke finnes i to utgaver. Det som er NYTT her er bare arbeidsflyten: én side
i stedet for 33, tittel i stedet for PDF, opplasting i stedet for Gelato.

Hva en preview-jobb ALDRI gjoer: bygger PDF, laster opp til Drive, snakker
med Gelato eller WooCommerce. Ingenting her koster penger, og ingenting her
kan trykkes.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from paths import FLOW, INPUT  # noqa: E402
import books  # noqa: E402
import comfy as comfy_mod  # noqa: E402
import config as flow_config  # noqa: E402
import preview as preview_mod  # noqa: E402
import preview_sink  # noqa: E402
import steps as steps_mod  # noqa: E402
from books import JobError  # noqa: E402
from steps import Context  # noqa: E402

PYTHON = sys.executable
PRE_DIR = FLOW / "pre"


# ---------------------------------------------------------------------------
# 0. Kan vi i det hele tatt levere?
# ---------------------------------------------------------------------------
def check_delivery(ctx: Context) -> dict:
    """Sinken er satt opp FOER GPU-en bruker tjue sekunder paa et bilde.

    Samme resonnement som `check_assets` staar foerst i bokpipelinen:
    mangelen skal oppdages foer rendringen, ikke under. En preview-jobb som
    rendrer helt ferdig og saa ikke kan levere, er en jobb som brukte GPU-tid
    paa ingenting - og verre: uten denne sjekken ville det sett ut som om
    bildet ble laget, for det ble det.
    """
    return preview_sink.check_ready()


# ---------------------------------------------------------------------------
# 1. Forstaa jobben
# ---------------------------------------------------------------------------
def validate_preview_job(ctx: Context) -> dict:
    """Payload -> bok, marked, side, mal og tittel. Avviser alt som mangler.

    ALLE filene sjekkes her, mens det fortsatt er gratis aa stoppe:

      malen og masken   ligger de ikke i input/, ville ComfyUI laget et bilde
                        av noe annet - eller feilet midt i.
      line2-logoen      for de fleste boeker ER logoen hele andre tittellinje
                        ("line2" er tom). Mangler fila, skriver
                        render-title-line2logo.py "ADVARSEL" og avslutter med
                        0, og forsiden blir staaende som en halv setning. Det
                        er ordre 1510, og det skal ikke kunne skje i en
                        forhaandsvisning heller: der ser KUNDEN den.
    """
    job = preview_mod.build_job(ctx.payload)
    page = preview_mod.build_page(job)
    ctx.job = job
    ctx.pages = [page]

    missing: list[str] = []
    for label, name in (("template_image", page.get("template_image")),
                        ("mask_image", page.get("mask_image"))):
        if not name:
            continue
        path = Path(name)
        if not path.is_absolute():
            path = INPUT / name
        if not path.is_file():
            missing.append(f"{label}: {path}")

    wf = Path(page["workflow_api_file"])
    if not wf.is_absolute():
        wf = books.BOOKS / job["book_slug"] / page["workflow_api_file"]
    if not wf.is_file():
        missing.append(f"workflow: {wf}")

    inner = None
    if job["asset_kind"] == "innerpage":
        # Kaster selv hvis bokas tekstscript mangler. Teksten SELV hentes av
        # rendreren, fra bokas egen build_pages() - side 7 i forhaands-
        # visningen er side 7 i boka.
        inner = preview_mod.innerpage_source(job, page)
    else:
        logo = job["title"].get("line2_image") or ""
        if logo and not Path(logo).is_file():
            missing.append(f"line2_image (tittellogo): {logo}")
        elif not logo and not str(job["title"].get("line2") or "").strip():
            missing.append(
                "tittelens andre linje: verken \"line2\" (tekst) eller "
                "\"line2_image\" (logo) er satt - forsiden ville blitt en "
                "halv setning, som i ordre 1510")

    if missing:
        raise JobError(
            f"forhaandsvisning av {job['book_slug']!r} ({job['market']}, "
            f"{job['asset_kind']}) kan ikke bygges - mangler:\n  "
            + "\n  ".join(missing))

    if ctx.store:
        ctx.store.set_meta(ctx.job_key, book_slug=job["book_slug"],
                           child_name=job["child_name"])
    ctx.progress(0, 1)

    return {
        "book_slug": job["book_slug"],
        "market": job["market"],
        "title_lang": job["title_lang"],
        "asset_kind": job["asset_kind"],
        "page_key": page["page_key"],
        "template_image": page["template_image"],
        "child_name": job["child_name"],
        "line1": job["title"].get("line1"),
        "text_script": (inner or {}).get("script"),
    }


def status_processing(ctx: Context) -> dict:
    """Si fra at jobben er i gang, saa frontenden kan vise fremdrift.

    Sidespor: en forhaandsvisning som ble laget, men der `processing` ikke
    kom fram, er ikke en feilet jobb. `completed` er den som betyr noe.
    """
    return preview_sink.processing(ctx.job, ctx.log)


def fetch_child_image(ctx: Context) -> dict:
    """Last ned barnets bilde til input/preview-<job_id>.jpg.

    Finnes filen alt, roeres den ikke - en redelivery skal ikke laste ned
    bildet paa nytt. Selve nedlastingen er den SAMME koden boekene bruker
    (steps.download_child_image), med Cloudflare-headeren, ventingen paa
    nattbruddet og 404-regelen fra ordre 1546.
    """
    target = INPUT / ctx.job["face_filename"]
    if target.is_file() and target.stat().st_size > 0:
        return {"path": str(target), "source": "fantes-alt",
                "bytes": target.stat().st_size}
    url = ctx.job["image_url"]
    steps_mod.download_child_image(url, target, ctx)
    return {"path": str(target), "source": "lastet-ned",
            "bytes": target.stat().st_size, "url": url}


# ---------------------------------------------------------------------------
# 2. Selve bildet
# ---------------------------------------------------------------------------
def render_preview_page(ctx: Context) -> dict:
    """Én side gjennom ComfyUI, i jobbens EGEN mappe.

    Samme klient, samme polling og samme regel som boeker: finnes filen paa
    disk, er siden ferdig, og vi ser BARE i denne jobbens mappe. Sidenoekkelen
    er "page00" i hver eneste omslagsjobb, saa to samtidige jobber som fikk
    se i samme mappe ville plukket opp hverandres bilder - noeyaktig det som
    skjedde med to bokordre 14.09.2026, bare med et barneansikt som innsats.
    """
    job, page = ctx.job, ctx.pages[0]
    output_dir = preview_mod.comfy_output_dir(job)
    prompt, patch_nodes = books.build_prompt(job, page)
    for note in patch_nodes.get("_corrections") or []:
        ctx.log.info(f"{page['page_key']}: patch-node korrigert ({note})")

    result = ctx.comfy.render_page(prompt, output_dir, page["page_key"])
    if result.path is None:
        raise RuntimeError(f"ComfyUI ga ingen fil for {page['page_key']} i "
                           f"{output_dir}")
    ctx.progress(1, 1)
    # `render_seconds`, ikke `seconds`: runneren logger sin egen `seconds` for
    # steget og slaar sammen detaljene i det samme kallet, saa noekkelen
    # `seconds` her ville kollidert med den. Bokens render_pages har samme
    # grunn til aa legge tiden per side inne i `detaljer`.
    return {"file": str(result.path), "source": result.source,
            "render_seconds": round(result.seconds, 1),
            "prompt_id": result.prompt_id, "output_dir": str(output_dir)}


def _raw_page(ctx: Context) -> Path:
    """Den raa sida ComfyUI laget. Disken er fasiten, ogsaa her."""
    output_dir = preview_mod.comfy_output_dir(ctx.job)
    path = comfy_mod.Comfy.existing_page(output_dir, ctx.pages[0]["page_key"])
    if path is None:
        raise RuntimeError(f"fant ingen rendret {ctx.pages[0]['page_key']} i "
                           f"{output_dir}")
    return path


def _font_scale(raw: Path, template_name: str, log) -> float:
    """Hvor mye fontstoerrelsene maa ganges med for DETTE bildet.

    render-title bruker absolutte pikselstoerrelser for fonten, mens
    logo_scale, top_margin og line_spacing er andeler av bredden.
    Tittelparametrene er tunet mot forside-malen; et ComfyUI-bilde i en annen
    opploesning trenger tilsvarende stoerre font for aa se likt ut. Samme
    regnestykke som build_last_page.font_scale, av samme grunn.
    """
    try:
        from PIL import Image
        template = Path(template_name)
        if not template.is_absolute():
            template = INPUT / template_name
        with Image.open(template) as im:
            baseline = im.width
        with Image.open(raw) as im:
            actual = im.width
    except Exception as exc:                          # noqa: BLE001
        # En skala vi ikke fikk maalt er ikke en manglende fil - bildet
        # finnes, teksten blir tegnet. Men det skal staa i loggen hvorfor
        # den ble 1.0.
        log.warn(f"kunne ikke maale bildestoerrelsen ({exc}) - fontskala 1.0")
        return 1.0
    if not baseline or actual == baseline:
        return 1.0
    return actual / baseline


def _run(cmd: list[str], ctx: Context, what: str) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600)
    out = (proc.stdout or "") + (proc.stderr or "")
    for line in out.splitlines():
        if "ADVARSEL" in line or "FEIL" in line:
            # Renderne er fail-soft og avslutter med 0 ogsaa naar de har
            # hoppet over noe. Da er loggen det eneste stedet det staar.
            ctx.log.warn(f"[{what}] {line.strip()}")
    if proc.returncode != 0:
        raise RuntimeError(f"{what} feilet (exit {proc.returncode}):\n"
                           + out[-2000:])
    return out


def render_preview_text(ctx: Context) -> dict:
    """Legg tittel/logo (omslag) eller historietekst (innerside) paa bildet.

    Omslag bruker de SAMME to rendrerne som boka sin egen forside
    (render-title-line2logo.py naar boka har logo, render-title.py naar den
    har tekst), med de samme parametrene fra config/next_book_titles.json.
    Det er hele poenget: det kunden ser i forhaandsvisningen skal vaere det
    kunden faar i posten.
    """
    job = ctx.job
    raw = _raw_page(ctx)
    out_dir = preview_sink.local_output_dir(job["job_id"])
    out_dir.mkdir(parents=True, exist_ok=True)
    titled = out_dir / f"{job['job_id']}_titled.png"

    if job["asset_kind"] == "innerpage":
        # Ingen tekst paa kommandolinja: rendreren kaller bokas eget
        # tekstscript og tegner sida med bokas egen render_page. Da er
        # navnebytte, uthevede ord, blokkdeling og kolonne noeyaktig som i
        # boka - og de kan ikke gli fra hverandre, for det er samme kode.
        inner = preview_mod.innerpage_source(job, ctx.pages[0])
        cmd = [PYTHON, str(PRE_DIR / "render-innerpage.py"),
               "--script", inner["script"],
               "--image", str(raw), "--out", str(titled),
               "--child-name", job["child_name"],
               "--filename", inner["filename"]]
        _run(cmd, ctx, "render-innerpage")
        renderer = "render-innerpage.py"
    else:
        renderer = _cover_command(ctx, raw, titled)

    if not titled.is_file() or titled.stat().st_size <= 0:
        raise RuntimeError(f"{renderer} skrev ingen fil til {titled}")

    final = _to_jpeg(titled, out_dir / f"{job['job_id']}_preview.jpg")
    return {"renderer": renderer, "titled": str(titled), "path": str(final),
            "bytes": final.stat().st_size}


def _cover_command(ctx: Context, raw: Path, out: Path) -> str:
    """Bygg og kjoer kommandoen for et omslag. Returnerer rendrerens navn."""
    job = ctx.job
    params = job["title"]
    logo = str(params.get("line2_image") or "").strip()
    renderer = "render-title-line2logo.py" if logo else "render-title.py"
    scale = _font_scale(raw, ctx.pages[0]["template_image"], ctx.log)

    cmd = [
        PYTHON, str(PRE_DIR / renderer),
        "--image", str(raw),
        "--out", str(out),
        "--line1", params["line1"],
        "--line2", params.get("line2") or "",
        "--font_small", str(round(float(params.get("font_small", 80)) * scale)),
        "--font_large", str(round(float(params.get("font_large", 90)) * scale)),
        "--gold", str(params.get("gold", "255, 255, 255")),
        "--shadow", str(params.get("shadow", "0, 0, 0")),
        "--top_margin", str(params.get("top_margin", 0.04)),
        "--line_spacing", str(params.get("line_spacing", 0.01)),
        "--font_small_path", str(params.get("font_small_path") or ""),
        "--font_large_path", str(params.get("font_large_path") or ""),
    ]
    if logo:
        cmd += ["--line2_image", logo,
                "--logo_scale", str(params.get("logo_scale", 0.38)),
                "--logo_x_offset", str(params.get("logo_x_offset", 0))]
    # Bare det boka faktisk har bedt om sendes videre; alt annet beholder
    # rendrerens standard, slik at en bok uten glod ser ut som den gjoer i dag.
    for key, flag in (("glow_color", "--glow_color"),
                      ("glow_opacity", "--glow_opacity"),
                      ("glow_radius_scale", "--glow_radius_scale"),
                      ("logo_shadow_opacity", "--logo_shadow_opacity"),
                      ("bottom_logo", "--bottom_logo"),
                      ("bottom_logo_scale", "--bottom_logo_scale"),
                      ("bottom_logo_margin", "--bottom_logo_margin"),
                      ("bottom_logo_x_offset", "--bottom_logo_x_offset")):
        value = params.get(key)
        if value not in (None, ""):
            cmd += [flag, str(value)]

    _run(cmd, ctx, renderer)
    return renderer


def _to_jpeg(src: Path, dst: Path) -> Path:
    """PNG fra rendreren -> JPEG for nettbutikken.

    Rendrerne skriver RGBA-PNG (de komponerer med alfa). Nettsiden viser
    bildet i en produktkarusell, og en 3 MB PNG per forhaandsvisning er
    forskjellen paa "dukket opp" og "lastet ferdig" paa mobil.
    """
    quality = int(flow_config.preview().get("jpeg_quality") or 90)
    from PIL import Image
    with Image.open(src) as im:
        im.convert("RGB").save(dst, "JPEG", quality=quality, optimize=True)
    return dst


# ---------------------------------------------------------------------------
# 3. Levering
# ---------------------------------------------------------------------------
def deliver_preview(ctx: Context) -> dict:
    """Last opp bildet, skriv `completed`, og si fra til nettbutikken.

    Rekkefoelgen er ikke tilfeldig: bildet foerst, saa statusfila, saa
    callbacken. Skrev vi `completed` foerst og opplastingen feilet, ville
    frontenden hentet en URL som ikke finnes - og en oedelagt bilderute er
    verre enn en spinner.
    """
    job = ctx.job
    path = Path(_last_detail(ctx, "render_preview_text", "path")
                or preview_sink.local_output_dir(job["job_id"])
                / f"{job['job_id']}_preview.jpg")
    url = preview_sink.upload_result(job, path, ctx.log)
    status = preview_sink.completed(job, url, ctx.log)
    callback = preview_sink.callback(job, url, ctx.log)
    return {"preview_url": url, "status_file": status.get("local"),
            "status_remote": bool(status.get("remote")),
            "callback": callback}


def _last_detail(ctx: Context, step_name: str, key: str):
    """Hent en verdi et tidligere steg la i jobb-DB-en.

    Stegene deler ikke variabler - de deler ctx og databasen. Her henter vi
    stien det forrige steget faktisk skrev, i stedet for aa gjette den paa
    nytt og risikere at de to gjetningene gaar fra hverandre.
    """
    store = ctx.store
    if store is None:
        return None
    row = store.job(ctx.job_key) or {}
    for step in reversed(row.get("steps") or []):
        if step.get("name") == step_name and isinstance(step.get("detail"), dict):
            value = step["detail"].get(key)
            if value:
                return value
    return None


def notify_preview(ctx: Context) -> dict:
    """Telegram-varsel per ferdig forhaandsvisning.

    Av som standard (`preview.notify_each`). En preview-PC kan gjoere
    hundrevis om dagen, og et varsel per stykk er stoey - og stoey er
    grunnen til at tolv ekte advarsler i ordre 1528 saa ut som mer av det
    samme. Feilede jobber varsles uansett, via notify.job_failed.
    """
    if not flow_config.preview().get("notify_each"):
        return {"sent": False, "reason": "preview.notify_each er av"}
    import notify
    job = ctx.job
    url = _last_detail(ctx, "deliver_preview", "preview_url") or "?"
    return notify.send(
        "Forhaandsvisning klar.\n\n"
        f"Jobb:   {job['job_id']}\n"
        f"Bok:    {job.get('book_title') or job['book_slug']}\n"
        f"Barn:   {job['child_name']}\n"
        f"Marked: {job['market']}  ({job['asset_kind']})\n"
        f"{url}", log=ctx.log)


def cleanup_preview(ctx: Context) -> dict:
    """Slett den raa ComfyUI-sida naar bildet er levert.

    En preview-PC lager tusenvis av disse, og de er verdiloese i det
    oeyeblikket det ferdige bildet ligger hos kunden - i motsetning til
    bokordre, der de rendrede sidene er det eneste som ikke kan lages om
    igjen uten GPU-tid (ordre 1528).

    Kjoeres bare naar leveringen faktisk gikk. Det ferdige bildet
    (<job_id>_preview.jpg) blir liggende.
    """
    if not _last_detail(ctx, "deliver_preview", "preview_url"):
        return {"removed": 0, "reason": "ingen levering - beholder sida"}
    output_dir = preview_mod.comfy_output_dir(ctx.job)
    removed = 0
    if output_dir.is_dir():
        for entry in output_dir.iterdir():
            try:
                if entry.is_file():
                    entry.unlink()
                    removed += 1
            except OSError:
                pass
        try:
            os.rmdir(output_dir)
        except OSError:
            pass
    return {"removed": removed, "dir": str(output_dir)}

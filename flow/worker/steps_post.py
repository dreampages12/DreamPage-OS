# -*- coding: utf-8 -*-
"""Fase 5: alt etter at sidene er rendret.

Rekkefoelgen er hentet fra de faktiske koblingene i n8n-workflowen, ikke
gjettet:

    All Pages Done -> Release RabbitMQ Job -> Claim Post-Comfy Order
      -> WP Progress: Book Creating
      -> Prepare Pages -> Build Next Cover Title -> Upload Continue Cover
      -> Build Last Page -> Run Text Script -> Stamp QR On Innersider
      -> Count Innersider Pages -> Build Gelato PDF -> Validate Gelato Files
      -> Create Drive Folder -> Upload x3 -> Make Public x3
      -> Create Gelato Draft -> Record Gelato Draft -> Auto Merge Multibook
      -> Suppress Telegram? -> Send Telegram Approval
      -> WP Progress: Quality Check

Merk at `Build Last Page` kommer FOER `Run Text Script`: den skriver
`orders/<job_key>/input/blank-back.png`, som tekstscriptet leser som siste
innerside. `Stamp QR On Innersider` kommer ETTER, fordi den stempler den
ferdige innersider.pdf.

### Det disse stegene IKKE gjoer: de trykker ingenting

Godkjenningsloekka i n8n er DOED KODE. `Confirm Gelato Order`,
`Send Telegram Confirmation` og `Init Approval Poll` (og dermed hele
Get Telegram Updates / Parse Approval Reply / Approval Done?-kjeden) har ingen
inngaaende kobling i den kjoerende workflowen. Telegram-meldingen sier det
selv: "Review/order manually in Gelato. n8n will now close this execution
after sending this notification."

Dagens oppfoersel er altsaa: workeren lager et UTKAST hos Gelato og varsler
operatoeren. Mennesket bekrefter. Derfor stopper denne pipelinen ved utkastet,
og `Confirm Gelato Order` er ikke portert. Aa legge inn automatisk bekreftelse
her ville sendt boeker til trykk uten at noen hadde sett dem - en irreversibel
handling paa en ekte kundeordre.

### Gjenbruk, ikke gjenskriving

`reprint_order.rebuild_pdfs()` og `.upload_and_draft()` ER denne kjeden, i
riktig rekkefoelge, med guardene. De har produsert ekte boeker i maaneder.
Stegene her kaller dem i stedet for aa skrive Drive-OAuth og
Gelato-bestillingsformatet paa nytt - der en feil koster en trykt bok.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from paths import FLOW, GELATO_DRAFTS, OUTPUT, order_dir  # noqa: E402
import books  # noqa: E402
import dp_secrets  # noqa: E402
import net  # noqa: E402
import notify  # noqa: E402
from books import JobError  # noqa: E402
from steps import Context  # noqa: E402

PYTHON = sys.executable
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
WP_PROGRESS_URL = "https://dreampage.store/wp-json/dreampage/v1/order-progress"


def _order_info(ctx: Context) -> dict:
    """dp_order.resolve() for denne jobben.

    Fungerer uten n8n fordi `persist_payload` skrev
    state/orders/<job_key>.json med payloaden. Det er hele grunnen til at det
    steget er et sjekkpunkt.
    """
    if ctx.job.get("_order_info"):
        return ctx.job["_order_info"]
    sys.path.insert(0, str(FLOW))
    import dp_order
    info = dp_order.resolve(ctx.job_key)
    ctx.job["_order_info"] = info
    return info


# ---------------------------------------------------------------------------
# Dedupe
# ---------------------------------------------------------------------------
def claim_post_comfy(ctx: Context) -> dict:
    """Skriv .post_comfy_claim.json - bare én kjoering faar gaa videre.

    Portert fra "Claim Post-Comfy Order". Den bruker `open(..., 'wx')`, altsaa
    en atomisk opprettelse: taper man kapploepet, finnes filen alt.

    I flow er dette teoretisk overfloedig - den interne koeen kjoerer én jobb
    om gangen, og jobb-DB-en avviser en duplikat. Filen beholdes likevel, av
    to grunner: dp_order.claimed_execution() leser den naar boten skal finne
    en ordre, og den er beviset paa hvem som eide ordren hvis noe skal
    ettergaas manuelt.
    """
    directory = order_dir(ctx.job["book_slug"], ctx.job_key)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".post_comfy_claim.json"
    claim = {"order_id": ctx.job_key, "job_key": ctx.job_key,
             "book_slug": ctx.job["book_slug"],
             "executionId": None, "source": "flow",
             "createdAt": __import__("datetime").datetime.now()
                          .astimezone().isoformat(timespec="seconds")}
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(claim, fh, ensure_ascii=False, indent=2)
        return {"claimed": True, "path": str(path)}
    except FileExistsError:
        existing = {}
        try:
            with open(path, encoding="utf-8") as fh:
                existing = json.load(fh)
        except (OSError, json.JSONDecodeError):
            pass
        # Ikke en feil: vi eier jobben (koeen slapp bare én inn), saa en
        # gammel claim-fil fra n8n eller fra et tidligere forsoek er bare
        # historie.
        ctx.log.info("post-comfy-claim fantes fra foer", eier=existing)
        return {"claimed": False, "existing": existing, "path": str(path)}


# ---------------------------------------------------------------------------
# WooCommerce-fremdrift
# ---------------------------------------------------------------------------
def _wp_progress(ctx: Context, status_value: str) -> dict:
    """POST til dreampage.store. Rent sidespor: kundens fremdriftsvisning skal
    aldri kunne stoppe boka.

    Endepunktet krever `X-DreamPage-Secret`. Porteringen fra n8n hadde
    droppet headeren, og siden steget svelger alle feil ble det bare en WARN
    i loggen mens kunden satt og saa en fremdrift som aldri flyttet seg -
    oppdaget da ordre 1517 kjoerte 16.09.2026 ("Invalid credentials", 403).
    Hemmeligheten ligger i config/secrets.json, ikke her: repoet er i git.

    Mangler hemmeligheten helt, sier vi det i loggen i stedet for aa sende en
    forespoersel vi vet blir avvist.
    """
    woo = ctx.job.get("woo_order_id") or ctx.job_key
    try:
        order_id = int(str(woo).split("-")[0])
    except ValueError:
        order_id = 0

    sys.path.insert(0, str(FLOW))
    import dp_secrets
    secret = dp_secrets.wp_progress_secret()
    if not secret:
        ctx.log.warn("WP-fremdrift hoppet over: hemmeligheten "
                     "'wp_progress_secret' mangler i config/secrets.json")
        return {"status": status_value, "skipped": "mangler hemmelighet",
                "order_id": order_id}

    body = json.dumps({"order_id": order_id, "status": status_value}).encode()
    req = urllib.request.Request(WP_PROGRESS_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": UA,
                                          "X-DreamPage-Secret": secret})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return {"status": status_value, "http": res.status, "order_id": order_id}
    except urllib.error.HTTPError as exc:
        # 400 dreampage_progress_regression er endepunktet som gjoer jobben
        # sin: kunden skal ikke se "boken settes sammen" etter at hun har
        # faatt "kvalitetskontroll". Den kommer hver gang en ferdig ordre
        # kjoeres om, og er IKKE en feil. Den skilles ut fordi det var en
        # WARN ingen leste som skjulte at headeren manglet i det hele tatt.
        body = ""
        try:
            body = exc.read()[:400].decode("utf-8", "replace")
        except OSError:
            pass
        if exc.code == 400 and "progress_regression" in body:
            ctx.log.info(f"WP-fremdrift '{status_value}' hoppet over: ordren "
                         f"har alt kommet lenger (omkjoering)")
            return {"status": status_value, "skipped": "alt lenger fremme",
                    "order_id": order_id}
        ctx.log.warn(f"WP-fremdrift '{status_value}' feilet: {exc}"
                     + (f" - {body}" if body else ""))
        return {"status": status_value, "error": str(exc), "order_id": order_id}
    except (urllib.error.URLError, OSError) as exc:
        ctx.log.warn(f"WP-fremdrift '{status_value}' feilet: {exc}")
        return {"status": status_value, "error": str(exc), "order_id": order_id}


def wp_book_creating(ctx: Context) -> dict:
    return _wp_progress(ctx, "book_creating")


def wp_quality_check(ctx: Context) -> dict:
    return _wp_progress(ctx, "quality_check")


# ---------------------------------------------------------------------------
# Tekst, PDF og QR-siste-side
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Grensen mot reprint_order
# ---------------------------------------------------------------------------
def _as_runtime_error(fn, *args, **kwargs):
    """Kall reprint_order og gjoer SystemExit til en vanlig feil.

    reprint_order er foerst og fremst et kommandolinjeskript, og der er
    `raise SystemExit("forklaring")` helt riktig - den skriver meldingen og
    setter exit-koden. Men den brukes ogsaa som BIBLIOTEK herfra, og da er
    SystemExit en BaseException som gaar rett gjennom `except Exception` i
    alle tre lagene i runneren.

    17.09.2026 drepte noeyaktig det arbeidstraaden: gelato_api kastet
    SystemExit for ordre 1532-b1, jobben stod som "running" for alltid og to
    andre ordre laa fast i koeen i 47 minutter. gelato_api er rettet, men
    reprint_order har ti slike raise-setninger, og de er riktige DER. Derfor
    konverteres de her, ved grensen, i stedet for aa endre ti kallsteder i et
    skript som ogsaa brukes manuelt.
    """
    try:
        return fn(*args, **kwargs)
    except SystemExit as exc:
        raise RuntimeError(str(exc) or "reprint_order avsluttet uten melding") from exc


def build_pdfs(ctx: Context) -> dict:
    """Prepare -> fortsett-side -> tekstscript -> QR-stempel -> Gelato-PDF.

    Hele kjeden ligger i reprint_order.rebuild_pdfs(), i noeyaktig den
    rekkefoelgen n8n har den, med de to guardene som skal vaere strenge:

        samlet PDF   maa vaere 33 sider (Gelato-produktet)
        innersider   maa vaere 30 eller 31 (config.expectedInnerPages)

    Feil antall stopper ordren. Det er en funksjon, ikke en bug: en PDF med
    14 innersider blir en trykt bok med 14 innersider.
    """
    info = _order_info(ctx)
    sys.path.insert(0, str(FLOW))
    import reprint_order

    # callback=True laster fortsett-forsiden opp til landingssiden, som i n8n
    # ("Upload Continue Cover"). Uten continue_code hopper rebuild_pdfs over
    # hele QR-siden selv.
    files = _as_runtime_error(reprint_order.rebuild_pdfs, info,
                              skip_prepare=False, callback=True)
    out = {k: str(v) for k, v in files.items()}
    for key in ("cover", "inner", "gelato"):
        path = Path(files[key])
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError(f"{key}-PDF-en ble ikke skrevet: {path}")
        out[f"{key}_bytes"] = path.stat().st_size
    ctx.job["_pdf_files"] = files
    return out


def validate_gelato_files(ctx: Context) -> dict:
    """Siste sjekk foer noe forlater maskinen.

    reprint_order sjekker sidetallene. Her sjekkes at filene faktisk ER der,
    har stoerrelse, og at den samlede PDF-en ikke er saa stor at Drive-lenka
    blir et problem: over 100 MB svarer /uc med en HTML-advarselside i stedet
    for filen, Gelato laster ned 2 kB HTML, og item-et staar igjen med
    files[0].id = null - uten at noe varsler. Det traff ordre 1300
    (105,7 MB) 22.08.2026.

    upload_and_draft bruker drive.usercontent-formen, som hopper over
    varselet. Denne sjekken er der for at tallet skal staa i loggen, saa en
    bok som plutselig vokser blir synlig foer den blir et mysterium.
    """
    files = ctx.job.get("_pdf_files") or {}
    if not files:
        raise RuntimeError("build_pdfs har ikke kjoert")
    out = {}
    for key in ("cover", "inner", "gelato"):
        path = Path(files[key])
        if not path.is_file():
            raise RuntimeError(f"{key}-PDF mangler: {path}")
        mb = path.stat().st_size / 1e6
        out[f"{key}_mb"] = round(mb, 1)
        if key == "gelato" and mb > 100:
            ctx.log.warn(f"den samlede PDF-en er {mb:.1f} MB - over 100 MB maa "
                         f"Drive-lenka vaere drive.usercontent, ellers henter "
                         f"Gelato aldri filen inn")
    return out


# ---------------------------------------------------------------------------
# Drive og Gelato
# ---------------------------------------------------------------------------
def upload_and_draft(ctx: Context) -> dict:
    """Drive-opplasting + Gelato-UTKAST. Bekrefter ingenting.

    reprint_order.upload_and_draft() gjoer alt: mappe, tre opplastinger,
    offentliggjoering, drive.usercontent-URL, utkast med riktig productUid for
    cover_type, og sletting av gamle utkast paa samme orderReferenceId (Gelato
    avviser ikke duplikater og erstatter dem bare noen ganger selv).

    Nytt utkast lages FOER gamle ryddes, slik at ordren aldri staar uten.
    """
    info = _order_info(ctx)
    files = ctx.job.get("_pdf_files")
    if not files:
        raise RuntimeError("build_pdfs har ikke kjoert")

    # Bare hardcover selges, men softcover er default i koden. Send alltid
    # eksplisitt - her ved aa slaa fast hva info faktisk sier.
    if info.get("cover_type") not in ("hardcover", "softcover"):
        raise JobError(f"ukjent cover_type {info.get('cover_type')!r}")
    if info["cover_type"] != "hardcover":
        ctx.log.warn(f"cover_type er {info['cover_type']} - bare hardcover selges")

    # Nattbruddet 04:30-05:05 (se net.wait_for_internet). Dette steget er
    # ETTER sjekkpunktet i build_pdfs, saa meldingen er acket: feiler det
    # her, ligger en ferdig bok og venter paa at noen tilfeldigvis ser den.
    for host in ("https://www.googleapis.com/", "https://order.gelatoapis.com/"):
        net.wait_for_internet(host, ctx.log, ctx.cancelled)

    sys.path.insert(0, str(FLOW))
    import reprint_order
    result = _as_runtime_error(reprint_order.upload_and_draft, info, files,
                               make_draft=True)
    draft_id = result.get("draft_id")
    if not draft_id:
        raise RuntimeError("Gelato svarte uten utkast-id")
    ctx.job["_draft_id"] = draft_id
    return {"draft_id": draft_id,
            "drive": {k: v.get("id") for k, v in (result.get("drive") or {}).items()},
            "confirmed": False,
            "note": "utkast, ikke bestilling - mennesket bekrefter"}


def auto_merge_multibook(ctx: Context) -> dict:
    """Samle flere boeker i samme WooCommerce-ordre i ETT Gelato-utkast.

    Bare naar payloaden sier book_count > 1. Sidespor: feiler den, staar de
    to utkastene der som to utkast, og operatoeren kan slaa dem sammen fra
    Telegram.
    """
    count = int(ctx.payload.get("book_count") or 1)
    if count <= 1:
        return {"merged": False, "reason": "enkeltbok"}
    woo = str(ctx.job.get("woo_order_id") or "").strip()
    if not woo:
        return {"merged": False, "reason": "mangler order_id"}
    script = FLOW / "auto_merge_multibook.py"
    proc = subprocess.run([PYTHON, str(script), "--order-id", woo,
                           "--book-count", str(count)],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=1800)
    ctx.log.info("auto_merge_multibook", returncode=proc.returncode,
                 stdout=(proc.stdout or "")[-500:])
    return {"returncode": proc.returncode, "book_count": count,
            "stdout": (proc.stdout or "")[-1000:]}


# ---------------------------------------------------------------------------
# Varsling
# ---------------------------------------------------------------------------
def telegram_approval(ctx: Context) -> dict:
    """Si til operatoeren at et utkast er klart til gjennomgang.

    Teksten er den samme som "Send Telegram Approval" sender i dag, inkludert
    setningen om at bestillingen gjoeres manuelt - for det er fortsatt sant.
    """
    token = dp_secrets.get("worker_bot_token")
    chat = dp_secrets.get("worker_chat_id")
    if not token or chat in (None, ""):
        ctx.log.warn("worker_bot_token/worker_chat_id mangler - ingen varsling")
        return {"sent": False, "reason": "mangler token eller chat_id"}

    job = ctx.job
    draft = ctx.job.get("_draft_id")
    text = (
        "Nytt DreamPage Gelato-utkast klart.\n\n"
        f"Ordre:   {ctx.job_key}\n"
        f"Barn:    {job.get('child_name')}\n"
        f"Bok:     {job.get('book_title') or job.get('book_slug')}\n"
        f"Spraak:  {str(job.get('language') or 'nb').upper()}\n"
        f"Marked:  {str(job.get('market') or 'no').upper()}\n"
        f"Omslag:  {job.get('cover_type')}\n\n"
        f"Gelato-utkast:\nhttps://dashboard.gelato.com/orders/{draft}\n\n"
        "Gaa gjennom og bestill manuelt i Gelato."
    )
    # Via notify.send, slik at et varsel som ikke kommer fram havner i
    # utboksen i stedet for aa forsvinne. En ordre som er ferdig, men der
    # varselet ikke kom fram, er ikke en feilet ordre - den er en ordre ingen
    # har sett. Derfor rulles den ikke tilbake, men den skal fram.
    result = notify.send(text, log=ctx.log)
    result["draft_id"] = draft
    return result


# ---------------------------------------------------------------------------
# Opprydding
# ---------------------------------------------------------------------------
def cleanup_comfy_folder(ctx: Context) -> dict:
    """Slett ordrens comfy-mappe naar utkastet er laget.

    Rotsjekken er ikke paranoia: n8n-noden hadde noeyaktig samme
    `if (-not $target.StartsWith($root)) { throw }`, fordi et tomt
    comfyOutputPrefix ville gjort stien til hele output-mappa.

    Kjoeres SIST, og bare naar det finnes et utkast. Sidene er det eneste vi
    ikke kan lage om igjen uten GPU-tid.
    """
    if not ctx.job.get("_draft_id"):
        return {"deleted": False, "reason": "ingen Gelato-utkast - sidene beholdes"}
    target = books.comfy_output_dir(ctx.job).resolve()
    root = OUTPUT.resolve()
    if root not in target.parents:
        raise RuntimeError(f"nekter aa slette utenfor output-rota: {target}")
    if not target.is_dir():
        return {"deleted": False, "reason": f"{target} finnes ikke"}
    import shutil
    files = sum(1 for _ in target.rglob("*") if _.is_file())
    shutil.rmtree(target)
    return {"deleted": True, "path": str(target), "files": files}

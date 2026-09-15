# -*- coding: utf-8 -*-
"""DreamPage-operatørbot: bytt sider i en ordre og bygg den på nytt fra Telegram.

Kommandoer:
  /vis 1235 [3,7]           se sidene slik de ligger i boka nå
  /fix 1235 3,7 forside     render nye varianter av oppgitte sider
  /nyttbilde 1235           bytt barnebildet og render ALLE sider på nytt
  /bygg 1235                bygg PDF på nytt uten å endre sider
  /status 1235              hvor ordren står
  /avbryt 1235              forkast økten (ingenting er skrevet til boka enda)
  /hjelp

Sender du et bilde mens en side venter på svar, brukes DET bildet i stedet for
å rendre. Send det som FIL (dokument) - Telegram komprimerer vanlige bilder.

EGEN BOT-TOKEN. gelato_merge.py long-poller getUpdates på produksjonsboten
under hver ordre, og bare en prosess kan eie getUpdates per token. Deler de
token vil de spise hverandres svar - og det som ryker er godkjenningen av et
sammenslått Gelato-utkast på en betalt ordre.

Ingenting rører boka før du har godkjent, og Gelato-utkastet lages først
når du trykker på knappen.

  python dp_bot.py            (leser config/dp_bot.json)
"""
from __future__ import annotations

import datetime as dt
import glob
import io
import json
import mimetypes
import os
import queue
import re
import shutil
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import dp_merge
import dp_order
import dp_testbook
import regen_page
import render_next_cover
import reprint_order

CONFIG_PATH = r"C:\ComfyUI\config\dp_bot.json"
STATE_DIR = r"C:\ComfyUI\state\reprint"
# Egen state for fortsett-forsiden. Ikke i sidevalg-økta: den har en
# stage-maskin (picking -> rendering -> built) som fortsett-siden ikke er en
# del av, og å blande dem ville latt en halvferdig forside stoppe et sidebytte.
NEXT_STATE_DIR = r"C:\ComfyUI\state\next_cover"
# Et bygg tar minutter og lever bare i minnet. Dør boten underveis, er jobben
# borte, og «Bygger …» blir stående som siste melding for alltid. Markøren
# gjør et avbrutt bygg synlig ved neste oppstart.
INFLIGHT_DIR = r"C:\ComfyUI\state\reprint\inflight"
PREVIEW_DIR = r"C:\ComfyUI\tmp\dp_bot_previews"
LOG_PATH = r"C:\ComfyUI\state\dp_bot.log"

PREVIEW_MAX_WIDTH = 1600      # Telegram: <=10 MB og bredde+høyde <=10000
UPLOAD_DIR = r"C:\ComfyUI\tmp\dp_bot_uploads"

# Bot API tar 50 MB per dokument. Coverne er 3-6 MB og går rett gjennom,
# men innersider (54-68 MB) og gelato-PDF-en (57-74 MB) gjør det ALDRI -
# de må via Drive. Litt margin ned, for grensen gjelder hele forespørselen.
TELEGRAM_DOC_LIMIT = 49 * 1024 * 1024


# --------------------------------------------------------------------------
def log(message: str) -> None:
    line = f"{dt.datetime.now().isoformat(timespec='seconds')}  {message}"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    sys.stdout.write(line.encode(encoding, "replace").decode(encoding, "replace") + "\n")
    sys.stdout.flush()


def config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------
# Telegram
# --------------------------------------------------------------------------
def api(method: str, body: dict | None = None, files: dict | None = None,
        timeout: int = 90) -> dict:
    token = config()["bot_token"]
    url = f"https://api.telegram.org/bot{token}/{method}"

    if files:
        boundary = uuid.uuid4().hex
        buf = io.BytesIO()
        for key, value in (body or {}).items():
            if value is None:
                continue
            if not isinstance(value, str):
                value = json.dumps(value)
            buf.write(f"--{boundary}\r\nContent-Disposition: form-data; "
                      f'name="{key}"\r\n\r\n{value}\r\n'.encode())
        for key, path in files.items():
            name = os.path.basename(path)
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            with open(path, "rb") as fh:
                data = fh.read()
            buf.write(f"--{boundary}\r\nContent-Disposition: form-data; "
                      f'name="{key}"; filename="{name}"\r\n'
                      f"Content-Type: {ctype}\r\n\r\n".encode())
            buf.write(data)
            buf.write(b"\r\n")
        buf.write(f"--{boundary}--\r\n".encode())
        request = urllib.request.Request(url, data=buf.getvalue(), method="POST")
        request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    else:
        data = json.dumps(body or {}).encode()
        request = urllib.request.Request(url, data=data, method="POST")
        request.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:600]
        # Å tegne samme meny på nytt (f.eks. "Tilbake" to ganger) er ikke en
        # feil verdt å logge - Telegram avviser bare en identisk redigering.
        if "message is not modified" not in detail:
            log(f"[telegram] {method} HTTP {error.code}: {detail}")
        return {"ok": False, "description": detail}
    except Exception as error:                      # nettverk faller ut iblant
        log(f"[telegram] {method} feilet: {error}")
        return {"ok": False, "description": str(error)}


def esc(value) -> str:
    """Gjør vilkårlig tekst trygg å sende med parse_mode HTML.

    Feilmeldinger er det farlige stedet: en Python-feil kan inneholde
    <module '...' from '...'>, og da avviser Telegram HELE meldingen med
    «Unsupported start tag». Feilen forsvinner da sporløst - du får aldri
    vite at noe gikk galt. Det har skjedd (18.08 kl. 20:06).
    """
    return (str(value).replace("&", "&amp;")
                      .replace("<", "&lt;")
                      .replace(">", "&gt;"))


def strip_tags(text: str) -> str:
    """Fjern BARE formateringen vi selv bruker.

    Et generelt <[^>]+>-sveip ville spist nettopp det som gjorde at meldingen
    feilet - «<module 'dp' from '...'>» - og dermed kastet bort selve
    opplysningen du trenger for å skjønne feilen.
    """
    return re.sub(r"</?(?:b|i|s|u|code|pre|a|tg-spoiler|blockquote)(?:\s[^>]*)?>",
                  "", text)


def send(chat_id, text: str, buttons: list | None = None, reply_to=None) -> dict:
    body = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": True}
    if buttons:
        body["reply_markup"] = {"inline_keyboard": buttons}
    if reply_to:
        body["reply_to_message_id"] = reply_to
    result = api("sendMessage", body)

    # Sikkerhetsnett: slipper det gjennom noe uescapet et sted vi ikke har
    # tenkt på, er ren tekst uendelig mye bedre enn ingen melding.
    if not result.get("ok") and "parse entities" in (result.get("description") or ""):
        body.pop("parse_mode", None)
        body["text"] = strip_tags(text)
        result = api("sendMessage", body)
        log(f"sendte uten HTML-formatering (Telegram avviste taggene): "
            f"{strip_tags(text)[:120]!r}")
    return result


def send_album(chat_id, paths: list[str], caption: str,
               captions: list[str] | None = None) -> dict:
    """captions merker HVERT bilde - ellers havner teksten bare på det første.

    Når du blar gjennom sidene i en bok trenger du å vite hvilken side du
    ser på; et album uten merking er ubrukelig til å peke ut en dårlig side.
    """
    media = []
    files = {}
    for index, path in enumerate(paths):
        key = f"photo{index}"
        files[key] = path
        item = {"type": "photo", "media": f"attach://{key}"}
        if captions:
            item["caption"] = captions[index]
            item["parse_mode"] = "HTML"
        elif index == 0:
            item["caption"] = caption
            item["parse_mode"] = "HTML"
        media.append(item)
    return api("sendMediaGroup", {"chat_id": chat_id, "media": media},
               files=files, timeout=300)


def download_file(file_id: str, dest_dir: str) -> str:
    info = api("getFile", {"file_id": file_id})
    if not info.get("ok"):
        raise RuntimeError(f"getFile feilet: {info.get('description')}")
    path = info["result"]["file_path"]
    token = config()["bot_token"]
    url = f"https://api.telegram.org/file/bot{token}/{path}"
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"{uuid.uuid4().hex}-{os.path.basename(path)}")
    with urllib.request.urlopen(url, timeout=300) as resp, open(dest, "wb") as fh:
        shutil.copyfileobj(resp, fh)
    return dest


def preview(path: str, name_hint: str | None = None) -> str:
    """Sidene er 8192x4096 og ~50 MB - langt over Telegrams bildegrenser.

    name_hint skiller filer som heter det samme i to ordrer: de ferdige
    sidene heter alltid page03_00001_.png, så uten et hint ville ordre 1248
    og 1250 skrive over hverandres forhåndsvisning.
    """
    from PIL import Image
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    dest = os.path.join(PREVIEW_DIR,
                        (f"{name_hint}-{stem}" if name_hint else stem) + ".jpg")
    with Image.open(path) as img:
        img = img.convert("RGB")
        if img.width > PREVIEW_MAX_WIDTH:
            height = round(img.height * PREVIEW_MAX_WIDTH / img.width)
            img = img.resize((PREVIEW_MAX_WIDTH, height), Image.LANCZOS)
        img.save(dest, "JPEG", quality=88, optimize=True)
    return dest


# --------------------------------------------------------------------------
# Sidene slik de ligger i boka nå
# --------------------------------------------------------------------------
def body_label(variant: str) -> str:
    return (dp_order.BODY_VARIANTS.get(variant) or {}).get("label", variant)


def hair_label(variant: str) -> str:
    return (dp_order.HAIR_VARIANTS.get(variant) or {}).get("label", variant)


def skin_label(variant: str) -> str:
    return (dp_order.SKIN_VARIANTS.get(variant) or {}).get("label", variant)


def page_label(page_key: str) -> str:
    return "forside" if page_key == "page00" else page_key.replace("page", "side ")


def current_page_image(info: dict, page_key: str) -> str | None:
    """Bildet som faktisk havner i PDF-en for denne siden.

    input/ er fasiten, ikke comfy/: det er input/ tekst-scriptet leser, så
    har du byttet et bilde for hånd, er det DIN fil som blir trykket. Viste
    vi comfy-filen her, ville du fått se en side som ikke finnes i boka -
    og trodd at byttet ditt ikke virket.

    comfy/ er reserven for ordre som ikke er prepared enda. Der plukker
    prepare_order første fil som starter med page_key + "_", og
    commit_variant skriver alltid til page_key_00001_.png; erstattede sider
    ligger i _erstattet og skal ikke med.
    """
    from_input = reprint_order.input_file_for(info, page_key)
    if from_input:
        return from_input

    hits = [p for p in glob.glob(os.path.join(info["comfy_dir"], f"{page_key}_*"))
            if os.path.isfile(p)
            and os.path.splitext(p)[1].lower() in (".png", ".jpg", ".jpeg")]
    if not hits:
        return None
    hits.sort()
    return hits[0]


def page_keys_for(info: dict) -> list[str]:
    return [page["page_key"] for page in info["config"].get("pages", [])]


# --------------------------------------------------------------------------
# Økt-tilstand
# --------------------------------------------------------------------------
STATE_LOCK = threading.Lock()


def state_path(order_id: str) -> str:
    return os.path.join(STATE_DIR, f"{order_id}.json")


def load_state(order_id: str) -> dict | None:
    try:
        with open(state_path(order_id), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def save_state(session: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    path = state_path(session["order_id"])
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(session, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def drop_state(order_id: str) -> None:
    try:
        os.unlink(state_path(order_id))
    except OSError:
        pass


def active_sessions() -> list[dict]:
    if not os.path.isdir(STATE_DIR):
        return []
    out = []
    for name in os.listdir(STATE_DIR):
        if name.endswith(".json"):
            session = load_state(name[:-5])
            if session:
                out.append(session)
    return out


def pending_page(session: dict) -> str | None:
    """Første side som venter på at du velger."""
    for page_key, page in session["pages"].items():
        if page["status"] == "awaiting":
            return page_key
    return None


def next_unrendered(session: dict) -> str | None:
    for page_key, page in session["pages"].items():
        if page["status"] == "pending":
            return page_key
    return None


def blank_page() -> dict:
    return {"status": "pending", "variants": [], "chosen": None}


def ensure_page(session: dict, page_key: str) -> dict:
    """Hent sidas plass i økta, og lag den om den mangler.

    Åpner du sidevelgeren mens en render står på, skriver menu_pages økta om
    til en tom «picking»-økt. Den ferdige rendringen har da ingen side å
    legge seg i, og falt før på KeyError: bildene var laget, men ingen fikk
    se dem (ordre 1509, 15.09.2026). Vi lager plassen i stedet.
    """
    pages = session.setdefault("pages", {})
    if page_key not in pages:
        pages[page_key] = blank_page()
        picked = session.setdefault("picked", [])
        if isinstance(picked, list) and page_key not in picked:
            picked.append(page_key)
    return pages[page_key]


# --------------------------------------------------------------------------
JOBS: "queue.Queue[tuple]" = queue.Queue()

# Menyer og kommandoer kjører på en EGEN tråd, ikke på polling-løkka og
# ikke bak renderkøen. Et ordreoppslag som ikke er cachet tar ~7 sekunder
# (skann av n8n-databasen); ligger det på polling-tråden står hele boten
# stille imens, og knappetrykk rekker å utløpe.
UI_JOBS: "queue.Queue[tuple]" = queue.Queue()

# Å se på sidene er nettopp det du vil gjøre MENS noe rendres - står visning
# i renderkøen, må du vente en halvtime på å få se om siden var dårlig.
# Skalering er CPU og disk, den rører ikke GPU-en, så den kan gå parallelt.
VIEW_JOBS: "queue.Queue[tuple]" = queue.Queue()


def ui_loop() -> None:
    while True:
        kind, arg = UI_JOBS.get()
        try:
            if kind == "callback":
                handle_callback(arg)
            elif kind == "message":
                handle_message(arg)
        except SystemExit as error:
            chat = (arg.get("message") or arg).get("chat", {}).get("id")
            if chat:
                send(chat, f"❌ {esc(error)}")
        except Exception as error:
            log(traceback.format_exc())
            chat = (arg.get("message") or arg).get("chat", {}).get("id")
            if chat:
                send(chat, f"❌ {esc(error)}")
        finally:
            UI_JOBS.task_done()


def clear_stale_lock() -> None:
    """Rydd bort ComfyUI-låsen hvis den er vår egen fra en drept prosess.

    Boten er det eneste som lager låser med denne eieren, og den starter jo
    akkurat nå - så en slik lås er per definisjon foreldreløs. Blir den
    liggende, blokkerer den n8n-workeren i inntil to timer, altså en BETALT
    ordre.
    """
    lock = regen_page.read_lock()
    if lock and lock.get("owner") == "regen_page.py":
        try:
            os.unlink(regen_page.LOCK_PATH)
            log(f"ryddet foreldreløs ComfyUI-lås fra ordre "
                f"{lock.get('order_id')} ({lock.get('page_key')})")
        except OSError as error:
            log(f"klarte ikke å rydde låsen: {error}")


def build_marker_path(order_id: str) -> str:
    return os.path.join(INFLIGHT_DIR, f"{order_id}.json")


def write_build_marker(order_id: str, chat_id, extra: dict) -> None:
    try:
        os.makedirs(INFLIGHT_DIR, exist_ok=True)
        with open(build_marker_path(order_id), "w", encoding="utf-8") as fh:
            json.dump({"order_id": order_id, "chat_id": chat_id,
                       "skip_prepare": bool(extra.get("skip_prepare")),
                       "started_at": dt.datetime.now().isoformat(timespec="seconds")},
                      fh, ensure_ascii=False)
    except OSError as error:
        # Markøren er en hjelp, ikke en forutsetning - den skal aldri kunne
        # stoppe selve bygget.
        log(f"klarte ikke å skrive byggmarkør for {order_id}: {error}")


def clear_build_marker(order_id: str) -> None:
    try:
        os.unlink(build_marker_path(order_id))
    except OSError:
        pass


def recover_builds() -> None:
    """Si fra om bygg som ble avbrutt av at boten døde.

    Uten dette er siste melding i chatten «Bygger … Dette tar noen minutter»,
    og den blir stående. Det skjedde med ordre 1411-b2 05.09.2026: cover og
    innersider ble ferdige, Gelato-PDF-en ble aldri laget, og ingen fikk vite
    det før noen så etter.
    """
    try:
        names = sorted(os.listdir(INFLIGHT_DIR))
    except OSError:
        return
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(INFLIGHT_DIR, name)
        try:
            with open(path, encoding="utf-8") as fh:
                mark = json.load(fh)
        except (OSError, json.JSONDecodeError):
            mark = {}
        order_id = mark.get("order_id") or name[:-5]
        chat_id = mark.get("chat_id")
        try:
            os.unlink(path)
        except OSError:
            pass
        log(f"avbrutt bygg funnet: {order_id} (startet {mark.get('started_at')})")
        if not chat_id:
            continue
        send(chat_id,
             f"↩️ Byggingen av <b>{order_id}</b> ble avbrutt da boten stoppet "
             f"({mark.get('started_at')}). PDF-ene kan være ufullstendige — "
             "bygg på nytt før du laster opp.", [
                 [{"text": "🔨 Bygg PDF på nytt",
                   "callback_data": f"build|{order_id}||0"}],
                 [{"text": "◀ Til ordren", "callback_data": f"ord|{order_id}||0"}]])


def recover_sessions() -> None:
    """Ta opp igjen økter som ble avbrutt av en restart.

    ComfyUI gjør ferdig det den holder på med selv om boten dor, så
    bildene ligger som regel klare på disk - de mangler bare noen til å
    sende dem.
    """
    resume: list = []
    for session in active_sessions():
        order_id = session["order_id"]
        chat_id = session.get("chat_id")
        if not chat_id:
            continue
        try:
            info = dp_order.resolve(order_id)
        except (SystemExit, Exception) as error:
            # resolve kaster SystemExit for ordre uten n8n-payload. Uten
            # SystemExit her dør hele gjenopprettingstråden på den første
            # slike ordren, og resten av øktene blir aldri tatt opp igjen.
            log(f"gjenoppretting hoppet over {order_id}: {error}")
            continue

        changed = False
        for page_key, page in session["pages"].items():
            if page["status"] != "rendering":
                continue
            found = regen_page.existing_variants(info, page_key)
            if found:
                page["variants"] = found
                changed = True
                log(f"gjenopptok {order_id}/{page_key}: {len(found)} varianter på disk")
                if session.get("auto"):
                    # En auto-kjøring som stopper og spør etter en restart er
                    # ikke lenger en auto-kjøring; da står boka og venter på
                    # et trykk du ikke visste om.
                    page["chosen"] = found[-1]
                    page["status"] = "approved"
                    send(chat_id, f"↩️ Boten ble restartet under "
                                  f"<b>{page_key}</b> (ordre {order_id}). Siden "
                                  "ble ferdig — fortsetter automatisk.")
                    resume.append((order_id, chat_id))
                else:
                    page["status"] = "awaiting"
                    send(chat_id, f"↩️ Boten ble restartet mens "
                                  f"<b>{page_key}</b> (ordre {order_id}) ble "
                                  "rendret. Bildene ble ferdige — her er de.")
                    show_variants(order_id, chat_id, page_key, found)
            else:
                page["status"] = "pending"
                changed = True
                log(f"gjenopptok {order_id}/{page_key}: ingen varianter, rendres på nytt")
                enqueue("render", order_id, chat_id, page_key=page_key)
        if changed:
            with STATE_LOCK:
                save_state(session)
    for order_id, chat_id in resume:
        advance(order_id, chat_id)


def warm_cache() -> None:
    """Bygg ordreindeksen i bakgrunnen, så ingen menytrykk venter på den.

    ALT her fanger SystemExit i tillegg til Exception: dp_order.resolve kaster
    SystemExit for ordre som ikke finnes i n8n (f.eks. testmapper som
    "1230-test"). Fanges den ikke, dør tråden på den første slike ordren og
    build_index kjører aldri - da er hvert første oppslag tilbake på 7-9
    sekunder, uten at noe som helst sier fra.
    """
    started = time.time()
    for order_id, _slug in recent_orders(10):
        try:
            dp_order.resolve(order_id)
        except (SystemExit, Exception):
            pass
    log(f"ordrecache varmet ({time.time() - started:.0f}s)")
    try:
        # Et bomtreff (ordremappe uten n8n-execution, f.eks. "1230-test")
        # skanner alle executions og bygger dermed indeksen her. Da melder
        # build_index 0 nye - det er riktig, jobben er alt gjort.
        added = dp_order.build_index()
        log(f"ordreindeks bygget ({added} nye executions, "
            f"{time.time() - started:.0f}s totalt)")
    except (SystemExit, Exception) as error:
        log(f"indeksbygging feilet: {error}")


CANCEL = threading.Event()


def enqueue(kind: str, order_id: str, chat_id, **extra) -> None:
    JOBS.put((kind, order_id, chat_id, extra))


def enqueue_view(order_id: str, chat_id, **extra) -> None:
    VIEW_JOBS.put((order_id, chat_id, extra))


def view_loop() -> None:
    while True:
        order_id, chat_id, extra = VIEW_JOBS.get()
        try:
            if "pdf" in extra:
                job_send_pdf(order_id, chat_id, extra)
            elif extra.get("next_cover"):
                job_next_view(order_id, chat_id, extra)
            elif extra.get("variants_for"):
                job_show_variants(order_id, chat_id, extra)
            else:
                job_view(order_id, chat_id, extra)
        except SystemExit as error:
            send(chat_id, f"❌ <b>{order_id}</b>: {esc(error)}")
        except Exception as error:
            log(traceback.format_exc())
            send(chat_id, f"❌ kunne ikke vise <b>{order_id}</b>: {esc(error)}")
        finally:
            VIEW_JOBS.task_done()


def stop_everything(chat_id, reset: bool = False) -> None:
    """Stopp alt arbeid nå. Med reset=True forkastes øktene også."""
    CANCEL.set()

    dropped = 0
    for pending in (JOBS, VIEW_JOBS):
        while True:
            try:
                pending.get_nowait()
                pending.task_done()
                dropped += 1
            except queue.Empty:
                break

    # ComfyUI avbrytes BARE hvis låsen er vår. Er den n8n sin, kjører det en
    # betalt ordre der inne, og den skal ikke stoppes av en reprint-kommando.
    lock = regen_page.read_lock()
    ours = bool(lock and lock.get("owner") == "regen_page.py")
    if ours:
        regen_page.interrupt()
        try:
            os.unlink(regen_page.LOCK_PATH)
        except OSError:
            pass
    elif lock:
        log(f"stopp: rorte ikke ComfyUI - låsen tilhorer {lock.get('executionId')} "
            f"(ordre {lock.get('order_id')})")

    lines = [f"🛑 Stoppet. {dropped} jobb(er) fjernet fra køen."]
    lines.append("ComfyUI avbrutt." if ours
                 else "ComfyUI ble ikke rort — den jobber ikke for meg nå."
                      if lock else "ComfyUI var ledig.")

    if reset:
        count = 0
        for session in active_sessions():
            drop_state(session["order_id"])
            count += 1
        lines.append(f"{count} økt(er) forkastet. Ingen bøker er endret.")
    else:
        lines.append("Øktene er beholdt — valgene dine står.")

    send(chat_id, "\n".join(lines))
    # Gi den pågående jobben et øyeblikk på å se flagget, ellers rekker
    # den neste jobben å bli avbrutt av et flagg som skulle vært nullstilt.
    threading.Timer(5.0, CANCEL.clear).start()


def worker_loop() -> None:
    while True:
        kind, order_id, chat_id, extra = JOBS.get()
        if kind == "build":
            write_build_marker(order_id, chat_id, extra)
        try:
            if kind == "render":
                job_render(order_id, chat_id, extra)
            elif kind == "build":
                job_build(order_id, chat_id, extra)
            elif kind == "publish":
                job_publish(order_id, chat_id, extra)
            elif kind == "merge":
                job_merge(order_id, chat_id, extra)
            elif kind == "testbook":
                job_testbook(order_id, chat_id, extra)
            elif kind == "nextrender":
                job_next_render(order_id, chat_id, extra)
            elif kind == "nextapply":
                job_next_apply(order_id, chat_id, extra)
        except SystemExit as error:
            send(chat_id, f"❌ <b>{order_id}</b>: {esc(error)}")
        except Exception as error:
            log(traceback.format_exc())
            send(chat_id, f"❌ <b>{order_id}</b> feilet: {esc(error)}")
        finally:
            if kind == "build":
                clear_build_marker(order_id)
            JOBS.task_done()


# --------------------------------------------------------------------------
def job_render(order_id: str, chat_id, extra: dict) -> None:
    with STATE_LOCK:
        session = load_state(order_id)
    if not session:
        return
    page_key = extra.get("page_key") or next_unrendered(session)
    if not page_key:
        offer_build(order_id, chat_id)
        return

    count = int(extra.get("count") or session.get("variants") or 3)
    info = dp_order.resolve(order_id)
    face = session.get("face_image") or info["face_image"]

    keys = list(session["pages"])
    position = keys.index(page_key) + 1 if page_key in keys else len(keys) + 1
    total_pages = max(len(keys), position)

    with STATE_LOCK:
        session = load_state(order_id) or session
        ensure_page(session, page_key)["status"] = "rendering"
        save_state(session)

    # En melding som redigeres, ikke en ny per steg: du ser at det går
    # framover uten at chatten fylles opp. En editMessageText koster noen
    # hundre millisekunder og rører ikke GPU-en.
    label = "forside" if page_key == "page00" else page_key.replace("page", "side ")
    variant = dp_order.body_variant(info)
    body_note = ""
    if variant != dp_order.DEFAULT_BODY_VARIANT:
        has = page_key in dp_order.variant_pages(info["config"], variant)
        body_note = (f"\n🧍 {body_label(variant)}" if has
                     else f"\n🧍 {body_label(variant)} — mangler for denne sida, "
                          "bruker standardmalen")
    hair = dp_order.hair_variant(info)
    if hair != dp_order.DEFAULT_HAIR_VARIANT:
        has = page_key in dp_order.hair_variant_pages(info["config"], hair, variant)
        body_note += (f"\n💇 {hair_label(hair)}" if has
                      else f"\n💇 {hair_label(hair)} — mangler for denne sida, "
                           "bruker standardmalen")
    skin = dp_order.skin_variant(info)
    if skin != dp_order.DEFAULT_SKIN_VARIANT:
        has = page_key in dp_order.skin_variant_pages(info["config"], skin,
                                                      variant, hair)
        body_note += (f"\n🧑🏾 {skin_label(skin)}" if has
                      else f"\n🧑🏾 {skin_label(skin)} — mangler for denne "
                           "sida, bruker standardmalen")
    head = (f"🎨 <b>Ordre {order_id}</b> · {info['book_slug']}\n"
            f"{label} ({position} av {total_pages}){body_note}")
    status = send(chat_id, head + f"\n\n▱▱▱ starter …")
    message_id = (status.get("result") or {}).get("message_id")
    started = time.time()

    def progress(index: int, of: int) -> None:
        if not message_id:
            return
        bar = "▰" * index + "▱" * (of - index)
        elapsed = int(time.time() - started)
        note = ""
        if index:
            eta = int(elapsed / index * (of - index))
            note = f" · ~{eta // 60}m {eta % 60}s igjen"
        api("editMessageText", {
            "chat_id": chat_id, "message_id": message_id, "parse_mode": "HTML",
            "text": head + f"\n\n{bar}  variant {index + 1} av {of}{note}"},
            timeout=15)

    try:
        paths = regen_page.render_variants(info, page_key, count,
                                           face_image=face, on_progress=progress,
                                           should_cancel=CANCEL.is_set)
    except regen_page.Cancelled:
        with STATE_LOCK:
            session = load_state(order_id)
            if session:
                ensure_page(session, page_key)["status"] = "pending"
                save_state(session)
        if message_id:
            api("editMessageText", {"chat_id": chat_id, "message_id": message_id,
                                    "parse_mode": "HTML",
                                    "text": head + "\n\n🛑 avbrutt"}, timeout=15)
        return
    if message_id:
        api("editMessageText", {
            "chat_id": chat_id, "message_id": message_id, "parse_mode": "HTML",
            "text": head + f"\n\n{'▰' * count}  ferdig — sender bildene …"},
            timeout=15)

    with STATE_LOCK:
        # Økta kan ha blitt forkastet eller nullstilt mens GPU-en jobbet.
        # Bildene finnes uansett på disk - de skal fram til deg.
        session = load_state(order_id) or {
            "order_id": order_id, "chat_id": chat_id, "stage": "collecting",
            "face_image": face, "variants": count,
            "created_at": dt.datetime.now().isoformat(timespec="seconds"),
            "picked": [], "pages": {}}
        page = ensure_page(session, page_key)
        page["variants"] = (page.get("variants") or []) + paths
        # "3 til" ber uttrykkelig om et valg, også midt i en auto-kjøring.
        auto = bool(session.get("auto")) and not extra.get("choose")
        if auto:
            page["chosen"] = page["variants"][-1]
            page["status"] = "approved"
        else:
            page["status"] = "awaiting"
        save_state(session)
        offered = page["variants"]

    if auto:
        if message_id:
            api("editMessageText", {
                "chat_id": chat_id, "message_id": message_id,
                "parse_mode": "HTML",
                "text": head + f"\n\n{'▰' * count}  ✅ klar"}, timeout=15)
        advance(order_id, chat_id)
        return

    show_variants(order_id, chat_id, page_key, offered)


def job_show_variants(order_id: str, chat_id, extra: dict) -> None:
    """Send variantvalget for en side på nytt.

    En side som står i «awaiting» stopper hele økta: advance() tilbyr aldri
    bygging så lenge pending_page() finner en. Kom valgmeldingen bort - den
    druknet i chatten, eller albumet nådde aldri fram - er det ingen vei
    videre uten dette. Ordre 1417 sto slik 05.09.2026.
    """
    page_key = extra["variants_for"]
    with STATE_LOCK:
        session = load_state(order_id)
    page = ((session or {}).get("pages") or {}).get(page_key)
    if not page or not page.get("variants"):
        send(chat_id, f"Fant ingen varianter for <b>{page_key}</b> på ordre "
                      f"{order_id} — sida må rendres på nytt.", [[
            {"text": "🔁 Rendre på nytt",
             "callback_data": f"more|{order_id}|{page_key}|3"}]])
        return
    show_variants(order_id, chat_id, page_key, page["variants"])


def job_view(order_id: str, chat_id, extra: dict) -> None:
    """Send sidene slik boka ser ut NÅ, én merket bildeserie.

    Uten dette må du gjette: du ser bare de nye variantene boten rendrer, og
    har ingenting å sammenligne med - altså ingen måte å avgjøre om en side
    er dårlig før du har brukt GPU-tid på å lage en ny.
    """
    info = dp_order.resolve(order_id)
    known = page_keys_for(info)
    if extra.get("page_keys"):
        keys = [k for k in known if k in set(extra["page_keys"])] or list(extra["page_keys"])
    elif extra.get("page_key"):
        keys = [extra["page_key"]]
    else:
        keys = known
    only = len(keys) == 1

    head = (f"🖼 <b>Ordre {order_id}</b> · {info['book_slug']} · "
            f"{esc(info['child_name'])}")
    status = send(chat_id, head + f"\n\n▱ henter {len(keys)} side(r) …")
    message_id = (status.get("result") or {}).get("message_id")

    ready: list[tuple[str, str]] = []          # (forhåndsvisning, merkelapp)
    missing: list[str] = []
    for index, page_key in enumerate(keys):
        if CANCEL.is_set():
            break
        source = current_page_image(info, page_key)
        if not source:
            missing.append(page_key)
            continue
        try:
            ready.append((preview(source, name_hint=order_id),
                          f"<b>{page_label(page_key)}</b>"))
        except Exception as error:                 # en ødelagt fil skal ikke
            log(f"[vis] {order_id} {page_key}: {error}")   # stoppe resten
            missing.append(page_key)
        if message_id and not only:
            bar = "▰" * (index + 1) + "▱" * (len(keys) - index - 1)
            api("editMessageText", {
                "chat_id": chat_id, "message_id": message_id,
                "parse_mode": "HTML",
                "text": head + f"\n\n{bar}  skalerer {index + 1} av {len(keys)}"},
                timeout=15)

    if message_id:
        api("editMessageText", {
            "chat_id": chat_id, "message_id": message_id, "parse_mode": "HTML",
            "text": head + f"\n\n{len(ready)} side(r) — nyeste versjon i boka."
                    + (f"\n⚠ ikke rendret enda: {', '.join(missing)}" if missing else "")},
            timeout=15)

    # Telegram tar maks 10 bilder i et album.
    for start in range(0, len(ready), 10):
        chunk = ready[start:start + 10]
        send_album(chat_id, [path for path, _ in chunk], "",
                   captions=[text for _, text in chunk])
        if start + 10 < len(ready):
            time.sleep(1)                          # Telegram misliker hastverk

    if not ready:
        send(chat_id, f"Fant ingen ferdige sidebilder for <b>{order_id}</b>.")
        return
    send(chat_id, "Se noe du vil bytte?", [[
        {"text": "🖼 Bytt sider", "callback_data": f"pgs|{order_id}||0"},
        {"text": "◀ Tilbake", "callback_data": f"ord|{order_id}||0"},
    ]])


# --------------------------------------------------------------------------
# Ferdige PDF-er ut av boten
# --------------------------------------------------------------------------
PDF_KINDS = (("gelato", "_gelato.pdf", "📕 Gelato (trykkeklar)"),
             ("inner", "_innersider.pdf", "📄 Innersider"),
             ("cover", "_cover.pdf", "📘 Cover"))


def order_pdfs(info: dict) -> list[tuple[str, str, str, int]]:
    """(nøkkel, merkelapp, sti, størrelse) for PDF-ene som ligger i pdf/.

    Vi matcher på etternavnet, ikke på barnets navn: navnet kan inneholde
    mellomrom og aksenter, og en ordre er noen ganger bygget under et annet
    navn enn payloaden sier.

    Innenfor hver type vinner den NYESTE fila. Bygger du om utenfor boten,
    eller under et annet barnenavn, blir det liggende flere `*_gelato.pdf` i
    mappa - og en alfabetisk sortering plukket da like gjerne den to timer
    gamle som den fra i går. Nå avgjør mtime.

    (Ren VERSAL-endring gir bare én fil: Windows er case-insensitivt, så
    «Lavrans_gelato.pdf» overskriver «LAVRANS_gelato.pdf». Det er ulike NAVN
    som skaper doble filer.)

    De eldre filene forsvinner ikke - de listes under, med navn og dato, så
    du fortsatt kan hente en tidligere bygging bevisst.
    """
    folder = info["pdf_dir"]
    if not os.path.isdir(folder):
        return []
    found = []
    taken = set()
    for key, suffix, label in PDF_KINDS:
        hits = glob.glob(os.path.join(folder, f"*{suffix}"))
        if not hits:
            continue
        newest = max(hits, key=os.path.getmtime)
        found.append((key, label, newest, os.path.getsize(newest)))
        taken.add(newest)
    for path in sorted(glob.glob(os.path.join(folder, "*.pdf")),
                       key=os.path.getmtime, reverse=True):
        if path not in taken:
            found.append(("other", "📄 " + os.path.basename(path), path,
                          os.path.getsize(path)))
    return found


# --------------------------------------------------------------------------
# Testbok — hele flyten uten n8n, Drive og Gelato
#
# Bilde + navn + bok inn, ferdig PDF ut. Ordren er syntetisk: payloaden
# skrives rett i ordrecachen, så resten av maskineriet (regen_page,
# prepare_order, tekst-scriptet, build_gelato_pdf) kjører nøyaktig som for en
# betalt ordre — det er jo det man vil teste.
# --------------------------------------------------------------------------
# chat_id -> {"slug":…, "name":…, "stage": "navn"|"bilde"}
PENDING_TEST: dict = {}


def menu_test(chat_id, message_id=None) -> None:
    books = dp_testbook.testable_books()
    rows = [[{"text": name, "callback_data": f"tstb|{slug}||0"}]
            for slug, name in books]
    rows.append([{"text": "🗑 Rydd testbøker", "callback_data": "tstl|||0"}])
    rows.append([{"text": "◀ Tilbake", "callback_data": "menu|||0"}])
    text = ("<b>🧪 Test en bok</b>\n\nVelg bok, send navn og bilde — så bygges "
            "hele boka og du får PDF-en.\n\n"
            "<i>Ingenting lastes opp til Drive, ingen Gelato-ordre lages, og "
            "ingen jobb går gjennom n8n. Testordren kan slettes etterpå.</i>")
    if message_id:
        api("editMessageText", {"chat_id": chat_id, "message_id": message_id,
                                "text": text, "parse_mode": "HTML",
                                "reply_markup": {"inline_keyboard": rows}})
    else:
        send(chat_id, text, rows)


def menu_test_list(chat_id, message_id=None) -> None:
    tests = dp_testbook.list_tests()
    if not tests:
        send(chat_id, "Ingen testbøker på disk.", [[
            {"text": "◀ Tilbake", "callback_data": "tst|||0"}]])
        return
    rows = [[{"text": f"🗑 {item['order_id']} · {item['book_slug']}",
              "callback_data": f"tstd|{item['order_id']}||0"}] for item in tests]
    rows.append([{"text": "◀ Tilbake", "callback_data": "tst|||0"}])
    lines = ["<b>Testbøker</b>  <i>(trykk for å slette)</i>", ""]
    for item in tests:
        lines.append(f"  <code>{item['order_id']}</code> · {item['book_slug']} "
                     f"· {len(item['pdfs'])} PDF")
    text = "\n".join(lines)
    if message_id:
        api("editMessageText", {"chat_id": chat_id, "message_id": message_id,
                                "text": text, "parse_mode": "HTML",
                                "reply_markup": {"inline_keyboard": rows}})
    else:
        send(chat_id, text, rows)


def job_testbook(order_id: str, chat_id, extra: dict) -> None:
    info = dp_order.resolve(order_id)
    pages = info["config"].get("pages", [])
    variant = dp_order.body_variant(info)
    head = (f"🧪 <b>Testbok {order_id}</b>\n"
            f"{info['config'].get('displayName', info['book_slug'])} · "
            f"{esc(info['child_name'])}"
            + ("" if variant == dp_order.DEFAULT_BODY_VARIANT
               else f" · {body_label(variant)}"))
    status = send(chat_id, head + f"\n\n▱ starter — {len(pages)} sider …")
    message_id = (status.get("result") or {}).get("message_id")
    started = time.time()

    def on_page(index: int, total: int, page_key: str) -> None:
        if not message_id:
            return
        bar = "▰" * index + "▱" * (total - index)
        elapsed = int(time.time() - started)
        note = ""
        if index:
            eta = int(elapsed / index * (total - index))
            note = f" · ~{eta // 60}m igjen"
        api("editMessageText", {
            "chat_id": chat_id, "message_id": message_id, "parse_mode": "HTML",
            "text": head + f"\n\n{bar}  {page_label(page_key)} "
                           f"({index + 1} av {total}){note}"}, timeout=15)

    try:
        dp_testbook.render_all(info, on_page=on_page,
                               should_cancel=CANCEL.is_set)
    except regen_page.Cancelled:
        if message_id:
            api("editMessageText", {"chat_id": chat_id, "message_id": message_id,
                                    "parse_mode": "HTML",
                                    "text": head + "\n\n🛑 avbrutt"}, timeout=15)
        return

    if message_id:
        api("editMessageText", {
            "chat_id": chat_id, "message_id": message_id, "parse_mode": "HTML",
            "text": head + f"\n\n{'▰' * len(pages)}  sidene er klare — "
                           "bygger PDF …"}, timeout=15)

    files = dp_testbook.build(info)
    minutes = int(time.time() - started) // 60
    send(chat_id,
         f"✅ <b>Testbok {order_id}</b> ferdig på ~{minutes} min.\n"
         f"{info['config'].get('displayName', info['book_slug'])} · "
         f"{esc(info['child_name'])}\n"
         f"Innersider: {files['inner_pages']} · Gelato-PDF: "
         f"{files['total_pages']} sider, "
         f"{os.path.getsize(files['gelato']) / 1e6:.1f} MB\n\n"
         "<i>Ingenting er lastet opp og ingen Gelato-ordre er laget.</i>", [
             [{"text": "📄 Hent PDF", "callback_data": f"pdf|{order_id}||0"}],
             [{"text": "👁 Se sidene", "callback_data": f"view|{order_id}||0"}],
             [{"text": "🗑 Slett testboka", "callback_data": f"tstd|{order_id}||0"}],
         ])


# --------------------------------------------------------------------------
# Barnets navn
#
# Kunder skriver ofte navnet i VERSALER i nettbutikken. Navnet står i
# payloaden fra n8n, og uten en retting ville hver eneste ombygging skrevet
# LAVRANS inn i boka på nytt.
# --------------------------------------------------------------------------
# Neste tekstmelding fra denne chatten er et navn, ikke en kommando.
PENDING_NAME: dict = {}


def titlecase_name(raw: str) -> str:
    """LAVRANS -> Lavrans, ANNE-MARIE -> Anne-Marie, OLA NORDMANN -> Ola Nordmann.

    Deler på det som ikke er bokstaver, så bindestrek og apostrof beholdes -
    en .title() ville gitt «Anne-Marie» riktig, men også «O'Brien» -> «O'Brien»
    med stor B, og norske navn med bindestrek er vanlige nok til å bry seg om.
    """
    return re.sub(r"[^\s\-']+",
                  lambda m: m.group(0)[:1].upper() + m.group(0)[1:].lower(),
                  (raw or "").strip())


def apply_name(chat_id, order_id: str, new_name: str) -> None:
    new_name = (new_name or "").strip()
    if not new_name:
        send(chat_id, "Tomt navn — ingenting endret.")
        return
    if len(new_name) > 40:
        send(chat_id, "Det navnet er mistenkelig langt — ingenting endret.")
        return

    info = dp_order.resolve(order_id)
    before = info["child_name"]
    dp_order.set_override(order_id, "child_name", new_name)
    log(f"ordre {order_id}: barnets navn {before!r} -> {new_name!r}")

    send(chat_id,
         f"✏️ <b>Ordre {order_id}</b>: navnet er nå <b>{esc(new_name)}</b> "
         f"(var <s>{esc(before)}</s>).\n\n"
         "Lagret på ordren — alle framtidige bygg bruker dette navnet, både i "
         "teksten i boka og i PDF-filnavnene.\n\n"
         "⚠️ <b>Boka må bygges på nytt</b> for at navnet skal komme inn i "
         "sidene. Den gamle PDF-en har fortsatt det gamle navnet.", [
             [{"text": "🔨 Bygg PDF på nytt", "callback_data": f"build|{order_id}||0"}],
             [{"text": "◀ Til ordren", "callback_data": f"ord|{order_id}||0"}],
         ])


def menu_name(chat_id, order_id: str, message_id=None) -> None:
    info = dp_order.resolve(order_id)
    current = info["child_name"]
    payload_name = info["child_name_payload"]
    suggestion = titlecase_name(current)

    lines = [f"<b>Ordre {order_id}</b> — barnets navn",
             f"\nNå: <b>{current}</b>"]
    if current != payload_name:
        lines.append(f"<i>Fra kunden: {payload_name}</i>")

    rows = []
    if suggestion != current:
        rows.append([{"text": f"✅ Bruk «{suggestion}»",
                      "callback_data": f"nam!|{order_id}||0"}])
        lines.append(f"\nForslag: <b>{suggestion}</b>")
    rows.append([{"text": "⌨️ Skriv navnet selv",
                  "callback_data": f"namx|{order_id}||0"}])
    if current != payload_name:
        rows.append([{"text": f"↩️ Tilbake til «{payload_name}»",
                      "callback_data": f"nam0|{order_id}||0"}])
    rows.append([{"text": "◀ Tilbake", "callback_data": f"ord|{order_id}||0"}])

    lines.append("\n<i>Navnet lagres på ordren og brukes i alle senere bygg. "
                 "Boka må bygges på nytt for at det skal vises i sidene.</i>")
    text = "\n".join(lines)
    if message_id:
        api("editMessageText", {"chat_id": chat_id, "message_id": message_id,
                                "text": text, "parse_mode": "HTML",
                                "reply_markup": {"inline_keyboard": rows}})
    else:
        send(chat_id, text, rows)


def menu_pdf(chat_id, order_id: str, message_id=None) -> None:
    info = dp_order.resolve(order_id)
    files = order_pdfs(info)
    if not files:
        send(chat_id, f"Ingen PDF i <code>pdf/</code> for <b>{order_id}</b> enda. "
                      "Bygg den først.", [[
            {"text": "🔨 Bygg PDF", "callback_data": f"build|{order_id}||0"},
            {"text": "◀ Tilbake", "callback_data": f"ord|{order_id}||0"},
        ]])
        return

    rows = []
    lines = [f"<b>Ordre {order_id}</b> — ferdige PDF-er:"]
    newest = max(os.path.getmtime(path) for _, _, path, _ in files)
    for index, (key, label, path, size) in enumerate(files):
        mb = size / 1e6
        via = "Telegram" if size <= TELEGRAM_DOC_LIMIT else "Drive-lenke"
        built = os.path.getmtime(path)
        # Er en fil eldre enn den nyeste i mappa, er den nesten alltid en
        # rest fra et tidligere bygg - da skal du se det før du sender den.
        stamp = dt.datetime.fromtimestamp(built).strftime("%d.%m %H:%M")
        old = " ⚠️ eldre" if built < newest - 120 else ""
        lines.append(f"  {label} — {mb:.1f} MB · {stamp}{old} <i>({via})</i>")
        rows.append([{"text": f"{label} · {mb:.0f} MB · {stamp}",
                      "callback_data": f"pdfg|{order_id}|{index}|0"}])
    lines.append("\n<i>Over 50 MB kan ikke sendes i Telegram — de legges på "
                 "Drive og du får en lenke du kan sende videre.</i>")
    rows.append([{"text": "◀ Tilbake", "callback_data": f"ord|{order_id}||0"}])

    text = "\n".join(lines)
    if message_id:
        api("editMessageText", {"chat_id": chat_id, "message_id": message_id,
                                "text": text, "parse_mode": "HTML",
                                "reply_markup": {"inline_keyboard": rows}})
    else:
        send(chat_id, text, rows)


# --------------------------------------------------------------------------
# Slå sammen to ordre til ett Gelato-utkast
#
# Erstatter den automatiske gaten i n8n, som lette etter kandidater ved HVER
# betalte ordre og spurte i gruppa der alle ordre lander. Nå skjer det bare
# når du ber om det, herfra.
# --------------------------------------------------------------------------
def merge_selection(raw) -> list[str]:
    """CSV fra callback_data → ordreliste uten duplikater, rekkefølgen bevart.

    "0" er fyllverdien i det gamle firefelts-formatet (`mrgB|1281|1282|0`) og
    aldri et ordrenummer, så den kastes — ellers ville gamle knapper i eldre
    meldinger tolket fyllverdien som en ordre.
    """
    out = []
    for part in str(raw or "").replace(" ", "").split(","):
        if part and part != "0" and part not in out:
            out.append(part)
    return out


def menu_merge(chat_id, selected="", message_id=None) -> None:
    """Velg så mange ordre du vil — trykk en gang til for å fjerne igjen.

    Var tidligere låst til nøyaktig to (velg første, velg andre). Tre bøker
    til samme adresse er ikke uvanlig, og da ble det to forsendelser.
    """
    chosen = merge_selection(selected)
    orders = recent_orders(12)
    known = {oid for oid, _ in orders}
    rows = []
    for oid, slug in orders:
        if oid in chosen:
            label = f"✅ {chosen.index(oid) + 1}. {oid} · {slug}"
        else:
            label = f"{oid} · {slug}"
        rest = [o for o in chosen if o != oid] if oid in chosen else chosen + [oid]
        rows.append([{"text": label, "callback_data": f"mrgT|{oid}||{','.join(rest)}"}])
    # Ordre du har skrevet inn manuelt kan ligge utenfor de 12 nyeste.
    for oid in chosen:
        if oid not in known:
            rest = [o for o in chosen if o != oid]
            rows.append([{"text": f"✅ {chosen.index(oid) + 1}. {oid}",
                          "callback_data": f"mrgT|{oid}||{','.join(rest)}"}])

    text = ("<b>Slå sammen ordre</b>\n\nVelg <b>to eller flere</b> ordre som skal "
            "i samme utkast og samme forsendelse. Trykk en gang til for å fjerne.\n\n"
            "<i>Alle må være bygget og ha samme mottaker. PDF-ene lastes alltid "
            "opp på nytt, så den nyeste versjonen er den som trykkes.</i>")
    if chosen:
        text += (f"\n\nValgt: <b>{', '.join(chosen)}</b>\nDet samlede utkastet får "
                 f"ordrenummeret til <b>{chosen[0]}</b> (den første du valgte).")
    if len(chosen) >= 2:
        rows.append([{"text": f"▶ Fortsett med {len(chosen)} ordre",
                      "callback_data": f"mrgB|{chosen[0]}||{','.join(chosen)}"}])
    elif len(chosen) == 1:
        text += "\n\n<i>Velg minst én til.</i>"
    if chosen:
        rows.append([{"text": "✖ Tøm valget", "callback_data": "mrg|||0"}])
    rows.append([{"text": "◀ Tilbake", "callback_data": "menu|||0"}])

    if message_id:
        api("editMessageText", {"chat_id": chat_id, "message_id": message_id,
                                "text": text, "parse_mode": "HTML",
                                "reply_markup": {"inline_keyboard": rows}})
    else:
        send(chat_id, text, rows)


def confirm_merge(chat_id, orders, message_id=None) -> None:
    """Siste steg: vis alle bøkene, med advarsler, før noe røres."""
    orders = merge_selection(",".join(str(o) for o in orders))
    if len(orders) < 2:
        send(chat_id, "❌ Trenger minst to ordre å slå sammen.", [[
            {"text": "◀ Tilbake", "callback_data": "mrg|||0"}]])
        return

    parts = [dp_merge.summarize(order_id) for order_id in orders]
    lines = [f"<b>Slå sammen {' + '.join(orders)}</b>\n"]
    for part in parts:
        lines.append(f"<b>{part['order_id']}</b> · {part['book_slug']} · "
                     f"{esc(part['child_name'])}")
        if part["pdf"]:
            lines.append(f"   {os.path.basename(part['pdf'])} — "
                         f"{part['size'] / 1e6:.1f} MB, bygget {part['built_at']}")
        for note in part["notes"]:
            lines.append(f"   ⚠️ {note}")
        lines.append("")
    ship = parts[0]["shipping"]
    lines.append(f"📦 {ship.get('first_name', '')} {ship.get('last_name', '')}, "
                 f"{ship.get('address_1', '')}, {ship.get('postcode', '')} "
                 f"{ship.get('city', '')}")

    problems = dp_merge.check(parts)
    if problems:
        lines.append("\n❌ <b>Kan ikke slås sammen:</b>")
        for problem in problems:
            lines.append(f"   {problem}")
        send(chat_id, "\n".join(lines), [[
            {"text": "◀ Tilbake", "callback_data": "mrg|||0"},
        ]])
        return

    drafts = [d for part in parts for d in part["drafts"]]
    lines.append(f"\nUtkast som erstattes: {', '.join(drafts) if drafts else 'ingen'}")
    lines.append(f"{len(parts)} bøker i ett utkast, én forsendelse.")
    lines.append(f"Samlet utkast får ordrenummer <b>{orders[0]}</b>.")
    if any(part["notes"] for part in parts):
        lines.append("\n⚠️ <i>Advarslene over betyr at en PDF kanskje ikke er "
                     "den nyeste. Bygg den om først hvis du er i tvil.</i>")

    send(chat_id, "\n".join(lines), [
        [{"text": f"🔗 Slå sammen {len(orders)} nå",
          "callback_data": f"mrg!|{orders[0]}||{','.join(orders)}"}],
        [{"text": "◀ Velg på nytt",
          "callback_data": f"mrgT|{orders[0]}||{','.join(orders)}"}],
    ])


def job_merge(order_id: str, chat_id, extra: dict) -> None:
    # "second" er formatet fra den gamle to-ordre-menyen; knapper som ligger
    # igjen i eldre meldinger skal fortsatt virke.
    others = merge_selection(extra.get("others") or extra.get("second") or "")
    orders = merge_selection(",".join([str(order_id)] + others))
    send(chat_id, f"🔗 Slår sammen <b>{'</b>, <b>'.join(orders)}</b>.\n"
                  f"Alle {len(orders)} PDF-ene lastes opp på nytt — dette tar "
                  "et par minutter.")

    parts = [dp_merge.summarize(oid) for oid in orders]
    steps: list[str] = []

    def say(line: str) -> None:
        steps.append(line)
        log(f"[merge {'+'.join(orders)}] {line}")

    result = dp_merge.merge(parts, say=say)

    lines = [f"✅ <b>{' + '.join(orders)}</b> slått sammen.",
             f"Utkast: <code>{result['draft_id']}</code> — "
             f"{result['items']} bøker, én forsendelse."]
    for part in parts:
        lines.append(f"   • {part['order_id']} {esc(part['child_name'])} "
                     f"({part['book_slug']}) — bygget {part['built_at']}")
    if result["deleted"]:
        lines.append(f"\nSlettet gamle utkast: {', '.join(result['deleted'])}")
    lines.append("\nUtkastet går ikke til trykk før du bekrefter det i Gelato.")
    send(chat_id, "\n".join(lines))


def job_send_pdf(order_id: str, chat_id, extra: dict) -> None:
    """Send en ferdig PDF - som dokument, eller som Drive-lenke om den er stor."""
    info = dp_order.resolve(order_id)
    files = order_pdfs(info)
    try:
        key, label, path, size = files[int(extra["pdf"])]
    except (ValueError, IndexError, KeyError):
        send(chat_id, "Fant ikke den PDF-en lenger — bygget kan ha skiftet den ut.")
        return

    name = os.path.basename(path)
    if size <= TELEGRAM_DOC_LIMIT:
        send(chat_id, f"📤 Sender <code>{name}</code> ({size / 1e6:.1f} MB) …")
        result = api("sendDocument",
                     {"chat_id": chat_id, "parse_mode": "HTML",
                      "caption": f"<b>Ordre {order_id}</b> · {label}"},
                     files={"document": path}, timeout=900)
        if not result.get("ok"):
            send(chat_id, f"❌ Telegram tok ikke imot fila: "
                          f"{esc(result.get('description'))}\nPrøver Drive i stedet …")
        else:
            return

    send(chat_id, f"📤 <code>{name}</code> er {size / 1e6:.1f} MB — for stor for "
                  "Telegram. Laster opp til Drive, det tar et minutt eller to …")
    parent = info["config"].get("driveFolderId")
    if not parent:
        send(chat_id, f"❌ {info['book_slug']} mangler <code>driveFolderId</code> "
                      "i config.json — kan ikke laste opp.")
        return

    # Uten --replace: en fil med samme navn kan være den et Gelato-utkast
    # peker på, og den skal ikke i papirkurven bare fordi du ba om en kopi.
    proc = reprint_order.run(
        [sys.executable, reprint_order.DRIVE_UPLOAD, "--file", path,
         "--parent", parent, "--folder", order_id, "--public"],
        f"Drive: {name}")
    start = proc.stdout.rfind("{")
    data = json.loads(proc.stdout[start:]) if start != -1 else {}
    link = data.get("webViewLink") or data.get("downloadUrl")
    if not link:
        send(chat_id, "❌ Opplastingen ga ingen lenke tilbake.")
        return
    send(chat_id, f"✅ <b>Ordre {order_id}</b> · {label}\n"
                  f"<code>{name}</code> ({size / 1e6:.1f} MB)\n\n"
                  f'<a href="{link}">Åpne i Drive</a>\n{link}\n\n'
                  "<i>Lenken er åpen for alle som har den — klar til å sendes videre.</i>")


def show_variants(order_id: str, chat_id, page_key: str, paths: list[str]) -> None:
    shown = paths[-9:]                     # Telegram tar maks 10 i et album
    first = len(paths) - len(shown)
    previews = [preview(path) for path in shown]

    # Den gamle siden først, som eget bilde: du kan ikke vurdere en variant
    # uten å se hva den skal erstatte. Eget bilde og ikke i albumet, slik at
    # nummereringen under fortsatt peker rett på variantene.
    try:
        info = dp_order.resolve(order_id)
        old = current_page_image(info, page_key)
        if old:
            api("sendPhoto", {"chat_id": chat_id, "parse_mode": "HTML",
                              "caption": f"<b>{page_label(page_key)}</b> — slik "
                                         f"den er i boka nå"},
                files={"photo": preview(old, name_hint=f"{order_id}-na")},
                timeout=120)
    except Exception as error:                 # referansebildet er en bonus,
        log(f"[vis] gammel {page_key}: {error}")   # ikke verdt å stoppe valget

    caption = (f"<b>Ordre {order_id} — {page_key}</b>\n"
               f"{len(shown)} varianter. Velg en, eller be om flere.")
    send_album(chat_id, previews, caption)

    numbers = [{"text": f"{first + index + 1}",
                "callback_data": f"pick|{order_id}|{page_key}|{first + index}"}
               for index in range(len(shown))]
    rows = [numbers[i:i + 5] for i in range(0, len(numbers), 5)]
    rows.append([
        {"text": "🔁 3 til", "callback_data": f"more|{order_id}|{page_key}|3"},
        {"text": "⏭ Behold gammel", "callback_data": f"skip|{order_id}|{page_key}|0"},
    ])
    send(chat_id, "Velg variant:", rows)


def show_auto_result(order_id: str, chat_id) -> None:
    """Alle de nye sidene i ett drag, etter en auto-kjøring.

    I auto-modus har du ikke sett en eneste side underveis - du får dem her,
    samlet, slik at du kan peke ut de få som ble dårlige i stedet for å
    godkjenne femten stykker én etter én.
    """
    with STATE_LOCK:
        session = load_state(order_id)
        if not session or session.get("auto_shown"):
            # Lager du om en enkelt side etterpå, havner du hit igjen. Femten
            # forhåndsvisninger til hjelper ingen; du har nettopp sett siden.
            return
        session["auto_shown"] = True
        save_state(session)
    items = [(key, page["chosen"]) for key, page in session["pages"].items()
             if page.get("chosen") and page["status"] in ("approved", "uploaded")]
    if not items:
        return
    for start in range(0, len(items), 10):    # Telegram tar maks 10 i et album
        chunk = items[start:start + 10]
        try:
            previews = [preview(path, name_hint=f"{order_id}-auto")
                        for _, path in chunk]
        except Exception as error:
            log(f"[auto] forhåndsvisning {order_id}: {error}")
            return
        send_album(chat_id, previews,
                   f"<b>Ordre {order_id}</b> — nye sider",
                   captions=[f"<b>{page_label(key)}</b>" for key, _ in chunk])

    # En knapp per side: ble en av dem dårlig, lager du bare den om - uten å
    # starte økten på nytt og miste de fjorten som ble bra.
    buttons = [{"text": ("forside" if key == "page00" else key.replace("page", "")),
                "callback_data": f"more|{order_id}|{key}|3"} for key, _ in items]
    rows = [buttons[i:i + 4] for i in range(0, len(buttons), 4)]
    send(chat_id, "🔁 Ble en side dårlig? Trykk på den, så lager "
                  "boten tre nye varianter å velge mellom.", rows)


def offer_build(order_id: str, chat_id) -> None:
    with STATE_LOCK:
        session = load_state(order_id)
    if not session:
        return
    lines = [f"<b>Ordre {order_id}</b> — alle sider avklart:"]
    for page_key, page in session["pages"].items():
        mark = {"approved": "✅", "skipped": "⏭", "uploaded": "📎"}.get(page["status"], "•")
        lines.append(f"  {mark} {page_key} ({page['status']})")
    lines.append("\nBygg PDF på nytt? Ingenting lastes opp enda.")
    send(chat_id, "\n".join(lines), [[
        {"text": "🔨 Bygg PDF", "callback_data": f"build|{order_id}||0"},
        {"text": "✖ Avbryt", "callback_data": f"cancel|{order_id}||0"},
    ]])


def ask_build(chat_id, order_id: str) -> None:
    """Manuelle endringer i input/ skal aldri forsvinne uten at du sa ja.

    prepare_order kopierer hele base/ over input/ og legger comfy-sidene
    oppå. Har du redigert en side for hånd, er den borte - og du oppdager
    det først når den gamle siden står i den ferdige boka.
    """
    info = dp_order.resolve(order_id)
    edits = reprint_order.manual_edits(info)
    if not edits:
        enqueue("build", order_id, chat_id)
        return

    if not os.path.isdir(info["comfy_dir"]):
        # Ordren er satt sammen for hånd - det finnes ingen comfy-mappe å
        # bygge fra. prepare_order ville bare krasjet, så det er ikke et
        # valg å tilby.
        send(chat_id, f"📁 <b>Ordre {order_id}</b> har ingen comfy-mappe — "
                      f"<code>input/</code> er eneste kilde. Bygger med dine "
                      f"{len(edits)} filer slik de ligger.")
        enqueue("build", order_id, chat_id, skip_prepare=True)
        return

    shown = "\n".join(f"  • {name}" for name in edits[:10])
    if len(edits) > 10:
        shown += f"\n  • … og {len(edits) - 10} til"
    send(chat_id,
         f"⚠️ <b>Ordre {order_id}</b> har {len(edits)} fil(er) i "
         f"<code>input/</code> som ikke kommer fra forrige kjøring:\n\n"
         f"{shown}\n\n"
         "Bygger jeg helt på nytt, blir disse overskrevet av base- og "
         "comfy-bildene. Hva vil du?", [
             [{"text": "✅ Behold mine bilder",
               "callback_data": f"bld!|{order_id}||keep"}],
             [{"text": "♻️ Bygg fra comfy (overskriv mine)",
               "callback_data": f"bld!|{order_id}||fresh"}],
             [{"text": "◀ Avbryt", "callback_data": f"ord|{order_id}||0"}],
         ])


def job_build(order_id: str, chat_id, extra: dict) -> None:
    with STATE_LOCK:
        session = load_state(order_id)
    info = dp_order.resolve(order_id)
    skip_prepare = bool(extra.get("skip_prepare"))

    # Ingen sperre her. Aa bygge en PDF paa disk kan ikke lage et duplikat hos
    # Gelato - det er publiseringen som kan det, og den sperren staar i
    # job_publish. Vi sier bare fra hva veien videre er.
    group = dp_merge.merged_group(order_id)
    if group:
        others = [o for o in group if str(o) != str(order_id)]
        send(chat_id,
             f"🔗 <b>{order_id}</b> ligger i et samlet Gelato-utkast sammen med "
             f"<b>{', '.join(others)}</b>. Bygget under er trygt — men naar du "
             "er ferdig maa du <b>slaa sammen paa nytt</b>, ikke lage et utkast "
             "for denne ordren alene.")

    send(chat_id, f"🔨 Bygger <b>{order_id}</b> ({info['book_slug']}) på nytt. "
                  + ("Beholder <code>input/</code> som den er.\n"
                     if skip_prepare else "")
                  + "Dette tar noen minutter.")

    if session:
        missing = []
        for page_key, page in session["pages"].items():
            chosen = page.get("chosen")
            if page["status"] in ("approved", "uploaded") and chosen:
                reprint_order.commit_variant(info, page_key, chosen)
                if skip_prepare:
                    # Uten prepare er det ingen som kopierer comfy/ -> input/.
                    # Da må den godkjente varianten inn i input/ selv, ellers
                    # bygges boka med den gamle siden.
                    if not reprint_order.commit_variant_to_input(
                            info, page_key, chosen):
                        missing.append(page_key)
        if missing:
            send(chat_id, "⚠️ Fant ikke hvilken input-fil disse hører til: "
                          f"<b>{', '.join(missing)}</b>. De ligger i comfy/, "
                          "men kommer ikke med i denne PDF-en.")

    reprint_order.backup(info)
    files = reprint_order.rebuild_pdfs(info, skip_prepare=skip_prepare)

    size = os.path.getsize(files["gelato"]) / 1e6
    text = (f"✅ <b>{order_id}</b> bygget.\n"
            f"Innersider: {files['inner_pages']}  |  Gelato-PDF: "
            f"{files['total_pages']} sider, {size:.1f} MB\n\n"
            + ("Slå sammen på nytt for å oppdatere det samlede utkastet?"
               if group else "Last opp til Drive og lag Gelato-utkast?"))
    if session:
        session["stage"] = "built"
        session["files"] = files
        with STATE_LOCK:
            save_state(session)
    # For en sammenslaatt ordre ville «Drive + Gelato-utkast» gaatt rett i
    # sperren i job_publish. Tilby re-merge i stedet - dp_merge laster alltid
    # opp PDF-en fra disk, saa det nettopp bygde blir med.
    publish_row = [
        {"text": "📤 Drive + Gelato-utkast", "callback_data": f"publish|{order_id}||1"},
        {"text": "📤 Bare Drive", "callback_data": f"publish|{order_id}||0"},
    ]
    if group:
        # Andre felt speiler menu_merge: den FORSTE ordren i lista, som blir
        # orderReferenceId. Behold gruppas egen rekkefolge, ellers bytter
        # re-mergen primaerordre og det samlede utkastet skifter referanse.
        publish_row = [{"text": "🔗 Slå sammen på nytt",
                        "callback_data": "mrgB|" + str(group[0]) + "||"
                                         + ",".join(str(o) for o in group)}]
    send(chat_id, text, [publish_row, [
        {"text": "📄 Hent PDF", "callback_data": f"pdf|{order_id}||0"},
    ], [
        {"text": "✖ Ferdig uten opplasting", "callback_data": f"cancel|{order_id}||0"},
    ]])


def job_publish(order_id: str, chat_id, extra: dict) -> None:
    make_draft = bool(extra.get("gelato"))
    info = dp_order.resolve(order_id)

    # En testbok skal aldri ut av maskinen. Adressen er oppdiktet, så et
    # Gelato-utkast herfra ville i verste fall blitt trykt og sendt.
    if dp_testbook.is_test(order_id):
        send(chat_id, f"🧪 <b>{order_id}</b> er en testbok — den lastes ikke opp "
                      "til Drive og får ikke Gelato-utkast.\n"
                      "Bruk «📄 Hent PDF» for å få fila.", [[
            {"text": "📄 Hent PDF", "callback_data": f"pdf|{order_id}||0"}]])
        return

    reprint_order.merge_guard(order_id)

    # Er denne ordren den PRIMÆRE i et samlet utkast, ville et nytt enkelt-
    # utkast her slette det samlede og etterlate kunden med én bok for lite.
    # Å bygge på nytt er greit; det er publiseringen som er farlig.
    combined = dp_merge.merged_primary(order_id) if make_draft else None
    if combined and not extra.get("force"):
        others = [o for o in combined.get("merged_orders", []) if str(o) != str(order_id)]
        send(chat_id,
             f"⛔ <b>{order_id}</b> ligger i et samlet utkast "
             f"(<code>{combined.get('draft_id')}</code>) sammen med "
             f"<b>{', '.join(others)}</b>.\n\n"
             "Lager jeg et utkast for denne ordren alene, slettes det samlede "
             "og kunden får én bok for lite. Slå dem sammen på nytt i stedet — "
             "da blir alle bøkene med, i nyeste versjon.", [
                 # Alle de andre skal med, ikke bare den første: et samlet
                 # utkast kan inneholde tre bøker like gjerne som to.
                 [{"text": "🔗 Slå sammen på nytt",
                   "callback_data": "mrgB|" + str(order_id) + "||"
                                    + ",".join([str(order_id)] + [str(o) for o in others])}]
                 if others else [],
                 [{"text": "📤 Bare Drive (ingen utkast)",
                   "callback_data": f"publish|{order_id}||0"}],
             ])
        return

    with STATE_LOCK:
        session = load_state(order_id)
    files = (session or {}).get("files")
    if not files:
        child = info["child_name"]
        pdf_dir = info["pdf_dir"]
        files = {"cover": os.path.join(pdf_dir, f"{child}_cover.pdf"),
                 "inner": os.path.join(pdf_dir, f"{child}_innersider.pdf"),
                 "gelato": os.path.join(pdf_dir, f"{child}_gelato.pdf")}
    for key in ("cover", "inner", "gelato"):
        if not os.path.isfile(files[key]):
            raise SystemExit(f"mangler {files[key]} - bygg PDF først")

    send(chat_id, f"📤 Laster opp <b>{order_id}</b> til Drive"
                  + (" og lager Gelato-utkast …" if make_draft else " …"))
    result = reprint_order.upload_and_draft(info, files, make_draft=make_draft)

    lines = [f"✅ <b>{order_id}</b> lastet opp."]
    link = (result["drive"].get("gelato") or {}).get("webViewLink")
    if link:
        lines.append(f'<a href="{link}">Gelato-PDF i Drive</a>')
    if make_draft:
        lines.append(f"Gelato-utkast: <code>{result.get('draft_id')}</code>")
        lines.append("Utkastet går ikke til trykk før det bekreftes i Gelato.")
    else:
        lines.append("Ingen Gelato-utkast opprettet.")
    send(chat_id, "\n".join(lines))
    drop_state(order_id)


# --------------------------------------------------------------------------
# «Fortsett eventyret» — siste innerside med neste bok sin forside
#
# Siden er et oppsalg og den eneste sida i boka som viser en ANNEN bok. Den
# ble bygget av workeren og var deretter usynlig herfra: du kunne se at den
# var feil først når den lå i den ferdige PDF-en. Nå kan den ses og byttes.
# --------------------------------------------------------------------------
def next_state_path(order_id: str) -> str:
    return os.path.join(NEXT_STATE_DIR, f"{order_id}.json")


def load_next_state(order_id: str) -> dict:
    try:
        with open(next_state_path(order_id), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"order_id": order_id, "variants": []}


def save_next_state(state: dict) -> None:
    os.makedirs(NEXT_STATE_DIR, exist_ok=True)
    state["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
    with open(next_state_path(state["order_id"]), "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)


def next_cover_status(info: dict) -> tuple[str, str | None]:
    """(tekstlinje, sti til beste bilde av neste bok) for meny og melding."""
    cover, mockup = reprint_order.next_cover_paths(info)
    raw = sorted(glob.glob(os.path.join(info["comfy_dir"], "page99_next*.png")))
    if os.path.isfile(mockup):
        return "✅ mockup klar", mockup
    if os.path.isfile(cover):
        return "⚠️ flat forside, ingen mockup", cover
    if raw:
        return "⚠️ bare rå render — siden er ikke bygget", raw[-1]
    # Nøyaktig tilstanden som ga trykte bøker med QR, men uten bilde.
    return "❌ ingen forside — siden bygges uten bilde", None


def next_face_image(info: dict) -> str:
    """Barnebildet fortsett-forsiden rendres med.

    Et bilde sendt med /nyttbilde ligger i oekta og skal slaa ut ordrens
    opprinnelige - ellers ville "lag 3 nye forsider" rett etter en opplasting
    stille brukt det gamle ansiktet.
    """
    with STATE_LOCK:
        session = load_state(info["order_id"])
    return (session or {}).get("face_image") or info["face_image"]


def menu_next(chat_id, order_id: str, message_id=None) -> None:
    info = dp_order.resolve(order_id)
    if not info["continue_code"]:
        send(chat_id, f"Ordre <b>{order_id}</b> har ingen fortsett-kode, "
                      "så boka har ingen slik side.")
        return
    payload = info["payload"]
    state, _ = next_cover_status(info)
    lines = [
        f"<b>Ordre {order_id} — fortsett-siden</b>",
        f"Neste bok: <b>{esc(info['next_book_title'] or info['next_book_slug'] or '?')}</b>",
        f"QR: <code>{info['continue_code']}</code> · "
        f"rabatt <code>{esc(payload.get('continue_coupon') or '-')}</code>",
        f"Barnebilde: <code>{esc(next_face_image(info))}</code>",
        f"\nForside: {state}",
    ]
    rows = [
        [{"text": "👁 Se siden", "callback_data": f"nxv|{order_id}||0"}],
        [{"text": "🔁 Lag 3 nye forsider", "callback_data": f"nxr|{order_id}||3"}],
        [{"text": "🔨 Bygg siden på nytt", "callback_data": f"nxb|{order_id}||0"}],
        [{"text": "◀ Tilbake", "callback_data": f"ord|{order_id}||0"}],
    ]
    text = "\n".join(lines)
    if message_id:
        api("editMessageText", {"chat_id": chat_id, "message_id": message_id,
                                "text": text, "parse_mode": "HTML",
                                "reply_markup": {"inline_keyboard": rows}})
    else:
        send(chat_id, text, rows)


def job_next_view(order_id: str, chat_id, extra: dict) -> None:
    """Vis siden slik den står i boka nå, og forsiden den er bygget av."""
    info = dp_order.resolve(order_id)
    state, art = next_cover_status(info)
    last_page = os.path.join(info["order_path"], "input", "blank-back.png")

    if art:
        api("sendPhoto", {"chat_id": chat_id, "parse_mode": "HTML",
                          "caption": f"<b>Neste bok</b> — {state}"},
            files={"photo": preview(art, name_hint=f"{order_id}-neste")},
            timeout=120)
    if os.path.isfile(last_page):
        api("sendPhoto", {"chat_id": chat_id, "parse_mode": "HTML",
                          "caption": f"<b>Siste innerside</b> slik den bygges nå"},
            files={"photo": preview(last_page, name_hint=f"{order_id}-siste")},
            timeout=120)
    else:
        send(chat_id, "Fant ingen <code>input/blank-back.png</code> — "
                      "siden er ikke bygget for denne ordren.")

    send(chat_id, "Bytt forsiden på siden?", [[
        {"text": "🔁 Lag 3 nye forsider", "callback_data": f"nxr|{order_id}||3"},
        {"text": "◀ Tilbake", "callback_data": f"nxt|{order_id}||0"},
    ]])


def job_next_render(order_id: str, chat_id, extra: dict) -> None:
    """Render nye forsider av neste bok, med DENNE ordrens barnebilde."""
    info = dp_order.resolve(order_id)
    if not info["continue_code"]:
        send(chat_id, f"Ordre <b>{order_id}</b> har ingen fortsett-kode.")
        return
    count = int(extra.get("count") or 3)
    face = next_face_image(info)

    slug = str(info.get("next_book_slug") or "")
    head = (f"🔮 <b>Ordre {order_id}</b> · fortsett-siden\n"
            f"forsiden til <b>{esc(slug or '?')}</b>\n"
            f"barnebilde <code>{esc(face)}</code>")
    status = send(chat_id, head + "\n\n▱▱▱ starter …")
    message_id = (status.get("result") or {}).get("message_id")
    started = time.time()

    def progress(index: int, of: int) -> None:
        if not message_id:
            return
        elapsed = int(time.time() - started)
        note = ""
        if index:
            eta = int(elapsed / index * (of - index))
            note = f" · ~{eta // 60}m {eta % 60}s igjen"
        api("editMessageText", {
            "chat_id": chat_id, "message_id": message_id, "parse_mode": "HTML",
            "text": head + f"\n\n{'▰' * index}{'▱' * (of - index)}  "
                           f"variant {index + 1} av {of}{note}"}, timeout=15)

    try:
        paths = render_next_cover.render(
            info, count=count, face_image=face,
            on_progress=progress, should_cancel=CANCEL.is_set)
    except regen_page.Cancelled:
        if message_id:
            api("editMessageText", {"chat_id": chat_id, "message_id": message_id,
                                    "parse_mode": "HTML",
                                    "text": head + "\n\n🛑 avbrutt"}, timeout=15)
        return
    except (ValueError, FileNotFoundError) as error:
        send(chat_id, f"❌ {esc(error)}")
        return

    state = load_next_state(order_id)
    state["variants"] = (state.get("variants") or []) + paths
    save_next_state(state)

    if message_id:
        api("editMessageText", {
            "chat_id": chat_id, "message_id": message_id, "parse_mode": "HTML",
            "text": head + f"\n\n{'▰' * count}  ferdig — sender bildene …"},
            timeout=15)

    show_next_variants(order_id, chat_id, state["variants"])


def show_next_variants(order_id: str, chat_id, paths: list[str]) -> None:
    shown = paths[-9:]                     # Telegram tar maks 10 i et album
    first = len(paths) - len(shown)
    send_album(chat_id, [preview(p, name_hint=f"{order_id}-nx") for p in shown],
               f"<b>Ordre {order_id}</b> — forsider til neste bok.\n"
               f"Velg en, så bygges fortsett-siden om med den.")
    numbers = [{"text": f"{first + index + 1}",
                "callback_data": f"nxp|{order_id}||{first + index}"}
               for index in range(len(shown))]
    rows = [numbers[i:i + 5] for i in range(0, len(numbers), 5)]
    rows.append([
        {"text": "🔁 3 til", "callback_data": f"nxr|{order_id}||3"},
        {"text": "⏭ Behold den gamle", "callback_data": f"nxt|{order_id}||0"},
    ])
    send(chat_id, "Velg forside:", rows)


def job_next_apply(order_id: str, chat_id, extra: dict) -> None:
    """Ta i bruk en valgt forside (eller bygg siden om med den som ligger der).

    Bygger hele kjeden på nytt gjennom reprint_order, altså nøyaktig samme
    kode som workeren og reprint bruker - en side bygget herfra skal ikke
    kunne se annerledes ut enn en bygget der.
    """
    info = dp_order.resolve(order_id)
    if not info["continue_code"]:
        send(chat_id, f"Ordre <b>{order_id}</b> har ingen fortsett-kode.")
        return

    index = extra.get("index")
    if index is not None:
        variants = load_next_state(order_id).get("variants") or []
        if not 0 <= index < len(variants):
            send(chat_id, "Fant ikke den varianten lenger — lag nye.")
            return
        render_next_cover.commit(info, variants[index])
        send(chat_id, f"🔮 <b>{order_id}</b>: forside {index + 1} valgt. "
                      "Bygger fortsett-siden på nytt …")
    else:
        send(chat_id, f"🔨 <b>{order_id}</b>: bygger fortsett-siden på nytt …")

    result = reprint_order.build_continue_page(info)

    if not result["has_cover"]:
        send(chat_id, "⚠️ Siden ble bygget <b>uten</b> bilde av neste bok — "
                      "det finnes ingen render å bygge den av. "
                      "Trykk «Lag 3 nye forsider» først.")

    last_page = result["last_page"]
    if os.path.isfile(last_page):
        api("sendPhoto", {"chat_id": chat_id, "parse_mode": "HTML",
                          "caption": f"<b>{order_id}</b> — ny fortsett-side"},
            files={"photo": preview(last_page, name_hint=f"{order_id}-siste")},
            timeout=120)

    # Siden ligger i input/. PDF-ene er fortsatt de gamle til tekst-scriptet
    # har kjørt, og det er verdt å si rett ut - ellers laster du opp en PDF
    # som ikke har den siden du nettopp godkjente.
    send(chat_id, "Siden er lagret i <code>input/</code>. "
                  "PDF-ene er fortsatt de gamle til du bygger dem om.", [[
        {"text": "🔨 Bygg PDF på nytt", "callback_data": f"build|{order_id}||0"},
    ], [
        {"text": "◀ Tilbake til ordren", "callback_data": f"ord|{order_id}||0"},
    ]])


# --------------------------------------------------------------------------
# Menyer — alt skal kunne gjøres med knapper, uten å huske syntaks
# --------------------------------------------------------------------------
BOOKS_DIR = r"C:\ComfyUI\books"


def recent_orders(limit: int = 8) -> list[tuple[str, str]]:
    """(ordre-id, bok-slug) sortert på når ordremappa sist ble rørt."""
    found = []
    for slug in os.listdir(BOOKS_DIR):
        orders = os.path.join(BOOKS_DIR, slug, "orders")
        if not os.path.isdir(orders):
            continue
        for order_id in os.listdir(orders):
            path = os.path.join(orders, order_id)
            if os.path.isdir(path):
                found.append((os.path.getmtime(path), order_id, slug))
    found.sort(reverse=True)
    return [(order_id, slug) for _, order_id, slug in found[:limit]]


def menu_main(chat_id, message_id=None) -> None:
    rows = [[{"text": f"{order_id} · {slug}",
              "callback_data": f"ord|{order_id}||0"}]
            for order_id, slug in recent_orders()]
    rows.append([{"text": "🔗 Slå sammen ordre", "callback_data": "mrg|||0"},
                 {"text": "🧪 Test en bok", "callback_data": "tst|||0"}])
    rows.append([{"text": "🔄 Oppdater", "callback_data": "menu|||0"},
                 {"text": "🛑 Stopp arbeid", "callback_data": "stop|||0"}])
    busy = JOBS.qsize()
    text = ("<b>DreamPage</b>\nVelg ordre — nyeste øverst.\n"
            + (f"⏳ {busy} jobb(er) i kø.\n" if busy else "")
            + "\n<i>Er ordren eldre, skriv nummeret rett i chatten.</i>")
    if message_id:
        api("editMessageText", {"chat_id": chat_id, "message_id": message_id,
                                "text": text, "parse_mode": "HTML",
                                "reply_markup": {"inline_keyboard": rows}})
    else:
        send(chat_id, text, rows)


def menu_order(chat_id, order_id: str, message_id=None) -> None:
    # Første oppslag av en ordre som ikke er cachet tar noen sekunder (skann
    # av n8n-databasen). Uten et livstegn ser boten ut som den har hengt seg.
    if not dp_order.read_cache(order_id):
        send(chat_id, f"⏳ Henter ordre <b>{order_id}</b> …")
        message_id = None
    info = dp_order.resolve(order_id)
    session = load_state(order_id)
    lines = [f"<b>Ordre {order_id}</b>",
             f"{info['config'].get('displayName', info['book_slug'])} · "
             f"{esc(info['child_name'])} · {info['cover_type']}"]
    if info["continue_code"]:
        lines.append(f"QR-kode: <code>{info['continue_code']}</code>")
    if session:
        done = sum(1 for p in session["pages"].values()
                   if p["status"] in ("approved", "skipped", "uploaded"))
        lines.append(f"\n⏳ Pågående økt: {done}/{len(session['pages'])} sider")
        # Uten denne linja er en økt som venter på ETT sidevalg helt taus: du
        # ser bare at «Bygg PDF»-tilbudet aldri kommer, uten noen måte å finne
        # ut hvorfor. Ordre 1417 sto slik i over en time 05.09.2026.
        stalled = pending_page(session)
        if stalled:
            lines.append(f"⏸ Venter på at du velger <b>{page_label(stalled)}</b>")

    variants = dp_order.available_body_variants(info["config"])
    current = dp_order.body_variant(info)
    if len(variants) > 1:
        covered = dp_order.variant_pages(info["config"], current)
        total = len(info["config"].get("pages", []))
        note = (f" · {len(covered)}/{total} sider"
                if current != dp_order.DEFAULT_BODY_VARIANT else "")
        lines.append(f"\n🧍 Kropp: <b>{body_label(current)}</b>{note}")

    hair_variants = dp_order.available_hair_variants(info["config"], current)
    hair_now = dp_order.hair_variant(info)
    if len(hair_variants) > 1:
        covered = dp_order.hair_variant_pages(info["config"], hair_now, current)
        total = len(info["config"].get("pages", []))
        note = (f" · {len(covered)}/{total} sider"
                if hair_now != dp_order.DEFAULT_HAIR_VARIANT else "")
        lines.append(f"\n💇 Hår: <b>{hair_label(hair_now)}</b>{note}")

    # Hudvarianten er den TREDJE aksen, og den leses etter de to andre fordi
    # filnavnet bygges i samme rekkefoelge: kropp, haar, hud.
    skin_variants = dp_order.available_skin_variants(info["config"], current, hair_now)
    skin_now = dp_order.skin_variant(info)
    if len(skin_variants) > 1:
        covered = dp_order.skin_variant_pages(info["config"], skin_now,
                                              current, hair_now)
        total = len(info["config"].get("pages", []))
        note = (f" · {len(covered)}/{total} sider"
                if skin_now != dp_order.DEFAULT_SKIN_VARIANT else "")
        lines.append(f"\n🧑🏾 Hud: <b>{skin_label(skin_now)}</b>{note}")

    stalled = pending_page(session) if session else None
    rows = [
        [{"text": "👁 Se sidene", "callback_data": f"view|{order_id}||0"}],
        [{"text": "🖼 Bytt sider", "callback_data": f"pgs|{order_id}||0"}],
        [{"text": "📷 Nytt barnebilde", "callback_data": f"face|{order_id}||0"}],
        [{"text": "🔁 Kjør hele boka på nytt",
          "callback_data": f"rerun|{order_id}||0"}],
        [{"text": "🔨 Bygg PDF på nytt", "callback_data": f"build|{order_id}||0"}],
        [{"text": "📄 Hent PDF", "callback_data": f"pdf|{order_id}||0"}],
        [{"text": "✏️ Endre barnets navn", "callback_data": f"nam|{order_id}||0"}],
        [{"text": "📤 Last opp / Gelato", "callback_data": f"pub?|{order_id}||0"}],
        [{"text": "◀ Tilbake", "callback_data": "menu|||0"}],
    ]
    if stalled:
        rows.insert(0, [{"text": f"⏸ Vis {page_label(stalled)} igjen",
                         "callback_data": f"again|{order_id}|{stalled}|0"}])
    if info["continue_code"]:
        # Indeksen er talt fra rows-lista over; legger du til en knapp foer
        # "Bygg PDF", maa den telles opp her ogsaa.
        rows.insert(5, [{"text": "🔮 Fortsett-siden",
                         "callback_data": f"nxt|{order_id}||0"}])
    if len(variants) > 1:
        rows.insert(-1, [{"text": ("● " if name == current else "○ ")
                                  + body_label(name),
                          "callback_data": f"body|{order_id}|{name}|0"}
                         for name in variants])
    if len(hair_variants) > 1:
        rows.insert(-1, [{"text": ("● " if name == hair_now else "○ ")
                                  + hair_label(name),
                          "callback_data": f"hair|{order_id}|{name}|0"}
                         for name in hair_variants])
    if len(skin_variants) > 1:
        rows.insert(-1, [{"text": ("● " if name == skin_now else "○ ")
                                  + skin_label(name),
                          "callback_data": f"hud|{order_id}|{name}|0"}
                         for name in skin_variants])
    if session:
        rows.insert(-1, [{"text": "✖ Forkast økt",
                          "callback_data": f"cancel|{order_id}||0"}])
    text = "\n".join(lines)
    if message_id:
        api("editMessageText", {"chat_id": chat_id, "message_id": message_id,
                                "text": text, "parse_mode": "HTML",
                                "reply_markup": {"inline_keyboard": rows}})
    else:
        send(chat_id, text, rows)


def menu_pages(chat_id, order_id: str, message_id=None) -> None:
    """Sidevelger: trykk sidene av og på, start når du er ferdig."""
    info = dp_order.resolve(order_id)
    with STATE_LOCK:
        session = load_state(order_id)
        if not session or session.get("stage") != "picking":
            # face_image må overleve: kommer du hit rett etter å ha sendt et
            # nytt barnebilde, er det nettopp DET bildet sidene skal rendres
            # med. Nullstilte vi det her, ville "velg sider selv" stille gitt
            # deg det gamle ansiktet tilbake.
            previous = session or {}
            session = {"order_id": order_id, "chat_id": chat_id,
                       "stage": "picking",
                       "face_image": previous.get("face_image"),
                       "variants": int(previous.get("variants")
                                       or config().get("variants", 3)),
                       "created_at": dt.datetime.now().isoformat(timespec="seconds"),
                       # Sidene fra en økt som allerede er startet skal
                       # ikke forsvinne fordi du tok en tur innom velgeren:
                       # de er nettopp de sidene du holder på med.
                       "picked": list(previous.get("picked")
                                      or (previous.get("pages") or {})),
                       "pages": {}}
            save_state(session)
        picked = set(session.get("picked") or [])
        face = session.get("face_image")

    buttons = []
    for page in info["config"].get("pages", []):
        key = page["page_key"]
        label = "forside" if key == "page00" else key.replace("page", "")
        buttons.append({"text": ("✅ " if key in picked else "") + label,
                        "callback_data": f"tog|{order_id}|{key}|0"})
    rows = [buttons[i:i + 4] for i in range(0, len(buttons), 4)]
    # Se før du velger - ellers merker du sider i blinde.
    rows.append([{"text": (f"👁 Se de {len(picked)} merkede" if picked
                           else "👁 Se alle sidene"),
                  "callback_data": f"view|{order_id}||{'picked' if picked else '0'}"}])
    rows.append([
        {"text": f"🚀 Start automatisk ({len(picked)})",
         "callback_data": f"go|{order_id}||auto"}])
    rows.append([
        {"text": f"▶️ Start, velg per side ({len(picked)})",
         "callback_data": f"go|{order_id}||0"},
        {"text": "◀ Tilbake", "callback_data": f"ord|{order_id}||0"},
    ])
    text = (f"<b>Ordre {order_id}</b> — velg sidene som skal lages på nytt.\n"
            f"Trykk for å merke, trykk igjen for å fjerne.")
    if face:
        text += (f"\n\n📷 Bruker det nye barnebildet "
                 f"<code>{face}</code> på sidene du merker.")
    if message_id:
        api("editMessageText", {"chat_id": chat_id, "message_id": message_id,
                                "text": text, "parse_mode": "HTML",
                                "reply_markup": {"inline_keyboard": rows}})
    else:
        send(chat_id, text, rows)


# --------------------------------------------------------------------------
# Kommandoer
# --------------------------------------------------------------------------
HELP = """<b>DreamPage-bot</b>

Send <code>/meny</code> — eller bare et ordrenummer — så styrer du alt med knapper.

Kommandoene finnes fortsatt som snarveier:

<code>/vis 1235</code> — se sidene slik de er i boka nå
<code>/vis 1235 3,7 forside</code> — se bare disse sidene
<code>/fix 1235 3,7 forside</code> — render nye varianter av sidene
<code>/nyttbilde 1235</code> — send nytt barnebilde, velg så hele boka eller enkeltsider
   «🚀 Hele boka automatisk» kjører alle sidene i ett strekk uten å spørre
   underveis — du får sidene samlet til slutt og kan lage om de dårlige.
<code>/bygg 1235</code> — bygg PDF på nytt uten å endre sider

Har du redigert bilder i <code>input/</code> for hånd, oppdager boten det og
spør før den bygger — <b>Behold mine bilder</b> hopper over prepare, så
ingenting du har laget blir overskrevet.
<code>/pdf 1235</code> — hent ferdige PDF-er (store går via Drive-lenke)
<code>/slaasammen 1281 1282 1283</code> — to eller flere bøker i ett Gelato-utkast
<code>/navn 1281 Lavrans</code> — rett barnets navn (kunder skriver ofte VERSALER)
<code>/test</code> — bygg en testbok fra bilde + navn (ingen Drive/Gelato/n8n)
<code>/status 1235</code> — hvor ordren står
<code>/avbryt 1235</code> — forkast en enkelt økt
<code>/stopp</code> — stopp alt arbeid nå, behold valgene dine
<code>/nullstill</code> — stopp alt og forkast alle økter
<code>/jobber</code> — hva boten jobber med

Sender du et bilde mens en side venter, brukes det bildet i stedet for å
rendre. Send det som <b>fil</b>, ellers komprimerer Telegram det.

Gelato-utkast lages aldri automatisk — alltid bak en knapp."""


def new_session(order_id: str, page_keys: list[str], chat_id,
                face_image: str | None = None, auto: bool = False) -> dict:
    return {
        "order_id": order_id,
        "chat_id": chat_id,
        "stage": "collecting",
        "face_image": face_image,
        # auto: kjør hele lista i ett strekk. Boten godkjenner bildet den
        # lager for hver side selv, i stedet for å stoppe og spørre. Uten
        # dette må du sitte ved telefonen og trykke mellom hver eneste side.
        "auto": bool(auto),
        "variants": int(config().get("variants", 3)),
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "pages": {key: {"status": "pending", "variants": [], "chosen": None}
                  for key in page_keys},
    }


def cmd_fix(chat_id, args: list[str]) -> None:
    if len(args) < 2:
        send(chat_id, "Bruk: <code>/fix 1235 3,7 forside</code>")
        return
    order_id = args[0]
    raw = ",".join(args[1:]).replace(" ", ",")
    page_keys = [dp_order.normalize_page_key(p) for p in raw.split(",") if p.strip()]

    info = dp_order.resolve(order_id)
    known = {p["page_key"] for p in info["config"].get("pages", [])}
    unknown = [p for p in page_keys if p not in known]
    if unknown:
        send(chat_id, f"❌ {info['book_slug']} har ikke {', '.join(unknown)}.\n"
                      f"Sider: {', '.join(sorted(known))}")
        return

    session = new_session(order_id, page_keys, chat_id)
    with STATE_LOCK:
        save_state(session)
    send(chat_id, f"📖 Ordre <b>{order_id}</b> — {info['book_slug']}, "
                  f"{esc(info['child_name'])}\nSider i kø: {', '.join(page_keys)}")
    enqueue("render", order_id, chat_id)


def cmd_nyttbilde(chat_id, args: list[str]) -> None:
    if not args:
        send(chat_id, "Bruk: <code>/nyttbilde 1235</code>, send så bildet.")
        return
    order_id = args[0]
    info = dp_order.resolve(order_id)
    page_keys = [p["page_key"] for p in info["config"].get("pages", [])]

    # Sidelista settes IKKE her. Tidligere låste et nytt barnebilde deg til
    # hele boka, side for side - vil du bare fikse ansiktet på tre sider,
    # måtte du sitte gjennom alle femten. Du velger etter at bildet er inne.
    session = new_session(order_id, [], chat_id)
    session["stage"] = "awaiting_face"
    with STATE_LOCK:
        save_state(session)
    send(chat_id, f"📷 Send nytt barnebilde for ordre <b>{order_id}</b> "
                  f"({esc(info['child_name'])}, {info['book_slug']}).\n\n"
                  f"Etterpå velger du om det skal brukes på <b>hele boka</b> "
                  f"({len(page_keys)} sider) eller bare på sidene du peker ut.\n"
                  "Send bildet som <b>fil</b> for full kvalitet.")


def cmd_vis(chat_id, args: list[str]) -> None:
    """/vis 1235 [3,7 forside] - sidene slik de er i boka nå."""
    if not args:
        send(chat_id, "Bruk: <code>/vis 1235</code> for hele boka, eller "
                      "<code>/vis 1235 3,7 forside</code> for enkeltsider.")
        return
    order_id = args[0]
    raw = ",".join(args[1:]).replace(" ", ",")
    page_keys = [dp_order.normalize_page_key(p) for p in raw.split(",") if p.strip()]

    if page_keys:
        info = dp_order.resolve(order_id)
        known = {p["page_key"] for p in info["config"].get("pages", [])}
        unknown = [k for k in page_keys if k not in known]
        if unknown:
            send(chat_id, f"❌ {info['book_slug']} har ikke {', '.join(unknown)}.\n"
                          f"Sider: {', '.join(sorted(known))}")
            return
        enqueue_view(order_id, chat_id, page_keys=page_keys)
    else:
        enqueue_view(order_id, chat_id)


def cmd_status(chat_id, args: list[str]) -> None:
    if not args:
        sessions = active_sessions()
        if not sessions:
            send(chat_id, "Ingen aktive økter.")
            return
        lines = ["<b>Aktive økter</b>"]
        for session in sessions:
            done = sum(1 for p in session["pages"].values()
                       if p["status"] in ("approved", "skipped", "uploaded"))
            lines.append(f"  {session['order_id']}: {session['stage']}, "
                         f"{done}/{len(session['pages'])} sider")
        send(chat_id, "\n".join(lines))
        return

    order_id = args[0]
    session = load_state(order_id)
    info = dp_order.resolve(order_id)
    lines = [f"<b>Ordre {order_id}</b> — {info['book_slug']}, {esc(info['child_name'])}",
             f"cover: {info['cover_type']}  |  QR-kode: {info['continue_code'] or 'ingen'}"]
    if not session:
        lines.append("\nIngen aktiv økt.")
    else:
        lines.append(f"\nSteg: {session['stage']}")
        for page_key, page in session["pages"].items():
            mark = {"approved": "✅", "skipped": "⏭", "uploaded": "📎",
                    "awaiting": "❓", "rendering": "🎨"}.get(page["status"], "•")
            lines.append(f"  {mark} {page_key} — {page['status']}")
    send(chat_id, "\n".join(lines))


def handle_photo(chat_id, message: dict) -> None:
    """Bilde: enten nytt barnebilde, eller en ferdig side du selv har laget."""
    sessions = [s for s in active_sessions() if s.get("chat_id") == chat_id]
    face_waiting = [s for s in sessions if s.get("stage") == "awaiting_face"]
    page_waiting = [s for s in sessions if pending_page(s)]

    document = message.get("document")
    photos = message.get("photo") or []
    if document:
        file_id = document["file_id"]
        compressed = False
    elif photos:
        file_id = photos[-1]["file_id"]
        compressed = True
    else:
        return

    # Testbok først: den har ingen økt å kjenne igjen på, bare en ventende
    # bestilling i minnet.
    pending = PENDING_TEST.get(chat_id)
    if pending and pending.get("stage") == "bilde":
        PENDING_TEST.pop(chat_id, None)
        path = download_file(file_id, UPLOAD_DIR)
        info = dp_testbook.create(pending["slug"], pending["name"], path)
        body = pending.get("body") or "standard"
        if body != dp_order.DEFAULT_BODY_VARIANT:
            dp_order.set_override(info["order_id"], "body_variant", body)
            info = dp_order.resolve(info["order_id"])
        pages = len(info["config"].get("pages", []))
        covered = dp_order.variant_pages(info["config"], body)
        note = ("\n⚠️ Sendt som bilde, ikke fil — Telegram har komprimert det."
                if compressed else "")
        if body != dp_order.DEFAULT_BODY_VARIANT:
            note += (f"\n🧍 {body_label(body)} — {len(covered)} av {pages} sider "
                     "har denne varianten, resten bruker standardmalen.")
        send(chat_id,
             f"🧪 Testordre <b>{info['order_id']}</b> opprettet.{note}\n"
             f"{info['config'].get('displayName', info['book_slug'])} · "
             f"{esc(info['child_name'])} · {pages} sider\n\n"
             f"Rendrer alle sidene og bygger PDF — regn med ~{pages} minutter. "
             "Du får beskjed underveis.")
        enqueue("testbook", info["order_id"], chat_id)
        return

    if face_waiting:
        session = face_waiting[0]
        order_id = session["order_id"]
        path = download_file(file_id, UPLOAD_DIR)
        dest = os.path.join(r"C:\ComfyUI\input",
                            f"{order_id}-ny{dt.datetime.now().strftime('%m%d%H%M')}.jpg")
        from PIL import Image
        with Image.open(path) as img:
            img.convert("RGB").save(dest, "JPEG", quality=95)
        with STATE_LOCK:
            session = load_state(order_id)
            session["face_image"] = os.path.basename(dest)
            # Ikke "collecting" enda - ingenting rendres før du har sagt
            # HVOR bildet skal brukes.
            session["stage"] = "face_ready"
            save_state(session)
        info = dp_order.resolve(order_id)
        total = len(info["config"].get("pages", []))
        note = ("\n⚠️ Sendt som bilde, ikke fil — Telegram har komprimert det."
                if compressed else "")
        rows = [
            [{"text": f"🚀 Hele boka automatisk ({total} sider)",
              "callback_data": f"fball|{order_id}||auto"}],
            [{"text": "📖 Hele boka, velg variant per side",
              "callback_data": f"fball|{order_id}||0"}],
            [{"text": "🖼 Velg sider selv",
              "callback_data": f"pgs|{order_id}||0"}],
        ]
        # Fortsett-siden er ikke en av bokas sider, saa den faller utenfor
        # baade "hele boka" og sidevelgeren. Uten denne knappen maa du gaa
        # ut av oekta og inn i ordremenyen for aa bruke det nye bildet der.
        if info["continue_code"]:
            rows.append([{"text": "🔮 Bare fortsett-siden (3 forsider)",
                          "callback_data": f"nxr|{order_id}||3"}])
        rows.append([{"text": "✖ Avbryt", "callback_data": f"cancel|{order_id}||0"}])
        send(chat_id,
             f"📷 Nytt barnebilde lagret som <code>{os.path.basename(dest)}</code>.{note}\n\n"
             "Hvor skal det brukes?", rows)
        return

    if page_waiting:
        session = page_waiting[0]
        order_id = session["order_id"]
        page_key = pending_page(session)
        path = download_file(file_id, UPLOAD_DIR)
        with STATE_LOCK:
            session = load_state(order_id)
            session["pages"][page_key]["chosen"] = path
            session["pages"][page_key]["status"] = "uploaded"
            save_state(session)
        note = ("\n⚠️ Sendt som bilde, ikke fil — Telegram har komprimert det. "
                "Send som fil hvis kvaliteten teller." if compressed else "")
        send(chat_id, f"📎 Bruker ditt bilde for <b>{page_key}</b> (ordre {order_id}).{note}")
        advance(order_id, chat_id)
        return

    send(chat_id, "Fikk et bilde, men ingen økt venter på et. "
                  "Start med <code>/fix</code> eller <code>/nyttbilde</code>.")


def advance(order_id: str, chat_id) -> None:
    """Gå videre til neste side, eller tilby bygging."""
    with STATE_LOCK:
        session = load_state(order_id)
    if not session:
        return
    if next_unrendered(session):
        enqueue("render", order_id, chat_id)
    elif not pending_page(session):
        if session.get("auto"):
            show_auto_result(order_id, chat_id)
        offer_build(order_id, chat_id)


def handle_callback(query: dict) -> None:
    # answerCallbackQuery er ALLEREDE sendt fra polling-løkka. Gjøres det her,
    # rekker spørringen å utløpe mens et tregt oppslag pågår, og knappen
    # blir stående og snurre.
    data = query.get("data") or ""
    chat_id = query["message"]["chat"]["id"]

    try:
        action, order_id, page_key, value = data.split("|", 3)
    except ValueError:
        return
    message_id = query["message"]["message_id"]

    if action == "menu":
        menu_main(chat_id, message_id)

    elif action == "stop":
        send(chat_id, "Stoppe alt arbeid nå?", [[
            {"text": "🛑 Stopp", "callback_data": "stop!|||0"},
            {"text": "🧹 Stopp + forkast økter", "callback_data": "reset!|||0"},
        ], [{"text": "◀ Nei, tilbake", "callback_data": "menu|||0"}]])

    elif action == "stop!":
        stop_everything(chat_id, reset=False)

    elif action == "reset!":
        stop_everything(chat_id, reset=True)

    elif action == "ord":
        menu_order(chat_id, order_id, message_id)

    elif action == "again":
        enqueue_view(order_id, chat_id, variants_for=page_key)

    elif action == "body":
        # Kroppsvarianten lagres som en override paa ordren, ikke i oekta:
        # da gjelder den ogsaa naar du senere rendrer en enkeltside uten aa
        # ha startet en ny oekt.
        variant = page_key if page_key in dp_order.BODY_VARIANTS else \
            dp_order.DEFAULT_BODY_VARIANT
        dp_order.set_override(
            order_id, "body_variant",
            None if variant == dp_order.DEFAULT_BODY_VARIANT else variant)
        info = dp_order.resolve(order_id)
        covered = dp_order.variant_pages(info["config"], variant)
        total = len(info["config"].get("pages", []))
        if variant == dp_order.DEFAULT_BODY_VARIANT:
            send(chat_id, f"🧍 Ordre <b>{order_id}</b> bruker nå "
                          f"<b>{body_label(variant)}</b>-malene.")
        else:
            send(chat_id,
                 f"🧍 Ordre <b>{order_id}</b> bruker nå <b>{body_label(variant)}</b>.\n"
                 f"{len(covered)} av {total} sider har denne varianten — "
                 "resten rendres med standardmalen.")
        menu_order(chat_id, order_id, message_id)

    elif action == "hair":
        # Haarvarianten: maler der figuren har kort haar. Er barnet en baby
        # eller har kort haar, kan headswappen ikke fjerne malens lange haar -
        # det ligger utenfor headmasken og blir sydd tilbake uendret (ordre
        # 1423). Lagres som override, som kroppsvarianten.
        variant = page_key if page_key in dp_order.HAIR_VARIANTS else \
            dp_order.DEFAULT_HAIR_VARIANT
        dp_order.set_override(
            order_id, "hair_variant",
            None if variant == dp_order.DEFAULT_HAIR_VARIANT else variant)
        info = dp_order.resolve(order_id)
        body = dp_order.body_variant(info)
        covered = dp_order.hair_variant_pages(info["config"], variant, body)
        total = len(info["config"].get("pages", []))
        if variant == dp_order.DEFAULT_HAIR_VARIANT:
            send(chat_id, f"💇 Ordre <b>{order_id}</b> bruker nå "
                          f"<b>{hair_label(variant)}</b>-malene.")
        else:
            send(chat_id,
                 f"💇 Ordre <b>{order_id}</b> bruker nå <b>{hair_label(variant)}</b>.\n"
                 f"{len(covered)} av {total} sider har denne varianten — "
                 "resten rendres med standardmalen.\n"
                 "Sidene må rendres på nytt for at det skal slå inn.")
        menu_order(chat_id, order_id, message_id)

    elif action == "hud":
        # Hudvarianten: maler der barnets KROPP har moerk hud. Headswappen
        # bytter HODET, saa ansiktet faar barnets egen hudfarge - men hendene
        # ligger utenfor headmasken og blir sydd tilbake uendret. Uten denne
        # malen faar et moerkt barn lyse hender. Lagres som override, som de
        # to andre variantene.
        variant = page_key if page_key in dp_order.SKIN_VARIANTS else \
            dp_order.DEFAULT_SKIN_VARIANT
        dp_order.set_override(
            order_id, "skin_variant",
            None if variant == dp_order.DEFAULT_SKIN_VARIANT else variant)
        info = dp_order.resolve(order_id)
        body = dp_order.body_variant(info)
        hair = dp_order.hair_variant(info)
        covered = dp_order.skin_variant_pages(info["config"], variant, body, hair)
        total = len(info["config"].get("pages", []))
        if variant == dp_order.DEFAULT_SKIN_VARIANT:
            send(chat_id, f"🧑🏾 Ordre <b>{order_id}</b> bruker nå "
                          f"<b>{skin_label(variant)}</b>-malene.")
        else:
            send(chat_id,
                 f"🧑🏾 Ordre <b>{order_id}</b> bruker nå "
                 f"<b>{skin_label(variant)}</b>.\n"
                 f"{len(covered)} av {total} sider har denne varianten — "
                 "resten rendres med standardmalen.\n"
                 "Sidene må rendres på nytt for at det skal slå inn.")
        menu_order(chat_id, order_id, message_id)

    elif action == "pgs":
        menu_pages(chat_id, order_id, message_id)

    elif action == "nxt":
        menu_next(chat_id, order_id, message_id)

    elif action == "nxv":
        enqueue_view(order_id, chat_id, next_cover=True)

    elif action == "nxr":
        # GPU-jobb, altsaa samme koe som sidebyttene - to rendringer samtidig
        # ville sloss om kortet og gjort begge tregere.
        enqueue("nextrender", order_id, chat_id, count=int(value or 3))
        send(chat_id, f"🔮 <b>{order_id}</b> lagt i kø: {value or 3} nye forsider.")

    elif action == "nxp":
        enqueue("nextapply", order_id, chat_id, index=int(value or 0))

    elif action == "nxb":
        enqueue("nextapply", order_id, chat_id)

    elif action == "view":
        if value == "picked":
            with STATE_LOCK:
                session = load_state(order_id)
                picked = list((session or {}).get("picked") or [])
            enqueue_view(order_id, chat_id, page_keys=picked)
        elif page_key:
            enqueue_view(order_id, chat_id, page_key=page_key)
        else:
            enqueue_view(order_id, chat_id)

    elif action == "tog":
        with STATE_LOCK:
            session = load_state(order_id)
            if session and session.get("stage") == "picking":
                picked = session.get("picked") or []
                if page_key in picked:
                    picked.remove(page_key)
                else:
                    picked.append(page_key)
                session["picked"] = picked
                save_state(session)
        menu_pages(chat_id, order_id, message_id)

    elif action == "go":
        with STATE_LOCK:
            session = load_state(order_id)
            picked = list((session or {}).get("picked") or [])
            face = (session or {}).get("face_image")
        if not picked:
            send(chat_id, "Ingen sider valgt.")
            return
        info = dp_order.resolve(order_id)
        order = [p["page_key"] for p in info["config"].get("pages", [])]
        picked.sort(key=lambda k: order.index(k) if k in order else 99)
        auto = value == "auto"
        session = new_session(order_id, picked, chat_id, face_image=face,
                              auto=auto)
        # Få sider tåler tre varianter hver; mange gjør det ikke. 15 sider a
        # tre er 45 rendringer og over en halvtime GPU. Auto velger uansett
        # bare ett bilde per side, så flere varianter ville vært bortkastet.
        session["variants"] = 1 if auto else (3 if len(picked) <= 5 else 1)
        with STATE_LOCK:
            save_state(session)
        send(chat_id, f"📖 Ordre <b>{order_id}</b> — {info['book_slug']}, "
                      f"{esc(info['child_name'])}\n"
                      + (f"📷 Nytt barnebilde: <code>{face}</code>\n" if face else "")
                      + f"Sider i kø: {', '.join(picked)}\n"
                      f"{session['variants']} variant(er) per side "
                      f"(~{len(picked) * session['variants']} min)"
                      + ("\n🚀 Kjører i ett strekk — du blir ikke "
                         "spurt underveis." if auto else ""))
        enqueue("render", order_id, chat_id)

    elif action == "fball":
        info = dp_order.resolve(order_id)
        keys = [p["page_key"] for p in info["config"].get("pages", [])]
        with STATE_LOCK:
            face = (load_state(order_id) or {}).get("face_image")
        auto = value == "auto"
        session = new_session(order_id, keys, chat_id, face_image=face,
                              auto=auto)
        # EN variant per side ved full omkjøring. Tre varianter av 15 sider er
        # 45 rendringer og over en halvtime GPU - og med nytt ansiktsbilde vil
        # man se resultatet, ikke velge mellom tre. Trenger en side flere,
        # finnes "3 til"-knappen på akkurat den siden.
        session["variants"] = 1
        with STATE_LOCK:
            save_state(session)
        send(chat_id, f"📖 Ordre <b>{order_id}</b> — {info['book_slug']}, "
                      f"{esc(info['child_name'])}\n"
                      + (f"📷 Nytt barnebilde: <code>{face}</code>\n" if face else "")
                      + f"Alle {len(keys)} sider, en variant hver (~{len(keys)} min).\n"
                      + ("🚀 Kjører hele boka i ett strekk — du blir "
                         "ikke spurt underveis. Til slutt får du alle sidene "
                         "samlet, og kan lage om de som ble dårlige."
                         if auto else
                         "Er en side dårlig, trykker du «3 til» på den."))
        enqueue("render", order_id, chat_id)

    elif action == "face":
        cmd_nyttbilde(chat_id, [order_id])

    elif action == "rerun":
        # Samme valg som etter et nytt barnebilde, bare uten bildet: "fball"
        # lager oekta og job_render faller tilbake til ordrens eget
        # barnebilde naar oekta ikke har et (`session.get("face_image") or
        # info["face_image"]`). Derfor trengs ingen ny jobb her - knappen er
        # en snarvei inn i en flyt som alt finnes, og det er poenget: to
        # kopier av «kjoer hele boka» ville drevet fra hverandre.
        info = dp_order.resolve(order_id)
        total = len(info["config"].get("pages", []))
        lines = [f"🔁 <b>Ordre {order_id}</b> — "
                 f"{info['config'].get('displayName', info['book_slug'])}, "
                 f"{esc(info['child_name'])}",
                 f"Rendrer alle {total} sidene på nytt med barnebildet som "
                 f"alt ligger på ordren."]

        # Variantene avgjoer HVILKE maler som brukes, saa de hoerer hjemme i
        # denne meldingen: trykker du «kjoer hele boka» rett etter aa ha
        # valgt moerk hud, vil du se at valget faktisk gjelder.
        body = dp_order.body_variant(info)
        hair = dp_order.hair_variant(info)
        skin = dp_order.skin_variant(info)
        chosen = []
        if body != dp_order.DEFAULT_BODY_VARIANT:
            chosen.append(f"🧍 {body_label(body)}")
        if hair != dp_order.DEFAULT_HAIR_VARIANT:
            chosen.append(f"💇 {hair_label(hair)}")
        if skin != dp_order.DEFAULT_SKIN_VARIANT:
            chosen.append(f"🧑🏾 {skin_label(skin)}")
        if chosen:
            lines.append("\n" + " · ".join(chosen))

        # En paagaaende oekt blir ERSTATTET av den nye. Sier vi det ikke her,
        # ser det ut som sidene du alt har godkjent er borte uten grunn.
        session = load_state(order_id)
        if session:
            done = sum(1 for pg in session["pages"].values()
                       if pg["status"] in ("approved", "skipped", "uploaded"))
            lines.append(f"\n⚠️ Du har en pågående økt "
                         f"({done}/{len(session['pages'])} sider). Starter du "
                         "på nytt, erstattes den.")

        send(chat_id, "\n".join(lines), [
            [{"text": f"🚀 Automatisk ({total} sider)",
              "callback_data": f"fball|{order_id}||auto"}],
            [{"text": "📖 Velg variant per side",
              "callback_data": f"fball|{order_id}||0"}],
            [{"text": "◀ Tilbake", "callback_data": f"ord|{order_id}||0"}],
        ])

    elif action == "tst":
        menu_test(chat_id, message_id)

    elif action == "tstb":
        books = dict(dp_testbook.testable_books())
        title = books.get(order_id, order_id)
        config_path = os.path.join(r"C:\ComfyUI\books", order_id, "config.json")
        variants = ["standard"]
        try:
            with open(config_path, encoding="utf-8-sig") as fh:
                variants = dp_order.available_body_variants(json.load(fh))
        except Exception:
            pass
        # Kroppen maa velges FOER navnet: den avgjoer hvilke maler som
        # rendres, og en testbok rendres i ett strekk uten flere stopp.
        if len(variants) > 1:
            PENDING_TEST[chat_id] = {"slug": order_id, "stage": "kropp"}
            send(chat_id, f"🧪 <b>{title}</b>\n\nHvilken kropp skal barnet ha?",
                 [[{"text": body_label(name),
                    "callback_data": f"tstv|{order_id}|{name}|0"}]
                  for name in variants]
                 + [[{"text": "◀ Tilbake", "callback_data": "tst|||0"}]])
        else:
            PENDING_TEST[chat_id] = {"slug": order_id, "stage": "navn",
                                     "body": "standard"}
            send(chat_id, f"🧪 <b>{title}</b>\n\n"
                          "Hva skal barnet hete? Skriv navnet i neste melding.\n"
                          "<i>/avbryttest for å la det være.</i>")

    elif action == "tstv":
        variant = page_key if page_key in dp_order.BODY_VARIANTS else "standard"
        PENDING_TEST[chat_id] = {"slug": order_id, "stage": "navn",
                                 "body": variant}
        books = dict(dp_testbook.testable_books())
        send(chat_id, f"🧪 <b>{books.get(order_id, order_id)}</b> · "
                      f"{body_label(variant)}\n\n"
                      "Hva skal barnet hete? Skriv navnet i neste melding.\n"
                      "<i>/avbryttest for å la det være.</i>")

    elif action == "tstl":
        menu_test_list(chat_id, message_id)

    elif action == "tstd":
        try:
            removed = dp_testbook.delete(order_id)
            send(chat_id, f"🗑 Testbok <b>{order_id}</b> slettet "
                          f"({len(removed)} mappe/fil).")
        except SystemExit as error:
            send(chat_id, f"❌ {esc(error)}")

    elif action == "mrg":
        menu_merge(chat_id, "", message_id)

    elif action in ("mrgT", "mrgA"):
        # mrgA er den gamle «velg første ordre»-knappen; den blir nå bare et
        # første valg i flervalgsmenyen, så gamle meldinger fortsatt virker.
        # Knappen bærer alltid HELE det nye valget - både når en ordre legges
        # til og når den fjernes. Ellers ville et trykk på en allerede valgt
        # ordre bare lagt den inn igjen.
        chosen = merge_selection(value)
        if not chosen and order_id:
            chosen = [order_id]
        menu_merge(chat_id, ",".join(chosen), message_id)

    elif action == "mrgB":
        # value = hele lista (nytt format), page_key = andre ordre (gammelt).
        chosen = merge_selection(value) or merge_selection(f"{order_id},{page_key}")
        confirm_merge(chat_id, chosen)

    elif action == "mrg!":
        chosen = merge_selection(value) or merge_selection(f"{order_id},{page_key}")
        enqueue("merge", chosen[0], chat_id, others=",".join(chosen[1:]))

    elif action == "nam":
        menu_name(chat_id, order_id, message_id)

    elif action == "nam!":
        apply_name(chat_id, order_id,
                   titlecase_name(dp_order.resolve(order_id)["child_name"]))

    elif action == "nam0":
        # Logges fordi det ellers er umulig i ettertid å se om et navn ble
        # tilbakestilt med vilje eller mistet av en feil. Det spørsmålet
        # dukket opp for ordre 1281 og kunne ikke besvares.
        was = dp_order.resolve(order_id)["child_name"]
        dp_order.set_override(order_id, "child_name", None)
        now = dp_order.resolve(order_id)["child_name"]
        log(f"ordre {order_id}: navnet tilbakestilt {was!r} -> {now!r} (fra payload)")
        send(chat_id, f"↩️ <b>{order_id}</b>: bruker kundens opprinnelige navn "
                      f"<b>{esc(now)}</b> igjen.")

    elif action == "namx":
        PENDING_NAME[chat_id] = order_id
        send(chat_id, f"⌨️ Skriv navnet for ordre <b>{order_id}</b> i neste "
                      "melding.\n<i>Send /avbrytnavn for å la det være.</i>")

    elif action == "pdf":
        menu_pdf(chat_id, order_id, message_id)

    elif action == "pdfg":
        enqueue_view(order_id, chat_id, pdf=page_key)

    elif action == "pub?":
        send(chat_id, f"<b>Ordre {order_id}</b> — hva skal lastes opp?\n"
                      "PDF-ene må være bygget først.", [[
            {"text": "📤 Drive + Gelato-utkast", "callback_data": f"publish|{order_id}||1"},
            {"text": "📤 Bare Drive", "callback_data": f"publish|{order_id}||0"},
        ], [{"text": "◀ Tilbake", "callback_data": f"ord|{order_id}||0"}]])

    elif action == "pick":
        with STATE_LOCK:
            session = load_state(order_id)
            if not session:
                send(chat_id, "Økten finnes ikke lenger.")
                return
            page = session["pages"][page_key]
            index = int(value)
            if index >= len(page["variants"]):
                send(chat_id, "Fant ikke den varianten.")
                return
            page["chosen"] = page["variants"][index]
            page["status"] = "approved"
            save_state(session)
        send(chat_id, f"✅ <b>{page_key}</b>: variant {index + 1} valgt.")
        advance(order_id, chat_id)

    elif action == "more":
        with STATE_LOCK:
            session = load_state(order_id)
            if session:
                session["pages"][page_key]["status"] = "pending"
                save_state(session)
        enqueue("render", order_id, chat_id, page_key=page_key,
                count=int(value), choose=True)

    elif action == "skip":
        with STATE_LOCK:
            session = load_state(order_id)
            if session:
                session["pages"][page_key]["status"] = "skipped"
                session["pages"][page_key]["chosen"] = None
                save_state(session)
        send(chat_id, f"⏭ <b>{page_key}</b>: beholder den gamle siden.")
        advance(order_id, chat_id)

    elif action == "build":
        ask_build(chat_id, order_id)

    elif action == "bld!":
        enqueue("build", order_id, chat_id, skip_prepare=(value == "keep"))

    elif action == "publish":
        enqueue("publish", order_id, chat_id, gelato=(value == "1"))

    elif action == "cancel":
        drop_state(order_id)
        send(chat_id, f"✖ Økt for <b>{order_id}</b> forkastet. "
                      "Boka er urort.")


def order_token(text: str) -> str | None:
    """Ordrenummeret i en fritekstmelding, eller None.

    Bestiller noen to boker i samme session far hver bok sin egen job_key
    ("1414-b1", "1414-b2") - det er den som er mappenavn og oppslagsnokkel.
    Et rent isdigit()-filter slapp aldri disse gjennom, sa a skrive "1414-b1"
    i chatten ga hovedmenyen i stedet for ordren.
    """
    words = (text or "").strip().split()[:2]
    if not words:
        return None
    raw = words[0].strip("#").strip().lower()
    # "1414 b1" med mellomrom er like naturlig a skrive som "1414-b1".
    if len(words) > 1 and raw.isdigit():
        rest = words[1].strip().lower()
        if re.fullmatch(r"b\d+", rest):
            raw = f"{raw}-{rest}"
    match = re.fullmatch(r"(\d+)(?:[-_ ]?b(\d+))?", raw)
    if not match:
        return None
    return f"{match[1]}-b{match[2]}" if match[2] else match[1]


def handle_message(message: dict) -> None:
    chat_id = message["chat"]["id"]
    text = (message.get("text") or message.get("caption") or "").strip()

    if message.get("photo") or message.get("document"):
        handle_photo(chat_id, message)
        return

    # Venter vi på et navn, er teksten et navn - også hvis den er et tall
    # ("1281" kunne ellers blitt tolket som at du ville åpne en ordre).
    pending = PENDING_TEST.get(chat_id)
    if pending and pending.get("stage") == "navn" and text and not text.startswith("/"):
        pending["name"] = text.strip()
        pending["stage"] = "bilde"
        send(chat_id, f"📷 Navn: <b>{pending['name']}</b>\n\n"
                      "Send nå bildet av barnet. Send det som <b>fil</b> for "
                      "full kvalitet.")
        return

    if chat_id in PENDING_NAME and text and not text.startswith("/"):
        apply_name(chat_id, PENDING_NAME.pop(chat_id), text)
        return

    if not text.startswith("/"):
        # Bare et ordrenummer holder - da slipper du menyen innom.
        token = order_token(text)
        if token:
            try:
                menu_order(chat_id, token)
            except SystemExit as error:
                send(chat_id, f"❌ {esc(error)}")
        elif text:
            menu_main(chat_id)
        return

    parts = text.split()
    command = parts[0].split("@")[0].lower()
    args = parts[1:]

    try:
        if command in ("/meny", "/menu", "/start"):
            menu_main(chat_id)
        elif command in ("/hjelp", "/help"):
            send(chat_id, HELP)
        elif command == "/fix":
            cmd_fix(chat_id, args)
        elif command in ("/nyttbilde", "/nyttfoto"):
            cmd_nyttbilde(chat_id, args)
        elif command == "/bygg":
            if not args:
                send(chat_id, "Bruk: <code>/bygg 1235</code>")
            else:
                ask_build(chat_id, args[0])
        elif command in ("/vis", "/se"):
            cmd_vis(chat_id, args)
        elif command in ("/slaasammen", "/merge"):
            if len(args) >= 2:
                confirm_merge(chat_id, args)
            elif len(args) == 1:
                menu_merge(chat_id, args[0])
            else:
                menu_merge(chat_id)
        elif command in ("/test", "/testbok"):
            menu_test(chat_id)
        elif command == "/avbryttest":
            PENDING_TEST.pop(chat_id, None)
            send(chat_id, "Greit — testboka er avlyst.")
        elif command == "/navn":
            if len(args) >= 2:
                apply_name(chat_id, args[0], " ".join(args[1:]))
            elif args:
                menu_name(chat_id, args[0])
            else:
                send(chat_id, "Bruk: <code>/navn 1281 Lavrans</code>")
        elif command == "/avbrytnavn":
            PENDING_NAME.pop(chat_id, None)
            send(chat_id, "Greit — navnet står som det er.")
        elif command == "/pdf":
            if not args:
                send(chat_id, "Bruk: <code>/pdf 1235</code>")
            else:
                menu_pdf(chat_id, args[0])
        elif command == "/status":
            cmd_status(chat_id, args)
        elif command == "/avbryt":
            if args:
                drop_state(args[0])
                send(chat_id, f"✖ Økt for <b>{args[0]}</b> forkastet.")
        # Telegram-kommandoer må være ASCII - "/kø" ville aldri blitt levert.
        elif command in ("/jobber", "/koe", "/queue"):
            send(chat_id, f"Jobber i kø: {JOBS.qsize()}")
        elif command in ("/stopp", "/stop"):
            stop_everything(chat_id, reset=False)
        elif command in ("/nullstill", "/reset"):
            stop_everything(chat_id, reset=True)
        elif command == "/chatid":
            send(chat_id, f"chat_id: <code>{chat_id}</code>")
    except SystemExit as error:
        send(chat_id, f"❌ {esc(error)}")
    except Exception as error:
        log(traceback.format_exc())
        send(chat_id, f"❌ {esc(error)}")


# --------------------------------------------------------------------------
def main() -> int:
    conf = config()
    if not conf.get("bot_token"):
        log(f"bot_token mangler i {CONFIG_PATH}")
        return 1
    # Tom mengde = åpen for alle. `allowed_chat_ids: []` alene holder ikke,
    # for en tom liste er falsy og ville falt tilbake på chat_id igjen -
    # derfor et eget, uttrykkelig flagg.
    if conf.get("allow_all"):
        allowed: set = set()
    else:
        raw = conf.get("allowed_chat_ids")
        if raw is None:
            raw = [conf.get("chat_id")]
        allowed = {int(c) for c in raw if c}

    me = api("getMe", {})
    if not me.get("ok"):
        log(f"kunne ikke nå Telegram: {me.get('description')}")
        return 1
    log(f"startet som @{me['result'].get('username')} — tillatte chatter: {allowed or 'alle'}")

    clear_stale_lock()
    threading.Thread(target=worker_loop, daemon=True).start()
    threading.Thread(target=ui_loop, daemon=True).start()
    threading.Thread(target=view_loop, daemon=True).start()
    threading.Thread(target=warm_cache, daemon=True).start()
    threading.Thread(target=recover_sessions, daemon=True).start()
    threading.Thread(target=recover_builds, daemon=True).start()

    offset = 0
    while True:
        try:
            offset = poll_once(offset, allowed)
        except Exception:
            # Arbeidstrådene er daemon: dør DENNE tråden, dør prosessen
            # øyeblikkelig - midt i et bygg, uten at noen får beskjed.
            # Det skjedde 05.09.2026: ordre 1411-b2 mistet Gelato-PDF-en
            # sin fordi hovedløkka forsvant mens tekst-scriptet kjørte.
            # api() svelger nettverksfeil selv, men config() over den gjør
            # det ikke - og en fil som ikke lot seg lese ETT sekund er ikke
            # verdt en død bot.
            log("hovedløkka feilet, prøver igjen om 5 s:\n"
                + traceback.format_exc())
            time.sleep(5)


def poll_once(offset: int, allowed: set) -> int:
    """Én runde med getUpdates. Returnerer ny offset."""
    result = api("getUpdates", {"offset": offset, "timeout": 50,
                                "allowed_updates": ["message", "callback_query"]},
                 timeout=70)
    if not result.get("ok"):
        time.sleep(5)
        return offset
    for update in result.get("result", []):
        offset = update["update_id"] + 1
        try:
            if "callback_query" in update:
                query = update["callback_query"]
                chat_id = query["message"]["chat"]["id"]
                if allowed and chat_id not in allowed:
                    continue
                # Svar med en gang - spørringen utløper etter få sekunder.
                api("answerCallbackQuery", {"callback_query_id": query["id"]},
                    timeout=10)
                UI_JOBS.put(("callback", query))
            elif "message" in update:
                chat_id = update["message"]["chat"]["id"]
                text = (update["message"].get("text") or "")
                # /chatid slipper alltid gjennom - ellers er allowlisten
                # umulig å sette opp: du trenger id-en for å fylle den ut,
                # men blir ignorert til den er fylt ut.
                if allowed and chat_id not in allowed \
                        and not text.startswith("/chatid"):
                    log(f"ignorerte melding fra chat {chat_id}")
                    continue
                UI_JOBS.put(("message", update["message"]))
        except Exception:
            log(traceback.format_exc())
    return offset


if __name__ == "__main__":
    sys.exit(main())

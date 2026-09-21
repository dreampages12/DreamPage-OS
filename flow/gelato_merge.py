# -*- coding: utf-8 -*-
"""Samle flere bestillinger fra samme kunde i ETT Gelato-utkast.

Bakgrunn: en kunde kjoper av og til to boker i to separate WooCommerce-ordre.
I dag blir det to Gelato-utkast, to forsendelser og dobbel frakt. Dette
scriptet oppdager tilfellet, spor deg paa Telegram med to knapper, og lar
n8n legge begge bokene som hvert sitt item i samme Gelato-ordre.

Grunnregelen er fail-soft: en betalt ordre skal ALDRI stoppe fordi
sammenslaaingen feilet. Hver kommando skriver gyldig JSON paa stdout og
avslutter med kode 0 uansett hva som gaar galt. Verste utfall er at ordren
blir et vanlig enkelt-utkast, noyaktig som i dag.

Kommandoer
----------
  gate    Kjores FOR "Create Gelato Draft". Finner kandidat, spor paa
          Telegram, venter (standard 20 min) og svarer med hvilke ekstra
          items n8n skal legge ved. Ingen kandidat = svarer paa under et
          sekund og ingen melding sendes.
  record  Kjores ETTER "Create Gelato Draft". Skriver kvitteringsfila for
          det nye utkastet og sletter partnerutkastet - i den rekkefolgen,
          slik at vi aldri staar uten utkast hvis noe feiler.
  status  Viser aapne utkast scriptet kjenner til.
  demo    Sender en testmelding med knapper, uten aa rore noen ordre.

  python gelato_merge.py gate   --request "<orderPath>/.merge_request.json"
  python gelato_merge.py record --request "<orderPath>/.merge_request.json" --draft-id <id>
  python gelato_merge.py status
  python gelato_merge.py demo
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import string
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# --------------------------------------------------------------------------
# OPPSETT
# --------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
import dp_secrets  # noqa: E402

# Stien til DreamPage-roten utledes, den hardkodes ikke: koden kjoerer paa
# Windows i dag og paa Linux paa nye maskiner. Se flow/paths.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import under  # noqa: E402
STATE_DIR = under("state/gelato_drafts")
CONFIG_PATH = under("config/merge_orders.json")
LOCK_PATH = os.path.join(STATE_DIR, ".merge.lock")
LOG_PATH = under("state/gelato_merge.log")

# Standardverdier. config/merge_orders.json kan overstyre alt sammen, slik at
# du kan skru funksjonen av uten aa rore n8n eller denne fila.
DEFAULTS = {
    "enabled": True,
    "window_hours": 24,          # hvor gammelt et utkast kan vare og fortsatt slaas sammen
    "timeout_seconds": 900,      # 15 minutter, deretter enkelt utkast som vanlig
    "poll_seconds": 3,
    "require_same_address": True,
    "max_items_per_order": 4,
    # Hemmelighetene laa hardkodet her til 2026-09-15. Naa i config/secrets.json,
    # som staar i .gitignore - en API-noekkel i git-historikk maa roteres, ikke
    # slettes. merge_orders.json kan fortsatt overstyre dem per ordre.
    "chat_id": dp_secrets.get("worker_chat_id"),
    "bot_token": dp_secrets.get("worker_bot_token"),
    "gelato_api_key": dp_secrets.get("gelato_api_key"),
}

# Cloudflare svarer 403 "error code: 1010" paa urllib sin standard User-Agent.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

STDOUT_MARKER = "DPMERGE_JSON"


def cfg() -> dict:
    out = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8-sig") as fh:
            out.update(json.load(fh))
    except FileNotFoundError:
        pass
    except Exception as exc:            # noqa: BLE001 - daarlig config skal ikke stoppe en ordre
        log(f"kunne ikke lese {CONFIG_PATH}: {exc}")
    return out


def log(msg: str) -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')}  {msg}"
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:                    # noqa: BLE001
        pass
    print(line, file=sys.stderr)


def emit(payload: dict) -> int:
    """Eneste kanal ut til n8n. Alltid ASCII, alltid en linje, alltid exit 0."""
    print(STDOUT_MARKER + " " + json.dumps(payload, ensure_ascii=True))
    return 0


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(value: str):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:                    # noqa: BLE001
        return None


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def http(method: str, url: str, body=None, headers=None, timeout=60):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    head = {"User-Agent": UA}
    if data is not None:
        head["Content-Type"] = "application/json"
    head.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=head)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except Exception:                # noqa: BLE001
            return exc.code, {"raw": raw}


def gelato(method: str, path: str, body=None, timeout=60):
    return http(method, "https://order.gelatoapis.com/v4" + path, body,
                {"X-API-KEY": cfg()["gelato_api_key"]}, timeout)


def telegram(method: str, body: dict, timeout=40):
    url = f"https://api.telegram.org/bot{cfg()['bot_token']}/{method}"
    return http("POST", url, body, timeout=timeout)


def telegram_get(method: str, params: dict, timeout=40):
    url = (f"https://api.telegram.org/bot{cfg()['bot_token']}/{method}?"
           + urllib.parse.urlencode(params))
    return http("GET", url, timeout=timeout)


# --------------------------------------------------------------------------
# KVITTERINGSFILER (sidecars)
# --------------------------------------------------------------------------
# En fil per ordre i STATE_DIR. Dette er systemets eget minne om hvilke
# utkast som er aapne og hva de inneholder. Vi stoler ikke paa Gelato-soek
# alene, fordi vi trenger den opprinnelige Drive-URL-en til PDF-en: Gelato
# gir bare tilbake en signert S3-lenke som utloper etter et dogn.

def sidecar_path(order_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(order_id))
    return os.path.join(STATE_DIR, f"{safe}.json")


def read_sidecar(order_id: str) -> dict:
    try:
        with open(sidecar_path(order_id), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                    # noqa: BLE001
        return {}


def write_sidecar(data: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    path = sidecar_path(data["order_id"])
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def all_sidecars():
    try:
        names = os.listdir(STATE_DIR)
    except FileNotFoundError:
        return []
    out = []
    for name in names:
        if not name.endswith(".json") or name.startswith("."):
            continue
        try:
            with open(os.path.join(STATE_DIR, name), encoding="utf-8") as fh:
                out.append(json.load(fh))
        except Exception:                # noqa: BLE001
            continue
    return out


def address_key(ship: dict) -> str:
    parts = [ship.get("address_1"), ship.get("address_2"), ship.get("postcode"),
             ship.get("city"), ship.get("country")]
    blob = " ".join(str(p or "") for p in parts).lower()
    blob = re.sub(r"[^\w\s]", " ", blob, flags=re.UNICODE)
    return re.sub(r"\s+", " ", blob).strip()


# --------------------------------------------------------------------------
# LAAS
# --------------------------------------------------------------------------
# Bare en sammenslaaing om gangen. To ordre som blir ferdige samtidig ville
# ellers begge sett den andre som kandidat og laget hver sin merkelige ordre.
# Den som ikke faar laasen gjor ingenting - altsaa vanlig enkelt-utkast.

def acquire_lock(max_age: int) -> bool:
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "at": now_utc().isoformat()}, fh)
        return True
    except FileExistsError:
        pass
    # Foreldrelos laas etter en krasj skal ikke blokkere for alltid.
    try:
        age = time.time() - os.path.getmtime(LOCK_PATH)
        if age > max_age:
            log(f"bryter foreldrelos laas ({int(age)}s gammel)")
            os.remove(LOCK_PATH)
            return acquire_lock(max_age)
    except Exception:                    # noqa: BLE001
        pass
    return False


def release_lock() -> None:
    try:
        os.remove(LOCK_PATH)
    except Exception:                    # noqa: BLE001
        pass


# --------------------------------------------------------------------------
# TELEGRAM-SPORSMAALET
# --------------------------------------------------------------------------

def describe(item: dict) -> str:
    name = item.get("child_name") or "?"
    title = item.get("book_title") or item.get("book_slug") or "?"
    cover = item.get("cover_type") or ""
    return f"#{item.get('order_id')} - {name}, {title} ({cover})"


def ask(req: dict, cand: dict, conf: dict) -> tuple:
    """Sender sporsmaalet og venter. Returnerer (approved|None, note)."""
    token = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8))
    ship = req.get("shipping") or {}
    minutes = max(1, int(conf["timeout_seconds"] // 60))

    lines = [
        "\U0001F4E6 To ordre til samme kunde",
        "",
        f"{ship.get('first_name','')} {ship.get('last_name','')}".strip(),
        f"{ship.get('address_1','')}, {ship.get('postcode','')} {ship.get('city','')} "
        f"{ship.get('country','')}".strip(),
        "",
        "Ny ordre:",
        "  " + describe(req),
    ]
    lines.append("Ventende utkast:")
    for it in cand.get("items", []):
        lines.append("  " + describe(it))
    lines += [
        "",
        "Skal de sendes i EN forsendelse?",
        f"Ingen svar innen {minutes} min = to separate utkast som vanlig.",
    ]

    st, res = telegram("sendMessage", {
        "chat_id": conf["chat_id"],
        "text": "\n".join(lines),
        "disable_web_page_preview": True,
        "reply_markup": {"inline_keyboard": [[
            {"text": "\u2705 Sl\u00e5 sammen", "callback_data": f"dpm:{token}:y"},
            {"text": "\u274C Hver for seg", "callback_data": f"dpm:{token}:n"},
        ]]},
    })
    if st != 200 or not res.get("ok"):
        log(f"telegram sendMessage feilet: {st} {res}")
        return None, "telegram utilgjengelig"

    message_id = res["result"]["message_id"]
    sent_at = int(res["result"].get("date") or time.time())
    deadline = time.time() + conf["timeout_seconds"]
    approved = None
    offset = None
    seen_update = None

    while time.time() < deadline and approved is None:
        time.sleep(conf["poll_seconds"])
        # allowed_updates settes eksplisitt: callback_query er med som standard,
        # men vi vil ikke vaere avhengige av at standarden aldri endres.
        params = {"limit": 100, "timeout": 0,
                  "allowed_updates": json.dumps(["callback_query", "message"])}
        if offset:
            params["offset"] = offset
        st, upd = telegram_get("getUpdates", params)
        if st != 200 or not upd.get("ok"):
            log(f"getUpdates svarte {st}: {str(upd)[:200]}")
            continue
        for u in upd.get("result", []):
            seen_update = u.get("update_id", seen_update)
            cb = u.get("callback_query")
            if cb:
                data = str(cb.get("data", ""))
                if data in (f"dpm:{token}:y", f"dpm:{token}:n"):
                    approved = data.endswith(":y")
                    telegram("answerCallbackQuery", {
                        "callback_query_id": cb["id"],
                        "text": "Slaar sammen" if approved else "Holder dem separat",
                    })
                    log(f"knappetrykk mottatt: {data}")
                    break
                # Utdatert knapp fra en tidligere runde. Svar likevel, ellers
                # blir telefonen staaende og spinne.
                telegram("answerCallbackQuery", {
                    "callback_query_id": cb["id"],
                    "text": "Dette sporsmaalet er utloept",
                })
                log(f"ignorerte knappetrykk med annen token: {data}")
                continue
            # Tekstsvar er en reserveutvei hvis knappene av en eller annen
            # grunn ikke virker paa telefonen.
            msg = u.get("message") or u.get("edited_message")
            if not msg or int(msg.get("date", 0)) < sent_at:
                continue
            if str((msg.get("reply_to_message") or {}).get("message_id")) != str(message_id):
                continue
            text = str(msg.get("text") or "").strip().lower()
            if text in ("ja", "yes", "y", "j"):
                approved = True
                break
            if text in ("nei", "no", "n"):
                approved = False
                break
        if seen_update is not None:
            offset = seen_update + 1

    verdict = ("\u2705 Sl\u00e5s sammen til \u00e9n forsendelse." if approved is True else
               "\u274C Holdes separat." if approved is False else
               f"\u23F1 Ingen svar p\u00e5 {minutes} min - holdes separat.")
    telegram("editMessageText", {
        "chat_id": conf["chat_id"], "message_id": message_id,
        "text": "\n".join(lines + ["", verdict]), "disable_web_page_preview": True,
    })
    return approved, verdict


# --------------------------------------------------------------------------
# GATE
# --------------------------------------------------------------------------

def find_candidate(req: dict, conf: dict):
    email = str((req.get("customer") or {}).get("email") or "").strip().lower()
    if not email:
        return None, "ordren mangler e-post"
    akey = address_key(req.get("shipping") or {})
    cutoff = now_utc().timestamp() - conf["window_hours"] * 3600
    hits = []
    for sc in all_sidecars():
        if str(sc.get("order_id")) == str(req.get("order_id")):
            continue
        if sc.get("status") != "open" or not sc.get("draft_id"):
            continue
        if str(sc.get("email", "")).strip().lower() != email:
            continue
        if conf["require_same_address"] and sc.get("address_key") != akey:
            continue
        created = parse_iso(sc.get("created_at", ""))
        if not created or created.timestamp() < cutoff:
            continue
        if len(sc.get("items", [])) >= conf["max_items_per_order"]:
            continue
        hits.append(sc)
    if not hits:
        return None, "ingen kandidat"
    hits.sort(key=lambda s: s.get("created_at", ""), reverse=True)
    return hits[0], ""


def cmd_gate(args) -> int:
    conf = cfg()
    decision = {"merge": False, "extraItems": [], "partner": None, "reason": ""}

    def finish(reason: str, dump=True):
        decision["reason"] = reason
        if dump:
            try:
                with open(args.request + ".decision", "w", encoding="utf-8") as fh:
                    json.dump(decision, fh, ensure_ascii=False, indent=1)
            except Exception as exc:     # noqa: BLE001
                log(f"kunne ikke skrive beslutningsfil: {exc}")
        log(f"gate ordre {decision.get('order_id','?')}: {reason}")
        return emit(decision)

    try:
        with open(args.request, encoding="utf-8") as fh:
            req = json.load(fh)
    except Exception as exc:             # noqa: BLE001
        return finish(f"kunne ikke lese forespoerselsfila: {exc}", dump=False)

    decision["order_id"] = req.get("order_id")

    if not conf["enabled"]:
        return finish("sammenslaaing er slaatt av i config")
    if args.no_ask:
        return finish("--no-ask")

    cand, why = find_candidate(req, conf)
    if not cand:
        return finish(why)

    # Kandidaten kan ha gaatt i produksjon siden sist. Da roerer vi den ikke.
    st, live = gelato("GET", f"/orders/{cand['draft_id']}")
    if st != 200:
        cand["status"] = "unknown"
        write_sidecar(cand)
        return finish(f"kunne ikke sjekke kandidatutkast (HTTP {st})")
    if live.get("orderType") != "draft" or live.get("fulfillmentStatus") != "draft":
        cand["status"] = "closed"
        write_sidecar(cand)
        return finish(f"kandidat #{cand['order_id']} er ikke lenger utkast "
                      f"({live.get('fulfillmentStatus')})")

    if args.dry_run:
        return finish(f"toerrkjoering - ville spurt om #{cand['order_id']}")

    if not acquire_lock(conf["timeout_seconds"] + 120):
        return finish("en annen sammenslaaing paagaar")
    try:
        approved, note = ask(req, cand, conf)
    except Exception as exc:             # noqa: BLE001
        log("ask() feilet:\n" + traceback.format_exc())
        approved, note = None, f"feil under sporsmaal: {exc}"
    finally:
        release_lock()

    if approved is not True:
        return finish(note)

    decision["merge"] = True
    decision["extraItems"] = [{
        "itemReferenceId": it["itemReferenceId"],
        "productUid": it["productUid"],
        "pageCount": it.get("pageCount", 30),
        "files": [{"type": "default", "url": it["file_url"]}],
        "quantity": 1,
    } for it in cand.get("items", [])]
    decision["partner"] = {
        "order_id": cand["order_id"],
        "draft_id": cand["draft_id"],
        "items": cand.get("items", []),
    }
    return finish(f"slaas sammen med #{cand['order_id']}")


# --------------------------------------------------------------------------
# RECORD
# --------------------------------------------------------------------------

def cmd_record(args) -> int:
    conf = cfg()
    out = {"ok": False, "draft_id": args.draft_id, "deleted": [], "warnings": []}
    try:
        with open(args.request, encoding="utf-8") as fh:
            req = json.load(fh)
    except Exception as exc:             # noqa: BLE001
        out["warnings"].append(f"kunne ikke lese forespoerselsfila: {exc}")
        return emit(out)

    try:
        with open(args.request + ".decision", encoding="utf-8") as fh:
            decision = json.load(fh)
    except Exception:                    # noqa: BLE001
        decision = {"merge": False}

    own_item = {
        "order_id": str(req.get("order_id")),
        "itemReferenceId": f"item-{req.get('order_id')}",
        "productUid": req.get("product_uid"),
        "pageCount": 30,
        "file_url": req.get("file_url"),
        "book_slug": req.get("book_slug"),
        "book_title": req.get("book_title"),
        "child_name": req.get("child_name"),
        "cover_type": req.get("cover_type"),
    }
    items = [own_item]
    merged_orders = [str(req.get("order_id"))]
    partner = decision.get("partner") if decision.get("merge") else None
    if partner:
        items += partner.get("items", [])
        merged_orders += [str(i.get("order_id")) for i in partner.get("items", [])]

    if not args.draft_id:
        out["warnings"].append("mangler draft-id, skriver ingen kvittering")
        return emit(out)

    write_sidecar({
        "order_id": str(req.get("order_id")),
        "draft_id": args.draft_id,
        "status": "open",
        "email": str((req.get("customer") or {}).get("email") or "").strip().lower(),
        "address_key": address_key(req.get("shipping") or {}),
        "created_at": now_utc().isoformat(),
        "book_slug": req.get("book_slug"),
        "child_name": req.get("child_name"),
        "book_title": req.get("book_title"),
        "cover_type": req.get("cover_type"),
        "merged_orders": merged_orders,
        "items": items,
    })
    out["ok"] = True
    out["merged_orders"] = merged_orders

    # Sletting skjer FORST naa - det nye utkastet finnes allerede, saa selv om
    # dette feiler staar vi igjen med for mye, aldri for lite.
    if partner:
        pid = partner["draft_id"]
        st, live = gelato("GET", f"/orders/{pid}")
        if st == 200 and live.get("orderType") == "draft" and live.get("fulfillmentStatus") == "draft":
            st_del, _ = gelato("DELETE", f"/orders/{pid}")
            if st_del in (200, 204):
                out["deleted"].append(pid)
            else:
                out["warnings"].append(f"kunne ikke slette gammelt utkast {pid} (HTTP {st_del})")
        else:
            out["warnings"].append(f"gammelt utkast {pid} var ikke lenger utkast - roerte det ikke")

        old = read_sidecar(partner["order_id"]) or {"order_id": str(partner["order_id"])}
        old["status"] = "merged"
        old["merged_into_order"] = str(req.get("order_id"))
        old["merged_into_draft"] = args.draft_id
        old["merged_at"] = now_utc().isoformat()
        write_sidecar(old)

        lines = [
            "\U0001F517 Sl\u00e5tt sammen",
            "",
            f"Ordre {', '.join('#' + o for o in merged_orders)} ligger n\u00e5 i ett Gelato-utkast:",
            f"https://dashboard.gelato.com/orders/{args.draft_id}",
        ]
        if out["deleted"]:
            lines.append(f"Gammelt utkast {partner['draft_id']} er slettet.")
        for w in out["warnings"]:
            lines.append("\u26A0 " + w)
        try:
            telegram("sendMessage", {"chat_id": conf["chat_id"], "text": "\n".join(lines),
                                     "disable_web_page_preview": True})
        except Exception as exc:         # noqa: BLE001
            log(f"kunne ikke varsle om sammenslaaing: {exc}")

    for w in out["warnings"]:
        log("record: " + w)
    return emit(out)


# --------------------------------------------------------------------------
# STATUS / DEMO
# --------------------------------------------------------------------------

def cmd_status(args) -> int:
    rows = sorted(all_sidecars(), key=lambda s: s.get("created_at", ""), reverse=True)
    if not rows:
        print("ingen kvitteringer i " + STATE_DIR)
        return 0
    for sc in rows:
        books = ", ".join(f"#{i.get('order_id')} {i.get('child_name')}" for i in sc.get("items", []))
        print(f"  {str(sc.get('order_id')):6s} {str(sc.get('status')):7s} "
              f"{sc.get('draft_id')}  {sc.get('created_at','')[:19]}  {books}")
        if sc.get("merged_into_draft"):
            print(f"         -> slaatt sammen inn i ordre #{sc['merged_into_order']}")
    return 0


def cmd_demo(args) -> int:
    conf = dict(cfg())
    conf["timeout_seconds"] = args.timeout
    req = {"order_id": "TEST", "child_name": "Testbarn", "book_title": "Demo",
           "cover_type": "hardcover",
           "customer": {"email": "demo@dreampage.store"},
           "shipping": {"first_name": "Demo", "last_name": "Kunde",
                        "address_1": "Losveien 23", "postcode": "3150",
                        "city": "Tolvsrod", "country": "NO"}}
    cand = {"order_id": "TEST2", "items": [
        {"order_id": "TEST2", "child_name": "Testbarn 2", "book_title": "Demo 2",
         "cover_type": "hardcover"}]}
    if not acquire_lock(conf["timeout_seconds"] + 120):
        print("laasen er opptatt - en ekte sammenslaaing paagaar")
        return 0
    try:
        approved, note = ask(req, cand, conf)
    finally:
        release_lock()
    print(f"svar: {approved!r} - {note}")
    return 0


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gate")
    g.add_argument("--request", required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--no-ask", action="store_true",
                   help="hopp over sporsmaalet helt (nodbrems)")
    g.set_defaults(func=cmd_gate)

    r = sub.add_parser("record")
    r.add_argument("--request", required=True)
    r.add_argument("--draft-id", default="")
    r.set_defaults(func=cmd_record)

    s = sub.add_parser("status")
    s.set_defaults(func=cmd_status)

    d = sub.add_parser("demo")
    d.add_argument("--timeout", type=int, default=120)
    d.set_defaults(func=cmd_demo)

    args = ap.parse_args()
    try:
        return args.func(args)
    except Exception as exc:             # noqa: BLE001
        # Siste skanse. En betalt ordre skal aldri stoppe her.
        log("uventet feil:\n" + traceback.format_exc())
        if args.cmd in ("gate", "record"):
            return emit({"merge": False, "extraItems": [], "partner": None,
                         "ok": False, "reason": f"uventet feil: {exc}"})
        print("FEIL:", exc, file=sys.stderr)
        return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:                    # noqa: BLE001
        pass
    sys.exit(main())

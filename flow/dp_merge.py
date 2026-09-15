# -*- coding: utf-8 -*-
"""Sla sammen to (eller flere) ordre til ETT Gelato-utkast.

Erstatter den automatiske gaten i n8n (se patch_worker_merge_off.py). Der
lette workeren etter kandidater ved hver eneste betalte ordre og spurte i
gruppa; her skjer det bare naar DU ber om det, fra Telegram-boten.

To ting er annerledes enn i finish_merged_order.py:

1. Vi leser IKKE ordredetaljene ut av et eksisterende Gelato-utkast. Alt
   kommer fra n8n-payloaden (dp_order.resolve), som ogsaa finnes for ordre
   som aldri fikk et utkast.
2. Vi krever IKKE at den lokale PDF-en er identisk med den som ligger i
   utkastet - vi krever det motsatte: PDF-en paa disk er fasiten og lastes
   opp paa nytt. Har du bygget en ordre om igjen i boten, er det den nye
   boka som skal trykkes.

  python dp_merge.py --order 1281 --order 1282 --dry-run
  python dp_merge.py --order 1281 --order 1282 --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

import dp_order                                                    # noqa: E402
import reprint_order                                               # noqa: E402
from finish_order import PRODUCT_UID, gelato                       # noqa: E402

DRAFT_STATE_DIR = reprint_order.DRAFT_STATE_DIR
SESSION_DIR = r"C:\ComfyUI\state\reprint"


# --------------------------------------------------------------------------
# Hvilken PDF, og er den fersk?
# --------------------------------------------------------------------------
def gelato_pdf(info: dict) -> str | None:
    """Nyeste *_gelato.pdf i ordrens pdf-mappe."""
    hits = glob.glob(os.path.join(info["pdf_dir"], "*_gelato.pdf"))
    if not hits:
        return None
    return max(hits, key=os.path.getmtime)


def fmt_time(stamp: float) -> str:
    return dt.datetime.fromtimestamp(stamp).strftime("%d.%m %H:%M")


def staleness(info: dict, pdf: str | None) -> list[str]:
    """Grunner til at PDF-en kanskje ikke er den nyeste versjonen.

    Hele poenget med aa sla sammen fra boten er at en ordre kan ha blitt
    bygget om etter at den forste ble trykkeklar. Da skal den NYE boka med -
    saa vi sier fra hvis noe tyder paa at PDF-en henger etter.
    """
    notes = []
    if not pdf:
        return ["ingen ferdig _gelato.pdf - ordren maa bygges forst"]

    built = os.path.getmtime(pdf)
    newest, newest_name = 0.0, ""
    for name, path in reprint_order._input_files(info):
        stamp = os.path.getmtime(path)
        if stamp > newest:
            newest, newest_name = stamp, name
    if newest > built + 1:
        notes.append("input/" + newest_name + " er nyere enn PDF-en ("
                     + fmt_time(newest) + " mot " + fmt_time(built)
                     + ") - bygg paa nytt forst")

    session = os.path.join(SESSION_DIR, info["order_id"] + ".json")
    if os.path.isfile(session):
        try:
            with open(session, encoding="utf-8") as fh:
                state = json.load(fh)
        except (OSError, json.JSONDecodeError):
            state = {}
        waiting = [key for key, page in (state.get("pages") or {}).items()
                   if page.get("status") in ("approved", "uploaded")]
        if waiting and state.get("stage") != "built":
            notes.append("paagaaende okt: " + str(len(waiting)) + " valgt side(r) ("
                         + ", ".join(sorted(waiting)) + ") er ikke bygget inn enda")
    return notes


def address_key(ship: dict) -> str:
    return " ".join(str(ship.get(key) or "").strip().lower() for key in
                    ("first_name", "last_name", "address_1", "postcode", "city", "country"))


def summarize(order_id: str) -> dict:
    """Alt boten trenger for aa vise en ordre i sammenslaaings-menyen."""
    info = dp_order.resolve(order_id)
    pdf = gelato_pdf(info)
    return {
        "order_id": info["order_id"],
        "info": info,
        "book_slug": info["book_slug"],
        "child_name": info["child_name"],
        "cover_type": info["cover_type"],
        "pdf": pdf,
        "size": os.path.getsize(pdf) if pdf else 0,
        "built_at": fmt_time(os.path.getmtime(pdf)) if pdf else "",
        "shipping": info["payload"].get("shipping") or {},
        "address_key": address_key(info["payload"].get("shipping") or {}),
        "notes": staleness(info, pdf),
        "drafts": reprint_order.known_draft_ids(order_id),
    }


# --------------------------------------------------------------------------
def check(parts: list[dict]) -> list[str]:
    """Blokkerende problemer. Tom liste = klar til aa sla sammen."""
    problems = []
    if len(parts) < 2:
        problems.append("trenger minst to ordre")
    for part in parts:
        if not part["pdf"]:
            problems.append("ordre " + part["order_id"] + " mangler ferdig _gelato.pdf")
    keys = {part["address_key"] for part in parts}
    if len(keys) > 1:
        problems.append("mottakerne er ikke like - de kan ikke sendes i samme "
                        "forsendelse:\n" + "\n".join(
                            "  " + p["order_id"] + ": " + p["address_key"] for p in parts))
    ids = [part["order_id"] for part in parts]
    if len(set(ids)) != len(ids):
        problems.append("samme ordre er valgt to ganger")
    return problems


def write_receipt(order_id: str, data: dict) -> None:
    os.makedirs(DRAFT_STATE_DIR, exist_ok=True)
    path = os.path.join(DRAFT_STATE_DIR, order_id + ".json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def merge(parts: list[dict], say=print) -> dict:
    """Last opp PDF-ene paa nytt, lag ETT utkast, rydd bort de gamle.

    Rekkefolgen er ikke valgfri: det nye utkastet opprettes FOR de gamle
    slettes, saa vi aldri staar uten utkast hvis noe feiler underveis.
    """
    problems = check(parts)
    if problems:
        raise SystemExit("\n".join(problems))

    primary = parts[0]
    order_id = primary["order_id"]

    # 1) Alltid ny opplasting. Den gamle Drive-lenken kan peke paa en PDF fra
    #    for du bygget ordren om - da ville feil bok blitt trykket.
    for part in parts:
        info = part["info"]
        parent = info["config"].get("driveFolderId")
        if not parent:
            raise SystemExit(info["book_slug"] + " mangler driveFolderId i config.json")
        say("laster opp " + os.path.basename(part["pdf"]) + " ("
            + format(part["size"] / 1e6, ".1f") + " MB, bygget "
            + part["built_at"] + ") ...")
        proc = reprint_order.run(
            [sys.executable, reprint_order.DRIVE_UPLOAD, "--file", part["pdf"],
             "--parent", parent, "--folder", part["order_id"], "--public"],
            "Drive: " + os.path.basename(part["pdf"]))
        start = proc.stdout.rfind("{")
        up = json.loads(proc.stdout[start:]) if start != -1 else {}
        part["file_url"] = (up.get("downloadUrl")
                            or "https://drive.google.com/uc?id=" + up["id"]
                            + "&export=download")
        part["drive_id"] = up.get("id")

    # 2) Ett utkast, ett item per bok. Aldri quantity 2 - det ville trykt
    #    samme bok to ganger i stedet for to forskjellige boker.
    payload = primary["info"]["payload"]
    ship = payload["shipping"]
    cust = payload["customer"]
    body = {
        "orderType": "draft",
        "orderReferenceId": str(order_id),
        "customerReferenceId": cust.get("email") or "customer-" + str(order_id),
        "currency": "NOK",
        "shippingAddress": {
            "firstName": ship["first_name"], "lastName": ship["last_name"],
            "addressLine1": ship["address_1"], "addressLine2": ship.get("address_2") or "",
            "city": ship["city"], "postCode": ship["postcode"], "country": ship["country"],
            "email": cust.get("email"),
            "phone": ship.get("phone") or cust.get("phone") or "",
        },
        "items": [{
            "itemReferenceId": part["order_id"] + "-" + part["book_slug"],
            "productUid": PRODUCT_UID[part["cover_type"]],
            "pageCount": 30,          # produkt-variant-ID, ikke faktisk sidetall
            "files": [{"type": "default", "url": part["file_url"]}],
            "quantity": 1,
        } for part in parts],
    }

    old = []
    for part in parts:
        old.extend(part["drafts"])
    old = list(dict.fromkeys(old))
    say("eksisterende utkast: " + (", ".join(old) if old else "ingen"))

    status, res = gelato("POST", "https://order.gelatoapis.com/v4/orders", body)
    draft_id = res.get("id")
    if not draft_id:
        raise SystemExit("Gelato svarte HTTP " + str(status) + " uten utkast-id: "
                         + json.dumps(res)[:500])
    say("nytt samlet utkast (HTTP " + str(status) + "): " + str(draft_id))

    # 3) Forst NAA rydder vi bort de gamle.
    deleted = []
    for old_id in old:
        if str(old_id) == str(draft_id):
            continue
        try:
            code, _ = gelato("DELETE",
                             "https://order.gelatoapis.com/v4/orders/" + str(old_id))
            deleted.append(old_id)
            say("slettet gammelt utkast " + str(old_id) + " (HTTP " + str(code) + ")")
        except Exception as error:                            # noqa: BLE001
            say("kunne ikke slette " + str(old_id) + ": " + str(error))

    # 4) Kvitteringer. Den primaere far hele lista; de andre peker hit, slik
    #    at reprint_order.merge_guard nekter aa lage duplikat ved siden av.
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    write_receipt(order_id, {
        "order_id": str(order_id),
        "draft_id": draft_id,
        "status": "open",
        "email": (cust.get("email") or "").strip().lower(),
        "created_at": now,
        "merged_orders": [part["order_id"] for part in parts],
        "items": [{"order_id": part["order_id"],
                   "itemReferenceId": part["order_id"] + "-" + part["book_slug"],
                   "productUid": PRODUCT_UID[part["cover_type"]],
                   "pageCount": 30,
                   "file_url": part["file_url"],
                   "book_slug": part["book_slug"],
                   "child_name": part["child_name"],
                   "cover_type": part["cover_type"],
                   "pdf": part["pdf"],
                   "pdf_size": part["size"]} for part in parts],
        "source": "dp_merge.py",
    })
    for part in parts[1:]:
        write_receipt(part["order_id"], {
            "order_id": part["order_id"],
            "status": "merged",
            "merged_into_order": str(order_id),
            "merged_into_draft": draft_id,
            "merged_at": now,
            "source": "dp_merge.py",
        })

    return {"draft_id": draft_id, "deleted": deleted, "items": len(parts),
            "orders": [part["order_id"] for part in parts]}


def merged_group(order_id: str) -> list[str]:
    """Alle ordrene i det samlede utkastet denne ordren tilhorer, ellers [].

    Virker fra begge sider: den PRIMAERE eier kvitteringen med `merged_orders`,
    mens en SEKUNDAER bare har `merged_into_order` og maa slaa opp videre.
    Rekkefolgen bevares - den forste blir orderReferenceId ved en re-merge.
    """
    data = _receipt(order_id)
    if data and data.get("status") == "merged":
        data = _receipt(data.get("merged_into_order"))
    orders = [str(o) for o in ((data or {}).get("merged_orders") or [])]
    return orders if len(orders) > 1 else []


def _receipt(order_id) -> dict | None:
    if not order_id:
        return None
    path = os.path.join(DRAFT_STATE_DIR, str(order_id) + ".json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def merged_primary(order_id: str) -> dict | None:
    """Kvitteringen hvis denne ordren ER det samlede utkastet (>1 bok).

    Publiserer du en slik ordre alene, lages et utkast med BARE den ene boka
    og det samlede slettes - kunden faar en bok for lite.
    """
    path = os.path.join(DRAFT_STATE_DIR, str(order_id) + ".json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("status") != "merged" and len(data.get("merged_orders") or []) > 1:
        return data
    return None


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", action="append", required=True,
                    help="gjenta per ordre; den FORSTE blir orderReferenceId")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    parts = [summarize(order_id) for order_id in args.order]
    for part in parts:
        print("#" + part["order_id"].ljust(8) + " " + part["child_name"].ljust(12)
              + " " + part["book_slug"].ljust(26)
              + " " + format(part["size"] / 1e6, "6.1f") + " MB  bygget "
              + (part["built_at"] or "-") + "  utkast "
              + (", ".join(part["drafts"]) if part["drafts"] else "ingen"))
        for note in part["notes"]:
            print("           ADVARSEL: " + note)
    print("\nmottaker: " + parts[0]["address_key"])
    print("samlet utkast far orderReferenceId " + parts[0]["order_id"])

    problems = check(parts)
    if problems:
        print("\nBLOKKERER:")
        for problem in problems:
            print("  " + problem)
        return 1

    if not args.apply:
        print("\nTORRKJORING - ingenting lastet opp, opprettet eller slettet")
        return 0

    result = merge(parts)
    print("\nFERDIG: utkast " + str(result["draft_id"]) + " med "
          + str(result["items"]) + " boker")
    return 0


if __name__ == "__main__":
    sys.exit(main())

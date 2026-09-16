# -*- coding: utf-8 -*-
"""Slaa sammen flere FERDIGE ordre til ETT Gelato-utkast, manuelt.

Til ordre som ble bygget for ordre-samlingen fantes, eller som er bygget
utenfor workeren. Hver bok blir sitt eget item med quantity 1 - aldri
quantity 2, som ville trykt samme bok to ganger.

Rekkefolgen er bevisst: det nye utkastet opprettes FOR de gamle slettes,
saa vi aldri staar uten utkast hvis noe feiler underveis.

  python finish_merged_order.py --primary 1229 \
      --order 1229:dyreparken:Max --order 1228:fotballstjernen:Aron --dry-run
  ... --apply
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))
import dp_secrets  # noqa: E402

# Laa hardkodet her til 2026-09-15. Naa i config/secrets.json (.gitignore).
GELATO_KEY = dp_secrets.gelato_api_key()
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
STATE_DIR = "C:/DreamPage-OS/state/gelato_drafts"


def gelato(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request("https://order.gelatoapis.com/v4" + path,
                                 data=data, method=method,
                                 headers={"X-API-KEY": GELATO_KEY,
                                          "Content-Type": "application/json",
                                          "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except Exception:                # noqa: BLE001
            return exc.code, {"raw": raw}


def remote_size(url: str) -> int:
    """Stoerrelsen paa fila Gelato faktisk har. Signert S3-URL nekter HEAD,
    saa vi ber om én byte og leser totalen ut av Content-Range."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        cr = r.headers.get("Content-Range", "")
    return int(cr.split("/")[-1]) if "/" in cr else -1


def drive_upload(path: str, parent: str, folder: str) -> dict:
    out = subprocess.run(
        [sys.executable, os.path.join(SCRIPT_DIR, "drive_upload.py"),
         "--file", path, "--parent", parent, "--folder", folder, "--public"],
        capture_output=True, text=True, encoding="utf-8")
    if out.returncode:
        raise SystemExit(f"Drive-opplasting feilet for {path}:\n{out.stderr}")
    start = out.stdout.rfind("{")
    if start != -1:
        try:
            return json.loads(out.stdout[start:])
        except json.JSONDecodeError:
            pass
    raise SystemExit("fant ingen JSON fra drive_upload.py:\n" + out.stdout)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", action="append", required=True,
                    metavar="ID:SLUG:NAVN",
                    help="gjenta for hver bok, f.eks. 1228:fotballstjernen:Aron")
    ap.add_argument("--primary", required=True,
                    help="hvilken ordre-id den samlede ordren skal hete i Gelato")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--shipping-from", metavar="ID",
                    help="hvilken ordres mottakeradresse som gjelder naar de to "
                         "utkastene ikke er like (skrivefeil i navn e.l.). Uten "
                         "denne avbryter scriptet paa ulike mottakere, som foer.")
    ap.add_argument("--allow-rebuilt", action="store_true",
                    help="godta at den lokale PDF-en ikke er den som ligger i "
                         "utkastet. Bruk BARE naar du med vilje har bygget boka "
                         "om (nye malbilder) og vil ha den nye versjonen trykt.")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    books = []
    for spec in args.order:
        oid, slug, name = spec.split(":", 2)
        books.append({"order_id": oid, "slug": slug, "name": name})
    if len(books) < 2:
        raise SystemExit("trenger minst to ordre")
    if args.primary not in [b["order_id"] for b in books]:
        raise SystemExit("--primary maa vaere en av ordrene")

    # 1) Finn og kontroller hvert eksisterende utkast.
    for b in books:
        st, res = gelato("POST", "/orders:search", {"orderReferenceIds": [b["order_id"]]})
        drafts = [o for o in res.get("orders", []) if o.get("orderType") == "draft"]
        if len(drafts) != 1:
            raise SystemExit(f"ordre {b['order_id']}: forventet noeyaktig ett utkast, "
                             f"fant {len(drafts)}")
        full_st, o = gelato("GET", f"/orders/{drafts[0]['id']}")
        if full_st != 200 or o.get("fulfillmentStatus") != "draft":
            raise SystemExit(f"ordre {b['order_id']} er ikke lenger et utkast")
        if len(o.get("items", [])) != 1:
            raise SystemExit(f"ordre {b['order_id']} har {len(o['items'])} items - "
                             "avbryter, dette scriptet forventer én bok per ordre")
        it = o["items"][0]
        b["draft_id"] = o["id"]
        b["shipping"] = o["shippingAddress"]
        b["customer_ref"] = o.get("customerReferenceId")
        b["item_ref"] = it["itemReferenceId"]
        b["product_uid"] = it["productUid"]
        b["page_count"] = it.get("pageCount", 30)
        b["remote_size"] = remote_size(it["files"][0]["url"])

        b["pdf"] = (f"C:/DreamPage-OS/books/{b['slug']}/orders/{b['order_id']}"
                    f"/pdf/{b['name']}_gelato.pdf")
        if not os.path.isfile(b["pdf"]):
            raise SystemExit("mangler " + b["pdf"])
        b["local_size"] = os.path.getsize(b["pdf"])
        # Sikrer at vi laster opp NOEYAKTIG den boka som ligger i utkastet,
        # ikke en eldre eller nyere bygging som tilfeldigvis ligger paa disk.
        if b["local_size"] != b["remote_size"]:
            if not args.allow_rebuilt:
                raise SystemExit(
                    f"ordre {b['order_id']}: den lokale PDF-en ({b['local_size']:,} B) er IKKE "
                    f"den som ligger i utkastet ({b['remote_size']:,} B). Avbryter.\n"
                    "Har du bygget boka om med vilje, kjor med --allow-rebuilt.")
            print(f"  #{b['order_id']}: laster opp den NYE byggingen "
                  f"({b['local_size']:,} B) i stedet for den i utkastet "
                  f"({b['remote_size']:,} B)  [--allow-rebuilt]")

    primary = next(b for b in books if b["order_id"] == args.primary)

    # 2) Samme mottaker for alle - ellers kan de ikke sendes sammen.
    def key(s):
        return " ".join(str(s.get(k) or "").strip().lower() for k in
                        ("firstName", "lastName", "addressLine1", "postCode", "city", "country"))
    if len({key(b["shipping"]) for b in books}) != 1:
        for b in books:
            print(f"  #{b['order_id']}: {key(b['shipping'])}")
        if not args.shipping_from:
            raise SystemExit("mottakerne er ikke like - kan ikke sendes i samme forsendelse.\n"
                             "Er forskjellen en skrivefeil, velg den riktige med "
                             "--shipping-from <ordre-id>.")
        chosen = next((b for b in books if b["order_id"] == args.shipping_from), None)
        if chosen is None:
            raise SystemExit("--shipping-from maa vaere en av ordrene")
        # Én mottaker for hele forsendelsen. Gelato ser bare adressen paa den
        # samlede ordren, saa dette avgjoer hva som faktisk staar paa pakka.
        primary["shipping"] = chosen["shipping"]
        print(f"  mottaker hentet fra #{chosen['order_id']} [--shipping-from]")

    print("Slaar sammen:")
    for b in books:
        print(f"  #{b['order_id']:5s} {b['name']:12s} {b['slug']:18s} "
              f"{b['local_size']/1e6:6.2f} MB  utkast {b['draft_id']}")
    s = primary["shipping"]
    print(f"  mottaker: {s['firstName']} {s['lastName']}, {s['addressLine1']}, "
          f"{s['postCode']} {s['city']}, {s['country']}")
    print(f"  samlet ordre far orderReferenceId {args.primary}")

    if not args.apply:
        preview = {
            "orderType": "draft",
            "orderReferenceId": args.primary,
            "customerReferenceId": primary["customer_ref"],
            "currency": "NOK",
            "shippingAddress": "<fra utkast " + primary["draft_id"] + ">",
            "items": [{"itemReferenceId": b["item_ref"], "productUid": b["product_uid"],
                       "pageCount": b["page_count"], "quantity": 1,
                       "files": [{"type": "default", "url": "<Drive-URL etter opplasting>"}]}
                      for b in books],
        }
        print("\nForespoerselen som ville blitt sendt:")
        print(json.dumps(preview, indent=1, ensure_ascii=False))
        print("\nTORRKJORING - ingenting lastet opp, opprettet eller slettet")
        return 0

    # 3) Last opp PDF-ene paa nytt, slik at lenkene peker paa noeyaktig disse filene.
    for b in books:
        with open(f"C:/DreamPage-OS/books/{b['slug']}/config.json", encoding="utf-8-sig") as fh:
            parent = json.load(fh)["driveFolderId"]
        up = drive_upload(b["pdf"], parent, b["order_id"])
        b["file_url"] = (up.get("downloadUrl")
                         or f"https://drive.usercontent.google.com/download"
                            f"?id={up['id']}&export=download&confirm=t")
        print(f"  Drive #{b['order_id']}: {up.get('id')}")

    body = {
        "orderType": "draft",
        "orderReferenceId": args.primary,
        "customerReferenceId": primary["customer_ref"],
        "currency": "NOK",
        "shippingAddress": {k: v for k, v in primary["shipping"].items()
                            if k in ("firstName", "lastName", "companyName", "addressLine1",
                                     "addressLine2", "city", "postCode", "state", "country",
                                     "email", "phone")},
        "items": [{
            "itemReferenceId": b["item_ref"],
            "productUid": b["product_uid"],
            "pageCount": b["page_count"],
            "files": [{"type": "default", "url": b["file_url"]}],
            "quantity": 1,
        } for b in books],
    }
    print("\nSender:")
    print(json.dumps(body, indent=1, ensure_ascii=False))

    st, res = gelato("POST", "/orders", body)
    if st not in (200, 201) or not res.get("id"):
        raise SystemExit(f"Gelato avviste ordren (HTTP {st}): {json.dumps(res)[:500]}")
    new_id = res["id"]
    print(f"\n  Samlet utkast opprettet (HTTP {st}): {new_id}")

    st, check = gelato("GET", f"/orders/{new_id}")
    got = check.get("items", [])
    print(f"  kontroll: {len(got)} items, "
          f"quantity {[i.get('quantity') for i in got]}, "
          f"refs {[i.get('itemReferenceId') for i in got]}")
    if len(got) != len(books) or any(i.get("quantity") != 1 for i in got):
        raise SystemExit("den nye ordren ser feil ut - de gamle utkastene er IKKE slettet")

    # 4) Foerst naa slettes de gamle. Nytt utkast finnes allerede.
    for b in books:
        s_del, _ = gelato("DELETE", f"/orders/{b['draft_id']}")
        print(f"  slettet gammelt utkast #{b['order_id']} {b['draft_id']} (HTTP {s_del})")

    # 5) Kvitteringer, saa finish_order.py ikke lager duplikat senere.
    os.makedirs(STATE_DIR, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    items = [{"order_id": b["order_id"], "itemReferenceId": b["item_ref"],
              "productUid": b["product_uid"], "pageCount": b["page_count"],
              "file_url": b["file_url"], "book_slug": b["slug"],
              "child_name": b["name"], "cover_type": "hardcover"} for b in books]
    with open(os.path.join(STATE_DIR, f"{args.primary}.json"), "w", encoding="utf-8") as fh:
        json.dump({"order_id": args.primary, "draft_id": new_id, "status": "open",
                   "email": (primary["shipping"].get("email") or "").lower(),
                   "created_at": now, "merged_orders": [b["order_id"] for b in books],
                   "items": items, "source": "finish_merged_order.py"},
                  fh, ensure_ascii=False, indent=1)
    for b in books:
        if b["order_id"] == args.primary:
            continue
        with open(os.path.join(STATE_DIR, f"{b['order_id']}.json"), "w", encoding="utf-8") as fh:
            json.dump({"order_id": b["order_id"], "status": "merged",
                       "merged_into_order": args.primary, "merged_into_draft": new_id,
                       "merged_at": now}, fh, ensure_ascii=False, indent=1)
    print(f"  kvitteringer skrevet i {STATE_DIR}")
    print(f"\n  https://dashboard.gelato.com/orders/{new_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

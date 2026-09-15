# -*- coding: utf-8 -*-
"""Bytt fil-URL-ene i det sammenslaatte utkastet for 1296+1297.

Bakgrunn: Marius_gelato.pdf vokste fra 73 MB til 106 MB da dinosaurenes-dal
fikk nye malbilder. Over 100 MB svarer https://drive.google.com/uc?...
med en HTML-side ("Google Drive - Virus scan warning") i stedet for fila,
saa Gelato hentet 2 kB HTML og item-1296 ble aldri ferdig - files[].id var
null og mimeType null, mens item-1297 (75 MB) gikk rett inn.

drive.usercontent.google.com/download?...&confirm=t hopper over varselet og
leverer fila. drive_upload.py bygger naa den lenka for alle opplastinger, men
dette utkastet ble laget foer den endringen.

Kildeutkastene er allerede slettet, saa finish_merged_order.py kan ikke kjoere
om igjen (den krever noeyaktig ett utkast per ordre). Derfor denne engangs-
fiksen, med samme rekkefolge som originalen: nytt utkast opprettes og
verifiseres FOER det gamle slettes.

  python fix_merged_draft_1297_urls.py --dry-run
  python fix_merged_draft_1297_urls.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from finish_merged_order import UA, STATE_DIR, gelato  # noqa: E402

BROKEN_DRAFT = "df8892eb-3cdb-4e3e-bce0-3edb8c7fbaa4"
PRIMARY = "1297"

# Filene ligger allerede paa Drive fra forrige kjoering - bare lenkeformen var feil.
DRIVE_IDS = {
    "item-1296": "1sVOC58nK4osTygKpgVFllIDLqpnogGcH",
    "item-1297": "1C83drnWMEtZNGG0cOXTNR0MSGs-HRslP",
}
EXPECTED_SIZE = {
    "item-1296": 105625586,
    "item-1297": 74970938,
}
BOOKS = {
    "item-1296": {"order_id": "1296", "book_slug": "dinosaurenes-dal", "child_name": "Marius"},
    "item-1297": {"order_id": "1297", "book_slug": "fotballstjernen", "child_name": "Alexander"},
}


def url_for(file_id: str) -> str:
    return ("https://drive.usercontent.google.com/download"
            f"?id={file_id}&export=download&confirm=t")


def probe(url: str) -> int:
    """Total stoerrelse Gelato vil se. -1 betyr at lenka ikke gir en fil."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-0"})
    with urllib.request.urlopen(req, timeout=180) as r:
        ctype = r.headers.get("Content-Type", "")
        cr = r.headers.get("Content-Range", "")
    if "html" in ctype.lower() or "/" not in cr:
        return -1
    return int(cr.split("/")[-1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    st, old = gelato("GET", "/orders/" + BROKEN_DRAFT)
    if st != 200 or old.get("fulfillmentStatus") != "draft":
        raise SystemExit(f"utkast {BROKEN_DRAFT} er ikke et utkast lenger (HTTP {st})")

    items = []
    for it in old["items"]:
        ref = it["itemReferenceId"]
        if ref not in DRIVE_IDS:
            raise SystemExit("ukjent item " + ref)
        url = url_for(DRIVE_IDS[ref])
        size = probe(url)
        print(f"  {ref}: {size:,} B (venter {EXPECTED_SIZE[ref]:,})")
        if size != EXPECTED_SIZE[ref]:
            raise SystemExit(f"{ref}: lenka gir {size} B, ikke den ferdige PDF-en. Avbryter.")
        items.append({
            "itemReferenceId": ref,
            "productUid": it["productUid"],
            "pageCount": it.get("pageCount", 30),
            "files": [{"type": "default", "url": url}],
            "quantity": 1,
        })

    s = old["shippingAddress"]
    body = {
        "orderType": "draft",
        "orderReferenceId": PRIMARY,
        "customerReferenceId": old.get("customerReferenceId"),
        "currency": old.get("currency", "NOK"),
        "shippingAddress": {k: v for k, v in s.items()
                            if k in ("firstName", "lastName", "companyName", "addressLine1",
                                     "addressLine2", "city", "postCode", "state", "country",
                                     "email", "phone")},
        "items": items,
    }
    print(f"\n  mottaker: {s['firstName']} {s['lastName']}, {s['addressLine1']}, "
          f"{s['postCode']} {s['city']}, {s['country']}")

    if not args.apply:
        print("\n" + json.dumps(body, indent=1, ensure_ascii=False))
        print("\nTORRKJORING - ingenting opprettet eller slettet")
        return 0

    st, res = gelato("POST", "/orders", body)
    if st not in (200, 201) or not res.get("id"):
        raise SystemExit(f"Gelato avviste ordren (HTTP {st}): {json.dumps(res)[:500]}")
    new_id = res["id"]
    print(f"\n  Nytt utkast: {new_id}")

    # Gelato henter filene asynkront. Vent til BEGGE har faatt en fil-id -
    # det er nettopp det som manglet sist, og det maa verifiseres foer det
    # gamle utkastet slettes.
    ok = False
    for attempt in range(20):
        time.sleep(15)
        cst, check = gelato("GET", f"/orders/{new_id}")
        got = check.get("items", [])
        states = [(i["itemReferenceId"], (i["files"][0] or {}).get("id"),
                   (i["files"][0] or {}).get("mimeType")) for i in got]
        print(f"  [{attempt + 1}/20] {states}", flush=True)
        if len(got) == len(items) and all(f_id for _, f_id, _ in states):
            ok = True
            break
    if not ok:
        raise SystemExit("filene ble ikke hentet inn - det GAMLE utkastet er IKKE slettet.\n"
                         f"Nytt utkast: {new_id}")

    dst, _ = gelato("DELETE", "/orders/" + BROKEN_DRAFT)
    print(f"  slettet oedelagt utkast {BROKEN_DRAFT} (HTTP {dst})")

    now = datetime.now(timezone.utc).isoformat()
    path = os.path.join(STATE_DIR, f"{PRIMARY}.json")
    with open(path, encoding="utf-8") as fh:
        rec = json.load(fh)
    rec["draft_id"] = new_id
    rec["created_at"] = now
    rec["source"] = "fix_merged_draft_1297_urls.py"
    for entry in rec.get("items", []):
        ref = "item-" + entry["order_id"]
        if ref in DRIVE_IDS:
            entry["file_url"] = url_for(DRIVE_IDS[ref])
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1)

    other = os.path.join(STATE_DIR, "1296.json")
    with open(other, encoding="utf-8") as fh:
        rec2 = json.load(fh)
    rec2["merged_into_draft"] = new_id
    rec2["merged_at"] = now
    with open(other, "w", encoding="utf-8") as fh:
        json.dump(rec2, fh, ensure_ascii=False, indent=1)

    print(f"  kvitteringer oppdatert i {STATE_DIR}")
    print(f"\n  https://dashboard.gelato.com/orders/{new_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

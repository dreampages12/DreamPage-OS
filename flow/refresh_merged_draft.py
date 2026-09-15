# -*- coding: utf-8 -*-
"""Oppdater et ALLEREDE sammenslaatt Gelato-utkast med nye PDF-er.

finish_merged_order.py duger bare foerste gang: den slaar sammen ett utkast
per ordre, og etter sammenslaaingen finnes de ikke lenger - det samlede
utkastet ligger under EN orderReferenceId (den primaere ordren). Skal en av
boekene rettes etterpaa, er det denne du bruker.

Den laster opp de PDF-ene du navngir paa nytt, bygger et nytt utkast med
noeyaktig de samme item-ene (samme itemReferenceId, productUid og pageCount,
quantity 1 hver), venter til Gelato faktisk har hentet inn ALLE filene, og
sletter foerst da det gamle. Rekkefolgen er den samme som i
finish_merged_order.py: vi staar aldri uten utkast.

At Gelato har hentet fila (files[0].id != null) maa verifiseres, ikke antas -
en Drive-lenke over 100 MB serverer en HTML-side, og utkastet ser helt riktig
ut i API-svaret likevel. Se drive_upload.py for lenkeformen.

  python refresh_merged_draft.py --draft <utkast-id> \
      --refresh 1296:dinosaurenes-dal:Marius --dry-run
  ... --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from finish_merged_order import STATE_DIR, drive_upload, gelato, remote_size  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", required=True, help="id-en til det sammenslaatte utkastet")
    ap.add_argument("--refresh", action="append", required=True, metavar="ID:SLUG:NAVN",
                    help="ordren som skal lastes opp paa nytt, gjenta ved behov")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    refresh = {}
    for spec in args.refresh:
        oid, slug, name = spec.split(":", 2)
        pdf = f"C:/ComfyUI/books/{slug}/orders/{oid}/pdf/{name}_gelato.pdf"
        if not os.path.isfile(pdf):
            raise SystemExit("mangler " + pdf)
        refresh["item-" + oid] = {"order_id": oid, "slug": slug, "name": name, "pdf": pdf}

    st, old = gelato("GET", "/orders/" + args.draft)
    if st != 200:
        raise SystemExit(f"fant ikke utkast {args.draft} (HTTP {st})")
    if old.get("fulfillmentStatus") != "draft":
        raise SystemExit(f"{args.draft} er ikke lenger et utkast "
                         f"({old.get('fulfillmentStatus')}) - avbryter")

    refs = [it["itemReferenceId"] for it in old["items"]]
    ukjent = set(refresh) - set(refs)
    if ukjent:
        raise SystemExit(f"utkastet har ingen item {', '.join(sorted(ukjent))}. "
                         f"Det inneholder: {', '.join(refs)}")

    s = old["shippingAddress"]
    print(f"utkast   {args.draft}  (ref {old.get('orderReferenceId')})")
    print(f"mottaker {s['firstName']} {s['lastName']}, {s['addressLine1']}, "
          f"{s['postCode']} {s['city']}, {s['country']}")
    for it in old["items"]:
        ref = it["itemReferenceId"]
        if ref in refresh:
            ny = os.path.getsize(refresh[ref]["pdf"])
            print(f"  {ref}: LASTES OPP PAA NYTT  {remote_size(it['files'][0]['url']):,} B "
                  f"-> {ny:,} B  ({refresh[ref]['pdf']})")
        else:
            print(f"  {ref}: beholdes som den er")

    if not args.apply:
        print("\nTORRKJORING - ingenting lastet opp, opprettet eller slettet")
        return 0

    items = []
    for it in old["items"]:
        ref = it["itemReferenceId"]
        if ref in refresh:
            b = refresh[ref]
            with open(f"C:/ComfyUI/books/{b['slug']}/config.json", encoding="utf-8-sig") as fh:
                parent = json.load(fh)["driveFolderId"]
            up = drive_upload(b["pdf"], parent, b["order_id"])
            url = up.get("downloadUrl")
            if not url:
                raise SystemExit("drive_upload.py ga ingen downloadUrl for " + ref)
            print(f"  Drive {ref}: {up.get('id')}")
        else:
            # Den signerte S3-lenka utloeper etter et doegn, men Gelato kopierer
            # fila naar ordren opprettes, saa den holder lenge nok her.
            url = it["files"][0]["url"]
        items.append({
            "itemReferenceId": ref,
            "productUid": it["productUid"],
            "pageCount": it.get("pageCount", 30),
            "files": [{"type": "default", "url": url}],
            "quantity": 1,
        })

    body = {
        "orderType": "draft",
        "orderReferenceId": old.get("orderReferenceId"),
        "customerReferenceId": old.get("customerReferenceId"),
        "currency": old.get("currency", "NOK"),
        "shippingAddress": {k: v for k, v in s.items()
                            if k in ("firstName", "lastName", "companyName", "addressLine1",
                                     "addressLine2", "city", "postCode", "state", "country",
                                     "email", "phone")},
        "items": items,
    }
    st, res = gelato("POST", "/orders", body)
    if st not in (200, 201) or not res.get("id"):
        raise SystemExit(f"Gelato avviste ordren (HTTP {st}): {json.dumps(res)[:500]}")
    new_id = res["id"]
    print(f"\n  Nytt utkast: {new_id}")

    ok = False
    for attempt in range(20):
        time.sleep(15)
        _, check = gelato("GET", f"/orders/{new_id}")
        got = check.get("items", [])
        states = [(i["itemReferenceId"], (i["files"][0] or {}).get("id")) for i in got]
        print(f"  [{attempt + 1}/20] {states}", flush=True)
        if len(got) == len(items) and all(fid for _, fid in states):
            ok = True
            break
    if not ok:
        raise SystemExit("Gelato hentet ikke inn alle filene - det GAMLE utkastet er IKKE "
                         f"slettet.\nNytt utkast: {new_id}")

    dst, _ = gelato("DELETE", "/orders/" + args.draft)
    print(f"  slettet gammelt utkast {args.draft} (HTTP {dst})")

    now = datetime.now(timezone.utc).isoformat()
    primary = old.get("orderReferenceId")
    path = os.path.join(STATE_DIR, f"{primary}.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
        rec["draft_id"] = new_id
        rec["created_at"] = now
        rec["source"] = "refresh_merged_draft.py"
        by_ref = {"item-" + e["order_id"]: e for e in rec.get("items", [])}
        for item in items:
            entry = by_ref.get(item["itemReferenceId"])
            if entry is not None and item["itemReferenceId"] in refresh:
                entry["file_url"] = item["files"][0]["url"]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, ensure_ascii=False, indent=1)
        for entry in rec.get("items", []):
            other = os.path.join(STATE_DIR, f"{entry['order_id']}.json")
            if entry["order_id"] == primary or not os.path.isfile(other):
                continue
            with open(other, encoding="utf-8") as fh:
                rec2 = json.load(fh)
            if rec2.get("status") == "merged":
                rec2["merged_into_draft"] = new_id
                rec2["merged_at"] = now
                with open(other, "w", encoding="utf-8") as fh:
                    json.dump(rec2, fh, ensure_ascii=False, indent=1)
        print(f"  kvitteringer oppdatert i {STATE_DIR}")

    print(f"\n  https://dashboard.gelato.com/orders/{new_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

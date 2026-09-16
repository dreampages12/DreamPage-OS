# -*- coding: utf-8 -*-
"""Ferdigstill en ordre utenfor n8n: Drive-opplasting + Gelato-utkast.

Speiler nodene Create Drive Folder / Upload / Make Public / Create Gelato Draft
i workflowen. Payloaden hentes fra en tidligere execution, saa adresse, e-post
og cover_type blir noeyaktig det WooCommerce sendte - ikke gjettet.

Rydder ALLTID gamle utkast paa samme orderReferenceId foerst: Gelato avviser
ikke duplikater, og erstatter dem bare noen ganger av seg selv.

  python finish_order.py --order 1221 --execution 2716 --dry-run
  python finish_order.py --order 1221 --execution 2716 --apply
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))
import dp_secrets  # noqa: E402

# Laa hardkodet her til 2026-09-15. Naa i config/secrets.json (.gitignore).
GELATO_KEY = dp_secrets.gelato_api_key()
# Cloudflare svarer 403 "error code: 1010" paa urllib sin standard User-Agent.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

PRODUCT_UID = {
    "hardcover": ("photobooks-hardcover_pf_200x200-mm-8x8-inch_pt_170-gsm-65lb-coated-silk"
                  "_cl_4-4_ccl_4-4_bt_glued-left_ct_matt-lamination_prt_1-0"
                  "_cpt_130-gsm-65-lb-cover-coated-silk_ver"),
    "softcover": ("photobooks-softcover_pf_200x200-mm-8x8-inch_pt_170-gsm-65lb-coated-silk"
                  "_cl_4-4_ccl_4-4_bt_glued-left_ct_matt-lamination_prt_1-0"
                  "_cpt_250-gsm-100-lb-cover-coated-silk_ver"),
}


def gelato(method: str, url: str, body=None):
    """Delegerer til flow/gelato_api.py.

    Signaturen staar fordi reprint_order, dp_merge og cleanup_variants
    importerer NOEYAKTIG denne. Innmaten er byttet ut slik at alle tre faar
    retry paa 408/429/5xx og feilkroppen fra Gelato i meldingen - se
    docstringen i gelato_api.py for hvorfor ingen av delene fantes for.
    """
    import gelato_api
    return gelato_api.call(method, url, body)


def load_payload(execution_id: int) -> dict:
    from republish_job import load_payload as lp
    return lp(execution_id)


def drive_upload(path: str, parent: str, folder: str) -> dict:
    out = subprocess.run(
        [sys.executable, os.path.join(SCRIPT_DIR, "drive_upload.py"),
         "--file", path, "--parent", parent, "--folder", folder, "--public"],
        capture_output=True, text=True, encoding="utf-8")
    if out.returncode:
        raise SystemExit(f"Drive-opplasting feilet for {path}:\n{out.stderr}")
    # drive_upload.py skriver JSON med indent=1, altsaa over flere linjer.
    start = out.stdout.rfind("{")
    if start != -1:
        try:
            return json.loads(out.stdout[start:])
        except json.JSONDecodeError:
            pass
    raise SystemExit("fant ingen JSON fra drive_upload.py:\n" + out.stdout)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", required=True)
    ap.add_argument("--execution", type=int, required=True)
    ap.add_argument("--slug", default="motet-i-hjertet")
    ap.add_argument("--name", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="kjoer selv om ordren ligger i et sammenslaatt utkast")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    # Er ordren allerede med i et sammenslaatt Gelato-utkast, finnes den ikke
    # lenger under sin egen orderReferenceId. Uten denne sperren ville soeket
    # nedenfor komme tomt tilbake og vi ville laget et DUPLIKAT ved siden av
    # det sammenslaatte utkastet - to trykte boeker for en betalt.
    merge_state = f"C:/DreamPage-OS/state/gelato_drafts/{args.order}.json"
    if os.path.isfile(merge_state) and not args.force:
        with open(merge_state, encoding="utf-8") as fh:
            state = json.load(fh)
        if state.get("status") == "merged":
            raise SystemExit(
                f"ordre {args.order} ligger i det sammenslaatte utkastet "
                f"{state.get('merged_into_draft')} (sammen med ordre "
                f"{state.get('merged_into_order')}).\n"
                f"Slett det utkastet i Gelato foerst, eller kjoer med --force.")

    payload = load_payload(args.execution)
    if str(payload.get("order_id")) != str(args.order):
        raise SystemExit(f"execution {args.execution} gjelder ordre "
                         f"{payload.get('order_id')}, ikke {args.order}")

    with open(f"C:/DreamPage-OS/books/{args.slug}/config.json", encoding="utf-8-sig") as fh:
        cfg = json.load(fh)
    parent = cfg["driveFolderId"]

    pdf_dir = f"C:/DreamPage-OS/books/{args.slug}/orders/{args.order}/pdf"
    cover = f"{pdf_dir}/{args.name}_cover.pdf"
    gelato_pdf = f"{pdf_dir}/{args.name}_gelato.pdf"
    inner = f"{pdf_dir}/{args.name}_innersider.pdf"
    for p in (cover, gelato_pdf, inner):
        if not os.path.isfile(p):
            raise SystemExit("mangler " + p)
        print(f"  {os.path.basename(p):24s} {os.path.getsize(p)/1e6:7.2f} MB")

    cover_type = payload.get("cover_type", "hardcover")
    ship = payload["shipping"]
    cust = payload["customer"]
    print(f"  cover_type   {cover_type}")
    print(f"  mottaker     {ship['first_name']} {ship['last_name']}, "
          f"{ship['address_1']}, {ship['postcode']} {ship['city']}, {ship['country']}")
    print(f"  e-post       {cust.get('email')}")

    st, res = gelato("POST", "https://order.gelatoapis.com/v4/orders:search",
                     {"orderReferenceIds": [str(args.order)]})
    old = [o["id"] for o in res.get("orders", [])]
    print(f"  eksisterende utkast: {old or 'ingen'}")

    if not args.apply:
        print("TORRKJORING - ingenting lastet opp eller opprettet")
        return 0

    for oid in old:
        s, _ = gelato("DELETE", f"https://order.gelatoapis.com/v4/orders/{oid}")
        print(f"  slettet gammelt utkast {oid} (HTTP {s})")

    up_cover = drive_upload(cover, parent, str(args.order))
    print("  Drive cover  :", up_cover.get("id"))
    up_inner = drive_upload(inner, parent, str(args.order))
    print("  Drive inner  :", up_inner.get("id"))
    up_gelato = drive_upload(gelato_pdf, parent, str(args.order))
    print("  Drive gelato :", up_gelato.get("id"))

    file_url = (up_gelato.get("downloadUrl")
                or f"https://drive.usercontent.google.com/download"
                   f"?id={up_gelato['id']}&export=download&confirm=t")

    body = {
        "orderType": "draft",
        "orderReferenceId": str(args.order),
        "customerReferenceId": cust.get("email") or f"customer-{args.order}",
        "currency": "NOK",
        "shippingAddress": {
            "firstName": ship["first_name"],
            "lastName": ship["last_name"],
            "addressLine1": ship["address_1"],
            "addressLine2": ship.get("address_2") or "",
            "city": ship["city"],
            "postCode": ship["postcode"],
            "country": ship["country"],
            "email": cust.get("email"),
            "phone": ship.get("phone") or cust.get("phone") or "",
        },
        "items": [{
            "itemReferenceId": f"item-{args.order}",
            "productUid": PRODUCT_UID[cover_type],
            "pageCount": 30,          # produkt-variant-ID, ikke faktisk sidetall
            "files": [{"type": "default", "url": file_url}],
            "quantity": 1,
        }],
    }
    st, res = gelato("POST", "https://order.gelatoapis.com/v4/orders", body)
    print(f"  Gelato-utkast opprettet (HTTP {st}): {res.get('id')}")

    st, res = gelato("POST", "https://order.gelatoapis.com/v4/orders:search",
                     {"orderReferenceIds": [str(args.order)]})
    print("  utkast na:", [o["id"] for o in res.get("orders", [])])
    return 0


if __name__ == "__main__":
    sys.exit(main())

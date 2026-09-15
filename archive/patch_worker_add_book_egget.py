"""Registrer 'Det Forsvunne Dinosauregget' i worker-workflowen.

Legger boka inn i TITLE_TO_SLUG (og HANDLE_TO_SLUG) i Load Book Config, slik at
WooCommerce-ordre med denne tittelen/slug'en finner riktig bokmappe.

Bruk:
  python patch_worker_add_book_egget.py --dry-run
  python patch_worker_add_book_egget.py --apply
  python patch_worker_add_book_egget.py --apply --woo-slug <slug-fra-woocommerce>
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys

DB = r"C:\Users\tobia\.n8n\database.sqlite"
WF_ID = "xy8qiRUzcBpH52CI"
SLUG = "det-forsvunne-dinosauregget"  # overstyres av --slug

# Tittel -> slug. Oppslaget i Load Book Config er lowercase på tittelen.
# Æ/Ø/Å tåles ikke i den eksisterende koden (den har mojibake fra før), så
# nøklene her holdes til ren ASCII slik resten av kartet gjør.
TITLES = [
    # Norsk
    "det forsvunne dinosauregget",
    "forsvunne dinosauregget",
    "det forsvunne dinosaur egget",
    # Engelsk
    "the lost dinosaur egg",
    "lost dinosaur egg",
    # Svensk
    "det forsvunna dinosaurieagget",
    "den forsvunna dinosaurieagget",
    "det forlorade dinosaurieagget",
]

HANDLES = [
    "det-forsvunne-dinosauregget",
    "forsvunne-dinosauregget",
    "the-lost-dinosaur-egg",
]


def patch(nodes, extra_handle: str | None):
    lbc = next(n for n in nodes if n["name"] == "Load Book Config")
    code = lbc["parameters"]["jsCode"]
    changed = []

    anchor = '  "dinosaurenes dal":     "dinosaurenes-dal",\n'
    if anchor not in code:
        raise SystemExit("Load Book Config: fant ikke ankeret i TITLE_TO_SLUG")

    added = "".join(
        '  "%s": "%s",\n' % (t, SLUG) for t in TITLES if '"%s"' % t not in code
    )
    if added:
        code = code.replace(anchor, anchor + added, 1)
        changed.append("TITLE_TO_SLUG += %d titler" % added.count("\n"))

    handles = list(HANDLES)
    if extra_handle:
        handles.append(extra_handle.strip().lower())

    h_anchor = '  "enhjorningsdalen":         "enhjorning",\n'
    if h_anchor not in code:
        raise SystemExit("Load Book Config: fant ikke ankeret i HANDLE_TO_SLUG")
    h_added = "".join(
        '  "%s": "%s",\n' % (h, SLUG) for h in handles if '"%s"' % h not in code
    )
    if h_added:
        code = code.replace(h_anchor, h_anchor + h_added, 1)
        changed.append("HANDLE_TO_SLUG += %d handles" % h_added.count("\n"))

    lbc["parameters"]["jsCode"] = code
    return changed


def main() -> int:
    global SLUG, TITLES, HANDLES
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--slug", default=SLUG)
    ap.add_argument("--titles", default="", help="kommaseparerte titler -> slug")
    ap.add_argument("--handles", default="", help="kommaseparerte handles -> slug")
    ap.add_argument("--woo-slug", default="",
                    help="Produkt-slug fra WooCommerce, hvis den avviker")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    SLUG = args.slug
    if args.titles:
        TITLES = [t.strip().lower() for t in args.titles.split(",") if t.strip()]
    if args.handles:
        HANDLES = [h.strip().lower() for h in args.handles.split(",") if h.strip()]

    con = sqlite3.connect(DB)
    raw = con.execute("select nodes from workflow_entity where id=?", (WF_ID,)).fetchone()[0]
    nodes = json.loads(raw)

    for c in patch(nodes, args.woo_slug or None):
        print("  +", c)

    if args.apply:
        con.execute("update workflow_entity set nodes=?, updatedAt=datetime('now') where id=?",
                    (json.dumps(nodes, ensure_ascii=False), WF_ID))
        con.commit()
        print("Skrevet til n8n-databasen. Restart n8n for aa laste endringen.")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

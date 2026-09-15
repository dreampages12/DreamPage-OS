# -*- coding: utf-8 -*-
"""Registrer 'Fotball VM' i worker-workflowen.

Legger boka inn i TITLE_TO_SLUG (og HANDLE_TO_SLUG) i Load Book Config, slik at
WooCommerce-ordre med denne tittelen/slug'en finner riktig bokmappe.

Den norske tittelen ville uansett truffet via slugify-fallbacken
("fotball vm" -> "fotball-vm"), men de engelske og svenske variantene gjor
ikke det - derfor listes de eksplisitt.

Bruk:
  python patch_worker_add_book_fotball_vm.py --dry-run
  python patch_worker_add_book_fotball_vm.py --apply
  python patch_worker_add_book_fotball_vm.py --apply --woo-slug <slug-fra-woocommerce>
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = r"C:\Users\tobia\.n8n\database.sqlite"
WF_ID = "xy8qiRUzcBpH52CI"
SLUG = "fotball-vm"

TITLES = [
    # Norsk
    "fotball vm",
    "fotball-vm",
    "fotballvm",
    "vm i fotball",
    # Engelsk
    "the world cup",
    "world cup",
    "football world cup",
    "soccer world cup",
    "wins the world cup",
    # Svensk
    "fotbolls vm",
    "fotbolls-vm",
    "fotbollsvm",
]

HANDLES = [
    "fotball-vm",
    "fotballvm",
    "vm-i-fotball",
    "world-cup",
    "the-world-cup",
    "football-world-cup",
    "soccer-world-cup",
    "fotbolls-vm",
]


def patch(nodes, extra_handle):
    lbc = next(n for n in nodes if n["name"] == "Load Book Config")
    code = lbc["parameters"]["jsCode"]
    changed = []

    # Nokler sjekkes per kart: en tittel og en handle kan hete det samme, og
    # da skal begge legges inn.
    split = code.index("const HANDLE_TO_SLUG")
    title_region, handle_region = code[:split], code[split:]

    anchor = '  "dinosaurenes dal":     "dinosaurenes-dal",\n'
    if anchor not in code:
        raise SystemExit("Load Book Config: fant ikke ankeret i TITLE_TO_SLUG")
    added = "".join('  "%s": "%s",\n' % (t, SLUG)
                    for t in TITLES if '"%s"' % t not in title_region)
    if added:
        code = code.replace(anchor, anchor + added, 1)
        changed.append("TITLE_TO_SLUG += %d titler" % added.count("\n"))

    handles = list(HANDLES)
    if extra_handle:
        handles.append(extra_handle.strip().lower())

    h_anchor = '  "enhjorningsdalen":         "enhjorning",\n'
    if h_anchor not in code:
        raise SystemExit("Load Book Config: fant ikke ankeret i HANDLE_TO_SLUG")
    h_added = "".join('  "%s": "%s",\n' % (h, SLUG)
                      for h in handles if '"%s"' % h not in handle_region)
    if h_added:
        code = code.replace(h_anchor, h_anchor + h_added, 1)
        changed.append("HANDLE_TO_SLUG += %d handles" % h_added.count("\n"))

    lbc["parameters"]["jsCode"] = code
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--woo-slug", default="")
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    row = con.execute("select nodes from workflow_entity where id=?", (WF_ID,)).fetchone()
    if not row:
        raise SystemExit("fant ikke worker-workflowen " + WF_ID)
    nodes = json.loads(row[0])

    changed = patch(nodes, args.woo_slug)
    if not changed:
        print("ingenting a endre - fotball-vm er allerede registrert")
        return 0
    print("\n".join(changed))

    if not args.apply:
        print("(dry-run - kjor med --apply for a skrive)")
        return 0

    shutil.copy2(DB, DB + ".backup-before-fotball-vm-20260828")
    con.execute("update workflow_entity set nodes=?, updatedAt=datetime('now') where id=?",
                (json.dumps(nodes, ensure_ascii=False), WF_ID))
    con.commit()
    con.close()
    print("skrevet. n8n ma restartes for at endringen skal tre i kraft.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Endre enkeltparametre paa en bok-node i DP Title Tester.

Brukes naar en tittel skal finjusteres uten aa aapne n8n. Endringene boer
etterpaa synkes til next_book_titles.json med sync_title_params.py, slik at
forsiden i boka og paa landingssiden ser likt ut som i testeren.

Bruk:
  python update_title_tester_params.py --node den-tapte-superbyen \\
      --set gold="255, 255, 255" --set logo_scale=0.72
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys

DB = r"C:\Users\tobia\.n8n\database.sqlite"
WF_ID = "1BqeGkXyjbUBsR9N"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--node", required=True)
    ap.add_argument("--set", action="append", default=[], metavar="FELT=VERDI")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    updates = {}
    for pair in args.set:
        if "=" not in pair:
            ap.error(f"forventet FELT=VERDI, fikk {pair!r}")
        k, v = pair.split("=", 1)
        updates[k.strip()] = v.strip()

    con = sqlite3.connect(DB)
    nodes = json.loads(con.execute(
        "select nodes from workflow_entity where id=?", (WF_ID,)).fetchone()[0])
    node = next((n for n in nodes if n["name"] == args.node), None)
    if node is None:
        raise SystemExit(f"fant ikke noden {args.node!r}")

    assigns = node["parameters"]["assignments"]["assignments"]
    by_name = {a["name"]: a for a in assigns}
    for field, value in updates.items():
        if field not in by_name:
            print(f"  ADVARSEL: {field} finnes ikke paa noden - hopper over")
            continue
        old = by_name[field]["value"]
        if str(old) == value:
            print(f"    {field:14} {old!r}  (uendret)")
            continue
        by_name[field]["value"] = value
        print(f"  -> {field:14} {old!r}  ->  {value!r}")

    if args.apply:
        con.execute("update workflow_entity set nodes=?, updatedAt=datetime('now') "
                    "where id=?", (json.dumps(nodes, ensure_ascii=False), WF_ID))
        con.commit()
        print("Skrevet til n8n-databasen.")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

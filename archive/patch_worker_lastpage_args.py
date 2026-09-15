"""Legg manglende argumenter til 'Build Last Page' i worker-workflowen.

To feil i den opprinnelige noden, begge stille:

  --book-slug manglet       -> siste side brukte den generiske aapningssiden i
                               script/ i stedet for bokas egen, saa siden ikke
                               matchet resten av boka.
  mockup-mal manglet        -> build_last_page fant ingen DP_MOCKUP_TEMPLATE
                               (n8n arver ikke skallet vaart) og falt tilbake
                               til den enkle geometriske mockupen i stedet for
                               den PSD-kalibrerte.

Ingen av dem ville stoppet en ordre - de ville bare gitt feil bilde paa trykk,
som er verre. Derfor sendes mal-id-en naa som et flagg, ikke som miljovariabel.

Bruk:
  python patch_worker_lastpage_args.py --dry-run
  python patch_worker_lastpage_args.py --apply [--template <id>]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys

DB = r"C:\Users\tobia\.n8n\database.sqlite"
WF_ID = "xy8qiRUzcBpH52CI"
DEFAULT_TEMPLATE = "psd_1c8e5a0dfdc188d1_layer-1"

OLD_TAIL = (
    " --lang \"' + (d.script_language || 'nb') + '\""
    " --out \"' + d.orderPath + '/input/blank-back.png\"'"
)
NEW_TAIL = (
    " --lang \"' + (d.script_language || 'nb') + '\""
    " --book-slug \"' + d.book_slug + '\""
    " --mockup-template \"%s\""
    " --out \"' + d.orderPath + '/input/blank-back.png\"'"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--template", default=DEFAULT_TEMPLATE)
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    con = sqlite3.connect(DB)
    nodes = json.loads(con.execute(
        "select nodes from workflow_entity where id=?", (WF_ID,)).fetchone()[0])
    node = next((n for n in nodes if n["name"] == "Build Last Page"), None)
    if node is None:
        raise SystemExit("fant ikke noden 'Build Last Page'")

    cmd = node["parameters"]["command"]
    if "--book-slug" in cmd and "--mockup-template" in cmd:
        print("  (allerede patchet)")
        return 0
    if OLD_TAIL not in cmd:
        raise SystemExit("kommandoen ser annerledes ut enn ventet - nekter aa gjette")

    node["parameters"]["command"] = cmd.replace(OLD_TAIL, NEW_TAIL % args.template, 1)
    print("  + --book-slug")
    print(f"  + --mockup-template {args.template}")

    if args.apply:
        con.execute("update workflow_entity set nodes=?, updatedAt=datetime('now') "
                    "where id=?", (json.dumps(nodes, ensure_ascii=False), WF_ID))
        con.commit()
        print("Skrevet til n8n-databasen. Restart n8n for aa laste endringen.")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

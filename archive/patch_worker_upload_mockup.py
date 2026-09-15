"""Last opp MOCKUPEN til landingssiden, ikke den flate forsiden.

Kravet er at landingssiden viser noeyaktig det samme som staar trykt i boka.
I boka staar 3D-mockupen. Noden lastet likevel opp den flate forsiden, fordi
opplastingen ble bygget for mockupen fantes.

Patchen gjor to ting:
  1. Build Next Cover Title lagrer ogsaa en mockup (--mockup-out).
  2. Upload Continue Cover laster opp mockupen naar den finnes, ellers den
     flate forsiden. Fallback-en er med vilje: feiler mockup-serveren, skal
     landingssiden faa et bilde framfor ingenting.

Bruk:
  python patch_worker_upload_mockup.py --dry-run
  python patch_worker_upload_mockup.py --apply
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys

DB = r"C:\Users\tobia\.n8n\database.sqlite"
WF_ID = "xy8qiRUzcBpH52CI"
TEMPLATE = "psd_1c8e5a0dfdc188d1_layer-1"

# --- Build Next Cover Title: legg til mockup-utdata ---
COVER_OLD = " --out \"' + titled + '\"'"
COVER_NEW = (
    " --mockup-template \"%s\""
    " --out \"' + titled + '\""
    " --mockup-out \"' + mockup + '\"'" % TEMPLATE
)

# `mockup` maa defineres i prologen til begge nodene
PROLOG_OLD = "const titled = d.orderPath + '/pdf/page99_next.png'; "
PROLOG_NEW = (
    "const titled = d.orderPath + '/pdf/page99_next.png'; "
    "const mockup = d.orderPath + '/pdf/page99_next_mockup.png'; "
)

# --- Upload Continue Cover: last opp mockupen hvis den finnes ---
UPLOAD_OLD = "return PY + 'upload --file \"' + titled + '\""
UPLOAD_NEW = (
    "const fs = require('fs'); "
    "const src = fs.existsSync(mockup) ? mockup : titled; "
    "return PY + 'upload --file \"' + src + '\""
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    con = sqlite3.connect(DB)
    nodes = json.loads(con.execute(
        "select nodes from workflow_entity where id=?", (WF_ID,)).fetchone()[0])
    changed = []

    for name in ("Build Next Cover Title", "Upload Continue Cover"):
        node = next((n for n in nodes if n["name"] == name), None)
        if node is None:
            raise SystemExit(f"fant ikke noden {name!r}")
        cmd = node["parameters"]["command"]
        before = cmd

        if "const mockup" not in cmd:
            if PROLOG_OLD not in cmd:
                raise SystemExit(f"{name}: fant ikke prologen - nekter aa gjette")
            cmd = cmd.replace(PROLOG_OLD, PROLOG_NEW, 1)

        if name == "Build Next Cover Title":
            if "--mockup-out" not in cmd:
                if COVER_OLD not in cmd:
                    raise SystemExit(f"{name}: fant ikke --out - nekter aa gjette")
                cmd = cmd.replace(COVER_OLD, COVER_NEW, 1)
        else:
            if "fs.existsSync(mockup)" not in cmd:
                if UPLOAD_OLD not in cmd:
                    raise SystemExit(f"{name}: fant ikke upload-linjen - nekter aa gjette")
                cmd = cmd.replace(UPLOAD_OLD, UPLOAD_NEW, 1)

        if cmd != before:
            node["parameters"]["command"] = cmd
            changed.append(name)
            print(f"  + {name}")
        else:
            print(f"    {name} (allerede patchet)")

    if args.apply and changed:
        con.execute("update workflow_entity set nodes=?, updatedAt=datetime('now') "
                    "where id=?", (json.dumps(nodes, ensure_ascii=False), WF_ID))
        con.commit()
        print("Skrevet til n8n-databasen. Restart n8n for aa laste endringen.")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

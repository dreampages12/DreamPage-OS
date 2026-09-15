# -*- coding: utf-8 -*-
"""Fikser de to feilene som stoppet ordre 1248 (foerste live-ordre med continue_code).

  1. Alle executeCommand-noder kalte bare `python`, som loeses via PATH. n8n var
     startet fra et skall med ComfyUI-venv aktivt, saa `python` ble
     C:/ComfyUI/venv/Scripts/python.exe - et miljoe uten reportlab/segno/pypdf.
     Run Text Script krasjet, og Build Last Page fail-softet forbi uten QR.
     Her pinnes tolkeren til den absolutte stien som har laget alle vellykkede
     boeker, slik at PATH i skallet som starter n8n ikke lenger kan endre
     hvilket Python som kjoerer.

  2. Upload Continue Cover brukte require('fs') inne i et n8n-*uttrykk*. Det er
     aldri tillatt, saa uttrykket ble undefined og noden lastet aldri opp
     neste-bok-coveret til landingssiden. Tidligere ordre slapp unna fordi
     uttrykket kortsluttet paa manglende continue_code - ordre 1248 var den
     foerste som naadde linjen. Fallback-valget flyttes til build_last_page.py
     (--fallback), der det hoerer hjemme.

Bruk:
  python patch_worker_continue_fix.py --dry-run     # vis diff, roer ikke DB
  python patch_worker_continue_fix.py --apply       # skriv til n8n-databasen
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime

DB = r"C:\Users\tobia\.n8n\database.sqlite"
WF_ID = "xy8qiRUzcBpH52CI"

# Tolkeren som faktisk har alle avhengighetene (reportlab, pypdf, segno, PIL).
# Stien har ingen mellomrom, saa den trenger ingen anfoerselstegn - det holder
# den trygg baade i cmd.exe og inne i JS-strengene i uttrykksnodene.
PY = "C:/Users/tobia/AppData/Local/Programs/Python/Python310/python.exe"

# Treffer `python` bare naar den star som kommandonavn (etterfulgt av et sitert
# script eller et flagg). Roerer ikke `powershell` eller ord som inneholder
# "python".
PY_CALL = re.compile(r'(?<![\w./\\-])python(?= ["-])')

OLD_FS = (
    "const fs = require('fs'); const src = fs.existsSync(mockup) ? mockup : titled; "
    "return PY + 'upload --file \"' + src + '\"")
NEW_FS = (
    "return PY + 'upload --file \"' + mockup + '\" --fallback \"' + titled + '\"")


def patch(nodes: list) -> list:
    changed = []
    for node in nodes:
        if node.get("type") != "n8n-nodes-base.executeCommand":
            continue
        params = node.get("parameters") or {}
        cmd = params.get("command")
        if not isinstance(cmd, str):
            continue
        before = cmd

        if node.get("name") == "Upload Continue Cover" and OLD_FS in cmd:
            cmd = cmd.replace(OLD_FS, NEW_FS)
            changed.append(f"{node['name']}: require('fs') fjernet -> --fallback")

        n_py = len(PY_CALL.findall(cmd))
        if n_py:
            cmd = PY_CALL.sub(PY, cmd)
            changed.append(f"{node['name']}: pinnet tolker ({n_py} kall)")

        if cmd != before:
            params["command"] = cmd
    return changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    con = sqlite3.connect(DB)
    row = con.execute("select nodes from workflow_entity where id=?", (WF_ID,)).fetchone()
    if not row:
        raise SystemExit(f"fant ikke workflow {WF_ID}")
    nodes = json.loads(row[0])

    changed = patch(nodes)
    for c in changed:
        print("  +", c)
    if not changed:
        print("  (ingen endringer - allerede patchet)")
        con.close()
        return 0

    # Etterkontroll: ingen executeCommand skal sitte igjen med bar `python`
    # eller med require( i uttrykket.
    rest = []
    for node in nodes:
        if node.get("type") != "n8n-nodes-base.executeCommand":
            continue
        cmd = (node.get("parameters") or {}).get("command")
        if not isinstance(cmd, str):
            continue
        if PY_CALL.search(cmd):
            rest.append(f"{node['name']}: bar `python` igjen")
        if "require(" in cmd:
            rest.append(f"{node['name']}: require( igjen i uttrykk")
    if rest:
        print("\nSTOPP - etterkontroll feilet:")
        for r in rest:
            print("  !", r)
        con.close()
        return 1
    print("\n  etterkontroll OK: ingen bar `python`, ingen require( i uttrykk")

    if args.apply:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = rf"C:\Users\tobia\.n8n\backup-worker-{WF_ID}-before-continue-fix-{stamp}.json"
        with open(backup, "w", encoding="utf-8") as fh:
            json.dump(json.loads(row[0]), fh, ensure_ascii=False, indent=1)
        print("  sikkerhetskopi:", backup)

        con.execute("update workflow_entity set nodes=?, updatedAt=datetime('now') where id=?",
                    (json.dumps(nodes, ensure_ascii=False), WF_ID))
        con.commit()
        print("Skrevet til n8n-databasen. n8n maa restartes for aa laste den nye versjonen.")
    else:
        print("TORRKJORING - databasen er uroert")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

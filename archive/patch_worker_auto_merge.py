# -*- coding: utf-8 -*-
"""Legg inn "Auto Merge Multibook" i Dreampage Worker v2.

En ordre med flere boeker gir en n8n-kjoering per bok, og dermed ett
Gelato-utkast per bok: `1411-b1` og `1411-b2`. Det blir to forsendelser til
samme adresse fra samme bestilling.

Naar boekene kommer fra SAMME ordre er det ingen tvil om at de skal til samme
kunde. Derfor slaas de sammen automatisk, uten Telegram-spoersmaal - i
motsetning til to separate WooCommerce-ordre, som `gelato_merge.py` fortsatt
spoer om foerst.

Noden settes MELLOM "Record Gelato Draft" og "Suppress Telegram?":

    Record Gelato Draft -> Auto Merge Multibook -> Suppress Telegram?

Den kjoerer en gang per bok. De foerste ser at ordren ikke er komplett og
gjoer ingenting; den siste finner soesknene og slaar sammen. Enkeltbok-ordre
(book_count < 2) gaar rett gjennom.

Scriptet er fail-soft: alltid gyldig JSON, alltid exit 0. En betalt ordre
stopper aldri fordi sammenslaaingen feilet - verste utfall er to pakker,
noeyaktig som foer.

  python patch_worker_auto_merge.py --dry-run
  python patch_worker_auto_merge.py --apply
  python patch_worker_auto_merge.py --revert
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_worker_job_key import BACKUP_DIR, WF, load_api_key, req  # noqa: E402

NODE = "Auto Merge Multibook"
AFTER = "Record Gelato Draft"
BEFORE = "Suppress Telegram?"

PY = "C:/Users/tobia/AppData/Local/Programs/Python/Python310/python.exe"
SCRIPT = "C:/ComfyUI/script/auto_merge_multibook.py"

# order_id er WooCommerce-ordren UTEN -bN. Edit Fields sin order_id er
# dirKey-en (job_key), saa den kan vi ikke bruke her - vi leser raa payload.
COMMAND = (
    '={{ (() => {'
    ' const j = $node["Parse Job"].json || {};'
    ' const count = Number(j.book_count || 1);'
    ' if (!(count > 1)) return \'cmd /c echo {"merged":false,'
    '"reason":"enkeltbok - hopper over"}\';'
    ' const order = String(j.order_id || "").trim();'
    ' if (!order) return \'cmd /c echo {"merged":false,'
    '"reason":"mangler order_id"}\';'
    ' return \'' + PY + ' "' + SCRIPT + '"'
    ' --order-id "\' + order + \'" --book-count \' + count;'
    ' })() }}'
)


def find(nodes, name):
    return next((n for n in nodes if n.get("name") == name), None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--revert", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run or args.revert):
        ap.error("velg --dry-run, --apply eller --revert")

    key = load_api_key()
    wf = req("GET", "/workflows/" + WF, key=key)
    nodes, conns = wf["nodes"], wf["connections"]
    print("workflow  %s (aktiv: %s)" % (wf["name"], wf.get("active")))

    exists = find(nodes, NODE) is not None

    if args.revert:
        if not exists:
            print("noden finnes ikke - ingenting aa gjoere")
            return 0
        wf["nodes"] = [n for n in nodes if n.get("name") != NODE]
        conns.pop(NODE, None)
        conns[AFTER] = {"main": [[{"node": BEFORE, "type": "main", "index": 0}]]}
        print("fjerner %s og kobler %s -> %s" % (NODE, AFTER, BEFORE))
    else:
        if exists:
            print("noden finnes allerede - ingenting aa gjoere")
            return 0
        anchor = find(nodes, AFTER)
        if anchor is None:
            raise SystemExit("fant ingen node som heter %r" % AFTER)
        pos = anchor.get("position") or [2080, 470]
        wf["nodes"].append({
            "parameters": {"command": COMMAND},
            "name": NODE,
            "type": "n8n-nodes-base.executeCommand",
            "typeVersion": 1,
            "position": [pos[0] + 180, pos[1] + 140],
            # En feilet sammenslaaing skal aldri stoppe en betalt ordre.
            "onError": "continueRegularOutput",
            "id": "a17ee0c3-9b52-4d21-8f0a-6ab21c4d0e77",
        })
        conns[AFTER] = {"main": [[{"node": NODE, "type": "main", "index": 0}]]}
        conns[NODE] = {"main": [[{"node": BEFORE, "type": "main", "index": 0}]]}
        print("setter inn %s mellom %s og %s" % (NODE, AFTER, BEFORE))

    if args.dry_run:
        print("\nkommando:\n  %s" % COMMAND)
        print("\nTORRKJORING - ingenting endret")
        return 0

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(BACKUP_DIR, "backup-main-before-automerge-%s.json" % stamp)
    with open(backup, "w", encoding="utf-8") as fh:
        json.dump(req("GET", "/workflows/" + WF, key=key), fh,
                  ensure_ascii=False, indent=1)
    print("backup    %s" % backup)

    # n8n sitt API godtar bare disse fire feltene paa PUT - alt annet gir 400.
    req("PUT", "/workflows/" + WF, {
        "name": wf["name"], "nodes": wf["nodes"],
        "connections": conns, "settings": wf.get("settings", {}),
    }, key=key)
    print("workflow oppdatert")

    if wf.get("active"):
        req("POST", "/workflows/%s/activate" % WF, {}, key=key)
        print("workflow reaktivert")

    check = req("GET", "/workflows/" + WF, key=key)
    has = find(check["nodes"], NODE) is not None
    wired = check["connections"].get(AFTER, {}).get("main", [[{}]])[0]
    target = wired[0].get("node") if wired else None
    ok = (not has and target == BEFORE) if args.revert else (has and target == NODE)
    print("kontroll  %s (node: %s, %s -> %s)"
          % ("OK" if ok else "FEIL - se over manuelt", has, AFTER, target))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""Skru av den automatiske ordre-sammenslaaingen i n8n-workeren.

Sammenslaaingen styres na fra Telegram-boten i stedet (dp_bot "Sla sammen
ordre"). Den gamle losningen gjorde tre ting vi ikke vil ha lenger:

  * den lette etter kandidater ved HVER betalte ordre, utenfor boten
  * den long-pollet getUpdates paa produksjonsbot-tokenet i inntil 20 min
  * den spurte i gruppa der alle ordre lander

Denne patchen fjerner Merge Gate Input / Merge Gate / Parse Merge Decision,
setter items i "Create Gelato Draft" tilbake til original, og erstatter
"Record Gelato Draft" med en STILLE Code-node som bare skriver kvitteringsfila
state/gelato_drafts/<ordre>.json.

Kvitteringen beholdes med vilje: reprint_order.known_draft_ids() og
sammenslaaingen i boten bruker den til aa finne det gamle utkastet, og
Gelato sitt orders:search har returnert tomt for utkast som fantes.

  python patch_worker_merge_off.py --dry-run
  python patch_worker_merge_off.py --apply
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime

DB = r"C:\Users\tobia\.n8n\database.sqlite"
WF = "xy8qiRUzcBpH52CI"

GATE_NODES = ["Merge Gate Input", "Merge Gate", "Parse Merge Decision"]
RECORD = "Record Gelato Draft"

ITEMS_OLD = "\n  }]\n})"
ITEMS_NEW = "\n  }].concat($node[\"Parse Merge Decision\"].json.extraItems || [])\n})"

RECORD_JS = r"""
// Skriver kvittering for utkastet. Ingen Telegram, ingen kandidatsok, ingen
// venting - bare en fil paa disk som boten kan slaa opp i senere.
const fs = require('fs');
const d = $node['All Pages Done'].json || {};
const draftId = ($json && $json.id) || '';
const dir = 'C:/ComfyUI/state/gelato_drafts';

try {
  if (draftId) {
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(dir + '/' + String(d.order_id) + '.json', JSON.stringify({
      order_id:   String(d.order_id || ''),
      draft_id:   draftId,
      status:     'open',
      email:      String((d.customer || {}).email || '').trim().toLowerCase(),
      book_slug:  d.book_slug || '',
      child_name: d.child_name || '',
      cover_type: d.cover_type || 'hardcover',
      created_at: new Date().toISOString(),
      merged_orders: [String(d.order_id || '')],
      source: 'n8n Record Gelato Draft'
    }, null, 1), 'utf8');
  }
} catch (e) {
  // En kvittering som ikke lot seg skrive skal aldri stoppe en betalt ordre.
  console.warn('Record Gelato Draft: ' + e.message);
}

return { json: $json };
""".strip()


def one(conns, src, dst):
    conns[src] = {"main": [[{"node": dst, "type": "main", "index": 0}]]}


def patch(nodes, conns, changed):
    draft = next((n for n in nodes if n["name"] == "Create Gelato Draft"), None)
    if draft is None:
        raise SystemExit("fant ingen node 'Create Gelato Draft'")
    body = draft["parameters"].get("jsonBody", "")
    if ITEMS_NEW in body:
        draft["parameters"]["jsonBody"] = body.replace(ITEMS_NEW, ITEMS_OLD)
        changed.append("Create Gelato Draft: items tilbake til original (uten extraItems)")

    for node in list(nodes):
        if node["name"] in GATE_NODES:
            nodes.remove(node)
            conns.pop(node["name"], None)
            changed.append(f"fjernet node {node['name']}")

    record = next((n for n in nodes if n["name"] == RECORD), None)
    if record is None:
        record = {"id": "merge-record", "name": RECORD,
                  "type": "n8n-nodes-base.code", "typeVersion": 2,
                  "position": [2080, 470], "onError": "continueRegularOutput"}
        nodes.append(record)
        changed.append(f"la til node {RECORD}")
    record["type"] = "n8n-nodes-base.code"
    record["typeVersion"] = 2
    record["onError"] = "continueRegularOutput"
    record["parameters"] = {"mode": "runOnceForEachItem", "jsCode": RECORD_JS}
    record.pop("alwaysOutputData", None)
    changed.append(f"{RECORD}: erstattet med stille Code-node (skriver bare kvittering)")

    one(conns, "Make Gelato PDF Public", "Create Gelato Draft")
    one(conns, "Create Gelato Draft", RECORD)
    one(conns, RECORD, "Suppress Telegram?")
    changed.append("koblet om: Make Gelato PDF Public -> Create Gelato Draft "
                   f"-> {RECORD} -> Suppress Telegram?")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    db = sqlite3.connect(DB)
    row = db.execute("select nodes, connections from workflow_entity where id=?",
                     (WF,)).fetchone()
    if not row:
        raise SystemExit(f"fant ingen workflow {WF}")
    nodes = json.loads(row[0])
    conns = json.loads(row[1])

    changed = []
    patch(nodes, conns, changed)
    for line in changed or ["ingenting aa endre"]:
        print("  " + line)

    if not args.apply:
        print("TORRKJORING - databasen er urort")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = f"{DB}.backup-mergeoff-{stamp}"
    shutil.copy(DB, backup)
    print(f"  sikkerhetskopi -> {backup}")
    db.execute("update workflow_entity set nodes=?, connections=?, updatedAt=? where id=?",
               (json.dumps(nodes, ensure_ascii=False),
                json.dumps(conns, ensure_ascii=False),
                datetime.utcnow().isoformat(sep=" ", timespec="milliseconds"), WF))
    db.commit()
    print("SKREVET - deaktiver og aktiver workflowen i n8n for at den skal lastes paa nytt")
    return 0


if __name__ == "__main__":
    sys.exit(main())

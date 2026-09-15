# -*- coding: utf-8 -*-
"""Kobler ordre-samling inn i Dreampage Worker v2.

Legger fire noder mellom "Make Gelato PDF Public" og "Suppress Telegram?":

  Make Gelato PDF Public
    -> Merge Gate Input      (skriver .merge_request.json)
    -> Merge Gate            (python gelato_merge.py gate - spor paa Telegram)
    -> Parse Merge Decision  (tolker svaret, feiler aldri)
    -> Create Gelato Draft   (uendret, bortsett fra at items utvides)
    -> Record Gelato Draft   (python gelato_merge.py record)
    -> Suppress Telegram?    (og alt nedstroms uendret)

Alt nedstroms bruker absolutte nodereferanser ($node[...]), ikke $json, saa
innsettingen endrer ingen eksisterende uttrykk. Eneste endring i en
eksisterende node er items-arrayen i Create Gelato Draft, som utvides med
.concat(...) - tom liste gir noyaktig dagens oppforsel.

  python patch_worker_merge_orders.py --dry-run
  python patch_worker_merge_orders.py --apply
  python patch_worker_merge_orders.py --revert
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime

DB = "C:/Users/tobia/.n8n/database.sqlite"
WF = "xy8qiRUzcBpH52CI"

HARDCOVER = ("photobooks-hardcover_pf_200x200-mm-8x8-inch_pt_170-gsm-65lb-coated-silk"
             "_cl_4-4_ccl_4-4_bt_glued-left_ct_matt-lamination_prt_1-0"
             "_cpt_130-gsm-65-lb-cover-coated-silk_ver")
SOFTCOVER = ("photobooks-softcover_pf_200x200-mm-8x8-inch_pt_170-gsm-65lb-coated-silk"
             "_cl_4-4_ccl_4-4_bt_glued-left_ct_matt-lamination_prt_1-0"
             "_cpt_250-gsm-100-lb-cover-coated-silk_ver")

NEW_NODES = ["Merge Gate Input", "Merge Gate", "Parse Merge Decision", "Record Gelato Draft"]

ITEMS_OLD = "\n  }]\n})"
ITEMS_NEW = "\n  }].concat($node[\"Parse Merge Decision\"].json.extraItems || [])\n})"

GATE_INPUT_JS = """
// Skriver forespoerselsfila som gelato_merge.py leser. Alt gaar via fil for aa
// slippe sitat-helvete med norske tegn paa Windows-kommandolinja.
const fs = require('fs');
const path = require('path');

const d = $node['All Pages Done'].json || {};
const up = $node['Upload Gelato PDF'].json || {};
const fileUrl = up.webContentLink ||
  ('https://drive.google.com/uc?id=' + up.id + '&export=download');
const productUid = (d.cover_type === 'softcover') ? __SOFT__ : __HARD__;
const dir = d.orderPath || ('C:/ComfyUI/books/' + d.book_slug + '/orders/' + d.order_id);
const reqPath = dir + '/.merge_request.json';

try {
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(reqPath, JSON.stringify({
    order_id:    String(d.order_id || ''),
    book_slug:   d.book_slug || '',
    book_title:  d.book_title || '',
    child_name:  d.child_name || '',
    cover_type:  d.cover_type || 'hardcover',
    product_uid: productUid,
    file_url:    fileUrl,
    drive_file_id: up.id || '',
    customer:    d.customer || {},
    shipping:    d.shipping || {},
    created_at:  new Date().toISOString(),
  }, null, 1), 'utf8');
} catch (e) {
  // Uten forespoerselsfil svarer gate-kommandoen bare "ingen sammenslaaing".
  console.warn('Merge Gate Input: ' + e.message);
}

return { json: Object.assign({}, $json, { mergeRequestPath: reqPath }) };
""".replace("__SOFT__", json.dumps(SOFTCOVER)).replace("__HARD__", json.dumps(HARDCOVER)).strip()

PARSE_JS = """
// Tolker stdout fra gelato_merge.py. Denne noden skal aldri kaste - uansett
// hva som kom tilbake ender vi i verste fall paa "vanlig enkelt utkast".
const MARK = 'DPMERGE_JSON';
let merge = false, extraItems = [], partner = null, reason = 'ingen utdata fra Merge Gate';

try {
  const raw = String(($json && $json.stdout) || '');
  const lines = raw.split(/\\r?\\n/).filter(function (l) { return l.indexOf(MARK) === 0; });
  if (lines.length) {
    const p = JSON.parse(lines[lines.length - 1].slice(MARK.length + 1));
    merge = p.merge === true;
    extraItems = Array.isArray(p.extraItems) ? p.extraItems : [];
    partner = p.partner || null;
    reason = p.reason || '';
  }
} catch (e) {
  reason = 'kunne ikke tolke svaret: ' + e.message;
}

// Godkjent uten items ville laget en identisk ordre til ingen nytte.
if (merge && extraItems.length === 0) {
  merge = false;
  reason = 'godkjent, men ingen items aa legge til';
}
for (const it of extraItems) {
  if (!it || !it.itemReferenceId || !it.productUid || !it.files || !it.files.length) {
    merge = false; extraItems = []; partner = null;
    reason = 'ufullstendig item fra Merge Gate - hopper over sammenslaaing';
    break;
  }
}

console.log('[MERGE] ' + (merge ? 'slaas sammen (+' + extraItems.length + ' item)' : 'nei') +
            ' - ' + reason);

return { json: {
  merge: merge,
  extraItems: extraItems,
  partner: partner,
  mergeReason: reason,
  mergeRequestPath: ($node['Merge Gate Input'].json || {}).mergeRequestPath || '',
} };
""".strip()

GATE_CMD = ("={{ 'python \"C:/ComfyUI/script/gelato_merge.py\" gate --request \"'"
            " + $json.mergeRequestPath + '\"' }}")
RECORD_CMD = ("={{ 'python \"C:/ComfyUI/script/gelato_merge.py\" record --request \"'"
              " + $node[\"Parse Merge Decision\"].json.mergeRequestPath"
              " + '\" --draft-id \"' + ($json.id || '') + '\"' }}")


def build_nodes():
    return [
        {"parameters": {"mode": "runOnceForEachItem", "jsCode": GATE_INPUT_JS},
         "id": "merge-gate-input", "name": "Merge Gate Input",
         "type": "n8n-nodes-base.code", "typeVersion": 2,
         "position": [1760, 800], "onError": "continueRegularOutput"},
        {"parameters": {"command": GATE_CMD},
         "id": "merge-gate", "name": "Merge Gate",
         "type": "n8n-nodes-base.executeCommand", "typeVersion": 1,
         "position": [1900, 800], "onError": "continueRegularOutput",
         "alwaysOutputData": True},
        {"parameters": {"mode": "runOnceForEachItem", "jsCode": PARSE_JS},
         "id": "merge-parse", "name": "Parse Merge Decision",
         "type": "n8n-nodes-base.code", "typeVersion": 2,
         "position": [2040, 800], "onError": "continueRegularOutput"},
        {"parameters": {"command": RECORD_CMD},
         "id": "merge-record", "name": "Record Gelato Draft",
         "type": "n8n-nodes-base.executeCommand", "typeVersion": 1,
         "position": [2080, 470], "onError": "continueRegularOutput",
         "alwaysOutputData": True},
    ]


def one(conns, src, dst):
    conns[src] = {"main": [[{"node": dst, "type": "main", "index": 0}]]}


def apply_patch(nodes, conns, changed):
    names = {n["name"] for n in nodes}
    for n in build_nodes():
        if n["name"] in names:
            changed.append(f"noden {n['name']} finnes allerede - hopper over")
            continue
        nodes.append(n)
        changed.append(f"la til node {n['name']}")

    draft = next(n for n in nodes if n["name"] == "Create Gelato Draft")
    body = draft["parameters"]["jsonBody"]
    if "Parse Merge Decision" in body:
        changed.append("Create Gelato Draft er allerede utvidet")
    else:
        if body.count(ITEMS_OLD) != 1:
            raise SystemExit("fant ikke items-arrayen entydig i Create Gelato Draft - "
                             "avbryter i stedet for aa gjette")
        draft["parameters"]["jsonBody"] = body.replace(ITEMS_OLD, ITEMS_NEW)
        changed.append("Create Gelato Draft: items utvides med extraItems")

    one(conns, "Make Gelato PDF Public", "Merge Gate Input")
    one(conns, "Merge Gate Input", "Merge Gate")
    one(conns, "Merge Gate", "Parse Merge Decision")
    one(conns, "Parse Merge Decision", "Create Gelato Draft")
    one(conns, "Create Gelato Draft", "Record Gelato Draft")
    one(conns, "Record Gelato Draft", "Suppress Telegram?")
    changed.append("koblet om: Make Gelato PDF Public -> ... -> Suppress Telegram?")


def revert_patch(nodes, conns, changed):
    draft = next(n for n in nodes if n["name"] == "Create Gelato Draft")
    body = draft["parameters"]["jsonBody"]
    if ITEMS_NEW in body:
        draft["parameters"]["jsonBody"] = body.replace(ITEMS_NEW, ITEMS_OLD)
        changed.append("Create Gelato Draft: items tilbake til original")

    for n in list(nodes):
        if n["name"] in NEW_NODES:
            nodes.remove(n)
            conns.pop(n["name"], None)
            changed.append(f"fjernet node {n['name']}")

    one(conns, "Make Gelato PDF Public", "Create Gelato Draft")
    one(conns, "Create Gelato Draft", "Suppress Telegram?")
    changed.append("koblet tilbake: Make Gelato PDF Public -> Create Gelato Draft "
                   "-> Suppress Telegram?")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run or args.revert):
        ap.error("velg --dry-run, --apply eller --revert")

    db = sqlite3.connect(DB)
    row = db.execute("select nodes, connections from workflow_entity where id=?",
                     (WF,)).fetchone()
    if not row:
        raise SystemExit(f"fant ingen workflow {WF}")
    nodes = json.loads(row[0])
    conns = json.loads(row[1])

    changed = []
    (revert_patch if args.revert else apply_patch)(nodes, conns, changed)

    for line in changed or ["ingenting aa endre"]:
        print("  " + line)

    if not (args.apply or args.revert):
        print("TORRKJORING - databasen er urort")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    tag = "revert" if args.revert else "merge"
    shutil.copy(DB, f"{DB}.backup-{tag}-{stamp}")
    print(f"  sikkerhetskopi -> {DB}.backup-{tag}-{stamp}")
    db.execute("update workflow_entity set nodes=?, connections=?, updatedAt=? where id=?",
               (json.dumps(nodes, ensure_ascii=False),
                json.dumps(conns, ensure_ascii=False),
                datetime.utcnow().isoformat(sep=" ", timespec="milliseconds"), WF))
    db.commit()
    print("SKREVET - workflowen maa deaktiveres og aktiveres paa nytt i n8n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

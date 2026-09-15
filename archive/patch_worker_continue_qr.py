"""Patch Dreampage Worker v2 med "Fortsett eventyret"-QR på siste side.

Endringene er additive og slår seg selv av når `continue_code` mangler, slik at
ordre uten feltet produseres nøyaktig som i dag.

  1. Edit Fields / Load Book Config / Parse Config / All Pages Done
     bærer de sju nye valgfrie feltene videre.
  2. Pages Config legger til ett ekstra element `page99_next` som arver hele
     Page Loop-maskineriet (dispatch, polling, timeout, retry).
  3. Fire nye executeCommand-noder mellom Prepare Pages og Count Innersider
     Pages bygger forsiden, laster den opp, bygger siste side og stempler en
     vektor-QR i innersider-PDF-en.

Bruk:
  python patch_worker_continue_qr.py --dry-run     # skriv patchet JSON, rør ikke DB
  python patch_worker_continue_qr.py --apply       # skriv til n8n-databasen
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

DB = r"C:\Users\tobia\.n8n\database.sqlite"
WF_ID = "xy8qiRUzcBpH52CI"
SECRET = "<CONTINUE_CALLBACK_SECRET>"

CONTINUE_FIELDS = [
    "continue_code", "continue_url", "continue_coupon", "continue_callback",
    "next_book_id", "next_book_slug", "next_book_title",
]

# ----------------------------------------------------------------- Edit Fields
EDIT_FIELD_EXPR = {
    "continue_code":     "={{ $node[\"Parse Job\"].json.continue_code || \"\" }}",
    "continue_url":      "={{ $node[\"Parse Job\"].json.continue_url || \"\" }}",
    "continue_coupon":   "={{ $node[\"Parse Job\"].json.continue_coupon || \"\" }}",
    "continue_callback": "={{ $node[\"Parse Job\"].json.continue_callback || \"\" }}",
    "next_book_id":      "={{ $node[\"Parse Job\"].json.next_book_id || ($node[\"Parse Job\"].json.next_book || {}).id || \"\" }}",
    "next_book_slug":    "={{ $node[\"Parse Job\"].json.next_book_slug || ($node[\"Parse Job\"].json.next_book || {}).slug || \"\" }}",
    "next_book_title":   "={{ $node[\"Parse Job\"].json.next_book_title || ($node[\"Parse Job\"].json.next_book || {}).title || \"\" }}",
}

PASSTHROUGH_JS = "".join(
    "  %s: ef.%s || '',\n" % (f, f) for f in CONTINUE_FIELDS
)

PAGES_CONFIG_EXTRA = r"""
// --- Fortsett eventyret: ekstra render av neste bok sin forside ---------------
// Ett ekstra element i Pages Config arver hele Page Loop-maskineriet
// (dispatch, polling, timeout, retry). Uten continue_code skjer ingenting.
const contCode = String(inp.continue_code || '').trim();
const nextSlug = String(inp.next_book_slug || '').trim();
if (contCode && nextSlug && nextSlug !== String(inp.book_slug || '')) {
  try {
    const fs = require('fs');
    const nextCfgPath = 'C:/ComfyUI/books/' + nextSlug + '/config.json';
    const nextCfg = JSON.parse(fs.readFileSync(nextCfgPath, 'utf8').replace(/^\uFEFF/, ''));
    const front = (nextCfg.pages || []).find(function (p) { return p.page_key === 'page00'; });
    if (!front) throw new Error('next book config mangler page00');
    const base = items[0] ? items[0].json : {};
    items.push({ json: Object.assign({}, base, {
      page_key:          'page99_next',
      template_image:    front.template_image,
      mask_image:        front.mask_image,
      workflow_role:     'frontpage',
      workflow_api_file: (nextCfg.workflowApis && nextCfg.workflowApis.frontpage) ||
                         nextCfg.workflowApi || workflowFile,
      patchNodes:        nextCfg.patchNodes || nextCfg.innerPatchNodes || patchNodes,
    })});
    console.log('[CONTINUE] page99_next lagt til fra ' + nextSlug + ' (' + front.template_image + ')');
  } catch (error) {
    // Et oppsalg skal aldri blokkere en betalt ordre.
    console.warn('[CONTINUE] hopper over neste-forside for ' + nextSlug + ': ' + error.message);
  }
}
"""


# No-op-kommandoen må være helt uten fnutter, så den kan ligge inne i en
# JS-streng uten escaping.
SKIP_CMD = 'cmd /c echo continue-av: ingen continue_code - siste side som i dag'

# Felles JS-prolog i n8n-uttrykket. Hele kommandoen bygges inne i ETT {{ }}-blokk,
# fordi nøstede {{ }} inne i en streng ikke blir evaluert av n8n.
CMD_PROLOG = (
    'const d = $node["All Pages Done"].json; '
    "if (!d.continue_code) return '" + SKIP_CMD + "'; "
    'const PY = \'python "C:/ComfyUI/script/build_last_page.py" \'; '
    "const titled = d.orderPath + '/pdf/page99_next.png'; "
    "const comfy = 'C:/ComfyUI/output/' + d.config.comfyOutputPrefix + '/' + d.order_id + '/comfy'; "
)


def cmd(body: str) -> str:
    """Pakk en JS-kropp som returnerer kommandostrengen inn i ett n8n-uttrykk."""
    return "={{ (() => { " + CMD_PROLOG + body + " })() }}"


def build_new_nodes():
    specs = [
        ("Build Next Cover Title",
         'return PY + \'cover'
         ' --raw "\' + comfy + \'"'
         ' --next-slug "\' + d.next_book_slug + \'"'
         ' --child-name "\' + d.child_name + \'"'
         ' --lang "\' + (d.script_language || \'nb\') + \'"'
         ' --out "\' + titled + \'"\';'),

        ("Upload Continue Cover",
         "if (!d.continue_callback) return '" + SKIP_CMD + "'; "
         'return PY + \'upload'
         ' --file "\' + titled + \'"'
         ' --callback "\' + d.continue_callback + \'"'
         ' --secret "' + SECRET + '"\';'),

        ("Build Last Page",
         'return PY + \'image'
         ' --next-cover "\' + titled + \'"'
         ' --child-name "\' + d.child_name + \'"'
         ' --next-title "\' + (d.next_book_title || \'\') + \'"'
         ' --qr-url "\' + d.continue_url + \'"'
         ' --coupon "\' + (d.continue_coupon || \'\') + \'"'
         ' --lang "\' + (d.script_language || \'nb\') + \'"'
         ' --out "\' + d.orderPath + \'/input/blank-back.png"\';'),

        ("Stamp QR On Innersider",
         'return PY + \'stamp'
         ' --pdf "\' + d.orderPath + \'/pdf/\' + d.child_name + \'_innersider.pdf"'
         ' --qr-url "\' + d.continue_url + \'"\';'),
    ]

    out = []
    for i, (name, body) in enumerate(specs):
        out.append({
            "parameters": {"command": cmd(body)},
            "id": "continue-qr-%d" % i,
            "name": name,
            "type": "n8n-nodes-base.executeCommand",
            "typeVersion": 1,
            "position": [-1180 + i * 220, 1180],
            # Et oppsalg skal aldri blokkere en betalt ordre.
            "onError": "continueRegularOutput",
        })
    return out


def patch(nodes, connections):
    by_name = {n["name"]: n for n in nodes}
    changed = []

    # 1) Edit Fields --------------------------------------------------------
    ef = by_name["Edit Fields"]["parameters"]["assignments"]["assignments"]
    existing = {a["name"] for a in ef}
    for field, expr in EDIT_FIELD_EXPR.items():
        if field not in existing:
            ef.append({"id": "cont-" + field, "name": field, "value": expr, "type": "string"})
            changed.append("Edit Fields += " + field)

    # 2) Load Book Config / Parse Config / All Pages Done --------------------
    lbc = by_name["Load Book Config"]["parameters"]
    if "continue_code" not in lbc["jsCode"]:
        anchor = "  script_language: scriptLanguage,\n"
        assert anchor in lbc["jsCode"], "Load Book Config: fant ikke anker"
        lbc["jsCode"] = lbc["jsCode"].replace(anchor, anchor + PASSTHROUGH_JS, 1)
        changed.append("Load Book Config passthrough")

    pc = by_name["Parse Config"]["parameters"]
    if "continue_code" not in pc["jsCode"]:
        anchor = "  script_language: scriptLanguage,\n"
        assert anchor in pc["jsCode"], "Parse Config: fant ikke anker"
        pc["jsCode"] = pc["jsCode"].replace(anchor, anchor + PASSTHROUGH_JS, 1)
        changed.append("Parse Config passthrough")

    apd = by_name["All Pages Done"]["parameters"]
    if "continue_code" not in apd["jsCode"]:
        anchor = "  orderPath: src.orderPath || '',\n"
        assert anchor in apd["jsCode"], "All Pages Done: fant ikke anker"
        extra = "".join("  %s: src.%s || '',\n" % (f, f) for f in CONTINUE_FIELDS)
        apd["jsCode"] = apd["jsCode"].replace(anchor, anchor + extra, 1)
        changed.append("All Pages Done passthrough")

    # 3) Pages Config -------------------------------------------------------
    pgc = by_name["Pages Config"]["parameters"]
    if "page99_next" not in pgc["jsCode"]:
        old_return = "return config.pages.map(function(p) {"
        assert old_return in pgc["jsCode"], "Pages Config: fant ikke anker"
        code = pgc["jsCode"].replace(old_return, "const items = config.pages.map(function(p) {", 1)
        code = code.rstrip()
        assert code.endswith("});"), "Pages Config: uventet slutt"
        code = code + "\n" + PAGES_CONFIG_EXTRA + "\nreturn items;\n"
        pgc["jsCode"] = code
        changed.append("Pages Config += page99_next")

    # 4) Nye noder + rekabling ---------------------------------------------
    if "Build Last Page" not in by_name:
        nodes.extend(build_new_nodes())
        changed.append("4 nye executeCommand-noder")

    def set_main(src, targets):
        connections[src] = {"main": [[{"node": t, "type": "main", "index": 0} for t in targets]]}

    if connections.get("Prepare Pages", {}).get("main", [[]])[0][0]["node"] != "Build Next Cover Title":
        set_main("Prepare Pages", ["Build Next Cover Title"])
        set_main("Build Next Cover Title", ["Upload Continue Cover"])
        set_main("Upload Continue Cover", ["Build Last Page"])
        set_main("Build Last Page", ["Run Text Script"])
        set_main("Run Text Script", ["Stamp QR On Innersider"])
        set_main("Stamp QR On Innersider", ["Count Innersider Pages"])
        changed.append("rekablet Prepare Pages -> ... -> Count Innersider Pages")

    return changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                  "worker-continue-qr.patched.json"))
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    con = sqlite3.connect(DB)
    raw_nodes, raw_conns = con.execute(
        "select nodes, connections from workflow_entity where id=?", (WF_ID,)).fetchone()
    nodes = json.loads(raw_nodes)
    connections = json.loads(raw_conns)

    changed = patch(nodes, connections)
    for c in changed:
        print("  +", c)
    if not changed:
        print("  (ingen endringer - allerede patchet)")

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"nodes": nodes, "connections": connections}, fh, ensure_ascii=False, indent=1)
    print("Patchet JSON:", args.out)

    if args.apply:
        con.execute("update workflow_entity set nodes=?, connections=?, updatedAt=datetime('now') "
                    "where id=?",
                    (json.dumps(nodes, ensure_ascii=False),
                     json.dumps(connections, ensure_ascii=False), WF_ID))
        con.commit()
        print("Skrevet til n8n-databasen. n8n må restartes for å laste den nye versjonen.")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

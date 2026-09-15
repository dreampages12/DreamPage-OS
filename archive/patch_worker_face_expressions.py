# -*- coding: utf-8 -*-
"""
Kobler uttrykksvariantene inn i n8n-workeren "Dreampage Worker v2".

Tre endringer, alle idempotente:

 1. Node "Build Face Variants" (executeCommand) mellom "Save Child Image" og
    "Edit Fields". Kjorer build_face_variants.py en gang per ordre, FOR
    sideloopen. AI-en ser paa bildet, velger verktoy fra workflows/tools.json
    og planen utfores.
    onError=continueRegularOutput sa en feil aldri stopper en betalt ordre.

 2. "Pages Config" slar opp riktig variantfil per side ut fra sidens
    `face_expression` (noytral | smil), med fallback til originalbildet.

 3. Sidespor "Photo Warning": ser scriptet at bildet er lite egnet (mat i
    munnen, haand foran ansiktet, flere barn ...), sendes en Telegram-melding
    sa du kan be om nytt bilde FOR boka trykkes. Sidesporet henger paa samme
    utgang som Edit Fields og kan derfor ikke forsinke ordren.

Bruk:  python patch_worker_face_expressions.py [--apply]
"""
import argparse
import io
import json
import os
import time
import urllib.request

# JWT-en laa hardkodet her. Naa i config/secrets.json, som staar i .gitignore -
# en API-noekkel i git-historikk maa roteres, ikke slettes. Dette scriptet doer
# uansett sammen med n8n.
def _n8n_api_key() -> str:
    import json as _json
    if os.environ.get("DP_N8N_API_KEY"):
        return os.environ["DP_N8N_API_KEY"]
    here = os.path.dirname(os.path.abspath(__file__))
    while True:                              # gaa opp til vi finner config/secrets.json
        candidate = os.path.join(here, "config", "secrets.json")
        if os.path.isfile(candidate):
            with open(candidate, encoding="utf-8-sig") as fh:
                return _json.load(fh).get("n8n_api_key", "")
        parent = os.path.dirname(here)
        if parent == here:
            raise SystemExit("fant ingen config/secrets.json med n8n_api_key")
        here = parent


API = _n8n_api_key()
BASE = "http://localhost:5678/api/v1"
WF = "xy8qiRUzcBpH52CI"

PYTHON = "C:/Users/tobia/AppData/Local/Programs/Python/Python310/python.exe"
SCRIPT = "C:/ComfyUI/script/face_variants/build_face_variants.py"
NODE_BUILD = "Build Face Variants"
NODE_WARN = "Photo Warning"

TELEGRAM_BOT = os.environ.get("DP_WORKER_BOT_TOKEN", "")  # var hardkodet; se config/secrets.json
TELEGRAM_CHAT = -5054483911

HELPER = """
// --- Uttrykksvarianter av barnebildet ----------------------------------------
// build_face_variants.py har lagt <order_id>-<uttrykk>.jpg i C:/ComfyUI/input.
// Mangler filen (scriptet feilet, eller en gammel ordre kjores om), brukes
// originalbildet - en side skal aldri feile fordi et uttrykk mangler.
const fsExpr = require('fs');
const FACE_EXPRESSIONS = ['noytral', 'smil'];
const faceBase = String(inp.faceFilename || '');
const faceStem = faceBase.replace(/\\.[^.]+$/, '');
function faceFor(expression) {
  const expr = String(expression || 'noytral');
  if (!faceStem || FACE_EXPRESSIONS.indexOf(expr) === -1) return faceBase;
  const candidate = faceStem + '-' + expr + '.jpg';
  try {
    if (fsExpr.existsSync('C:/ComfyUI/input/' + candidate)) return candidate;
  } catch (error) {}
  console.warn('[FACE] mangler ' + candidate + ' - bruker ' + faceBase);
  return faceBase;
}

"""

WARN_CODE = """// Varsler paa Telegram hvis barnebildet er flagget som lite egnet.
// Rent sidespor - hovedflyten gaar videre via Edit Fields uansett hva som
// skjer her, derfor er alt pakket i try/catch.
const https = require('https');
const out = String(($json && $json.stdout) || '');
const hits = out.split('\\n').filter(l => l.indexOf('ADVARSEL') !== -1 || l.indexOf('MERK:') !== -1);
if (!hits.length) return { json: { warned: false } };

const orderId = $node['Parse Job'].json.order_id;
const name = $node['Parse Job'].json.child_name || '';
const text = 'Barnebildet for ordre ' + orderId + ' (' + name + ') ser problematisk ut:\\n\\n'
  + hits.join('\\n')
  + '\\n\\nBoka lages likevel. Vil du ha et nytt bilde, gjor det for godkjenning.';

try {
  await new Promise((resolve) => {
    const body = JSON.stringify({ chat_id: %(chat)d, text: text });
    const req = https.request({
      hostname: 'api.telegram.org', path: '/bot%(bot)s/sendMessage',
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
      timeout: 15000,
    }, (res) => { res.on('data', () => {}); res.on('end', resolve); });
    req.on('error', resolve);
    req.on('timeout', () => { req.destroy(); resolve(); });
    req.write(body); req.end();
  });
} catch (error) {}
return { json: { warned: true, problems: hits } };
""" % {"chat": TELEGRAM_CHAT, "bot": TELEGRAM_BOT}


def req(method, path, payload=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    r = urllib.request.Request(BASE + path, body, method=method, headers={
        "X-N8N-API-KEY": API, "Accept": "application/json",
        "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=60))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-ai", action="store_true",
                    help="dropp AI-beslutningen (bare geometri)")
    args = ap.parse_args()

    wf = req("GET", "/workflows/" + WF)
    nodes, conns = wf["nodes"], wf["connections"]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = os.path.expanduser("~/.n8n/backup-main-before-faceexpr-%s.json" % stamp)
    io.open(backup, "w", encoding="utf-8").write(
        json.dumps(wf, ensure_ascii=False, indent=1))
    print("backup -> " + backup)

    by_name = {n["name"]: n for n in nodes}
    for required in ("Save Child Image", "Edit Fields", "Pages Config", "Parse Job"):
        if required not in by_name:
            raise SystemExit("fant ikke noden %r" % required)

    command = ('=' + PYTHON + ' "' + SCRIPT + '" '
               '{{ $node["Parse Job"].json.order_id }}'
               + ('' if args.no_ai else ' --ai'))

    # --- 1. byggenoden --------------------------------------------------------
    if NODE_BUILD in by_name:
        by_name[NODE_BUILD]["parameters"]["command"] = command
        by_name[NODE_BUILD]["onError"] = "continueRegularOutput"
        print("oppdaterte %r" % NODE_BUILD)
    else:
        nodes.append({
            "parameters": {"command": command},
            "type": "n8n-nodes-base.executeCommand", "typeVersion": 1,
            "position": [-760, 736], "id": "face-variants-node-0001",
            "name": NODE_BUILD, "onError": "continueRegularOutput"})
        conns["Save Child Image"] = {"main": [[
            {"node": NODE_BUILD, "type": "main", "index": 0}]]}
        print("la inn %r" % NODE_BUILD)

    # --- 3. varselsidesporet --------------------------------------------------
    if NODE_WARN not in by_name:
        nodes.append({
            "parameters": {"mode": "runOnceForAllItems", "jsCode": WARN_CODE},
            "type": "n8n-nodes-base.code", "typeVersion": 2,
            "position": [-760, 900], "id": "face-variants-warn-0001",
            "name": NODE_WARN, "onError": "continueRegularOutput"})
        print("la inn %r" % NODE_WARN)
    else:
        by_name[NODE_WARN]["parameters"]["jsCode"] = WARN_CODE
        print("oppdaterte %r" % NODE_WARN)

    conns[NODE_BUILD] = {"main": [[
        {"node": "Edit Fields", "type": "main", "index": 0},
        {"node": NODE_WARN, "type": "main", "index": 0}]]}

    # --- 2. Pages Config ------------------------------------------------------
    pc = by_name["Pages Config"]
    code = pc["parameters"]["jsCode"]
    if "faceFor(" in code:
        # allerede patchet - sorg bare for at uttrykkslista er den nye
        code = code.replace("['noytral', 'glad', 'trist']", "['noytral', 'smil']")
        pc["parameters"]["jsCode"] = code
        print("Pages Config: oppdaterte uttrykkslista")
    else:
        anchor = "const items = config.pages.map(function(p) {"
        if anchor not in code:
            raise SystemExit("fant ikke ankeret i Pages Config")
        code = code.replace(anchor, HELPER.lstrip("\n") + anchor, 1)

        old = "face_image:        inp.faceFilename,"
        if old not in code:
            raise SystemExit("fant ikke face_image-linja i Pages Config")
        code = code.replace(old, "face_image:        faceFor(p.face_expression),", 1)

        old_next = ("patchNodes:        nextCfg.patchNodes || "
                    "nextCfg.innerPatchNodes || patchNodes,")
        if old_next in code:
            code = code.replace(old_next,
                                "face_image:        faceFor(front.face_expression),\n      "
                                + old_next, 1)
        pc["parameters"]["jsCode"] = code
        print("Pages Config patchet")

    if not args.apply:
        print("\n(torrkjoring - kjor med --apply for a skrive og aktivere)")
        return

    req("PUT", "/workflows/" + WF, {
        "name": wf["name"], "nodes": nodes, "connections": conns,
        "settings": wf.get("settings", {})})
    req("POST", "/workflows/%s/activate" % WF)
    print("skrevet og aktivert")


if __name__ == "__main__":
    main()

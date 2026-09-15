# -*- coding: utf-8 -*-
"""
Kobler TRIST-varianten inn i n8n-workeren "Dreampage Worker v2".

To endringer, begge idempotente:

 1. Noden "Build Face Variants" pekes om til build_trist_variant.py og faar
    med seg book_slug. Den gamle kommandoen (build_face_variants.py --ai) har
    vaert DOD siden workflows/tools.json ble fjernet - den kastet
    FileNotFoundError paa hver eneste ordre, saa alle sider har i praksis
    brukt originalbildet. Noden beholder posisjon, koblinger og
    onError=continueRegularOutput.

 2. "Pages Config" faar 'trist' inn i FACE_EXPRESSIONS, slik at en side med
    face_expression:"trist" slaar opp <job_key>-trist.jpg. Mangler filen,
    brukes originalbildet som for.

I dag er det bare fotballstjernen side 04 som har face_expression:"trist", og
build_trist_variant.py generer kun for boker i sin egen BOOKS-liste.

Bruk:  python patch_worker_trist.py [--apply]
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
SCRIPT = "C:/ComfyUI/script/face_variants/build_trist_variant.py"

COMMAND = ("=%s \"%s\" "
           "{{ $node[\"Parse Job\"].json.job_key || $node[\"Parse Job\"].json.order_id }} "
           "--book {{ $node[\"Parse Job\"].json.book_slug || \"\" }}" % (PYTHON, SCRIPT))

OLD_LIST = "const FACE_EXPRESSIONS = ['noytral', 'smil'];"
NEW_LIST = "const FACE_EXPRESSIONS = ['noytral', 'smil', 'trist'];"


def call(method, path, payload=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(BASE + path, body, {
        "X-N8N-API-KEY": API, "Content-Type": "application/json"}, method=method)
    return json.load(urllib.request.urlopen(req, timeout=300))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    wf = call("GET", "/workflows/" + WF)
    nodes = {n["name"]: n for n in wf["nodes"]}
    changes = []

    build = nodes.get("Build Face Variants")
    if build is None:
        raise SystemExit("fant ikke noden 'Build Face Variants'")
    if build["parameters"].get("command") != COMMAND:
        changes.append("Build Face Variants -> build_trist_variant.py")
        if args.apply:
            build["parameters"]["command"] = COMMAND
            build["onError"] = "continueRegularOutput"

    pages = nodes.get("Pages Config")
    if pages is None:
        raise SystemExit("fant ikke noden 'Pages Config'")
    code = pages["parameters"].get("jsCode", "")
    if NEW_LIST not in code:
        if OLD_LIST not in code:
            raise SystemExit("fant ikke FACE_EXPRESSIONS-linja i Pages Config")
        changes.append("Pages Config -> FACE_EXPRESSIONS + 'trist'")
        if args.apply:
            pages["parameters"]["jsCode"] = code.replace(OLD_LIST, NEW_LIST)

    if not changes:
        print("ingenting aa gjore - workeren er allerede patchet")
        return 0

    for c in changes:
        print(("  ANVENDER " if args.apply else "  VILLE ENDRET ") + c)
    if not args.apply:
        print("\nkjor med --apply for aa skrive")
        return 0

    backup = os.path.expanduser(
        "~/.n8n/backup-main-before-trist-%s.json" % time.strftime("%Y%m%d-%H%M%S"))
    io.open(backup, "w", encoding="utf-8").write(
        json.dumps(wf, ensure_ascii=False, indent=1))
    print("backup: " + backup)

    call("PUT", "/workflows/" + WF, {
        "name": wf["name"], "nodes": wf["nodes"],
        "connections": wf["connections"], "settings": wf.get("settings", {})})
    print("skrevet (%d noder)" % len(wf["nodes"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

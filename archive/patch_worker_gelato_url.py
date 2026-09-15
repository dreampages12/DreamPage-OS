# -*- coding: utf-8 -*-
"""Fiks Drive-lenka i "Create Gelato Draft" i Dreampage Worker v2.

Noden ber Gelato hente PDF-en fra Drive, og bruker i dag:

    url: $node["Upload Gelato PDF"].json.webContentLink
         || ("https://drive.google.com/uc?id=" + ...id + "&export=download")

Begge grenene gir samme lenkeform - Drive-API-ets webContentLink ER
`drive.google.com/uc?...`. Over 100 MB svarer den med en HTML-side
("Google Drive - Virus scan warning") i stedet for fila. Gelato laster ned
2 kB HTML, item-et blir staaende med files[0].id = null og mimeType = null,
og utkastet ser helt riktig ut i API-svaret. Ingenting varsler om det.

Traff ordre 1300 (dinosaurenes-dal, 105,7 MB) 2026-08-22. Boka laa paa 73 MB
til malbildene ble byttet - alle andre boeker ligger paa 61-76 MB og har
ikke vaert i naerheten. Derfor har dette aldri slaatt til foer.

drive.usercontent.google.com/download?...&confirm=t hopper over varselet og
leverer fila uansett stoerrelse. webContentLink droppes helt: den er alltid
den daarlige formen, saa aa foretrekke den gir ingenting.

Samme rettelse er allerede gjort i drive_upload.py, finish_order.py,
reprint_order.py og finish_merged_order.py.

  python patch_worker_gelato_url.py --dry-run
  python patch_worker_gelato_url.py --apply
  python patch_worker_gelato_url.py --revert
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
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
NODE = "Create Gelato Draft"
BACKUP_DIR = r"C:\Users\tobia\.n8n"

OLD = ('url: $node["Upload Gelato PDF"].json.webContentLink '
       '|| ("https://drive.google.com/uc?id=" '
       '+ $node["Upload Gelato PDF"].json.id + "&export=download")')
NEW = ('url: "https://drive.usercontent.google.com/download?id=" '
       '+ $node["Upload Gelato PDF"].json.id + "&export=download&confirm=t"')


def load_api_key() -> str:
    return API


def req(method, path, payload=None, key=""):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    r = urllib.request.Request(BASE + path, body, method=method, headers={
        "X-N8N-API-KEY": key, "Accept": "application/json",
        "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=120))


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
    node = next((n for n in wf["nodes"] if n.get("name") == NODE), None)
    if node is None:
        raise SystemExit(f"fant ingen node som heter {NODE!r}")

    field = "jsonBody" if "jsonBody" in node["parameters"] else "body"
    body = node["parameters"][field]

    frm, to = (NEW, OLD) if args.revert else (OLD, NEW)
    if body.count(frm) != 1:
        if body.count(to) == 1:
            print("allerede " + ("tilbakestilt" if args.revert else "rettet")
                  + " - ingenting aa gjoere")
            return 0
        raise SystemExit(f"fant {body.count(frm)} treff (ventet 1) for:\n  {frm}")

    print(f"workflow  {wf['name']} (aktiv: {wf.get('active')})")
    print(f"node      {NODE}.{field}")
    print(f"\n- {frm}\n+ {to}")

    if not args.apply and not args.revert:
        print("\nTORRKJORING - ingenting endret")
        return 0

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(BACKUP_DIR, f"backup-main-before-gelato-url-{stamp}.json")
    with open(backup, "w", encoding="utf-8") as fh:
        json.dump(wf, fh, ensure_ascii=False, indent=1)
    print(f"\nbackup    {backup}")

    node["parameters"][field] = body.replace(frm, to)
    # n8n sitt API godtar bare disse fire feltene paa PUT - alt annet gir 400.
    req("PUT", "/workflows/" + WF, {
        "name": wf["name"], "nodes": wf["nodes"],
        "connections": wf["connections"], "settings": wf.get("settings", {}),
    }, key=key)
    print("workflow oppdatert")

    if wf.get("active"):
        req("POST", f"/workflows/{WF}/activate", {}, key=key)
        print("workflow reaktivert")

    check = req("GET", "/workflows/" + WF, key=key)
    cnode = next(n for n in check["nodes"] if n.get("name") == NODE)
    ok = to in cnode["parameters"][field] and frm not in cnode["parameters"][field]
    print("kontroll  " + ("OK" if ok else "FEIL - se over manuelt"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

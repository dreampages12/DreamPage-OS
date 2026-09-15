# -*- coding: utf-8 -*-
"""La neste-bok-forsiden overleve ordren: pdf/page99_next* -> next/page99_next*

Symptom: ordre som ble kjoert om (reprint/regen) fikk en QR-siste-side UTEN
bildet av neste bok - bare tittelen sto igjen. Bekreftet paa 1397 og 1411-b1,
mens ordre som gikk rett gjennom (1412, 1416) var korrekte.

Aarsak: begge kopiene av forsiden slettes foer en reprint rekker aa bruke dem.

  1. `Cleanup Comfy Folder` sletter output/<bok>/orders/<key>/comfy/, altsaa
     raafila page99_next_00001_.png som `cover`-modus leser.
  2. Tekst-scriptet rmtree-er pdf/ ved hvert bygg, altsaa den ferdige
     pdf/page99_next.png + _mockup.png.

Innenfor EN kjoering gaar det bra, fordi forsiden allerede er limt inn i
blank-back.png foer pdf/ tommes. Men reprint_order kjoerer `cover --raw
<comfy>` paa nytt mot en mappe som ikke finnes lenger. Alt er fail-soft
(exit 0, onError: continueRegularOutput), saa det skjer i full stillhet:

    [LAST PAGE WARNING] raa forside mangler: .../comfy (prefiks page99_next)
    [LAST PAGE WARNING] neste-forside mangler - siden bygges uten bilde

Fiksen er aa skrive forsiden til `orders/<key>/next/` i stedet. Den mappa
roeres verken av comfy-cleanup eller tekst-scriptets rmtree, saa en reprint
finner den ferdige forsiden selv naar raafila er borte. Samme konvensjon som
ordre 1233 allerede brukte.

`next/` opprettes av build_last_page selv (os.makedirs paa --out), saa ingen
egen mkdir-node trengs.

  python patch_worker_next_cover_persist.py --dry-run
  python patch_worker_next_cover_persist.py --apply
  python patch_worker_next_cover_persist.py --revert
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

BASE = "http://localhost:5678/api/v1"
WF = "xy8qiRUzcBpH52CI"
BACKUP_DIR = r"C:\Users\tobia\.n8n"

OLD = "d.orderPath + '/pdf/page99_next"
NEW = "d.orderPath + '/next/page99_next"

# (node, hvor mange treff noden skal ha)
#
# Stamp QR definerer `titled` uten aa bruke den. Den byttes likevel, saa alle
# fire nodene i kjeden leser samme sti - neste som endrer noe her skal slippe
# aa lure paa om den ene avvikeren var med vilje.
NODES = [
    ("Build Next Cover Title", 2),      # titled + mockup
    ("Upload Continue Cover", 2),       # titled + mockup
    ("Build Last Page", 1),             # titled
    ("Stamp QR On Innersider", 1),      # titled (ubrukt)
]


def load_api_key() -> str:
    """n8n sin API-noekkel. Laa hardkodet i patch_worker_face_expressions.py og
    ble lest ut derfra som tekst; naa i config/secrets.json (.gitignore)."""
    import json as _json
    if os.environ.get("DP_N8N_API_KEY"):
        return os.environ["DP_N8N_API_KEY"]
    here = os.path.dirname(os.path.abspath(__file__))
    while True:
        candidate = os.path.join(here, "config", "secrets.json")
        if os.path.isfile(candidate):
            with open(candidate, encoding="utf-8-sig") as fh:
                return _json.load(fh).get("n8n_api_key", "")
        parent = os.path.dirname(here)
        if parent == here:
            raise SystemExit("fant ingen config/secrets.json med n8n_api_key")
        here = parent


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
    by_name = {n.get("name"): n for n in wf["nodes"]}
    print("workflow  %s (aktiv: %s)" % (wf["name"], wf.get("active")))

    frm, to = (NEW, OLD) if args.revert else (OLD, NEW)

    planned, already = [], 0
    for name, expected in NODES:
        node = by_name.get(name)
        if node is None:
            raise SystemExit("fant ingen node som heter %r" % name)
        value = node["parameters"]["command"]
        hits = value.count(frm)
        if hits == 0 and value.count(to) == expected:
            print("  = %-24s allerede %s" % (
                name, "tilbakestilt" if args.revert else "patchet"))
            already += 1
            continue
        if hits != expected:
            raise SystemExit(
                "%s: fant %d treff paa %r (ventet %d) - noden er endret siden"
                " denne patchen ble skrevet, se over manuelt"
                % (name, hits, frm, expected))
        planned.append((name, node, value.replace(frm, to)))

    if not planned:
        print("\ningenting aa gjoere - alle %d nodene er allerede paa plass"
              % already)
        return 0

    for name, _, newvalue in planned:
        print("\n%s\n  + %s" % (name, newvalue[:400]))

    if args.dry_run:
        print("\nTORRKJORING - ingenting endret")
        return 0

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(BACKUP_DIR,
                          "backup-main-before-next-cover-persist-%s.json" % stamp)
    with open(backup, "w", encoding="utf-8") as fh:
        json.dump(wf, fh, ensure_ascii=False, indent=1)
    print("\nbackup    %s" % backup)

    for _, node, newvalue in planned:
        node["parameters"]["command"] = newvalue

    # n8n sitt API godtar bare disse fire feltene paa PUT - alt annet gir 400.
    req("PUT", "/workflows/" + WF, {
        "name": wf["name"], "nodes": wf["nodes"],
        "connections": wf["connections"], "settings": wf.get("settings", {}),
    }, key=key)
    print("workflow oppdatert (%d noder)" % len(planned))

    if wf.get("active"):
        req("POST", "/workflows/%s/activate" % WF, {}, key=key)
        print("workflow reaktivert")

    check = req("GET", "/workflows/" + WF, key=key)
    cby = {n.get("name"): n for n in check["nodes"]}
    want = OLD if args.revert else NEW
    ok = True
    for name, expected in NODES:
        good = cby[name]["parameters"]["command"].count(want) == expected
        ok = ok and good
        print("  %s %s" % ("OK  " if good else "FEIL", name))
    print("kontroll  " + ("OK" if ok else "FEIL - se over manuelt"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

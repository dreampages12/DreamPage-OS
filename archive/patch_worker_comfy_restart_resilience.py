# -*- coding: utf-8 -*-
"""Overlev at ComfyUI starter paa nytt midt i en jobb.

SYMPTOM (15.09.2026, ordre 1506 fotballstjernen "Joar", kjoering 2959):

    connect ECONNREFUSED 127.0.0.1:8188     i noden "HTTP Request ComfyUI"

12 av sidene var ferdige (page00..page11, 15:29-15:43). ComfyUI ble
startet paa nytt 15:43:19 - 12 sekunder etter at side 11 var ferdig.
Side 12 traff en port som ikke svarte, og HELE jobben doede.

Verre: laasen for side 12 ble ALDRI frigitt.

    Acquire Comfy Lock   13 kjoeringer
    Release Comfy Lock   12 kjoeringer

"Release Comfy Lock (Error)" henger bare under "If Error" og
"If Timed Out" - altsaa feil ComfyUI rapporterer ETTER at prompten er
levert. Naar selve leveringen feiler, kaster Code-noden og workflowen
avbrytes med laasen liggende.

Foelgefeilen: ordre 1507 (dinosaurenes-dal, kjoering 2960) startet
15:43:17 og stod og ventet paa den doede laasen i 50 minutter. TTL er
2 timer, saa den ville staatt til 17:43.

FIX - tre deler:

  1. HTTP Request ComfyUI   retryOnFail, 5 forsoek x 15 s.
                            De fleste blaff mot porten varer sekunder.
  2. HTTP Request ComfyUI   onError=continueErrorOutput + ny feilgren til
                            "Release Comfy Lock (Error)" -> "Fail Comfy
                            Page". Naar forsoekene er brukt opp slippes
                            laasen foer jobben doer.
  3. Release Comfy Lock (+ Error)
                            slipper laasen naar executionId er VAAR, selv
                            uten token-treff. Paa feilgrenen er det ikke
                            garantert at $json.comfyLock overlever, og en
                            laas vi selv har laget er det alltid trygt aa
                            fjerne. Uten dette ville del 2 kunne bli en
                            no-op.

  Get History faar samme retry - den snakker med samme port og ville
  lekket laasen paa samme maate.

TTL er ogsaa kortet fra 2 timer til 30 minutter. En side tok 1-2
minutter i denne jobben, saa 30 min er rikelig, og verste ventetid for
en uskyldig ordre bak en doed laas gaar fra 2 timer til 30 minutter.

  python patch_worker_comfy_restart_resilience.py --dry-run
  python patch_worker_comfy_restart_resilience.py --apply
  python patch_worker_comfy_restart_resilience.py --revert
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_worker_job_key import BACKUP_DIR, WF, load_api_key, req  # noqa: E402

ERR_NODE = "Release Comfy Lock (Error)"
SRC = "HTTP Request ComfyUI"

# --- kode-endringer ---------------------------------------------------------

REL_OLD = """    if (tokenMatches || (samePage && completedPageExists)) {"""
REL_NEW = """    // ownedByUs alene holder: paa feilgrenen fra HTTP Request ComfyUI er
    // det ikke garantert at $json.comfyLock (og dermed tokenen) overlever,
    // men en laas VI har laget er alltid trygg aa fjerne.
    if (tokenMatches || ownedByUs || (samePage && completedPageExists)) {"""

TTL_OLD = """const ttlMs = 2 * 60 * 60 * 1000;"""
TTL_NEW = """const ttlMs = 30 * 60 * 1000;"""

# /prompt svarer normalt paa millisekunder - den bare koeer jobben. Men naar
# maskinen er under minnepress blokkerer ComfyUI sin event-loop: 15.09.2026
# brukte en side 178 s (mot 69 s normalt) og /prompt svarte ikke innen 60 s.
# Kjoering 2960 (ordre 1507) doede av det, med laasen liggende paa page09.
PROMPT_TIMEOUT_OLD = """const timeoutMs = 60000;"""
PROMPT_TIMEOUT_NEW = """const timeoutMs = 180000;"""

CODE_EDITS = [
    (SRC, "/prompt timeout 60s -> 180s", PROMPT_TIMEOUT_OLD, PROMPT_TIMEOUT_NEW),
    ("Acquire Comfy Lock", "ttl 2t -> 30min", TTL_OLD, TTL_NEW),
    ("Release Comfy Lock", "eier-slipp", REL_OLD, REL_NEW),
    (ERR_NODE, "eier-slipp", REL_OLD, REL_NEW),
]

# --- node-innstillinger -----------------------------------------------------
# (node, felt, verdi-ved-apply, verdi-ved-revert)  None = fjern feltet
SETTING_EDITS = [
    (SRC, "retryOnFail", True, None),
    (SRC, "maxTries", 5, None),
    (SRC, "waitBetweenTries", 15000, None),
    (SRC, "onError", "continueErrorOutput", None),
    ("Get History", "retryOnFail", True, None),
    ("Get History", "maxTries", 5, None),
    ("Get History", "waitBetweenTries", 10000, None),
]

ERR_BRANCH = [{"node": ERR_NODE, "type": "main", "index": 0}]


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
    nodes = {n["name"]: n for n in wf["nodes"]}
    conns = wf["connections"]

    planned = already = 0

    # 1. kode
    for name, label, old, new in CODE_EDITS:
        node = nodes.get(name)
        if node is None:
            raise SystemExit("fant ingen node %r" % name)
        code = node["parameters"].get("jsCode", "")
        frm, to = (new, old) if args.revert else (old, new)
        if code.count(frm) == 1 and code.count(to) == 0:
            node["parameters"]["jsCode"] = code.replace(frm, to)
            planned += 1
            print("  kode     %-28s %s" % (name, label))
        elif code.count(frm) == 0 and code.count(to) >= 1:
            already += 1
            print("  allerede %-28s %s" % (name, label))
        else:
            raise SystemExit(
                "uventet kode i %r (%s): %d treff paa moensteret - "
                "noden er endret manuelt, patch den for haand"
                % (name, label, code.count(frm)))

    # 2. innstillinger
    for name, field, new, old in SETTING_EDITS:
        node = nodes.get(name)
        if node is None:
            raise SystemExit("fant ingen node %r" % name)
        want = old if args.revert else new
        if node.get(field) == want and (want is not None or field not in node):
            already += 1
            print("  allerede %-28s %s" % (name, field))
            continue
        if want is None:
            node.pop(field, None)
        else:
            node[field] = want
        planned += 1
        print("  felt     %-28s %s = %s" % (name, field, want))

    # 3. feilgren
    out = conns.setdefault(SRC, {}).setdefault("main", [])
    if args.revert:
        if len(out) > 1:
            del out[1:]
            planned += 1
            print("  kobling  %-28s feilgren fjernet" % SRC)
        else:
            already += 1
            print("  allerede %-28s ingen feilgren" % SRC)
    else:
        if not out:
            raise SystemExit("%r mangler hovedgrenen sin" % SRC)
        if len(out) > 1 and out[1] == ERR_BRANCH:
            already += 1
            print("  allerede %-28s feilgren -> %s" % (SRC, ERR_NODE))
        elif len(out) > 1 and out[1]:
            raise SystemExit(
                "%r har allerede en annen feilgren: %s" % (SRC, out[1]))
        else:
            if len(out) < 2:
                out.append(list(ERR_BRANCH))
            else:
                out[1] = list(ERR_BRANCH)
            planned += 1
            print("  kobling  %-28s feilgren -> %s" % (SRC, ERR_NODE))

    print("\n%d endring(er) planlagt, %d allerede riktige" % (planned, already))
    if args.dry_run:
        print("TORRKJORING - ingenting endret")
        return 0
    if planned == 0:
        print("ingenting aa gjoere")
        return 0

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(
        BACKUP_DIR,
        "backup-main-before-comfy-restart-resilience-%s.json" % stamp)
    with open(backup, "w", encoding="utf-8") as fh:
        json.dump(req("GET", "/workflows/" + WF, key=key), fh,
                  ensure_ascii=False, indent=1)
    print("backup    %s" % backup)

    req("PUT", "/workflows/" + WF, {
        "name": wf["name"], "nodes": wf["nodes"],
        "connections": wf["connections"], "settings": wf.get("settings", {}),
    }, key=key)
    print("workflow oppdatert")

    if wf.get("active"):
        req("POST", "/workflows/%s/activate" % WF, {}, key=key)
        print("workflow reaktivert")

    # kontroll
    fresh = req("GET", "/workflows/" + WF, key=key)
    check = {n["name"]: n for n in fresh["nodes"]}
    ok = True
    for name, label, old, new in CODE_EDITS:
        want = old if args.revert else new
        if want not in check[name]["parameters"].get("jsCode", ""):
            ok = False
            print("kontroll  FEIL i %s (%s)" % (name, label))
    for name, field, new, old in SETTING_EDITS:
        want = old if args.revert else new
        if check[name].get(field) != want:
            ok = False
            print("kontroll  FEIL i %s (%s)" % (name, field))
    fout = fresh["connections"].get(SRC, {}).get("main", [])
    has_err = len(fout) > 1 and fout[1] == ERR_BRANCH
    if has_err == bool(args.revert):
        ok = False
        print("kontroll  FEIL i feilgren fra %s" % SRC)
    print("kontroll  %s" % ("OK" if ok else "FEIL - se over manuelt"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

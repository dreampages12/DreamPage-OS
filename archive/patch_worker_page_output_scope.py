# -*- coding: utf-8 -*-
"""Hindre at to samtidige ordre stjeler hverandres ferdige sider.

SYMPTOM (14.09.2026, ordre 1499 havfruen + 1500 dyreparken):

    ValueError: Inner PDF page count must be one of [30, 31]; got 14

Begge ordrene feilet i "Run Text Script". 1499 manglet side 03/10/12/14,
1500 manglet forsiden + 04-09/11/13 - noeyaktig de sidene den ANDRE ordren
hadde laget. Ingen bilder var feil; de var borte.

AARSAK - to feil som forsterker hverandre:

  1. "Acquire Comfy Lock" returnerer HELE den fremmede laasen i `comfyLock`
     naar Comfy er opptatt. Da peker `comfyLock.pageOutputDir` paa den andre
     ordrens output-mappe.

  2. "Check Page Output" tar `comfyLock.pageOutputDir` med i listen over
     mapper den leter i. Sidenoeklene er like i alle boeker (page00..page14),
     saa `page04_00001_.png` fra ordre 1499 gjorde at ordre 1500 konkluderte
     med at side 04 var ferdig - og hoppet over den.

     Check Page Output -> Page Already Done? (true) -> Page Done

  Samme lekkasje gjorde at "Release Comfy Lock" kunne slette den ANDRE
  ordrens laas: tokenen i $json.comfyLock var jo en kopi av den fremmede
  laasen, saa `tokenMatches` slo til. Da kjoerte to ordre mot ComfyUI
  samtidig.

FIX - tre noder:

  * Check Page Output      leter kun i ordrens EGEN output_dir.
  * Acquire Comfy Lock     lekker ikke lenger den fremmede laasen videre;
                           eieren rapporteres i lockWaitReason/lockOwner.
  * Release Comfy Lock (+ Error-varianten)
                           slipper kun laaser denne kjoeringen selv eier
                           (executionId maa stemme).

Sidehopp for SAMME ordre er fortsatt paakrevd: den samme ordren kommer
av og til flere ganger paa koeen (1499 kom tre ganger denne dagen), og
uten hoppet ville hver levering rendret alt paa nytt.

  python patch_worker_page_output_scope.py --dry-run
  python patch_worker_page_output_scope.py --apply
  python patch_worker_page_output_scope.py --revert
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from patch_worker_job_key import BACKUP_DIR, WF, load_api_key, req  # noqa: E402


# --- 1. Check Page Output ---------------------------------------------------
# Fjerner comfyLock.pageOutputDir fra kandidatlisten. pageOutputDir beholdes
# som fallback (den er ordrens egen etter denne patchen), men output_dir fra
# Pages Config er alltid satt og gaar foerst.
CPO_OLD = """const candidates = [
  normalizeDir($json.output_dir),
  normalizeDir($json.pageOutputDir),
  normalizeDir($json.comfyLock && $json.comfyLock.pageOutputDir),
].filter(Boolean);"""

CPO_NEW = """// KUN ordrens egen mappe. Sidenoeklene (page00..page14) er like i alle
// boeker, saa en fremmed mappe her faar en annen ordres side til aa se
// ferdig ut - og siden blir aldri laget for denne ordren.
const candidates = [
  normalizeDir($json.output_dir),
  normalizeDir($json.pageOutputDir),
].filter(Boolean);"""


# --- 2. Acquire Comfy Lock --------------------------------------------------
# Den siste returen (Comfy opptatt av en ANNEN ordre) skal ikke sende den
# fremmede laasen videre i $json.comfyLock.
ACQ_OLD = """return {
  json: Object.assign({}, $json, {
    lockAcquired: false,
    lockWaitReason: existing
      ? ('Comfy busy with order ' + (existing.order_id || '?') + ' ' + (existing.page_key || '?'))
      : 'Comfy lock exists',
    comfyLock: existing ? Object.assign({ path: lockPath }, existing) : { path: lockPath },
  }),
};"""

ACQ_NEW = """// Laasen tilhoerer en annen kjoering. Send ALDRI dens felter videre i
// comfyLock: pageOutputDir ville sendt Check Page Output inn i den andre
// ordrens mappe, og tokenen ville latt Release Comfy Lock slette en laas
// vi ikke eier. Kun diagnostikk herfra.
return {
  json: Object.assign({}, $json, {
    lockAcquired: false,
    lockWaitReason: existing
      ? ('Comfy busy with order ' + (existing.order_id || '?') + ' ' + (existing.page_key || '?'))
      : 'Comfy lock exists',
    lockOwner: existing
      ? { order_id: existing.order_id || '', book_slug: existing.book_slug || '',
          page_key: existing.page_key || '', executionId: existing.executionId || '' }
      : null,
    comfyLock: { path: lockPath },
  }),
};"""


# --- 3. Release Comfy Lock (begge variantene) -------------------------------
# Token alene er ikke eierskap naar tokenen kan vaere kopiert fra en fremmed
# laas. Krev at kjoeringen som laget laasen er DENNE kjoeringen.
REL_OLD = """    const tokenMatches = lock.token && current && current.token === lock.token;"""

REL_NEW = """    const selfId = (typeof $execution !== 'undefined' && $execution.id) ? String($execution.id) : 'unknown';
    const ownedByUs = current && String(current.executionId || '') === selfId;
    const tokenMatches = ownedByUs && lock.token && current.token === lock.token;"""


EDITS = [
    ("Check Page Output", "kandidatmapper", CPO_OLD, CPO_NEW),
    ("Acquire Comfy Lock", "busy-retur", ACQ_OLD, ACQ_NEW),
    ("Release Comfy Lock", "eierskapssjekk", REL_OLD, REL_NEW),
    ("Release Comfy Lock (Error)", "eierskapssjekk", REL_OLD, REL_NEW),
]


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

    planned, already = 0, 0
    for name, label, old, new in EDITS:
        node = by_name.get(name)
        if node is None:
            raise SystemExit("fant ingen node som heter %r" % name)
        code = node["parameters"].get("jsCode", "")
        frm, to = (new, old) if args.revert else (old, new)
        if code.count(frm) == 1:
            node["parameters"]["jsCode"] = code.replace(frm, to)
            planned += 1
            print("  endrer   %-28s %s" % (name, label))
        elif code.count(frm) == 0 and code.count(to) >= 1:
            already += 1
            print("  allerede %-28s %s" % (name, label))
        else:
            raise SystemExit(
                "uventet kode i %r (%s): fant %d treff paa moensteret - "
                "noden er endret manuelt, patch den for haand"
                % (name, label, code.count(frm)))

    print("\n%d node(r) skal endres, %d er allerede riktige" % (planned, already))
    if args.dry_run:
        print("TORRKJORING - ingenting endret")
        return 0
    if planned == 0:
        print("ingenting aa gjoere")
        return 0

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(BACKUP_DIR,
                          "backup-main-before-page-output-scope-%s.json" % stamp)
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

    check = {n["name"]: n for n in req("GET", "/workflows/" + WF, key=key)["nodes"]}
    ok = True
    for name, label, old, new in EDITS:
        want = old if args.revert else new
        if want not in check[name]["parameters"].get("jsCode", ""):
            ok = False
            print("kontroll  FEIL i %s (%s)" % (name, label))
    print("kontroll  %s" % ("OK" if ok else "FEIL - se over manuelt"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

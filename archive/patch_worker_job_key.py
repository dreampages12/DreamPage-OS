# -*- coding: utf-8 -*-
"""Gjoer Dreampage Worker v2 klar for flere boeker i samme ordre (job_key).

Fram til naa har en WooCommerce-ordre alltid vaert noeyaktig en bok, og
`order_id` har derfor kunnet fungere baade som ordrenummer OG som unik
noekkel for mapper, ComfyUI-input, laaser og Gelato-referanse.

Nettsiden tillater naa flere boeker i samme handlekurv. Da kommer det en
koe-melding per bok, alle med samme `order_id`, men med et nytt felt:

    order_id  = "1400"                      (WooCommerce-ordren)
    job_key   = "1400-b1" / "1400-b2"       (unik per bok)
    job_key   = "1400"                      naar ordren har KUN en bok

Verste tilfelle er samme bok til to barn (f.eks. Fotballstjernen til Emil
og Kristoffer): samme `book_slug` + samme `order_id` = samme mappe. Da
overskriver de to jobbene hverandres input-bilde, sider og PDF, og ett av
barna faar feil ansikt i boka si.

Denne patchen bytter dirKey fra order_id til (job_key || order_id) fem
steder. Fallbacken `|| order_id` er ikke pynt: den gjoer at gamle meldinger
som allerede ligger i koeen fortsatt virker, og at denne patchen trygt kan
rulles ut FOER WordPress-delen gaar live.

  1. Edit Fields / ef-1 "order_id"   -> selve dirKey-en. Alt nedstroems
     (Setup Order Dirs, Parse Config sin orderPath + outputDir, Comfy-laas,
     Claim Post-Comfy Order, Read Cover/Innersider PDF, Cleanup, Record
     Gelato Draft) leser denne, saa ett bytte her flytter hele kjeden.
  2. Edit Fields / ef-4 "face_image" -> C:/ComfyUI/input/<key>.jpg
  3. Save Child Image  / fileName    -> samme fil, skrives her
  4. Build Face Variants / command   -> lager <key>-noytral.jpg osv.
  5. Create Gelato Draft / jsonBody  -> orderReferenceId. Gelato krever unik
     referanse; to draft med "1400" blir avvist eller slaatt sammen, og den
     ene boka blir aldri trykket. Bruker gelato_reference naar den finnes.

Punkt 2-4 er det som faktisk redder same-bok-to-barn-tilfellet: uten dem
peker begge jobbene paa samme C:/ComfyUI/input/1400.jpg.

IKKE endret med vilje:
  * "WP Progress: *" bruker woo_order_id || Parse Job.order_id direkte fra
    Parse Job - WooCommerce skal fortsatt ha "1400", ikke "1400-b2".
  * book_index / book_count er kun logging og trengs ikke i worker-flyten.
  * Sammenslaaing av to Gelato-ordre til en pakke er en senere forbedring.

  python patch_worker_job_key.py --dry-run
  python patch_worker_job_key.py --apply
  python patch_worker_job_key.py --revert
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.request

BASE = "http://localhost:5678/api/v1"
WF = "xy8qiRUzcBpH52CI"
BACKUP_DIR = r"C:\Users\tobia\.n8n"

PJ = '$node["Parse Job"].json'
PJ1 = "$node['Parse Job'].json"

# (node, beskrivelse av felt, accessor, OLD, NEW)
EDITS = [
    (
        "Edit Fields", "ef-1 order_id",
        ("assign", "ef-1"),
        '={{ %s.order_id }}' % PJ,
        '={{ %s.job_key || %s.order_id }}' % (PJ, PJ),
    ),
    (
        "Edit Fields", "ef-4 face_image",
        ("assign", "ef-4"),
        "={{ 'C:/ComfyUI/input/' + %s.order_id + '.jpg' }}" % PJ1,
        "={{ 'C:/ComfyUI/input/' + (%s.job_key || %s.order_id) + '.jpg' }}"
        % (PJ1, PJ1),
    ),
    (
        "Save Child Image", "fileName",
        ("param", "fileName"),
        "={{ 'C:/ComfyUI/input/' + %s.order_id + '.jpg' }}" % PJ1,
        "={{ 'C:/ComfyUI/input/' + (%s.job_key || %s.order_id) + '.jpg' }}"
        % (PJ1, PJ1),
    ),
    (
        "Build Face Variants", "command",
        ("param", "command"),
        '{{ %s.order_id }}' % PJ,
        '{{ %s.job_key || %s.order_id }}' % (PJ, PJ),
    ),
    (
        "Create Gelato Draft", "jsonBody orderReferenceId",
        ("param", "jsonBody"),
        'orderReferenceId: $node["All Pages Done"].json.order_id,',
        'orderReferenceId: %s.gelato_reference'
        ' || $node["All Pages Done"].json.order_id,' % PJ,
    ),
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


def slot(node, accessor):
    """Returnerer (get, set) for feltet patchen skal roere."""
    kind, ident = accessor
    if kind == "param":
        params = node["parameters"]
        return (lambda: params[ident],
                lambda v: params.__setitem__(ident, v))
    rows = node["parameters"]["assignments"]["assignments"]
    row = next((r for r in rows if r.get("id") == ident), None)
    if row is None:
        raise SystemExit("fant ingen assignment med id %r i %r"
                         % (ident, node["name"]))
    return (lambda: row["value"], lambda v: row.__setitem__("value", v))


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

    planned, already = [], 0
    for name, label, accessor, old, new in EDITS:
        node = by_name.get(name)
        if node is None:
            raise SystemExit("fant ingen node som heter %r" % name)
        get, set_ = slot(node, accessor)
        value = get()
        frm, to = (new, old) if args.revert else (old, new)
        if value.count(frm) != 1:
            if value.count(frm) == 0 and value.count(to) >= 1:
                print("  = %-22s %s - allerede %s" % (
                    name, label,
                    "tilbakestilt" if args.revert else "patchet"))
                already += 1
                continue
            raise SystemExit(
                "%s.%s: fant %d treff (ventet 1) for:\n  %s"
                % (name, label, value.count(frm), frm))
        planned.append((name, label, set_, value.replace(frm, to), frm, to))

    if not planned:
        print("\ningenting aa gjoere - alle %d stedene er allerede paa plass"
              % already)
        return 0

    for name, label, _, _, frm, to in planned:
        print("\n%s / %s\n  - %s\n  + %s" % (name, label, frm, to))

    if args.dry_run:
        print("\nTORRKJORING - ingenting endret")
        return 0

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(BACKUP_DIR,
                          "backup-main-before-job-key-%s.json" % stamp)
    with open(backup, "w", encoding="utf-8") as fh:
        json.dump(wf, fh, ensure_ascii=False, indent=1)
    print("\nbackup    %s" % backup)

    for _, _, set_, newvalue, _, _ in planned:
        set_(newvalue)

    # n8n sitt API godtar bare disse fire feltene paa PUT - alt annet gir 400.
    req("PUT", "/workflows/" + WF, {
        "name": wf["name"], "nodes": wf["nodes"],
        "connections": wf["connections"], "settings": wf.get("settings", {}),
    }, key=key)
    print("workflow oppdatert (%d endringer)" % len(planned))

    if wf.get("active"):
        req("POST", "/workflows/%s/activate" % WF, {}, key=key)
        print("workflow reaktivert")

    check = req("GET", "/workflows/" + WF, key=key)
    cby = {n.get("name"): n for n in check["nodes"]}
    ok = True
    for name, label, accessor, old, new in EDITS:
        get, _ = slot(cby[name], accessor)
        value = get()
        want = old if args.revert else new
        good = want in value
        ok = ok and good
        print("  %s %s / %s" % ("OK  " if good else "FEIL", name, label))
    print("kontroll  " + ("OK" if ok else "FEIL - se over manuelt"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

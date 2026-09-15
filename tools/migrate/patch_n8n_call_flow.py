# -*- coding: utf-8 -*-
"""Fase 2-leveransen: la n8n kalle flow som ÉN node, og slett laasen.

Bytter ut 23 noder med ett `executeCommand`-kall, paa samme maate som
workflowen alt kaller "Run Text Script":

    Pages Config, Page Loop, Build Page Prompt, HTTP Request ComfyUI,
    Init Poll, Get History, Parse History, If Error, Done Check, Page Done,
    Inc Tries, If Timed Out, Poll Wait, Check Page Output,
    Page Already Done?, Fail Comfy Page, All Pages Done, Read Template
    + Acquire Comfy Lock, Lock Acquired?, Wait Comfy Lock,
      Release Comfy Lock, Release Comfy Lock (Error)

De fem siste er laasen. Den migreres ikke - den slettes. flow er én prosess
med én intern koe, saa serialiseringen er en egenskap ved konstruksjonen.
To produksjonsinsidenter paa to dager laa i noeyaktig den mekanismen.

Den nye noden:

    python flow/worker/cli.py render --payload <tempfil med payloaden>

CLI-en sender jobben til den kjoerende workeren og venter. Selv om n8n starter
to executions parallelt, havner begge i den samme interne koeen.

    python patch_n8n_call_flow.py --dry-run     # vis hva som skjer
    python patch_n8n_call_flow.py --apply
    python patch_n8n_call_flow.py --revert      # tilbake fra backupen

### Les dette foer du kjoerer den

Dette ENDRER PRODUKSJON. Foerst maa alt dette vaere sant:

  1. Fase 1 er ferdig og verifisert - treet ligger i DreamPage-image, stiene
     er rettet, og en ekte ordre har gaatt gjennom fra ny sti.
  2. flow-workeren kjoerer (`.\\dreampage.ps1 status`), og /api/health svarer.
  3. Ingen ordre er i arbeid.
  4. `python flow/worker/tests/test_flow.py` er groenn.

Skriptet sjekker 2, 3 og 4 selv og nekter ellers. Punkt 1 kan det ikke sjekke.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent.parent
WF_ID = "xy8qiRUzcBpH52CI"
BASE = os.environ.get("DP_N8N_API_BASE", "http://localhost:5678/api/v1")
BACKUP_DIR = ROOT / "state" / "n8n-backups"

NEW_NODE = "Flow: Render Pages"

# Nodene som forsvinner. Rekkefoelgen er bare for lesbarhet.
REPLACED = [
    "Pages Config", "Page Loop", "Build Page Prompt", "HTTP Request ComfyUI",
    "Init Poll", "Get History", "Parse History", "If Error", "Done Check",
    "Page Done", "Inc Tries", "If Timed Out", "Poll Wait",
    "Check Page Output", "Page Already Done?", "Fail Comfy Page",
    "All Pages Done",
    # Leste books/<slug>/workflow_api.json og sendte den binaert videre til
    # Build Page Prompt. flow leser filen selv, saa denne blir foreldreloes.
    "Read Template",
]
LOCK_NODES = [
    "Acquire Comfy Lock", "Lock Acquired?", "Wait Comfy Lock",
    "Release Comfy Lock", "Release Comfy Lock (Error)",
]

# Noden som kaller flow. Payloaden skrives til en tempfil foerst: en jobb-
# payload inneholder adresse, e-post og continue_code, og en kommandolinje
# ender i prosesslister og eventloggen.
PY = sys.executable.replace("\\", "/")
CLI = str(ROOT / "flow" / "worker" / "cli.py").replace("\\", "/")
COMMAND = (
    "={{ (() => {\n"
    "  const job = $node[\"Parse Job\"].json;\n"
    "  const key = job.job_key || job.order_id;\n"
    "  const fs = require('fs'), os = require('os'), path = require('path');\n"
    "  // Payloaden paa kommandolinja ville lagt kundens adresse i\n"
    "  // prosesslisten. Tempfil i stedet.\n"
    "  const file = path.join(os.tmpdir(), 'dpflow-' + key + '.json');\n"
    "  fs.writeFileSync(file, JSON.stringify(job), 'utf8');\n"
    "  return '\"" + PY + "\" \"" + CLI + "\" render --payload \"' + file + '\"';\n"
    "})() }}"
)

PARSE_CODE = """// Svaret fra flow/worker/cli.py. Siste linje paa stdout er
// "DPFLOW_JSON {...}" - alt annet (logg, fremdrift) gaar til stderr, nettopp
// for at denne parsingen skal vaere triviell.
const out = String($json.stdout || '');
const line = out.split('\\n').reverse().find(l => l.includes('DPFLOW_JSON'));
if (!line) {
  throw new Error('flow svarte uten DPFLOW_JSON. stdout=' + out.slice(-1500)
    + ' stderr=' + String($json.stderr || '').slice(-1500));
}
const result = JSON.parse(line.slice(line.indexOf('DPFLOW_JSON') + 11));
if (result.status !== 'done') {
  throw new Error('flow stoppet ordren: ' + (result.error || result.status)
    + (result.step ? ' (steg: ' + result.step + ')' : ''));
}

// Videre i grafen forventer feltene "All Pages Done" satte. De hentes fra
// Parse Config, som fortsatt kjoerer foer dette.
const src = $node['Parse Config'].json || {};
return [{ json: Object.assign({}, src, {
  allDone: true,
  flowPages: result.pages,
  flowSeconds: result.seconds,
}) }];
"""


def api_key() -> str:
    if os.environ.get("DP_N8N_API_KEY"):
        return os.environ["DP_N8N_API_KEY"]
    with open(ROOT / "config" / "secrets.json", encoding="utf-8-sig") as fh:
        return json.load(fh)["n8n_api_key"]


def req(method: str, path: str, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(BASE + path, body, method=method, headers={
        "X-N8N-API-KEY": api_key(), "Accept": "application/json",
        "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(request, timeout=180))


# ---------------------------------------------------------------------------
# Forhaandssjekker
# ---------------------------------------------------------------------------
def _flow_health() -> dict | None:
    try:
        with open(ROOT / "config" / "api.json", encoding="utf-8-sig") as fh:
            conf = json.load(fh)
        token = next(iter(conf.get("tokens") or {}), None) or conf.get("token")
    except (OSError, json.JSONDecodeError):
        return None
    if not token:
        return None
    request = urllib.request.Request(
        "http://127.0.0.1:8765/api/health",
        headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=10) as res:
            return json.load(res)
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None


def preflight(force: bool) -> None:
    print("--- forhaandssjekker")
    health = _flow_health()
    if health is None:
        msg = ("flow-workeren svarer ikke paa http://127.0.0.1:8765/api/health. "
               "Uten den faller CLI-en tilbake til aa kjoere jobben i n8n sin "
               "egen prosess, og da er serialiseringen borte - det er hele "
               "grunnen til at fase 2 finnes. Start den med "
               ".\\dreampage.ps1 up")
        if not force:
            raise SystemExit("STOPP: " + msg)
        print("  ADVARSEL (--force): " + msg)
    else:
        print(f"  flow: worker alive={health['worker']['alive']}, "
              f"ComfyUI ok={health['comfy']['ok']}")
        if health["worker"].get("running"):
            raise SystemExit(
                f"STOPP: flow jobber med ordre {health['worker']['running']}. "
                f"Vent til den er ferdig.")
        if not health["comfy"]["ok"]:
            raise SystemExit("STOPP: flow naar ikke ComfyUI.")

    # Kjoerer det en ordre i n8n?
    import sqlite3
    db = os.path.expanduser(r"~/.n8n/database.sqlite")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        running = con.execute(
            "select count(*) from execution_entity where stoppedAt is null"
        ).fetchone()[0]
    finally:
        con.close()
    print(f"  n8n: {running} uferdige executions")
    if running and not force:
        raise SystemExit("STOPP: n8n har en execution som kjoerer.")

    # Testene.
    tests = ROOT / "flow" / "worker" / "tests" / "test_flow.py"
    proc = subprocess.run([sys.executable, str(tests)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    last = [l for l in (proc.stdout or "").splitlines() if "tester gikk" in l]
    print(f"  tester: {last[-1].strip() if last else 'ukjent'}")
    if proc.returncode != 0 and not force:
        raise SystemExit("STOPP: testene er ikke groenne.\n" + (proc.stdout or "")[-3000:])


# ---------------------------------------------------------------------------
# Selve patchen
# ---------------------------------------------------------------------------
def _rewire(wf: dict) -> tuple[dict, list[str]]:
    """Fjern nodene, sett inn den nye, og koble grafen om.

    Parse Config -> Flow: Render Pages -> Parse Flow Result -> (det All Pages
    Done pekte paa)
    """
    notes = []
    nodes = {n["name"]: n for n in wf["nodes"]}
    gone = [name for name in REPLACED + LOCK_NODES if name in nodes]
    for name in REPLACED + LOCK_NODES:
        if name not in nodes:
            notes.append(f"fantes ikke: {name}")

    # Hvor pekte "All Pages Done"? Det er der vi skal fortsette.
    after = wf["connections"].get("All Pages Done", {}).get("main", [[]])
    after_targets = [t for branch in after for t in (branch or [])]
    if not after_targets:
        raise SystemExit("fant ingen utgang fra 'All Pages Done' - grafen er "
                         "ikke slik dette skriptet forventer")
    notes.append("etter flow fortsetter grafen til: "
                 + ", ".join(t["node"] for t in after_targets))

    base_pos = nodes.get("Page Loop", {}).get("position", [1200, 300])
    new_nodes = [n for n in wf["nodes"] if n["name"] not in gone]
    new_nodes.append({
        "parameters": {"command": COMMAND},
        "type": "n8n-nodes-base.executeCommand",
        "typeVersion": 1,
        "position": base_pos,
        "id": "flow-render-pages",
        "name": NEW_NODE,
        # Feiler flow, skal ordren STOPPE - ikke gaa videre til PDF med
        # manglende sider. Det er hele poenget med sidetall-guarden.
        "onError": "stopWorkflow",
    })
    new_nodes.append({
        "parameters": {"jsCode": PARSE_CODE},
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [base_pos[0] + 200, base_pos[1]],
        "id": "flow-parse-result",
        "name": "Parse Flow Result",
    })

    conns = {k: v for k, v in wf["connections"].items() if k not in gone}
    # Parse Config peker naa paa den nye noden.
    conns["Parse Config"] = {"main": [[{"node": NEW_NODE, "type": "main", "index": 0}]]}
    conns[NEW_NODE] = {"main": [[{"node": "Parse Flow Result", "type": "main", "index": 0}]]}
    conns["Parse Flow Result"] = {"main": [after_targets]}

    # Alle andre referanser til en fjernet node maa bort, ellers avviser n8n
    # workflowen med "node not found".
    for source, outs in list(conns.items()):
        for kind, branches in list(outs.items()):
            for i, branch in enumerate(branches or []):
                if branch is None:
                    continue
                kept = [t for t in branch if t["node"] not in gone]
                if len(kept) != len(branch):
                    dropped = [t["node"] for t in branch if t["node"] in gone]
                    notes.append(f"{source} pekte paa {', '.join(dropped)} - fjernet")
                branches[i] = kept

    wf["nodes"] = new_nodes
    wf["connections"] = conns
    return wf, notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--revert", metavar="BACKUP.json")
    ap.add_argument("--force", action="store_true",
                    help="kjoer selv om en forhaandssjekk klager")
    args = ap.parse_args()

    if args.revert:
        with open(args.revert, encoding="utf-8") as fh:
            wf = json.load(fh)
        req("PUT", f"/workflows/{WF_ID}", {
            "name": wf["name"], "nodes": wf["nodes"],
            "connections": wf["connections"], "settings": wf.get("settings", {})})
        print(f"gjenopprettet fra {args.revert}")
        return 0

    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    if args.apply:
        preflight(args.force)

    wf = req("GET", f"/workflows/{WF_ID}")
    print(f"\nworkflow  {wf['name']}  (aktiv: {wf.get('active')})  "
          f"{len(wf['nodes'])} noder")
    if wf.get("active") and args.apply:
        raise SystemExit(
            "STOPP: workflowen er AKTIV. Deaktiver den i n8n foerst - en ordre "
            "kan ellers starte midt i omkoblingen. Aktiver den igjen etterpaa.")

    before = len(wf["nodes"])
    patched, notes = _rewire(json.loads(json.dumps(wf)))

    print(f"\nfjerner {before - len(patched['nodes']) + 2} noder:")
    for name in REPLACED:
        print(f"    {name}")
    print("  og laasen, som ikke migreres - den slettes:")
    for name in LOCK_NODES:
        print(f"    {name}")
    print(f"\nsetter inn:\n    {NEW_NODE}\n    Parse Flow Result")
    print(f"\nkommando:\n    {PY}\n    {CLI} render --payload <tempfil>")
    print("\nmerknader:")
    for note in notes:
        print(f"    {note}")
    print(f"\nnoder: {before} -> {len(patched['nodes'])}")

    if not args.apply:
        print("\nTORRKJORING - ingenting endret")
        return 0

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = BACKUP_DIR / f"worker-before-flow-{stamp}.json"
    backup.write_text(json.dumps(wf, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nbackup   {backup}")
    print(f"  tilbake:  python {Path(__file__).name} --revert \"{backup}\"")

    req("PUT", f"/workflows/{WF_ID}", {
        "name": patched["name"], "nodes": patched["nodes"],
        "connections": patched["connections"],
        "settings": patched.get("settings", {})})
    print("workflow oppdatert")

    check = req("GET", f"/workflows/{WF_ID}")
    names = {n["name"] for n in check["nodes"]}
    left = [n for n in REPLACED + LOCK_NODES if n in names]
    print("kontroll  " + ("OK - laasen og side-loekka er borte, flow-noden er inne"
                          if not left and NEW_NODE in names
                          else f"GJENSTAAR: {left}"))
    print("\nHUSK: aktiver workflowen igjen i n8n, og kjoer en ekte ordre.")
    print("Naar den er verifisert, slett det som er igjen av laasen:")
    print("    Remove-Item C:\\DreamPage-OS\\DreamPage-image\\.dreampage-comfy.lock")
    return 0 if not left else 1


if __name__ == "__main__":
    sys.exit(main())

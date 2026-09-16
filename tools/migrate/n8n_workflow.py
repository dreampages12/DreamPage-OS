# -*- coding: utf-8 -*-
"""Aktiver, deaktiver og list n8n-workflows. Med backup.

Trengs fordi overgangen til DreamPage OS ikke er "skru av n8n". n8n har to
roller, og bare én av dem skal bort:

    xy8qiRUzcBpH52CI  "Dreampage Worker v2"  - bygger boekene. SKAL bort.
    G0skxlQwcLhDH3NT  "My workflow 3"        - WooCommerce-webhooken som
                                               legger ordre paa RabbitMQ.
                                               MAA leve, ellers naar en ny
                                               ordre aldri koen i det hele
                                               tatt.

Dreper man n8n-prosessen, stopper ordreinntaket. Derfor deaktiveres bare
worker-workflowen; prosessen lever videre som webhook-mottaker.

    python n8n_workflow.py list
    python n8n_workflow.py deactivate xy8qiRUzcBpH52CI
    python n8n_workflow.py activate xy8qiRUzcBpH52CI      # tilbake

Deaktivering er reversibel og tar backup av hele workflowen foerst.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
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
BASE = os.environ.get("DP_N8N_API_BASE", "http://localhost:5678/api/v1")
BACKUP_DIR = ROOT / "state" / "n8n-backups"

# Workflowen som MAA vaere aktiv for at ordre skal komme inn. Nekter aa
# deaktivere den uten --i-know.
PRODUCER = "G0skxlQwcLhDH3NT"


def _key() -> str:
    if os.environ.get("DP_N8N_API_KEY"):
        return os.environ["DP_N8N_API_KEY"]
    with open(ROOT / "config" / "secrets.json", encoding="utf-8-sig") as fh:
        return json.load(fh)["n8n_api_key"]


def req(method: str, path: str, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(BASE + path, body, method=method, headers={
        "X-N8N-API-KEY": _key(), "Accept": "application/json",
        "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=120) as res:
            return json.loads(res.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"n8n svarte HTTP {exc.code}: "
                         f"{exc.read().decode('utf-8','replace')[:500]}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"naadde ikke n8n paa {BASE}: {exc}") from exc


def cmd_list(args) -> int:
    data = req("GET", "/workflows")["data"]
    active = [w for w in data if w.get("active")]
    print(f"{len(data)} workflows, {len(active)} aktive\n")
    for w in sorted(data, key=lambda x: (not x.get("active"), x["name"])):
        mark = "AKTIV" if w.get("active") else "  -  "
        note = ""
        if w["id"] == PRODUCER:
            note = "   <- produsenten: WooCommerce -> RabbitMQ. Maa leve."
        print(f"  {mark}  {w['id']}  {w['name']}{note}")
    return 0


def _set_active(wf_id: str, active: bool, force: bool) -> int:
    if wf_id == PRODUCER and not active and not force:
        raise SystemExit(
            f"NEKTER: {wf_id} er WooCommerce-webhooken som legger ordre paa "
            f"RabbitMQ. Deaktiverer du den, naar en ny ordre aldri koen - og "
            f"det er stille, ingen feiler. Bruk --i-know hvis du virkelig mener "
            f"det.")

    wf = req("GET", f"/workflows/{wf_id}")
    print(f"workflow  {wf['name']}")
    print(f"  aktiv naa : {wf.get('active')}")
    print(f"  noder     : {len(wf.get('nodes', []))}")
    if bool(wf.get("active")) == active:
        print(f"  allerede {'aktiv' if active else 'deaktivert'} - ingenting aa gjoere")
        return 0

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    what = "activate" if active else "deactivate"
    backup = BACKUP_DIR / f"{wf_id}-before-{what}-{stamp}.json"
    backup.write_text(json.dumps(wf, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  backup    : {backup}")

    req("POST", f"/workflows/{wf_id}/{'activate' if active else 'deactivate'}", {})
    check = req("GET", f"/workflows/{wf_id}")
    ok = bool(check.get("active")) == active
    print(f"  aktiv naa : {check.get('active')}")
    print("  " + ("OK" if ok else "FEIL - se over i n8n"))
    if not active:
        print(f"\n  tilbake:  python {Path(__file__).name} activate {wf_id}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="alle workflows og hvilke som er aktive").set_defaults(
        func=cmd_list)

    for name, active in (("activate", True), ("deactivate", False)):
        p = sub.add_parser(name, help=f"{name} en workflow")
        p.add_argument("workflow_id")
        p.add_argument("--i-know", action="store_true",
                       help="tillat aa deaktivere produsent-workflowen")
        p.set_defaults(func=lambda a, _a=active: _set_active(
            a.workflow_id, _a, a.i_know))

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

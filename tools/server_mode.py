# -*- coding: utf-8 -*-
"""Les eller sett servermodus: BOOK eller PREVIEW.

    python tools/server_mode.py              # hva staar den til naa
    python tools/server_mode.py --json
    python tools/server_mode.py book
    python tools/server_mode.py preview

Modusen avgjoer hvilken RabbitMQ-koe serveren lytter paa og hvilken
DreamPage Flow-pipeline den kjoerer. Den staar i config/flow.json ("mode"),
og leses av flow/worker/config.py.

Hvorfor dette er et eget verktoey og ikke bare "rediger fila":

Et bytte fra `preview` til `book` gjoer at maskinen begynner aa plukke ekte,
betalte bokordre fra `dreampage-jobs`. Det er ikke en innstilling paa linje
med en timeout - det er hva maskinen ER. Her staar det hva som skjer, og
byttet skrives atomisk gjennom den samme koden panelet bruker, slik at en
halvskrevet flow.json ikke sender neste oppstart tilbake til
standardverdiene uten at noen skjoenner hvorfor.

Endringen faar foerst virkning naar flow startes paa nytt:
    .\\dreampage.ps1 restart
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "flow"))
sys.path.insert(0, os.path.join(ROOT, "flow", "worker"))

import config as flow_config  # noqa: E402


def current() -> dict:
    conf = flow_config.load(refresh=True)
    name = flow_config.mode()
    modes = conf.get("modes") or {}
    import pipeline as pipeline_mod
    return {
        "mode": name,
        "queue": flow_config.queue().get("name"),
        "pipeline": pipeline_mod.active_name(),
        "available": sorted(modes),
        "config": str(flow_config.CONFIG_PATH),
        "env_override": os.environ.get("DP_MODE") or None,
    }


def set_mode(name: str) -> dict:
    """Skriv "mode" i config/flow.json - og BARE den.

    Leser FILA, ikke den sammenslaatte konfigurasjonen. flow_config.load()
    gir standardverdiene fra koden med fila lagt oppaa, og aa skrive DEN
    tilbake ville gjort en liten overstyringsfil til en full kopi av
    DEFAULTS. Da er det ikke lenger mulig aa se hva som er valgt paa denne
    maskinen, og en standardverdi som endres i koden ville vaert frosset
    fast i fila uten at noen hadde bedt om det.

    Atomisk skriving: en halvskrevet flow.json ville sendt neste oppstart
    tilbake til standardverdiene uten at noen skjoenner hvorfor.
    """
    if name not in flow_config.MODES:
        raise SystemExit(f"ukjent modus {name!r}. Lov: "
                         f"{', '.join(flow_config.MODES)}")
    path = flow_config.CONFIG_PATH
    try:
        with open(path, encoding="utf-8-sig") as fh:
            on_disk = json.load(fh)
    except FileNotFoundError:
        on_disk = {}
    before = on_disk.get("mode") or flow_config.DEFAULTS["mode"]
    on_disk["mode"] = name

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(on_disk, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, path)

    flow_config.load(refresh=True)
    return {"before": before, "after": name, **current()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default="",
                    help="book eller preview. Utelatt = bare vis.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not args.mode:
        info = current()
    else:
        info = set_mode(args.mode.strip().lower())

    if args.json:
        print(json.dumps(info, ensure_ascii=False))
        return 0

    if args.mode:
        print(f"servermodus: {info['before']} -> {info['after']}")
        print(f"  koe:       {info['queue']}")
        print(f"  pipeline:  {info['pipeline']}")
        print()
        print("Endringen virker foerst etter en omstart av flow:")
        print("  .\\dreampage.ps1 restart")
        if info["after"] == "book":
            print()
            print("MERK: denne maskinen lytter naa paa koen med EKTE, BETALTE")
            print("      bokordre og bygger PDF-er og Gelato-utkast.")
    else:
        print(f"servermodus: {info['mode']}")
        print(f"  koe:       {info['queue']}")
        print(f"  pipeline:  {info['pipeline']}")
        print(f"  fra:       {info['config']}")
        if info["env_override"]:
            print(f"  MERK: DP_MODE={info['env_override']} i miljoeet "
                  f"overstyrer fila")
    return 0


if __name__ == "__main__":
    sys.exit(main())

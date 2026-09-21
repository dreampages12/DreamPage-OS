# -*- coding: utf-8 -*-
"""Hold ComfyUI-GUI-ets workflow-liste lik det systemet FAKTISK kjoerer.

Workflow-lista i GUI-et (`DreamPage-image/user/default/workflows/`) hadde 44
filer. Ingen av dem var produksjonsworkflowen: bokworkflowen ligger i
`books/*/workflow_api.json` og uttrykksvariantene i
`flow/face_variants/workflows/`. Resten var GUI-eksperimenter fra tidligere
generasjoner av pipelinen - `Main-styrken`, `Unsaved Workflow (2..9)`,
`preveiw_drage`. Aa lete etter den riktige i den haugen er hvordan en
operatoer aapner feil graf og tror hun ser produksjonen.

Produksjonsfilene er API-format (`{"9": {"class_type": ...}}`). Frontenden
(1.43.18) forstaar API-format BARE i drag-and-drop-veien - `isApiJson` /
`loadApiJson` finnes kun i `dialogService`. Aapner du en API-fil fra
workflow-lista, kaller den `loadGraphData` rett paa den, finner ingen
`nodes`-liste og tegner et TOMT lerret. Uten feilmelding. Derfor konverterer
dette scriptet i stedet API -> GUI-format.

Noderekkefoelgen (hvilken widget som har hvilken verdi) hentes fra kjoerende
ComfyUI via `/object_info`, ikke fra en liste her. En liste her ville vaert
utdatert neste gang en custom node endret en input.

    python tools/comfy_workflows.py           # vis hva som ville skjedd
    python tools/comfy_workflows.py --sync    # skriv GUI-filer + arkiver resten
    python tools/comfy_workflows.py --check    # exit 1 hvis lista er ute av takt

`--check` snakker ikke med ComfyUI: hver genererte fil baerer sha1-en til
kilden sin i `extra.dreampage`, saa sjekken er ren filsammenligning.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "flow"))
import paths  # noqa: E402  (etter sys.path - flow/paths.py eier alle stier)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = paths.ROOT
WF_DIR = paths.COMFY_USER / "default" / "workflows"
ARCHIVE = ROOT / "state" / "comfy-workflows-arkiv"

# Filer som faar staa i lista selv om de ikke er generert herfra.
#
# Head_Hair_Mask_FullSize_Fast.json er operatoerverktoeyet som lager
# headmasken til en NY bok (se nodes/README.md). Den er ikke i ordreveien, men
# den er i arbeidsveien til et menneske - arkiverer man den, blir en ny bok
# vanskeligere aa sette opp enn den trenger aa vaere.
KEEP = ("Head_Hair_Mask_FullSize_Fast.json", "LAB-DreamPage-HeadSwap.json")

# Typenavn som er en VERDI (widget), ikke en ledning. Alt annet - IMAGE,
# MODEL, CLIP, LATENT, MASK, SEGS ... - er en ledning mellom to noder.
WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}

COL_W = 420          # bredde per kolonne i utlegget
ROW_GAP = 40


# ---------------------------------------------------------------------------
# Kildene
# ---------------------------------------------------------------------------
def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def sources() -> list[tuple[str, Path, str]]:
    """[(filnavn i GUI-lista, kildefil, sha1)] - ropende hvis noe mangler.

    Alle boeker deler samme workflow_api.json i dag. Det er en egenskap ved
    dagens produksjon, ikke en garanti: skulle en bok avvike, skal det ikke
    stille velges en av dem. Da faar hver variant sitt eget navn, og det sies.
    """
    out: list[tuple[str, Path, str]] = []

    books = sorted((ROOT / "books").glob("*/workflow_api.json"))
    if not books:
        raise SystemExit("FEIL: fant ingen books/*/workflow_api.json under %s" % ROOT)
    groups: dict[str, list[Path]] = {}
    for wf in books:
        groups.setdefault(_sha1(wf.read_bytes()), []).append(wf)
    if len(groups) == 1:
        digest, wfs = next(iter(groups.items()))
        out.append(("DreamPage-bok.json", wfs[0], digest))
    else:
        print("ADVARSEL: boekene deler IKKE samme workflow_api.json lenger - "
              "%d ulike varianter. Hver faar sin egen fil i lista:" % len(groups))
        for digest, wfs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            slug = wfs[0].parent.name
            print("  %-40s %d bok(er): %s"
                  % (slug, len(wfs), ", ".join(w.parent.name for w in wfs)))
            out.append(("DreamPage-bok-%s.json" % slug, wfs[0], digest))

    var_dir = ROOT / "flow" / "face_variants" / "workflows"
    variants = sorted(var_dir.glob("*.json"))
    if not variants:
        raise SystemExit("FEIL: fant ingen variantworkflows i %s" % var_dir)
    for wf in variants:
        out.append(("DreamPage-variant-%s.json" % wf.stem, wf,
                    _sha1(wf.read_bytes())))
    return out


def object_info() -> dict:
    """Nodedefinisjonene fra den KJOERENDE ComfyUI-en.

    Uten den kan ikke widget-rekkefoelgen utledes, og en gjetning her gir en
    graf der verdiene staar paa feil widget - som ser riktig ut til noen
    lagrer den. Derfor: ingen fallback, den skal kaste.
    """
    url = paths.COMFY_URL.rstrip("/") + "/object_info"
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise SystemExit(
            "FEIL: naadde ikke %s (%s).\nComfyUI maa kjoere - widget-rekkefoelgen "
            "kommer derfra, ikke fra en liste i dette scriptet.\n"
            "Start med: .\\dreampage.ps1 up" % (url, exc))


# ---------------------------------------------------------------------------
# API-format -> GUI-format
# ---------------------------------------------------------------------------
def _input_specs(defn: dict) -> list[tuple[str, list]]:
    """[(navn, spec)] i den rekkefoelgen frontenden bygger widgets i."""
    spec = defn.get("input") or {}
    order = defn.get("input_order") or {}
    out: list[tuple[str, list]] = []
    for section in ("required", "optional"):
        names = order.get(section) or list((spec.get(section) or {}).keys())
        for name in names:
            entry = (spec.get(section) or {}).get(name)
            if entry is not None:
                out.append((name, entry))
    return out


def _is_widget(entry) -> bool:
    kind = entry[0] if isinstance(entry, (list, tuple)) and entry else entry
    if isinstance(kind, list):          # combo: ["a", "b", ...]
        return True
    return str(kind) in WIDGET_TYPES


def _opts(entry) -> dict:
    if isinstance(entry, (list, tuple)) and len(entry) > 1 and isinstance(entry[1], dict):
        return entry[1]
    return {}


def _default(entry):
    opts = _opts(entry)
    if "default" in opts:
        return opts["default"]
    kind = entry[0] if isinstance(entry, (list, tuple)) and entry else entry
    if isinstance(kind, list):
        return kind[0] if kind else ""
    return {"INT": 0, "FLOAT": 0.0, "STRING": "", "BOOLEAN": False}.get(str(kind), None)


def _slot_type(entry) -> str:
    kind = entry[0] if isinstance(entry, (list, tuple)) and entry else entry
    return "COMBO" if isinstance(kind, list) else str(kind)


def _order(api: dict) -> list[str]:
    """Topologisk rekkefoelge. En ring stopper ikke jobben - resten bakerst."""
    deps = {nid: {str(v[0]) for v in (node.get("inputs") or {}).values()
                  if isinstance(v, list) and len(v) == 2 and str(v[0]) in api}
            for nid, node in api.items()}
    done: list[str] = []
    seen: set[str] = set()
    while True:
        ready = [n for n in api if n not in seen and deps[n] <= seen]
        if not ready:
            break
        for n in sorted(ready, key=lambda x: (len(x), x)):
            done.append(n)
            seen.add(n)
    done += [n for n in api if n not in seen]
    return done


def to_gui(api: dict, oi: dict, label: str, src: Path, digest: str) -> dict:
    """Bygg en GUI-graf av en API-graf. Ukjent nodeklasse -> SystemExit."""
    missing = sorted({str(n.get("class_type")) for n in api.values()
                      if isinstance(n, dict) and str(n.get("class_type")) not in oi})
    if missing:
        raise SystemExit(
            "FEIL: %s bruker nodeklasser ComfyUI ikke kjenner: %s\n"
            "Da ville ogsaa en ordre blitt avvist med \"Cannot execute because "
            "node X does not exist\". Kjoer: python tools/node_requirements.py --check"
            % (src, ", ".join(missing)))

    order = _order(api)
    depth: dict[str, int] = {}
    for nid in order:
        ups = [str(v[0]) for v in (api[nid].get("inputs") or {}).values()
               if isinstance(v, list) and len(v) == 2 and str(v[0]) in api]
        depth[nid] = max((depth.get(u, 0) + 1 for u in ups), default=0)

    num = {nid: i + 1 for i, nid in enumerate(order)}
    nodes: dict[str, dict] = {}
    col_y: dict[int, float] = {}
    # Inputnavn API-grafen setter, men noden ikke har lenger. ComfyUI ignorerer
    # dem stille (LanPaint dopte om "More Info..." til "LanPaint_Info"). Det er
    # ufarlig, men det skal SIES en gang - ellers oppdages en reell omdoeping
    # av en input aldri.
    ukjente: list[str] = []

    for nid in order:
        api_node = api[nid]
        cls = str(api_node.get("class_type"))
        defn = oi[cls]
        specs = _input_specs(defn)
        linked = {k: v for k, v in (api_node.get("inputs") or {}).items()
                  if isinstance(v, list) and len(v) == 2 and str(v[0]) in api}
        given = api_node.get("inputs") or {}

        in_slots, widgets_values, n_widgets = [], [], 0
        for name, entry in specs:
            widget = _is_widget(entry)
            force = bool(_opts(entry).get("forceInput"))
            if widget and not force:
                n_widgets += 1
                # Er verdien en ledning, eier en annen node den. Staar den
                # ikke i API-grafen i det hele tatt, brukte ComfyUI
                # standardverdien. Begge tilfeller MAA fylles - en None her
                # forskyver ikke bare seg selv, den forskyver alle widgets
                # etter seg, og da staar ordreverdiene paa feil felt.
                if name in linked or name not in given:
                    widgets_values.append(_default(entry))
                else:
                    widgets_values.append(given[name])
                # Legacy-formatet frontenden migrerer fra har ett ekstra felt
                # etter en seed-widget. Treffer vi den lengden, fjerner
                # migrateWidgetsValues() feltet selv - og verdiene havner paa
                # riktig widget. Treffer vi den ikke, brukes lista som den er.
                if _opts(entry).get("control_after_generate"):
                    widgets_values.append("fixed")
            elif widget and force:
                widgets_values.append(None)
            if name in linked or not widget:
                slot = {"name": name, "type": _slot_type(entry),
                        "link": None, "localized_name": name}
                if widget:
                    slot["widget"] = {"name": name}
                in_slots.append(slot)

        kjente = {name for name, _ in specs}
        ukjente += ["%s (%s).%s" % (nid, cls, k) for k in given if k not in kjente]

        out_types = list(defn.get("output") or [])
        out_names = list(defn.get("output_name") or []) or out_types
        outputs = [{"name": (out_names[i] if i < len(out_names) else out_types[i]),
                    "type": out_types[i], "links": [], "slot_index": i}
                   for i in range(len(out_types))]

        title = ((api_node.get("_meta") or {}).get("title")
                 or defn.get("display_name") or cls)
        height = 30 + 26 * n_widgets + 20 * len(in_slots)
        col = depth[nid]
        y = col_y.get(col, 60.0)
        col_y[col] = y + height + ROW_GAP

        nodes[nid] = {
            "id": num[nid], "type": cls, "pos": [60.0 + col * COL_W, y],
            "size": [340, height], "flags": {}, "order": order.index(nid),
            "mode": 0, "inputs": in_slots, "outputs": outputs,
            # Bare "Node name for S&R". cnr_id/aux_id er Manager-ens
            # registernoekler, og en gjettet verdi der gir "missing node pack"
            # i GUI-et for en node som er installert.
            "properties": {"Node name for S&R": cls},
            "widgets_values": widgets_values, "title": title,
        }

    if ukjente:
        print("    merk: %s setter input(er) noden ikke har lenger: %s"
              % (label, ", ".join(ukjente)))

    links = []
    for nid in order:
        for name, val in (api[nid].get("inputs") or {}).items():
            if not (isinstance(val, list) and len(val) == 2 and str(val[0]) in api):
                continue
            src_id, src_slot = str(val[0]), int(val[1])
            target = nodes[nid]
            slot_i = next((i for i, s in enumerate(target["inputs"])
                           if s["name"] == name), None)
            if slot_i is None:
                continue
            src_node = nodes[src_id]
            if src_slot >= len(src_node["outputs"]):
                raise SystemExit(
                    "FEIL: %s: node %s (%s) leser utgang %d, men %s har bare %d"
                    % (src, nid, api[nid].get("class_type"), src_slot,
                       src_node["type"], len(src_node["outputs"])))
            lid = len(links) + 1
            typ = src_node["outputs"][src_slot]["type"]
            target["inputs"][slot_i]["link"] = lid
            src_node["outputs"][src_slot]["links"].append(lid)
            links.append([lid, src_node["id"], src_slot, target["id"], slot_i, typ])

    return {
        "id": "dreampage-" + digest[:12],
        "revision": 0,
        "last_node_id": len(nodes),
        "last_link_id": len(links),
        "nodes": [nodes[n] for n in order],
        "links": links,
        "groups": [],
        "config": {},
        "extra": {
            "dreampage": {
                # Hvorfor dette staar i fila: aapner en operatoer grafen,
                # endrer en verdi og lagrer, blir endringen borte neste
                # --sync. Kilden er API-fila, ikke denne.
                "generert_av": "tools/comfy_workflows.py",
                "kilde": str(src.relative_to(ROOT)).replace("\\", "/"),
                "kilde_sha1": digest,
                "merk": ("Generert visning av produksjonsworkflowen. Endringer "
                         "her brukes IKKE av pipelinen og overskrives ved neste "
                         "sync - rediger kilden."),
            }
        },
        "version": 0.4,
    }


# ---------------------------------------------------------------------------
# Kommandoene
# ---------------------------------------------------------------------------
def planned() -> tuple[list[tuple[str, Path, str]], list[Path]]:
    src = sources()
    want = {name for name, _, _ in src} | set(KEEP)
    extra = sorted(p for p in WF_DIR.glob("*.json") if p.name not in want)
    return src, extra


def cmd_sync(dry: bool) -> int:
    src, extra = planned()
    oi = None if dry else object_info()

    if extra:
        print("%s %d GUI-eksperiment(er) -> %s"
              % ("Ville arkivert" if dry else "Arkiverer", len(extra), ARCHIVE))
        if not dry:
            ARCHIVE.mkdir(parents=True, exist_ok=True)
        for p in extra:
            print("  %s" % p.name)
            if dry:
                continue
            dest = ARCHIVE / p.name
            if dest.exists():                       # aldri overskriv et arkiv
                stem, i = dest.stem, 2
                while dest.exists():
                    dest = ARCHIVE / ("%s (%d)%s" % (stem, i, p.suffix))
                    i += 1
            shutil.move(str(p), str(dest))

    for name in KEEP:
        if (WF_DIR / name).exists():
            print("Beholder operatoerverktoey: %s" % name)
        else:
            print("ADVARSEL: %s staar i KEEP, men finnes ikke i %s" % (name, WF_DIR))

    print("%s %d produksjonsworkflow(er):"
          % ("Ville skrevet" if dry else "Skriver", len(src)))
    for name, path, digest in src:
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        if dry:
            print("  %-34s <- %s" % (name, rel))
            continue
        api = json.loads(path.read_text(encoding="utf-8-sig"))
        gui = to_gui(api, oi, name, path, digest)
        WF_DIR.mkdir(parents=True, exist_ok=True)
        (WF_DIR / name).write_text(json.dumps(gui, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
        print("  %-34s <- %-52s %d noder, %d ledninger"
              % (name, rel, len(gui["nodes"]), len(gui["links"])))
    if dry:
        print("\n(ingenting er endret - kjoer med --sync)")
    return 0


def cmd_check() -> int:
    src, extra = planned()
    bad = []
    for name, path, digest in src:
        target = WF_DIR / name
        if not target.exists():
            bad.append("%s mangler i workflow-lista" % name)
            continue
        try:
            got = ((json.loads(target.read_text(encoding="utf-8-sig"))
                    .get("extra") or {}).get("dreampage") or {}).get("kilde_sha1")
        except (OSError, ValueError) as exc:
            bad.append("%s kunne ikke leses (%s)" % (name, exc))
            continue
        if got != digest:
            bad.append("%s er bygget fra en eldre %s"
                       % (name, str(path.relative_to(ROOT)).replace("\\", "/")))
    for p in extra:
        bad.append("%s ligger i lista uten aa vaere en produksjonsworkflow" % p.name)
    if bad:
        print("Workflow-lista er ute av takt med produksjonen:")
        for line in bad:
            print("  %s" % line)
        print("\nKjoer: python tools/comfy_workflows.py --sync")
        return 1
    print("OK: workflow-lista viser %d produksjonsworkflow(er) og ingenting annet."
          % len(src))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sync", action="store_true",
                    help="skriv GUI-filene og arkiver resten")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 hvis lista ikke stemmer (snakker ikke med ComfyUI)")
    args = ap.parse_args()
    if args.check:
        return cmd_check()
    return cmd_sync(dry=not args.sync)


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""Les tittel-tabellene ut av n8n-noden og skriv flow/worker/book_titles.py.

Tabellen har 78 tittelvarianter paa fire spraak. Aa skrive den av for haand er
uakseptabelt: en typo sender en kunde feil bok.

FUNN 2026-09-15: den kjoerende noden inneholder ZERO ikke-ASCII tegn. 16
oppfoeringer har en literal `?` der ae/oe/aa skulle staatt -

    "p?skejakten", "enhj?rning", "enhj?rningsdalen", "sj?jungfru",
    "modet i hj?rtat", "den dolda v?rlden", "fotbollsstj?rna", ...

- og de kan aldri matche en ekte tittel. Det ser ut som en cp1252-runde:
noen leste noden, skrev den tilbake med feil encoding, og BEGGE stavemaatene
("enhjoerning" og "enhjorning") kollapset til samme oedelagte noekkel. Derfor
staar de i par i kilden.

I dag redder handle-veien ordren: WooCommerce sender ogsaa `book_slug`
("enhjorningsdalen"), som slaar opp i HANDLE_TO_SLUG foer tittelen i det hele
tatt proeves. Tittel-tabellen er altsaa delvis doedvekt uten at noen har merket
det.

Fiksen er ikke aa gjette hva som stod: hver oedelagt noekkel har allerede en
ASCII-foldet tvilling i tabellen ("paskejakten", "enhjorning", "sjojungfru"...).
Derfor droppes `?`-noeklene, og book_titles.normalize() folder baade tabellen
og oppslaget (ae->ae, oe->o, aa->a, ae->a, oe->o) saa begge stavemaatene
treffer. Det som var doedt blir levende, uten at noe maa gjettes.

    python extract_title_map.py            # fra n8n sin database (read-only)
    python extract_title_map.py --check    # bare rapporter, skriv ingenting
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "flow" / "worker" / "book_titles.py"
WF_ID = "xy8qiRUzcBpH52CI"
NODE = "Load Book Config"


def node_source() -> str:
    db = os.path.expanduser(r"~/.n8n/database.sqlite")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        raw = con.execute("select nodes from workflow_entity where id=?", (WF_ID,)).fetchone()
    finally:
        con.close()
    if not raw:
        raise SystemExit(f"fant ikke workflow {WF_ID}")
    for node in json.loads(raw[0]):
        if node.get("name") == NODE:
            return node["parameters"]["jsCode"]
    raise SystemExit(f"fant ikke noden {NODE!r}")


def parse_map(code: str, name: str) -> tuple[dict, list[str]]:
    """Returnerer (tabell uten oedelagte noekler, de oedelagte noeklene)."""
    m = re.search(r"const " + name + r" = \{(.*?)\n\};", code, re.S)
    if not m:
        raise SystemExit(f"fant ikke {name} i noden")
    table: dict[str, str] = {}
    broken: list[str] = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        hit = re.match(r'"([^"]*)"\s*:\s*"([^"]*)"\s*,?\s*(?://.*)?$', line)
        if not hit:
            raise SystemExit(f"uparset linje i {name}: {line!r}")
        key, value = hit.group(1), hit.group(2)
        if "?" in key:
            broken.append(key)
            continue
        table[key] = value
    return table, broken


HEADER = '''# -*- coding: utf-8 -*-
"""Tittel- og handle-oppslag: det WooCommerce sender -> bokas MAPPENAVN.

GENERERT av tools/migrate/extract_title_map.py, hentet fra noden
"{node}" i n8n-workflowen {wf} den {date}.
Ikke rediger her - rediger kilden, eller gjoer tabellen selvstendig naar n8n
er borte.

Norsk, engelsk og svensk tittel peker paa SAMME bokmappe. Det er bare
textScript som varierer med spraaket.

{broken_note}
"""
from __future__ import annotations

import re
import unicodedata


# ---------------------------------------------------------------------------
# Normalisering
#
# Slugene folder ae/oe/aa til ASCII paa den maaten mappenavnene alt gjoer:
# "moetet i hjertet" -> motet-i-hjertet, "enhjoerning" -> enhjorning,
# "paaskejakten" -> paskejakten. Svensk ae/oe foelger samme regel.
#
# Baade tabellen og oppslaget normaliseres, saa "Enhjoerningsdalen",
# "enhjorningsdalen" og "ENHJOERNINGSDALEN" treffer samme bok. Det er ogsaa
# det som gjoer de 16 oedelagte n8n-noeklene unoedvendige.
# ---------------------------------------------------------------------------
_FOLD = {{
    "\\u00e6": "ae", "\\u00f8": "o", "\\u00e5": "a",     # ae oe aa
    "\\u00e4": "a", "\\u00f6": "o", "\\u00fc": "u",      # ae oe ue (svensk/tysk)
    "\\u00e9": "e", "\\u00e8": "e", "\\u00ea": "e",
}}


def normalize(value: str) -> str:
    """Nedkoket form for oppslag: smaa bokstaver, ASCII-foldet, ett mellomrom."""
    text = unicodedata.normalize("NFC", str(value or "")).strip().lower()
    text = "".join(_FOLD.get(ch, ch) for ch in text)
    # Det som er igjen av aksenter strippes; "café" og "cafe" er samme bok.
    text = "".join(ch for ch in unicodedata.normalize("NFD", text)
                   if not unicodedata.combining(ch))
    return re.sub(r"\\s+", " ", text)


'''


def render(titles: dict, handles: dict, gendered: list[str], broken: list[str]) -> str:
    note = ("De 16 oedelagte noeklene fra n8n (literal `?` der ae/oe/aa skulle "
            "staatt) er\nbevisst IKKE tatt med. Hver av dem hadde allerede en "
            "ASCII-foldet tvilling\ni tabellen, og normalize() under gjoer at "
            "begge stavemaatene treffer.\nDe var: " + ", ".join(sorted(set(broken))))
    out = HEADER.format(node=NODE, wf=WF_ID,
                        date=datetime.date.today().isoformat(),
                        broken_note=note)
    out += "_TITLES_RAW = " + json.dumps(titles, ensure_ascii=False, indent=4) + "\n\n"
    out += "_HANDLES_RAW = " + json.dumps(handles, ensure_ascii=False, indent=4) + "\n\n"
    out += ("# Titler der samme navn selges i to utgaver, og bare `gender` i\n"
            "# payloaden skiller dem. Mangler gender skal ordren STOPPE, ikke gjette.\n")
    out += "_GENDERED_RAW = " + json.dumps(sorted(gendered), ensure_ascii=False, indent=4) + "\n\n"
    out += '''
# Normaliserte oppslagstabeller. Bygges én gang ved import.
TITLE_TO_SLUG = {normalize(k): v for k, v in _TITLES_RAW.items()}
HANDLE_TO_SLUG = {normalize(k): v for k, v in _HANDLES_RAW.items()}
GENDERED_TITLES = {normalize(t) for t in _GENDERED_RAW}
'''
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="rapporter, skriv ingenting")
    args = ap.parse_args()

    code = node_source()
    titles, broken_t = parse_map(code, "TITLE_TO_SLUG")
    handles, broken_h = parse_map(code, "HANDLE_TO_SLUG")
    gm = re.search(r"const GENDERED_TITLES = new Set\(\[(.*?)\]\)", code, re.S)
    gendered = re.findall(r'"([^"]*)"', gm.group(1)) if gm else []
    broken = broken_t + broken_h

    print(f"TITLE_TO_SLUG   {len(titles)} brukbare, {len(broken_t)} oedelagte")
    print(f"HANDLE_TO_SLUG  {len(handles)} brukbare, {len(broken_h)} oedelagte")
    print(f"GENDERED_TITLES {len(gendered)}")
    non_ascii = sum(1 for k in list(titles) + list(handles) if any(ord(c) > 127 for c in k))
    print(f"noekler med ekte ikke-ASCII i n8n: {non_ascii}"
          + ("  <- noden er mangled, se modulens docstring" if non_ascii == 0 else ""))
    if broken:
        print("\noedelagte noekler (droppet, dekket av normalize()):")
        for k in sorted(set(broken)):
            print(f"    {k}")

    if args.check:
        return 0
    OUT.write_text(render(titles, handles, gendered, broken), encoding="utf-8")
    print(f"\nskrevet {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

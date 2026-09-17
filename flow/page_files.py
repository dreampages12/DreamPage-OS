# -*- coding: utf-8 -*-
"""Hvilken fil i en ordres input/ er egentlig side N - og er den personalisert?

To spoersmaal som ser trivielle ut, men som ikke er det:

1. **Hvilket filnavn?** `config.json` sier `template_image: "04(bok).png"`,
   men for de delte sidene (kvadratpar) heter den faktiske fila
   `04-right(bok).png`. Fasiten er `PAGE_TO_BASE_STEM` i bokas eget
   `prepare_order_<bok>.py` - det er den samme tabellen prepare selv bruker
   naar den plasserer ComfyUI-resultatet.

   Gjorde vi dette med `template_image` alene, meldte hver delte side seg
   som "MANGLER i input/". Det ga tre falske alarmer per fotball-ordre - og
   stoy er presis det som gjorde at tolv EKTE advarsler ikke ble oppdaget i
   ordre 1528.

2. **Er den raa?** En side som er byte-identisk med malen ble aldri
   faceswappet. Malen finnes to steder som ikke alltid er like
   (`books/<slug>/base/` og rot-`input/`), og i flere hudfarge- og
   haarvarianter. Alle maa sjekkes.

For de hoeyre halvdelene av delte sider finnes det ingen hel mal aa
sammenligne med - `base/` har bare `-left`. Der er fravaer feilmodusen:
mangler comfy-resultatet, legger prepare aldri noen `-right` inn i det hele
tatt. Det fanges av `mangler`.
"""
from __future__ import annotations

import ast
import hashlib
import os

import paths

# Stier gaar gjennom paths, som ogsaa respekterer DP_ROOT. Utledet vi rota
# fra __file__ her, pekte testene sine oppslag rett inn i produksjonstreet -
# og en raa mal i sandkassa ble da meldt som "ingen mal aa sammenligne med".
ROOT = str(paths.ROOT)
TEMPLATE_DIR = str(paths.INPUT)

# Varianter av samme mal. En bok bygget for et morkt barn bruker
# "01(styrken)mork.png" som mal, og skal ikke regnes som raa mal bare fordi
# den ikke er identisk med standardmalen.
VARIANT_SUFFIXES = ("", "mixed", "mork", "kort", "kortmixed", "kortmork")
IMAGE_EXTS = (".png", ".webp", ".jpg", ".jpeg")

_STEM_CACHE: dict[str, dict[str, str]] = {}


def md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def base_stem_map(book_slug: str) -> dict[str, str]:
    """`PAGE_TO_BASE_STEM` fra bokas prepare-script, lest med AST.

    AST og ikke import: scriptet kjoerer `main()`-logikk og loeser stier ut
    fra `__file__` naar det lastes. Vi vil bare ha tabellen.
    """
    if book_slug in _STEM_CACHE:
        return _STEM_CACHE[book_slug]

    path = os.path.join(ROOT, "books", book_slug, "script",
                        f"prepare_order_{book_slug}.py")
    out: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), path)
    except (OSError, SyntaxError):
        _STEM_CACHE[book_slug] = out
        return out

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "PAGE_TO_BASE_STEM" not in names:
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        for key, value in zip(node.value.keys, node.value.values):
            if isinstance(key, ast.Constant) and isinstance(value, ast.Constant):
                if isinstance(key.value, str) and isinstance(value.value, str):
                    out[key.value] = value.value

    _STEM_CACHE[book_slug] = out
    return out


def page_stem(book_slug: str, page: dict) -> str:
    """Filnavn-stem (uten filending) for siden, slik prepare navngir den."""
    key = page.get("page_key") or ""
    mapped = base_stem_map(book_slug).get(key)
    if mapped:
        return mapped
    return os.path.splitext(page.get("template_image") or "")[0]


def find_by_stem(folder: str, stem: str) -> str | None:
    """`<folder>/<stem><en av IMAGE_EXTS>` - filendingen varierer per bok."""
    if not stem or not os.path.isdir(folder):
        return None
    for ext in IMAGE_EXTS:
        cand = os.path.join(folder, stem + ext)
        if os.path.isfile(cand):
            return cand
    return None


def template_hashes(stem: str, book_base: str) -> dict[str, str]:
    """{sti: md5} for malen og variantene, fra BEGGE kildene.

    `books/<slug>/base/` er det prepare kopierer fra; rot-`input/` er det
    ComfyUI laster. For den-skjulte-styrken er `01(styrken).png` identisk i
    begge, mens `forside(styrken).png` er ULIK - sjekker vi bare den ene,
    gaar de fleste raa malene rett igjennom.
    """
    out: dict[str, str] = {}
    for folder in (book_base, TEMPLATE_DIR):
        if not folder or not os.path.isdir(folder):
            continue
        for suffix in VARIANT_SUFFIXES:
            cand = find_by_stem(folder, stem + suffix)
            if cand:
                out[cand] = md5(cand)
    return out


def audit_page(info: dict, page: dict) -> dict:
    """Status for en side: ok / mangler / raa / usikker.

    `usikker` = fila finnes, men det finnes ingen mal aa sammenligne med
    (typisk hoeyre halvdel av en delt side). Den er IKKE en feil: skip-prepare
    kan bare bevare det som ligger der, og kan aldri legge inn en raa mal.
    """
    slug = info.get("book_slug") or ""
    stem = page_stem(slug, page)
    found = find_by_stem(info["input_dir"], stem)
    row = {"page_key": page.get("page_key") or "?", "stem": stem,
           "path": found, "raw_as": None}

    if not found:
        row["status"] = "mangler"
        return row

    book_base = os.path.join(ROOT, "books", slug, "base")
    templates = template_hashes(stem, book_base)
    if not templates:
        row["status"] = "usikker"
        return row

    digest = md5(found)
    for tpath, thash in templates.items():
        if thash == digest:
            row["status"] = "raa"
            row["raw_as"] = os.path.basename(tpath)
            return row

    row["status"] = "ok"
    return row


def audit_input(info: dict) -> list[dict]:
    """Radene for alle sider i config.json, i sidenes rekkefoelge."""
    pages = (info.get("config") or {}).get("pages") or []
    return [audit_page(info, p) for p in pages if p.get("page_key")]


def unusable(rows: list[dict]) -> list[dict]:
    """Sidene som IKKE kan brukes som de er - de maa rendres paa nytt."""
    return [r for r in rows if r["status"] in ("mangler", "raa")]

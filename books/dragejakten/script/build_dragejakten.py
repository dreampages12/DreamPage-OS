# -*- coding: utf-8 -*-
"""Skriver den nye Dragejakten-historien inn i alle fem tekstscriptene.

Idempotent: kan kjoeres om igjen. Tre ting patches i hver fil:

  1. hele `pages: List[Dict[str, Any]] = [ ... ]`-literalen i build_pages
  2. `_DREAMPAGE_TRANSLATIONS` (kun nn / en-US / en-GB / sv)
  3. `_dp_layout_offsets` + `_dp_mark_backdrop` - de per-side-finjusteringene
     som var tunet mot de GAMLE bildene og bommer paa de nye

Kjoer:  python build_dragejakten.py --apply
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from story_dragejakten import (  # noqa: E402
    PAGES,
    COVER_TITLE_NB,
    INTRO_NB,
    INTRO_TR,
    BAKSIDE_NB,
    BAKSIDE_TR,
)

SCRIPT_ROOT = r"C:\ComfyUI\script"
TARGETS = {
    "nb": os.path.join(SCRIPT_ROOT, "nb", "dragejakten-text-nb.py"),
    "nn": os.path.join(SCRIPT_ROOT, "nn", "dragejakten-text-nn.py"),
    "en-US": os.path.join(SCRIPT_ROOT, "en-US", "dragejakten-text-en-US.py"),
    "en-GB": os.path.join(SCRIPT_ROOT, "en-GB", "dragejakten-text-en-GB.py"),
    "sv": os.path.join(SCRIPT_ROOT, "sv", "dragejakten-text-sv.py"),
}
TR_LANG = {"nn": "nn", "en-US": "en", "en-GB": "en", "sv": "sv"}

# Lyse/travle halvsider som trenger tyngre plate bak teksten
STRONG_PAGES = sorted(p["n"] for p in PAGES if p["strong"])


def q(text: str) -> str:
    """Norsk kildetekst -> en kjede av python-strenger, en per linje."""
    lines = text.split("\n")
    out = []
    for i, line in enumerate(lines):
        suffix = "\\n" if i < len(lines) - 1 else ""
        body = line.replace("\\", "\\\\").replace('"', '\\"')
        out.append('                    "%s%s"' % (body, suffix))
    return "\n".join(out)


def key_of(nb_text: str) -> str:
    """Oppslagsnoekkelen i _DREAMPAGE_TRANSLATIONS."""
    for token in ("[NAVN]", "[ NAVN ]", "(navn)", "(Navn)"):
        nb_text = nb_text.replace(token, "{name}")
    return nb_text


def pylit(s: str) -> str:
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


# ---------------------------------------------------------------- pages-literal
def build_pages_literal() -> str:
    out = []
    add = out.append
    add("    pages: List[Dict[str, Any]] = [")
    add("        {")
    add('            "filename": "forside(dragejakten).png",')
    add('            "type": "cover",')
    add('            "text": p("%s"),' % COVER_TITLE_NB.replace("\n", "\\n"))
    add("        },")
    add("        {")
    add('            "filename": "ryggrad.png",')
    add('            "type": "cover",')
    add("        },")
    add("")
    add("        # Introside")
    add("        {")
    add('            "type": "blank",')
    add('            "side": "right",')
    add('            "text": p("%s"),' % COVER_TITLE_NB.replace("\n", "\\n"))
    add('            "blocks": [{')
    add('                "text": p(')
    add(q(INTRO_NB))
    add("                ),")
    add('                "font_size": 50,')
    add('                "color": "#111111",')
    add('                "y_offset": 420,')
    add("            }],")
    add("        },")
    add("")

    for page in PAGES:
        add("        # Side %d" % page["n"])
        add("        {")
        add('            "filename": "%02d(dragejakten).png",' % page["n"])
        add('            "type": "inner",')
        add('            "side": "%s",' % page["side"])
        add('            "blocks": [{')
        add('                "text": p(')
        add(q(page["nb"]))
        add("                ),")
        add('                "font_size": 30,')
        add('                "color": "#FFFFFF",')
        add('                "highlights": [%s],' % ", ".join(pylit(h) for h in page["hl"]))
        add("            }],")
        add("        },")
        add("")

    add("        # EKSTRA BLANK SISTE INNERSIDE")
    add("        {")
    add('            "filename": "blank-back.png",')
    add('            "type": "inner",')
    add('            "side": "left",')
    add('            "blank_only": True')
    add("        },")
    add("        # PER-BOK LASTPAGE - kommer ETTER blank-back, lastes fra script/lastpages/<locale>")
    add("        {")
    add('            "filename": "Lastpage(drage).png",')
    add('            "type": "inner",')
    add('            "side": "right",')
    add('            "blank_only": True')
    add("        },")
    add("")
    add("        # Bakside")
    add("        {")
    add('            "filename": "bakside(dragejakten).png",')
    add('            "type": "cover",')
    add('            "side": "left",')
    add('            "blocks": [{')
    add('                "text": p(')
    add(q(BAKSIDE_NB))
    add("                ),")
    add('                "font_size": 46,')
    add('                "color": "#FFFFFF",')
    add('                "highlights": ["(navn)", "drage", "fotspor", "mot", "Dragejakten", "vennskap", "fjellene"],')
    add("            }],")
    add("        },")
    add("    ]")
    return "\n".join(out)


PAGES_RE = re.compile(
    r"[ \t]*pages: List\[Dict\[str, Any\]\] = \[.*?\n[ \t]*\][ \t]*\n(?=\s*\n\s*return pages)",
    re.S,
)


def patch_pages(src: str) -> str:
    new = build_pages_literal() + "\n"
    out, n = PAGES_RE.subn(lambda _m: new, src, count=1)
    if n != 1:
        raise SystemExit("Fant ikke pages-literalen (traff %d ganger)" % n)
    return out


# ------------------------------------------------------------------ oversetting
TRANS_RE = re.compile(r"_DREAMPAGE_TRANSLATIONS = \{.*?\n\}\n", re.S)


def existing_cover_translation(src: str, lang_key: str):
    """Behold den eksisterende tittel-oversettelsen - den er tunet mot logoen."""
    m = re.search(
        r'^\s*"\{name\} og\\nDragejakten":\s*(".*?"),\s*$',
        src,
        re.M,
    )
    return m.group(1) if m else None


def build_translations(src: str, lang: str) -> str:
    tr_lang = TR_LANG[lang]
    rows = []
    cover = existing_cover_translation(src, tr_lang)
    if cover:
        rows.append('  %s: %s,' % (pylit(key_of(COVER_TITLE_NB)), cover))
    rows.append('  %s: %s,' % (pylit(key_of(INTRO_NB)), pylit(INTRO_TR[tr_lang])))
    for page in PAGES:
        rows.append('  %s: %s,' % (pylit(key_of(page["nb"])), pylit(page[tr_lang])))
    rows.append('  %s: %s' % (pylit(key_of(BAKSIDE_NB)), pylit(BAKSIDE_TR[tr_lang])))
    return (
        "_DREAMPAGE_TRANSLATIONS = {\n" + "\n".join(rows) + "\n}\n"
    )


def patch_translations(src: str, lang: str) -> str:
    new = build_translations(src, lang)
    out, n = TRANS_RE.subn(lambda _m: new, src, count=1)
    if n != 1:
        raise SystemExit("[%s] Fant ikke _DREAMPAGE_TRANSLATIONS (traff %d)" % (lang, n))
    return out


# ------------------------------------------------------------------- layout
LAYOUT_RE = re.compile(
    r"def _dp_layout_offsets\(filename: str\):.*?"
    r"(?=\n\ndef _dp_split_inner_story_blocks)",
    re.S,
)

LAYOUT_NEW = '''def _dp_layout_offsets(filename: str):
    # Nullstilt 2026-09-04 sammen med de nye innersidene. De gamle
    # per-side-justeringene var tunet mot bilder som ikke finnes lenger.
    number = _dp_page_number(filename)
    top_y = 25
    bottom_y = 345
    return number, top_y, bottom_y


def _dp_mark_backdrop(block: dict, filename: str, child_name: str, *, second: bool = False) -> None:
    block["text_backdrop"] = True
    block["color"] = "#FFFFFF"
    block["highlights"] = _dp_auto_highlights(block.get("text", ""), child_name, block.get("highlights", []))
    number = _dp_page_number(filename)
    # Lyse eller travle halvsider trenger tyngre plate bak teksten.
    if number in %s:
        block["text_backdrop_strength"] = "strong"
''' % (tuple(STRONG_PAGES),)


def patch_layout(src: str) -> str:
    out, n = LAYOUT_RE.subn(lambda _m: LAYOUT_NEW.rstrip("\n"), src, count=1)
    if n != 1:
        raise SystemExit("Fant ikke _dp_layout_offsets/_dp_mark_backdrop (traff %d)" % n)
    return out


# --------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="skriv endringene til disk")
    args = ap.parse_args()

    for lang, path in TARGETS.items():
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        out = patch_pages(src)
        if lang != "nb":
            out = patch_translations(out, lang)
        out = patch_layout(out)

        if out == src:
            print("[%-5s] uendret" % lang)
            continue
        if not args.apply:
            print("[%-5s] ville endret %s (%d -> %d tegn)" % (lang, os.path.basename(path), len(src), len(out)))
            continue
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(out)
        print("[%-5s] skrevet %s" % (lang, os.path.basename(path)))

    if args.apply:
        print("\nSterk bakgrunnsplate paa sider: %s" % (STRONG_PAGES,))
        print("Sider (tekstside):")
        for page in PAGES:
            print("  %02d -> %s" % (page["n"], page["side"]))


if __name__ == "__main__":
    main()

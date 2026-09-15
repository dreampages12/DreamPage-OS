# -*- coding: utf-8 -*-
"""Gjoer tekstkolonnen paa innersidene i motet-i-hjertet bredere.

Grunnkolonnen er 400 designenheter (LEFT_X1..LEFT_X2 / RIGHT_X1..RIGHT_X2),
men hver side i build_pages spiser av den med x_offset (20-60) og negativ
width_offset (-40/-60). Netto blir 310-375, og da faller teksten i unoedvendig
mange korte linjer.

Denne patchen legger til en minstebredde som haandheves ETTER at
_dp_split_inner_story_blocks har delt teksten i topp/bunn-blokk: er kolonnen
smalere enn maalet, skyves HOEYREKANTEN utover (width_offset oekes).
Venstrekanten staar stille, saa tekstblokken blir vaerende der den er
komponert mot illustrasjonen - den faar bare loepe litt lenger.

  python tune_innertext_width.py --width 400            (toerrkjoering)
  python tune_innertext_width.py --width 400 --apply
  python tune_innertext_width.py --width 420 --apply    (retune senere)
  python tune_innertext_width.py --revert                (fjern patchen)
"""
from __future__ import annotations

import argparse
import ast
import io
import re
import shutil
from datetime import datetime

LOCALES = ("nb", "nn", "en-US", "en-GB", "sv")
FILES = ["C:/ComfyUI/script/%s/motet-i-hjertet-text-%s.py" % (l, l) for l in LOCALES]

ANCHOR = """    for page in pages:
        for block in page.get("blocks") or []:
            if isinstance(block, dict) and block.get("text"):
                block["highlights"] = _dp_auto_highlights(block.get("text", ""), child_name, block.get("highlights", []))
        _dp_split_inner_story_blocks(page, child_name)
    return pages"""

NEW_CALL = """    for page in pages:
        for block in page.get("blocks") or []:
            if isinstance(block, dict) and block.get("text"):
                block["highlights"] = _dp_auto_highlights(block.get("text", ""), child_name, block.get("highlights", []))
        _dp_split_inner_story_blocks(page, child_name)
        _dp_widen_narrow_blocks(page)
    return pages"""

HELPER = '''# Minste tekstkolonne paa innersider, i designenheter (1536x1024-rommet).
# Grunnkolonnen er 400; per-side x_offset/width_offset trakk den ned til
# 310-375, som ga unoedvendig mange linjer. Hoeyrekanten skyves ut til
# denne bredden; venstrekanten roeres ikke.
DP_MIN_TEXT_WIDTH = %(width)d


def _dp_block_column(block: dict, side: str):
    """Venstre/hoeyre kant av blokkens tekstkolonne i designenheter."""
    if side == "left":
        base_x1 = globals().get("LEFT_X1", 140)
        base_x2 = globals().get("LEFT_X2", 540)
    elif side == "right":
        base_x1 = globals().get("RIGHT_X1", 996)
        base_x2 = globals().get("RIGHT_X2", 1396)
    else:
        return None
    try:
        x_offset = int(block.get("x_offset", 0) or 0)
        width_offset = int(block.get("width_offset", 0) or 0)
    except (TypeError, ValueError):
        return None
    return base_x1 + x_offset, base_x2 + width_offset, width_offset


def _dp_widen_narrow_blocks(page: dict) -> None:
    """Utvid for smale tekstkolonner til DP_MIN_TEXT_WIDTH.

    Kjoeres etter _dp_split_inner_story_blocks, saa den ser de endelige
    x_offset-verdiene (inkludert +-10 paa nederste blokk).
    """
    if page.get("type") != "inner":
        return
    side = page.get("side", "right")
    for block in page.get("blocks") or []:
        if not isinstance(block, dict) or not block.get("text"):
            continue
        column = _dp_block_column(block, side)
        if column is None:
            continue
        x1, x2, width_offset = column
        missing = DP_MIN_TEXT_WIDTH - (x2 - x1)
        if missing > 0:
            block["width_offset"] = width_offset + missing


'''

HELPER_RE = re.compile(
    r"# Minste tekstkolonne paa innersider.*?\n\n\ndef _dp_apply_universal_layout",
    re.DOTALL,
)
WIDTH_RE = re.compile(r"^DP_MIN_TEXT_WIDTH = \d+$", re.MULTILINE)


def patch(src: str, width: int) -> str:
    if "DP_MIN_TEXT_WIDTH" in src:
        # Allerede patchet - bare oppdater maalbredden.
        out, n = WIDTH_RE.subn("DP_MIN_TEXT_WIDTH = %d" % width, src, count=1)
        if not n:
            raise SystemExit("fant ikke DP_MIN_TEXT_WIDTH-linja")
        return out

    if src.count(ANCHOR) != 1:
        raise SystemExit("fant ikke _dp_apply_universal_layout-kroppen (%d treff)" % src.count(ANCHOR))
    out = src.replace(ANCHOR, NEW_CALL, 1)

    marker = "def _dp_apply_universal_layout"
    if out.count(marker) != 1:
        raise SystemExit("fant ikke %s (%d treff)" % (marker, out.count(marker)))
    return out.replace(marker, (HELPER % {"width": width}) + marker, 1)


def revert(src: str) -> str:
    if "DP_MIN_TEXT_WIDTH" not in src:
        return src
    out = HELPER_RE.sub("def _dp_apply_universal_layout", src, count=1)
    return out.replace(NEW_CALL, ANCHOR, 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=int, default=400, help="minste kolonnebredde i designenheter")
    ap.add_argument("--revert", action="store_true", help="fjern patchen igjen")
    ap.add_argument("--apply", action="store_true", help="skriv til fil (ellers toerrkjoering)")
    args = ap.parse_args()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    tag = "revert" if args.revert else "width%d" % args.width

    for path in FILES:
        src = io.open(path, encoding="utf-8").read()
        out = revert(src) if args.revert else patch(src, args.width)
        ast.parse(out)
        name = path.split("/")[-1]
        if out == src:
            print("  %s: uendret" % name)
            continue
        print("  %s: endret" % name)
        if args.apply:
            shutil.copy(path, "%s.backup-before-innerwidth-%s-%s" % (path, tag, stamp))
            io.open(path, "w", encoding="utf-8", newline="\n").write(out)

    print("revert" if args.revert else "minstebredde = %d designenheter" % args.width)
    print("SKREVET" if args.apply else "TORRKJORING")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Bakside-teksten skal ha EN samlet skygge, ikke en per linje.

Innersidene bruker "pill"-varianten: en avrundet plate per tekstlinje, som
foelger ordene. Paa baksiden er teksten en sammenhengende bolk, og da ser den
oppdelingen rotete ut - den skal ligge paa ETT mykt felt bak hele blokken.

Patchen gjor to ting:
  1. draw_text_backdrop faar shape="lines" (som foer) eller shape="block".
  2. Bakside-grenen kaller den med shape="block" foer draw_text.

  python patch_motet_bakside_backdrop.py --dry-run
  python patch_motet_bakside_backdrop.py --apply
"""
from __future__ import annotations

import argparse
import ast
import io
import shutil
import sys
from datetime import datetime

FILES = [
    "C:/ComfyUI/script/nb/motet-i-hjertet-text-nb.py",
    "C:/ComfyUI/script/nn/motet-i-hjertet-text-nn.py",
    "C:/ComfyUI/script/en-US/motet-i-hjertet-text-en-US.py",
    "C:/ComfyUI/script/en-GB/motet-i-hjertet-text-en-GB.py",
    "C:/ComfyUI/script/sv/motet-i-hjertet-text-sv.py",
]

SIG_OLD = ('def draw_text_backdrop(img, box, text, font, line_spacing, '
           'highlights=None, align="left", strength="normal"):')
SIG_NEW = ('def draw_text_backdrop(img, box, text, font, line_spacing, '
           'highlights=None, align="left", strength="normal", shape="lines"):')

# Selve tegningen: bytt loekka over line_boxes med en som kan slaa dem sammen.
DRAW_OLD = """    drew = False
    for lb in line_boxes:
        left = max(0, lb[0] - pad_x)
        top = max(0, lb[1] - pad_y)
        right = min(img.size[0], lb[2] + pad_x)
        bottom = min(img.size[1], lb[3] + pad_y)
        if right <= left or bottom <= top:
            continue
        radius = max(6, min((right - left) // 2, int((bottom - top) * 0.40)))
        sd.rounded_rectangle((left, top, right, bottom), radius=radius, fill=(0, 0, 0, shadow_alpha))
        pd.rounded_rectangle((left, top, right, bottom), radius=radius, fill=(0, 0, 0, plate_alpha))
        drew = True
"""

DRAW_NEW = '''    if shape == "block":
        # Baksiden: ETT felt bak hele bolken. Litt romsligere luft enn
        # linjeplatene, ellers klemmer den seg rundt den lengste linja.
        pad_x = int(pad_x * 1.35)
        pad_y = int(pad_y * 1.6)
        boxes = [(
            min(lb[0] for lb in line_boxes),
            min(lb[1] for lb in line_boxes),
            max(lb[2] for lb in line_boxes),
            max(lb[3] for lb in line_boxes),
        )]
    else:
        boxes = line_boxes

    drew = False
    for lb in boxes:
        left = max(0, lb[0] - pad_x)
        top = max(0, lb[1] - pad_y)
        right = min(img.size[0], lb[2] + pad_x)
        bottom = min(img.size[1], lb[3] + pad_y)
        if right <= left or bottom <= top:
            continue
        if shape == "block":
            radius = max(24, int(fs * 0.9))
        else:
            radius = max(6, min((right - left) // 2, int((bottom - top) * 0.40)))
        sd.rounded_rectangle((left, top, right, bottom), radius=radius, fill=(0, 0, 0, shadow_alpha))
        pd.rounded_rectangle((left, top, right, bottom), radius=radius, fill=(0, 0, 0, plate_alpha))
        drew = True
'''

# Bakside-grenen: legg inn kallet rett foer draw_text.
BACK_OLD = """            use_gradient = "color" not in block


            draw_text(
                draw=draw,
                text=block["text"],
                box=box,
                font=font,
                color=block.get("color", TEXT_COLOR),
                stroke_color=STROKE_COLOR,
                line_spacing=line_spacing,
                highlights=block.get("highlights", []),
                gradient=DEFAULT_TEXT_GRADIENT if use_gradient else None,
                img=img,
                align="center",
"""

BACK_NEW = """            use_gradient = "color" not in block

            # Ett samlet felt bak hele bakside-teksten (ikke per linje).
            if block.get("text_backdrop", True):
                draw_text_backdrop(
                    img, box, block["text"], font, line_spacing,
                    highlights=block.get("highlights", []),
                    align="center", shape="block",
                    strength=block.get("text_backdrop_strength", "strong"),
                )

            draw_text(
                draw=draw,
                text=block["text"],
                box=box,
                font=font,
                color=block.get("color", TEXT_COLOR),
                stroke_color=STROKE_COLOR,
                line_spacing=line_spacing,
                highlights=block.get("highlights", []),
                gradient=DEFAULT_TEXT_GRADIENT if use_gradient else None,
                img=img,
                align="center",
"""


def patch(src: str, path: str) -> str:
    if 'shape="block"' in src:
        return src                                   # allerede patchet
    for needle, name in ((SIG_OLD, "signaturen"), (DRAW_OLD, "tegne-loekka"),
                         (BACK_OLD, "bakside-grenen")):
        if needle not in src:
            raise SystemExit(f"{path}: fant ikke {name} - nekter aa gjette")
    src = src.replace(SIG_OLD, SIG_NEW, 1)
    src = src.replace(DRAW_OLD, DRAW_NEW, 1)
    return src.replace(BACK_OLD, BACK_NEW, 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for path in FILES:
        src = io.open(path, encoding="utf-8").read()
        out = patch(src, path)
        ast.parse(out)
        print(f"  {path.split('/')[-1]}: endret={out != src}")
        if args.apply and out != src:
            shutil.copy(path, f"{path}.backup-baksideplate-{stamp}")
            io.open(path, "w", encoding="utf-8", newline="\n").write(out)
    print("SKREVET" if args.apply else "TORRKJORING")
    return 0


if __name__ == "__main__":
    sys.exit(main())

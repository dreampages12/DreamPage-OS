# -*- coding: utf-8 -*-
"""Juster den myke skyggen bak bakside-teksten.

  python tune_bakside.py --pad-x 1.9 --pad-y 2.4 --alpha 120 --blur 1.9 --apply

pad-* er faktorer paa grunnpaddingen, blur er faktor paa fontstoerrelsen.
Skrives inn i alle fem spraakfilene samtidig.
"""
import argparse, ast, io, re, shutil, sys
from datetime import datetime

FILES = ["C:/ComfyUI/script/%s/motet-i-hjertet-text-%s.py" % (l, l)
         for l in ("nb", "nn", "en-US", "en-GB", "sv")]

ap = argparse.ArgumentParser()
ap.add_argument("--pad-x", type=float, required=True)
ap.add_argument("--pad-y", type=float, required=True)
ap.add_argument("--alpha", type=int, required=True)
ap.add_argument("--blur", type=float, required=True)
ap.add_argument("--apply", action="store_true")
a = ap.parse_args()

SUBS = [
    (r"(if shape == \"block\":\n(?:.*\n)*?        pad_x = int\(pad_x \* )[\d.]+", r"\g<1>%s" % a.pad_x),
    (r"(        pad_y = int\(pad_y \* )[\d.]+(\)\n        plate_alpha = 0)", r"\g<1>%s\g<2>" % a.pad_y),
    (r"(        shadow_alpha = )\d+", r"\g<1>%d" % a.alpha),
    (r"(        blur_amount = max\(\d+, int\(fs \* )[\d.]+", r"\g<1>%s" % a.blur),
]

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
for path in FILES:
    src = io.open(path, encoding="utf-8").read()
    out = src
    for pat, rep in SUBS:
        out, n = re.subn(pat, rep, out, count=1)
        if not n:
            raise SystemExit(f"{path}: fant ikke {pat[:40]}")
    ast.parse(out)
    print(f"  {path.split('/')[-1]}: endret={out != src}")
    if a.apply and out != src:
        shutil.copy(path, f"{path}.backup-tune-{stamp}")
        io.open(path, "w", encoding="utf-8", newline="\n").write(out)
print(f"pad_x*{a.pad_x} pad_y*{a.pad_y} alpha={a.alpha} blur=fs*{a.blur}")
print("SKREVET" if a.apply else "TORRKJORING")

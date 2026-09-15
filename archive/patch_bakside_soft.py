# -*- coding: utf-8 -*-
"""Bakside-skyggen skal vaere en myk sky, ikke et kort.

Linjeplatene paa innersidene bestaar av to lag: en blurret skygge og en
crisp avrundet plate oppaa. Platen er det som gir den harde kanten. Over en
hel tekstbolk leser den som en svart boks, saa i block-modus dropper vi
platen helt og lener oss paa en kraftig blurret skygge.
"""
import ast, io, shutil, sys
from datetime import datetime

FILES = ["C:/ComfyUI/script/%s/motet-i-hjertet-text-%s.py" % (l, l)
         for l in ("nb", "nn", "en-US", "en-GB", "sv")]

OLD = '''    if shape == "block":
        # Baksiden: ETT felt bak hele bolken. Litt romsligere luft enn
        # linjeplatene, ellers klemmer den seg rundt den lengste linja.
        pad_x = int(pad_x * 1.35)
        pad_y = int(pad_y * 1.6)
'''

NEW = '''    if shape == "block":
        # Baksiden: EN myk sky bak hele bolken - ingen synlig kant.
        # Den crisp platen droppes (plate_alpha = 0); i stedet blurres
        # skyggen kraftig slik at den toner ut i illustrasjonen.
        pad_x = int(pad_x * 0.9)
        pad_y = int(pad_y * 1.1)
        plate_alpha = 0
        shadow_alpha = 190
        blur_amount = max(30, int(fs * 1.15))
'''

apply = "--apply" in sys.argv
stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
for path in FILES:
    src = io.open(path, encoding="utf-8").read()
    if "plate_alpha = 0" in src:
        print(f"  {path.split('/')[-1]}: allerede patchet"); continue
    if OLD not in src:
        raise SystemExit(f"{path}: fant ikke block-grenen")
    out = src.replace(OLD, NEW, 1)
    ast.parse(out)
    print(f"  {path.split('/')[-1]}: endret")
    if apply:
        shutil.copy(path, f"{path}.backup-myksky-{stamp}")
        io.open(path, "w", encoding="utf-8", newline="\n").write(out)
print("SKREVET" if apply else "TORRKJORING")

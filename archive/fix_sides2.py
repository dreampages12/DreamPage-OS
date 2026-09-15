# -*- coding: utf-8 -*-
"""Tekstsiden maa staa motsatt av figuren. Treffer BARE de 14 nummererte
historiesidene - ikke blank-back (QR-siden), som ogsaa har "side" i en-US/en-GB."""
import io, re, sys, shutil
from datetime import datetime

FILES = ["C:/ComfyUI/script/nb/motet-i-hjertet-text-nb.py",
         "C:/ComfyUI/script/nn/motet-i-hjertet-text-nn.py",
         "C:/ComfyUI/script/en-US/motet-i-hjertet-text-en-US.py",
         "C:/ComfyUI/script/en-GB/motet-i-hjertet-text-en-GB.py",
         "C:/ComfyUI/script/sv/motet-i-hjertet-text-sv.py"]
WANT = ["left", "right"] * 7          # figuren staar vekselvis hoyre/venstre
PAT = re.compile(r'("filename": "(\d\d)\(Prinsessen\)\.png",\s*\n\s*'
                 r'"type": "inner",\s*\n\s*"side": ")\w+(")')
apply = "--apply" in sys.argv
stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

for path in FILES:
    src = io.open(path, encoding="utf-8").read()
    hits = []
    def repl(m):
        n = int(m.group(2))
        hits.append(n)
        return m.group(1) + WANT[n - 1] + m.group(3)
    out = PAT.sub(repl, src)
    assert sorted(hits) == list(range(1, 15)), (path, sorted(hits))
    print(f"  {path.split('/')[-1]}: 14 treff, endret={out != src}")
    if apply and out != src:
        shutil.copy(path, f"{path}.backup-sides2-{stamp}")
        io.open(path, "w", encoding="utf-8", newline="\n").write(out)
print("SKREVET" if apply else "TORRKJORING")

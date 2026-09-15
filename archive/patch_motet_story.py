# -*- coding: utf-8 -*-
"""Bytt ut historien i alle motet-i-hjertet-tekstscriptene.

Den nye historien er en HELT annen fortelling enn den gamle (jenta er ikke
prinsesse fra start - hun gjennomforer Prinsessens prove og blir kronet).
Bildene er allerede byttet.

To ting maa endres SAMMEN i de oversatte filene:
  * kildeteksten i build_pages (norsk)
  * noklene i _DREAMPAGE_TRANSLATIONS, som slaas opp paa nettopp den norske
    kildeteksten. Endres bare den ene, faller boka tilbake til norsk tekst.

  python patch_motet_story.py --dry-run
  python patch_motet_story.py --apply
"""
from __future__ import annotations

import argparse
import ast
import io
import json
import os
import re
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from motet_story import NB, HIGHLIGHTS, TRANSLATIONS  # noqa: E402

FILES = {
    "nb": "C:/ComfyUI/script/nb/motet-i-hjertet-text-nb.py",
    "nn": "C:/ComfyUI/script/nn/motet-i-hjertet-text-nn.py",
    "en-US": "C:/ComfyUI/script/en-US/motet-i-hjertet-text-en-US.py",
    "en-GB": "C:/ComfyUI/script/en-GB/motet-i-hjertet-text-en-GB.py",
    "sv": "C:/ComfyUI/script/sv/motet-i-hjertet-text-sv.py",
}

TEXT_RE = re.compile(r'("text": p\(\n)(.*?)(\n(\s*)\),)', re.DOTALL)
HL_RE = re.compile(r'^(\s*)"highlights": \[[^\]]*\],\s*$', re.MULTILINE)


def story_slice(src: str) -> tuple[int, int]:
    """Bare de 14 innersidene - hverken forside eller bakside."""
    start = src.index("# Side 1")
    end = src.index('"filename": "bakside')
    return start, end


def to_key(text: str) -> str:
    return text.replace("(Navn)", "{name}").replace("[NAVN]", "{name}")


def render_literal(text: str, indent: str) -> str:
    lines = text.split("\n")
    out = []
    for i, line in enumerate(lines):
        body = line.replace("\\", "\\\\").replace('"', '\\"')
        if i < len(lines) - 1:
            body += "\\n"
        out.append(f'{indent}"{body}"')
    return "\n".join(out)


def old_nb_texts() -> list[str]:
    src = io.open(FILES["nb"], encoding="utf-8").read()
    a, b = story_slice(src)
    found = [ast.literal_eval("(" + m.group(2).strip() + ")")
             for m in TEXT_RE.finditer(src[a:b])]
    if len(found) != 14:
        raise SystemExit(f"fant {len(found)} sidetekster i nb, forventet 14")
    return found


def patch_story(src: str) -> tuple[str, int]:
    a, b = story_slice(src)
    head, body, tail = src[:a], src[a:b], src[b:]

    counter = {"n": 0}

    def repl(m):
        i = counter["n"]
        counter["n"] += 1
        indent = re.match(r"\s*", m.group(2)).group(0)
        return m.group(1) + render_literal(NB[i], indent) + m.group(3)

    body = TEXT_RE.sub(repl, body)
    if counter["n"] != 14:
        raise SystemExit(f"erstattet {counter['n']} tekster, forventet 14")

    hl = {"n": 0}

    def hrepl(m):
        i = hl["n"]
        hl["n"] += 1
        words = ", ".join(json.dumps(w, ensure_ascii=False) for w in HIGHLIGHTS[i])
        return f'{m.group(1)}"highlights": [{words}],'

    body = HL_RE.sub(hrepl, body)
    if hl["n"] != 14:
        raise SystemExit(f"erstattet {hl['n']} highlights, forventet 14")

    return head + body + tail, counter["n"]


def patch_translations(src: str, lang: str, old_keys: list[str]) -> str:
    marker = "_DREAMPAGE_TRANSLATIONS = {"
    start = src.index(marker)
    end = src.index("\n}\n", start) + len("\n}\n")
    old = ast.literal_eval(src[start + len("_DREAMPAGE_TRANSLATIONS = "):end].strip())

    new_texts = TRANSLATIONS[lang]
    mapping = {old_keys[i]: (to_key(NB[i]), new_texts[i]) for i in range(14)}

    lines = ["_DREAMPAGE_TRANSLATIONS = {"]
    seen = set()
    for k, v in old.items():
        if k in mapping:
            nk, nv = mapping[k]
            seen.add(k)
        else:
            nk, nv = k, v
        lines.append("  %s: %s," % (json.dumps(nk, ensure_ascii=False),
                                    json.dumps(nv, ensure_ascii=False)))
    missing = [i for i, k in enumerate(old_keys) if k not in seen]
    if missing:
        raise SystemExit(f"{lang}: fant ikke gamle nokler for side(r) "
                         + ", ".join(str(i + 1) for i in missing))
    lines[-1] = lines[-1].rstrip(",")
    lines.append("}")
    return src[:start] + "\n".join(lines) + src[end - 1:]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    old_keys = [to_key(t) for t in old_nb_texts()]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    for lang, path in FILES.items():
        src = io.open(path, encoding="utf-8").read()
        out, n = patch_story(src)
        if lang != "nb":
            out = patch_translations(out, lang, old_keys)
        ast.parse(out)  # nekt aa skrive noe som ikke er gyldig python
        print(f"  {lang}: {n} sidetekster"
              + ("" if lang == "nb" else f" + {len(TRANSLATIONS[lang])} oversettelser"))
        if args.apply:
            shutil.copy(path, f"{path}.backup-nystory-{stamp}")
            io.open(path, "w", encoding="utf-8", newline="\n").write(out)

    print("SKREVET" if args.apply else "TORRKJORING - ingenting skrevet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

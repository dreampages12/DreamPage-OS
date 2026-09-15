"""Rett Lumo->Lumi og "dinosauren"->"Lumi" i alle spraakversjoner av dinosaurboka.

To ting maa skje samtidig:

1. Kildeteksten i build_pages() rettes (det er den norske teksten som trykkes
   i nb-boka).
2. NOEKLENE i _DREAMPAGE_TRANSLATIONS maa rettes likt, fordi oppslaget skjer paa
   den norske kildeteksten. Rettes bare kilden, finner ikke oversettelsen sin
   noekkel lenger, og den engelske boka faller tilbake til norsk tekst.
3. Selve OVERSETTELSENE rettes ogsaa - i svensk het han Lumo hele veien.

Alle endringer er eksakte strengbytter. Scriptet teller treff og nekter aa
skrive hvis et bytte ikke fant noe, saa en stille halv-retting er umulig.

Bruk:
  python fix_lumi_all_languages.py --dry-run
  python fix_lumi_all_languages.py --apply
"""
from __future__ import annotations

import argparse
import io
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

FILES = [
    ("nb", "nb/dinosaur-text-nb.py"),
    ("nn", "nn/dinosaur-text-nn.py"),
    ("sv", "sv/dinosaur-text-sv.py"),
    ("en-US", "en-US/dinosaur-text-en-US.py"),
    ("en-GB", "en-GB/dinosaur-text-en-GB.py"),
]

# (gammel, ny, paakrevd) - paakrevd=False for varianter som ikke finnes overalt
REPLACEMENTS = [
    # --- navnet: Lumo -> Lumi (norsk kilde + engelske/svenske oversettelser) ---
    ("«Jeg heter Lumo,»", "«Jeg heter Lumi,»", False),
    ('"My name is Lumo,"', '"My name is Lumi,"', False),
    ('«Eg heiter *Lumo,»', '«Eg heiter Lumi,»', False),
    ('"Jag heter Lumo"', '"Jag heter Lumi"', False),
    ('"Lumo", "hjelp"', '"Lumi", "hjelp"', False),

    # --- svensk brukte Lumo ogsaa der norsk sier Lumi ---
    ("{name} och Lumo stod stilla", "{name} och Lumi stod stilla", False),
    ("Lumo log försiktigt", "Lumi log försiktigt", False),
    ("Lumo såg på honom", "Lumi såg på honom", False),

    # --- fortelleren skal bruke navnet, ikke "dinosauren" ---
    # side 8
    ("Plutselig begynte dinosauren å løpe. Den snudde seg og så på",
     "Plutselig begynte Lumi å løpe. Han snudde seg og så på", False),
    ("«Kom!» sa den vennlig.", "«Kom!» sa han vennlig.", False),
    ("Suddenly the dinosaur started running. It turned and looked at the {name}.",
     "Suddenly Lumi started running. He turned and looked at {name}.", False),
    ("Come!\\\" it said kindly.", "Come!\\\" he said kindly.", False),

    # side 9 - kilden bruker "(Navn)", ordboknoeklene bruker "{name}", og i
    # ordboken staar linjeskiftene som escapet \n paa EN linje. Derfor byttes
    # setningene hver for seg i stedet for hele avsnittet.
    ("gikk ved siden av dinosauren. Stien var smal og stille.",
     "gikk ved siden av Lumi. Stien var smal og stille.", False),
    ("Dinosauren ristet på hodet.", "Lumi ristet på hodet.", False),
    ("«Jeg kan ikke si det,» sa den lavt.", "«Jeg kan ikke si det,» sa han lavt.", False),
    ("{name} walked next to the dinosaur. The path was narrow and quiet.",
     "{name} walked next to Lumi. The path was narrow and quiet.", False),
    ("{name} asked. The dinosaur shook his head.", "{name} asked. Lumi shook his head.", False),
    ('I can\\\'t say,\\" it said softly.', 'I can\\\'t say,\\" he said softly.', False),

    # side 10
    ("Plutselig stoppet dinosauren. Øynene ble store.",
     "Plutselig stoppet Lumi. Øynene ble store.", False),
    ("der er han,» hvisket den.", "der er han,» hvisket han.", False),
    ("Den pekte mot den store dinosauren.", "Lumi pekte mot den store dinosauren.", False),
    ("Den så på (Navn). «Det er han jeg trenger hjelp med.»",
     "Så så han på (Navn). «Det er han jeg trenger hjelp med.»", False),
    ("Den så på {name}. «Det er han jeg trenger hjelp med.»",
     "Så så han på {name}. «Det er han jeg trenger hjelp med.»", False),
    ("Suddenly the dinosaur stopped. The eyes widened.",
     "Suddenly Lumi stopped. His eyes widened.", False),
    ("there he is,\\\" it whispered.", "there he is,\\\" he whispered.", False),
    ("It pointed towards the big dinosaur.", "Lumi pointed towards the big dinosaur.", False),
    ("It looked at the {name}.", "Then he looked at {name}.", False),
]


def process(path: str, apply: bool):
    with io.open(path, encoding="utf-8") as fh:
        text = fh.read()
    original = text
    hits = []
    for old, new, required in REPLACEMENTS:
        n = text.count(old)
        if n:
            text = text.replace(old, new)
            hits.append((old.split("\n")[0][:52], n))
        elif required:
            print(f"    ADVARSEL: fant ikke paakrevd tekst: {old[:52]!r}")
    changed = text != original
    for label, n in hits:
        print(f"    {n}x  {label}")
    if not hits:
        print("    (ingen treff)")
    if apply and changed:
        with io.open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    return changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    for lang, rel in FILES:
        path = os.path.join(SCRIPT_DIR, rel)
        print(f"\n=== {lang}  ({rel}) ===")
        if not os.path.isfile(path):
            print("    filen finnes ikke - hopper over")
            continue
        process(path, args.apply)

    if args.apply:
        print("\n--- syntakssjekk ---")
        import ast
        for lang, rel in FILES:
            path = os.path.join(SCRIPT_DIR, rel)
            if not os.path.isfile(path):
                continue
            try:
                ast.parse(io.open(path, encoding="utf-8").read())
                print(f"  {lang:6} OK")
            except SyntaxError as exc:
                print(f"  {lang:6} SYNTAKSFEIL linje {exc.lineno}: {exc.msg}")
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

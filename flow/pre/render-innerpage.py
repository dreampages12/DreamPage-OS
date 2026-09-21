# -*- coding: utf-8 -*-
"""Legg BOKAS EGEN tekst paa en innerside-forhaandsvisning.

Soesken av render-title.py og render-title-line2logo.py: de tegner omslaget,
denne tegner en innerside. Kalles av preview-pipelinen etter at ComfyUI har
satt barnets ansikt inn i scenen.

DEN SKRIVER IKKE SIN EGEN TEKST, OG DEN HAR INGEN EGEN LAYOUT.

Side 7 i forhaandsvisningen er side 7 i boka. Alt annet ville vaert en
loegn mot kunden - de kjoeper boka de ser. Derfor importerer dette scriptet
bokas eget tekstscript (flow/text/<lokale>/<bok>-text-<lokale>.py), kaller
`build_pages(child_name)` og lar bokas egen `render_page()` tegne sida.

Det betyr at ALT foelger med gratis og kan ikke gli fra hverandre:
teksten, navnebyttet, automatisk uthevede ord, delingen i to balanserte
blokker, den moerke puta bak teksten, venstre/hoeyre kolonne, y-offsets og
den automatiske krympingen av skriftstoerrelsen. Endrer noen teksten paa
side 7, endrer forhaandsvisningen seg i samme oeyeblikk.

Det eneste som er annerledes enn i boka: `save_split_a5` byttes ut, slik at
oppslaget lagres HELT i stedet for aa deles i to A5-sider paa 2625 px. En
forhaandsvisning er ett bilde, ikke to trykksider.

  python render-innerpage.py --script flow/text/nb/dyreparken-text-nb.py ^
      --image raa.png --out ferdig.png --child-name Emma ^
      --filename "07(dyreparken).png"
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import sys
import tempfile

from PIL import Image


def log(msg: str) -> None:
    print(msg, flush=True)


def load_text_script(path: str):
    """Importer bokas tekstscript som modul.

    Lokalemappa legges foerst i sys.path fordi tekstscriptene importerer
    soesknene sine bart (`from gelato_cover import ...`, `dream_pdf_guard`,
    `dream_text_layout`). De buntene er selvstendige per spraak og skal ikke
    splittes - se flow/paths.py.
    """
    folder = os.path.dirname(os.path.abspath(path))
    if folder not in sys.path:
        sys.path.insert(0, folder)
    spec = importlib.util.spec_from_file_location(
        "dp_book_text_" + os.path.splitext(os.path.basename(path))[0].replace("-", "_"),
        path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"kunne ikke laste tekstscriptet {path}")
    module = importlib.util.module_from_spec(spec)
    # Registrer FOER exec: enkelte tekstscript slaar opp seg selv i
    # sys.modules naar de bygger om build_pages (den universelle layouten).
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def find_page(pages, filename: str):
    """Sida i boka som bruker DENNE malfila, eller None.

    Malfilnavnet er noekkelen fordi det er det eneste boka og
    books/<slug>/config.json er enige om: config har `template_image`,
    tekstscriptet har `filename`, og de er den samme strengen.

    Returnerer None og lar main() skrive feilen paa stdout, som alt annet i
    dette scriptet. SystemExit ville lagt den paa stderr - og en feil som
    ligger et annet sted enn de andre, er en feil noen leter etter.
    """
    target = os.path.basename(str(filename)).lower()
    for page in pages:
        if os.path.basename(str(page.get("filename") or "")).lower() == target:
            return page
    finnes = ", ".join(str(p.get("filename")) for p in pages if p.get("filename"))
    log(f"FEIL: tekstscriptet har ingen side som bruker {filename!r}.\n"
        f"      Sidene det kjenner: {finnes}\n"
        f"      Malfilnavnet maa vaere det samme i books/<slug>/config.json "
        f"(template_image) og i tekstscriptet (filename).")
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True,
                    help="bokas tekstscript for riktig spraak")
    ap.add_argument("--image", required=True, help="raa side fra ComfyUI")
    ap.add_argument("--out", required=True)
    ap.add_argument("--child-name", required=True)
    ap.add_argument("--filename", required=True,
                    help="malfilnavnet, f.eks. \"07(dyreparken).png\"")
    args = ap.parse_args()

    if not os.path.isfile(args.image):
        # Hard feil. Uten kildebildet finnes det ingen side aa skrive paa, og
        # et tomt lerret med tekst ville vaert verre enn ingen fil.
        log(f"FEIL: fant ikke {args.image}")
        return 1
    if not os.path.isfile(args.script):
        log(f"FEIL: fant ikke tekstscriptet {args.script}")
        return 1

    module = load_text_script(args.script)
    page = find_page(module.build_pages(args.child_name), args.filename)
    if page is None:
        return 1

    blocks = page.get("blocks") or []
    if not any(str(b.get("text") or "").strip() for b in blocks):
        # En innerside uten tekst er en tom side. Det kan vaere riktig i boka
        # (en ren illustrasjonsside), men da er den et daarlig valg for en
        # forhaandsvisning - og valget skal tas av et menneske, ikke oppdages
        # av en kunde.
        log(f"FEIL: {args.filename} har ingen tekst i tekstscriptet. "
            f"Velg en annen side i config/preview/books/<marked>/<slug>.json.")
        return 1

    # Bokas render_page henter malen fra base_dir/<filename>. Vi gir den den
    # RENDREDE sida i stedet for malen - det er hele forskjellen paa en
    # forhaandsvisning og en tom mal.
    workdir = tempfile.mkdtemp(prefix="dp-innerpage-")
    try:
        shutil.copy2(args.image, os.path.join(workdir, page["filename"]))

        # save_split_a5 deler oppslaget i to A5-sider paa 2625 px og skriver
        # dem til disk. En forhaandsvisning er ETT bilde, saa vi fanger det
        # ferdige oppslaget her i stedet. Alt annet i render_page er urort.
        out_dir = os.path.dirname(os.path.abspath(args.out))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        def save_whole(img, _out_dir, _base_filename):
            img.convert("RGB").save(args.out)
            return [args.out]

        module.save_split_a5 = save_whole
        module.render_page(page, workdir, workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if not os.path.isfile(args.out):
        log(f"FEIL: bokas render_page skrev ingen fil til {args.out}")
        return 1

    with Image.open(args.out) as im:
        size = im.size
    log(f"Lagret: {args.out}  ({page['filename']}, "
        f"side={page.get('side', 'right')}, {len(blocks)} blokk(er), "
        f"{size[0]}x{size[1]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

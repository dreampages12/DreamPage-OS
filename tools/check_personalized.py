# -*- coding: utf-8 -*-
"""Er sidene i en ordre faktisk personaliserte, eller er de raa maler?

    python tools/check_personalized.py 1528
    python tools/check_personalized.py 1528 1530 1534
    python tools/check_personalized.py --all-open     # alle uferdige ordre

HVORFOR DEN FINNES

Ordre 1528 (Lion, den-skjulte-styrken) gikk til Gelato med 12 raa maler i
boka. Kjeden var:

  1. Ordren ble bygget ferdig -> Gelato-utkast -> `cleanup_comfy_folder`
     slettet de 14 rendrede sidene, fordi et utkast fantes.
  2. Operatoren rendret to nye sider fra Telegram. De to havnet i en ellers
     tom comfy/.
  3. /bygg kjorte `prepare_order`, som kopierer ALLE base-malene over input/
     og DERETTER henter faceswappede sider fra comfy/. Den fant to av tolv.
  4. De ti ovrige fikk "[ADVARSEL] Fant ikke faceswappet bilde" og `continue`.
     Scriptet avsluttet med 0 og skrev "[Ferdig] Input-mappa er klar".
  5. `dream_pdf_guard` sa ok: den teller SIDER, ikke om de er personaliserte.
     33 sider var riktig. Innholdet var det ikke.

`reprint_order.assert_comfy_complete()` stopper na aarsaken. Dette verktoyet
er den andre siden: det svarer paa "er denne ordren OK?" for en bok som
allerede er bygget - altsaa ogsaa for de ordrene som ble bygget FOER guarden
fantes.

HVORDAN

`template_image` i config.json navngir malen. Er ordrens
`input/<template_image>` byte-identisk med malen, er siden ALDRI blitt
faceswappet. Malen sjekkes BEGGE steder den finnes - `books/<slug>/base/`
(det prepare kopierer fra) og rot-`input/` (det ComfyUI laster) - fordi de
to ikke alltid er like.

Hud- og haarvarianter (`…mixed.png`, `…mork.png`, `…kort.png`) sjekkes ogsaa,
slik at en bok bygget med en variantmal ikke gir falsk alarm.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_DIR = os.path.join(ROOT, "input")

# Varianter av samme mal. En bok bygget for et morkt barn bruker
# "01(styrken)mork.png" som mal, og den skal ikke regnes som "raa mal" bare
# fordi den ikke er identisk med standardmalen.
VARIANT_SUFFIXES = ("", "mixed", "mork", "kort", "kortmixed", "kortmork")


def md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def template_hashes(filename: str, book_base: str) -> dict[str, str]:
    """{sti: md5} for malen og variantene, fra BEGGE kildene.

    Malen finnes to steder, og de er ikke alltid like:

      books/<slug>/base/     det `prepare_order` faktisk kopierer fra
      <rot>/input/           det ComfyUI laster naar den rendrer

    For den-skjulte-styrken er `01(styrken).png` identisk i begge, mens
    `forside(styrken).png` er ULIK. Sjekker vi bare den ene, gaar de fleste
    raa malene rett igjennom - det gjorde forste utgave av dette verktoyet,
    som fant 1 av 10.

    Begge maa derfor med. En side som er byte-identisk med NOEN av dem er
    ikke faceswappet.
    """
    stem, ext = os.path.splitext(filename)
    out = {}
    for folder in (book_base, TEMPLATE_DIR):
        if not folder or not os.path.isdir(folder):
            continue
        for suffix in VARIANT_SUFFIXES:
            cand = os.path.join(folder, f"{stem}{suffix}{ext}")
            if os.path.isfile(cand):
                out[cand] = md5(cand)
    return out


def check(order_id: str) -> tuple[int, list[str]]:
    """(antall sider, liste med problemer)."""
    sys.path.insert(0, os.path.join(ROOT, "flow"))
    import dp_order

    try:
        info = dp_order.resolve(order_id)
    except SystemExit as exc:
        return 0, [f"kunne ikke slaa opp ordren: {exc}"]

    pages = (info.get("config") or {}).get("pages") or []
    input_dir = info["input_dir"]
    book_base = os.path.join(ROOT, "books", info.get("book_slug") or "", "base")
    problems: list[str] = []

    if not pages:
        return 0, [f"{info.get('book_slug')} har ingen pages i config.json"]
    if not os.path.isdir(input_dir):
        return 0, [f"ingen input-mappe: {input_dir}"]

    for page in pages:
        name = page.get("template_image")
        key = page.get("page_key", "?")
        if not name:
            continue
        dst = os.path.join(input_dir, name)
        if not os.path.isfile(dst):
            problems.append(f"{key:<8} {name} MANGLER i ordrens input/")
            continue

        templates = template_hashes(name, book_base)
        if not templates:
            problems.append(f"{key:<8} {name} - fant ingen mal aa sammenligne "
                            f"med i {book_base} eller {TEMPLATE_DIR} "
                            f"(kan ikke avgjores)")
            continue

        digest = md5(dst)
        if digest in templates.values():
            which = next(os.path.basename(p) for p, h in templates.items()
                         if h == digest)
            problems.append(f"{key:<8} {name} er RAA MAL (identisk med {which})")

    return len(pages), problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("orders", nargs="*", help="ordre-ID-er")
    ap.add_argument("--all-open", action="store_true",
                    help="alle ordre som ikke staar som done i jobb-DB-en")
    args = ap.parse_args()

    orders = list(args.orders)
    if args.all_open:
        import sqlite3
        db = os.path.join(ROOT, "state", "jobs.sqlite")
        con = sqlite3.connect(db)
        orders += [r[0] for r in con.execute(
            "SELECT job_key FROM jobs WHERE status != 'done' ORDER BY queued_at")]
    if not orders:
        ap.error("oppgi minst én ordre, eller bruk --all-open")

    verdict = 0
    for order_id in orders:
        total, problems = check(str(order_id))
        if problems:
            verdict = 1
            print(f"\n{order_id}: {len(problems)} AV {total} SIDER ER IKKE OK")
            for p in problems:
                print(f"  {p}")
        else:
            print(f"{order_id}: alle {total} sidene er personaliserte")

    if verdict:
        print("\nEn raa mal betyr at siden aldri ble faceswappet. Boka viser da")
        print("malebarnet, ikke kundens barn. Bygg om - og bruk --skip-prepare")
        print("hvis de riktige sidene fortsatt ligger i ordrens input/.")
    return verdict


if __name__ == "__main__":
    sys.exit(main())

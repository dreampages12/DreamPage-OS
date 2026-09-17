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

Selve sjekken bor i `flow/page_files.py`, som ogsaa `reprint_order` bruker:
er ordrens fil byte-identisk med malen, ble siden ALDRI faceswappet. Malen
sjekkes begge steder den finnes (`books/<slug>/base/` og rot-`input/`) og i
alle hud- og haarvarianter.

Filnavnet kommer fra bokas `PAGE_TO_BASE_STEM`, ikke fra `template_image`:
de delte sidene heter `04-right(bok).png` paa disk. Foerste utgave brukte
`template_image` og meldte derfor hver delte side som MANGLER - tre falske
alarmer per fotball-ordre, og stoy er nettopp det som skjulte de tolv ekte
advarslene i 1528.
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check(order_id: str) -> tuple[int, list[str]]:
    """(antall sider, liste med problemer)."""
    sys.path.insert(0, os.path.join(ROOT, "flow"))
    import dp_order
    import page_files

    try:
        info = dp_order.resolve(order_id)
    except SystemExit as exc:
        return 0, [f"kunne ikke slaa opp ordren: {exc}"]

    pages = (info.get("config") or {}).get("pages") or []
    if not pages:
        return 0, [f"{info.get('book_slug')} har ingen pages i config.json"]
    if not os.path.isdir(info["input_dir"]):
        return 0, [f"ingen input-mappe: {info['input_dir']}"]

    problems: list[str] = []
    for row in page_files.audit_input(info):
        key, stem = row["page_key"], row["stem"]
        if row["status"] == "mangler":
            problems.append(f"{key:<8} {stem} MANGLER i ordrens input/")
        elif row["status"] == "raa":
            problems.append(f"{key:<8} {stem} er RAA MAL "
                            f"(identisk med {row['raw_as']})")
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

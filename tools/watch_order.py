# -*- coding: utf-8 -*-
"""Foelg en ordre til den er ferdig - og si fra hvis den staar stille.

    python tools/watch_order.py 1541
    python tools/watch_order.py 1541 --stall-minutes 20 --interval 60

Skriver EN linje per endring paa stdout og avslutter naar alle boekene i
ordren er ferdige (eller feilet). Ingen linjer betyr at alt gaar som det
skal - men en jobb som staar stille i for lang tid gir en STOPPET-linje, og
det er hele poenget:

  * `render_pages` bruker ca. 72 s per side. Staar samme side i 20 minutter,
    er noe galt - ComfyUI henger, eller noeklene er borte.
  * En jobb som staar som `running` uten aa bytte steg er usynlig utenfra:
    API-et svarer, koeen ser levende ut, og ingen varsler. Slik sto koeen i
    47 minutter 17.09.2026.

Flerbok-ordre foelges som en helhet: begge boekene skal ende i ETT samlet
Gelato-utkast. Blir de staaende som to, sies det fra - da maa de slaas
sammen fra Telegram, ellers faar kunden to pakker.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "state", "jobs.sqlite")
DRAFTS = os.path.join(ROOT, "state", "gelato_drafts")
TERMINAL = ("done", "failed", "cancelled")


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def jobs(order_id: str) -> list[dict]:
    """Radene for alle boekene i ordren. Lesing, aldri skriving."""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT job_key, status, step, child_name, book_slug, started_at,"
            " finished_at, error FROM jobs"
            " WHERE job_key = ? OR job_key LIKE ? ORDER BY job_key",
            (order_id, f"{order_id}-b%")).fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


def drafts(order_id: str) -> dict[str, str]:
    """{job_key: draft_id} fra kvitteringene paa disk."""
    out = {}
    for path in glob.glob(os.path.join(DRAFTS, f"{order_id}*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        key = os.path.splitext(os.path.basename(path))[0]
        if data.get("draft_id"):
            out[key] = data["draft_id"]
    return out


def merged(order_id: str) -> str | None:
    """Er boekene samlet i ETT utkast? Returnerer utkast-ID-en."""
    for path in glob.glob(os.path.join(DRAFTS, f"{order_id}*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        # Samme regel som dp_merge bruker: status "merged", eller en
        # merged_orders-liste med FLERE enn seg selv. En liste med ett navn
        # er ikke en sammenslaaing.
        if not data.get("draft_id"):
            continue
        if (data.get("status") == "merged"
                or len(data.get("merged_orders") or []) > 1):
            return data["draft_id"]
    return None


def si(text: str, enabled: bool) -> None:
    """Kort beskjed i operatoer-chatten. Fail-soft: en melding som ikke gaar
    gjennom skal ikke drepe overvaakingen - da mister vi ogsaa stopp-alarmen.
    """
    if not enabled:
        return
    try:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import say_to_operator
        say_to_operator.main_text(text)
    except Exception as error:                        # noqa: BLE001
        print(f"{now()}  (klarte ikke sende Telegram-melding: {error})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("order_id")
    ap.add_argument("--interval", type=int, default=60, help="sekunder")
    ap.add_argument("--stall-minutes", type=int, default=20,
                    help="hvor lenge samme steg far staa foer vi sier fra")
    ap.add_argument("--si-i-telegram", action="store_true",
                    help="send en kort melding i operatoer-chatten naar "
                         "ordren er ferdig bygget (og hvis den staar stille)")
    args = ap.parse_args()

    order = str(args.order_id)
    seen: dict[str, str] = {}          # job_key -> "status/step"
    since: dict[str, float] = {}       # job_key -> naar vi saa det sist endre
    stalled: set[str] = set()
    said_drafts: set[str] = set()
    said_merge = False

    rows = jobs(order)
    if not rows:
        print(f"{now()}  {order}: ingen jobber i databasen")
        return 1
    print(f"{now()}  foelger {order}: "
          + ", ".join(f"{r['job_key']} ({r['child_name']}, {r['book_slug']})"
                      for r in rows))

    while True:
        rows = jobs(order)
        for r in rows:
            key = r["job_key"]
            state = f"{r['status']}/{r['step'] or '-'}"
            if seen.get(key) != state:
                if key in seen:                       # ikke ved foerste runde
                    print(f"{now()}  {key}: {state}")
                seen[key] = state
                since[key] = time.time()
                stalled.discard(key)
                continue

            # Uendret: staar den for lenge?
            waited = (time.time() - since.get(key, time.time())) / 60
            if (r["status"] not in TERMINAL and key not in stalled
                    and waited >= args.stall_minutes):
                stalled.add(key)
                print(f"{now()}  STOPPET? {key} har staatt paa {state} i "
                      f"{waited:.0f} min - se paa den")
                si(f"\u26a0\ufe0f <b>{key}</b> har staatt paa "
                   f"<code>{state}</code> i {waited:.0f} min. Jeg ser paa "
                   f"den - la den staa.", args.si_i_telegram)

        for key, draft in drafts(order).items():
            if key not in said_drafts:
                said_drafts.add(key)
                print(f"{now()}  {key}: Gelato-utkast {draft}")

        samlet = merged(order)
        if samlet and not said_merge:
            said_merge = True
            print(f"{now()}  {order}: SAMLET utkast {samlet}")

        if rows and all(r["status"] in TERMINAL for r in rows):
            feil = [r for r in rows if r["status"] != "done"]
            for r in feil:
                print(f"{now()}  {r['job_key']}: {r['status']} - "
                      f"{(r['error'] or '')[:200]}")
            if len(rows) > 1 and not samlet and not feil:
                print(f"{now()}  {order}: {len(rows)} boeker, men INGEN "
                      "samlet utkast - slaa dem sammen fra Telegram, "
                      "ellers blir det to pakker")
            print(f"{now()}  {order}: ferdig "
                  + ("med feil" if feil else "- alle boekene er bygget"))

            if feil:
                si(f"\u274c <b>{order}</b> er ikke ferdig: "
                   + ", ".join(f"{r['job_key']} ({r['status']})" for r in feil)
                   + ". Jeg ser paa den.", args.si_i_telegram)
            else:
                boker = ", ".join(f"{r['child_name']} ({r['book_slug']})"
                                  for r in rows)
                linjer = [f"\u2705 <b>{order}</b> er ferdig bygget: {boker}."]
                if samlet:
                    linjer.append(f"Samlet Gelato-utkast: "
                                  f"<code>{samlet}</code>")
                elif len(rows) > 1:
                    linjer.append("MEN: boekene ligger som to separate "
                                  "utkast - de maa slaas sammen, ellers blir "
                                  "det to pakker.")
                si("\n".join(linjer), args.si_i_telegram)
            return 0

        sys.stdout.flush()
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())

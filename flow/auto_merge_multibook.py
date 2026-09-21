# -*- coding: utf-8 -*-
"""Slaa sammen Gelato-utkastene naar EN ordre inneholder flere boeker.

Bakgrunn
--------
Fra 2026-08-31 kan en kunde legge flere personaliserte boeker i samme
handlekurv. Hver bok blir en egen koe-melding og en egen n8n-kjoering, og
dermed ogsaa sitt eget Gelato-utkast: `1411-b1` og `1411-b2`. Det gir to
forsendelser til samme adresse, av samme bestilling.

Naar to boeker kommer fra SAMME ordre er det ingen tvil om at de skal til
samme kunde - i motsetning til to separate WooCommerce-ordre, som
`gelato_merge.py` spoer om paa Telegram foerst. Her trengs ingen bekreftelse:
vi slaar sammen automatisk, uten varsel.

Naar kjoeres den
----------------
Etter "Record Gelato Draft" i Dreampage Worker v2, en gang per bok. De
foerste boekene ser at ordren ikke er komplett enda og gjoer ingenting; den
SISTE som blir ferdig finner alle soesknene og slaar dem sammen. Vi ser paa
hvor mange kvitteringer som faktisk finnes - ikke paa `book_index` - fordi
boeker kan bli ferdige i annen rekkefoelge hvis en feiler og kjoeres om.

Fail-soft
---------
En betalt ordre skal ALDRI stoppe fordi sammenslaaingen feilet. Scriptet
skriver alltid gyldig JSON paa stdout og avslutter med kode 0. Verste utfall
er at kunden faar to pakker - noeyaktig som foer denne automatikken.

  python auto_merge_multibook.py --order-id 1411 --book-count 2
  python auto_merge_multibook.py --order-id 1411 --book-count 2 --dry-run
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
import traceback

# Stien til DreamPage-roten utledes, den hardkodes ikke: koden kjoerer paa
# Windows i dag og paa Linux paa nye maskiner. Se flow/paths.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import under  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DRAFT_STATE_DIR = under("state/gelato_drafts")
LOCK_PATH = os.path.join(DRAFT_STATE_DIR, ".automerge.lock")
LOCK_STALE_SECONDS = 900


def out(**payload) -> int:
    """Ett JSON-objekt paa stdout, alltid exit 0."""
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def receipt(job_key: str) -> dict | None:
    try:
        with open(os.path.join(DRAFT_STATE_DIR, job_key + ".json"),
                  encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def sibling_keys(order_id: str) -> list[str]:
    """job_key-ene for denne ordren som har et utkast, i bok-rekkefoelge."""
    pattern = os.path.join(DRAFT_STATE_DIR, "%s-b*.json" % order_id)
    keys = [os.path.basename(p)[:-5] for p in glob.glob(pattern)]

    def book_no(key: str) -> int:
        tail = key.rsplit("-b", 1)[-1]
        return int(tail) if tail.isdigit() else 0

    return sorted(keys, key=book_no)


def acquire_lock() -> bool:
    """Hindrer at to boeker som blir ferdige samtidig slaar sammen hver sin gang."""
    os.makedirs(DRAFT_STATE_DIR, exist_ok=True)
    try:
        age = time.time() - os.path.getmtime(LOCK_PATH)
        if age > LOCK_STALE_SECONDS:
            os.remove(LOCK_PATH)          # eier doede - laasen er foreldet
    except OSError:
        pass
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"pid": os.getpid(), "at": time.time()}, fh)
    return True


def release_lock() -> None:
    try:
        os.remove(LOCK_PATH)
    except OSError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--order-id", required=True,
                    help="WooCommerce-ordren, uten -bN (f.eks. 1411)")
    ap.add_argument("--book-count", type=int, required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    order_id = str(args.order_id).strip()
    count = int(args.book_count or 1)

    if count < 2:
        return out(merged=False, reason="enkeltbok-ordre - ingenting aa slaa sammen",
                   order_id=order_id, book_count=count)

    keys = sibling_keys(order_id)
    if len(keys) < count:
        return out(merged=False, reason="venter paa flere boeker",
                   order_id=order_id, have=len(keys), need=count, keys=keys)

    # Allerede slaatt sammen? Da har en av kvitteringene enten status "merged"
    # eller en merged_orders-liste med flere enn seg selv.
    for key in keys:
        rec = receipt(key) or {}
        if rec.get("status") == "merged" or len(rec.get("merged_orders") or []) > 1:
            return out(merged=False, reason="allerede slaatt sammen",
                       order_id=order_id, keys=keys,
                       draft_id=rec.get("merged_into_draft") or rec.get("draft_id"))

    if not acquire_lock():
        return out(merged=False, reason="en annen sammenslaaing paagaar",
                   order_id=order_id, keys=keys)

    lines: list[str] = []
    try:
        import dp_merge
        parts = [dp_merge.summarize(key) for key in keys]
        problems = dp_merge.check(parts)
        if problems:
            return out(merged=False, reason="blokkert", order_id=order_id,
                       keys=keys, problems=problems)
        if args.dry_run:
            return out(merged=False, reason="TORRKJORING", order_id=order_id,
                       keys=keys,
                       items=[{"job_key": p["order_id"], "barn": p["child_name"],
                               "bok": p["book_slug"],
                               "pdf_mb": round(p["size"] / 1e6, 1)} for p in parts])
        result = dp_merge.merge(parts, say=lines.append)
        return out(merged=True, order_id=order_id, keys=keys,
                   draft_id=result.get("draft_id"),
                   deleted=result.get("deleted"), items=result.get("items"),
                   log=lines)
    except SystemExit as stop:
        return out(merged=False, reason="stoppet: " + str(stop),
                   order_id=order_id, keys=keys, log=lines)
    except Exception as error:                                # noqa: BLE001
        return out(merged=False, reason="feil: " + str(error)[:300],
                   order_id=order_id, keys=keys, log=lines,
                   trace=traceback.format_exc()[-800:])
    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())

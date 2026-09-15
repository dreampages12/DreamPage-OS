# -*- coding: utf-8 -*-
"""En sammenslaatt ordre skal kunne BYGGES paa nytt fra Telegram.

Symptom (2026-09-06, ordre 1414-b2): «Bygg PDF paa nytt» svarte
«ordre 1414-b2 ligger i det sammenslaatte utkastet ... Slett det utkastet i
Gelato foerst, eller kjoer med --force» - og ga ingen vei videre.

`job_build` kalte `reprint_order.merge_guard`, men den sperren finnes for aa
hindre at det lages et ENKELT Gelato-utkast ved siden av det samlede (= to
trykte boeker for en betalt). Aa bygge en PDF paa disk kan ikke gjoere det.
`job_publish` har sin egen, riktige sperre, og kommentaren der sier det
allerede: «Aa bygge paa nytt er greit; det er publiseringen som er farlig.»
Vaktene sto altsaa ett steg for tidlig i byggeveien.

Etter patchen:

* `job_build` sperrer ikke. Den sier fra at ordren ligger i et samlet utkast,
  og at veien videre er aa slaa sammen paa nytt - `dp_merge` laster ALLTID opp
  PDF-en fra disk, saa den ombygde boka blir med i nyeste versjon.
* Knappene etter bygget bytter «📤 Drive + Gelato-utkast» med «🔗 Slaa sammen
  paa nytt» for slike ordre, saa neste trykk ikke gaar rett i den sperren som
  faktisk skal staa.
* Ny `dp_merge.merged_group(order_id)`: alle ordrene i det samlede utkastet,
  og den virker fra BEGGE sider - den primaere eier kvitteringen med
  `merged_orders`, en sekundaer peker bare paa den primaere.
* Ny `reprint_order.merged_state(order_id)`: kvitteringen naar ordren er en
  sekundaer. `merge_guard` bruker den, saa det er én lesning av tilstanden.

CLI-en (`reprint_order.py --order ... --apply`) er uroert: der daekker samme
kall bade bygging og `--gelato`, og `--force` er dokumentert.

  python patch_bot_build_merged.py --dry-run
  python patch_bot_build_merged.py --apply
  python patch_bot_build_merged.py --revert
"""
from __future__ import annotations

import argparse
import ast
import glob
import io
import os
import shutil
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TAG = "build-merged"

# ---------------------------------------------------------------- reprint_order
RO_OLD = '''    path = os.path.join(DRAFT_STATE_DIR, f"{order_id}.json")
    if not os.path.isfile(path) or force:
        return
    try:
        with open(path, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return
    if state.get("status") == "merged":
        raise SystemExit(
'''
RO_NEW = '''    state = None if force else merged_state(order_id)
    if state:
        raise SystemExit(
'''

RO_HELPER = '''def merged_state(order_id: str) -> dict | None:
    """Kvitteringen hvis ordren ligger INNE I et sammenslaatt utkast.

    Bare den sekundaere ordren far `status: "merged"`; den primaere beholder
    utkastet under sin egen referanse. Se dp_merge.merged_group() for hele
    gruppa uansett hvilken side du spor fra.
    """
    path = os.path.join(DRAFT_STATE_DIR, f"{order_id}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return state if state.get("status") == "merged" else None


'''

# ---------------------------------------------------------------- dp_merge
DM_OLD = '''def merged_primary(order_id: str) -> dict | None:'''
DM_NEW = '''def merged_group(order_id: str) -> list[str]:
    """Alle ordrene i det samlede utkastet denne ordren tilhorer, ellers [].

    Virker fra begge sider: den PRIMAERE eier kvitteringen med `merged_orders`,
    mens en SEKUNDAER bare har `merged_into_order` og maa slaa opp videre.
    Rekkefolgen bevares - den forste blir orderReferenceId ved en re-merge.
    """
    data = _receipt(order_id)
    if data and data.get("status") == "merged":
        data = _receipt(data.get("merged_into_order"))
    orders = [str(o) for o in ((data or {}).get("merged_orders") or [])]
    return orders if len(orders) > 1 else []


def _receipt(order_id) -> dict | None:
    if not order_id:
        return None
    path = os.path.join(DRAFT_STATE_DIR, str(order_id) + ".json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def merged_primary(order_id: str) -> dict | None:'''

# ---------------------------------------------------------------- dp_bot
BOT_OLD = '''    info = dp_order.resolve(order_id)
    reprint_order.merge_guard(order_id)
    skip_prepare = bool(extra.get("skip_prepare"))
'''
BOT_NEW = '''    info = dp_order.resolve(order_id)
    skip_prepare = bool(extra.get("skip_prepare"))

    # Ingen sperre her. Aa bygge en PDF paa disk kan ikke lage et duplikat hos
    # Gelato - det er publiseringen som kan det, og den sperren staar i
    # job_publish. Vi sier bare fra hva veien videre er.
    group = dp_merge.merged_group(order_id)
    if group:
        others = [o for o in group if str(o) != str(order_id)]
        send(chat_id,
             f"🔗 <b>{order_id}</b> ligger i et samlet Gelato-utkast sammen med "
             f"<b>{', '.join(others)}</b>. Bygget under er trygt — men naar du "
             "er ferdig maa du <b>slaa sammen paa nytt</b>, ikke lage et utkast "
             "for denne ordren alene.")
'''

BOT_BTN_OLD = '''    send(chat_id, text, [[
        {"text": "📤 Drive + Gelato-utkast", "callback_data": f"publish|{order_id}||1"},
        {"text": "📤 Bare Drive", "callback_data": f"publish|{order_id}||0"},
    ], [
'''
BOT_BTN_NEW = '''    # For en sammenslaatt ordre ville «Drive + Gelato-utkast» gaatt rett i
    # sperren i job_publish. Tilby re-merge i stedet - dp_merge laster alltid
    # opp PDF-en fra disk, saa det nettopp bygde blir med.
    publish_row = [
        {"text": "📤 Drive + Gelato-utkast", "callback_data": f"publish|{order_id}||1"},
        {"text": "📤 Bare Drive", "callback_data": f"publish|{order_id}||0"},
    ]
    if group:
        # Andre felt speiler menu_merge: den FORSTE ordren i lista, som blir
        # orderReferenceId. Behold gruppas egen rekkefolge, ellers bytter
        # re-mergen primaerordre og det samlede utkastet skifter referanse.
        publish_row = [{"text": "🔗 Slå sammen på nytt",
                        "callback_data": "mrgB|" + str(group[0]) + "||"
                                         + ",".join(str(o) for o in group)}]
    send(chat_id, text, [publish_row, [
'''

BOT_TEXT_OLD = '''            "Last opp til Drive og lag Gelato-utkast?")
'''
BOT_TEXT_NEW = '''            + ("Slå sammen på nytt for å oppdatere det samlede utkastet?"
               if group else "Last opp til Drive og lag Gelato-utkast?"))
'''

EDITS = [
    ("reprint_order.py", [(RO_OLD, RO_NEW)], ("def merge_guard", RO_HELPER)),
    ("dp_merge.py", [(DM_OLD, DM_NEW)], None),
    ("dp_bot.py", [(BOT_OLD, BOT_NEW), (BOT_TEXT_OLD, BOT_TEXT_NEW),
                   (BOT_BTN_OLD, BOT_BTN_NEW)], None),
]


def patch_file(text, pairs, insert):
    for old, new in pairs:
        if old not in text:
            return None, "fant ikke ankeret: %r" % old.strip().splitlines()[0]
        text = text.replace(old, new, 1)
    if insert:
        anchor, block = insert
        i = text.index(anchor)
        text = text[:i] + block + text[i:]
    return text, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--revert", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run or args.revert):
        ap.error("velg --dry-run, --apply eller --revert")

    if args.revert:
        for bak in sorted(glob.glob(os.path.join(SCRIPT_DIR, "*.backup-before-%s-*" % TAG))):
            shutil.copy2(bak, bak.split(".backup-before-")[0])
            print("  tilbakestilt", os.path.basename(bak.split(".backup-before-")[0]))
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    for name, pairs, insert in EDITS:
        path = os.path.join(SCRIPT_DIR, name)
        text = io.open(path, encoding="utf-8").read()
        new_text, err = patch_file(text, pairs, insert)
        if err:
            print("  HOPPER OVER %-20s %s" % (name, err))
            continue
        ast.parse(new_text)
        print("  %-20s ok" % name)
        if args.apply:
            shutil.copy2(path, "%s.backup-before-%s-%s" % (path, TAG, stamp))
            io.open(path, "w", encoding="utf-8", newline="").write(new_text)
    print("APPLIED" if args.apply else "DRY-RUN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

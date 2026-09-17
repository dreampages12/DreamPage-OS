# -*- coding: utf-8 -*-
"""Send en melding i operatoerbot-chatten fra kommandolinja.

    python tools/say_to_operator.py "Teksten" [--chat <id>]
    echo "Teksten" | python tools/say_to_operator.py

HVORFOR DEN FINNES

Naar noe stopper og en av oss holder paa aa rette det, trenger operatoeren
aa vite det FOER han begynner aa trykke paa knapper selv - to som retter
samme ordre samtidig er hvordan et samlet Gelato-utkast blir slettet.

Chatten gjettes ikke: `config/dp_bot.json` -> `chat_id` er Tobias' private
chat, mens oektene i `state/reprint/<id>.json` -> `chat_id` er den chatten
som faktisk brukes. Uten --chat brukes den sist brukte oekten, og faller
tilbake paa config. 17.09.2026 gikk en melding til den gale av de to.

Sender som botten selv, med HTML-formatering (<b>, <code>, <i>).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config", "dp_bot.json")
SESSIONS = os.path.join(ROOT, "state", "reprint", "*.json")


LAST_CHAT = os.path.join(ROOT, "state", "dp_bot_last_chat.json")


def active_chat() -> int | None:
    """Chatten botten sist fikk en melding eller et knappetrykk fra.

    Dette er fasiten naar den finnes: botten skriver den hver gang
    operatoeren roerer den.
    """
    try:
        with open(LAST_CHAT, encoding="utf-8") as fh:
            chat = json.load(fh).get("chat_id")
        return int(chat) if chat else None
    except (OSError, ValueError, TypeError):
        return None


def last_session_chat() -> int | None:
    """chat_id fra den sist endrede oekten - reserve hvis fasiten mangler."""
    best, newest = None, 0.0
    for path in glob.glob(SESSIONS):
        try:
            mtime = os.path.getmtime(path)
            if mtime <= newest:
                continue
            with open(path, encoding="utf-8") as fh:
                chat = json.load(fh).get("chat_id")
            if chat:
                best, newest = int(chat), mtime
        except (OSError, ValueError, TypeError):
            continue
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", help="meldingen (ellers leses stdin)")
    ap.add_argument("--chat", type=int, help="overstyr chat-ID")
    args = ap.parse_args()

    text = args.text if args.text is not None else sys.stdin.read()
    text = text.strip()
    if not text:
        ap.error("ingen tekst aa sende")

    with open(CONFIG, encoding="utf-8") as fh:
        conf = json.load(fh)
    chat_id = (args.chat or active_chat() or last_session_chat()
               or conf["chat_id"])

    body = json.dumps({"chat_id": chat_id, "text": text,
                       "parse_mode": "HTML",
                       "disable_web_page_preview": True}).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{conf['bot_token']}/sendMessage",
        data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as res:
        answer = json.load(res)
    print(f"sendt til chat {chat_id}: {answer.get('ok')}")
    return 0 if answer.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())

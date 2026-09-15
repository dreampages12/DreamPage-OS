# -*- coding: utf-8 -*-
"""Hemmeligheter, lest fra config/secrets.json - aldri fra kildekoden.

Gelato-noekkelen og worker-botens token laa hardkodet i tre filer
(`gelato_merge.py`, `tools/finish_order.py`, `tools/finish_merged_order.py`).
Med koden i git ville de blitt publisert, og en API-noekkel i git-historikk
maa roteres, ikke slettes - derfor ble de tatt ut FOER foerste commit.

`config/secrets.json` staar i `.gitignore`. `config/secrets.example.json`
viser formen.

Miljoevariabler vinner over fila, slik at en testkjoering kan bruke en annen
noekkel uten aa skrive over produksjonsverdien:

    DP_GELATO_API_KEY, DP_WORKER_BOT_TOKEN, DP_WORKER_CHAT_ID
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import CONFIG  # noqa: E402

SECRETS_PATH = CONFIG / "secrets.json"

_ENV = {
    "gelato_api_key": "DP_GELATO_API_KEY",
    "worker_bot_token": "DP_WORKER_BOT_TOKEN",
    "worker_chat_id": "DP_WORKER_CHAT_ID",
    "mockup_secret": "DP_MOCKUP_SECRET",
}

_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            with open(SECRETS_PATH, encoding="utf-8-sig") as fh:
                _cache = json.load(fh)
        except FileNotFoundError:
            _cache = {}
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{SECRETS_PATH} er ikke gyldig JSON: {exc}") from exc
    return _cache


def get(name: str, default=None):
    """Hemmeligheten, eller `default`. Miljoevariabelen vinner."""
    env = os.environ.get(_ENV.get(name, ""))
    if env:
        return env
    value = _load().get(name)
    return default if value in (None, "") else value


def require(name: str):
    """Som get(), men stopper med en forklaring i stedet for aa sende et
    tomt token til Gelato og faa en 401 lenger ned i kalltreet."""
    value = get(name)
    if value in (None, ""):
        raise SystemExit(
            f"hemmeligheten '{name}' mangler.\n"
            f"Legg den i {SECRETS_PATH} (se secrets.example.json), "
            f"eller sett {_ENV.get(name, 'DP_' + name.upper())} i miljoeet.")
    return value


def gelato_api_key() -> str:
    return require("gelato_api_key")

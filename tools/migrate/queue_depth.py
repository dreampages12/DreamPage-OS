# -*- coding: utf-8 -*-
"""Antall meldinger som venter paa dreampage-jobs. Skriver bare tallet.

Brukes av phase1_cutover.ps1. En melding som venter er GREIT under en
overgang: den blir liggende i koen og plukkes opp naar workeren er oppe. Det
er nettopp derfor RabbitMQ staar i midten.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "flow"))

try:
    import dp_secrets
    import pika
    cred = dp_secrets.get("rabbitmq") or {}
    params = pika.ConnectionParameters(
        host=cred["hostname"], port=int(cred.get("port") or 5672),
        virtual_host=cred.get("vhost") or "/",
        credentials=pika.PlainCredentials(cred["username"], cred["password"]),
        socket_timeout=10, blocked_connection_timeout=10)
    con = pika.BlockingConnection(params)
    try:
        res = con.channel().queue_declare(queue="dreampage-jobs", passive=True)
        print(res.method.message_count)
    finally:
        con.close()
except Exception:                                    # noqa: BLE001
    print("")

"""Publiser en jobb paa nytt til dreampage-jobs.

Payloaden hentes fra en tidligere n8n-execution, slik at den blir NOEYAKTIG
den samme som WooCommerce sendte - inkludert continue_code. Koden skal aldri
finnes paa; en reprint skal bruke den samme (se memory-notatet).

n8n lagrer execution_data i "flatted"-format: hver strengverdi er en indeks
inn i toppnivaa-arrayen. Oppslaget gjoeres BARE ett hopp - gir det en streng,
er vi ferdige. Ellers ville "1221" blitt tolket som indeks 1221.

  python republish_job.py --execution 2716 --dry-run
  python republish_job.py --execution 2716 --publish
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys

DB = r"C:\Users\tobia\.n8n\database.sqlite"
QUEUE = "dreampage-jobs"
CRED_ID = "paSMyl2k9MRFBE0P"
CRED_TOOL = "C:/DreamPage-OS/flow/n8n_credential.py"


def load_payload(execution_id: int) -> dict:
    con = sqlite3.connect(DB)
    row = con.execute("select data from execution_data where executionId=?",
                      (execution_id,)).fetchone()
    con.close()
    if not row:
        raise SystemExit(f"fant ingen execution_data for {execution_id}")
    arr = json.loads(row[0])

    def resolve(ref, depth=0):
        if depth > 40 or not isinstance(ref, str) or not ref.isdigit():
            return ref
        val = arr[int(ref)]
        if isinstance(val, str):
            return val
        if isinstance(val, list):
            return [resolve(x, depth + 1) for x in val]
        if isinstance(val, dict):
            return {k: resolve(v, depth + 1) for k, v in val.items()}
        return val

    # Jobbobjektet er det foerste som har baade order_id og raw_shape.
    for el in arr:
        if isinstance(el, dict) and "order_id" in el and "raw_shape" in el:
            return {k: resolve(v) for k, v in el.items()}
    raise SystemExit("fant ingen jobb-payload i denne executionen")


def credentials() -> dict:
    out = subprocess.run([sys.executable, CRED_TOOL, "--id", CRED_ID],
                         capture_output=True, text=True, encoding="utf-8")
    if out.returncode:
        raise SystemExit("kunne ikke dekryptere legitimasjon:\n" + out.stderr)
    return json.loads(out.stdout)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execution", type=int, required=True)
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.publish or args.dry_run):
        ap.error("velg --dry-run eller --publish")

    payload = load_payload(args.execution)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    print(f"koe          : {QUEUE}")
    print(f"felter       : {len(payload)}")
    print(f"stoerrelse   : {len(body.encode('utf-8'))} bytes")
    for k in ("order_id", "child_name", "book_slug", "language", "cover_type",
              "continue_code", "next_book_slug"):
        print(f"  {k:16s} {payload.get(k)!r}")

    if not args.publish:
        print("TORRKJORING - ingenting publisert")
        return 0

    import pika

    cred = credentials()
    params = pika.ConnectionParameters(
        host=cred["hostname"],
        port=int(cred.get("port") or 5672),
        virtual_host=cred.get("vhost") or "/",
        credentials=pika.PlainCredentials(cred["username"], cred["password"]),
        heartbeat=30,
        blocked_connection_timeout=30,
    )
    conn = pika.BlockingConnection(params)
    ch = conn.channel()
    ch.confirm_delivery()
    ch.basic_publish(
        exchange="",
        routing_key=QUEUE,
        body=body.encode("utf-8"),
        properties=pika.BasicProperties(delivery_mode=2,
                                        content_type="application/json"),
    )
    conn.close()
    print("PUBLISERT")
    return 0


if __name__ == "__main__":
    sys.exit(main())

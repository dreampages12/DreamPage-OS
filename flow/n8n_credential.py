"""Les en n8n-legitimasjon utenfor n8n.

n8n krypterer credentials_entity.data med CryptoJS AES i OpenSSL sitt
"Salted__"-format, med encryptionKey fra ~/.n8n/config som passord. Nokkel og
IV utledes med EVP_BytesToKey (MD5), som er det CryptoJS gjor.

Brukes til aa kalle Google Drive direkte naar en jobb maa kjores utenfor
workflowen. Skriver aldri legitimasjonen til disk.

Bruk:
  python n8n_credential.py --id 8Udm8DTuztrnxpuv [--field oauthTokenData]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sqlite3
import sys

from Crypto.Cipher import AES

CONFIG = r"C:\Users\tobia\.n8n\config"
DB = r"C:\Users\tobia\.n8n\database.sqlite"


def evp_bytes_to_key(password: bytes, salt: bytes, key_len: int, iv_len: int):
    d = b""
    prev = b""
    while len(d) < key_len + iv_len:
        prev = hashlib.md5(prev + password + salt).digest()
        d += prev
    return d[:key_len], d[key_len:key_len + iv_len]


def decrypt(blob: str, password: str) -> str:
    raw = base64.b64decode(blob)
    if raw[:8] != b"Salted__":
        raise SystemExit("uventet format - forventet OpenSSL 'Salted__'")
    salt = raw[8:16]
    key, iv = evp_bytes_to_key(password.encode(), salt, 32, 16)
    data = AES.new(key, AES.MODE_CBC, iv).decrypt(raw[16:])
    pad = data[-1]
    return data[:-pad].decode("utf-8")


def load(credential_id: str) -> dict:
    with open(CONFIG, encoding="utf-8") as fh:
        key = json.load(fh)["encryptionKey"]
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    row = con.execute(
        "select name, type, data from credentials_entity where id=?", (credential_id,)
    ).fetchone()
    con.close()
    if not row:
        raise SystemExit(f"ukjent legitimasjon: {credential_id}")
    return {"name": row[0], "type": row[1], "data": json.loads(decrypt(row[2], key))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--field", default="")
    ap.add_argument("--show-keys", action="store_true",
                    help="vis bare feltnavn, ikke verdier")
    args = ap.parse_args()

    cred = load(args.id)
    if args.show_keys:
        print(cred["name"], "|", cred["type"])
        print("felter:", sorted(cred["data"].keys()))
        return 0
    if args.field:
        print(json.dumps(cred["data"].get(args.field)))
        return 0
    print(json.dumps(cred["data"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

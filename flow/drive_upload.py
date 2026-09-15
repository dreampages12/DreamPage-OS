"""Last opp en fil til Google Drive med n8n sin legitimasjon, og del den.

Gjor det samme som nodene Create Drive Folder / Upload / Make Public i
workflowen, slik at en ordre kan ferdigstilles utenfor n8n uten aa maatte
kjore hele jobben paa nytt.

Bruk:
  python drive_upload.py --file <sti> --parent <mappe-id> [--folder 1205] [--public]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from n8n_credential import load  # noqa: E402

CRED_ID = "8Udm8DTuztrnxpuv"
UA = "DreamPage-Worker/1.0"


def _req(url, data=None, headers=None, method=None):
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("User-Agent", UA)
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    with urllib.request.urlopen(r, timeout=600) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


def access_token() -> str:
    d = load(CRED_ID)["data"]
    body = urllib.parse.urlencode({
        "client_id": d["clientId"],
        "client_secret": d["clientSecret"],
        "refresh_token": d["oauthTokenData"]["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    tok = _req("https://oauth2.googleapis.com/token", data=body,
               headers={"Content-Type": "application/x-www-form-urlencoded"})
    return tok["access_token"]


def find_or_create_folder(token: str, name: str, parent: str) -> str:
    q = (f"name='{name}' and '{parent}' in parents and "
         "mimeType='application/vnd.google-apps.folder' and trashed=false")
    url = ("https://www.googleapis.com/drive/v3/files?q=" + urllib.parse.quote(q) +
           "&fields=files(id,name)&supportsAllDrives=true")
    res = _req(url, headers={"Authorization": f"Bearer {token}"})
    if res.get("files"):
        print(f"[DRIVE] fant mappe {name}: {res['files'][0]['id']}")
        return res["files"][0]["id"]
    meta = json.dumps({"name": name, "parents": [parent],
                       "mimeType": "application/vnd.google-apps.folder"}).encode()
    res = _req("https://www.googleapis.com/drive/v3/files?fields=id&supportsAllDrives=true",
               data=meta, headers={"Authorization": f"Bearer {token}",
                                   "Content-Type": "application/json"})
    print(f"[DRIVE] opprettet mappe {name}: {res['id']}")
    return res["id"]


def upload(token: str, path: str, parent: str) -> dict:
    """Resumable upload - de kombinerte PDF-ene er titalls megabyte."""
    name = os.path.basename(path)
    size = os.path.getsize(path)
    meta = json.dumps({"name": name, "parents": [parent]}).encode()
    req = urllib.request.Request(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable"
        "&fields=id,name,webViewLink,webContentLink&supportsAllDrives=true",
        data=meta, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json; charset=UTF-8")
    req.add_header("X-Upload-Content-Type", "application/pdf")
    req.add_header("X-Upload-Content-Length", str(size))
    with urllib.request.urlopen(req, timeout=120) as resp:
        session_url = resp.headers["Location"]

    with open(path, "rb") as fh:
        body = fh.read()
    put = urllib.request.Request(session_url, data=body, method="PUT")
    put.add_header("Content-Type", "application/pdf")
    put.add_header("Content-Length", str(size))
    with urllib.request.urlopen(put, timeout=1800) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    print(f"[DRIVE] lastet opp {name} ({size // 1024 // 1024} MB): {res['id']}")
    return res


def find_by_name(token: str, name: str, parent: str) -> list[dict]:
    q = f"name='{name}' and '{parent}' in parents and trashed=false"
    url = ("https://www.googleapis.com/drive/v3/files?q=" + urllib.parse.quote(q) +
           "&fields=files(id,name,createdTime)&supportsAllDrives=true")
    return _req(url, headers={"Authorization": f"Bearer {token}"}).get("files", [])


def trash(token: str, file_id: str) -> None:
    _req(f"https://www.googleapis.com/drive/v3/files/{file_id}?supportsAllDrives=true",
         data=json.dumps({"trashed": True}).encode(), method="PATCH",
         headers={"Authorization": f"Bearer {token}",
                  "Content-Type": "application/json"})
    print(f"[DRIVE] la gammel duplikat i papirkurven: {file_id}")


def make_public(token: str, file_id: str) -> None:
    _req(f"https://www.googleapis.com/drive/v3/files/{file_id}/permissions"
         "?supportsAllDrives=true",
         data=json.dumps({"role": "reader", "type": "anyone"}).encode(),
         headers={"Authorization": f"Bearer {token}",
                  "Content-Type": "application/json"})
    print(f"[DRIVE] delt offentlig: {file_id}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--parent", required=True, help="overordnet mappe-id")
    ap.add_argument("--folder", default="", help="undermappe (f.eks. ordre-id)")
    ap.add_argument("--public", action="store_true")
    ap.add_argument("--replace", action="store_true",
                    help="rydd bort eldre filer med samme navn i mappa")
    args = ap.parse_args()

    token = access_token()
    parent = args.parent
    if args.folder:
        parent = find_or_create_folder(token, args.folder, parent)

    # Duplikatene ryddes ETTER at den nye fila er oppe, ikke foer. Feiler
    # opplastingen midtveis vil et eksisterende Gelato-utkast fortsatt peke paa
    # en gyldig fil - samme prinsipp som gelato_merge bruker for utkast.
    stale = find_by_name(token, os.path.basename(args.file), parent) if args.replace else []

    res = upload(token, args.file, parent)

    for old in stale:
        if old["id"] != res["id"]:
            trash(token, old["id"])

    if args.public:
        make_public(token, res["id"])
    # drive.usercontent.google.com i stedet for drive.google.com/uc: over 100 MB
    # svarer den gamle lenka med en HTML-side ("Google Drive - Virus scan
    # warning") i stedet for fila. Gelato henter da 2 kB HTML og item-et blir
    # aldri ferdig (files[].id = null). Traff ordre 1296 da PDF-en vokste fra
    # 73 MB til 106 MB. confirm=t hopper over varselet; lenka funker like godt
    # for smaa filer, saa den brukes for alle.
    direct = (f"https://drive.usercontent.google.com/download"
              f"?id={res['id']}&export=download&confirm=t")
    print(json.dumps({"id": res["id"], "name": res["name"],
                      "webViewLink": res.get("webViewLink"),
                      "downloadUrl": direct}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

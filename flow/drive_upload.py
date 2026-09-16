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
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from n8n_credential import load  # noqa: E402

CRED_ID = "8Udm8DTuztrnxpuv"
UA = "DreamPage-Worker/1.0"

# Google svarer med disse naar det er dem det staar paa, ikke oss. De skal
# proeves paa nytt - ordre 1512 doede paa en enkelt HTTP 500 midt i en
# opplasting som ellers gikk fint, og tok Gelato-utkastet med seg i fallet.
RETRY_STATUS = {408, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 6


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """308 fra en opplastingssesjon betyr "fortsett", ikke "gaa hit".

    Python 3.11+ foelger 308 automatisk. Da forsvinner Range-headeren som
    forteller hvor mange bytes Google faktisk fikk, og vi ville lastet opp
    alt paa nytt i blinde.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if code == 308:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_NoRedirect)


def _sleep(attempt: int) -> None:
    """Eksponentiell backoff med litt slark, slik Google ber om."""
    delay = min(2 ** attempt, 60) + random.uniform(0, 1)
    print(f"[DRIVE] venter {delay:.1f} s foer forsoek {attempt + 1}/{MAX_ATTEMPTS}")
    time.sleep(delay)


def _open(req, timeout):
    return _OPENER.open(req, timeout=timeout)


def _req(url, data=None, headers=None, method=None):
    last = None
    for attempt in range(MAX_ATTEMPTS):
        r = urllib.request.Request(url, data=data, method=method)
        r.add_header("User-Agent", UA)
        for k, v in (headers or {}).items():
            r.add_header(k, v)
        try:
            with _open(r, timeout=600) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as error:
            if error.code not in RETRY_STATUS:
                raise
            last = error
            print(f"[DRIVE] {method or 'GET'} {url.split('?')[0]} ga HTTP {error.code}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last = error
            print(f"[DRIVE] {method or 'GET'} feilet: {error}")
        if attempt + 1 < MAX_ATTEMPTS:
            _sleep(attempt)
    raise last


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


def _start_session(token: str, name: str, size: int, parent: str) -> str:
    """Be Google om en opplastingssesjon. Selve URL-en er engangsbruk."""
    meta = json.dumps({"name": name, "parents": [parent]}).encode()
    last = None
    for attempt in range(MAX_ATTEMPTS):
        req = urllib.request.Request(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable"
            "&fields=id,name,webViewLink,webContentLink&supportsAllDrives=true",
            data=meta, method="POST")
        req.add_header("User-Agent", UA)
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Content-Type", "application/json; charset=UTF-8")
        req.add_header("X-Upload-Content-Type", "application/pdf")
        req.add_header("X-Upload-Content-Length", str(size))
        try:
            with _open(req, timeout=120) as resp:
                return resp.headers["Location"]
        except urllib.error.HTTPError as error:
            if error.code not in RETRY_STATUS:
                raise
            last = error
            print(f"[DRIVE] kunne ikke aapne sesjon: HTTP {error.code}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last = error
            print(f"[DRIVE] kunne ikke aapne sesjon: {error}")
        if attempt + 1 < MAX_ATTEMPTS:
            _sleep(attempt)
    raise last


def _received(session_url: str, size: int):
    """Hvor mange bytes fikk Google faktisk? -> (offset, ferdig-svar eller None).

    Et tomt PUT med "Content-Range: bytes */<size>" er Googles maate aa
    sporre paa. 308 betyr "ikke ferdig, jeg har til og med byte N"; 200/201
    betyr at opplastingen gikk igjennom likevel og svaret er fila.
    """
    req = urllib.request.Request(session_url, data=b"", method="PUT")
    req.add_header("User-Agent", UA)
    req.add_header("Content-Range", f"bytes */{size}")
    try:
        with _open(req, timeout=120) as resp:
            return size, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as error:
        if error.code != 308:
            raise
        rng = error.headers.get("Range")
        # Ingen Range = ingenting er kommet fram enda.
        return (int(rng.split("-")[1]) + 1 if rng else 0), None


def _put(session_url: str, body: bytes, offset: int, size: int) -> dict:
    req = urllib.request.Request(session_url, data=body[offset:], method="PUT")
    req.add_header("User-Agent", UA)
    req.add_header("Content-Type", "application/pdf")
    req.add_header("Content-Range", f"bytes {offset}-{size - 1}/{size}")
    with _open(req, timeout=1800) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


def upload(token: str, path: str, parent: str) -> dict:
    """Resumable upload - de kombinerte PDF-ene er titalls megabyte.

    Gjenopptar der Google stoppet i stedet for aa gi opp. Ordre 1512 feilet
    paa HTTP 500 i det avsluttende PUT-et, og fordi reprint_order avbryter
    paa foerste feil ble hverken innmat eller Gelato-utkast rort.
    """
    name = os.path.basename(path)
    size = os.path.getsize(path)
    if not size:
        raise SystemExit(f"{path} er tom - nekter aa laste den opp")
    with open(path, "rb") as fh:
        body = fh.read()

    session_url = _start_session(token, name, size, parent)
    offset = 0
    last = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            res = _put(session_url, body, offset, size)
            print(f"[DRIVE] lastet opp {name} ({size // 1024 // 1024} MB): {res['id']}")
            return res
        except urllib.error.HTTPError as error:
            if error.code in (404, 410):
                # Sesjonen er borte. Da hjelper det ikke aa gjenoppta - ny sesjon.
                print(f"[DRIVE] sesjonen utloept (HTTP {error.code}) - starter ny")
                last = error
                if attempt + 1 < MAX_ATTEMPTS:
                    _sleep(attempt)
                    session_url = _start_session(token, name, size, parent)
                    offset = 0
                continue
            if error.code not in RETRY_STATUS:
                raise
            last = error
            print(f"[DRIVE] opplasting av {name} ga HTTP {error.code}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last = error
            print(f"[DRIVE] opplasting av {name} brast: {error}")
        if attempt + 1 >= MAX_ATTEMPTS:
            break
        _sleep(attempt)
        # Sporr hvor langt vi kom, slik at vi bare sender resten.
        try:
            offset, done = _received(session_url, size)
        except urllib.error.HTTPError as error:
            if error.code not in (404, 410):
                raise
            session_url = _start_session(token, name, size, parent)
            offset = 0
            continue
        if done:
            print(f"[DRIVE] {name} var oppe likevel: {done['id']}")
            return done
        print(f"[DRIVE] gjenopptar {name} fra {offset // 1024 // 1024} MB av "
              f"{size // 1024 // 1024} MB")
    raise SystemExit(f"Drive-opplasting av {name} feilet etter {MAX_ATTEMPTS} "
                     f"forsoek. Siste feil: {last}")


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

# -*- coding: utf-8 -*-
"""Levering av en ferdig forhaandsvisning: statusfil, opplasting, callback.

Dette er den ENE veien ut av PREVIEW-modus, paa samme maate som notify.py er
den ene veien ut til operatoeren. Alt som naar verden utenfor maskinen staar
her, saa grensen kan leses paa ett sted.

Tre mottakere, og de har ulik vekt:

  statusfil   `<bucket>/preview-jobs/<job_id>.json`. Det er den frontenden
              poller: processing -> completed/failed. Den skrives OGSAA
              lokalt under state/preview_jobs/, alltid, fordi den lokale
              kopien er det eneste sporet som finnes naar nettet var nede i
              det oeyeblikket jobben ble ferdig.
  bildet      `<bucket>/previews/<session>/<job_id>_preview.jpg`. PAAKREVD.
              Uten det finnes det ingen forhaandsvisning aa vise.
  callback    POST til `preview_callback_url`. Et sidespor: jobben er alt
              "completed" naar den sendes, og et tapt callback betyr at
              frontenden faar svaret sitt fra pollingen i stedet.

DET FINNES INGEN STILLE FALLBACK TIL DISK. `preview.sink` i config/flow.json
maa staa til "supabase" eller "local", og "supabase" uten legitimasjon er en
hard feil. Alternativet - aa skrive bildet lokalt og si "ferdig" - ville
vaert en jobb som ser vellykket ut mens kunden ser en tom rute. Det er
noeyaktig feilklassen CLAUDE.md handler om.
"""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from paths import PREVIEW_JOBS, ROOT  # noqa: E402
import config as flow_config  # noqa: E402
import dp_secrets  # noqa: E402
from books import JobError  # noqa: E402

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"


# ---------------------------------------------------------------------------
# Oppsett
# ---------------------------------------------------------------------------
def sink_name() -> str:
    return str(flow_config.preview().get("sink") or "supabase").lower()


def _supabase_credentials() -> dict:
    """{"url", "key"} fra config/secrets.json -> "supabase", eller {}."""
    cred = dp_secrets.get("supabase") or {}
    if not isinstance(cred, dict):
        return {}
    url = str(cred.get("url") or "").rstrip("/")
    key = str(cred.get("service_key") or cred.get("key") or "")
    return {"url": url, "key": key} if url and key else {}


def check_ready() -> dict:
    """Kan denne maskinen i det hele tatt LEVERE en forhaandsvisning?

    Kalles som foerste steg i preview-pipelinen, foer GPU-en bruker tjue
    sekunder paa et bilde ingen kan motta. Samme resonnement som
    `check_assets` i bokpipelinen: mangelen skal oppdages FOER rendringen.
    """
    name = sink_name()
    if name == "local":
        return {"sink": "local",
                "note": "bildet blir liggende paa disk - ikke for produksjon"}
    if name != "supabase":
        raise JobError(f"ukjent preview.sink {name!r} i config/flow.json. "
                       f"Lov: supabase, local.")
    cred = _supabase_credentials()
    if not cred:
        raise JobError(
            "preview.sink er \"supabase\", men config/secrets.json har ingen "
            "\"supabase\": {\"url\": ..., \"service_key\": ...}. Uten den kan "
            "et ferdig preview ikke leveres, og jobben ville sett vellykket "
            "ut mens kunden saa en tom rute. Legg inn legitimasjonen, eller "
            "sett preview.sink til \"local\" for utvikling.")
    return {"sink": "supabase", "url": cred["url"]}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _request(url: str, data: bytes | None, headers: dict, method: str,
             timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"User-Agent": UA, **headers})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.status, res.read().decode("utf-8", "replace")[:2000]


def _storage_upload(path_in_bucket: str, bucket: str, payload: bytes,
                    content_type: str, timeout: float) -> str:
    """Legg en fil i Supabase Storage og returner den offentlige URL-en.

    `x-upsert: true` fordi en jobb kan komme to ganger fra koen (ordre 1499
    kom tre ganger paa én dag i bokverdenen, og preview-koen har samme
    at-least-once-garanti). Da skal det bli ÉN fil, ikke en 409.
    """
    cred = _supabase_credentials()
    if not cred:
        raise JobError("mangler Supabase-legitimasjon - se check_ready()")
    quoted = urllib.parse.quote(path_in_bucket)
    url = f"{cred['url']}/storage/v1/object/{bucket}/{quoted}"
    headers = {
        "Authorization": f"Bearer {cred['key']}",
        "Content-Type": content_type,
        "x-upsert": "true",
    }
    try:
        _request(url, payload, headers, "POST", timeout)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        # Feilteksten tas med: en 403 fra Storage betyr noe helt annet enn en
        # 404, og "opplastingen feilet" alene sender noen paa leting i GPU-en.
        raise RuntimeError(f"Supabase Storage svarte {exc.code} paa "
                           f"{bucket}/{path_in_bucket}: {detail}") from exc
    return f"{cred['url']}/storage/v1/object/public/{bucket}/{quoted}"


# ---------------------------------------------------------------------------
# Statusfila
# ---------------------------------------------------------------------------
def _status_record(job: dict | None, job_id: str, status: str,
                   **extra) -> dict:
    job = job or {}
    record = {
        "job_id": job_id,
        "status": status,
        "at": _now(),
        "book_slug": job.get("book_slug"),
        "book_title": job.get("book_title"),
        "asset_kind": job.get("asset_kind"),
        "market": job.get("market"),
        "dp_session_id": job.get("session_id"),
        "child_name": job.get("child_name"),
    }
    record.update({k: v for k, v in extra.items() if v is not None})
    return record


def _now() -> str:
    import jobs as jobs_mod
    return jobs_mod.now()


def write_status(job_id: str, record: dict, log=None) -> dict:
    """Skriv statusfila lokalt, og til Supabase naar den er sinken.

    Den lokale kopien skrives FOERST og alltid. Feiler opplastingen, har vi
    fortsatt et spor av hva som skjedde - og en operatoer som spoer "hva
    skjedde med jobb X" faar et svar uten aa maatte naa Supabase.
    """
    out = {"local": None, "remote": None}
    PREVIEW_JOBS.mkdir(parents=True, exist_ok=True)
    path = PREVIEW_JOBS / f"{job_id}.json"
    body = json.dumps(record, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, path)
    out["local"] = str(path)

    if sink_name() != "supabase":
        return out

    conf = flow_config.preview().get("supabase") or {}
    bucket = str(conf.get("status_bucket") or "uploads")
    prefix = str(conf.get("status_prefix") or "preview-jobs").strip("/")
    timeout = float(conf.get("timeout_s") or 60)
    try:
        out["remote"] = _storage_upload(
            f"{prefix}/{job_id}.json", bucket, body.encode("utf-8"),
            "application/json", timeout)
    except (RuntimeError, JobError, urllib.error.URLError, OSError) as exc:
        # Statusfila er hvordan frontenden ser fremdrift. At den ikke kom
        # fram skal IKKE drepe jobben - bildet er fortsatt det som betyr
        # noe - men det skal staa i loggen at den ikke kom fram.
        if log:
            log.warn(f"statusfila naadde ikke Supabase: {exc}")
        out["error"] = str(exc)
    return out


def processing(job: dict, log=None) -> dict:
    return write_status(job["job_id"],
                        _status_record(job, job["job_id"], "processing"), log)


def completed(job: dict, image_url: str, log=None) -> dict:
    return write_status(job["job_id"],
                        _status_record(job, job["job_id"], "completed",
                                       preview_url=image_url), log)


def failed(job_id: str, error: str, job: dict | None = None, log=None) -> dict:
    return write_status(job_id,
                        _status_record(job, job_id, "failed", error=str(error)),
                        log)


# ---------------------------------------------------------------------------
# Bildet
# ---------------------------------------------------------------------------
def upload_result(job: dict, path: Path, log=None) -> str:
    """Last opp det ferdige bildet og returner URL-en kunden skal se.

    Kaster hvis det ikke gikk. Dette er det ene steget i preview-pipelinen
    som ikke har lov til aa vaere fail-soft.
    """
    path = Path(path)
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError(f"det ferdige preview-bildet finnes ikke eller er "
                           f"tomt: {path}")

    if sink_name() == "local":
        # Eksplisitt valgt lokal modus. URL-en er en filsti, og den SIER at
        # den er det, slik at ingen tror dette er noe kunden kan aapne.
        return path.resolve().as_uri()

    conf = flow_config.preview().get("supabase") or {}
    bucket = str(conf.get("result_bucket") or "storage")
    prefix = str(conf.get("result_prefix") or "previews").strip("/")
    timeout = float(conf.get("timeout_s") or 60)
    session = job.get("session_id") or job["job_id"]
    name = f"{job['job_id']}_preview{path.suffix.lower() or '.jpg'}"
    content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    url = _storage_upload(f"{prefix}/{session}/{name}", bucket,
                          path.read_bytes(), content_type, timeout)
    if log:
        log.info("preview lastet opp", bytes=path.stat().st_size)
    return url


# ---------------------------------------------------------------------------
# Callback til nettbutikken
# ---------------------------------------------------------------------------
def callback(job: dict, image_url: str, log=None) -> dict:
    """POST resultatet til `preview_callback_url`.

    Sidespor. Jobben er alt "completed" i statusfila naar dette kalles, saa
    en feil her betyr at frontenden faar svaret sitt fra pollingen i stedet -
    ikke at kunden mister forhaandsvisningen. Derfor kaster den ikke.
    """
    url = str(job.get("callback_url") or "").strip()
    if not url:
        return {"sent": False, "reason": "ingen preview_callback_url"}
    body = json.dumps({
        "job_id": job["job_id"],
        "status": "completed",
        "preview_url": image_url,
        "dp_session_id": job.get("session_id"),
        "book_slug": job.get("book_slug"),
        "asset_type": job.get("asset_kind"),
        "preview_token": job.get("preview_token"),
    }, ensure_ascii=False).encode("utf-8")
    timeout = float(flow_config.preview().get("callback_timeout_s") or 30)
    try:
        status, _ = _request(url, body, {"Content-Type": "application/json"},
                             "POST", timeout)
        return {"sent": True, "http": status}
    except (urllib.error.URLError, OSError) as exc:
        if log:
            log.warn(f"callback til nettbutikken feilet: {exc}")
        return {"sent": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Feilrapportering, kalt fra notify.job_failed
# ---------------------------------------------------------------------------
def report_failed(job_key: str, error: str, log=None) -> dict:
    """Skriv `failed` i statusfila for en preview-jobb som stoppet.

    Kalles fra notify.job_failed, altsaa det ENE stedet en feilet jobb
    allerede sier fra. Poenget er at frontenden ikke skal staa og polle en
    `processing` som aldri blir noe: da venter kunden paa en spinner for
    alltid, og det er samme stillhet som ordre 1517.

    Kaster aldri. En varsling som blir feilen er en verre feil.
    """
    try:
        return failed(job_key, error, log=log)
    except Exception as exc:                          # noqa: BLE001
        if log:
            log.warn(f"kunne ikke skrive failed-status for {job_key}: {exc}")
        return {"sent": False, "error": str(exc)}


def local_output_dir(job_id: str) -> Path:
    """output/preview/<job_id>/ - der de ferdige filene legges."""
    rel = str(flow_config.preview().get("output_dir") or "output/preview")
    base = Path(rel)
    if not base.is_absolute():
        base = ROOT / base
    return base / str(job_id)

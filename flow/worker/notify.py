# -*- coding: utf-8 -*-
"""Varsling til operatoeren. Én vei ut, brukt av alle som skal si fra.

Hvorfor denne fila finnes:

Fram til 16.09.2026 fantes det to varsler i hele workeren - `notify_pages_ready`
og `telegram_approval` - og BEGGE fyrte bare naar det gikk bra. En jobb som
feilet ble skrevet til `state/jobs.sqlite` med status `failed` og feilteksten
sin, og saa var det stille. Ingen fikk beskjed.

Det er noeyaktig ordre 1517 om igjen. Den stoppet fordi
`books/hestestjernen/config.json` ikke fantes; n8n skrev `success`, kunden
ventet. Svaret den gangen var at `validate_job` skulle avvise en ubyggbar bok
med en setning som sier hva som mangler - og det gjoer den. Men setningen gikk
til en database ingen ser paa. Feilen var flyttet fra n8n til SQLite, ikke
fjernet.

Regelen er derfor: **en betalt ordre som stopper, skal si fra selv.**

Varsling er alltid et sidespor. Feiler den, logges det og arbeidet gaar
videre - en ordre der varselet ikke kom fram er ikke en feilet ordre, den er
en ordre ingen har sett. Derfor kaster ingenting her.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dp_secrets  # noqa: E402
from paths import STATE  # noqa: E402

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# Telegram kutter meldinger over 4096 tegn. En traceback er lengre enn det,
# og en kuttet melding fra Telegram er en 400 - altsaa INGEN melding.
MAX_LEN = 3900


def enabled() -> bool:
    return bool(dp_secrets.get("worker_bot_token")) and \
        dp_secrets.get("worker_chat_id") not in (None, "")


def _post(token: str, chat, text: str, timeout: int) -> dict:
    body = json.dumps({"chat_id": chat, "text": text,
                       "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return {"sent": True, "http": res.status}


# ---------------------------------------------------------------------------
# Utboksen: et varsel som ikke kom fram, er ikke borte
# ---------------------------------------------------------------------------
# Hver natt 04:30-05:05 er utgaaende HTTPS nede paa maskinen (se
# net.wait_for_internet). Ordre 1532 doede i det vinduet 17.09.2026 - og
# varselet om at den doede gikk over det samme nedlagte nettet. Det ble en
# linje i loggen, og ordren laa i fem timer til noen aapnet panelet.
#
# Et varsel som feiler, skrives derfor hit og sendes neste gang noe lykkes:
# ved neste varsel, eller naar vaktmesteren kjoerer `notify.py flush` hvert
# 5. minutt. Den kommer sent, og den sier at den kommer sent.
OUTBOX = STATE / "notify_outbox"


def _queue(text: str) -> Path | None:
    try:
        OUTBOX.mkdir(parents=True, exist_ok=True)
        now = datetime.now().astimezone()
        path = OUTBOX / f"{now.strftime('%Y%m%d-%H%M%S-%f')}.json"
        path.write_text(json.dumps({"at": now.isoformat(timespec="seconds"),
                                    "text": text}, ensure_ascii=False),
                        encoding="utf-8")
        return path
    except OSError:
        return None


def flush(log=None, timeout: int = 30) -> dict:
    """Send det som ligger i utboksen, eldst foerst. Stopper ved foerste
    feil - da er nettet fortsatt nede, og resten venter til neste gang."""
    token = dp_secrets.get("worker_bot_token")
    chat = dp_secrets.get("worker_chat_id")
    files = sorted(OUTBOX.glob("*.json")) if OUTBOX.is_dir() else []
    sent = 0
    if not files or not token or chat in (None, ""):
        return {"sent": 0, "waiting": len(files)}
    for path in files:
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Legges til side, ikke slettes - men skal ikke stenge koeen.
            try:
                path.rename(path.with_suffix(".bad"))
            except OSError:
                pass
            continue
        text = (f"⏳ Forsinket varsel, skrevet {str(item.get('at'))[:16]} "
                f"mens nettet var nede:\n\n{item.get('text', '')}")
        if len(text) > MAX_LEN:
            text = text[:MAX_LEN] + "\n... (kuttet)"
        try:
            _post(token, chat, text, timeout)
        except (urllib.error.URLError, OSError) as exc:
            if log:
                log.warn(f"utboksen: fortsatt ikke fram ({exc})")
            break
        path.unlink(missing_ok=True)
        sent += 1
    waiting = len(list(OUTBOX.glob("*.json")))
    return {"sent": sent, "waiting": waiting}


def send(text: str, log=None, timeout: int = 30) -> dict:
    """Send én melding. Returnerer alltid - kaster aldri.

    `log` er valgfri (en Log eller None), fordi denne ogsaa kalles fra
    steder som ikke har en jobb-logg, som vaktmesteren.

    Kommer meldingen ikke fram, legges den i utboksen i stedet for aa
    forsvinne. Kommer den fram, sendes det som ventet i utboksen etterpaa.
    """
    token = dp_secrets.get("worker_bot_token")
    chat = dp_secrets.get("worker_chat_id")
    if not token or chat in (None, ""):
        if log:
            log.warn("worker_bot_token/worker_chat_id mangler - ingen varsling")
        return {"sent": False, "reason": "mangler token eller chat_id"}

    if len(text) > MAX_LEN:
        text = text[:MAX_LEN] + "\n... (kuttet)"

    try:
        result = _post(token, chat, text, timeout)
    except (urllib.error.URLError, OSError) as exc:
        queued = _queue(text)
        if log:
            log.error(f"Telegram-varsel feilet: {exc} - "
                      + ("lagt i utboksen" if queued else "KUNNE IKKE LAGRES"))
        return {"sent": False, "error": str(exc), "queued": bool(queued)}

    if OUTBOX.is_dir() and any(OUTBOX.glob("*.json")):
        try:
            result["outbox"] = flush(log, timeout)
        except Exception as exc:                     # noqa: BLE001
            if log:
                log.warn(f"utboksen kunne ikke toemmes: {exc}")
    return result


def _is_preview() -> bool:
    try:
        import config as flow_config
        return flow_config.mode() == "preview"
    except Exception:                                 # noqa: BLE001
        return False


def _report_preview_failure(job_key: str, error: str, log=None) -> None:
    """Statusfila for en feilet PREVIEW-jobb. No-op i bokmodus.

    Ligger her, og ikke i preview-pipelinen, fordi et steg som feiler
    avbryter pipelinen - da kjoerer ingen senere steg. job_failed er det ENE
    stedet alle feilende jobber uansett kommer forbi.

    Svelger alt. En rapportering som blir feilen er en verre feil, og denne
    kalles fra en except-gren der et unntak ville spist RabbitMQ-ack-en.
    """
    try:
        import config as flow_config
        if flow_config.mode() != "preview":
            return
        import preview_sink
        preview_sink.report_failed(job_key, error, log)
    except Exception as exc:                          # noqa: BLE001
        if log:
            log.warn(f"kunne ikke skrive failed-status for {job_key}: {exc}")


def job_failed(job_key: str, job: dict, error: str, kind: str,
               step: str | None, permanent: bool, log=None) -> dict:
    """Varselet som mangler i dag: en ordre stoppet.

    `permanent` skiller de to tilfellene operatoeren maa handle ulikt paa:

      permanent=True   jobbens EGEN feil - en bok uten config.json, en ordre
                       uten gender. Den kjoeres ikke om automatisk og blir
                       ikke bedre av aa vente. Noen maa rette aarsaken.
      permanent=False  systemfeil. Den kan vaere lagt tilbake paa koen og
                       forsoekt paa nytt, eller gitt opp etter tre forsoek.

    I PREVIEW-modus gjoer den ÉN ting til foerst: skriver `failed` i
    jobbens statusfil. Uten det ville frontenden staatt og pollet en
    `processing` som aldri ble noe, og kunden sett en spinner for alltid -
    samme stillhet som ordre 1517, bare foran en betalende kunde i stedet
    for bak en operatoer.
    """
    _report_preview_failure(job_key, error, log)
    child = job.get("child_name") or "?"
    book = job.get("book_slug") or "?"
    # Ordet betyr noe: i PREVIEW-modus finnes det ingen ordre og ingen
    # betaling, og en operatoer som leser "ORDREN ER STOPPET" ville begynt
    # aa lete etter en kunde som venter paa en bok.
    what = "FORHAANDSVISNINGEN" if _is_preview() else "ORDREN"
    head = (f"{what} ER STOPPET og starter ikke av seg selv."
            if permanent else f"{what.capitalize()} feilet.")
    lines = [
        f"❌ {head}",
        "",
        f"Jobb:   {job_key}",
        f"Barn:   {child}",
        f"Bok:    {book}",
        f"Steg:   {step or '?'}",
        f"Feil:   {kind}",
        "",
        str(error),
        "",
    ]
    if permanent:
        lines += [
            "Dette er jobbens egen feil. Den legges IKKE tilbake paa koen -",
            "en omkjoering ville gitt samme feil i evig loekke.",
            "Rett aarsaken, og be om ny kjoering:",
            f"  POST /api/jobs/{job_key}/retry",
        ]
    else:
        lines += [
            "Systemfeil. Se om den kom tilbake av seg selv:",
            f"  python flow\worker\cli.py status --job-key {job_key}",
        ]
    return send("\n".join(lines), log=log)


def watchdog_failed(failed: list[str], started: list[str] | None = None) -> dict:
    """Vaktmesteren fikk ikke en tjeneste opp igjen.

    `dreampage.ps1 ensure` kjoerer hvert 5. minutt og restarter det som er
    nede. Naar den IKKE klarer det, skrev den fram til 16.09.2026 en linje i
    state/watchdog.log og returnerte exit 1 til Task Scheduler - to steder
    ingen ser paa. En ComfyUI som ikke lar seg starte var dermed usynlig helt
    til ordrene hadde hopet seg opp i RabbitMQ.
    """
    lines = ["⚠️ Vaktmesteren fikk ikke alt opp igjen.", ""]
    lines.append("Nede:   " + ", ".join(failed))
    if started:
        lines.append("Startet: " + ", ".join(started))
    lines += [
        "",
        "Ordre som kommer inn naa blir staaende i RabbitMQ-koen.",
        "Sjekk:  .\dreampage.ps1 status",
        "Logg:   state\watchdog.log",
    ]
    return send("\n".join(lines))


if __name__ == "__main__":
    # Kalles fra dreampage.ps1 (PowerShell har ingen grunn til aa kunne
    # Telegram-protokollen):
    #   python flow\worker\notify.py watchdog "ComfyUI,flow" "bot"
    #   python flow\worker\notify.py send "fri tekst"
    import sys as _sys
    _args = _sys.argv[1:]
    if not _args:
        raise SystemExit("bruk: notify.py send <tekst> | watchdog <nede> [startet] | flush")
    if _args[0] == "flush":
        # Vaktmesteren, hvert 5. minutt. Exit 0 ogsaa naar noe venter: det er
        # ikke vaktmesterens feil at nettet er nede.
        print(json.dumps(flush(), ensure_ascii=False))
        raise SystemExit(0)
    if _args[0] == "watchdog":
        _failed = [x for x in (_args[1] if len(_args) > 1 else "").split(",") if x]
        _started = [x for x in (_args[2] if len(_args) > 2 else "").split(",") if x]
        _res = watchdog_failed(_failed, _started)
    else:
        _res = send(" ".join(_args[1:]) if _args[0] == "send" else " ".join(_args))
    print(json.dumps(_res, ensure_ascii=False))
    raise SystemExit(0 if _res.get("sent") else 1)

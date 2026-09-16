# -*- coding: utf-8 -*-
"""ComfyUI-klienten: send prompt, poll, verifiser at filen finnes paa disk.

Portert fra nodene "HTTP Request ComfyUI", "Init Poll", "Get History",
"Parse History", "Inc Tries", "If Timed Out", "Poll Wait", "Check Page Output".

Tre ting er bevisst beholdt fra n8n, fordi de er dyrekjoept:

  1. DISK SLAAR HISTORY. Finnes filen paa disk, er siden ferdig - uansett hva
     /history sier. Det er dette som gjoer at ComfyUI kan startes paa nytt
     midt i en ordre: history-en forsvinner med prosessen, filen gjoer ikke.
  2. KUN ORDRENS EGEN MAPPE. Sidenoeklene (page00..page15) er like i alle
     boeker. Da to samtidige ordre 14.09.2026 fikk se i hverandres
     output-mapper, hoppet de over hverandres sider - bildene var ikke feil,
     de var borte. Denne modulen faar én mappe og kan ikke se andre steder.
  3. /prompt-timeout paa 180 s. ComfyUI kan bruke naer tre minutter under
     minnepress; en side gikk fra 69 s til 178 s da lokal RAM-bruk sultet ut
     event-loopen.

Det som er NYTT: én prosess med intern koe betyr at serialiseringen er en
egenskap ved konstruksjonen. Derfor finnes det ingen laasefil her, og ingen
acquire/release/TTL/stale/token/eierskap - de ~200 linjene vrien JS over fire
noder som to produksjonsinsidenter laa i.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as flow_config  # noqa: E402

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


class ComfyError(Exception):
    """ComfyUI svarte ikke, eller svarte noe uforstaaelig. Kan retries."""


class PageFailed(Exception):
    """ComfyUI kjoerte prompten og den feilet. Skal IKKE retries blindt."""


@dataclass
class PageResult:
    page_key: str
    path: Path | None = None
    prompt_id: str = ""
    seconds: float = 0.0
    # "already-on-disk" naar siden laa der fra foer, "rendered" naar vi laget
    # den, "resumed" naar filen dukket opp mens vi pollet en history som var
    # borte (ComfyUI restartet).
    source: str = ""
    tries: int = 0
    history_errors: int = 0
    notes: list[str] = field(default_factory=list)


def _request(url: str, payload: dict | None, timeout: float) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        # n8n satte Connection: close. ComfyUI sin aiohttp-server holder
        # ellers keep-alive-sockets aapne gjennom en hel ordre.
        "Connection": "close",
    }, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            body = res.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1500]
        raise ComfyError(f"ComfyUI {url} HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ComfyError(f"ComfyUI {url} svarte ikke: {exc}") from exc
    if not body.strip():
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ComfyError(f"ComfyUI {url} ga ugyldig JSON: {exc} body={body[:500]}") from exc


class Comfy:
    def __init__(self, conf: dict | None = None):
        self.conf = conf or flow_config.comfy()
        self.url = self.conf["url"].rstrip("/")

    # -- helse ------------------------------------------------------------
    def alive(self) -> bool:
        try:
            self.system_stats()
            return True
        except ComfyError:
            return False

    def system_stats(self) -> dict:
        return _request(f"{self.url}/system_stats", None, 10)

    def identity(self) -> dict:
        """ER dette vaar ComfyUI, eller bare EN ComfyUI?

        At noe svarer paa 8188 beviser ingenting. 16.09.2026 svarte en ComfyUI
        startet fra den GAMLE C:\ComfyUI paa porten, elevert og uten
        mappe-flaggene. Den saa NULL modeller, saa hver eneste bokside ville
        feilet med "unet_name not in []" - og helsesjekken sa "ok", fordi den
        bare spurte om noe svarte.

        Her sjekkes hvem det er: kjoerer den main.py fra DreamPage-image, og
        finner den modellene boekene trenger?
        """
        stats = self.system_stats()
        argv = [str(a) for a in (stats.get("system", {}).get("argv") or [])]
        joined = " ".join(argv).replace("\\", "/")
        from paths import IMAGE
        expected = str(IMAGE).replace("\\", "/")
        out = {
            "argv": argv,
            "from_image": expected.lower() in joined.lower(),
            "version": stats.get("system", {}).get("comfyui_version"),
        }
        # Modellene er den andre halvdelen: en instans kan godt kjoere fra
        # riktig sted og likevel mangle --extra-model-paths-config.
        try:
            info = _request(f"{self.url}/object_info/UNETLoader", None, 30)
            names = (info.get("UNETLoader", {}).get("input", {})
                     .get("required", {}).get("unet_name") or [[]])[0]
            out["unet_models"] = len(names)
        except ComfyError:
            out["unet_models"] = None
        out["ok"] = bool(out["from_image"]) and bool(out.get("unet_models"))
        return out

    def queue(self) -> dict:
        return _request(f"{self.url}/queue", None, 10)

    def queue_depth(self) -> int:
        q = self.queue()
        return len(q.get("queue_running") or []) + len(q.get("queue_pending") or [])

    # -- sidefiler paa disk ----------------------------------------------
    @staticmethod
    def existing_page(output_dir: Path, page_key: str) -> Path | None:
        """Nyeste ikke-tomme sidefil i DENNE mappa, eller None.

        `page_key + "_"` er prefikset ComfyUI lager: page04 -> page04_00001_.png.
        Understreken er viktig - uten den ville "page1" truffet "page10".
        """
        if not page_key or not output_dir.is_dir():
            return None
        best: tuple[float, Path] | None = None
        try:
            entries = list(output_dir.iterdir())
        except OSError:
            return None
        for entry in entries:
            if not entry.name.startswith(page_key + "_"):
                continue
            if entry.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            try:
                st = entry.stat()
            except OSError:
                continue
            if not entry.is_file() or st.st_size <= 0:
                continue
            if best is None or st.st_mtime > best[0]:
                best = (st.st_mtime, entry)
        return best[1] if best else None

    # -- kjoer én side ----------------------------------------------------
    def submit(self, prompt: dict) -> str:
        res = _request(f"{self.url}/prompt", {"prompt": prompt},
                       self.conf["prompt_timeout_s"])
        prompt_id = res.get("prompt_id") or res.get("promptId") or ""
        if not prompt_id:
            raise ComfyError("ComfyUI /prompt svarte uten prompt_id: "
                             + json.dumps(res)[:1000])
        return str(prompt_id)

    def history(self, prompt_id: str) -> dict:
        return _request(f"{self.url}/history/{urllib.parse.quote(prompt_id)}",
                        None, self.conf["history_timeout_s"])

    @staticmethod
    def _parse_history(body: dict, prompt_id: str) -> tuple[bool, bool, dict]:
        """(ferdig, feilet, feildetaljer) - fra "Parse History"-noden.

        Ferdig = status sier completed/success ELLER det finnes bilder i
        outputs. n8n stolte paa begge, fordi ComfyUI har hatt versjoner der
        status-feltet aldri ble satt.
        """
        entry = body.get(prompt_id) or (next(iter(body.values()), {}) if body else {})
        if not isinstance(entry, dict):
            return False, False, {}

        images: list = []
        outputs = entry.get("outputs") or entry.get("output") or {}
        if isinstance(outputs, dict):
            for value in outputs.values():
                if isinstance(value, dict) and isinstance(value.get("images"), list):
                    images += value["images"]
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict) and isinstance(item.get("images"), list):
                            images += item["images"]
                        elif isinstance(item, dict) and (
                                item.get("type") == "image" or item.get("filename")):
                            images.append(item)

        status = entry.get("status") or {}
        status_str = status.get("status") or status.get("status_str") if isinstance(status, dict) else status
        done = (isinstance(status, dict) and status.get("completed") is True) \
            or status_str in ("completed", "success") or bool(images)

        errors = entry.get("node_errors") or entry.get("errors") or {}
        failed = any(bool(v) if not isinstance(v, list) else len(v) > 0
                     for v in (errors.values() if isinstance(errors, dict) else []))
        return bool(done), bool(failed), errors if failed else {}

    def render_page(self, prompt: dict, output_dir: Path, page_key: str,
                    on_progress=None) -> PageResult:
        """Bygg én side og returner filen. Idempotent.

        Finnes siden alt i DENNE mappa, gjoer vi ingenting. Det er ikke en
        optimalisering: en ordre kan komme flere ganger paa koen (ordre 1499
        kom tre ganger paa én dag), og da skal den bli én bok.
        """
        started = time.monotonic()
        result = PageResult(page_key=page_key)

        existing = self.existing_page(output_dir, page_key)
        if existing:
            result.path = existing
            result.source = "already-on-disk"
            result.seconds = time.monotonic() - started
            return result

        output_dir.mkdir(parents=True, exist_ok=True)
        result.prompt_id = self.submit(prompt)
        if on_progress:
            on_progress(result)

        interval = self.conf["poll_interval_s"]
        max_tries = self.conf["poll_max_tries"]
        tolerance = self.conf["history_error_tolerance"]

        while result.tries < max_tries:
            # Disken foerst, HVER runde. Da overlever en ordre at ComfyUI
            # startes paa nytt: history-en er borte, men filen ligger der, og
            # jobben fortsetter i stedet for aa polle en promptId som ikke
            # finnes lenger.
            found = self.existing_page(output_dir, page_key)
            if found:
                # Gi ComfyUI et oeyeblikk til aa lukke filen: /history kan si
                # completed noen millisekunder foer siste byte er skrevet.
                time.sleep(self.conf["disk_settle_s"])
                result.path = self.existing_page(output_dir, page_key) or found
                result.source = "rendered" if result.history_errors == 0 else "resumed"
                result.seconds = time.monotonic() - started
                return result

            try:
                body = self.history(result.prompt_id)
                result.history_errors = 0
            except ComfyError as exc:
                result.history_errors += 1
                if result.history_errors >= tolerance:
                    raise ComfyError(
                        f"{result.history_errors} /history-feil paa rad for "
                        f"{page_key}: {exc}") from exc
                time.sleep(min(interval, 60))
                result.tries += 1
                continue

            done, failed, errors = self._parse_history(body, result.prompt_id)
            if failed:
                raise PageFailed(f"ComfyUI feilet paa {page_key}: "
                                 + json.dumps(errors, ensure_ascii=False)[:1500])
            if done:
                time.sleep(self.conf["disk_settle_s"])
                found = self.existing_page(output_dir, page_key)
                if found:
                    result.path = found
                    result.source = "rendered"
                    result.seconds = time.monotonic() - started
                    return result
                # /history sier ferdig, men ingen fil. Det skjer hvis
                # filename_prefix peker et annet sted enn vi tror, og det er
                # verdt aa vite noeyaktig - ikke bare "timeout".
                raise PageFailed(
                    f"ComfyUI sier {page_key} er ferdig, men ingen fil i "
                    f"{output_dir}. Sjekk filename_prefix i workflowen.")

            time.sleep(min(interval, 60))
            result.tries += 1
            if on_progress and result.tries % 6 == 0:
                on_progress(result)

        raise ComfyError(f"{page_key} ble ikke ferdig innen "
                         f"{max_tries * interval} s ({max_tries} forsoek)")

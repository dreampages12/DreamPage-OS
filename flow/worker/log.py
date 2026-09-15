# -*- coding: utf-8 -*-
"""Strukturert logging, én fil per jobb i tillegg til fellesloggen.

`print` var godt nok saa lenge n8n eide historikken. Det gjoer den ikke lenger,
og naar en ordre feiler er den jobbens egen loggfil det eneste man vil se i -
ikke 40 MB fellslogg fra samtlige ordre.

Hver linje er JSON, saa loggen kan leses av API-et og av panelet uten aa
parses med regex:

    {"at": "...", "level": "INFO", "job": "1515", "step": "render_pages",
     "msg": "page04 ferdig", "seconds": 71.2}
"""
from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from paths import STATE  # noqa: E402

LOG_DIR = STATE / "log"
JOB_LOG_DIR = LOG_DIR / "jobs"
_lock = threading.Lock()
_LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}


def _stamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


class Log:
    """Logger for én jobb (eller for workeren selv, med job=None)."""

    def __init__(self, job_key: str | None = None, level: str = "INFO",
                 per_job_files: bool = True):
        self.job_key = job_key
        self.step: str | None = None
        self.min_level = _LEVELS.get(level.upper(), 20)
        self.per_job_files = per_job_files
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.main_path = LOG_DIR / "flow.log"
        self.job_path = None
        if job_key and per_job_files:
            JOB_LOG_DIR.mkdir(parents=True, exist_ok=True)
            # job_key kan inneholde bindestrek ("1411-b2") men aldri
            # separatorer, saa det er trygt som filnavn.
            self.job_path = JOB_LOG_DIR / f"{job_key}.log"

    def bind(self, step: str | None) -> "Log":
        self.step = step
        return self

    def _emit(self, level: str, msg: str, **fields) -> None:
        if _LEVELS.get(level, 20) < self.min_level:
            return
        record = {"at": _stamp(), "level": level}
        if self.job_key:
            record["job"] = self.job_key
        if self.step:
            record["step"] = self.step
        record["msg"] = msg
        record.update(fields)
        line = json.dumps(record, ensure_ascii=False, default=str)
        with _lock:
            for path in (self.main_path, self.job_path):
                if path is None:
                    continue
                try:
                    with open(path, "a", encoding="utf-8") as fh:
                        fh.write(line + "\n")
                except OSError:
                    # Loggingen skal aldri vaere det som stopper en ordre.
                    pass
            # stderr, ikke stdout: stdout er svarkanalen naar flow kalles fra
            # n8n som ett steg, og en loggelinje der ville oedelagt JSON-en.
            try:
                print(line, file=sys.stderr, flush=True)
            except (OSError, ValueError):
                pass

    def debug(self, msg: str, **f) -> None: self._emit("DEBUG", msg, **f)
    def info(self, msg: str, **f) -> None: self._emit("INFO", msg, **f)
    def warn(self, msg: str, **f) -> None: self._emit("WARN", msg, **f)
    def error(self, msg: str, **f) -> None: self._emit("ERROR", msg, **f)


def job_log_lines(job_key: str, limit: int = 400) -> list[dict]:
    """Siste linjer fra en jobbs egen logg, som dicts. Brukes av API-et naar
    panelet aapner et steg."""
    path = JOB_LOG_DIR / f"{job_key}.log"
    if not path.is_file():
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()[-limit:]
    except OSError:
        return []
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"msg": line})
    return out

# -*- coding: utf-8 -*-
"""Jobb-databasen: hvor stoppet ordre X, og hvorfor.

Dette erstatter n8n sin execution-historikk, som er det eneste ved n8n vi
ellers ville savnet. Den er uvurderlig naar en ordre feiler - og den er ogsaa
beviselig utilstrekkelig: ordre 1517 stoppet 2026-09-15 19:00 fordi
books/hestestjernen/config.json ikke finnes, og n8n skrev `status = success`.
Kunden venter fortsatt. Derfor har `jobs` her en status-enum der ingenting kan
vaere baade ferdig og mislykket, og hvert steg sin egen rad med feilteksten.

SQLite, WAL, én fil: state/jobs.sqlite. API-et (fase 4) leser SAMME database i
samme prosess - det finnes ikke to kopier av tilstanden.

Status-enum (fast, dashbordet leser den):
    pending    lagt paa koen, ikke startet
    running    holder paa naa
    done       ferdig
    failed     stoppet med feil
    cancelled  avbrutt av operatoer
"""
from __future__ import annotations

import json
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from paths import JOBS_DB  # noqa: E402

STATUSES = ("pending", "running", "done", "failed", "cancelled")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_key        TEXT PRIMARY KEY,
    woo_order_id   TEXT,
    book_slug      TEXT,
    child_name     TEXT,
    status         TEXT NOT NULL,
    step           TEXT,               -- steget den staar paa naa
    progress_done  INTEGER DEFAULT 0,  -- ferdige sider
    progress_total INTEGER DEFAULT 0,
    queued_at      TEXT NOT NULL,
    started_at     TEXT,
    finished_at    TEXT,
    error          TEXT,
    payload        TEXT,               -- hele jobb-payloaden, som JSON
    delivery_tag   INTEGER,            -- RabbitMQ, for ack
    redelivered    INTEGER DEFAULT 0,
    attempt        INTEGER DEFAULT 1,
    cancel_wanted  INTEGER DEFAULT 0,
    -- 1 = jobbens EGEN feil (bok uten config.json, ukjent gender). Skal
    -- aldri kjoeres om automatisk; en redelivery av den ville spunnet i
    -- evig loekke. Operatoeren maa rette aarsaken og be om retry.
    permanent      INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS jobs_status  ON jobs(status);
CREATE INDEX IF NOT EXISTS jobs_queued  ON jobs(queued_at);
CREATE INDEX IF NOT EXISTS jobs_woo     ON jobs(woo_order_id);

CREATE TABLE IF NOT EXISTS steps (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key     TEXT NOT NULL,
    name        TEXT NOT NULL,
    attempt     INTEGER NOT NULL DEFAULT 1,
    status      TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT,
    seconds     REAL,
    error       TEXT,
    detail      TEXT                   -- JSON: sider, promptId, filstier
);
CREATE INDEX IF NOT EXISTS steps_job ON steps(job_key, id);

CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    at        TEXT NOT NULL,
    job_key   TEXT,
    kind      TEXT NOT NULL,
    message   TEXT,
    detail    TEXT
);
CREATE INDEX IF NOT EXISTS events_at ON events(id);

-- Alt som ENDRER noe skal logges med hvem og naar. POST-endepunktene i
-- API-et skriver hit; det er forskjellen paa en retry en operatoer ba om og
-- en retry systemet tok selv.
CREATE TABLE IF NOT EXISTS actions (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    at       TEXT NOT NULL,
    who      TEXT,
    action   TEXT NOT NULL,
    job_key  TEXT,
    detail   TEXT
);
"""


def now() -> str:
    """ISO-8601 med UTC-offset. Dashbordet leser dette, saa det skal aldri
    vaere en naken lokaltid uten sone."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class JobStore:
    """Traadsikker tilgang til jobb-DB-en.

    Workeren skriver fra sin egen traad, API-et leser fra uvicorns traader.
    SQLite taaler det med WAL og én connection per traad.
    """

    def __init__(self, path: Path | None = None):
        self.path = Path(path or JOBS_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.Lock()
        with self._conn() as con:
            con.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        con = getattr(self._local, "con", None)
        if con is None:
            con = sqlite3.connect(self.path, timeout=30,
                                  detect_types=0, isolation_level=None)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=NORMAL")
            con.execute("PRAGMA busy_timeout=30000")
            self._local.con = con
        return con

    # -- skriving ---------------------------------------------------------
    def _write(self, sql: str, args: tuple = ()) -> None:
        with self._write_lock:
            self._conn().execute(sql, args)

    def enqueue(self, job_key: str, payload: dict, delivery_tag: int | None = None,
                redelivered: bool = False, max_attempts: int = 3) -> bool:
        """Legg en jobb inn som pending. Returnerer False hvis den fins fra foer.

        Samme ordre kan leveres flere ganger fra koen - ordre 1499 kom tre
        ganger paa én dag. Primaernoekkelen er job_key, saa en redelivery
        oppdaterer den samme raden i stedet for aa lage en ny bok.
        """
        with self._write_lock:
            con = self._conn()
            row = con.execute("SELECT status, attempt, permanent FROM jobs WHERE job_key=?",
                              (job_key,)).fetchone()
            if row is None:
                con.execute(
                    "INSERT INTO jobs (job_key, woo_order_id, book_slug, child_name,"
                    " status, queued_at, payload, delivery_tag, redelivered)"
                    " VALUES (?,?,?,?,'pending',?,?,?,?)",
                    (job_key, str(payload.get("order_id") or ""),
                     str(payload.get("book_slug") or ""),
                     str(payload.get("child_name") or ""),
                     now(), json.dumps(payload, ensure_ascii=False),
                     delivery_tag, 1 if redelivered else 0))
                return True
            # Jobben finnes fra foer.
            con.execute("UPDATE jobs SET delivery_tag=?, redelivered=? WHERE job_key=?",
                        (delivery_tag, 1 if redelivered else 0, job_key))
            if row["status"] not in ("failed",):
                # done, running, pending, cancelled: ikke kjoer paa nytt.
                return False
            if row["permanent"]:
                # Jobbens egen feil. Aa kjoere den paa nytt automatisk gir
                # noeyaktig samme feil, og fordi en mislykket jobb legges
                # tilbake paa koen ville det blitt en evig loekke - det er
                # slik en poison message spiser en koe.
                return False
            if int(row["attempt"] or 1) >= max_attempts:
                return False
            con.execute("UPDATE jobs SET status='pending', error=NULL,"
                        " attempt=attempt+1, finished_at=NULL, permanent=0"
                        " WHERE job_key=?", (job_key,))
            return True

    def start(self, job_key: str, total_pages: int = 0) -> None:
        """Marker jobben som running.

        `cancel_wanted` nullstilles bevisst IKKE her. En operatoer som trykker
        avbryt mens jobben ligger i koeen og venter, ville ellers mistet
        avbruddet i det oeyeblikket arbeidstraaden plukket den opp - og sett en
        jobb starte rett etter at de ba den stoppe. Flagget ryddes i retry(),
        som er der noen faktisk ber om en ny kjoering.
        """
        self._write("UPDATE jobs SET status='running', started_at=?, error=NULL,"
                    " progress_total=?, progress_done=0"
                    " WHERE job_key=?", (now(), total_pages, job_key))

    def set_step(self, job_key: str, step: str) -> None:
        self._write("UPDATE jobs SET step=? WHERE job_key=?", (step, job_key))

    def set_progress(self, job_key: str, done: int, total: int | None = None) -> None:
        if total is None:
            self._write("UPDATE jobs SET progress_done=? WHERE job_key=?",
                        (done, job_key))
        else:
            self._write("UPDATE jobs SET progress_done=?, progress_total=?"
                        " WHERE job_key=?", (done, total, job_key))

    def set_meta(self, job_key: str, **fields) -> None:
        allowed = {"book_slug", "child_name", "woo_order_id"}
        pairs = {k: v for k, v in fields.items() if k in allowed}
        if not pairs:
            return
        sql = ", ".join(f"{k}=?" for k in pairs)
        self._write(f"UPDATE jobs SET {sql} WHERE job_key=?",
                    (*pairs.values(), job_key))

    def finish(self, job_key: str, status: str, error: str | None = None,
               permanent: bool = False) -> None:
        """`permanent=True` betyr jobbens egen feil: ikke proev igjen av seg
        selv. Se kommentaren paa kolonnen."""
        if status not in STATUSES:
            raise ValueError(f"ukjent status {status!r}")
        self._write("UPDATE jobs SET status=?, finished_at=?, error=?, step=NULL,"
                    " permanent=? WHERE job_key=?",
                    (status, now(), error, 1 if permanent else 0, job_key))

    def retry(self, job_key: str) -> bool:
        """Operatoeren ber om ny kjoering. Nullstiller ogsaa `permanent`.

        Dette er det ENESTE som gjenoppliver en jobb som feilet paa sin egen
        feil - som ordre 1517, der boka manglet config.json. Da er det noen
        som faktisk har rettet aarsaken.
        """
        row = self._conn().execute("SELECT status FROM jobs WHERE job_key=?",
                                   (job_key,)).fetchone()
        if row is None or row["status"] == "running":
            return False
        self._write("UPDATE jobs SET status='pending', error=NULL, permanent=0,"
                    " attempt=attempt+1, finished_at=NULL, cancel_wanted=0"
                    " WHERE job_key=?", (job_key,))
        return True

    def request_cancel(self, job_key: str) -> None:
        self._write("UPDATE jobs SET cancel_wanted=1 WHERE job_key=?", (job_key,))

    def cancel_wanted(self, job_key: str) -> bool:
        row = self._conn().execute("SELECT cancel_wanted FROM jobs WHERE job_key=?",
                                   (job_key,)).fetchone()
        return bool(row and row["cancel_wanted"])

    # -- steg -------------------------------------------------------------
    def step_started(self, job_key: str, name: str, attempt: int = 1) -> int:
        with self._write_lock:
            cur = self._conn().execute(
                "INSERT INTO steps (job_key, name, attempt, status, started_at)"
                " VALUES (?,?,?,'running',?)", (job_key, name, attempt, now()))
            return int(cur.lastrowid)

    def step_finished(self, step_id: int, status: str, seconds: float,
                      error: str | None = None, detail: dict | None = None) -> None:
        self._write("UPDATE steps SET status=?, finished_at=?, seconds=?, error=?,"
                    " detail=? WHERE id=?",
                    (status, now(), round(seconds, 3), error,
                     json.dumps(detail, ensure_ascii=False) if detail else None,
                     step_id))

    # -- hendelser og handlinger -----------------------------------------
    def event(self, kind: str, message: str = "", job_key: str | None = None,
              detail: dict | None = None) -> None:
        self._write("INSERT INTO events (at, job_key, kind, message, detail)"
                    " VALUES (?,?,?,?,?)",
                    (now(), job_key, kind, message,
                     json.dumps(detail, ensure_ascii=False) if detail else None))

    def action(self, who: str, action: str, job_key: str | None = None,
               detail: dict | None = None) -> None:
        self._write("INSERT INTO actions (at, who, action, job_key, detail)"
                    " VALUES (?,?,?,?,?)",
                    (now(), who, action, job_key,
                     json.dumps(detail, ensure_ascii=False) if detail else None))

    # -- lesing -----------------------------------------------------------
    def job(self, job_key: str) -> dict | None:
        row = self._conn().execute("SELECT * FROM jobs WHERE job_key=?",
                                   (job_key,)).fetchone()
        if row is None:
            return None
        out = dict(row)
        out["payload"] = json.loads(out["payload"]) if out["payload"] else {}
        out["steps"] = self.steps(job_key)
        return out

    def steps(self, job_key: str) -> list[dict]:
        rows = self._conn().execute(
            "SELECT * FROM steps WHERE job_key=? ORDER BY id", (job_key,)).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["detail"] = json.loads(item["detail"]) if item["detail"] else None
            out.append(item)
        return out

    def list_jobs(self, status: str | None = None, limit: int = 50,
                  offset: int = 0) -> list[dict]:
        sql = ("SELECT job_key, woo_order_id, book_slug, child_name, status, step,"
               " progress_done, progress_total, queued_at, started_at, finished_at,"
               " error, attempt FROM jobs")
        args: list = []
        if status:
            sql += " WHERE status=?"
            args.append(status)
        # Nyeste foerst. queued_at er ISO med sone, saa tekstsortering er
        # kronologisk saa lenge sonen er den samme - og den er lokal her.
        sql += " ORDER BY queued_at DESC, rowid DESC LIMIT ? OFFSET ?"
        args += [limit, offset]
        return [dict(r) for r in self._conn().execute(sql, args).fetchall()]

    def count_by_status(self) -> dict:
        rows = self._conn().execute(
            "SELECT status, COUNT(*) n FROM jobs GROUP BY status").fetchall()
        out = {s: 0 for s in STATUSES}
        out.update({r["status"]: r["n"] for r in rows})
        return out

    def pending(self) -> list[dict]:
        return self.list_jobs(status="pending", limit=500)

    def running(self) -> dict | None:
        rows = self.list_jobs(status="running", limit=1)
        return rows[0] if rows else None

    def events_since(self, after_id: int = 0, limit: int = 200) -> list[dict]:
        rows = self._conn().execute(
            "SELECT * FROM events WHERE id > ? ORDER BY id LIMIT ?",
            (after_id, limit)).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["detail"] = json.loads(item["detail"]) if item["detail"] else None
            out.append(item)
        return out

    # -- opprydding -------------------------------------------------------
    def reset_stale_running(self) -> list[str]:
        """Jobber som stod som `running` da prosessen doede.

        Kalles ved oppstart. En jobb som laa i `running` har ingen som kjoerer
        den lenger, saa den settes til pending og plukkes opp igjen - i
        motsetning til dagens doede laasefil, som blokkerte en uskyldig ordre
        i 50 minutter 15.09.2026 uten at noen kunne se hvorfor.
        """
        rows = self._conn().execute(
            "SELECT job_key FROM jobs WHERE status='running'").fetchall()
        keys = [r["job_key"] for r in rows]
        for key in keys:
            self._write("UPDATE jobs SET status='pending', step=NULL,"
                        " attempt=attempt+1 WHERE job_key=?", (key,))
            self.event("resume", "stod som running da workeren startet - "
                                 "satt tilbake til pending", key)
        return keys


_store: JobStore | None = None


def store() -> JobStore:
    global _store
    if _store is None:
        _store = JobStore()
    return _store

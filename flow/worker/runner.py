# -*- coding: utf-8 -*-
"""Den interne koeen: én jobb om gangen, én side om gangen.

Dette er grunnen til at flow finnes. n8n kjoerte executions parallelt uten
delt minne, ComfyUI taaler én jobb, og forskjellen ble haandtert av
`.dreampage-comfy.lock` med acquire/release/TTL/stale/token/eierskap - ~200
linjer JS spredt over fire noder. To produksjonsinsidenter paa to dager laa i
noeyaktig den mekanismen:

    14.09.2026  to samtidige ordre stjal hverandres ferdige sider
    15.09.2026  en doed laas blokkerte en uskyldig ordre i 50 minutter

Her finnes ingen laas. Det er én arbeidstraad som tar én jobb av en
`queue.Queue` om gangen. Serialiseringen er en egenskap ved konstruksjonen, og
kan derfor ikke feile uten at koden er endret.

To ordre paa koen samtidig kjoerer etter hverandre. Det er ikke noe som
haandheves - det er den eneste maaten dette kan oppfoere seg.
"""
from __future__ import annotations

import queue
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import comfy as comfy_mod  # noqa: E402
import config as flow_config  # noqa: E402
import jobs as jobs_mod  # noqa: E402
import notify  # noqa: E402
import pipeline as pipeline_mod  # noqa: E402
from books import JobError  # noqa: E402
from log import Log  # noqa: E402
from steps import Context  # noqa: E402


@dataclass
class QueuedJob:
    job_key: str
    payload: dict
    # Kalles naar jobben har naadd et varig sjekkpunkt, og igjen naar den er
    # ferdig. RabbitMQ-konsumenten bruker dem til aa acke.
    #   on_checkpoint(job_key)
    #   on_finished(job_key, checkpoint_reached, permanent)
    on_checkpoint: object = None
    on_finished: object = None
    # Navnet paa en pipeline fra pipeline.PIPELINES, eller None for den
    # aktive. Finnes for aa kunne kjoere ÉN ordre gjennom "full" uten aa
    # flippe pipeline.ACTIVE for alle framtidige ordre - fase 5 maa kunne
    # proeves paa en ekte ordre foer den blir standard.
    pipeline: str | None = None


class Runner:
    """Arbeidstraaden. Eier ComfyUI-tilgangen alene."""

    def __init__(self, store: jobs_mod.JobStore | None = None):
        self.store = store or jobs_mod.store()
        self.queue: "queue.Queue[QueuedJob | None]" = queue.Queue()
        self.comfy = comfy_mod.Comfy()
        self.log = Log(None, flow_config.load()["log"]["level"])
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        # Hva som kjoerer naa. API-et leser den for /api/queue.
        self.current: str | None = None
        self.current_step: str | None = None
        self.started_at: float | None = None

    # -- livssyklus -------------------------------------------------------
    def start(self) -> None:
        # En jobb som stod som `running` da prosessen doede har ingen som
        # kjoerer den. Den settes tilbake til pending og legges paa koen -
        # motsatt av den doede laasefila, som bare blokkerte.
        resumed = self.store.reset_stale_running()
        for key in resumed:
            job = self.store.job(key)
            if job:
                self.log.warn(f"gjenopptar {key} - stod som running ved oppstart")
                self.submit(QueuedJob(key, job["payload"]))
        for job in self.store.pending():
            row = self.store.job(job["job_key"])
            if row and row["job_key"] not in resumed:
                self.submit(QueuedJob(row["job_key"], row["payload"]))

        self._thread = threading.Thread(target=self._loop, name="dp-runner",
                                        daemon=True)
        self._thread.start()
        self.log.info("runner startet", gjenopptatt=len(resumed))

    def stop(self, timeout: float = 30) -> None:
        self._stop.set()
        self.queue.put(None)
        if self._thread:
            self._thread.join(timeout)

    def submit(self, job: QueuedJob) -> None:
        self.queue.put(job)

    def depth(self) -> int:
        return self.queue.qsize()

    # -- selve loekka -----------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                item = self.queue.get(timeout=1)
            except queue.Empty:
                continue
            if item is None:
                break
            try:
                chosen = (pipeline_mod.by_name(item.pipeline)
                          if getattr(item, "pipeline", None) else None)
                self.run_job(item, pipeline=chosen)
            except Exception:                       # noqa: BLE001
                # En feil her er en feil i runneren selv, ikke i jobben.
                # Traaden maa overleve den, ellers stopper hele koeen.
                self.log.error("runner-traaden fanget en uventet feil",
                               traceback=traceback.format_exc())
            except BaseException:                   # noqa: BLE001
                # BaseException, ikke bare Exception. SystemExit og
                # KeyboardInterrupt arver BaseException og gikk foer rett
                # gjennom alle tre except-lagene.
                #
                # 17.09.2026: gelato_api.verify_draft kastet SystemExit for
                # ordre 1532-b1. Traaden doede stille. Jobben stod som
                # "running" for alltid, 1537 og 1532-b2 laa fast i koeen, og
                # /api/status meldte worker_alive: false i 47 minutter uten at
                # noe varslet. Aarsaken er fikset i gelato_api (GelatoError),
                # men denne vakten staar fordi ETHVERT bibliotek kan kalle
                # sys.exit(): en arbeidstraad som kan drepes av en tredjeparts
                # feilhaandtering er ikke en holdbar konstruksjon.
                #
                # Vi svelger den IKKE - jobben markeres som feilet og
                # operatoeren varsles - men koeen faar leve.
                self.log.error("runner-traaden fanget en TRAADDREPENDE feil "
                               "(BaseException) - koeen lever videre",
                               traceback=traceback.format_exc())
                try:
                    key = getattr(item, "job_key", None)
                    if key and (self.store.job(key) or {}).get("status") == "running":
                        self.store.finish(key, "failed",
                                          "avbrutt av en traaddrepende feil "
                                          "i et steg - se loggen")
                        self._notify_failed(
                            key, self.store.job(key) or {},
                            "traaddrepende feil (BaseException) i et steg",
                            "BaseException", self.current_step, False, self.log)
                except Exception:                    # noqa: BLE001
                    pass
            finally:
                self.queue.task_done()

    def run_job(self, item: QueuedJob, pipeline=None) -> dict:
        """Kjoer én jobb gjennom pipelinen. Returnerer sluttilstanden."""
        steps_list = pipeline or pipeline_mod.active()
        job_key = item.job_key
        conf = flow_config.load()
        log = Log(job_key, conf["log"]["level"], conf["log"]["per_job_files"])

        self.current = job_key
        self.started_at = time.monotonic()
        self.store.start(job_key)
        self.store.event("start", "jobben starter", job_key)
        log.info("jobb startet", payload_keys=sorted(item.payload))

        ctx = Context(job_key=job_key, payload=item.payload, log=log,
                      store=self.store, comfy=self.comfy,
                      cancelled=lambda: self.store.cancel_wanted(job_key))

        checkpoint_reached = False
        permanent = False
        try:
            for step in steps_list:
                settings = step.settings()
                if not settings["enabled"]:
                    log.warn(f"{step.name}: avskrudd i config, hopper over")
                    self.store.event("step-skipped", step.name, job_key)
                    continue

                if self.store.cancel_wanted(job_key):
                    raise JobError(f"avbrutt av operatoer foer {step.name}")

                self.current_step = step.name
                self.store.set_step(job_key, step.name)
                self._run_step(ctx, step, settings, log)

                if step.checkpoint:
                    checkpoint_reached = True
                    if item.on_checkpoint:
                        # Ack-en er det som gjoer en redelivery kjedelig i
                        # stedet for farlig. Den skjer FOERST naar arbeidet er
                        # varig lagret.
                        try:
                            item.on_checkpoint(job_key)
                        except Exception as exc:     # noqa: BLE001
                            log.warn(f"sjekkpunkt-callback feilet: {exc}")

            self.store.finish(job_key, "done")
            self.store.event("done", "jobben er ferdig", job_key)
            log.info("jobb ferdig",
                     sekunder=round(time.monotonic() - self.started_at, 1))
            result = {"status": "done", "job_key": job_key}

        except JobError as exc:
            # Jobbens egen feil. Ingen retry - en bok uten config.json blir
            # ikke bedre av aa proeves ti ganger.
            # permanent=True: en bok uten config.json blir ikke bedre av aa
            # proeves igjen, og fordi en mislykket jobb legges tilbake paa
            # RabbitMQ-koen ville en automatisk omkjoering blitt en evig
            # loekke. Den staar synlig som failed til noen retter aarsaken.
            self.store.finish(job_key, "failed", str(exc), permanent=True)
            self.store.event("failed", str(exc), job_key, {"kind": "JobError",
                                                           "permanent": True})
            log.error("jobben feilet", feil=str(exc), kind="JobError")
            permanent = True
            # Si fra. Uten dette blir en betalt ordre liggende som `failed` i
            # SQLite til noen tilfeldigvis aapner panelet - se notify.py.
            self._notify_failed(job_key, str(exc), "JobError", True, log)
            result = {"status": "failed", "job_key": job_key, "error": str(exc),
                      "kind": "JobError", "permanent": True}

        except Exception as exc:                     # noqa: BLE001
            self.store.finish(job_key, "failed", str(exc))
            self.store.event("failed", str(exc), job_key,
                             {"kind": type(exc).__name__,
                              "traceback": traceback.format_exc()[-4000:]})
            log.error("jobben feilet", feil=str(exc), kind=type(exc).__name__,
                      traceback=traceback.format_exc()[-4000:])
            self._notify_failed(job_key, str(exc), type(exc).__name__,
                                False, log)
            result = {"status": "failed", "job_key": job_key, "error": str(exc),
                      "kind": type(exc).__name__}

        except BaseException as exc:                 # noqa: BLE001
            # SystemExit og KeyboardInterrupt arver BaseException og gikk foer
            # rett gjennom except-en over. 17.09.2026 kastet gelato_api
            # SystemExit for ordre 1532-b1: jobben stod som "running" for
            # alltid, to andre ordre laa fast i koeen, og worker_alive ble
            # false i 47 minutter uten at noe varslet.
            #
            # Jobben MAA markeres feilet her, i koden som eier jobbstatusen -
            # ellers ser den ut som en evig kjoerende ordre. Feilen logges og
            # varsles som alle andre, men den slippes IKKE videre.
            kind = type(exc).__name__
            self.store.finish(job_key, "failed", f"{kind}: {exc}")
            self.store.event("failed", f"{kind}: {exc}", job_key,
                             {"kind": kind, "thread_killing": True,
                              "traceback": traceback.format_exc()[-4000:]})
            log.error("jobben feilet paa en TRAADDREPENDE feil", feil=str(exc),
                      kind=kind, traceback=traceback.format_exc()[-4000:])
            self._notify_failed(job_key, f"{kind}: {exc}", kind, False, log)
            result = {"status": "failed", "job_key": job_key,
                      "error": f"{kind}: {exc}", "kind": kind}

        finally:
            self.current = None
            self.current_step = None
            self.started_at = None
            if item.on_finished:
                try:
                    item.on_finished(job_key, checkpoint_reached, permanent)
                except Exception as exc:             # noqa: BLE001
                    log.warn(f"finished-callback feilet: {exc}")

        job = self.store.job(job_key) or {}
        result["steps"] = [{"name": s["name"], "status": s["status"],
                            "seconds": s["seconds"], "error": s["error"]}
                           for s in job.get("steps", [])]
        result["progress"] = {"done": job.get("progress_done"),
                              "total": job.get("progress_total")}
        return result

    def _notify_failed(self, job_key: str, error: str, kind: str,
                       permanent: bool, log: Log) -> None:
        """Varsle om en feilet jobb - og aldri la varslingen bli feilen.

        notify.send fanger selv URLError og OSError, men den leser ogsaa
        config/secrets.json og bygger JSON. Kaster noe av det, ville unntaket
        propagert ut av except-grenen i run_job: jobben returnerer aldri, og
        `on_finished` sin ack/nack til RabbitMQ forsvinner. Da ville et
        varsel som ikke kom fram ha blitt en melding som ble liggende
        uacket - altsaa et stoerre problem enn det vi proevde aa loese.
        """
        try:
            notify.job_failed(job_key, self.store.job(job_key) or {}, error,
                              kind, self.current_step, permanent, log)
        except Exception as exc:                     # noqa: BLE001
            log.warn(f"kunne ikke varsle om feilet jobb: {exc}")

    def _run_step(self, ctx: Context, step, settings: dict, log: Log) -> None:
        """Ett steg, med retry. Kaster videre naar forsoekene er brukt opp."""
        attempts = settings["retries"] + 1
        last: Exception | None = None

        for attempt in range(1, attempts + 1):
            step_id = self.store.step_started(ctx.job_key, step.name, attempt)
            started = time.monotonic()
            log.bind(step.name)
            try:
                detail = step.run(ctx) or {}
                seconds = time.monotonic() - started
                self.store.step_finished(step_id, "done", seconds, None, detail)
                log.info(f"{step.name} ok", seconds=round(seconds, 2), **{
                    k: v for k, v in detail.items()
                    if not isinstance(v, (list, dict))})
                return

            except JobError as exc:
                # Retries aldri, uansett hva config sier.
                seconds = time.monotonic() - started
                self.store.step_finished(step_id, "failed", seconds, str(exc))
                if step.optional:
                    log.warn(f"{step.name} feilet, men er valgfritt: {exc}")
                    return
                raise

            except Exception as exc:                 # noqa: BLE001
                seconds = time.monotonic() - started
                last = exc
                is_last = attempt >= attempts
                self.store.step_finished(
                    step_id, "failed" if is_last else "retry", seconds, str(exc),
                    {"traceback": traceback.format_exc()[-2000:]})
                log.warn(f"{step.name} feilet (forsoek {attempt}/{attempts}): {exc}")
                if not is_last:
                    # Voksende pause. Grunnverdien er per steg - se
                    # Step.retry_delay_s: 5 s er riktig for ComfyUI paa samme
                    # maskin, men for kort for et steg som henter kundens
                    # bilde over internett.
                    base = settings.get("retry_delay_s", 5)
                    delay = min(base * attempt, base * 6)
                    log.info(f"venter {delay} s foer forsoek {attempt + 1}"
                             f"/{attempts}")
                    time.sleep(delay)

        if step.optional:
            log.warn(f"{step.name} feilet i alle {attempts} forsoek, men er "
                     f"valgfritt: {last}")
            return
        raise last if last else RuntimeError(f"{step.name} feilet uten unntak")

    # -- innsyn for API-et ------------------------------------------------
    def snapshot(self) -> dict:
        return {
            "running": self.current,
            "running_step": self.current_step,
            "running_seconds": (round(time.monotonic() - self.started_at, 1)
                                if self.started_at else None),
            "internal_queue_depth": self.depth(),
            "alive": bool(self._thread and self._thread.is_alive()),
        }

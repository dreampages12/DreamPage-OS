# -*- coding: utf-8 -*-
"""RabbitMQ-konsumenten: prefetch=1, manuell ack.

Erstatter "MQ Trigger" og "Release RabbitMQ Job". n8n-noden hadde riktignok
`acknowledge: laterMessageNode` og `parallelMessages: 1`, men ack-en laa langt
nede i grafen og ble hoppet over paa hver gren som ikke gikk helt fram. Samme
ordre kunne derfor leveres flere ganger - ordre 1499 kom tre ganger paa én dag
- og det ble haandtert av sidehopp-logikk i stedet for av ordentlig ack.

Her er regelen én setning: **meldingen ackes foerst naar jobben har naadd et
varig sjekkpunkt, og nack-es tilbake paa koen hvis den ikke naadde dit.**
Da er en redelivery kjedelig i stedet for farlig:

  * naadde den ikke sjekkpunktet -> ingenting varig er gjort, kjoer om
  * naadde den sjekkpunktet      -> hvert steg hopper over seg selv, og
                                    sidene ligger alt paa disk

Legitimasjonen ligger i config/secrets.json, ikke i n8n sin krypterte
credential-store. Det er en UTGAAENDE forbindelse over Tailscale og trenger
ingen eksponering.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as flow_config  # noqa: E402
import dp_secrets  # noqa: E402
import jobs as jobs_mod  # noqa: E402
from log import Log  # noqa: E402
from runner import QueuedJob  # noqa: E402


class Consumer:
    """Én konsument, én melding om gangen, manuell ack.

    Kjoerer i egen traad og leverer jobber til Runner sin interne koe. Ack og
    nack skjer fra pika-traaden via add_callback_threadsafe, fordi en
    pika-kanal ikke er traadsikker.
    """

    def __init__(self, runner, store: jobs_mod.JobStore | None = None):
        self.runner = runner
        self.store = store or jobs_mod.store()
        self.conf = flow_config.queue()
        self.log = Log(None, flow_config.load()["log"]["level"])
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._connection = None
        self._channel = None
        # job_key -> delivery_tag. Trengs fordi ack-en skjer i en annen traad
        # og lenge etter at meldingen ble mottatt.
        self._tags: dict[str, int] = {}
        self._tags_lock = threading.Lock()
        self.connected = False
        self.last_error: str | None = None

    # -- tilkobling -------------------------------------------------------
    @staticmethod
    def _params():
        import pika
        cred = dp_secrets.get("rabbitmq") or {}
        missing = [k for k in ("hostname", "username", "password") if not cred.get(k)]
        if missing:
            raise SystemExit(
                "config/secrets.json mangler rabbitmq." + ", rabbitmq.".join(missing))
        return pika.ConnectionParameters(
            host=cred["hostname"],
            port=int(cred.get("port") or 5672),
            virtual_host=cred.get("vhost") or "/",
            credentials=pika.PlainCredentials(cred["username"], cred["password"]),
            # Heartbeat maa vaere lengre enn en side tar. En ordre kan holde
            # kanalen i timer uten aa si noe, og en kort heartbeat ville
            # revet forbindelsen midt i en bok.
            heartbeat=int(flow_config.queue().get("heartbeat_s") or 600),
            blocked_connection_timeout=60,
            socket_timeout=15,
        )

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="dp-mq", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        conn = self._connection
        if conn is not None:
            try:
                conn.add_callback_threadsafe(conn.close)
            except Exception:                       # noqa: BLE001
                pass
        if self._thread:
            self._thread.join(15)

    def _loop(self) -> None:
        delay = int(self.conf.get("reconnect_delay_s") or 10)
        while not self._stop.is_set():
            try:
                self._consume()
            except Exception as exc:                # noqa: BLE001
                self.connected = False
                self.last_error = str(exc)
                self.log.error(f"RabbitMQ-forbindelsen falt: {exc}")
                self.store.event("mq-error", str(exc))
            if self._stop.is_set():
                break
            time.sleep(delay)

    def _consume(self) -> None:
        import pika
        self._connection = pika.BlockingConnection(self._params())
        self._channel = self._connection.channel()
        # Leveringstagger gjelder bare paa kanalen de kom paa. En ny kanal
        # teller fra 1 igjen, saa en gammel tagg acket her treffer en ANNEN
        # melding - eller lukker kanalen med PRECONDITION_FAILED. Meldinger
        # som ikke ble acket paa den gamle kanalen, leverer brokeren paa nytt,
        # og da faar de en ny tagg (eller ackes som duplikat).
        with self._tags_lock:
            self._tags.clear()
        queue_name = self.conf["name"]
        # passive: koen eies av WooCommerce-siden av oppsettet. Vi skal lese
        # den, ikke definere den - en feil `durable` her ville feilet med
        # PRECONDITION_FAILED og vaert vanskelig aa forstaa.
        self._channel.queue_declare(queue=queue_name, passive=True)
        self._channel.basic_qos(prefetch_count=int(self.conf.get("prefetch") or 1))
        self.connected = True
        self.last_error = None
        self.log.info("lytter paa koen", queue=queue_name,
                      prefetch=self.conf.get("prefetch"))
        self.store.event("mq-connected", f"lytter paa {queue_name}")

        for method, properties, body in self._channel.consume(
                queue_name, auto_ack=False, inactivity_timeout=5):
            if self._stop.is_set():
                break
            if method is None:                       # inactivity_timeout
                continue
            self._handle(method, body)

        self.connected = False
        try:
            self._channel.cancel()
            self._connection.close()
        except Exception:                            # noqa: BLE001
            pass

    # -- én melding -------------------------------------------------------
    def _handle(self, method, body: bytes) -> None:
        tag = method.delivery_tag
        try:
            payload = self._parse(body)
        except ValueError as exc:
            # En melding vi ikke kan lese blir aldri bedre av aa komme
            # tilbake. Den forkastes med en hendelse i loggen, ellers ville
            # den blokkert koen for alle andre.
            self.log.error(f"forkaster uleselig melding: {exc}")
            self.store.event("mq-bad-message", str(exc))
            self._ack(tag)
            return

        job_key = str(payload.get("job_key") or payload.get("order_id") or "").strip()
        if not job_key:
            self.log.error("melding uten job_key og order_id - forkastes")
            self.store.event("mq-bad-message", "mangler job_key/order_id")
            self._ack(tag)
            return

        fresh = self.store.enqueue(job_key, payload, delivery_tag=tag,
                                   redelivered=bool(method.redelivered))

        if not fresh:
            # Jobben er alt ferdig eller kjoerer. Ack med en gang: dette er
            # noeyaktig tilfellet som tidligere ble haandtert av sidehopp.
            state = (self.store.job(job_key) or {}).get("status")
            self.log.warn(f"{job_key} er alt {state} - ack uten aa kjoere paa nytt",
                          redelivered=bool(method.redelivered))
            self.store.event("duplicate", f"levert paa nytt, status={state}", job_key)
            self._ack(tag)
            return

        # Taggen huskes FOERST her, bare for en jobb som faktisk skal kjoere.
        # Foer 18.09.2026 ble den lagret ogsaa for duplikater, som ackes med
        # en gang ovenfor - og ble liggende. Duplikatet av 1536 (17.09 kl.
        # 11:38) sto i et doegn som `unacked: 1` i /api/status med en tom koe:
        # et varsel som alltid staar paa. Og den ville blitt acket en gang til
        # hvis 1536 noen gang kom fram til et sjekkpunkt fra RabbitMQ.
        with self._tags_lock:
            self._tags[job_key] = tag
        self.log.info(f"{job_key} lagt paa den interne koeen",
                      redelivered=bool(method.redelivered),
                      depth=self.runner.depth() + 1)
        self.runner.submit(QueuedJob(
            job_key=job_key,
            payload=payload,
            on_checkpoint=self._on_checkpoint,
            on_finished=self._on_finished,
        ))

    @staticmethod
    def _parse(body: bytes) -> dict:
        """Meldingen. n8n sin rabbitmqTrigger ga den som `content`-streng, og
        WooCommerce-siden publiserer JSON direkte - begge former godtas."""
        text = body.decode("utf-8", "replace").strip()
        if not text:
            raise ValueError("tom melding")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"ikke gyldig JSON: {exc}") from exc
        if isinstance(data, dict) and isinstance(data.get("content"), str):
            try:
                data = json.loads(data["content"])
            except json.JSONDecodeError as exc:
                raise ValueError(f"content var ikke gyldig JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"forventet et objekt, fikk {type(data).__name__}")
        return data

    # -- ack / nack -------------------------------------------------------
    def _pop_tag(self, job_key: str) -> int | None:
        with self._tags_lock:
            return self._tags.pop(job_key, None)

    def _ack(self, tag: int) -> None:
        conn, chan = self._connection, self._channel
        if conn is None or chan is None:
            return
        try:
            conn.add_callback_threadsafe(lambda: chan.basic_ack(tag))
        except Exception as exc:                     # noqa: BLE001
            # Mistet vi forbindelsen foer ack-en, kommer meldingen tilbake.
            # Det er den trygge retningen: jobben er idempotent.
            self.log.warn(f"kunne ikke acke {tag}: {exc}")

    def _nack(self, tag: int) -> None:
        conn, chan = self._connection, self._channel
        if conn is None or chan is None:
            return
        try:
            conn.add_callback_threadsafe(
                lambda: chan.basic_nack(tag, requeue=True))
        except Exception as exc:                     # noqa: BLE001
            self.log.warn(f"kunne ikke nacke {tag}: {exc}")

    def _on_checkpoint(self, job_key: str) -> None:
        """Jobben har naadd et varig sjekkpunkt - meldingen kan slippes."""
        tag = self._pop_tag(job_key)
        if tag is None:
            return
        self.log.info(f"{job_key}: sjekkpunkt naadd, acker meldingen")
        self.store.event("ack", "sjekkpunkt naadd", job_key)
        self._ack(tag)

    def _on_finished(self, job_key: str, checkpoint_reached: bool,
                     permanent: bool = False) -> None:
        """Jobben er over. Ack eller tilbake paa koen - og det er et valg med
        konsekvenser i begge retninger."""
        tag = self._pop_tag(job_key)
        if tag is None:
            return
        job = self.store.job(job_key) or {}
        status = job.get("status")

        if checkpoint_reached or status in ("done", "cancelled"):
            self._ack(tag)
            return

        if permanent:
            # Jobbens egen feil - en bok uten config.json, en ordre uten
            # gender. Aa legge den tilbake paa koen ville gitt noeyaktig samme
            # feil om og om igjen: det er slik en poison message spiser en
            # koe, og den ville blokkert alle andre ordre bak seg. Meldingen
            # ackes, og jobben staar som `failed` med feilteksten sin til noen
            # retter aarsaken og ber om retry.
            self.log.error(f"{job_key}: permanent feil - ackes og staar som "
                           f"failed. {job.get('error') or ''}")
            self.store.event("ack-permanent",
                             "jobbens egen feil, ikke lagt tilbake paa koen",
                             job_key, {"error": job.get("error")})
            self._ack(tag)
            return

        if int(job.get("attempt") or 1) >= 3:
            # Systemfeil, men vi har proevd nok. Samme resonnement som over:
            # bedre at én ordre staar synlig enn at koen staar stille.
            self.log.error(f"{job_key}: feilet {job.get('attempt')} ganger - "
                           f"ackes og staar som failed")
            self.store.event("ack-oppgitt", f"{job.get('attempt')} forsoek brukt",
                             job_key, {"error": job.get("error")})
            self._ack(tag)
            return

        # Systemfeil foer sjekkpunktet: ingenting varig er gjort. Tilbake paa
        # koen, og neste levering forsoeker paa nytt.
        self.log.warn(f"{job_key}: feilet foer sjekkpunkt - meldingen legges "
                      f"tilbake paa koen (forsoek {job.get('attempt')})")
        self.store.event("nack", "feilet foer sjekkpunkt", job_key)
        self._nack(tag)

    # -- innsyn -----------------------------------------------------------
    def snapshot(self) -> dict:
        return {
            "connected": self.connected,
            "queue": self.conf["name"],
            "prefetch": self.conf.get("prefetch"),
            "last_error": self.last_error,
            "unacked": len(self._tags),
        }

    def broker_depth(self) -> int | None:
        """Antall meldinger som venter hos brokeren. None hvis vi ikke naar den."""
        try:
            import pika
            con = pika.BlockingConnection(self._params())
            try:
                chan = con.channel()
                res = chan.queue_declare(queue=self.conf["name"], passive=True)
                return int(res.method.message_count)
            finally:
                con.close()
        except Exception:                            # noqa: BLE001
            return None

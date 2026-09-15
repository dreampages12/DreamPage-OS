# -*- coding: utf-8 -*-
"""Pipelinen som DATA: steg, rekkefoelge, retry, timeout, sjekkpunkt.

Oppdraget krever dette: logikken skal kunne versjoneres, diffes og testes, og
den skal kunne vises som bokser med piler i panelet uten at panelet vet noe om
hva et steg gjoer. Derfor er dette en liste, ikke en funksjon med if-er.

Et steg er:

    Step(name, run, retries, timeout_s, checkpoint, optional, description)

  retries      hvor mange EKSTRA forsoek ved systemfeil. JobError - altsaa
               jobbens egen feil, som en bok uten config.json - retries aldri.
  checkpoint   naar dette steget er ferdig, er arbeidet varig lagret og
               RabbitMQ-meldingen kan ackes. Dette er stedet "loes
               ack-semantikk" faktisk fikses: foer sjekkpunktet er en
               redelivery kjedelig (jobben gjoeres om), etter det er den
               gratis (alt er alt gjort, og hvert steg hopper over seg selv).
  optional     feiler steget, gaar ordren videre. Brukes paa sidespor som
               uttrykksvarianter: et manglende uttrykk skal ikke stoppe en
               betalt bok.

config/flow.json kan overstyre `enabled`, `retries` og `timeout_s` per steg -
det er den "enkle redigeringen" panelet skal tilby. Rekkefoelgen kan den IKKE
endre; den er kode, og en pipeline der stegene kan stokkes fritt er n8n paa
nytt.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as flow_config  # noqa: E402
import steps  # noqa: E402


@dataclass(frozen=True)
class Step:
    name: str
    run: Callable
    description: str = ""
    retries: int = 0
    timeout_s: int = 3600
    checkpoint: bool = False
    optional: bool = False

    def settings(self) -> dict:
        """Effektive verdier: standard fra koden, overstyrt av config."""
        override = flow_config.step(self.name)
        return {
            "enabled": bool(override.get("enabled", True)),
            "retries": int(override.get("retries", self.retries)),
            "timeout_s": int(override.get("timeout_s", self.timeout_s)),
        }


# ---------------------------------------------------------------------------
# FASE 2: fram til og med sidene.
#
# Etter `verify_pages` tar n8n over som foer, fra "Run Text Script". Det er
# hele poenget med fase 2: ett steg byttes ut, resten staar. Fase 5 forlenger
# denne listen nedover - rekkefoelgen der er allerede kjent fra de 82 nodene
# (tekst -> prepare -> PDF -> guard -> Drive -> Gelato -> Telegram -> confirm).
# ---------------------------------------------------------------------------
PAGES_PIPELINE: tuple[Step, ...] = (
    Step("validate_job", steps.validate_job,
         "Payload -> bok, spraak og sideliste. Avviser en ubyggbar bok med en "
         "gang i stedet for aa doe stille (ordre 1517).",
         retries=0, timeout_s=60),

    Step("persist_payload", steps.persist_payload,
         "Skriv state/orders/<job_key>.json. Uten denne forsvinner adresse, "
         "e-post og continue_code den dagen n8n er borte.",
         retries=2, timeout_s=60, checkpoint=True),

    Step("setup_dirs", steps.setup_dirs,
         "Lag input/, pdf/ og comfy-mappa for ordren.",
         retries=2, timeout_s=60),

    Step("fetch_child_image", steps.fetch_child_image,
         "Last ned barnebildet til input/<job_key>.jpg. Finnes det, roeres det "
         "ikke - operatoeren kan ha byttet det.",
         retries=3, timeout_s=300),

    Step("face_variants", steps.face_variants,
         "Uttrykksvarianter av barnebildet. Sidespor: en manglende variant "
         "faller tilbake paa originalen.",
         retries=0, timeout_s=900, optional=True),

    Step("render_pages", steps.render_pages,
         "Side-loekka. Én side om gangen mot ComfyUI, kun i ordrens egen "
         "output-mappe. Ingen laasefil - workeren er serialisert av "
         "konstruksjon.",
         # Ingen retry paa hele loekka: den er idempotent per side, saa en
         # omkjoering plukker opp der den stoppet. Retry hoerer inne i
         # comfy.render_page, der den kan gjelde én side.
         retries=0, timeout_s=14 * 3600, checkpoint=True),

    Step("verify_pages", steps.verify_pages,
         "Alle paakrevde sider ligger paa disk. Fanger den manglende siden HER "
         "i stedet for som 'Inner PDF page count ... got 14' fire steg senere.",
         retries=1, timeout_s=300),
)

PIPELINES: dict[str, tuple[Step, ...]] = {
    "pages": PAGES_PIPELINE,
}

ACTIVE = "pages"


def active() -> tuple[Step, ...]:
    return PIPELINES[ACTIVE]


def by_name(name: str) -> tuple[Step, ...]:
    if name not in PIPELINES:
        raise KeyError(f"ukjent pipeline {name!r}. Finnes: {', '.join(PIPELINES)}")
    return PIPELINES[name]


def describe(name: str | None = None) -> dict:
    """Pipelinen som JSON - grunnlaget for GET /api/workflows og for
    flow-visningen i panelet. Panelet tegner bokser og piler av dette og
    trenger ikke vite hva et steg gjoer."""
    key = name or ACTIVE
    return {
        "name": key,
        "active": key == ACTIVE,
        "steps": [
            {
                "name": s.name,
                "description": s.description,
                "checkpoint": s.checkpoint,
                "optional": s.optional,
                **s.settings(),
            }
            for s in by_name(key)
        ],
    }


def describe_all() -> list[dict]:
    return [describe(name) for name in PIPELINES]

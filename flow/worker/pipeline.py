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
import steps_post  # noqa: E402
import steps_preview  # noqa: E402


@dataclass(frozen=True)
class Step:
    name: str
    run: Callable
    description: str = ""
    retries: int = 0
    timeout_s: int = 3600
    checkpoint: bool = False
    optional: bool = False
    # Pausen mellom forsoekene er retry_delay_s * forsoeksnummer, begrenset
    # til 6x grunnverdien. 5 er riktig for et steg som snakker med ComfyUI paa
    # samme maskin: den restarter paa sekunder, og en ordre skal ikke staa i
    # ti minutter av den grunn.
    #
    # Tallet er DATA fordi ett tall ikke passer alle. fetch_child_image henter
    # kundens bilde over internett, og 17.09.2026 kl. 04:51 var TLS nede paa
    # denne maskinen i ca. to minutter. Med 5 sekunder brukte steget opp alle
    # fire forsoekene paa 30 sekunder og drepte BEGGE boekene i ordre 1532 -
    # en betalt tobok-ordre - mens feilen var over lenge foer noen saa den.
    retry_delay_s: int = 5

    def settings(self) -> dict:
        """Effektive verdier: standard fra koden, overstyrt av config."""
        override = flow_config.step(self.name)
        return {
            "enabled": bool(override.get("enabled", True)),
            "retries": int(override.get("retries", self.retries)),
            "timeout_s": int(override.get("timeout_s", self.timeout_s)),
            "retry_delay_s": int(override.get("retry_delay_s",
                                              self.retry_delay_s)),
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
    Step("check_assets", steps.check_assets,
         "All delt kunst og alle fonter finnes. Staar FOERST fordi bade "
         "line2-logoen (ordre 1510) og aapningssida (ordre 1506) er fail-soft "
         "nedover i kjeden: mangler de, blir boka bygget med feil bilde uten "
         "at noe sier fra.",
         retries=0, timeout_s=120),

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
         # 5 forsoek med 30 s grunnpause: 30+60+90+120 = 5 minutter foer vi
         # gir opp. Dette er det ENESTE steget som er avhengig av internett
         # midt i en ordre, og en forbigaaende nettverksfeil skal ikke drepe
         # en betalt bok. Ordre 1532 doede paa 30 sekunder 17.09.2026.
         retries=4, timeout_s=300, retry_delay_s=30),

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

    # Siste steg, og det som gjoer at "stopp etter sidene" er en
    # GJENNOMGANG og ikke en stillhet. Uten dette ble ordre staaende
    # "done" i DB-en mens kunden ventet - se docstringen i steget.
    Step("notify_pages_ready", steps.notify_pages_ready,
         "Si til operatoeren paa Telegram at sidene er klare. Optional: en "
         "ordre der varselet ikke kom fram er ikke en feilet ordre.",
         retries=2, timeout_s=60, optional=True),
)

# ---------------------------------------------------------------------------
# FASE 5: hele veien, uten n8n.
#
# Rekkefoelgen er hentet fra de faktiske koblingene i workflowen, ikke gjettet.
# Build Last Page (inne i build_pdfs) MAA komme foer tekstscriptet: den skriver
# input/blank-back.png, som tekstscriptet leser som siste innerside.
#
# Pipelinen stopper ved GELATO-UTKASTET. Godkjenningsloekka i n8n er doed kode
# - Confirm Gelato Order, Send Telegram Confirmation og Init Approval Poll har
# ingen inngaaende kobling - og dagens oppfoersel er at et menneske bestiller
# manuelt. Automatisk bekreftelse her ville sendt boeker til trykk uten at noen
# hadde sett dem.
# ---------------------------------------------------------------------------
FULL_PIPELINE: tuple[Step, ...] = PAGES_PIPELINE + (
    Step("claim_post_comfy", steps_post.claim_post_comfy,
         "Skriv .post_comfy_claim.json. Overfloedig naar koeen er serialisert, "
         "men boten leser den for aa finne en ordre.",
         retries=1, timeout_s=60),

    Step("wp_book_creating", steps_post.wp_book_creating,
         "Fortell WooCommerce at boka lages. Sidespor.",
         retries=1, timeout_s=60, optional=True),

    Step("build_pdfs", steps_post.build_pdfs,
         "Prepare -> fortsett-side -> tekstscript -> QR-stempel -> Gelato-PDF, "
         "med de strenge sidetall-guardene (33 samlet, 30/31 innersider).",
         retries=0, timeout_s=3600, checkpoint=True),

    Step("validate_gelato_files", steps_post.validate_gelato_files,
         "Filene finnes og har stoerrelse. Logger MB, saa en bok som vokser "
         "over 100 MB blir synlig foer den blir et mysterium.",
         retries=0, timeout_s=120),

    Step("upload_and_draft", steps_post.upload_and_draft,
         "Drive-opplasting + Gelato-UTKAST. Bekrefter ingenting.",
         retries=2, timeout_s=3600, checkpoint=True),

    Step("auto_merge_multibook", steps_post.auto_merge_multibook,
         "Flere boeker i samme ordre samles i ett utkast. Sidespor.",
         retries=0, timeout_s=1800, optional=True),

    Step("telegram_approval", steps_post.telegram_approval,
         "Varsle operatoeren om at utkastet er klart. Bestillingen gjoeres "
         "manuelt - det er dagens oppfoersel.",
         retries=2, timeout_s=120, optional=True),

    Step("wp_quality_check", steps_post.wp_quality_check,
         "Fortell WooCommerce at boka er til kvalitetssjekk. Sidespor.",
         retries=1, timeout_s=60, optional=True),

    Step("cleanup_comfy_folder", steps_post.cleanup_comfy_folder,
         "Slett ordrens comfy-mappe. Kjoeres bare naar det finnes et utkast - "
         "sidene er det eneste vi ikke kan lage om igjen uten GPU-tid.",
         retries=0, timeout_s=600, optional=True),
)

# ---------------------------------------------------------------------------
# PREVIEW-MODUS: forhaandsvisningen til nettbutikken.
#
# Én side, ett bilde, tjue sekunder - og ingenting som koster penger. Den
# deler side-loekka, jobb-DB-en, loggen og koe-semantikken med bokpipelinen,
# fordi det er infrastruktur. Det som er annerledes er arbeidsflyten, og den
# staar her, som data, paa samme maate som bokens.
#
# Den kjoerer bare naar serveren staar i PREVIEW-modus (config/flow.json ->
# "mode"). En bok-PC har denne listen staaende ubrukt.
#
# Ingen PDF, ingen Drive, ingen Gelato, ingen WooCommerce. At en preview-jobb
# ikke kan bestille eller trykke noe er ikke en regel noen maa huske - det er
# at stegene ikke finnes i denne listen.
# ---------------------------------------------------------------------------
PREVIEW_PIPELINE: tuple[Step, ...] = (
    Step("check_delivery", steps_preview.check_delivery,
         "Er sinken (Supabase) satt opp? Staar FOERST av samme grunn som "
         "check_assets i bokpipelinen: en jobb som rendrer ferdig og saa "
         "ikke kan levere, brukte GPU-tid paa ingenting.",
         retries=0, timeout_s=60),

    Step("validate_preview_job", steps_preview.validate_preview_job,
         "Payload -> bok, marked, side, mal og tittel. Sjekker mal, maske, "
         "workflow og line2-logoen MENS det fortsatt er gratis aa stoppe.",
         retries=0, timeout_s=60),

    Step("status_processing", steps_preview.status_processing,
         "Skriv `processing` i statusfila, saa frontenden kan vise fremdrift. "
         "Sidespor.",
         retries=1, timeout_s=60, optional=True),

    Step("fetch_child_image", steps_preview.fetch_child_image,
         "Last ned barnets bilde til input/preview-<job_id>.jpg.",
         # Samme tall som bokpipelinen, av samme grunn: dette er det eneste
         # steget som er avhengig av internett midt i jobben, og utgaaende
         # HTTPS er nede paa denne maskinen 04:30-05:05 hver natt.
         retries=4, timeout_s=300, retry_delay_s=30),

    Step("render_preview_page", steps_preview.render_preview_page,
         "Én side gjennom ComfyUI, i jobbens EGEN mappe. Sjekkpunkt: sida "
         "ligger paa disk og skal ikke rendres om igjen om meldingen kommer "
         "tilbake.",
         retries=1, timeout_s=1800, checkpoint=True),

    Step("render_preview_text", steps_preview.render_preview_text,
         "Tittel + logo (omslag) eller historietekst (innerside), med de "
         "SAMME rendrerne boka trykkes med.",
         retries=1, timeout_s=600),

    Step("deliver_preview", steps_preview.deliver_preview,
         "Last opp bildet, skriv `completed`, POST callback. Bildet foerst - "
         "en `completed` med en URL som ikke finnes er verre enn en spinner.",
         retries=2, timeout_s=600, checkpoint=True),

    Step("notify_preview", steps_preview.notify_preview,
         "Telegram, hvis preview.notify_each er paa. Sidespor.",
         retries=1, timeout_s=60, optional=True),

    Step("cleanup_preview", steps_preview.cleanup_preview,
         "Slett den raa ComfyUI-sida naar bildet er levert. Sidespor.",
         retries=0, timeout_s=120, optional=True),
)

PIPELINES: dict[str, tuple[Step, ...]] = {
    # Fase 2: flow eier side-loekka, n8n gjoer resten. Dette er den aktive.
    "pages": PAGES_PIPELINE,
    # Fase 5: flow eier alt fram til Gelato-utkastet. Settes aktiv naar
    # "pages" er verifisert paa ekte ordre og n8n-workflowen deaktiveres.
    "full": FULL_PIPELINE,
    # PREVIEW-modus. Velges IKKE av ACTIVE, men av servermodusen - se
    # active_name() under.
    "preview": PREVIEW_PIPELINE,
}

# FASE 5 ER AKTIV fra 16.09.2026.
#
# Gjennomgangen skjer i GELATO-UTKASTET, ikke for det. Det er slik det alltid
# har vaert gjort, og det er hele poenget med at pipelinen stopper ved et
# utkast i stedet for en bestilling: mennesket ser boka i Gelato og bestiller
# der. Et stopp etter sidene ville lagt inn et ekstra ledd som ikke fantes
# for, og latt ordre bli staaende og vente paa at noen kjorer /bygg.
#
# Forutsetningene som maatte vaere paa plass, og som var det:
#   * n8n eier ikke lenger noen del av ordreveien - alle ordre-workflowene er
#     deaktiverte, og WooCommerce publiserer selv til RabbitMQ. Se
#     docs/ordreveien.md, verifisert mot broker og n8n-API 16.09.2026.
#   * "full" er kjort helt igjennom paa en EKTE ordre: 1517 (Hestestjernen),
#     alle 17 steg, build_pdfs 137 s og upload_and_draft 26 s.
#
# Pipelinen bestiller fortsatt INGENTING. Den stopper ved utkastet, og det er
# et menneske som trykker bestill i Gelato.
#
# Tilbake til manuell bygging: sett denne til "pages". Én linje, og den er i
# git. En ENKELT ordre kan alltid kjores med den andre pipelinen uten aa
# roere denne - se QueuedJob.pipeline og POST /api/jobs.
ACTIVE = "full"


def active_name() -> str:
    """Navnet paa pipelinen denne serveren skal kjoere.

    To lag, og de svarer paa to forskjellige spoersmaal:

      servermodus   HVA denne maskinen er til - bok eller forhaandsvisning.
                    Staar i config/flow.json ("mode") og velger koe og
                    pipeline sammen. Se flow/worker/config.py.
      ACTIVE        hvilken BOKpipeline som er den aktive ("pages"/"full").
                    Det er et valg om hvor langt flow eier ordreveien, og
                    begrunnelsen staar der ACTIVE staar.

    Derfor overstyrer modusen aldri ACTIVE for boeker: bokmodus har
    pipeline=null i modus-tabellen og faller tilbake hit.
    """
    name = flow_config.mode_conf().get("pipeline")
    return str(name) if name else ACTIVE


def active() -> tuple[Step, ...]:
    return PIPELINES[active_name()]


def by_name(name: str) -> tuple[Step, ...]:
    if name not in PIPELINES:
        raise KeyError(f"ukjent pipeline {name!r}. Finnes: {', '.join(PIPELINES)}")
    return PIPELINES[name]


def describe(name: str | None = None) -> dict:
    """Pipelinen som JSON - grunnlaget for GET /api/workflows og for
    flow-visningen i panelet. Panelet tegner bokser og piler av dette og
    trenger ikke vite hva et steg gjoer."""
    key = name or active_name()
    return {
        "name": key,
        "active": key == active_name(),
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

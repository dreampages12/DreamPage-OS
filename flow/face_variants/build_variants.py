# -*- coding: utf-8 -*-
"""
DreamPage - lag uttrykksvariantene av barnebildet (trist, glad, ...).

Hvilke uttrykk en bok trenger, staar i books/<slug>/config.json: hver side har
`face_expression`. Dette scriptet lager én variant per uttrykk som boka ber
om, med workflows/<uttrykk>.json. Ut kommer

    input/<job_key>-<uttrykk>.jpg

som books.face_for() plukker opp for sidene med det uttrykket. Mangler fila,
bruker siden originalbildet.

Bare boeker i BOOKS faar varianter. Alle andre gaar rett gjennom: der betyr
et `smil` i config i dag det samme som `noytral`, og det er forventet - ikke
noe aa advare om.

Historikk: dette var build_trist_variant.py, som bare kunne lage "trist" til
fotballstjernen side 04. 18.09.2026 fikk fotballstjernen ogsaa en glad
variant til side 14, og uttrykkene ble data i config i stedet for kode her.

Motor: Flux.2 Klein - samme UNET og text encoder som sidegenereringen, saa
modellene blir staaende i VRAM.

Scriptet stopper ALDRI en ordre - det avslutter med 0 uansett. Men et
fallback skal rope: feiler en variant, eller ber boka om et uttrykk det ikke
finnes noen workflow for, skrives en linje med ADVARSEL. Den plukker
face_variants-steget opp og legger i jobbloggen. Foer 18.09.2026 skrev
scriptet "FEILET" - et ord steget ikke lette etter - og feilen forsvant.

Serialisering: ingen. Scriptet kalles som ett steg inne i flow sin jobb, og
flow kjoerer én jobb om gangen. Kjoerer du det for haand mens en ordre gaar,
konkurrerer du om GPU-en. Sjekk `.\dreampage.ps1 status` foerst.

Bruk:
    python build_variants.py <job_key> --book SLUG [--only UTTRYKK] [--force]
    python build_variants.py <job_key> --book SLUG --source bilde.jpg --out-dir D
"""
import argparse
import io
import json
import os
import sys
import time

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_face_variants as BFV  # noqa: E402

sys.path.insert(0, os.path.dirname(HERE))
from paths import BOOKS as BOOKS_DIR  # noqa: E402

WORKFLOWS = os.path.join(HERE, "workflows")
TIMEOUT = 900

# Boeker som faar uttrykksvarianter. Hvilke uttrykk, og paa hvilke sider,
# staar i bokas config.json - ikke her. Legg boka til her naar config-en dens
# er satt opp og variantene er sett paa med egne oeyne.
BOOKS = {"fotballstjernen"}

# Originalbildet. Ingen variant lages for det.
NEUTRAL = "noytral"


def log(msg):
    sys.stdout.write("[varianter] %s\n" % msg)
    sys.stdout.flush()


def warn(msg):
    # "ADVARSEL" er ordet face_variants-steget leter etter.
    log("ADVARSEL: %s" % msg)


def wanted_expressions(book):
    """Uttrykkene boka ber om, i sideorden, uten noytral og uten duplikater."""
    path = os.path.join(str(BOOKS_DIR), book, "config.json")
    with io.open(path, encoding="utf-8") as fh:
        config = json.load(fh)
    pages = list(config.get("pages") or [])
    out = []
    for page in pages:
        expr = str(page.get("face_expression") or NEUTRAL).strip().lower()
        if expr != NEUTRAL and expr not in out:
            out.append(expr)
    return out


def generate(expr, source, dest, job_key):
    crop = "_%s_%s.png" % (expr, job_key)
    crop_path = os.path.join(BFV.INPUT_DIR, crop)
    Image.open(source).convert("RGB").save(crop_path)
    try:
        with io.open(os.path.join(WORKFLOWS, expr + ".json"), encoding="utf-8") as fh:
            graph = json.load(fh)
        graph["1"]["inputs"]["image"] = crop
        graph["15"]["inputs"]["filename_prefix"] = "face_variants/%s_%s" % (expr, job_key)
        img = BFV.wait_for(BFV.submit(graph), TIMEOUT)
        data = BFV.fetch(img)
        BFV.discard_comfy_copy(img)
        Image.open(io.BytesIO(data)).convert("RGB").save(
            dest, "JPEG", quality=95, subsampling=0)
    finally:
        try:
            os.remove(crop_path)
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job_key")
    ap.add_argument("--book", default="")
    ap.add_argument("--source", default=None)
    ap.add_argument("--out-dir", default=None,
                    help="skriv variantene hit i stedet for input/ (for proever)")
    ap.add_argument("--only", default=None, help="lag bare dette uttrykket")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    job_key = str(a.job_key).strip()
    book = str(a.book).strip().lower()

    if book not in BOOKS:
        log("boka '%s' bruker ingen varianter - hopper over" % (book or "?"))
        return 0

    try:
        exprs = wanted_expressions(book)
    except (OSError, ValueError) as exc:
        warn("kunne ikke lese config for '%s' (%s) - ingen varianter, "
             "sidene bruker originalbildet" % (book, exc))
        return 0
    if a.only:
        exprs = [e for e in exprs if e == a.only.strip().lower()]
    if not exprs:
        log("'%s' ber ikke om noen varianter" % book)
        return 0

    source = a.source or os.path.join(BFV.INPUT_DIR, job_key + ".jpg")
    out_dir = a.out_dir or BFV.INPUT_DIR
    if not os.path.isfile(source):
        warn("fant ikke %s - %s bruker originalbildet" % (source, ", ".join(exprs)))
        return 0

    BFV.normalize_orientation(source)        # EXIF bakes inn foer alt annet

    for expr in exprs:
        dest = os.path.join(out_dir, "%s-%s.jpg" % (job_key, expr))
        if not os.path.isfile(os.path.join(WORKFLOWS, expr + ".json")):
            warn("boka ber om '%s', men workflows/%s.json finnes ikke - "
                 "de sidene bruker originalbildet" % (expr, expr))
            continue
        if os.path.isfile(dest) and os.path.getsize(dest) > 0 and not a.force:
            log("%s finnes allerede" % os.path.basename(dest))
            continue
        try:
            t0 = time.time()
            generate(expr, source, dest, job_key)
            log("%s ferdig paa %.0fs" % (os.path.basename(dest), time.time() - t0))
        except Exception as exc:
            # Stopper ikke ordren - men roper.
            warn("%s-varianten feilet (%s) - de sidene bruker originalbildet"
                 % (expr, exc))
            try:
                if os.path.isfile(dest) and os.path.getsize(dest) == 0:
                    os.remove(dest)
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

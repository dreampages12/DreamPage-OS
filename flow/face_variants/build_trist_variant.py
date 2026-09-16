# -*- coding: utf-8 -*-
"""
DreamPage - lag TRIST-varianten av barnebildet.

Kun for boker som staar i BOOKS (i dag: fotballstjernen, side 04). Alle andre
boker gaar rett gjennom uten aa gjore noe.

Ut kommer C:/DreamPage-OS/input/<job_key>-trist.jpg. Det er filnavnet "Pages Config"
i n8n leter etter naar en side har face_expression = "trist"; finnes den ikke,
bruker sideloopen originalbildet som for. Derfor kan dette scriptet ALDRI
stoppe en ordre - det avslutter med 0 uansett hva som gaar galt.

Motor: Flux.2 Klein (workflows/trist.json) - samme UNET og text encoder som
sidegenereringen, saa modellene blir staaende i VRAM.

Serialisering: ingen. Scriptet kalles som ett steg inne i flow sin jobb, og
flow kjoerer én jobb om gangen - saa det KAN ikke kollidere med sideloopen.
Her stod det en laasefil foer; se kommentaren ved "serialisering" nedenfor.

Bruk:
    python build_trist_variant.py <job_key> [--book SLUG] [--force]
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
import build_face_variants as BFV

WORKFLOW = os.path.join(HERE, "workflows", "trist.json")
TIMEOUT = 900

# Boker som faktisk bruker en trist-variant. Staar boka ikke her, gjor
# scriptet ingenting. Legg til nye boker her OG sett face_expression:"trist"
# paa de aktuelle sidene i books/<slug>/config.json.
BOOKS = {"fotballstjernen"}


def log(msg):
    sys.stdout.write("[trist] %s\n" % msg)
    sys.stdout.flush()


# --- serialisering ------------------------------------------------------------
#
# Her stod det en laas: samme `.dreampage-comfy.lock` som n8n sin side-loekke
# brukte, med samme TTL, samme token og 45 minutters venting. Den er fjernet,
# og ikke erstattet med noe.
#
# Grunnen er at DreamPage OS ikke har noen aa serialisere mot. Scriptet kalles
# som ETT STEG inne i flow sin jobb (`face_variants` i pipelinen), og flow er
# én prosess med én arbeidstraad som tar én jobb om gangen. Det er allerede
# umulig for dette scriptet aa kjoere samtidig med side-loekka.
#
# Beholdt man laasen, ville den vaert direkte skadelig: ingen tar eller
# slipper den lenger, saa scriptet ville ventet 45 minutter paa en fil som
# aldri kommer, hver eneste ordre. Steget er valgfritt, saa ordren hadde
# overlevd - den hadde bare tatt tre kvarter lenger.
#
# Kjoerer du scriptet for haand mens en ordre gaar, konkurrerer du om GPU-en.
# Det gjorde du foer ogsaa; laasen beskyttet mot samtidige ComfyUI-prompts,
# ikke mot en operatoer med hastverk. Sjekk `.\dreampage.ps1 status` foerst.


# --- selve jobben ------------------------------------------------------------

def generate(source, dest, job_key):
    crop = "_trist_%s.png" % job_key
    crop_path = os.path.join(BFV.INPUT_DIR, crop)
    Image.open(source).convert("RGB").save(crop_path)
    try:
        graph = json.load(io.open(WORKFLOW, encoding="utf-8"))
        graph["1"]["inputs"]["image"] = crop
        graph["15"]["inputs"]["filename_prefix"] = "face_variants/trist_%s" % job_key
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
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    job_key = str(a.job_key).strip()
    book = str(a.book).strip().lower()

    if book not in BOOKS:
        log("boka '%s' bruker ingen trist-variant - hopper over" % (book or "?"))
        return 0

    source = a.source or os.path.join(BFV.INPUT_DIR, job_key + ".jpg")
    dest = os.path.join(BFV.INPUT_DIR, job_key + "-trist.jpg")

    if os.path.isfile(dest) and not a.force:
        log("%s finnes allerede" % os.path.basename(dest))
        return 0
    if not os.path.isfile(source):
        log("FANT IKKE %s - sidene bruker originalbildet" % source)
        return 0

    BFV.normalize_orientation(source)        # EXIF bakes inn foer alt annet

    try:
        t0 = time.time()
        generate(source, dest, job_key)
        log("%s ferdig paa %.0fs" % (os.path.basename(dest), time.time() - t0))
    except Exception as exc:
        # Dette scriptet skal ALDRI stoppe en ordre: mangler filen, bruker
        # sideloopen originalbildet. Derfor svelges alt, og vi avslutter med 0.
        log("FEILET (%s) - sidene bruker originalbildet" % exc)
        try:
            if os.path.isfile(dest) and os.path.getsize(dest) == 0:
                os.remove(dest)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

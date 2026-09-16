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

Scriptet tar SAMME laas som sideloopen (C:/DreamPage-OS/DreamPage-image/.dreampage-comfy.lock), slik
at det aldri sender jobb til ComfyUI mens en annen ordre genererer sider.

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
LOCK = "C:/DreamPage-OS/DreamPage-image/.dreampage-comfy.lock"
LOCK_TTL = 2 * 60 * 60          # samme 2 timer som n8n-noden
LOCK_WAIT = 45 * 60             # hvor lenge vi venter paa lasen
TIMEOUT = 900

# Boker som faktisk bruker en trist-variant. Staar boka ikke her, gjor
# scriptet ingenting. Legg til nye boker her OG sett face_expression:"trist"
# paa de aktuelle sidene i books/<slug>/config.json.
BOOKS = {"fotballstjernen"}


def log(msg):
    sys.stdout.write("[trist] %s\n" % msg)
    sys.stdout.flush()


# --- lassen ------------------------------------------------------------------

def _lock_stale():
    try:
        with io.open(LOCK, encoding="utf-8") as fh:
            created = float(json.load(fh).get("createdAt") or 0) / 1000.0
        return created <= 0 or (time.time() - created) > LOCK_TTL
    except Exception:
        return True


def acquire(token, job_key, book):
    """Samme lasefil og samme form som 'Acquire Comfy Lock' i n8n."""
    deadline = time.time() + LOCK_WAIT
    while True:
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, json.dumps({
                    "token": token,
                    "createdAt": int(time.time() * 1000),
                    "executionId": "build_trist_variant",
                    "order_id": job_key,
                    "book_slug": book,
                    "page_key": "face-trist",
                    "pageOutputDir": "",
                }, indent=2).encode("utf-8"))
            finally:
                os.close(fd)
            return True
        except OSError:
            if os.path.isfile(LOCK) and _lock_stale():
                log("laasen er foreldet - fjerner den")
                try:
                    os.remove(LOCK)
                    continue
                except OSError:
                    pass
            if time.time() > deadline:
                return False
            time.sleep(5)


def release(token):
    """Fjerner lasen kun hvis den fortsatt er var."""
    try:
        with io.open(LOCK, encoding="utf-8") as fh:
            if json.load(fh).get("token") != token:
                log("laasen tilhorer noen andre naa - rorer den ikke")
                return
        os.remove(LOCK)
    except Exception:
        pass


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

    token = "trist:%s:%s:%d" % (book, job_key, time.time() * 1000)
    if not acquire(token, job_key, book):
        log("fikk ikke Comfy-laasen paa %d min - hopper over" % (LOCK_WAIT // 60))
        return 0
    try:
        t0 = time.time()
        generate(source, dest, job_key)
        log("%s ferdig paa %.0fs" % (os.path.basename(dest), time.time() - t0))
    except Exception as exc:
        log("FEILET (%s) - sidene bruker originalbildet" % exc)
        try:
            if os.path.isfile(dest) and os.path.getsize(dest) == 0:
                os.remove(dest)
        except OSError:
            pass
    finally:
        release(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())

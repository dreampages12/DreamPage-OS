# -*- coding: utf-8 -*-
"""
DreamPage - lag ETT rent bilde av barnet.

Ut kommer et nytt bilde der barnet ser rett i kameraet med hodet rett og
munnen lukket. Det er det bildet headswappen bruker paa alle sider.

    Claude ser paa bildet  ->  Flux.2 Klein lager bildet

Klein-workflowen (workflows/barnebilde.json) er rein prompt-til-bilde:
bilde inn, prompt, bilde ut. INGEN maske, ingen inpainting, ingen LoRA,
ingen andre modeller.

HELE bildet sendes inn. Foerste steg i workflowen er YOLO-ansiktsdeteksjon,
saa den finner barnet ogsaa naar det staar langt unna i et stort bilde.
crop_factor 3.0 gir et romslig utsnitt - haar og skuldre blir med. Finner
YOLO ingen ansikt, faller den tilbake til hele bildet.

Claude ser paa bildet foerst, men BESTEMMER ingenting - den noterer bare om
det er noe i haaret (spenner, boyle, briller) eller ved munnen (mat, smokk).

Bruk:
    python make_child_photo.py <bilde> [<bilde> ...] [--out MAPPE] [--no-ai]
"""
import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import time

import cv2
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import analyse_photo as AP
import build_face_variants as BFV
import straighten as ST

WORKFLOW = os.path.join(HERE, "workflows", "barnebilde.json")
CLAUDE = os.environ.get("DP_CLAUDE_BIN", "C:/Users/tobia/.local/bin/claude.exe")

LOOK_PROMPT = """Look at the photo at {path}. It is a child photo a customer uploaded; only the child's HEAD will be cut out and placed into storybook illustrations.

Only OBSERVE and report. Do not judge usability, do not recommend anything.

Report ONLY these three things:
  1. hair  - objects in or on the hair or head: headband, hair band, hair clips, bows, hat, cap, hood, glasses pushed up.
  2. mouth - things on or around the mouth: food, crumbs, smears, a dummy/pacifier, tongue sticking out. Also say if the mouth is open with teeth showing.
  3. other - AT MOST 3 items, and only things that would still be visible once the head alone is cut out and drawn into a storybook scene.

Everything below the neck is cropped away, so IGNORE clothing, hands, background, furniture, other people, lighting and image quality. Do not list them.

Reply with ONLY this JSON, no prose, no markdown fence:
{{"hair": {{"found": true|false, "items": ["..."]}}, "mouth": {{"found": true|false, "items": ["..."]}}, "other": ["..."], "clean": true|false, "summary": "one short sentence in Norwegian"}}"""


def log(msg):
    sys.stdout.write("[child-photo] %s\n" % msg)
    sys.stdout.flush()


def look(path, timeout=120, tries=2, model=None):
    """Claude ser paa bildet. None hvis kallet ikke gaar igjennom - da
    fortsetter vi som vanlig, for observasjonen styrer ingenting."""
    if not os.path.isfile(CLAUDE):
        return None
    cmd = [CLAUDE, "-p", LOOK_PROMPT.format(path=os.path.abspath(path)),
           "--allowedTools", "Read", "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    for _ in range(tries):
        try:
            out = subprocess.run(cmd, capture_output=True, timeout=timeout,
                                 text=True, encoding="utf-8", errors="replace")
            raw = json.loads(out.stdout).get("result", "")
            a, b = raw.find("{"), raw.rfind("}")
            if a >= 0 and b >= 0:
                return json.loads(raw[a:b + 1])
        except Exception:
            pass
    return None


def run_klein(crop_name, prefix, timeout):
    """Rein Klein: bilde inn, prompt, bilde ut."""
    with io.open(WORKFLOW, encoding="utf-8") as fh:
        graph = json.load(fh)
    graph["1"]["inputs"]["image"] = crop_name
    graph["15"]["inputs"]["filename_prefix"] = prefix
    img = BFV.wait_for(BFV.submit(graph), timeout)
    data = BFV.fetch(img)
    BFV.discard_comfy_copy(img)
    return data


def make(src, out_dir, use_ai=True, timeout=900, model=None):
    tag = os.path.splitext(os.path.basename(src))[0]
    os.makedirs(out_dir, exist_ok=True)
    rec = {"tag": tag, "source": src, "started": time.strftime("%Y-%m-%d %H:%M:%S")}

    original = os.path.join(out_dir, "%s-1-original.jpg" % tag)
    shutil.copyfile(src, original)
    BFV.normalize_orientation(original)      # baker EXIF-rotasjonen inn
    rec["original"] = os.path.basename(original)

    if use_ai:
        seen = look(original, model=model)
        rec["claude"] = seen
        if seen is None:
            log("%-8s claude: ikke tilgjengelig - fortsetter" % tag)
        else:
            bits = []
            if (seen.get("hair") or {}).get("found"):
                bits.append("haar: " + ", ".join(seen["hair"].get("items") or []))
            if (seen.get("mouth") or {}).get("found"):
                bits.append("munn: " + ", ".join(seen["mouth"].get("items") or []))
            for o in (seen.get("other") or []):
                bits.append("annet: " + str(o))
            log("%-8s claude saa: %s" % (tag, "; ".join(bits) if bits else "ingenting"))
    else:
        rec["claude"] = None

    base = AP.load_upright(original)
    pts, faces = AP.landmarks(base)
    if pts is None:
        rec["error"] = "fant ingen ansikt"
        log("%-8s FANT INGEN ANSIKT - hopper over" % tag)
        return rec
    rec["faces"] = faces
    rec["pose_before"] = ST.measure(base, pts)
    log("%-8s hode: pitch %.0f yaw %.0f roll %.0f" % (
        tag, rec["pose_before"]["pitch"], rec["pose_before"]["yaw"],
        rec["pose_before"]["roll"]))

    # HELE bildet gaar inn. Foerste steg i workflowen er YOLO-deteksjon, saa
    # den finner ansiktet selv - ogsaa naar barnet staar langt unna.
    crop_name = "_cp_%s.png" % tag
    Image.fromarray(cv2.cvtColor(base, cv2.COLOR_BGR2RGB)) \
         .save(os.path.join(BFV.INPUT_DIR, crop_name))

    result = os.path.join(out_dir, "%s-2-klein.jpg" % tag)
    try:
        t0 = time.time()
        data = run_klein(crop_name, "child_photo/%s" % tag, timeout)
        Image.open(io.BytesIO(data)).convert("RGB").save(
            result, "JPEG", quality=95, subsampling=0)
        rec["result"] = os.path.basename(result)
        rec["klein_seconds"] = round(time.time() - t0, 1)
        try:
            nb = AP.load_upright(result)
            npts, _ = AP.landmarks(nb)
            if npts is not None:
                rec["pose_after"] = ST.measure(nb, npts)
                log("%-8s ferdig (%.0fs)  pitch %.0f->%.0f yaw %.0f->%.0f roll %.0f->%.0f"
                    % (tag, rec["klein_seconds"],
                       rec["pose_before"]["pitch"], rec["pose_after"]["pitch"],
                       rec["pose_before"]["yaw"], rec["pose_after"]["yaw"],
                       rec["pose_before"]["roll"], rec["pose_after"]["roll"]))
            else:
                log("%-8s ferdig (%.0fs)" % (tag, rec["klein_seconds"]))
        except Exception:
            pass
    except Exception as exc:
        rec["error"] = "klein feilet: %s" % exc
        log("%-8s KLEIN FEILET: %s" % (tag, exc))
    finally:
        try:
            os.remove(os.path.join(BFV.INPUT_DIR, crop_name))
        except OSError:
            pass
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    ap.add_argument("--out", default="C:/ComfyUI/output/barnebilde")
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--ai-model", default=None)
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args()

    records = []
    for src in a.images:
        if not os.path.isfile(src):
            log("hopper over %s (finnes ikke)" % src)
            continue
        records.append(make(src, a.out, not a.no_ai, a.timeout, a.ai_model))

    path = os.path.join(a.out, "rapport.json")
    old = []
    if os.path.isfile(path):
        try:
            with io.open(path, encoding="utf-8") as fh:
                old = json.load(fh)
        except Exception:
            old = []
    merged = {r["tag"]: r for r in old}
    merged.update({r["tag"]: r for r in records})
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(list(merged.values()), ensure_ascii=False, indent=1))
    log("skrev %s (%d bilder)" % (path, len(merged)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

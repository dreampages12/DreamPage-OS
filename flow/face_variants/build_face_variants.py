# -*- coding: utf-8 -*-
"""
DreamPage - klargjor kundens barnebilde for headswap.

Kjores EN gang per ordre, FOR sideloopen starter, og fyller to sloter:

    <order_id>-noytral.jpg   lukket munn, rolig, antydning til smil
    <order_id>-smil.jpg      varmt smil, fortsatt lukket munn

Scriptet BESTEMMER ikke selv - det UTFORER planen fra analyse_photo.py:

    keep      -> kopier det opplastede bildet uendret (det ER allerede uttrykket)
    generate  -> kjor ComfyUI-workflowen som verktoyet peker paa

Med --ai ser Claude Code paa selve bildet, faar maalingene og
verktoykatalogen (workflows/tools.json), og velger handling per slot. Uten
--ai, eller hvis AI-en er utilgjengelig eller foreslar et verktoy som ikke
finnes, gjelder geometriplanen. Den er alltid gyldig.

Fire steg:

 1. NORMALISER ORIENTERING. cv2 bruker EXIF-rotasjon, PIL gjor det ikke, og
    ComfyUI kjorer exif_transpose. Er de tre uenige havner munnmasken paa
    kinnet. Vi baker rotasjonen inn i pikslene en gang og stripper taggen.
    (Dette var arsaken til at ordre 1295 maatte lastes opp paa nytt to ganger.)
 2. ANALYSER -> plan.
 3. UTFOR planen. Generering redigerer KUN munnregionen, saa oyne, nese, har
    og bakgrunn forblir urorte piksler og identiteten kan ikke drifte.
 4. KOMPONER TILBAKE gjennom masken i full opplosning - VAE-rundturen far ikke
    rore resten av bildet.

Feiler noe som helst, faller sloten tilbake til originalbildet. En betalt ordre
skal aldri stoppe pa dette.

Bruk:
    python build_face_variants.py <order_id> [--source F] [--force] [--ai]
"""
import argparse
import io as _io
import json
import os
import shutil
import sys
import time
import urllib.parse
import urllib.request

import cv2
import numpy as np
from PIL import Image, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyse_photo as AP

COMFY = os.environ.get("DP_COMFY_URL", "http://127.0.0.1:8188")
INPUT_DIR = os.environ.get("DP_COMFY_INPUT", "C:/ComfyUI/input")
OUTPUT_DIR = os.environ.get("DP_COMFY_OUTPUT", "C:/ComfyUI/output")
WF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workflows")

CROP_FACTOR = 1.7          # hvor mye rundt ansiktet vi tar med i utsnittet
MASK_GROW = 0.45           # maskevekst i andel av munnbredden
MASK_FEATHER = 0.22        # myk kant, samme enhet


def log(msg):
    sys.stdout.write("[face-variants] %s\n" % msg)
    sys.stdout.flush()


# ---------------------------------------------------------------- orientering
def normalize_orientation(path):
    """Baker EXIF-rotasjonen inn i pikslene og stripper taggen. Idempotent."""
    try:
        im = Image.open(path)
        if im.getexif().get(274, 1) in (1, None):
            return False
        ImageOps.exif_transpose(im.convert("RGB")).save(
            path, "JPEG", quality=95, subsampling=0)
        log("normaliserte EXIF-orientering paa %s" % os.path.basename(path))
        return True
    except Exception as exc:
        log("kunne ikke normalisere orientering (%s) - fortsetter" % exc)
        return False


# --------------------------------------------------------------- maske/utsnitt
def head_box(pts):
    x1, y1 = pts.min(0)
    x2, y2 = pts.max(0)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    s = max(x2 - x1, y2 - y1) * CROP_FACTOR
    return (int(cx - s / 2), int(cy - s / 2), int(cx + s / 2), int(cy + s / 2))


def mouth_mask(pts, shape):
    """Maske rundt munnen: leppene, nasolabialfoldene og litt hake - alt som
    maa endres for at en lukket munn skal se naturlig ut."""
    h, w = shape[:2]
    m = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(m, cv2.convexHull(pts[AP.OUTER_LIP].astype(np.int32)), 255)
    mw = float(np.linalg.norm(pts[AP.IDX["c_l"]] - pts[AP.IDX["c_r"]]))
    k = max(3, int(mw * MASK_GROW) | 1)
    m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    b = max(3, int(mw * MASK_FEATHER) | 1)
    return cv2.GaussianBlur(m, (b, b), 0)


# --------------------------------------------------------------------- ComfyUI
def submit(graph):
    body = json.dumps({"prompt": graph}).encode("utf-8")
    req = urllib.request.Request(COMFY + "/prompt", body,
                                 {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))["prompt_id"]


def wait_for(prompt_id, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        hist = json.load(urllib.request.urlopen(
            COMFY + "/history/" + prompt_id, timeout=30))
        entry = hist.get(prompt_id)
        if entry:
            for node in (entry.get("outputs") or {}).values():
                for img in node.get("images", []):
                    if img.get("type") == "output":
                        return img
            if (entry.get("status") or {}).get("status_str") == "error":
                raise RuntimeError("ComfyUI: %s" % json.dumps(entry["status"])[:600])
        time.sleep(1.5)
    raise RuntimeError("tidsavbrudd etter %ss" % timeout)


def fetch(img):
    q = urllib.parse.urlencode({"filename": img["filename"],
                                "subfolder": img.get("subfolder", ""),
                                "type": "output"})
    return urllib.request.urlopen(COMFY + "/view?" + q, timeout=120).read()


def discard_comfy_copy(img):
    """SaveImage-kopien i output/ er ikke artefaktet - varianten i input/ er."""
    try:
        path = os.path.join(OUTPUT_DIR, img.get("subfolder", ""), img["filename"])
        root = os.path.abspath(OUTPUT_DIR)
        if os.path.abspath(path).startswith(root) and os.path.isfile(path):
            os.remove(path)
            folder = os.path.dirname(path)
            if os.path.abspath(folder) != root and not os.listdir(folder):
                os.rmdir(folder)
    except Exception:
        pass


def find_node(graph, class_type, has_input):
    for nid, node in graph.items():
        if node.get("class_type") == class_type and has_input in (node.get("inputs") or {}):
            return nid
    raise RuntimeError("fant ikke %s i workflowen" % class_type)


def run_tool(tool, crop_name, mask_name, prefix, timeout):
    """Kjorer workflowen verktoyet peker paa. Vi patcher tre punkter:
    hodeutsnitt, munnmaske og utdata-prefix. Resten av grafen eier du."""
    path = os.path.join(WF_DIR, tool["workflow"])
    with _io.open(path, encoding="utf-8") as fh:
        graph = json.load(fh)
    graph[find_node(graph, "LoadImage", "image")]["inputs"]["image"] = crop_name
    graph[find_node(graph, "LoadImageMask", "image")]["inputs"]["image"] = mask_name
    graph[find_node(graph, "SaveImage", "filename_prefix")]["inputs"]["filename_prefix"] = prefix
    img = wait_for(submit(graph), timeout)
    data = fetch(img)
    discard_comfy_copy(img)
    return data


def compose(gen_bytes, base_bgr, mask, box, dest):
    """Legger de genererte pikslene tilbake GJENNOM masken, i full opplosning.
    Utenfor masken beholdes originalens piksler bit for bit."""
    x1, y1, x2, y2 = box
    h, w = base_bgr.shape[:2]
    gen = cv2.cvtColor(np.array(Image.open(_io.BytesIO(gen_bytes)).convert("RGB")),
                       cv2.COLOR_RGB2BGR)
    gen = cv2.resize(gen, (x2 - x1, y2 - y1), interpolation=cv2.INTER_LANCZOS4)

    full = np.zeros_like(base_bgr)
    sx1, sy1 = max(x1, 0), max(y1, 0)
    sx2, sy2 = min(x2, w), min(y2, h)
    full[sy1:sy2, sx1:sx2] = gen[sy1 - y1:sy2 - y1, sx1 - x1:sx2 - x1]

    a = (mask.astype(np.float32) / 255.0)[:, :, None]
    out = full.astype(np.float32) * a + base_bgr.astype(np.float32) * (1 - a)
    Image.fromarray(cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8),
                                 cv2.COLOR_BGR2RGB)).save(
        dest, "JPEG", quality=95, subsampling=0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("order_id")
    ap.add_argument("--source", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--ai", action="store_true",
                    help="la Claude Code se paa bildet og velge verktoy")
    ap.add_argument("--ai-model", default=None)
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()

    reg = AP.registry()
    tools = {t["name"]: t for t in reg["tools"]}
    slots = AP.slot_names(reg)

    order = str(args.order_id).strip()
    source = args.source or os.path.join(INPUT_DIR, order + ".jpg")
    report = {"order_id": order, "source": source, "results": {}}

    if not os.path.isfile(source):
        log("FANT IKKE kildebilde %s - ingenting a gjore" % source)
        report["error"] = "mangler kildebilde"
        return finish(report)

    normalize_orientation(source)

    try:
        info = AP.analyse(source, use_ai=args.ai, ai_model=args.ai_model)
    except Exception as exc:
        log("analyse feilet (%s) - genererer alle sloter" % exc)
        info = {"plan": {s: {"action": "generate", "tool": s} for s in slots},
                "problems": ["analyse feilet: %s" % exc], "decided_by": "fallback"}
    report["analysis"] = info

    plan = info.get("plan") or {}
    log("bestemt av %s: %s" % (info.get("decided_by"), json.dumps(
        {s: (plan.get(s) or {}).get("action") for s in slots})))
    if info.get("ai_reason"):
        log("ai: " + str(info["ai_reason"]))
    for p in info.get("problems", []):
        log("MERK: " + p)

    base_bgr = AP.load_upright(source)
    mask = box = crop_name = mask_name = None
    need_gen = any((plan.get(s) or {}).get("action") == "generate" for s in slots)
    if need_gen:
        try:
            pts, _ = AP.landmarks(base_bgr)
            if pts is None:
                raise RuntimeError("ingen ansikt")
            box = head_box(pts)
            mask = mouth_mask(pts, base_bgr.shape)
            crop_name = "_fv_%s_crop.png" % order
            mask_name = "_fv_%s_mask.png" % order
            Image.fromarray(cv2.cvtColor(base_bgr, cv2.COLOR_BGR2RGB)).crop(box) \
                 .resize((1024, 1024), Image.LANCZOS) \
                 .save(os.path.join(INPUT_DIR, crop_name))
            Image.fromarray(mask).crop(box) \
                 .resize((1024, 1024), Image.LANCZOS) \
                 .save(os.path.join(INPUT_DIR, mask_name))
        except Exception as exc:
            log("kunne ikke lage munnmaske (%s) - alt faller tilbake" % exc)
            plan = {s: {"action": "fallback"} for s in slots}

    for slot in slots:
        dest = os.path.join(INPUT_DIR, "%s-%s.jpg" % (order, slot))
        entry = plan.get(slot) or {"action": "generate", "tool": slot}
        action = entry.get("action")

        if os.path.isfile(dest) and not args.force:
            report["results"][slot] = "cached"
            log("%-8s finnes allerede, hopper over" % slot)
            continue

        if action in ("keep", "fallback"):
            shutil.copyfile(source, dest)
            report["results"][slot] = action
            if action == "keep":
                log("%-8s BEHOLDT originalen%s" % (
                    slot, (" - " + entry["why"]) if entry.get("why") else ""))
            continue

        tool = tools.get(entry.get("tool"))
        if not tool:
            shutil.copyfile(source, dest)
            report["results"][slot] = "fallback: ukjent verktoy"
            log("%-8s ukjent verktoy %r - falt tilbake" % (slot, entry.get("tool")))
            continue

        try:
            t0 = time.time()
            data = run_tool(tool, crop_name, mask_name,
                            "face_variants/%s/%s" % (order, slot), args.timeout)
            compose(data, base_bgr, mask, box, dest)
            report["results"][slot] = "generate:" + tool["name"]
            log("%-8s KJORTE %s (%.1fs)%s" % (
                slot, tool["name"], time.time() - t0,
                (" - " + entry["why"]) if entry.get("why") else ""))
        except Exception as exc:
            try:
                shutil.copyfile(source, dest)
                report["results"][slot] = "fallback: %s" % exc
                log("%-8s FEILET (%s) - falt tilbake til originalen" % (slot, exc))
            except Exception as copy_exc:
                report["results"][slot] = "error: %s" % copy_exc
                log("%-8s FEILET helt: %s" % (slot, copy_exc))

    for name in (crop_name, mask_name):
        if name:
            try:
                os.remove(os.path.join(INPUT_DIR, name))
            except OSError:
                pass

    return finish(report)


def finish(report):
    """Rapporten leses av n8n, som varsler paa Telegram hvis bildet er daarlig."""
    path = os.path.join(INPUT_DIR, "%s-facevariants.json" % report["order_id"])
    try:
        with _io.open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(report, ensure_ascii=False, indent=1))
    except Exception:
        pass
    log("RESULTAT " + json.dumps(report.get("results", {}), ensure_ascii=False))
    a = report.get("analysis") or {}
    if a.get("usable") is False:
        log("ADVARSEL: bildet er flagget som lite egnet: %s"
            % "; ".join(a.get("problems", [])))
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""
DreamPage - se paa det opplastede barnebildet og BESTEM hva som skal skje.

Dette er beslutningsleddet, ikke en varsellampe. Ut kommer en plan med en
handling per uttrykkslot:

    {"noytral": {"action": "keep"},
     "smil":    {"action": "generate", "tool": "smil"}}

`keep`     = bruk det opplastede bildet uendret (det ER allerede uttrykket)
`generate` = kjor den navngitte ComfyUI-workflowen fra verktoykatalogen

To lag tar beslutningen, i denne rekkefolgen:

 1. GEOMETRI (alltid, ~0.3 s, ren CPU, ingen nett).
    MediaPipe Face Landmarker maaler munnaapning, munnbredde og hodevinkel.
    Deterministisk. Kalibrert paa ekte kundebilder: lukket munn maaler
    gap 0.003-0.05, aapen munn 0.22-0.38. Dette er ALLTID en gyldig plan, og
    fungerer som gulv hvis alt annet svikter.

 2. AI (valgfritt, ~15 s). Claude Code headless ser paa selve bildet, faar
    maalingene OG verktoykatalogen (workflows/tools.json), og velger handling
    per slot. Den ser det geometri ikke kan: mat i munnen, smokk, haand foran
    ansiktet, grimaser, flere barn. Svaret valideres mot katalogen - finner den
    paa et verktoy som ikke finnes, forkastes planen og geometrien gjelder.

Vil du gi AI-en et nytt verktoy: legg workflowen i workflows/ og for den opp i
tools.json med en beskrivelse av naar den skal brukes. Ingen kodeendring.

Bruk:
    python analyse_photo.py <bilde> [--ai] [--json]
"""
import argparse
import json
import math
import os
import subprocess
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = "C:/ComfyUI/models/mediapipe/face_landmarker.task"
REGISTRY = os.path.join(HERE, "workflows", "tools.json")
CLAUDE = os.environ.get("DP_CLAUDE_BIN", "C:/Users/tobia/.local/bin/claude.exe")

IDX = dict(up_in=13, lo_in=14, up_out=0, lo_out=17, c_l=61, c_r=291,
           cheek_l=234, cheek_r=454, eye_l_up=159, eye_l_lo=145,
           eye_r_up=386, eye_r_lo=374, eye_l_out=33, eye_l_in=133,
           eye_r_in=362, eye_r_out=263, nose=1)
INNER_LIP = [78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308, 415,
             310, 311, 312, 13, 82, 81, 80, 191]
OUTER_LIP = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409,
             270, 269, 267, 0, 37, 39, 40, 185]

# Terskler kalibrert 2026-08-21 paa ordrebildene 1275/1281/1282/1284/1289/1291/1295
GAP_CLOSED = 0.12
GAP_WIDE = 0.28
SMILE_CURL = 0.05
SMILE_WIDTH = 0.42
ROLL_MAX = 30.0

_LM = None


def registry():
    with open(REGISTRY, encoding="utf-8") as fh:
        return json.load(fh)


def slot_names(reg=None):
    return [s["name"] for s in (reg or registry())["slots"]]


def _landmarker():
    global _LM
    if _LM is None:
        import mediapipe as mp
        from mediapipe.tasks.python import vision, BaseOptions
        _LM = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=MODEL),
                running_mode=vision.RunningMode.IMAGE, num_faces=2))
    return _LM


def load_upright(path):
    """Leser bildet slik ComfyUI ser det - med EXIF-rotasjonen anvendt.

    cv2.imread BRUKER EXIF, PIL gjor det IKKE, og ComfyUI kjorer
    exif_transpose (nodes.py:1716). Blander man disse havner munnmasken paa
    kinnet. Vi gaar alltid via PIL + exif_transpose.
    """
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(path).convert("RGB"))
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


def landmarks(bgr):
    import mediapipe as mp
    res = _landmarker().detect(mp.Image(
        image_format=mp.ImageFormat.SRGB,
        data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))
    if not res.face_landmarks:
        return None, 0
    h, w = bgr.shape[:2]
    best, best_area = None, -1.0
    for f in res.face_landmarks:
        p = np.array([[q.x * w, q.y * h] for q in f])
        area = float((p[:, 0].max() - p[:, 0].min()) * (p[:, 1].max() - p[:, 1].min()))
        if area > best_area:
            best, best_area = p, area
    return best, len(res.face_landmarks)


def geometry(bgr, pts):
    P = lambda k: pts[IDX[k]]
    d = lambda a, b: float(np.linalg.norm(P(a) - P(b)))
    h, w = bgr.shape[:2]

    face_w = d("cheek_l", "cheek_r") or 1.0
    mouth_w = d("c_l", "c_r") or 1.0
    gap = d("up_in", "lo_in") / mouth_w

    mask = np.zeros((h, w), np.uint8)
    cv2.fillPoly(mask, [pts[INNER_LIP].astype(np.int32)], 255)
    px = bgr[mask > 0]
    teeth = tongue = 0.0
    if len(px) > 20 and gap > GAP_CLOSED:
        hsv = cv2.cvtColor(px.reshape(-1, 1, 3), cv2.COLOR_BGR2HSV)
        hsv = hsv.reshape(-1, 3).astype(float)
        H, S, V = hsv[:, 0], hsv[:, 1], hsv[:, 2]
        teeth = float(np.mean((S < 70) & (V > 120)))
        tongue = float(np.mean(((H < 12) | (H > 168)) & (S > 110) & (V > 70)))

    lip_mid_y = (P("up_in")[1] + P("lo_in")[1]) / 2
    corner_y = (P("c_l")[1] + P("c_r")[1]) / 2
    curl = float((lip_mid_y - corner_y) / mouth_w)

    eye = (d("eye_l_up", "eye_l_lo") / max(d("eye_l_out", "eye_l_in"), 1e-6) +
           d("eye_r_up", "eye_r_lo") / max(d("eye_r_in", "eye_r_out"), 1e-6)) / 2

    v = P("eye_r_out") - P("eye_l_out")
    roll = abs(math.degrees(math.atan2(v[1], v[0])))
    roll = min(roll, 180 - roll)
    yaw = float((P("nose")[0] - (P("cheek_l")[0] + P("cheek_r")[0]) / 2) / face_w)

    return {"gap": round(float(gap), 3),
            "mouth_width": round(float(mouth_w / face_w), 3),
            "curl": round(curl, 3), "teeth": round(teeth, 3),
            "tongue": round(tongue, 3), "eye_open": round(float(eye), 3),
            "roll_deg": round(roll, 1), "yaw": round(yaw, 3),
            "face_px": int(face_w)}


def classify(m):
    if m["gap"] <= GAP_CLOSED:
        mouth = "closed"
    elif m["gap"] <= GAP_WIDE:
        mouth = "open"
    else:
        mouth = "wide_open"
    smiling = (m["curl"] > SMILE_CURL) or (m["mouth_width"] > SMILE_WIDTH)
    return mouth, bool(smiling)


def geometry_plan(mouth, smiling, reg):
    """Gulvet. Kopier originalen der den allerede ER uttrykket, ellers kjor
    verktoyet som produserer sloten."""
    closed = mouth == "closed"
    by_slot = {t["produces"]: t["name"] for t in reg["tools"] if t.get("produces")}
    plan = {}
    for slot in slot_names(reg):
        if slot == "noytral":
            keep = closed and not smiling
        elif slot == "smil":
            keep = closed and smiling
        else:
            keep = False
        plan[slot] = ({"action": "keep"} if keep else
                      {"action": "generate", "tool": by_slot.get(slot, slot)})
    return plan


# ------------------------------------------------------------------ AI-leddet
def build_prompt(path, metrics, mouth, smiling, reg):
    tools = "\n".join(
        "  - %s : %s (ca %ss)" % (t["name"], t["description"], t.get("cost_seconds", "?"))
        for t in reg["tools"])
    slots = "\n".join("  - %s : %s" % (s["name"], s["description"]) for s in reg["slots"])
    return (
        "You decide how to prepare a customer's uploaded child photo for a "
        "personalised children's book. The child's head is swapped onto "
        "storybook illustrations, and each page needs a specific expression.\n\n"
        "Look at the image: " + os.path.abspath(path) + "\n\n"
        "Geometric measurements already taken (trust these for pure geometry; "
        "gap is inner-lip opening divided by mouth width, where <=0.12 is a "
        "closed mouth):\n" + json.dumps(metrics) +
        "\nGeometry classified the mouth as '" + mouth + "', smiling=" +
        str(bool(smiling)).lower() + ".\n\n"
        "You must fill these expression slots:\n" + slots + "\n\n"
        "Available actions:\n"
        "  - keep     : use the uploaded photo unchanged for that slot. "
        "Always prefer this when the child ALREADY has that expression and "
        "nothing spoils the mouth - a real photo beats an edit.\n"
        "  - generate : run a ComfyUI workflow that edits ONLY the mouth "
        "region; eyes, nose, hair and background stay untouched pixels.\n\n"
        "Tools you can call with 'generate':\n" + tools + "\n\n"
        "Rules:\n"
        "  - Never 'keep' a photo where the mouth is spoiled: food, a dummy, a "
        "hand, a tongue out, a grimace, or teeth showing when the slot needs a "
        "closed mouth. Generate instead.\n"
        "  - Only use tool names from the list above.\n"
        "  - Generating costs time, so do not generate what you can keep.\n\n"
        "Reply with ONLY this JSON, no prose, no markdown fence:\n"
        '{"plan": {"noytral": {"action": "keep|generate", "tool": "<tool name '
        'or null>", "why": "short"}, "smil": {"action": "keep|generate", '
        '"tool": "<tool name or null>", "why": "short"}}, '
        '"photo": {"usable": true|false, "obstruction": '
        '"none|food|hand|pacifier|glasses|other", "faces": <count>, '
        '"problems": ["..."]}, "reason": "one short sentence"}')


def ask_ai(path, metrics, mouth, smiling, reg, timeout=120, model=None, tries=2):
    """Claude Code headless. Returnerer None hvis noe som helst gaar galt -
    da gjelder geometriplanen.

    Ett gjenforsok, fordi kallet av og til faller ut forbigaaende. Er det
    fortsatt nede, er geometrien et fullgodt gulv - vi venter ikke lenger.
    """
    if not os.path.isfile(CLAUDE):
        return None
    cmd = [CLAUDE, "-p", build_prompt(path, metrics, mouth, smiling, reg),
           "--allowedTools", "Read", "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    for attempt in range(tries):
        try:
            out = subprocess.run(cmd, capture_output=True, timeout=timeout,
                                 text=True, encoding="utf-8", errors="replace")
            raw = json.loads(out.stdout).get("result", "")
            start, end = raw.find("{"), raw.rfind("}")
            if start >= 0 and end >= 0:
                return json.loads(raw[start:end + 1])
        except Exception:
            pass
    return None


def validate_plan(plan, reg):
    """Et verktoynavn AI-en har funnet paa er en hard feil - da forkaster vi
    hele planen og bruker geometrien. Halvveis riktig er verre enn forutsigbar."""
    known = {t["name"] for t in reg["tools"]}
    clean = {}
    for slot in slot_names(reg):
        entry = (plan or {}).get(slot)
        if not isinstance(entry, dict):
            return None, "mangler slot %r" % slot
        action = entry.get("action")
        if action == "keep":
            clean[slot] = {"action": "keep", "why": entry.get("why", "")}
        elif action == "generate":
            tool = entry.get("tool")
            if tool not in known:
                return None, "ukjent verktoy %r for %r" % (tool, slot)
            clean[slot] = {"action": "generate", "tool": tool,
                           "why": entry.get("why", "")}
        else:
            return None, "ugyldig handling %r for %r" % (action, slot)
    return clean, None


def analyse(path, use_ai=False, ai_model=None):
    reg = registry()
    out = {"path": path, "ok": False, "problems": [], "decided_by": "geometry"}
    bgr = load_upright(path)
    out["size"] = [int(bgr.shape[1]), int(bgr.shape[0])]

    pts, faces = landmarks(bgr)
    if pts is None:
        out["problems"].append("fant ingen ansikt")
        by_slot = {t["produces"]: t["name"] for t in reg["tools"] if t.get("produces")}
        out["plan"] = {s: {"action": "generate", "tool": by_slot.get(s, s)}
                       for s in slot_names(reg)}
        out["usable"] = False
        return out

    m = geometry(bgr, pts)
    mouth, smiling = classify(m)
    out.update({"ok": True, "metrics": m, "faces": faces,
                "mouth": mouth, "smiling": smiling,
                "plan": geometry_plan(mouth, smiling, reg)})

    if faces > 1:
        out["problems"].append("flere ansikter i bildet (%d)" % faces)
    if m["roll_deg"] > ROLL_MAX:
        out["problems"].append("hodet er vridd %.0f grader" % m["roll_deg"])
    if m["face_px"] < 120:
        out["problems"].append("ansiktet er lite (%d px bredt)" % m["face_px"])

    if use_ai:
        ai = ask_ai(path, m, mouth, smiling, reg, model=ai_model)
        out["ai"] = ai
        if not ai:
            out["problems"].append("ai: hoppet over (utilgjengelig)")
        else:
            plan, err = validate_plan(ai.get("plan"), reg)
            if plan:
                out["plan"] = plan
                out["decided_by"] = "ai"
                out["ai_reason"] = ai.get("reason", "")
            else:
                out["problems"].append("ai: forkastet plan (%s)" % err)
            photo = ai.get("photo") or {}
            for p in (photo.get("problems") or []):
                out["problems"].append("ai: " + str(p))
            if photo.get("usable") is False:
                out["problems"].append("ai: " + str(ai.get("reason", "lite egnet")))

    hard = [p for p in out["problems"] if not p.startswith("ai: hoppet")]
    out["usable"] = not hard
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--ai", action="store_true",
                    help="la Claude Code se paa bildet og velge verktoy")
    ap.add_argument("--ai-model", default=None, help="f.eks. sonnet")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = analyse(a.image, a.ai, a.ai_model)
    print(json.dumps(r, ensure_ascii=False, indent=None if a.json else 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

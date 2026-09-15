# -*- coding: utf-8 -*-
"""
Retter hodet og blikket mot kameraet.

Maaler hodets faktiske stilling med solvePnP mot en generisk 3D-hodemodell
(pitch/yaw/roll i grader) og blikket ut fra hvor iris ligger inne i oyet.
Korreksjonen gjores av LivePortrait, som WARPER de faktiske pikslene - den
syntetiserer ingenting, saa barnet kan ikke bli en annen. (Det var nettopp
munnen LivePortrait ikke klarte; der finnes det ingen lukkede lepper aa warpe
fram. Hodestilling og blikk er derimot ren geometri, og det er den god paa.)

Vi retter bare DELVIS opp. Et hode som staar helt rett mot kamera ser stivt ut,
og store warper blir gummiaktige. Innenfor dodsonen roeres bildet ikke i det
hele tatt.

Fortegn og styrke er maalt empirisk 2026-08-25, ikke gjettet:
    rotate_yaw   = +yaw    reduserer yaw   (~0.80 grader effekt per enhet)
    rotate_pitch = -pitch  reduserer pitch (~0.74 per enhet)
    rotate_roll  = -roll   reduserer roll  (~1.07 per enhet)
    pupil_x/y    = -blikk / 0.0115
"""
import math
import os

import cv2
import numpy as np

# Generisk 3D-hodemodell (mm) mot MediaPipe-punktene under
MODEL_3D = np.array([
    (0.0, 0.0, 0.0),        # nesetipp
    (0.0, -63.6, -12.5),    # hake
    (-43.3, 32.7, -26.0),   # venstre oyekrok (ytre)
    (43.3, 32.7, -26.0),    # hoyre oyekrok (ytre)
    (-28.9, -28.9, -24.1),  # venstre munnvik
    (28.9, -28.9, -24.1),   # hoyre munnvik
], dtype=np.float64)
POSE_IDS = [1, 152, 33, 263, 61, 291]

DEADZONE_ANGLE = 6.0     # grader - under dette roeres hodet ikke
DEADZONE_ROLL = 3.0
DEADZONE_GAZE = 0.030    # andel av oyebredden
CORRECT_FRACTION = 0.70  # vi retter opp 70 % av avviket, ikke alt
MAX_ROTATE = 13.0        # noden tillater 20, men over ~13 blir warpen gummiaktig
MAX_PUPIL = 8.0
EFF_YAW, EFF_PITCH, EFF_ROLL = 0.80, 0.74, 1.07
GAZE_PER_UNIT = 0.0115

EDITOR_DEFAULTS = dict(
    rotate_pitch=0.0, rotate_yaw=0.0, rotate_roll=0.0, blink=0.0, eyebrow=0.0,
    wink=0.0, pupil_x=0.0, pupil_y=0.0, aaa=0.0, eee=0.0, woo=0.0, smile=0.0,
    src_ratio=1.0,          # 1.0 = behold barnets eget uttrykk urort
    sample_ratio=1.0, sample_parts="OnlyExpression", crop_factor=1.7)


def head_pose(bgr, pts):
    """pitch, yaw, roll i grader. 0/0/0 = rett mot kameraet."""
    h, w = bgr.shape[:2]
    image_pts = np.array([pts[i] for i in POSE_IDS], dtype=np.float64)
    f = float(w)
    cam = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]], dtype=np.float64)
    ok, rvec, _ = cv2.solvePnP(MODEL_3D, image_pts, cam, np.zeros((4, 1)),
                               flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        return 0.0, 0.0, 0.0
    R, _ = cv2.Rodrigues(rvec)
    sy = math.sqrt(R[0, 0] ** 2 + R[1, 0] ** 2)
    x = math.degrees(math.atan2(R[2, 1], R[2, 2]))
    yaw = math.degrees(math.atan2(-R[2, 0], sy))
    pitch = -(180 - abs(x)) * np.sign(x) if abs(x) > 90 else x
    v = pts[263] - pts[33]
    roll = (math.degrees(math.atan2(v[1], v[0])) + 180) % 360 - 180
    return float(pitch), float(yaw), float(roll)


def gaze_offset(pts):
    """Hvor iris ligger i forhold til oyets senter. 0 = ser rett i kameraet."""
    def one(iris, outer, inner, upper, lower):
        cx = (pts[outer][0] + pts[inner][0]) / 2
        w = abs(pts[outer][0] - pts[inner][0]) or 1.0
        cy = (pts[upper][1] + pts[lower][1]) / 2
        h = abs(pts[upper][1] - pts[lower][1]) or 1.0
        return (pts[iris][0] - cx) / w, (pts[iris][1] - cy) / h
    a = one(468, 33, 133, 159, 145)
    b = one(473, 362, 263, 386, 374)
    return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2


def _excess(value, deadzone):
    if abs(value) <= deadzone:
        return 0.0
    return (abs(value) - deadzone) * (1 if value > 0 else -1)


def plan_correction(pitch, yaw, roll, gaze_x, gaze_y):
    """Hvor mye vi faktisk ber LivePortrait om. Tomt dict = bildet er bra nok."""
    def rot(excess, eff):
        if not excess:
            return 0.0
        want = excess * CORRECT_FRACTION
        return round(max(-MAX_ROTATE, min(MAX_ROTATE, want / eff)), 1)

    corr = {
        "rotate_yaw":   rot(_excess(yaw, DEADZONE_ANGLE), EFF_YAW),
        "rotate_pitch": -rot(_excess(pitch, DEADZONE_ANGLE), EFF_PITCH),
        "rotate_roll":  -rot(_excess(roll, DEADZONE_ROLL), EFF_ROLL),
    }
    for key, g in (("pupil_x", gaze_x), ("pupil_y", gaze_y)):
        e = _excess(g, DEADZONE_GAZE)
        corr[key] = round(max(-MAX_PUPIL, min(MAX_PUPIL,
                                              -e / GAZE_PER_UNIT)), 1) if e else 0.0
    return {k: v for k, v in corr.items() if v}


def build_graph(image_name, correction, prefix):
    params = dict(EDITOR_DEFAULTS)
    params.update(correction)
    params["src_image"] = ["1", 0]
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "2": {"class_type": "ExpressionEditor", "inputs": params},
        "3": {"class_type": "SaveImage",
              "inputs": {"images": ["2", 0], "filename_prefix": prefix}},
    }


def measure(bgr, pts):
    pitch, yaw, roll = head_pose(bgr, pts)
    gx, gy = gaze_offset(pts)
    return {"pitch": round(pitch, 1), "yaw": round(yaw, 1), "roll": round(roll, 1),
            "gaze_x": round(gx, 3), "gaze_y": round(gy, 3)}

# -*- coding: utf-8 -*-
"""Lag headmask fra et malbilde: mediapipe-ansiktsdeteksjon + ellipse.

Ansiktsboksen fra detektoren dekker bare ansiktet - masken skal dekke HELE
hodet med haar. Utvidelsesfaktorene under er kalibrert mot maskene brukeren
tegnet for haand (04/05 i 2-4-aars-settet til dinosaurenes-dal), slik at de
genererte maskene faar samme form og dekning som de manuelle.

Bruk:
  python make_headmask.py --image "C:/ComfyUI/input/01(dinosaur)2-4aar.png" \
      --out "C:/ComfyUI/input/01-headmask(dinosaur)2-4aar.png"
  python make_headmask.py --calibrate <bilde> <manuell-maske> [...]
"""

import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# Foerst kalibrert mot de haandtegnede maskene 04/05 i 2-4-aars-settet
# (grow_w 1.59, grow_h 1.75, shift_y -0.035). I praksis ble den masken for
# TRANG: kjeven og haartoppen falt utenfor, og headswappen sydde da tilbake
# malens eget haar/hake. 2026-09-13 oekt ~30% etter tilbakemelding paa
# dinosaurenes-dal. Maskene skal heller vaere litt for store enn for smaa -
# LanPaint maler uansett bare der den trenger det.
GROW_W = 2.05          # bredde / ansiktsboksens bredde
GROW_H = 2.25          # hoyde  / ansiktsboksens hoyde
SHIFT_Y = -0.05        # senterforskyvning opp, i andeler av boksens hoyde
FEATHER = 0.06         # myk kant, andel av maskens hoyde


_ANALYSER = None


def _analyser():
    """insightface buffalo_l - samme detektor PuLID allerede bruker lokalt.

    (mediapipe er installert, men bygget her har bare `tasks`-API-et og ingen
    `solutions.face_detection`, saa den er ikke et alternativ.)
    """
    global _ANALYSER
    if _ANALYSER is None:
        from insightface.app import FaceAnalysis
        app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection"],
                           providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=-1, det_size=(1024, 1024))
        _ANALYSER = app
    return _ANALYSER


def detect_face(path: str):
    """Returnerer (x, y, w, h) i piksler for det stoerste ansiktet."""
    import cv2

    img = np.array(Image.open(path).convert("RGB"))[:, :, ::-1]
    faces = _analyser().get(img)
    if not faces:
        return None
    face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    x1, y1, x2, y2 = face.bbox
    return (float(x1), float(y1), float(x2 - x1), float(y2 - y1))


def build_mask(size, face, grow_w=GROW_W, grow_h=GROW_H,
               shift_y=SHIFT_Y, feather=FEATHER) -> Image.Image:
    w, h = size
    fx, fy, fw, fh = face
    cx = fx + fw / 2.0
    cy = fy + fh / 2.0 + fh * shift_y
    rx = fw * grow_w / 2.0
    ry = fh * grow_h / 2.0

    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse(
        (cx - rx, cy - ry, cx + rx, cy + ry), fill=255)
    blur = max(1, int(ry * 2 * feather))
    return mask.filter(ImageFilter.GaussianBlur(blur))


def calibrate(pairs) -> None:
    """Skriv ut hvilke faktorer de manuelle maskene faktisk tilsvarer."""
    for image_path, mask_path in pairs:
        face = detect_face(image_path)
        if not face:
            print("%-44s INGEN ANSIKT FUNNET" % os.path.basename(image_path))
            continue
        a = np.array(Image.open(mask_path).convert("L"))
        ys, xs = np.where(a > 32)
        mw = xs.max() - xs.min()
        mh = ys.max() - ys.min()
        mcx = (xs.max() + xs.min()) / 2.0
        mcy = (ys.max() + ys.min()) / 2.0
        fx, fy, fw, fh = face
        print("%-30s face=(%4.0f,%4.0f,%4.0f,%4.0f)  grow_w=%.2f grow_h=%.2f "
              "shift_x=%+.2f shift_y=%+.2f  dekning=%.4f"
              % (os.path.basename(image_path), fx, fy, fw, fh,
                 mw / fw, mh / fh,
                 (mcx - (fx + fw / 2)) / fw,
                 (mcy - (fy + fh / 2)) / fh,
                 (a > 32).mean()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image")
    ap.add_argument("--out")
    ap.add_argument("--grow-w", type=float, default=GROW_W)
    ap.add_argument("--grow-h", type=float, default=GROW_H)
    ap.add_argument("--shift-y", type=float, default=SHIFT_Y)
    ap.add_argument("--calibrate", nargs="*",
                    help="par av <bilde> <maske>")
    args = ap.parse_args()

    if args.calibrate:
        vals = args.calibrate
        calibrate(list(zip(vals[0::2], vals[1::2])))
        return 0

    if not args.image or not args.out:
        ap.error("--image og --out kreves")

    face = detect_face(args.image)
    if not face:
        print("fant ingen ansikt i", args.image)
        return 1
    src = Image.open(args.image)
    mask = build_mask(src.size, face, args.grow_w, args.grow_h, args.shift_y)
    mask.convert("RGB").save(args.out)
    a = np.array(mask)
    ys, xs = np.where(a > 32)
    print("%s  ansikt=(%.0f,%.0f,%.0f,%.0f)  maske=%dx%d  dekning=%.4f"
          % (os.path.basename(args.out), *face,
             xs.max() - xs.min(), ys.max() - ys.min(), (a > 32).mean()))
    return 0


if __name__ == "__main__":
    sys.exit(main())

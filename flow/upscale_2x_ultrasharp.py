"""
2x-oppskalering av ferdige sidebilder, med samme modell som workflowen bruker
(4x-UltraSharp) og en Lanczos-halvering etterpa. Gir renere kanter enn en ren
2x-modell, og teksturen matcher sidene ComfyUI selv leverer.

  python upscale_2x_ultrasharp.py --src "<mappe>" --out "<mappe>"

Kilde 4096x2048 -> 8192x4096, som er formatet innersidene har i input/.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import torch
from PIL import Image

# Stien til DreamPage-roten utledes, den hardkodes ikke: koden kjoerer paa
# Windows i dag og paa Linux paa nye maskiner. Se flow/paths.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import under  # noqa: E402

Image.MAX_IMAGE_PIXELS = None

MODEL = under("models/upscale_models/4x-UltraSharp.pth")
TILE = 512          # kildepiksler per rute
OVERLAP = 32        # kildepiksler som beregnes ekstra og kastes


def load_model(device: torch.device):
    from spandrel import ModelLoader
    model = ModelLoader().load_from_file(MODEL)
    net = model.model.eval().to(device)
    if device.type == "cuda":
        net = net.half()
    return net, model.scale


def upscale(img: Image.Image, net, scale: int, device: torch.device) -> Image.Image:
    src = np.asarray(img.convert("RGB"), dtype=np.uint8)
    h, w = src.shape[:2]
    out = np.zeros((h * scale // 2, w * scale // 2, 3), dtype=np.uint8)

    for y in range(0, h, TILE):
        for x in range(0, w, TILE):
            th, tw = min(TILE, h - y), min(TILE, w - x)
            y0, y1 = max(0, y - OVERLAP), min(h, y + th + OVERLAP)
            x0, x1 = max(0, x - OVERLAP), min(w, x + tw + OVERLAP)

            tile = src[y0:y1, x0:x1].astype(np.float32) / 255.0
            t = torch.from_numpy(tile).permute(2, 0, 1).unsqueeze(0).to(device)
            if device.type == "cuda":
                t = t.half()
            with torch.no_grad():
                up = net(t)
            up = up.float().clamp(0, 1).squeeze(0).permute(1, 2, 0).cpu().numpy()

            # klipp bort marginen i 4x-domenet, sa bare kjernen limes inn
            top, left = (y - y0) * scale, (x - x0) * scale
            core = up[top:top + th * scale, left:left + tw * scale]
            core = (core * 255.0 + 0.5).astype(np.uint8)

            half = Image.fromarray(core).resize(
                (tw * scale // 2, th * scale // 2), Image.LANCZOS)
            out[y * scale // 2:(y + th) * scale // 2,
                x * scale // 2:(x + tw) * scale // 2] = np.asarray(half)

            del t, up
    if device.type == "cuda":
        torch.cuda.empty_cache()
    return Image.fromarray(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    net, scale = load_model(device)
    print(f"modell 4x-UltraSharp (scale {scale}) pa {device}")

    os.makedirs(args.out, exist_ok=True)
    names = sorted(
        (n for n in os.listdir(args.src) if n.lower().endswith(".png")),
        key=lambda n: (len(n), n))

    for name in names:
        img = Image.open(os.path.join(args.src, name))
        dst = os.path.join(args.out, name)
        res = upscale(img, net, scale, device)
        res.save(dst, "PNG", compress_level=6)
        print(f"  {name}  {img.size[0]}x{img.size[1]} -> {res.size[0]}x{res.size[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

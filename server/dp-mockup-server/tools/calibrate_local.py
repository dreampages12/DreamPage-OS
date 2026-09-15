"""Lokal kalibrering av en bok-mockup-PSD - uten nettleser, uten Photopea.

Virker naar coveret legges paa som et FLATT LAG (ikke redigert smart object),
og lagene over/under bruker blandingsmoduser som er affine i coverkanalen.
For 05-Free-Square-Book-Mockup.psd er stakken:

    Main Image   normal        (den hvite boka)          -> Bse
    Layer 1      multiply      (her havner coveret)      -> Bse * c/255
    Highlight    screen  50%   (glans over)              -> S(x)

    S(x) = x + k*(screen(x,HL) - x),  k = opacity * alpha
         = x*(1 - k*HL/255) + k*HL              <- affin i x

    => black = S(0)   = k*HL
       white = S(Bse) = Bse*(1 - k*HL/255) + k*HL

`white` verifiseres mot en ekte psd-tools-komposisjon med coverlaget skjult
(multiply med hvitt er identitet). Treffer de ikke, er antakelsen feil og
kalibreringen avvises - da maa Photopea-veien brukes i stedet.

Bruk:
  python calibrate_local.py --psd <fil> --cover-layer "Layer 1" \
      --highlight-layer "Highlight" --out <mappe> [--max-error 2.0]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")

import numpy as np
from psd_tools import PSDImage

UV_OUTSIDE = 65535
MAP_FORMAT_VERSION = 2


def find_layer(container, name):
    for layer in container:
        if layer.name == name:
            return layer
        if layer.is_group():
            hit = find_layer(layer, name)
            if hit is not None:
                return hit
    return None


def composite_rgba(psd, hidden):
    """Komposisjon med et sett lag skjult. Returnerer uint8 RGBA."""
    hidden_ids = {id(x) for x in hidden}
    img = psd.composite(layer_filter=lambda l: l.visible and id(l) not in hidden_ids)
    return np.array(img.convert("RGBA"), dtype=np.uint8)


def layer_rgba_on_canvas(layer, width, height):
    """Legg et lags piksler inn paa dokumentflaten. Returnerer (rgb, alpha)."""
    arr = layer.numpy()  # H x W x C, float 0..1
    if arr is None:
        raise SystemExit(f"laget {layer.name!r} har ingen piksler")
    x0, y0, x1, y1 = layer.bbox
    rgb = np.zeros((height, width, 3), dtype=np.float64)
    alpha = np.zeros((height, width), dtype=np.float64)
    h = min(y1, height) - y0
    w = min(x1, width) - x0
    rgb[y0:y0 + h, x0:x0 + w] = arr[:h, :w, :3] * 255.0
    if arr.shape[2] >= 4:
        alpha[y0:y0 + h, x0:x0 + w] = arr[:h, :w, 3]
    else:
        alpha[y0:y0 + h, x0:x0 + w] = 1.0
    return rgb, alpha


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--psd", required=True)
    ap.add_argument("--cover-layer", required=True)
    ap.add_argument("--highlight-layer", default="Highlight")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-error", type=float, default=2.0,
                    help="hoyeste tillatte gjennomsnittsavvik (0-255)")
    ap.add_argument("--cover-space", type=int, default=0,
                    help="oppl. coveret samples i (0 = bruk lagets egen bredde)")
    ap.add_argument("--hide-layers", default="",
                    help="kommaseparerte lag som skjules, f.eks. studiobakgrunnen. "
                         "Skyggen overlever paa gjennomsiktig bakgrunn og kan da "
                         "legges rett paa en hvilken som helst side.")
    ap.add_argument("--crop", action="store_true",
                    help="beskjaer til synlig innhold (mindre kart, raskere render)")
    ap.add_argument("--crop-margin", type=int, default=8)
    ap.add_argument("--shadow-strength", type=float, default=1.0,
                    help="skaler slagskyggen (alfa utenfor bokflaten). 1.0 = som i "
                         "PSD-en, lavere gir en mer diskret skygge paa siden.")
    ap.add_argument("--feather", type=int, default=0,
                    help="mykne alfa mot ytterkanten (piksler). Hindrer en hard "
                         "linje der beskjaeringen kutter gjennom slagskyggen.")
    ap.add_argument("--crop-alpha", type=int, default=6,
                    help="alfaterskel for beskjaering. Hev den for aa kutte den ytre, "
                         "nesten usynlige delen av slagskyggen slik at motivet fyller mer.")
    ap.add_argument("--calib-version", type=int, default=4)
    ap.add_argument("--neutralize-alpha", action="store_true",
                    help="trekk fra den flate bakgrunnshinnen et heldekkende "
                         "skyggelag legger igjen naar studiobakgrunnen skjules")
    args = ap.parse_args()

    t0 = time.time()
    psd = PSDImage.open(args.psd)
    W, H = psd.width, psd.height
    print(f"[KALIB] dokument {W}x{H}, {psd.depth}-bit", flush=True)

    cover_layer = find_layer(psd, args.cover_layer)
    if cover_layer is None:
        raise SystemExit(f"fant ikke coverlaget {args.cover_layer!r}")
    hl_layer = find_layer(psd, args.highlight_layer)

    x0, y0, x1, y1 = cover_layer.bbox
    print(f"[KALIB] coverflate: x {x0}-{x1}  y {y0}-{y1}  "
          f"({x1 - x0}x{y1 - y0})", flush=True)

    extra_hidden = []
    for name in [n.strip() for n in args.hide_layers.split(",") if n.strip()]:
        layer = find_layer(psd, name)
        if layer is None:
            print(f"[KALIB] ADVARSEL: fant ikke laget {name!r} - hopper over")
        else:
            extra_hidden.append(layer)
    if extra_hidden:
        print("[KALIB] skjuler: " + ", ".join(l.name for l in extra_hidden), flush=True)

    # --- hvitt: coverlaget skjult (multiply med hvitt = identitet) ---
    white_rgba = composite_rgba(psd, [cover_layer] + extra_hidden)
    white = white_rgba[:, :, :3].astype(np.float64)
    alpha_doc = white_rgba[:, :, 3]
    print(f"[KALIB] hvitt-render ferdig ({time.time() - t0:.0f}s)", flush=True)

    # --- basis uten glans, for aa verifisere modellen ---
    hidden = [cover_layer] + extra_hidden + ([hl_layer] if hl_layer is not None else [])
    base = composite_rgba(psd, hidden)[:, :, :3].astype(np.float64)
    print(f"[KALIB] basis-render ferdig ({time.time() - t0:.0f}s)", flush=True)

    # --- glansleddet k*HL ---
    if hl_layer is not None:
        hl_rgb, hl_a = layer_rgba_on_canvas(hl_layer, W, H)
        k = (hl_layer.opacity / 255.0) * hl_a
        k = k[:, :, None]
        khl = k * hl_rgb
        white_pred = base * (1.0 - khl / 255.0) + khl
    else:
        khl = np.zeros_like(base)
        white_pred = base

    # --- verifiser modellen mot fasit ---
    inside = np.zeros((H, W), dtype=bool)
    inside[y0:y1, x0:x1] = True
    solid = (alpha_doc >= 250) & inside
    err = np.abs(white_pred - white)[solid]
    mean_err = float(err.mean()) if err.size else 0.0
    p99 = float(np.percentile(err, 99)) if err.size else 0.0
    print(f"[KALIB] modellsjekk paa coverflaten: mean={mean_err:.3f} "
          f"p99={p99:.2f} max={float(err.max()) if err.size else 0:.1f}", flush=True)

    if mean_err > args.max_error:
        print(f"[KALIB] AVVIST: avviket er over {args.max_error}. Stakken er ikke "
              f"affin i coverkanalen - bruk Photopea-veien for denne PSD-en.",
              file=sys.stderr)
        return 2

    # --- svart: S(0) = k*HL, kun paa coverflaten ---
    black = white.copy()
    black[inside] = np.clip(khl, 0, 255)[inside]

    # --- uv: akse-alignert rektangel over coverflaten ---
    uvx = np.full((H, W), UV_OUTSIDE, dtype=np.uint16)
    uvy = np.full((H, W), UV_OUTSIDE, dtype=np.uint16)
    xs = np.linspace(0, 65534, x1 - x0, dtype=np.float64)
    ys = np.linspace(0, 65534, y1 - y0, dtype=np.float64)
    uvx[y0:y1, x0:x1] = xs[None, :].astype(np.uint16)
    uvy[y0:y1, x0:x1] = ys[:, None].astype(np.uint16)

    # --- nullstill den flate bakgrunnshinnen ---
    # Skyggelaget i denne PSD-en bruker linear burn og dekker HELE lerretet.
    # Naar studiobakgrunnen skjules, legger det igjen en jevn halvgjennomsiktig
    # hinne (typisk alpha ~44) ogsaa der det ikke er noen skygge. Vi maaler
    # hinnen langs ytterkanten og trekker den fra, saa tomrommet blir helt
    # gjennomsiktig mens skyggens gradient beholdes.
    bg_alpha = 0
    if args.neutralize_alpha:
        frame = np.concatenate([
            alpha_doc[0, :], alpha_doc[-1, :], alpha_doc[:, 0], alpha_doc[:, -1],
        ])
        bg_alpha = int(np.median(frame))
        if bg_alpha > 0:
            a = alpha_doc.astype(np.float64)
            a = (a - bg_alpha) / max(1.0, 255.0 - bg_alpha) * 255.0
            alpha_doc = np.clip(a, 0, 255).astype(np.uint8)
            print(f"[KALIB] bakgrunnshinne fjernet: alpha {bg_alpha} -> 0 "
                  f"(helt gjennomsiktig: {100 * (alpha_doc == 0).mean():.1f}% av flaten)",
                  flush=True)
        else:
            print("[KALIB] ingen bakgrunnshinne aa fjerne", flush=True)

    # --- beskjaer til synlig innhold ---
    crop_box = [0, 0, W, H]
    if args.crop:
        vis = np.where(alpha_doc > args.crop_alpha)
        if vis[0].size:
            m = args.crop_margin
            cy0 = max(0, int(vis[0].min()) - m)
            cy1 = min(H, int(vis[0].max()) + 1 + m)
            cx0 = max(0, int(vis[1].min()) - m)
            cx1 = min(W, int(vis[1].max()) + 1 + m)
            crop_box = [cx0, cy0, cx1, cy1]
            white = white[cy0:cy1, cx0:cx1]
            black = black[cy0:cy1, cx0:cx1]
            alpha_doc = alpha_doc[cy0:cy1, cx0:cx1]
            uvx = uvx[cy0:cy1, cx0:cx1]
            uvy = uvy[cy0:cy1, cx0:cx1]
            H, W = white.shape[0], white.shape[1]
            x0, y0, x1, y1 = x0 - cx0, y0 - cy0, x1 - cx0, y1 - cy0
            print(f"[KALIB] beskaaret til {W}x{H} "
                  f"(x {cx0}-{cx1}, y {cy0}-{cy1})", flush=True)

    # Der coveret ikke paavirker noe, la uv staa som "utenfor".
    dead = np.abs(white - black).max(axis=2) <= 6
    uvx[dead] = UV_OUTSIDE
    uvy[dead] = UV_OUTSIDE

    # --- demp slagskyggen ---
    # PSD-ens skygge er laget for en graa studiobakgrunn og blir en synlig dis
    # paa en hvit bokside. Vi skalerer bare alfa UTENFOR bokflaten, saa selve
    # boka staar urort.
    if args.shadow_strength != 1.0:
        # `inside` maa regnes paa nytt her: beskjaeringen har allerede flyttet
        # bokrektangelet og endret lerretstoerrelsen.
        book = np.zeros((H, W), dtype=bool)
        book[max(0, y0):min(H, y1), max(0, x0):min(W, x1)] = True
        outside = ~book
        a = alpha_doc.astype(np.float64)
        a[outside] *= max(0.0, args.shadow_strength)
        alpha_doc = np.clip(a, 0, 255).astype(np.uint8)
        print(f"[KALIB] slagskygge skalert til {args.shadow_strength:g}", flush=True)

    # --- mykne ytterkanten ---
    # Beskjaeringen gaar uansett terskel tvers gjennom slagskyggen et sted.
    # Uten mykning blir det en synlig rett kant paa siden. Med den toner
    # skyggen ut til null over de ytterste pikslene.
    if args.feather > 0:
        f = min(args.feather, H // 2, W // 2)
        ramp_y = np.ones(H)
        ramp_x = np.ones(W)
        edge = np.linspace(0.0, 1.0, f)
        ramp_y[:f] = edge
        ramp_y[-f:] = edge[::-1]
        ramp_x[:f] = edge
        ramp_x[-f:] = edge[::-1]
        mask = np.minimum(ramp_y[:, None], ramp_x[None, :])
        # Mykningen skal BARE gjelde skyggen. Ligger bokflaten naer kanten av
        # utsnittet, ville den ellers blitt tonet halvt bort - det gir en lys
        # stripe langs bokas kant.
        mask[max(0, y0):min(H, y1), max(0, x0):min(W, x1)] = 1.0
        alpha_doc = (alpha_doc.astype(np.float64) * mask).astype(np.uint8)
        print(f"[KALIB] ytterkant myknet over {f} px", flush=True)

    cover_space = args.cover_space or (x1 - x0)
    os.makedirs(args.out, exist_ok=True)
    uvx.tofile(os.path.join(args.out, "uvx.u16"))
    uvy.tofile(os.path.join(args.out, "uvy.u16"))
    np.clip(white, 0, 255).astype(np.uint8).tofile(os.path.join(args.out, "white.rgb"))
    np.clip(black, 0, 255).astype(np.uint8).tofile(os.path.join(args.out, "black.rgb"))
    alpha_doc.tofile(os.path.join(args.out, "alpha.u8"))

    meta = {
        "formatVersion": MAP_FORMAT_VERSION,
        "width": int(W),
        "height": int(H),
        "source": "psd-local",
        "calibrationVersion": args.calib_version,
        "layerName": args.cover_layer,
        "highlightLayer": args.highlight_layer if hl_layer is not None else None,
        "coverRect": [int(x0), int(y0), int(x1), int(y1)],
        "cropBox": [int(v) for v in crop_box],
        "bgAlphaRemoved": int(bg_alpha),
        "coverSpace": {"width": int(cover_space), "height": int(cover_space)},
        "influenceRatio": float((~dead).mean()),
        "validation": {
            "model": {"mean": mean_err, "p99": p99,
                      "max": float(err.max()) if err.size else 0.0,
                      "samples": int(err.size)}
        },
        "accepted": True,
        "calibratedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(os.path.join(args.out, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)

    print(f"[KALIB] ferdig paa {time.time() - t0:.0f}s -> {args.out}", flush=True)
    print(f"[KALIB] paavirket flate: {100 * (~dead).mean():.1f}% av siden", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

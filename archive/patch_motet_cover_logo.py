# -*- coding: utf-8 -*-
"""Bruk logo som linje 2 paa forsiden i motet-i-hjertet-scriptene.

Linje 1 (navn) tegnes fortsatt som tekst og oversettes som for. Linje 2 var
tekst ("Motet I Hjertet") og blir naa et logo-bilde fra script/logo/<locale>.

Vi har foreloepig BARE en norsk logo. Derfor faller funksjonen tilbake til den
gamle tekst-varianten naar det ikke finnes logo for spraaket - ellers ville den
engelske og svenske boka faatt en norsk tittel trykt paa forsiden. Legges
motet-logo-en.png / motet-logo-sv.png inn senere, slaar de inn av seg selv.

  python patch_motet_cover_logo.py --dry-run
  python patch_motet_cover_logo.py --apply
"""
from __future__ import annotations

import argparse
import ast
import io
import shutil
import sys
from datetime import datetime

FILES = [
    "C:/ComfyUI/script/nb/motet-i-hjertet-text-nb.py",
    "C:/ComfyUI/script/nn/motet-i-hjertet-text-nn.py",
    "C:/ComfyUI/script/en-US/motet-i-hjertet-text-en-US.py",
    "C:/ComfyUI/script/en-GB/motet-i-hjertet-text-en-GB.py",
    "C:/ComfyUI/script/sv/motet-i-hjertet-text-sv.py",
]

OLD_SIG = "def draw_centered_title_cover(img, text):"
NEW_SIG = "def _draw_title_cover_text(img, text):"
ANCHOR = "def draw_gradient_word(img, draw, text, x, y, font, colors, shadow):"

LOGO_CONST = 'LOGO_DIR = os.path.join(SCRIPT_ROOT_DIR, "logo", SCRIPT_LOCALE)'
LOGO_ANCHOR = 'COVER_FONT     = os.path.join(SCRIPT_DIR, "PlayfairDisplay.ttf")'

BLOCK = '''
# ---------------------------------------------------------------------------
#  FORSIDE-TITTEL - navn som tekst + Motet i Hjertet-logo som linje 2
# ---------------------------------------------------------------------------
FRONT_COVER_LOGO_SCALE = 0.78
FRONT_COVER_LOGO_X_OFFSET = 0
FRONT_COVER_TOP_MARGIN = 0.03
FRONT_COVER_LINE_SPACING = 0.04
FRONT_COVER_LINE1_SIZE = 81 / 1024          # andel av kortsiden
FRONT_COVER_GOLD = ((255, 255, 255), (255, 255, 255))
FRONT_COVER_SHADOW = (60, 35, 70)


def _crop_logo_to_visible_alpha(logo_img, alpha_threshold=8):
    logo_rgba = logo_img.convert("RGBA")
    bbox = logo_rgba.getchannel("A").point(
        lambda a: 255 if a > alpha_threshold else 0).getbbox()
    return logo_rgba.crop(bbox) if bbox else logo_rgba


def resolve_front_cover_logo():
    """Logo for gjeldende spraak, eller None hvis den ikke finnes.

    None betyr med vilje "tegn linje 2 som tekst" - en norsk logo skal aldri
    havne paa en engelsk eller svensk bok.
    """
    name = {
        "nb": "motet-logo-nb.png",
        "nn": "motet-logo-nb.png",
        "en-US": "motet-logo-en.png",
        "en-GB": "motet-logo-en.png",
        "sv": "motet-logo-sv.png",
    }.get(SCRIPT_LOCALE, "motet-logo-nb.png")
    path = os.path.join(LOGO_DIR, name)
    if os.path.exists(path):
        return path
    print("[FORSIDE] Fant ingen logo for", SCRIPT_LOCALE, "- linje 2 tegnes som tekst")
    return None


def draw_centered_title_cover(img, text, base_dir=None):
    logo_path = resolve_front_cover_logo()
    if not logo_path:
        _draw_title_cover_text(img, text)
        return

    draw = ImageDraw.Draw(img)
    w, h = img.size
    base = min(w, h)

    line1 = text.split("\\n")[0] if text else ""
    font_small = ImageFont.truetype(COVER_FONT, int(base * FRONT_COVER_LINE1_SIZE))
    shadow_offset = max(3, int(font_small.size * 0.04))

    def _mask(x, y, t, fnt):
        m = Image.new("L", img.size, 0)
        ImageDraw.Draw(m).text((x, y), t, font=fnt, fill=255)
        return m

    def _gradient(mask, bbox, top, bottom):
        x0, y0, x1, y1 = bbox
        grad = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(grad)
        height = max(1, y1 - y0)
        for i in range(y0, y1):
            t = (i - y0) / height
            d.line([(x0, i), (x1, i)], fill=(
                int(top[0] + (bottom[0] - top[0]) * t),
                int(top[1] + (bottom[1] - top[1]) * t),
                int(top[2] + (bottom[2] - top[2]) * t),
                255,
            ))
        img.paste(grad, (0, 0), mask)

    bbox1 = draw.textbbox((0, 0), line1, font=font_small)
    w1, h1 = bbox1[2] - bbox1[0], bbox1[3] - bbox1[1]
    y1_pos = int(h * FRONT_COVER_TOP_MARGIN)
    x1_pos = (w - w1) // 2

    if line1:
        sm = _mask(x1_pos + shadow_offset, y1_pos + shadow_offset, line1, font_small)
        sm = sm.filter(ImageFilter.GaussianBlur(max(1, shadow_offset // 2)))
        img.paste((*FRONT_COVER_SHADOW, 255), (0, 0), sm)
        tm = _mask(x1_pos, y1_pos, line1, font_small)
        _gradient(tm, draw.textbbox((x1_pos, y1_pos), line1, font=font_small),
                  FRONT_COVER_GOLD[0], FRONT_COVER_GOLD[1])

    logo = _crop_logo_to_visible_alpha(Image.open(logo_path).convert("RGBA"))
    target_w = int(w * FRONT_COVER_LOGO_SCALE)
    target_h = int(logo.height * (target_w / logo.width))
    logo = logo.resize((target_w, target_h), Image.LANCZOS)

    descender_cut = int(h1 * 0.15) if h1 else 0
    y2_pos = y1_pos + h1 - descender_cut + int(h * FRONT_COVER_LINE_SPACING)
    lx = max(0, min(w - target_w,
                    ((w - target_w) // 2) + FRONT_COVER_LOGO_X_OFFSET))

    shadow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow_img = Image.new("RGBA", (target_w, target_h), (*FRONT_COVER_SHADOW, 180))
    shadow_img.putalpha(logo.split()[3])
    shadow_layer.paste(shadow_img, (lx + shadow_offset, y2_pos + shadow_offset))
    shadow_layer = shadow_layer.filter(
        ImageFilter.GaussianBlur(max(8, int(target_h * 0.20))))
    img.alpha_composite(shadow_layer)
    img.alpha_composite(logo, (lx, y2_pos))


'''


def patch(src: str) -> str:
    if "def _draw_title_cover_text" in src:
        return src                                     # allerede patchet
    if OLD_SIG not in src:
        raise SystemExit("fant ikke draw_centered_title_cover - nekter aa gjette")
    if ANCHOR not in src:
        raise SystemExit("fant ikke ankeret draw_gradient_word")

    src = src.replace(OLD_SIG, NEW_SIG, 1)
    if LOGO_CONST not in src:
        src = src.replace(LOGO_ANCHOR, LOGO_ANCHOR + "\n" + LOGO_CONST, 1)
    return src.replace(ANCHOR, BLOCK.lstrip("\n") + ANCHOR, 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not (args.apply or args.dry_run):
        ap.error("velg --dry-run eller --apply")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for path in FILES:
        src = io.open(path, encoding="utf-8").read()
        out = patch(src)
        ast.parse(out)
        print(f"  {path.split('/')[-1]}: endret={out != src}")
        if args.apply and out != src:
            shutil.copy(path, f"{path}.backup-coverlogo-{stamp}")
            io.open(path, "w", encoding="utf-8", newline="\n").write(out)
    print("SKREVET" if args.apply else "TORRKJORING")
    return 0


if __name__ == "__main__":
    sys.exit(main())

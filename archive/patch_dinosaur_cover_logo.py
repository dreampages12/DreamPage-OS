# -*- coding: utf-8 -*-
"""Ny forside + mykere bakside-skygge for dinosaurenes-dal.

To ting skjer i alle fem locale-scriptene (dinosaur-text-<locale>.py):

1. FORSIDE. `draw_centered_title_cover` blir styrt av modul-konstanter i
   stedet for hardkodede tall, og nb faar "Dinosaurenes Dal"-logoen som
   linje 2. Verdiene er hentet rett fra "dinosaur"-noden i DP Title Tester
   (n8n-workflow 1BqeGkXyjbUBsR9N), som er der brukeren tuner forsider:
   hvit linje 1 i Trebuchet MS Bold, moerk halo bak den, logo paa 80 % av
   coverbredden.

   Bare nb faar logoen. Logografikken sier "Dinosaurenes Dal", og det er
   bokmaal - nn-tittelen er "Dinosaurdalen" og en/sv har sine egne titler,
   saa de tegner fortsatt linje 2 som tekst. nn arver resten av det nye
   nb-utseendet (font, farge, halo) siden de to norske utgavene skal se like
   ut; en/sv beholder sin varme gull-gradient, som er det som er tunet for
   dem i EN-/SV-nodene.

   en-GB laa igjen paa de gamle generiske nb-verdiene og blir satt lik
   en-US, som er der EN-tuningen faktisk ligger.

2. BAKSIDE-SKYGGE. `draw_text_backdrop` faar `shape`-argumentet fra
   motet-i-hjertet, og bakside-grenen kaller den med shape="block". I dag
   tegner dinosaur-baksiden en "strong" pille per linje - synlige moerke
   kanter. shape="block" slaar linjene sammen til ETT felt, dropper den
   crispe platen og blurrer skyggen kraftig, saa det blir en myk sky uten
   kant. Det er noeyaktig samme logikk som motet-i-hjertet bruker.

  python patch_dinosaur_cover_logo.py --dry-run
  python patch_dinosaur_cover_logo.py --apply
"""
from __future__ import annotations

import argparse
import os
import re
import sys

LOCALES = ["nb", "nn", "en-US", "en-GB", "sv"]


def path_for(locale: str) -> str:
    return "C:/ComfyUI/script/%s/dinosaur-text-%s.py" % (locale, locale)


# ---------------------------------------------------------------------------
#  1a. Forside-konstanter per locale
# ---------------------------------------------------------------------------
# Font-stoerrelsene er andeler av kortsiden fordi Title Tester tuner mot et
# 1024px cover, mens de ferdige sidene rendres i full opploesning.

NB_STYLE = """FRONT_COVER_LINE1_SIZE = 90 / 1024
FRONT_COVER_LINE2_SIZE = 120 / 1024
FRONT_COVER_GOLD = ((255, 255, 255), (255, 255, 255))
FRONT_COVER_SHADOW = (15, 35, 65)
FRONT_COVER_TOP_MARGIN = 0.045
FRONT_COVER_LINE_SPACING = 0.010
FRONT_COVER_LINE1_FONT = os.path.join(SCRIPT_ROOT_DIR, "pre", "Trebuchet MS Bold.ttf")
FRONT_COVER_LINE2_FONT = os.path.join(SCRIPT_ROOT_DIR, "pre", "Fredoka-Bold.ttf")
FRONT_COVER_GLOW_COLOR = (10, 25, 20)
FRONT_COVER_GLOW_OPACITY = 0.9
FRONT_COVER_GLOW_RADIUS_SCALE = 0.30
FRONT_COVER_LOGO_SCALE = 0.80
FRONT_COVER_LOGO_X_OFFSET = 0
"""

EN_STYLE = """FRONT_COVER_LINE1_SIZE = 89 / 1024
FRONT_COVER_LINE2_SIZE = 97 / 1024
FRONT_COVER_GOLD = ((245, 232, 205), (160, 130, 80))
FRONT_COVER_SHADOW = (45, 30, 18)
FRONT_COVER_TOP_MARGIN = 0.057
FRONT_COVER_LINE_SPACING = 0.024
FRONT_COVER_LINE1_FONT = None
FRONT_COVER_LINE2_FONT = None
FRONT_COVER_GLOW_COLOR = None
FRONT_COVER_GLOW_OPACITY = 0.9
FRONT_COVER_GLOW_RADIUS_SCALE = 0.30
FRONT_COVER_LOGO_SCALE = 0.80
FRONT_COVER_LOGO_X_OFFSET = 0
"""

SV_STYLE = """FRONT_COVER_LINE1_SIZE = 85 / 1024
FRONT_COVER_LINE2_SIZE = 96 / 1024
FRONT_COVER_GOLD = ((245, 232, 205), (160, 130, 80))
FRONT_COVER_SHADOW = (45, 30, 18)
FRONT_COVER_TOP_MARGIN = 0.057
FRONT_COVER_LINE_SPACING = 0.015
FRONT_COVER_LINE1_FONT = None
FRONT_COVER_LINE2_FONT = None
FRONT_COVER_GLOW_COLOR = None
FRONT_COVER_GLOW_OPACITY = 0.9
FRONT_COVER_GLOW_RADIUS_SCALE = 0.30
FRONT_COVER_LOGO_SCALE = 0.80
FRONT_COVER_LOGO_X_OFFSET = 0
"""

STYLE = {
    "nb": NB_STYLE,
    "nn": NB_STYLE,
    "en-US": EN_STYLE,
    "en-GB": EN_STYLE,
    "sv": SV_STYLE,
}

# Bare bokmaal har en logo. None = tegn linje 2 som tekst.
LOGO_NAME = {
    "nb": '"dinosaurenes-dal-logo-nb.png"',
    "nn": "None",
    "en-US": "None",
    "en-GB": "None",
    "sv": "None",
}


def cover_block(locale: str) -> str:
    return '''
# ---------------------------------------------------------------------------
#  FORSIDE-TITTEL
#  Verdiene speiler "dinosaur"-noden i DP Title Tester (n8n).
# ---------------------------------------------------------------------------
LOGO_DIR = os.path.join(SCRIPT_ROOT_DIR, "logo", SCRIPT_LOCALE)

''' + STYLE[locale] + '''
# Logoen finnes bare paa bokmaal. None betyr med vilje "tegn linje 2 som
# tekst" - en norsk logo skal aldri havne paa en nynorsk, engelsk eller
# svensk forside naar tittelen deres er en annen.
FRONT_COVER_LOGO_NAME = ''' + LOGO_NAME[locale] + '''


def _front_cover_font(path, size):
    """Fonten fra Title Tester, eller COVER_FONT hvis den ikke finnes."""
    if path and os.path.exists(path):
        return ImageFont.truetype(path, size)
    return ImageFont.truetype(COVER_FONT, size)


def resolve_front_cover_logo():
    if not FRONT_COVER_LOGO_NAME:
        return None
    path = os.path.join(LOGO_DIR, FRONT_COVER_LOGO_NAME)
    if os.path.exists(path):
        return path
    print("[FORSIDE] Fant ingen logo i", path, "- linje 2 tegnes som tekst")
    return None


def _crop_logo_to_visible(logo_img):
    """Samme beskjaering som render-title-line2logo.py.

    getbbox() alene tar med den myke glorien rundt bokstavene, saa rader med
    under 2 % dekning trimmes bort i tillegg. Uten det ville logoen bli
    skalert ned for aa gi plass til tom luft.
    """
    logo = logo_img.convert("RGBA")
    bbox = logo.getbbox()
    if bbox:
        logo = logo.crop(bbox)

    lw, lh = logo.size
    pixels = logo.load()
    threshold = max(1, lw * 2 // 100)

    top_trim = 0
    for row in range(lh):
        if sum(1 for x in range(lw) if pixels[x, row][3] > 10) >= threshold:
            break
        top_trim = row + 1

    bottom_trim = lh
    for row in range(lh - 1, -1, -1):
        if sum(1 for x in range(lw) if pixels[x, row][3] > 10) >= threshold:
            break
        bottom_trim = row

    if top_trim > 0 or bottom_trim < lh:
        logo = logo.crop((0, top_trim, lw, bottom_trim))
    return logo


def draw_centered_title_cover(img, text):
    """Linje 1 som tekst, linje 2 som logo (nb) eller tekst (resten)."""
    draw = ImageDraw.Draw(img)
    w, h = img.size
    base = min(w, h)

    lines = (text or "").split("\\n")
    line1 = lines[0] if len(lines) > 0 else ""
    line2 = lines[1] if len(lines) > 1 else ""

    font_small = _front_cover_font(FRONT_COVER_LINE1_FONT,
                                   max(1, int(base * FRONT_COVER_LINE1_SIZE)))
    font_large = _front_cover_font(FRONT_COVER_LINE2_FONT,
                                   max(1, int(base * FRONT_COVER_LINE2_SIZE)))

    # Krymp til teksten faar plass. Titlene varierer mye i lengde mellom
    # spraakene, og en fast fontstoerrelse lot de lengste renne ut over
    # begge kantene. Gjelder bare tekst-varianten - logoen skaleres i bredde.
    FRONT_COVER_TEXT_MAX_W = 0.90

    def _fit(line, fnt, path):
        if not line:
            return fnt
        limit = int(w * FRONT_COVER_TEXT_MAX_W)
        size = fnt.size
        while size > 8:
            bbox = draw.textbbox((0, 0), line, font=fnt)
            if bbox[2] - bbox[0] <= limit:
                break
            size -= 2
            fnt = _front_cover_font(path, size)
        return fnt

    font_small = _fit(line1, font_small, FRONT_COVER_LINE1_FONT)
    font_large = _fit(line2, font_large, FRONT_COVER_LINE2_FONT)

    size_large = int(base * 0.10)
    shadow_offset = max(3, int(size_large * 0.04))

    def _mask(x, y, t, fnt):
        m = Image.new("L", img.size, 0)
        ImageDraw.Draw(m).text((x, y), t, font=fnt, fill=255)
        return m

    def _paste_gradient(mask, bbox, top, bottom):
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

    def draw_line(t, fnt, x, y, glow=False):
        if not t:
            return
        # Moerk halo bak hvit tekst. Forsiden er lys og travel, og uten den
        # forsvinner navnet i illustrasjonen.
        if glow and FRONT_COVER_GLOW_COLOR:
            radius = max(18, int(fnt.size * FRONT_COVER_GLOW_RADIUS_SCALE))
            gm = _mask(x, y, t, fnt).filter(ImageFilter.GaussianBlur(radius))
            gm = gm.point(lambda p: int(p * FRONT_COVER_GLOW_OPACITY))
            glow_layer = Image.merge("RGBA", (
                Image.new("L", img.size, FRONT_COVER_GLOW_COLOR[0]),
                Image.new("L", img.size, FRONT_COVER_GLOW_COLOR[1]),
                Image.new("L", img.size, FRONT_COVER_GLOW_COLOR[2]),
                gm,
            ))
            img.alpha_composite(glow_layer)

        sm = _mask(x + shadow_offset, y + shadow_offset, t, fnt)
        sm = sm.filter(ImageFilter.GaussianBlur(max(1, shadow_offset // 2)))
        img.paste((*FRONT_COVER_SHADOW, 255), (0, 0), sm)

        tm = _mask(x, y, t, fnt)
        _paste_gradient(tm, draw.textbbox((x, y), t, font=fnt),
                        FRONT_COVER_GOLD[0], FRONT_COVER_GOLD[1])

    def text_size(t, f):
        if not t:
            return 0, 0
        bbox = draw.textbbox((0, 0), t, font=f)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    w1, h1 = text_size(line1, font_small)
    y1_pos = int(h * FRONT_COVER_TOP_MARGIN)
    x1_pos = (w - w1) // 2
    draw_line(line1, font_small, x1_pos, y1_pos, glow=True)

    descender_cut = int(h1 * 0.15) if h1 else 0
    y2_pos = y1_pos + h1 - descender_cut + int(h * FRONT_COVER_LINE_SPACING)

    logo_path = resolve_front_cover_logo()
    if not logo_path:
        w2, _ = text_size(line2, font_large)
        draw_line(line2, font_large, (w - w2) // 2, y2_pos)
        return

    logo = _crop_logo_to_visible(Image.open(logo_path))
    target_w = int(w * FRONT_COVER_LOGO_SCALE)
    target_h = max(1, int(logo.height * (target_w / logo.width)))
    logo = logo.resize((target_w, target_h), Image.LANCZOS)

    lx = max(0, min(w - target_w,
                    ((w - target_w) // 2) + FRONT_COVER_LOGO_X_OFFSET))

    shadow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow_img = Image.new("RGBA", (target_w, target_h),
                           (*FRONT_COVER_SHADOW, 255))
    shadow_img.putalpha(logo.split()[3])
    shadow_layer.paste(shadow_img, (lx + shadow_offset, y2_pos + shadow_offset))
    shadow_layer = shadow_layer.filter(
        ImageFilter.GaussianBlur(max(8, int(target_h * 0.20))))
    img.alpha_composite(shadow_layer)
    img.alpha_composite(logo, (lx, y2_pos))


'''


COVER_START = "def draw_centered_title_cover(img, text):"
COVER_END = "def draw_gradient_word(img, draw, text, x, y, font, colors, shadow):"


def patch_cover(src: str, locale: str) -> str:
    start = src.index(COVER_START)
    end = src.index(COVER_END, start)
    return src[:start] + cover_block(locale).lstrip("\n") + src[end:]


# ---------------------------------------------------------------------------
#  2. Bakside-skygge: shape-argumentet fra motet-i-hjertet
# ---------------------------------------------------------------------------

BACKDROP_SIG_OLD = (
    'def draw_text_backdrop(img, box, text, font, line_spacing, '
    'highlights=None, align="left", strength="normal"):'
)
BACKDROP_SIG_NEW = (
    'def draw_text_backdrop(img, box, text, font, line_spacing, '
    'highlights=None, align="left", strength="normal", shape="lines"):'
)

BOXES_OLD = """    drew = False
    for lb in line_boxes:
"""
BOXES_NEW = '''    if shape == "block":
        # Baksiden: EN myk sky bak hele bolken - ingen synlig kant.
        # Den crisp platen droppes (plate_alpha = 0); i stedet blurres
        # skyggen kraftig slik at den toner ut i illustrasjonen.
        pad_x = int(pad_x * 1.9)
        pad_y = int(pad_y * 2.4)
        plate_alpha = 0
        shadow_alpha = 110
        blur_amount = max(30, int(fs * 2.1))
        boxes = [(
            min(lb[0] for lb in line_boxes),
            min(lb[1] for lb in line_boxes),
            max(lb[2] for lb in line_boxes),
            max(lb[3] for lb in line_boxes),
        )]
    else:
        boxes = line_boxes

    drew = False
    for lb in boxes:
'''

RADIUS_OLD = """        radius = max(6, min((right - left) // 2, int((bottom - top) * 0.40)))
"""
RADIUS_NEW = """        if shape == "block":
            radius = max(24, int(fs * 0.9))
        else:
            radius = max(6, min((right - left) // 2, int((bottom - top) * 0.40)))
"""

# Kallet i bakside-grenen. Speiler motet-i-hjertet: shape="block" og
# text_backdrop-flagget respekteres (default paa, som i motet).
# Regex fordi kommentaren over kallet er skrevet med ae/oe i noen locales og
# med ae/oe-bokstaver i andre - selve kallet er identisk overalt.
CALL_RE = re.compile(
    r'[ \t]*# Baksiden er type "cover"(?:.|\n)*?'
    r'align="center", strength="strong",\n[ \t]*\)\n'
)
CALL_NEW = """            # Ett samlet felt bak hele bakside-teksten (ikke per linje).
            # Per-linje-pillene ga harde mørke kanter her; shape="block"
            # gir den samme myke skyen som motet-i-hjertet har.
            if block.get("text_backdrop", True):
                draw_text_backdrop(
                    img, box, block["text"], font, line_spacing,
                    highlights=block.get("highlights", []),
                    align="center", shape="block",
                    strength=block.get("text_backdrop_strength", "strong"),
                )
"""


def patch_backside(src: str) -> str:
    for old, new in (
        (BACKDROP_SIG_OLD, BACKDROP_SIG_NEW),
        (BOXES_OLD, BOXES_NEW),
        (RADIUS_OLD, RADIUS_NEW),
    ):
        if src.count(old) != 1:
            raise SystemExit("Fant %d treff (ventet 1) for:\n%s" % (src.count(old), old[:120]))
        src = src.replace(old, new)

    hits = CALL_RE.findall(src)
    if len(hits) != 1:
        raise SystemExit("Fant %d bakside-kall (ventet 1)" % len(hits))
    return CALL_RE.sub(lambda _m: CALL_NEW, src, count=1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.apply and not args.dry_run:
        ap.error("bruk --dry-run eller --apply")

    for locale in LOCALES:
        path = path_for(locale)
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        out = patch_backside(patch_cover(src, locale))
        compile(out, path, "exec")
        print("%-6s %+d tegn" % (locale, len(out) - len(src)))
        if args.apply:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(out)
    print("apply" if args.apply else "dry-run (ingen filer skrevet)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

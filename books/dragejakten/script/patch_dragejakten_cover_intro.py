# -*- coding: utf-8 -*-
"""Tre forbedringer i Dragejakten-tekstscriptene. Idempotent.

1. FORSIDE: linje 1 som tekst + Dragejakten-logoen som linje 2, med samme
   verdier som DP Title Tester-noden "Dragejakten" (glod, skygge, logo-skygge).
   en/sv har ingen egen logo og faller MED VILJE tilbake til ren tekst.
2. APNINGSSIDA (dreampage-first): mye svakere lys plate bak brodteksten,
   samme tekstboks som de andre bokene, og taglinen
   "Trykket med omtanke for kvalitet" over (c)-linja.
3. BAKSIDE: en myk samlet sky bak teksten (draw_text_backdrop shape="block"),
   slik den-magiske-bursdagen-familien gjor det.

Kjor:  python patch_dragejakten_cover_intro.py --apply
"""

import argparse
import os
import re

SCRIPT_ROOT = r"C:\ComfyUI\script"
TARGETS = {
    "nb": os.path.join(SCRIPT_ROOT, "nb", "dragejakten-text-nb.py"),
    "nn": os.path.join(SCRIPT_ROOT, "nn", "dragejakten-text-nn.py"),
    "en-US": os.path.join(SCRIPT_ROOT, "en-US", "dragejakten-text-en-US.py"),
    "en-GB": os.path.join(SCRIPT_ROOT, "en-GB", "dragejakten-text-en-GB.py"),
    "sv": os.path.join(SCRIPT_ROOT, "sv", "dragejakten-text-sv.py"),
}

TAGLINE = {
    "nb": "Trykket med omtanke for\\nkvalitet",
    "nn": "Trykt med omtanke for\\nkvalitet",
    "en-US": "Printed with care\\nfor quality",
    "en-GB": "Printed with care\\nfor quality",
    "sv": "Tryckt med omtanke f\u00f6r\\nkvalitet",
}


# =====================================================================
# 1. FORSIDE - linje 1 tekst + linje 2 logo
# =====================================================================
COVER_BLOCK = '''
# ------------------------------------------------------------
#  FORSIDE-TITTEL - linje 1 som tekst + Dragejakten-logo som linje 2
# ------------------------------------------------------------
# Verdiene speiler DP Title Tester-noden "Dragejakten" (nb). Fontstorrelsen
# er en ANDEL av kortsiden, malt mot forside-malen pa 1024 px, slik at den
# folger med nar comfy leverer 4096 px.
FRONT_COVER_LOGO_SCALE = 0.72
FRONT_COVER_LOGO_X_OFFSET = 0
FRONT_COVER_TOP_MARGIN = 0.025
FRONT_COVER_LINE_SPACING = -0.015
FRONT_COVER_LINE1_SIZE = 92 / 1024
FRONT_COVER_GOLD = ((255, 255, 255), (255, 255, 255))
FRONT_COVER_SHADOW = (5, 8, 18)
FRONT_COVER_SHADOW_OPACITY = 150
FRONT_COVER_SHADOW_BLUR = 6            # px ved 1024 - skaleres med bildet
FRONT_COVER_LOGO_SHADOW_OPACITY = 110
FRONT_COVER_GLOW_COLOR = (255, 248, 215)
FRONT_COVER_GLOW_OPACITY = 0.5
FRONT_COVER_GLOW_RADIUS_SCALE = 0.4

_FC_LOCALES = {"nb", "nn", "en-US", "en-GB", "sv"}
_FC_LOCALE = os.path.basename(SCRIPT_DIR)
_FC_ROOT = os.path.dirname(SCRIPT_DIR) if _FC_LOCALE in _FC_LOCALES else SCRIPT_DIR
if _FC_LOCALE not in _FC_LOCALES:
    _FC_LOCALE = "nb"
FRONT_COVER_LOGO_DIR = os.path.join(_FC_ROOT, "logo", _FC_LOCALE)

# Linje 1 tegnes med Trebuchet MS Bold - rendererens standard, og det er den
# DP Title Tester faktisk brukte (font_small_path star tom i noden).
FRONT_COVER_LINE1_FONT = os.path.join(SCRIPT_DIR, "Trebuchet MS Bold.ttf")
if not os.path.exists(FRONT_COVER_LINE1_FONT):
    FRONT_COVER_LINE1_FONT = os.path.join(_FC_ROOT, "pre", "Trebuchet MS Bold.ttf")


def resolve_front_cover_logo():
    """Logo for linje 2, eller None = tegn linje 2 som tekst.

    None er MED VILJE for en/sv: en norsk logo skal aldri trykkes pa en
    engelsk eller svensk bok.
    """
    name = {"nb": "dragejakten-logo-nb.png",
            "nn": "dragejakten-logo-nb.png"}.get(_FC_LOCALE)
    if not name:
        return None
    path = os.path.join(FRONT_COVER_LOGO_DIR, name)
    if os.path.exists(path):
        return path
    print("[FORSIDE] Fant ingen logo for", _FC_LOCALE, "- linje 2 tegnes som tekst")
    return None


def _fc_text_mask(size, x, y, text, font):
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).text((x, y), text, font=font, fill=255)
    return mask


def _fc_paste_gradient(base_img, mask, bbox, top, bottom):
    W, H = base_img.size
    x0, y0, x1, y1 = bbox
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
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
    base_img.paste(grad, (0, 0), mask)


def _fc_trim_logo(logo):
    """Tett-beskjaer topp og bunn, samme regel som render-title-line2logo.py."""
    logo = logo.convert("RGBA")
    lw, lh = logo.size
    px = logo.load()
    threshold = max(1, lw * 2 // 100)
    top_trim = 0
    for row in range(lh):
        if sum(1 for x in range(lw) if px[x, row][3] > 10) >= threshold:
            break
        top_trim = row + 1
    bottom_trim = lh
    for row in range(lh - 1, -1, -1):
        if sum(1 for x in range(lw) if px[x, row][3] > 10) >= threshold:
            break
        bottom_trim = row
    if top_trim > 0 or bottom_trim < lh:
        logo = logo.crop((0, top_trim, lw, bottom_trim))
    return logo


def draw_centered_title_cover(img, text):
    logo_path = resolve_front_cover_logo()
    if not logo_path:
        _draw_title_cover_text(img, text)
        return

    draw = ImageDraw.Draw(img)
    w, h = img.size
    base = min(w, h)
    scale = base / 1024.0

    line1 = (text or "").split("\\n")[0]
    font = ImageFont.truetype(FRONT_COVER_LINE1_FONT,
                              max(1, int(base * FRONT_COVER_LINE1_SIZE)))
    shadow_offset = max(3, int(base * 0.10 * 0.04))

    w1, h1 = draw.textbbox((0, 0), line1, font=font)[2:]
    y1_pos = int(h * FRONT_COVER_TOP_MARGIN)
    x1_pos = (w - w1) // 2

    if line1:
        # Glod: myk halo som lofter hvit tekst fra den lyse himmelen.
        gm = _fc_text_mask(img.size, x1_pos, y1_pos, line1, font)
        gm = gm.filter(ImageFilter.GaussianBlur(
            max(18, int(font.size * FRONT_COVER_GLOW_RADIUS_SCALE))))
        gm = gm.point(lambda p: int(p * FRONT_COVER_GLOW_OPACITY))
        img.alpha_composite(Image.merge("RGBA", (
            Image.new("L", img.size, FRONT_COVER_GLOW_COLOR[0]),
            Image.new("L", img.size, FRONT_COVER_GLOW_COLOR[1]),
            Image.new("L", img.size, FRONT_COVER_GLOW_COLOR[2]),
            gm)))

        sm = _fc_text_mask(img.size, x1_pos + shadow_offset,
                           y1_pos + shadow_offset, line1, font)
        sm = sm.filter(ImageFilter.GaussianBlur(
            max(1, int(FRONT_COVER_SHADOW_BLUR * scale))))
        if FRONT_COVER_SHADOW_OPACITY < 255:
            sm = sm.point(lambda p: int(p * FRONT_COVER_SHADOW_OPACITY / 255))
        img.paste((*FRONT_COVER_SHADOW, 255), (0, 0), sm)

        tm = _fc_text_mask(img.size, x1_pos, y1_pos, line1, font)
        _fc_paste_gradient(img, tm,
                           draw.textbbox((x1_pos, y1_pos), line1, font=font),
                           FRONT_COVER_GOLD[0], FRONT_COVER_GOLD[1])

    logo = _fc_trim_logo(Image.open(logo_path))
    target_w = max(1, int(w * FRONT_COVER_LOGO_SCALE))
    target_h = max(1, int(logo.height * (target_w / logo.width)))
    logo = logo.resize((target_w, target_h), Image.LANCZOS)

    descender_cut = int(h1 * 0.15)
    y2_pos = y1_pos + h1 - descender_cut + int(h * FRONT_COVER_LINE_SPACING)
    lx = (w - target_w) // 2 + FRONT_COVER_LOGO_X_OFFSET

    if FRONT_COVER_LOGO_SHADOW_OPACITY > 0:
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        alpha = logo.split()[3]
        if FRONT_COVER_LOGO_SHADOW_OPACITY < 255:
            alpha = alpha.point(
                lambda p: int(p * FRONT_COVER_LOGO_SHADOW_OPACITY / 255))
        shadow_img = Image.new("RGBA", (target_w, target_h),
                               (*FRONT_COVER_SHADOW, 255))
        shadow_img.putalpha(alpha)
        layer.paste(shadow_img, (lx + shadow_offset, y2_pos + shadow_offset))
        img.alpha_composite(layer.filter(
            ImageFilter.GaussianBlur(max(8, int(target_h * 0.20)))))

    img.alpha_composite(logo, (lx, y2_pos))
'''


def patch_cover(src: str) -> str:
    if "def _draw_title_cover_text(" in src:
        return src  # allerede patchet
    out, n = re.subn(
        r"\ndef draw_centered_title_cover\(img, text\):\n",
        "\ndef _draw_title_cover_text(img, text):\n",
        src, count=1)
    if n != 1:
        raise SystemExit("Fant ikke draw_centered_title_cover (traff %d)" % n)

    # Legg den nye funksjonen rett foer neste toppnivaa-def etter den gamle.
    idx = out.index("def _draw_title_cover_text(img, text):")
    nxt = out.find("\ndef ", idx + 10)
    if nxt == -1:
        raise SystemExit("Fant ikke slutten paa _draw_title_cover_text")
    return out[:nxt] + "\n" + COVER_BLOCK + out[nxt:]


# =====================================================================
# 2. APNINGSSIDA
# =====================================================================
def patch_intro(src: str, lang: str) -> str:
    out = src

    # Mye svakere lys plate. Den gamle (alpha 196) vasket ut hele dragemonsteret.
    out, n = re.subn(
        r"def draw_light_plate\(img, box, alpha=\d+, pad=[\d.]+\):",
        "def draw_light_plate(img, box, alpha=72, pad=0.075):",
        out, count=1)
    if n != 1:
        raise SystemExit("Fant ikke draw_light_plate")

    # Samme tekstkolonne som de andre bokene. Bunnen stopper paa 0.80 slik at
    # taglinen faar plass mellom brodteksten og den innbakte (c)-linja.
    out = re.sub(
        r"                int\(img_w \* 0\.\d+\),\n"
        r"                int\(img_h \* 0\.\d+\),\n"
        r"                int\(img_w \* 0\.\d+\),\n"
        r"                int\(img_h \* 0\.\d+\)\n",
        lambda _m: (
            "                int(img_w * 0.18),\n"
            "                int(img_h * 0.36),\n"
            "                int(img_w * 0.82),\n"
            "                int(img_h * 0.80)\n"),
        out, count=1)

    # Tagline-konstant. MAA settes inn via en lambda - `\n` i erstatningen
    # blir ellers tolket av re.sub og gir et avbrutt strenglitteral.
    tag_line = 'DREAMPAGE_FIRST_TAGLINE = "%s"' % TAGLINE[lang]
    if "DREAMPAGE_FIRST_TAGLINE" in out:
        # Reparer en tidligere feilskrevet (flerlinjet) konstant.
        out = re.sub(r'DREAMPAGE_FIRST_TAGLINE = "[^"]*"',
                     lambda _m: tag_line, out, count=1, flags=re.S)
    else:
        out, n = re.subn(
            r"\n(COVER_FONT\s*=)",
            lambda m: "\n" + tag_line + "\n\n" + m.group(1),
            out, count=1)
        if n != 1:
            raise SystemExit("Fant ikke COVER_FONT-linja")

    # Tegn taglinen paa apningssida, over "(c) 2026 DreamPage"
    tag_code = (
        '        # --- Tagline (rendret av scriptet, over "(c) 2026 DreamPage") ---\n'
        '        _dpf_tag_lines = DREAMPAGE_FIRST_TAGLINE.splitlines()\n'
        '        _dpf_tag_fs = int(img_h * 0.028)\n'
        '        try:\n'
        '            _dpf_tag_font = ImageFont.truetype(COVER_FONT, _dpf_tag_fs)\n'
        '        except Exception:\n'
        '            _dpf_tag_font = ImageFont.load_default()\n'
        '        _dpf_tag_gap = int(_dpf_tag_fs * 0.30)\n'
        '        _dpf_tag_dims = [draw.textbbox((0, 0), _t, font=_dpf_tag_font) for _t in _dpf_tag_lines]\n'
        '        _dpf_tag_total = sum((b[3] - b[1]) for b in _dpf_tag_dims) + _dpf_tag_gap * (len(_dpf_tag_lines) - 1)\n'
        '        _dpf_ty = int(img_h * 0.835) - _dpf_tag_total // 2\n'
        '        for _t, _b in zip(_dpf_tag_lines, _dpf_tag_dims):\n'
        '            _dpf_lw = _b[2] - _b[0]\n'
        '            draw.text(((img_w - _dpf_lw) // 2, _dpf_ty), _t, font=_dpf_tag_font, fill=(35, 30, 25, 255))\n'
        '            _dpf_ty += (_b[3] - _b[1]) + _dpf_tag_gap\n'
    )
    if "_dpf_tag_lines" not in out:
        anchor = '        out_path = os.path.join(out_dir, "blank.png")\n'
        if anchor not in out:
            raise SystemExit("Fant ikke blank.png-ankeret")
        out = out.replace(anchor, tag_code + anchor, 1)
    else:
        # Allerede satt inn - hold stoerrelse og plassering i synk.
        out = re.sub(r"_dpf_tag_fs = int\(img_h \* [\d.]+\)",
                     "_dpf_tag_fs = int(img_h * 0.028)", out, count=1)
        out = re.sub(r"_dpf_ty = int\(img_h \* [\d.]+\) - _dpf_tag_total // 2",
                     "_dpf_ty = int(img_h * 0.835) - _dpf_tag_total // 2",
                     out, count=1)

    return out


# =====================================================================
# 3. BAKSIDE - samlet myk sky bak teksten
# =====================================================================
def patch_backdrop(src: str) -> str:
    out = src

    # a) shape-parameter paa draw_text_backdrop
    out, n = re.subn(
        r'(def draw_text_backdrop\(img, box, text, font, line_spacing, '
        r'highlights=None, align="left", strength="normal")\):',
        r'\1, shape="lines"):',
        out, count=1)
    if n not in (0, 1):
        raise SystemExit("draw_text_backdrop-signaturen traff %d ganger" % n)

    # b) block-grenen rett foer tegneloekka
    block_branch = '''    if shape == "block":
        # Baksiden: EN myk sky bak hele bolken - ingen synlig kant. Den crispe
        # platen droppes (plate_alpha = 0); i stedet blurres skyggen kraftig
        # slik at den toner ut i illustrasjonen.
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
    if "if shape == \"block\":" not in out:
        old = "    drew = False\n    for lb in line_boxes:\n"
        if out.count(old) != 1:
            raise SystemExit("Fant ikke tegneloekka i draw_text_backdrop (%d)" % out.count(old))
        out = out.replace(old, block_branch, 1)

        old_radius = (
            "        radius = max(6, min((right - left) // 2, int((bottom - top) * 0.40)))\n")
        new_radius = (
            "        if shape == \"block\":\n"
            "            radius = max(24, int(fs * 0.9))\n"
            "        else:\n"
            "            radius = max(6, min((right - left) // 2, int((bottom - top) * 0.40)))\n")
        if out.count(old_radius) != 1:
            raise SystemExit("Fant ikke radius-linja (%d)" % out.count(old_radius))
        out = out.replace(old_radius, new_radius, 1)

    # c) kall den fra bakside-grenen
    if "shape=\"block\"" not in out.split("def draw_text_backdrop")[0]:
        anchor = (
            "            use_gradient = \"color\" not in block\n"
            "\n"
            "\n"
            "            draw_text(\n")
        call = (
            "            use_gradient = \"color\" not in block\n"
            "\n"
            "            # Ett samlet, mykt felt bak hele bakside-teksten - ikke per linje.\n"
            "            if block.get(\"text_backdrop\", True):\n"
            "                draw_text_backdrop(\n"
            "                    img, box, block[\"text\"], font, line_spacing,\n"
            "                    highlights=block.get(\"highlights\", []),\n"
            "                    align=\"center\", shape=\"block\",\n"
            "                    strength=block.get(\"text_backdrop_strength\", \"strong\"),\n"
            "                )\n"
            "\n"
            "            draw_text(\n")
        if out.count(anchor) != 1:
            raise SystemExit("Fant ikke bakside-draw_text-ankeret (%d)" % out.count(anchor))
        out = out.replace(anchor, call, 1)

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    for lang, path in TARGETS.items():
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        out = patch_backdrop(patch_intro(patch_cover(src), lang))
        if out == src:
            print("[%-5s] uendret" % lang)
            continue
        if not args.apply:
            print("[%-5s] ville endret (%d -> %d tegn)" % (lang, len(src), len(out)))
            continue
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(out)
        print("[%-5s] skrevet" % lang)


if __name__ == "__main__":
    main()

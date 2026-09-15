

from reportlab.pdfgen import canvas
from reportlab.lib.units import inch

import shutil

import os
import re
import argparse
from typing import List, Dict, Any
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from gelato_cover import build_gelato_cover_pdf
from dream_pdf_guard import (
    EXPECTED_INNER_PAGES as _DEFAULT_EXPECTED_INNER_PAGES,
    log_inner_page_order,
    validate_inner_pdf_page_count,
)

# Lastpage(drage).png ligger etter blank-back, så total innersider = 31.
EXPECTED_INNER_PAGES = 31

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT_LOCALES = {"nb", "nn", "en-US", "en-GB", "sv"}
SCRIPT_LOCALE = os.path.basename(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR) in SCRIPT_LOCALES else "nb"
SCRIPT_ROOT_DIR = os.path.dirname(SCRIPT_DIR) if SCRIPT_LOCALE in SCRIPT_LOCALES else SCRIPT_DIR
LASTPAGE_DIR = os.path.join(SCRIPT_ROOT_DIR, "lastpages", SCRIPT_LOCALE)


def is_lastpage_filename(filename):
    return os.path.basename(filename).lower().startswith("lastpage")


def resolve_lastpage_path(filename):
    candidate = os.path.join(LASTPAGE_DIR, filename)
    if os.path.exists(candidate):
        return candidate
    return None


def resolve_final_inner_path(filename, base_dir):
    if is_lastpage_filename(filename):
        source = resolve_lastpage_path(filename)
        if source:
            return source
        print(f"ADVARSEL: Fant ikke {filename} i {LASTPAGE_DIR} - hopper over")
        return None

    source = os.path.join(base_dir, filename)
    if not os.path.exists(source):
        source = os.path.join(SCRIPT_DIR, filename)
    if not os.path.exists(source):
        raise FileNotFoundError(
            f"Fant ikke siste innerside ({filename}) i {base_dir} eller {SCRIPT_DIR}"
        )
    return source


FRONT_LOGO_PATH = os.path.join(SCRIPT_DIR, "DreamPage_logo.png")
BACK_LOGO_PATH  = os.path.join(SCRIPT_DIR, "DreamPage_logo.png")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

DREAMPAGE_FIRST_TAGLINE = "Tryckt med omtanke för\nkvalitet"

COVER_FONT     = os.path.join(SCRIPT_DIR, "PlayfairDisplay.ttf")
INNER_FONT     = os.path.join(SCRIPT_DIR, "Georgia.ttf")
HIGHLIGHT_FONT = os.path.join(SCRIPT_DIR, "Georgia Bold.ttf")
BACK_TEXT_FONT = os.path.join(globals().get("SCRIPT_ROOT_DIR", os.path.dirname(SCRIPT_DIR)), "pre", "Fredoka.ttf")

# Dragejaktens egen apningsside (drageromster). Ligger i bokmappa som de andre
# bok-spesifikke apningssidene; faller tilbake til den delte sida hvis den mangler.
DRAGE_DREAMPAGE_FIRST = os.path.join(
    os.path.dirname(globals().get("SCRIPT_ROOT_DIR", os.path.dirname(SCRIPT_DIR))),
    "books", "dragejakten", "dreampage-first-drage.png"
)

TEXT_COLOR   = "#FFFFFF"
STROKE_COLOR = "#000000"

# Design-størrelse (samme som de andre bøkene)
INNER_WIDTH  = 1536
INNER_HEIGHT = 1024

LEFT_X1  = 140
LEFT_X2  = 540

RIGHT_X1 = 996
RIGHT_X2 = 1396

MARGIN_Y          = 80
DEFAULT_FONT_SIZE = 30

LULU_DPI = 300
LULU_PAGE_PX = 2625              # 8.75 inch * 300 dpi
LULU_SPREAD_SIZE = (5250, 2625)  # 2 sider

# -------------------- LULU COVER (SOURCE OF TRUTH) --------------------
# Dette er tallene Lulu krever hos deg (fra UI: 19 x 10.25, spine 0.25)
COVER_DPI = 300

LULU_TRIM_IN   = 8.75
LULU_SPINE_IN  = 0.25
LULU_COVER_W_IN = 19.0
LULU_COVER_H_IN = 10.25

# Lulu Photo Book bleed (fra template)
BLEED_LEFT_RIGHT_IN = 0.625   # wrap horisontalt per side
BLEED_TOP_BOTTOM_IN = 0.65    # wrap vertikalt per side


def in_to_px(x: float, dpi: int = COVER_DPI) -> int:
    return int(round(x * dpi))

def cover_fit_with_bleed(img, target_w, target_h, trim_w, trim_h, align):
    # Blur bakgrunn
    bg = img.resize((target_w, target_h), Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(24))

    # Skaler FG til trim
    iw, ih = img.size
    scale = min(trim_w / iw, trim_h / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    fg = img.resize((nw, nh), Image.LANCZOS)

    canvas = Image.new("RGB", (target_w, target_h))
    canvas.paste(bg, (0, 0))

    # Plasser FG riktig side
    if align == "right":   # bakside: trim mot høyre (mot ryggen)
        x = target_w - nw
    elif align == "left":  # forside: trim mot venstre (mot ryggen)
        x = 0
    else:
        x = (target_w - nw)//2

    y = (target_h - nh)//2
    canvas.paste(fg, (x, y))

    return canvas







# ------------------------------------------------------------
#  STANDARD TEKSTSTIL FOR INNERSIDER
# ------------------------------------------------------------

DEFAULT_TEXT_STYLE = {
    "gradient": {
        "colors": ((30, 60, 120), (90, 110, 160)),  # samme som forside
        "shadow": (5, 8, 18),
    }
}

# ✅ Alias for kompatibilitet med kallet du allerede har i render_page()
DEFAULT_TEXT_GRADIENT = DEFAULT_TEXT_STYLE["gradient"]


# ------------------------------------------------------------
#  TEKSTRENDERING (samme logikk + gradient-støtte)
# ------------------------------------------------------------

def draw_text(draw, text, box, font,
              color=TEXT_COLOR,
              stroke_color=STROKE_COLOR,
              line_spacing=10,
              highlights=None,
              gradient=None,
              img=None,
              align="left"):
    """
    Skriver avsnitttekst inni en boks med enkel word-wrapping.
    Støtter "highlights" som får bold-font.
    Støtter "gradient" (samme mask+gradient som forside) dersom gradient != None.
    """
    x1, y1, x2, y2 = box
    max_width = x2 - x1

    if highlights is None:
        hl_set = set()
    else:
        hl_set = {h.strip().lower() for h in highlights}

    base_font = font
    highlight_font = ImageFont.truetype(HIGHLIGHT_FONT, base_font.size)

    paragraphs = text.split("\n")
    y = y1

    for para in paragraphs:
        para = para.strip()
        if not para:
            y += base_font.size + line_spacing
            continue

        words = para.split(" ")
        line_words: List[str] = []
        line_fonts: List[ImageFont.FreeTypeFont] = []
        line_width = 0

        def flush_line():
            nonlocal y
            if not line_words:
                return
            if align == "center":
                x = x1 + max(0, int((max_width - line_width) / 2))
            elif align == "right":
                x = x2 - int(line_width)
            else:
                x = x1

            for w, fnt in zip(line_words, line_fonts):
                if gradient:
                    # Gradient krever img (RGBA) for paste()
                    draw_gradient_word(
                        img, draw, w, x, y, fnt,
                        gradient["colors"],
                        gradient["shadow"]
                    )
                else:
                    draw.text((x, y), w, font=fnt, fill=color)

                x += draw.textlength(w, font=fnt)
            y += base_font.size + line_spacing

        for word in words:
            clean = word.strip(".,!?…:;«»\"'").lower()
            fnt = highlight_font if clean in hl_set else base_font

            piece = ("" if not line_words else " ") + word
            piece_width = draw.textlength(piece, font=fnt)

            if line_words and (line_width + piece_width > max_width):
                flush_line()
                line_words = [word]
                line_fonts = [fnt]
                line_width = draw.textlength(word, font=fnt)
            else:
                line_words.append(piece)
                line_fonts.append(fnt)
                line_width += piece_width

        flush_line()
        y += line_spacing


# ------------------------------------------------------------
#  FORSIDE-TITTEL – render-title.py logikk + dine farger
# ------------------------------------------------------------

def draw_light_plate(img, box, alpha=72, pad=0.075):
    """Myk, lys hinne bak brodteksten pa apningssida.

    Tegner en avrundet hvit flate og blurrer den kraftig, slik at den tones ut
    mot bakgrunnen i stedet for a lage en synlig rektangelkant.
    """
    from PIL import ImageFilter

    w, h = img.size
    x1, y1, x2, y2 = box
    px = int(w * pad)
    py = int(h * pad * 0.55)
    rect = (max(0, x1 - px), max(0, y1 - py), min(w, x2 + px), min(h, y2 + py))

    plate = Image.new("RGBA", img.size, (255, 255, 255, 0))
    pd = ImageDraw.Draw(plate)
    radius = int(min(rect[2] - rect[0], rect[3] - rect[1]) * 0.22)
    pd.rounded_rectangle(rect, radius=radius, fill=(255, 255, 255, alpha))
    plate = plate.filter(ImageFilter.GaussianBlur(int(min(w, h) * 0.020)))

    img.alpha_composite(plate)


def draw_inside_title(img, text):
    """
    Elegant dark title for the first inside page only.
    No cover gradient, no heavy shadow - cleaner book-style intro page.
    """
    draw = ImageDraw.Draw(img)
    w, h = img.size

    lines = text.split("\n")
    line1 = lines[0] if len(lines) > 0 else ""
    line2 = lines[1] if len(lines) > 1 else ""

    try:
        font1 = ImageFont.truetype(COVER_FONT, int(min(w, h) * 0.052))
        font2 = ImageFont.truetype(COVER_FONT, int(min(w, h) * 0.068))
    except Exception:
        font1 = ImageFont.load_default()
        font2 = font1

    title_color = "#1c1c1e"

    def _tw(t, f):
        if not t:
            return 0, 0
        bbox = draw.textbbox((0, 0), t, font=f)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    w1, h1 = _tw(line1, font1)
    w2, h2 = _tw(line2, font2)

    top_y = int(h * 0.10)
    spacing = int(h * 0.018)

    if line1:
        draw.text(((w - w1) // 2, top_y), line1, font=font1, fill=title_color)
    if line2:
        draw.text(((w - w2) // 2, top_y + h1 + spacing), line2, font=font2, fill=title_color)


def _draw_title_cover_text(img, text):
    """
    Forside-tittel med render-title.py:
    - mask + blur shadow
    - gradient
    - to linjer
    """
    draw = ImageDraw.Draw(img)
    w, h = img.size
    base = min(w, h)

    lines = text.split("\n")
    line1 = lines[0] if len(lines) > 0 else ""
    line2 = lines[1] if len(lines) > 1 else ""

    font_small = ImageFont.truetype(COVER_FONT, int(min(img.size) * 0.098))
    font_large = ImageFont.truetype(COVER_FONT, int(min(img.size) * 0.121))


    gold   = ((30, 60, 120), (210, 220, 235))
    shadow = (5, 8, 18)

    def _make_text_mask(size, x, y, t, fnt):
        mask = Image.new("L", size, 0)
        d = ImageDraw.Draw(mask)
        d.text((x, y), t, font=fnt, fill=255)
        return mask

    def _paste_gradient(base_img, mask, bbox, top, bottom):
        W, H = base_img.size
        x0, y0, x1, y1 = bbox
        grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(grad)

        height = max(1, y1 - y0)
        for i in range(y0, y1):
            t = (i - y0) / height
            col = (
                int(top[0] + (bottom[0] - top[0]) * t),
                int(top[1] + (bottom[1] - top[1]) * t),
                int(top[2] + (bottom[2] - top[2]) * t),
                255,
            )
            d.line([(x0, i), (x1, i)], fill=col)

        base_img.paste(grad, (0, 0), mask)

    size_large = int(base * 0.10)
    shadow_offset = max(3, int(size_large * 0.04))

    def text_size(t, f):
        if not t:
            return 0, 0
        bbox = draw.textbbox((0, 0), t, font=f)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    w1, h1 = text_size(line1, font_small)
    w2, h2 = text_size(line2, font_large)

    top_y = int(h * 0.040)
    spacing = int(h * 0.003)

    x1 = (w - w1) // 2
    x2 = (w - w2) // 2
    y1 = top_y

    descender_cut = int(h1 * 0.15) if h1 else 0
    y2 = y1 + h1 - descender_cut + spacing

    def draw_line(t, fnt, x, y):
        if not t:
            return

        sm = _make_text_mask(img.size, x + shadow_offset, y + shadow_offset, t, fnt)
        sm = sm.filter(ImageFilter.GaussianBlur(max(1, shadow_offset // 2)))
        img.paste((*shadow, 255), (0, 0), sm)

        tm = _make_text_mask(img.size, x, y, t, fnt)
        bbox = draw.textbbox((x, y), t, font=fnt)
        _paste_gradient(img, tm, bbox, gold[0], gold[1])

    draw_line(line1, font_small, x1, y1)
    draw_line(line2, font_large, x2, y2)



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

    line1 = (text or "").split("\n")[0]
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

def draw_gradient_word(img, draw, text, x, y, font, colors, shadow):
    # Lag tekstmaske
    mask = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(mask)
    d.text((x, y), text, font=font, fill=255)

    # Skygge
    # sm = mask.filter(ImageFilter.GaussianBlur(3))
    # img.paste((*shadow, 255), (0, 0), sm)

    # Gradient
    bbox = draw.textbbox((x, y), text, font=font)
    x0, y0, x1, y1 = bbox
    height = max(1, y1 - y0)

    grad = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)

    for i in range(y0, y1):
        t = (i - y0) / height
        col = (
            int(colors[0][0] + (colors[1][0] - colors[0][0]) * t),
            int(colors[0][1] + (colors[1][1] - colors[0][1]) * t),
            int(colors[0][2] + (colors[1][2] - colors[0][2]) * t),
            255,
        )
        gd.line([(x0, i), (x1, i)], fill=col)

    img.paste(grad, (0, 0), mask)


def save_split_a5(img, out_dir: str, base_filename: str) -> List[str]:
    """
    Deler et oppslag (2048x1024) i to kvadrater (1024x1024):
    venstre kvadrat og høyre kvadrat.
    """
    # TVING oppslaget til korrekt Lulu-størrelse
    img = img.resize(LULU_SPREAD_SIZE, Image.LANCZOS)

    left_img = img.crop((0, 0, LULU_PAGE_PX, LULU_PAGE_PX))
    right_img = img.crop((LULU_PAGE_PX, 0, LULU_PAGE_PX * 2, LULU_PAGE_PX))


    base, ext = os.path.splitext(base_filename)
    left_name  = f"{base}_L{ext}"
    right_name = f"{base}_R{ext}"

    left_path  = os.path.join(out_dir, left_name)
    right_path = os.path.join(out_dir, right_name)

    os.makedirs(out_dir, exist_ok=True)
    left_img.save(left_path)
    right_img.save(right_path)

    print("Lagret:", left_path)
    return [left_path, right_path]

# ------------------------------------------------------------
#  build_pages – (uendret, din tekst)
# ------------------------------------------------------------

def build_pages(child_name: str) -> List[Dict[str, Any]]:
    def p(text: str) -> str:
        return (
            text.replace("[NAVN]", child_name)
                .replace("[ NAVN ]", child_name)
                .replace("(navn)", child_name)
                .replace("(Navn)", child_name)
                .replace("{{name}}", child_name)
                .replace("{{['name']}}", child_name)
        )

    pages: List[Dict[str, Any]] = [
        {
            "filename": "forside(dragejakten).png",
            "type": "cover",
            "text": p("[NAVN] og\nDragejakten"),
        },
        {
            "filename": "ryggrad.png",
            "type": "cover",
        },

        # Introside
        {
            "type": "blank",
            "side": "right",
            "text": p("[NAVN] og\nDragejakten"),
            "blocks": [{
                "text": p(
                    "Takk for at du kjøpte denne personlige historien!\n"
                    "I denne boken følger vi (Navn) på et eventyr i en verden full av drager.\n"
                    "(Navn) lærer at ekte mot er å hjelpe noen som trenger det.\n"
                    "Vi håper historien bringer glede, spenning og fantasifulle øyeblikk."
                ),
                "font_size": 50,
                "color": "#111111",
                "y_offset": 420,
            }],
        },

        # Side 1
        {
            "filename": "01(dragejakten).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "(navn) likte å utforske skogen.\n"
                    "Han kjente hver sti og hvert eneste tre.\n"
                    "Men denne dagen fant han noe han aldri hadde sett før.\n"
                    "Enorme fotspor i bakken – så store at begge føttene hans fikk plass i ett av dem."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": ["(navn)", "utforske", "skogen", "fotspor"],
            }],
        },

        # Side 2
        {
            "filename": "02(dragejakten).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Sporene fortsatte mellom trærne.\n"
                    "(navn) fulgte etter, dypere og dypere inn i skogen.\n"
                    "Greinene lukket seg over ham, og lyden av fugler ble borte.\n"
                    "Hvem hadde laget dem? Og hvor kunne de føre?"
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": ["(navn)", "Sporene", "dypere", "skogen"],
            }],
        },

        # Side 3
        {
            "filename": "03(dragejakten).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Plutselig stoppet sporene foran en mørk hule i fjellet.\n"
                    "Fra innsiden kom et svakt blått lys som pustet, av og på.\n"
                    "Langt der inne hørte han noe tungt puste i mørket.\n"
                    "(navn) tok mot til seg og gikk inn."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": ["(navn)", "hule", "blått", "mot"],
            }],
        },

        # Side 4
        {
            "filename": "04(dragejakten).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Langt inne i hulen fikk (navn) øye på noe enormt.\n"
                    "En stor blågrønn drage var lenket fast til fjellveggen!\n"
                    "Tunge jernlenker lå rundt beina hans.\n"
                    "Men dragen så ikke farlig ut.\n"
                    "Den så redd ut."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": ["(navn)", "drage", "lenket", "redd"],
            }],
        },

        # Side 5
        {
            "filename": "05(dragejakten).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "(navn) løp bort til dragen.\n"
                    "Låsen var gammel og rusten. Han dro og vred, og dro enda en gang, helt til den endelig ga etter.\n"
                    "KLANK!\n"
                    "Lenken falt i bakken.\n"
                    "Dragen var fri!"
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": ["(navn)", "KLANK", "Lenken", "fri"],
            }],
        },

        # Side 6
        {
            "filename": "06(dragejakten).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "«Takk, (navn),» sa dragen. Stemmen var dyp og varm.\n"
                    "Men så ble den alvorlig.\n"
                    "«Sønnen min er også fanget – jeg klarer ikke å redde ham alene.»\n"
                    "(navn) kjente hjertet slå fortere. Men han visste med én gang hva han måtte gjøre."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": ["(navn)", "dragen", "Sønnen", "fanget"],
            }],
        },

        # Side 7
        {
            "filename": "07(dragejakten).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Dragen bøyde seg helt ned til bakken.\n"
                    "«Hopp opp!»\n"
                    "(navn) klatret forsiktig opp på ryggen og holdt godt fast i de varme skjellene.\n"
                    "Så spredte dragen de enorme vingene sine."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": ["(navn)", "ryggen", "vingene", "dragen"],
            }],
        },

        # Side 8
        {
            "filename": "08(dragejakten).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "WHOOSH!\n"
                    "De skjøt ut av hulen og høyt opp over skogen.\n"
                    "Vinden suste i ørene hans, og under dem ble trærne små som fyrstikker.\n"
                    "(navn) hadde aldri fløyet før. Han lo høyt."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": ["(navn)", "WHOOSH", "skogen", "fløyet"],
            }],
        },

        # Side 9
        {
            "filename": "09(dragejakten).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Snart dukket et mørkt fjell opp foran dem.\n"
                    "Høyt oppe mellom gamle steinruiner satt en liten drage fanget bak et gitter.\n"
                    "Han var ikke større enn (navn) selv.\n"
                    "«Der er han!» ropte (navn)."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": ["(navn)", "fjell", "steinruiner", "drage"],
            }],
        },

        # Side 10
        {
            "filename": "10(dragejakten).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "(navn) snek seg inn mellom de gamle murene. Steinene var kalde og glatte.\n"
                    "Den lille dragen skalv bak gitteret og trakk seg bakover.\n"
                    "«Ikke vær redd,» hvisket (navn).\n"
                    "«Jeg skal få deg ut.»"
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": ["(navn)", "murene", "gitteret", "redd"],
            }],
        },

        # Side 11
        {
            "filename": "11(dragejakten).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "(navn) fant låsen og tok godt tak.\n"
                    "Én gang.\n"
                    "To ganger.\n"
                    "KLIKK!\n"
                    "Porten åpnet seg, og den lille dragen løp rett ut og gned hodet mot armen hans."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": ["(navn)", "låsen", "KLIKK", "Porten"],
            }],
        },

        # Side 12
        {
            "filename": "12(dragejakten).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Den store dragen skyndte seg fram.\n"
                    "Den lille dragen kastet seg inntil faren sin, og de la vingene rundt hverandre.\n"
                    "(navn) smilte.\n"
                    "Dragejakten var endelig over."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": ["(navn)", "dragen", "Dragejakten", "smilte"],
            }],
        },

        # Side 13
        {
            "filename": "13(dragejakten).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "De tre fløy sammen tilbake over fjellene mens solen gikk ned.\n"
                    "Den lille dragen fløy ved siden av faren sin, mens (navn) satt trygt på ryggen til den store dragen.\n"
                    "Langt foran dem lå et sted (navn) aldri hadde sett før."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": ["(navn)", "fjellene", "dragen", "trygt"],
            }],
        },

        # Side 14
        {
            "filename": "14(dragejakten).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Bak fjellene lå en hemmelig dal full av drager.\n"
                    "Store og små, i alle farger, fløy de over trærne.\n"
                    "Før (navn) dro hjem, ga dragen ham et glødende drageskjell.\n"
                    "«Behold dette,» sa dragen. «En dag kan vi trenge deg igjen.»\n"
                    "(navn) så ned på skjellet. Plutselig begynte det å lyse enda sterkere.\n"
                    "Eventyret var kanskje ikke helt over likevel…"
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": ["(navn)", "hemmelig", "drageskjell", "Eventyret"],
            }],
        },

        # EKSTRA BLANK SISTE INNERSIDE
        {
            "filename": "blank-back.png",
            "type": "inner",
            "side": "left",
            "blank_only": True
        },
        # PER-BOK LASTPAGE - kommer ETTER blank-back, lastes fra script/lastpages/<locale>
        {
            "filename": "Lastpage(drage).png",
            "type": "inner",
            "side": "right",
            "blank_only": True
        },

        # Bakside
        {
            "filename": "bakside(dragejakten).png",
            "type": "cover",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Dypt inne i skogen finner (navn) enorme fotspor – og en drage som er lenket fast i en mørk hule.\n"
                    "Sammen flyr de over fjellene for å redde dragens lille sønn.\n"
                    "Dragejakten er en spennende historie om mot, vennskap og det å hjelpe andre.\n"
                    "En personlig barnebok hvor (navn) selv blir helten i sitt eget drageeventyr."
                ),
                "font_size": 46,
                "color": "#FFFFFF",
                "highlights": ["(navn)", "drage", "fotspor", "mot", "Dragejakten", "vennskap", "fjellene"],
            }],
        },
    ]


    return pages



# ------------------------------------------------------------
#  render_page – skalering + A5-splitt (samme struktur)
# ------------------------------------------------------------

try:
    from dream_text_layout import draw_text as draw_text
except Exception as exc:
    print("Kunne ikke laste felles tekstlayout:", exc)


# ------------------------ ryggrad per språk (script/ryggrad/<book-slug>/) ------------------------
RYGGRAD_BOOK_SLUG = "dragejakten"
RYGGRAD_LOCALES = {"nb", "nn", "en-US", "en-GB", "sv"}


def resolve_ryggrad_path(base_dir=None):
    """Finn riktig ryggrad for språket: script/ryggrad/<slug>/ryggrad-<locale>.png,
    fallback til ryggrad-nb.png, deretter ryggrad.png i ordre-input."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    locale = os.path.basename(script_dir)
    root_dir = os.path.dirname(script_dir) if locale in RYGGRAD_LOCALES else script_dir
    if locale not in RYGGRAD_LOCALES:
        locale = "nb"
    ryggrad_dir = os.path.join(root_dir, "ryggrad", RYGGRAD_BOOK_SLUG)
    for cand in (locale, "nb"):
        path = os.path.join(ryggrad_dir, "ryggrad-" + cand + ".png")
        if os.path.exists(path):
            if cand != locale:
                print("ADVARSEL: Fant ikke ryggrad-" + locale + ".png i " + ryggrad_dir + " - bruker ryggrad-nb.png")
            return path
    if base_dir:
        legacy = os.path.join(base_dir, "ryggrad.png")
        if os.path.exists(legacy):
            print("ADVARSEL: Fant ingen ryggrad i " + ryggrad_dir + " - bruker " + legacy)
            return legacy
    return None


# ------------------------ bakside per bok (script/bakside/<book-slug>/) ------------------------
def resolve_bakside_path(filename, base_dir=None):
    """Finn bakside fra script/bakside/<slug>/, fallback til ordre-input."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    locale = os.path.basename(script_dir)
    bakside_locales = {"nb", "nn", "en-US", "en-GB", "sv"}
    root_dir = os.path.dirname(script_dir) if locale in bakside_locales else script_dir
    if locale not in bakside_locales:
        locale = "nb"

    bakside_dir = os.path.join(root_dir, "bakside", RYGGRAD_BOOK_SLUG)
    stem, ext = os.path.splitext(filename)
    exts = [ext] if ext else []
    for extra in (".png", ".jpg", ".jpeg"):
        if extra.lower() not in [e.lower() for e in exts]:
            exts.append(extra)

    candidates = [os.path.join(bakside_dir, filename)]
    for candidate_ext in exts:
        candidates.append(os.path.join(bakside_dir, "bakside-" + locale + candidate_ext))
    for candidate_ext in exts:
        candidates.append(os.path.join(bakside_dir, "bakside" + candidate_ext))

    for path in candidates:
        if os.path.exists(path):
            return path

    if os.path.isdir(bakside_dir):
        image_exts = {".png", ".jpg", ".jpeg"}
        for name in sorted(os.listdir(bakside_dir)):
            lower = name.lower()
            if lower.startswith("bakside") and os.path.splitext(lower)[1] in image_exts:
                return os.path.join(bakside_dir, name)

    if base_dir:
        legacy = os.path.join(base_dir, filename)
        if os.path.exists(legacy):
            print("ADVARSEL: Fant ingen bakside i " + bakside_dir + " - bruker " + legacy)
            return legacy
    return None


def render_page(page: Dict[str, Any], base_dir: str, out_dir: str) -> List[str]:

    # ------------------------ SISTE INNERSIDE (Lastpage / blank-back) ------------------------
    if page.get("blank_only"):
        blank_path = resolve_final_inner_path(page["filename"], base_dir)
        if blank_path is None:
            return []
        img = Image.open(blank_path).convert("RGBA")

        out_path = os.path.join(out_dir, page["filename"])
        os.makedirs(out_dir, exist_ok=True)
        if os.path.splitext(out_path)[1].lower() in (".jpg", ".jpeg"):
            img.convert("RGB").save(out_path)
        else:
            img.save(out_path)

        print("Lagret siste innerside:", out_path)
        return [out_path]


    # ------------------------ blank side ------------------------
    if page.get("type") == "blank":
        blank_path = (
            DRAGE_DREAMPAGE_FIRST if os.path.exists(DRAGE_DREAMPAGE_FIRST)
            else os.path.join(SCRIPT_DIR, "dreampage-first.png")
        )

        if not os.path.exists(blank_path):
            raise FileNotFoundError("Fant ikke dreampage-first.png i script-mappen")

        img = Image.open(blank_path).convert("RGBA")
        draw = ImageDraw.Draw(img)

        img_w, img_h = img.size
        scale_x = img_w / INNER_WIDTH
        scale_y = img_h / INNER_HEIGHT

        # --- 1) Elegant inside-page title (not the cover style) ---
        title_text = page.get("text")
        if title_text:
            draw_inside_title(img, title_text)

        # --- 2) Tegn beskrivende tekst ---
        # Linjeavstanden var tidligere 10 rene piksler (draw_text sin default) mens
        # fonten skaleres opp til sidens faktiske oppl?sning. P? en 4096px side ga
        # det ~112px bokstaver med 10px luft - teksten klumpet seg sammen. B?de
        # st?rrelsen og luften m? f?lge samme skala som resten av siden.
        for block in page.get("blocks", []):
            base_size = block.get("font_size", 40)
            font_size = int(base_size * min(scale_x, scale_y))
            font = ImageFont.truetype(INNER_FONT, font_size)
            line_spacing = int(font_size * 0.52)

            box = (
                int(img_w * 0.18),
                int(img_h * 0.36),
                int(img_w * 0.82),
                int(img_h * 0.80)
            )

            # Drageromsteret er langt kraftigere enn den gamle, bleke apningssida,
            # sa den morke brodteksten trenger en myk lys hinne under seg. Kraftig
            # blur gjor at platen ikke leser som en boks - dragene skinner gjennom
            # i kantene, men kontrasten under teksten holder.
            draw_light_plate(img, box)

            draw_text(
                draw=draw,
                text=block["text"],
                box=box,
                font=font,
                line_spacing=line_spacing,
                color=block.get("color", "#111111"),
                highlights=block.get("highlights", []),
                gradient=None,
                img=img,
                align="center"
            )

        # --- Tagline (rendret av scriptet, over "(c) 2026 DreamPage") ---
        _dpf_tag_lines = DREAMPAGE_FIRST_TAGLINE.splitlines()
        _dpf_tag_fs = int(img_h * 0.028)
        try:
            _dpf_tag_font = ImageFont.truetype(COVER_FONT, _dpf_tag_fs)
        except Exception:
            _dpf_tag_font = ImageFont.load_default()
        _dpf_tag_gap = int(_dpf_tag_fs * 0.30)
        _dpf_tag_dims = [draw.textbbox((0, 0), _t, font=_dpf_tag_font) for _t in _dpf_tag_lines]
        _dpf_tag_total = sum((b[3] - b[1]) for b in _dpf_tag_dims) + _dpf_tag_gap * (len(_dpf_tag_lines) - 1)
        _dpf_ty = int(img_h * 0.835) - _dpf_tag_total // 2
        for _t, _b in zip(_dpf_tag_lines, _dpf_tag_dims):
            _dpf_lw = _b[2] - _b[0]
            draw.text(((img_w - _dpf_lw) // 2, _dpf_ty), _t, font=_dpf_tag_font, fill=(35, 30, 25, 255))
            _dpf_ty += (_b[3] - _b[1]) + _dpf_tag_gap
        out_path = os.path.join(out_dir, "blank.png")
        os.makedirs(out_dir, exist_ok=True)
        img.save(out_path)

        print("Lagret intro-side med tekst:", out_path)
        return [out_path]




    base_path = os.path.join(base_dir, page["filename"])

    # RYGGRAD-FIX: ryggrad hentes fra script/ryggrad/<slug>/ (ligger normalt ikke
    # i ordre-input). MÅ stå før base_path-eksistenssjekken under, ellers bailer
    # den tidlige "Fant ikke bilde"-returen ut før ryggrad resolves.
    if os.path.basename(page.get("filename", "")).lower() == "ryggrad.png":
        _rygg = resolve_ryggrad_path(base_dir)
        if not _rygg:
            print("Fant ingen ryggrad (script/ryggrad eller ordre-input):", page["filename"])
            return []
        _rimg = Image.open(_rygg).convert("RGBA")
        _rout = os.path.join(out_dir, page["filename"])
        os.makedirs(out_dir, exist_ok=True)
        _rimg.save(_rout)
        print("Lagret ryggrad:", _rout, "(kilde:", _rygg + ")")
        return [_rout]

    if os.path.basename(page.get("filename", "")).lower().startswith("bakside"):
        _bakside = resolve_bakside_path(page["filename"], base_dir)
        if _bakside:
            base_path = _bakside

    if not os.path.exists(base_path):
        print("Fant ikke bilde:", base_path)
        return []

    img = Image.open(base_path).convert("RGBA")
    draw = ImageDraw.Draw(img)

    img_w, img_h = img.size
    scale_x = img_w / INNER_WIDTH
    scale_y = img_h / INNER_HEIGHT
    scale   = min(scale_x, scale_y)

    def sx(v: int) -> int:
        return int(v * scale_x)

    def sy(v: int) -> int:
        return int(v * scale_y)

    generated_paths: List[str] = []

    # ------------------------ cover ------------------------
    if page.get("type") == "cover":
        text = page.get("text")
        is_front = page.get("filename", "").lower().startswith("forside")

        if is_front:
            if text is not None:
                draw_centered_title_cover(img, text)

            try:
                logo = Image.open(FRONT_LOGO_PATH).convert("RGBA")
                max_logo_width = int(img_w * 0.35)
                logo_scale = min(max_logo_width / logo.width, 1.0)
                new_size = (int(logo.width * logo_scale), int(logo.height * logo_scale))
                logo = logo.resize(new_size, Image.LANCZOS)

                lx = (img_w - logo.width) // 2
                ly = img_h - logo.height - sy(25)
                img.alpha_composite(logo, (lx, ly))
            except FileNotFoundError:
                print("Fant ikke forside-logo:", FRONT_LOGO_PATH)

            out_path = os.path.join(out_dir, page["filename"])
            os.makedirs(out_dir, exist_ok=True)
            img.save(out_path)
            print("Lagret:", out_path)
            generated_paths.append(out_path)
            return generated_paths

    # ------------------------ ryggrad (skal IKKE splittes) ------------------------
    if os.path.basename(page.get("filename", "")).lower() == "ryggrad.png":
        ryggrad_src = resolve_ryggrad_path(base_dir)
        if ryggrad_src:
            img = Image.open(ryggrad_src).convert("RGBA")
        out_path = os.path.join(out_dir, page["filename"])
        os.makedirs(out_dir, exist_ok=True)
        img.save(out_path)
        print("Lagret:", out_path)
        return [out_path]


    # ------------------------ innersider ------------------------
    side = page.get("side", "right")

    if side == "left":
        x1, x2 = sx(LEFT_X1), sx(LEFT_X2)
    elif side == "right":
        x1, x2 = sx(RIGHT_X1), sx(RIGHT_X2)
    else:
        x1, x2 = sx(200), img_w - sx(200)

    y = sy(MARGIN_Y + 150)

    # ---------- bakside (center + back-logo) ----------
    if page.get("filename", "").lower().startswith("bakside"):
        column_width = sx(850)
        x_center = img_w // 2
        x1 = x_center - column_width // 2
        x2 = x_center + column_width // 2

        y = sy(120)
        line_spacing = max(6, int(16 * scale_y))

        for block in page.get("blocks", []):
            base_size = block.get("font_size", 30)
            font_size = max(8, int(base_size * scale))
            back_font_path = BACK_TEXT_FONT if os.path.exists(BACK_TEXT_FONT) else INNER_FONT
            font = ImageFont.truetype(back_font_path, font_size)
            box = (x1, y, x2, sy(INNER_HEIGHT - 350))

            use_gradient = "color" not in block

            # Ett samlet, mykt felt bak hele bakside-teksten - ikke per linje.
            if block.get("text_backdrop", True):
                draw_text_backdrop(
                    img, box, block["text"], font, line_spacing,
                    highlights=block.get("highlights", []),
                    align="center", shape="block",
                    strength=block.get("text_backdrop_strength", "strong"),
                )

            draw_text(
                draw=draw,
                text=block["text"],
                box=box,
                font=font,
                color=block.get("color", TEXT_COLOR),
                stroke_color=STROKE_COLOR,
                line_spacing=line_spacing,
                highlights=block.get("highlights", []),
                gradient=DEFAULT_TEXT_GRADIENT if use_gradient else None,
                img=img,
                align="center",

            )
            y += font_size * 2.3

        try:
            logo = Image.open(BACK_LOGO_PATH).convert("RGBA")
            max_logo_width = int(img_w * 0.30)
            logo_scale = min(max_logo_width / logo.width, 1.0)
            new_size = (int(logo.width * logo_scale), int(logo.height * logo_scale))
            logo = logo.resize(new_size, Image.LANCZOS)

            lx = (img_w - logo.width) // 2
            ly = img_h - logo.height - sy(170)
            img.alpha_composite(logo, (lx, ly))
        except FileNotFoundError:
            print("Fant ikke bakside-logo:", BACK_LOGO_PATH)

        out_path = os.path.join(out_dir, page["filename"])
        os.makedirs(out_dir, exist_ok=True)
        img.save(out_path)
        print("Lagret:", out_path)
        generated_paths.append(out_path)
        return generated_paths

  


    # ---------- vanlige innersider ----------
    for block in page.get("blocks", []):
        base_size = block.get("font_size", DEFAULT_FONT_SIZE)
        font_size = max(8, int(base_size * scale))
        font = ImageFont.truetype(INNER_FONT, font_size)

        # ---- per-block justeringer (valgfrie) ----
        x_offset     = block.get("x_offset", 0)
        y_offset     = block.get("y_offset", 0)
        width_offset = block.get("width_offset", 0)

        bx1 = x1 + sx(x_offset)
        bx2 = x2 + sx(width_offset)
        by1 = y  + sy(y_offset)
        by2 = sy(INNER_HEIGHT - 80)

        box = (bx1, by1, bx2, by2)


        # ✅ Gradient er default. Slå av per blokk med: "use_gradient": False
        use_gradient = "color" not in block
        text_line_spacing = max(6, int(16 * scale_y))
        shadow_offset = max(2, int(font_size * 0.05))
        shadow_blur = max(2, int(font_size * 0.07))

        if block.get("text_backdrop", False):
            draw_text_backdrop(img, box, block["text"], font, text_line_spacing, highlights=block.get("highlights", []), strength=block.get("text_backdrop_strength", "normal"))

        draw_text(
            draw=draw,
            text=block["text"],
            box=box,
            font=font,
            color=block.get("color", TEXT_COLOR),
            stroke_color=STROKE_COLOR,
            line_spacing=text_line_spacing,
            highlights=block.get("highlights", []),
            gradient=DEFAULT_TEXT_GRADIENT if use_gradient else None,
            img=img,
            shadow_offset=shadow_offset,
            shadow_blur=shadow_blur,
            shadow_alpha=115,
        )

        if "y_offset" not in block:
            y += font_size * 4

    generated_paths.extend(save_split_a5(img, out_dir, page["filename"]))
    return generated_paths


def process_book(base_dir: str, out_dir: str, child_name: str, cover_type: str = "softcover", gelato_api_key: str = None):
    os.makedirs(out_dir, exist_ok=True)

    pages = build_pages(child_name)

    # Render alle sidetyper (innersider + cover-deler) til out_dir
    all_paths: List[str] = []
    for page in pages:
        paths = render_page(page=page, base_dir=base_dir, out_dir=out_dir)
        all_paths.extend(paths)

    # Skille cover fra innersider basert på FILNAVN (robust og i tråd med resten av scriptet)
    def is_cover_path(p: str) -> bool:
        b = os.path.basename(p).lower()
        return b.startswith("forside") or b.startswith("bakside") or b == "ryggrad.png"

    inner_paths = []
    cover_paths = []

    for p in all_paths:
        name = os.path.basename(p).lower()
        if name == "ryggrad.png" or name.startswith("forside") or name.startswith("bakside"):
            cover_paths.append(p)
        else:
            inner_paths.append(p)

    cover_rendered = {os.path.basename(p).lower(): p for p in cover_paths}




    # -------------------- PDF 1: INNERSIDER --------------------
    if inner_paths:
        inner_pdf_path = os.path.join(out_dir, f"{child_name}_innersider.pdf")
        inner_paths = log_inner_page_order(
            inner_paths,
            script_name=os.path.basename(__file__),
            expected_count=EXPECTED_INNER_PAGES,
        )

        PAGE_INCH = 8.5  # du sa at bleed ikke trengs (Lulu godkjente uten bleed)
        PAGE_SIZE = PAGE_INCH * inch

        c = canvas.Canvas(inner_pdf_path, pagesize=(PAGE_SIZE, PAGE_SIZE))

        tmp_dir = os.path.join(out_dir, "_pdf_tmp_inner")
        os.makedirs(tmp_dir, exist_ok=True)

        for i, path in enumerate(inner_paths):
            im = Image.open(path)

            # Robust: tving RGB (unngår alpha-problemer i PDF)
            if im.mode in ("RGBA", "P", "LA"):
                im = im.convert("RGB")

            # Robust: tving korrekt pikselstørrelse pr side (2625x2625)
            if im.size != (LULU_PAGE_PX, LULU_PAGE_PX):
                im = im.resize((LULU_PAGE_PX, LULU_PAGE_PX), Image.LANCZOS)

            tmp_path = os.path.join(tmp_dir, f"page_{i:04d}.jpg")
            im.save(tmp_path, "JPEG", quality=95)

            c.drawImage(tmp_path, 0, 0, width=PAGE_SIZE, height=PAGE_SIZE)
            c.showPage()

        c.save()
        validate_inner_pdf_page_count(inner_pdf_path, EXPECTED_INNER_PAGES)
        print("Innersider PDF lagret:", inner_pdf_path)
    else:
        print("Ingen innersider å bygge PDF av.")

        # -------------------- PDF 2: COVER (Lulu-safe: eksakt 19 x 10.25) --------------------
    need = ["bakside(dragejakten).png", "ryggrad.png", "forside(dragejakten).png"]
    missing = [n for n in need if n not in cover_rendered]

    if missing:
        print("Cover PDF ble IKKE laget. Mangler rendret cover-del(er):", ", ".join(missing))
        return

    back_path  = cover_rendered["bakside(dragejakten).png"]
    spine_path = cover_rendered["ryggrad.png"]
    front_path = cover_rendered["forside(dragejakten).png"]

    back  = Image.open(back_path).convert("RGB")
    spine = Image.open(spine_path).convert("RGB")
    front = Image.open(front_path).convert("RGB")

    # ---- Bygg eksakt Lulu canvas i px (det som låser MediaBox riktig) ----


    trim_px   = in_to_px(LULU_TRIM_IN)
    spine_px  = in_to_px(LULU_SPINE_IN)

    bleed_tb_px = in_to_px(BLEED_TOP_BOTTOM_IN)
    bleed_lr_px = in_to_px(BLEED_LEFT_RIGHT_IN)



# Bakside: bleed kun på ytterkant
    back_box_w = trim_px + bleed_lr_px

# Ryggrad: ingen bleed
    spine_box_w = spine_px

# Forside: bleed kun på ytterkant
    front_box_w = trim_px + bleed_lr_px


    # Full høyde = trim + bleed top/bottom*2
    panel_h_px  = trim_px + bleed_tb_px*2

   
    total_w_px = (trim_px * 2) + spine_px + (bleed_lr_px * 2)
    total_h_px = panel_h_px    


    back_f  = cover_fit_with_bleed(back, back_box_w, panel_h_px, trim_px, trim_px, align="right")
    spine_f = cover_fit_with_bleed(spine, spine_px, panel_h_px, spine_px, trim_px, align="center")
    front_f = cover_fit_with_bleed(front, front_box_w, panel_h_px, trim_px, trim_px, align="left")






    cover_img = Image.new("RGB", (total_w_px, total_h_px), (255, 255, 255))

# X-posisjon starter med ytter-bleed på venstre side
    x = 0

# Bakside (har bleed på venstre side)
    cover_img.paste(back_f, (x, 0))
    x += back_box_w

# Ryggrad (ingen bleed)
    cover_img.paste(spine_f, (x, 0))
    x += spine_px

# Forside (har bleed på høyre side)
    cover_img.paste(front_f, (x, 0))


    cover_tmp = os.path.join(out_dir, "_cover_composite.jpg")
    cover_img.save(cover_tmp, "JPEG", quality=95)

    cover_pdf_path = os.path.join(out_dir, f"{child_name}_cover.pdf")

    # ✅ Kritisk: lås PDF MediaBox til eksakt Lulu-størrelse (19 x 10.25)
    c = canvas.Canvas(
        cover_pdf_path,
        pagesize=(LULU_COVER_W_IN * inch, LULU_COVER_H_IN * inch)
    )
    c.drawImage(
        cover_tmp, 0, 0,
        width=LULU_COVER_W_IN * inch,
        height=LULU_COVER_H_IN * inch
    )
    c.showPage()
    c.save()

    print("Cover PDF lagret (Lulu-safe):", cover_pdf_path)

    cover_info = build_gelato_cover_pdf(
        back_image_path=back_path,
        spine_image_path=spine_path,
        front_image_path=front_path,
        out_pdf_path=cover_pdf_path,
        cover_type=cover_type,
        page_count=len(inner_paths),
        api_key=gelato_api_key,
    )
    print(
        "Cover PDF oppdatert til Gelato-size:",
        cover_pdf_path,
        f"[{cover_info['width_mm']}mm x {cover_info['height_mm']}mm]",
    )


    # -------------------- CLEANUP --------------------


    keep = {
        f"{child_name}_innersider.pdf",
        f"{child_name}_cover.pdf",
    }

    for fname in os.listdir(out_dir):
        path = os.path.join(out_dir, fname)

    # behold kun de ferdige PDF-ene
        if fname in keep:
            continue

    # slett alt annet
        if os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)






def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, help="Barnets navn")
    parser.add_argument("--base", required=True, help="Mappe med base-bilder")
    parser.add_argument("--out", required=True, help="Mappe der resultatbildene skal lagres")
    parser.add_argument("--cover-type", default="softcover", help="Gelato cover type: hardcover eller softcover")
    parser.add_argument("--gelato-api-key", default=os.environ.get("GELATO_API_KEY"), help="Gelato API key")

    args = parser.parse_args()

    process_book(
        base_dir=args.base,
        out_dir=args.out,
        child_name=args.name,
        cover_type=args.cover_type,
        gelato_api_key=args.gelato_api_key,
    )




# --- DreamPage translated text table (sv) ---
_DREAMPAGE_TRANSLATIONS = {
  "{name} og\nDragejakten": "{name} och\nDrakjakten",
  "Takk for at du kjøpte denne personlige historien!\nI denne boken følger vi {name} på et eventyr i en verden full av drager.\n{name} lærer at ekte mot er å hjelpe noen som trenger det.\nVi håper historien bringer glede, spenning og fantasifulle øyeblikk.": "Tack för att du köpte den här personliga berättelsen!\nI den här boken följer vi {name} på ett äventyr i en värld full av drakar.\n{name} lär sig att riktigt mod är att hjälpa någon som behöver det.\nVi hoppas att berättelsen ger glädje, spänning och fantasifulla stunder.",
  "{name} likte å utforske skogen.\nHan kjente hver sti og hvert eneste tre.\nMen denne dagen fant han noe han aldri hadde sett før.\nEnorme fotspor i bakken – så store at begge føttene hans fikk plass i ett av dem.": "{name} tyckte om att utforska skogen.\nHan kände varje stig och varje enda träd.\nMen den här dagen hittade han något han aldrig hade sett förut.\nEnorma fotspår i marken – så stora att båda hans fötter fick plats i ett av dem.",
  "Sporene fortsatte mellom trærne.\n{name} fulgte etter, dypere og dypere inn i skogen.\nGreinene lukket seg over ham, og lyden av fugler ble borte.\nHvem hadde laget dem? Og hvor kunne de føre?": "Spåren fortsatte mellan träden.\n{name} följde efter, djupare och djupare in i skogen.\nGrenarna slöt sig ovanför honom, och ljudet av fåglar tystnade.\nVem hade gjort dem? Och vart kunde de leda?",
  "Plutselig stoppet sporene foran en mørk hule i fjellet.\nFra innsiden kom et svakt blått lys som pustet, av og på.\nLangt der inne hørte han noe tungt puste i mørket.\n{name} tok mot til seg og gikk inn.": "Plötsligt stannade spåren framför en mörk grotta i berget.\nInifrån kom ett svagt blått ljus som andades, av och på.\nLångt där inne hörde han något tungt andas i mörkret.\n{name} tog mod till sig och gick in.",
  "Langt inne i hulen fikk {name} øye på noe enormt.\nEn stor blågrønn drage var lenket fast til fjellveggen!\nTunge jernlenker lå rundt beina hans.\nMen dragen så ikke farlig ut.\nDen så redd ut.": "Långt inne i grottan fick {name} syn på något enormt.\nEn stor blågrön drake satt fastkedjad vid bergväggen!\nTunga järnkedjor låg runt hans ben.\nMen draken såg inte farlig ut.\nDen såg rädd ut.",
  "{name} løp bort til dragen.\nLåsen var gammel og rusten. Han dro og vred, og dro enda en gang, helt til den endelig ga etter.\nKLANK!\nLenken falt i bakken.\nDragen var fri!": "{name} sprang fram till draken.\nLåset var gammalt och rostigt. Han drog och vred, och drog en gång till, tills det äntligen gav vika.\nKLANG!\nKedjan föll till marken.\nDraken var fri!",
  "«Takk, {name},» sa dragen. Stemmen var dyp og varm.\nMen så ble den alvorlig.\n«Sønnen min er også fanget – jeg klarer ikke å redde ham alene.»\n{name} kjente hjertet slå fortere. Men han visste med én gang hva han måtte gjøre.": "«Tack, {name},» sa draken. Rösten var djup och varm.\nMen så blev den allvarlig.\n«Min son är också fångad – jag klarar inte att rädda honom ensam.»\n{name} kände hjärtat slå fortare. Men han visste med en gång vad han måste göra.",
  "Dragen bøyde seg helt ned til bakken.\n«Hopp opp!»\n{name} klatret forsiktig opp på ryggen og holdt godt fast i de varme skjellene.\nSå spredte dragen de enorme vingene sine.": "Draken böjde sig ända ner till marken.\n«Hoppa upp!»\n{name} klättrade försiktigt upp på ryggen och höll hårt i de varma fjällen.\nSedan spred draken ut sina enorma vingar.",
  "WHOOSH!\nDe skjøt ut av hulen og høyt opp over skogen.\nVinden suste i ørene hans, og under dem ble trærne små som fyrstikker.\n{name} hadde aldri fløyet før. Han lo høyt.": "WHOOSH!\nDe sköt ut ur grottan och högt upp över skogen.\nVinden susade i hans öron, och under dem blev träden små som tändstickor.\n{name} hade aldrig flugit förut. Han skrattade högt.",
  "Snart dukket et mørkt fjell opp foran dem.\nHøyt oppe mellom gamle steinruiner satt en liten drage fanget bak et gitter.\nHan var ikke større enn {name} selv.\n«Der er han!» ropte {name}.": "Snart dök ett mörkt berg upp framför dem.\nHögt uppe bland gamla stenruiner satt en liten drake fångad bakom galler.\nHan var inte större än {name} själv.\n«Där är han!» ropade {name}.",
  "{name} snek seg inn mellom de gamle murene. Steinene var kalde og glatte.\nDen lille dragen skalv bak gitteret og trakk seg bakover.\n«Ikke vær redd,» hvisket {name}.\n«Jeg skal få deg ut.»": "{name} smög sig in mellan de gamla murarna. Stenarna var kalla och hala.\nDen lilla draken darrade bakom gallret och backade undan.\n«Var inte rädd,» viskade {name}.\n«Jag ska få ut dig.»",
  "{name} fant låsen og tok godt tak.\nÉn gang.\nTo ganger.\nKLIKK!\nPorten åpnet seg, og den lille dragen løp rett ut og gned hodet mot armen hans.": "{name} hittade låset och tog ett stadigt tag.\nEn gång.\nTvå gånger.\nKLICK!\nPorten öppnades, och den lilla draken sprang rakt ut och gned huvudet mot hans arm.",
  "Den store dragen skyndte seg fram.\nDen lille dragen kastet seg inntil faren sin, og de la vingene rundt hverandre.\n{name} smilte.\nDragejakten var endelig over.": "Den stora draken skyndade fram.\nDen lilla draken kastade sig intill sin pappa, och de lade vingarna om varandra.\n{name} log.\nDrakjakten var äntligen över.",
  "De tre fløy sammen tilbake over fjellene mens solen gikk ned.\nDen lille dragen fløy ved siden av faren sin, mens {name} satt trygt på ryggen til den store dragen.\nLangt foran dem lå et sted {name} aldri hadde sett før.": "De tre flög tillsammans tillbaka över bergen medan solen gick ner.\nDen lilla draken flög bredvid sin pappa, medan {name} satt tryggt på den stora drakens rygg.\nLångt framför dem låg en plats {name} aldrig hade sett förut.",
  "Bak fjellene lå en hemmelig dal full av drager.\nStore og små, i alle farger, fløy de over trærne.\nFør {name} dro hjem, ga dragen ham et glødende drageskjell.\n«Behold dette,» sa dragen. «En dag kan vi trenge deg igjen.»\n{name} så ned på skjellet. Plutselig begynte det å lyse enda sterkere.\nEventyret var kanskje ikke helt over likevel…": "Bakom bergen låg en hemlig dal full av drakar.\nStora och små, i alla färger, flög de över träden.\nInnan {name} åkte hem, gav draken honom ett glödande drakfjäll.\n«Behåll det här,» sa draken. «En dag kan vi behöva dig igen.»\n{name} tittade ner på drakfjället. Plötsligt började det lysa ännu starkare.\nÄventyret var kanske inte riktigt över ändå…",
  "Dypt inne i skogen finner {name} enorme fotspor – og en drage som er lenket fast i en mørk hule.\nSammen flyr de over fjellene for å redde dragens lille sønn.\nDragejakten er en spennende historie om mot, vennskap og det å hjelpe andre.\nEn personlig barnebok hvor {name} selv blir helten i sitt eget drageeventyr.": "Djupt inne i skogen hittar {name} enorma fotspår – och en drake som sitter fastkedjad i en mörk grotta.\nTillsammans flyger de över bergen för att rädda drakens lilla son.\nDrakjakten är en spännande berättelse om mod, vänskap och att hjälpa andra.\nEn personlig barnbok där {name} själv blir hjälten i sitt eget drakäventyr."
}
_DREAMPAGE_ORIGINAL_BUILD_PAGES = build_pages

def _dreampage_text_key(text: str, child_name: str) -> str:
    return str(text).replace(child_name, "{name}")

def _dreampage_sv_genitive(child_name: str) -> str:
    clean_name = str(child_name)
    return clean_name if clean_name.lower().endswith(("s", "x", "z")) else clean_name + "s"

def _dreampage_apply_translation(text: str, child_name: str) -> str:
    key = _dreampage_text_key(text, child_name)
    translated = _DREAMPAGE_TRANSLATIONS.get(key)
    if translated is None:
        return text
    return (
        translated
        .replace("{name_genitive}", _dreampage_sv_genitive(child_name))
        .replace("{name}", child_name)
    )

def build_pages(child_name: str):
    pages = _DREAMPAGE_ORIGINAL_BUILD_PAGES(child_name)
    for page in pages:
        if isinstance(page.get("text"), str):
            page["text"] = _dreampage_apply_translation(page["text"], child_name)
        for block in page.get("blocks") or []:
            if isinstance(block.get("text"), str):
                block["text"] = _dreampage_apply_translation(block["text"], child_name)
    return pages


# --- DreamPage universal inner text layout ---
def _dp_clean_word(word: str) -> str:
    return re.sub(r"^[^\w??????????????????????????????]+|[^\w??????????????????????????????]+$", "", str(word), flags=re.UNICODE).lower()


def _dp_highlight_font(size: int, fallback):
    candidates = []
    if "HIGHLIGHT_FONT" in globals():
        candidates.append(globals()["HIGHLIGHT_FONT"])
    candidates.append(os.path.join(SCRIPT_DIR, "Georgia Bold.ttf"))
    for path in candidates:
        try:
            if path and os.path.exists(path):
                return ImageFont.truetype(path, size)
        except Exception:
            pass
    return fallback


def draw_text_backdrop(img, box, text, font, line_spacing, highlights=None, align="left", strength="normal", shape="lines"):
    # Per-line "pill" backdrop. Mirrors the exact layout the shared text engine
    # draws (balanced wrap + auto-shrink) so each pill hugs its own line instead
    # of one greedy, too-wide rectangle. Falls back to a simple greedy wrap if
    # the engine internals are unavailable.
    x1, y1, x2, y2 = box
    max_width = max(1, x2 - x1)
    max_height = max(1, y2 - y1)
    measure = ImageDraw.Draw(img)

    line_boxes = []
    used_font = font

    try:
        from dream_text_layout import _layout_text, _load_font_like
    except Exception:
        _layout_text = None
        _load_font_like = None

    if _layout_text is not None:
        cur_font = font
        cur_spacing = line_spacing
        paragraphs, total_height = _layout_text(measure, text, box, cur_font, cur_spacing, highlights)
        min_size = max(16, int(font.size * 0.78))
        while total_height > max_height and cur_font.size > min_size:
            next_size = cur_font.size - 1
            cur_font = _load_font_like(cur_font, next_size)
            cur_spacing = max(3, int(line_spacing * (next_size / max(font.size, 1))))
            paragraphs, total_height = _layout_text(measure, text, box, cur_font, cur_spacing, highlights)
        used_font = cur_font

        y = y1
        for lines, is_blank in paragraphs:
            if is_blank:
                y += cur_font.size + cur_spacing
                continue
            for runs, line_width in lines:
                if align == "center":
                    x = x1 + max(0, int((max_width - line_width) / 2))
                elif align == "right":
                    x = x2 - int(line_width)
                else:
                    x = x1
                top = None
                bottom = None
                cursor = x
                for piece, piece_font in runs:
                    bbox = measure.textbbox((int(cursor), int(y)), piece, font=piece_font)
                    top = bbox[1] if top is None else min(top, bbox[1])
                    bottom = bbox[3] if bottom is None else max(bottom, bbox[3])
                    cursor += measure.textlength(piece, font=piece_font)
                if top is None or bottom is None:
                    top = int(y)
                    bottom = int(y + cur_font.size)
                line_boxes.append((int(x), int(top), int(x + line_width), int(bottom)))
                y += cur_font.size + cur_spacing
            y += cur_spacing
    else:
        hl_set = {_dp_clean_word(h) for h in (highlights or []) if str(h).strip()}
        highlight_font = _dp_highlight_font(font.size, font)
        y = y1

        def flush(line_words, line_fonts, line_width):
            nonlocal y
            if not line_words:
                return
            cursor = x1
            top = None
            bottom = None
            for piece, piece_font in zip(line_words, line_fonts):
                bbox = measure.textbbox((int(cursor), int(y)), piece, font=piece_font)
                top = bbox[1] if top is None else min(top, bbox[1])
                bottom = bbox[3] if bottom is None else max(bottom, bbox[3])
                cursor += measure.textlength(piece, font=piece_font)
            if top is None:
                top = int(y)
                bottom = int(y + font.size)
            line_boxes.append((int(x1), int(top), int(x1 + line_width), int(bottom)))
            y += font.size + line_spacing

        for para in str(text).split("\n"):
            para = para.strip()
            if not para:
                y += font.size + line_spacing
                continue
            line_words = []
            line_fonts = []
            line_width = 0
            for word in para.split(" "):
                if not word:
                    continue
                word_font = highlight_font if _dp_clean_word(word) in hl_set else font
                piece = word if not line_words else " " + word
                piece_width = measure.textlength(piece, font=word_font)
                if line_words and line_width + piece_width > max_width:
                    flush(line_words, line_fonts, line_width)
                    line_words = [word]
                    line_fonts = [word_font]
                    line_width = measure.textlength(word, font=word_font)
                else:
                    line_words.append(piece)
                    line_fonts.append(word_font)
                    line_width += piece_width
            flush(line_words, line_fonts, line_width)
            y += line_spacing

    if not line_boxes:
        return

    is_strong = strength == "strong"
    fs = used_font.size
    pad_x = max(18, int(fs * 0.45))
    pad_y = max(6, int(fs * 0.17))
    shadow_alpha = 165 if is_strong else 120
    plate_alpha = 88 if is_strong else 64
    blur_amount = max(10 if is_strong else 7, int(fs * (0.20 if is_strong else 0.16)))

    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    plate = Image.new("RGBA", img.size, (0, 0, 0, 0))
    pd = ImageDraw.Draw(plate)

    if shape == "block":
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
        left = max(0, lb[0] - pad_x)
        top = max(0, lb[1] - pad_y)
        right = min(img.size[0], lb[2] + pad_x)
        bottom = min(img.size[1], lb[3] + pad_y)
        if right <= left or bottom <= top:
            continue
        if shape == "block":
            radius = max(24, int(fs * 0.9))
        else:
            radius = max(6, min((right - left) // 2, int((bottom - top) * 0.40)))
        sd.rounded_rectangle((left, top, right, bottom), radius=radius, fill=(0, 0, 0, shadow_alpha))
        pd.rounded_rectangle((left, top, right, bottom), radius=radius, fill=(0, 0, 0, plate_alpha))
        drew = True

    if not drew:
        return

    shadow = shadow.filter(ImageFilter.GaussianBlur(blur_amount))
    img.alpha_composite(shadow)
    img.alpha_composite(plate)
_DP_STOPWORDS = {
    "the", "and", "with", "that", "this", "then", "there", "were", "was", "his", "her", "she", "him", "you", "your", "they", "them", "from", "into", "over", "under", "again", "just", "like", "because", "when", "what", "where", "while", "could", "would", "should", "very", "every", "their", "about", "after", "before", "through",
    "det", "den", "der", "som", "var", "han", "hun", "seg", "sin", "sitt", "sine", "til", "med", "for", "fra", "over", "under", "etter", "f?r", "igjen", "ikke", "n?r", "mens", "alle", "hele", "inn", "ut", "opp", "ned", "hans", "henne", "dette", "hadde", "kunne", "skulle", "ville", "ble", "blei", "blir", "bare", "rundt", "gjennom", "mellom", "fram", "frem", "mot",
    "ein", "eit", "dei", "dei", "ikkje", "fr?", "vart", "vere", "vera", "sj?lv", "noko", "nokon", "kva", "kor", "d?", "no", "?g",
    "och", "att", "det", "den", "som", "var", "han", "hon", "sig", "sin", "sitt", "sina", "till", "med", "f?r", "fr?n", "?ver", "under", "efter", "f?re", "igen", "inte", "n?r", "medan", "alla", "hela", "hans", "henne", "hade", "kunde", "skulle", "ville", "blev", "bara", "runt", "genom", "mellan", "fram", "mot"
}


def _dp_auto_highlights(text: str, child_name: str, existing=None) -> list[str]:
    merged = []
    seen = set()

    def add(word):
        clean = _dp_clean_word(word)
        if not clean or clean in seen or len(clean) < 3:
            return
        seen.add(clean)
        merged.append(word)

    for word in existing or []:
        add(str(word))
    for part in [child_name, *str(child_name).replace("-", " ").split()]:
        if part:
            add(part)

    words = re.findall(r"[A-Za-z??????????????????????????????]+", str(text))
    scored = []
    for idx, word in enumerate(words):
        clean = _dp_clean_word(word)
        if len(clean) < 4 or clean in _DP_STOPWORDS or clean in seen:
            continue
        score = len(clean) + (3 if word[:1].isupper() else 0) - idx * 0.01
        scored.append((score, idx, word, clean))
    scored.sort(key=lambda item: (-item[0], item[1]))
    for _, _, word, _ in scored:
        add(word)
        if len(merged) >= 8:
            break
    return merged


def _dp_balanced_story_split(text: str):
    raw = str(text).strip()
    if not raw:
        return None
    # Flatten the page text into sentence units across paragraphs, then pick
    # the break point that makes the two halves as equal in length as
    # possible (balanced by character count instead of paragraph count).
    units = []
    for para in raw.split("\n"):
        para = para.strip()
        if not para:
            continue
        clean = re.sub(r"\s+", " ", para)
        for sentence in re.split(r"(?<=[.!?])\s+", clean):
            sentence = sentence.strip()
            if sentence:
                units.append(sentence)
    if len(units) < 2:
        return None

    total = sum(len(u) for u in units)
    target = total / 2.0
    best = 1
    best_delta = float("inf")
    cum = 0
    for idx in range(len(units) - 1):
        cum += len(units[idx])
        delta = abs(cum - target)
        if delta < best_delta:
            best = idx + 1
            best_delta = delta
    first = " ".join(units[:best]).strip()
    second = " ".join(units[best:]).strip()
    return (first, second) if first and second else None
def _dp_page_number(filename: str) -> int | None:
    match = re.match(r"\D*(\d+)", str(filename))
    return int(match.group(1)) if match else None


def _dp_layout_offsets(filename: str):
    # Nullstilt 2026-09-04 sammen med de nye innersidene. De gamle
    # per-side-justeringene var tunet mot bilder som ikke finnes lenger.
    number = _dp_page_number(filename)
    top_y = 25
    bottom_y = 345
    return number, top_y, bottom_y


def _dp_mark_backdrop(block: dict, filename: str, child_name: str, *, second: bool = False) -> None:
    block["text_backdrop"] = True
    block["color"] = "#FFFFFF"
    block["highlights"] = _dp_auto_highlights(block.get("text", ""), child_name, block.get("highlights", []))
    number = _dp_page_number(filename)
    # Lyse eller travle halvsider trenger tyngre plate bak teksten.
    if number in (3, 6, 7, 8, 10, 12, 13, 14):
        block["text_backdrop_strength"] = "strong"

def _dp_split_inner_story_blocks(page: dict, child_name: str) -> None:
    if page.get("type") != "inner":
        return
    blocks = page.get("blocks") or []
    filename = str(page.get("filename", ""))
    side = page.get("side", "right")

    if len(blocks) != 1:
        for idx, block in enumerate(blocks):
            if isinstance(block, dict) and block.get("text"):
                _dp_mark_backdrop(block, filename, child_name, second=idx > 0)
        return

    block = blocks[0]
    split = _dp_balanced_story_split(block.get("text", ""))
    if not split:
        _dp_mark_backdrop(block, filename, child_name)
        return

    first, second = split
    number, top_y, bottom_y = _dp_layout_offsets(filename)
    first_block = dict(block)
    second_block = dict(block)
    first_block["text"] = first
    second_block["text"] = second
    first_block["y_offset"] = top_y
    second_block["y_offset"] = bottom_y
    first_block["font_size"] = max(24, min(int(first_block.get("font_size", globals().get("DEFAULT_FONT_SIZE", 30))), 30))
    second_block["font_size"] = max(24, min(int(second_block.get("font_size", globals().get("DEFAULT_FONT_SIZE", 30))), 30))
    first_block.setdefault("width_offset", 95)
    second_block.setdefault("width_offset", 95)
    _dp_mark_backdrop(first_block, filename, child_name, second=False)
    _dp_mark_backdrop(second_block, filename, child_name, second=True)

    if side == "left":
        second_block["x_offset"] = int(second_block.get("x_offset", 0)) - 10
    else:
        second_block["x_offset"] = int(second_block.get("x_offset", 0)) + 10
    if number == 7:
        first_block["x_offset"] = 25
        second_block["x_offset"] = 25
    page["blocks"] = [first_block, second_block]


def _dp_apply_universal_layout(pages, child_name: str):
    for page in pages:
        for block in page.get("blocks") or []:
            if isinstance(block, dict) and block.get("text"):
                block["highlights"] = _dp_auto_highlights(block.get("text", ""), child_name, block.get("highlights", []))
        _dp_split_inner_story_blocks(page, child_name)
    return pages


_DREAM_UNIVERSAL_ORIGINAL_BUILD_PAGES = build_pages


def build_pages(child_name: str):
    return _dp_apply_universal_layout(_DREAM_UNIVERSAL_ORIGINAL_BUILD_PAGES(child_name), child_name)

if __name__ == "__main__":
    main()

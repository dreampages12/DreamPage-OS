


from reportlab.pdfgen import canvas
from reportlab.lib.units import inch

import shutil  

import os
import sys
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

# Lastpage(superhelt).png ligger etter blank-back, så total innersider = 31.
EXPECTED_INNER_PAGES = 31

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# DP_ROOT er DreamPage-roten: mappa som inneholder books/. Den ble regnet ut
# som dirname(SCRIPT_ROOT_DIR) den gangen tekstscriptene laa i <rot>/script/<sprak>.
# Etter flyttingen til <rot>/flow/text/<sprak> ga det <rot>/flow, og ALLE
# bok-spesifikke sider (dreampage-first, blank-back) falt stille tilbake til
# den delte gamle malen. Vi gaar oppover til vi finner books/ i stedet, slik at
# en ny flytting ikke kan gjenskape feilen.
def _dp_find_root(start):
    cur = os.path.abspath(start)
    while True:
        if os.path.isdir(os.path.join(cur, "books")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            raise RuntimeError(
                "Fant ingen DreamPage-rot (mappe med books/) over " + str(start))
        cur = parent


DP_ROOT = _dp_find_root(SCRIPT_DIR)


def _dp_first(book_page):
    """Bokas EGEN aapningsside, med den delte gamle malen som naudloesning.

    Fallbacket var stille foer: ordre 1506 ble bygget om med den delte malen
    uten at noe sa fra, fordi stien til bokas egen side pekte feil. Naa ropes
    det - en ombygging som skriver dette skal ikke sendes til trykk.
    """
    if os.path.exists(book_page):
        return book_page
    shared = os.path.join(SCRIPT_DIR, "dreampage-first.png")
    sys.stderr.write(
        "[FEIL] Bokas egen aapningsside mangler: %s\n"
        "[FEIL] Faller tilbake til den DELTE gamle malen: %s\n"
        "[FEIL] Denne boka skal IKKE trykkes med den sida.\n"
        % (book_page, shared))
    return shared


SCRIPT_LOCALES = {"nb", "nn", "en-US", "en-GB", "sv"}
SCRIPT_LOCALE = os.path.basename(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR) in SCRIPT_LOCALES else "nb"
SCRIPT_ROOT_DIR = os.path.dirname(SCRIPT_DIR) if SCRIPT_LOCALE in SCRIPT_LOCALES else SCRIPT_DIR
LOGO_DIR = os.path.join(SCRIPT_ROOT_DIR, "logo", SCRIPT_LOCALE)
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

COVER_FONT       = os.path.join(SCRIPT_DIR, "PlayfairDisplay.ttf")
COVER_TITLE_FONT = os.path.join(SCRIPT_DIR, "Trebuchet MS Bold.ttf")
INNER_FONT     = os.path.join(SCRIPT_DIR, "Georgia.ttf")

STYRKEN_DREAMPAGE_FIRST = os.path.join(
    DP_ROOT, "books", "den-skjulte-styrken", "dreampage-first-styrken.png"
)
DREAMPAGE_FIRST_TAGLINE = "Trykt med omtanke for\nkvalitet"
HIGHLIGHT_FONT = os.path.join(SCRIPT_DIR, "Georgia Bold.ttf")
BACK_TEXT_FONT = os.path.join(SCRIPT_ROOT_DIR, "pre", "Fredoka.ttf")

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


def _layout_wrapped_text_lines(draw, text, max_width, font, line_spacing, highlights=None):
    if highlights is None:
        hl_set = set()
    else:
        hl_set = {h.strip().lower() for h in highlights}

    base_font = font
    highlight_font = ImageFont.truetype(HIGHLIGHT_FONT, base_font.size)
    lines = []
    y = 0

    def push_line(width):
        nonlocal y
        lines.append({"width": int(width), "y": y})
        y += base_font.size + line_spacing

    for para in str(text).split("\n"):
        para = para.strip()
        if not para:
            y += base_font.size + line_spacing
            continue

        line_width = 0
        has_words = False
        for word in para.split(" "):
            clean = word.strip(".,!?:;\"'").lower()
            fnt = highlight_font if clean in hl_set else base_font
            piece = word if not has_words else " " + word
            piece_width = draw.textlength(piece, font=fnt)

            if has_words and line_width + piece_width > max_width:
                push_line(line_width)
                line_width = draw.textlength(word, font=fnt)
                has_words = True
            else:
                line_width += piece_width
                has_words = True

        if has_words:
            push_line(line_width)

        y += line_spacing

    return lines


def measure_wrapped_text(draw, text, max_width, font, line_spacing, highlights=None):
    lines = _layout_wrapped_text_lines(draw, text, max_width, font, line_spacing, highlights=highlights)
    if not lines:
        return 0, font.size

    max_line_width = max(line["width"] for line in lines)
    total_h = lines[-1]["y"] + font.size
    return max_line_width, max(total_h, font.size)


def draw_text_backdrop(img, box, text, font, line_spacing, highlights=None, align="left", strength="normal"):
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

    drew = False
    for lb in line_boxes:
        left = max(0, lb[0] - pad_x)
        top = max(0, lb[1] - pad_y)
        right = min(img.size[0], lb[2] + pad_x)
        bottom = min(img.size[1], lb[3] + pad_y)
        if right <= left or bottom <= top:
            continue
        radius = max(6, min((right - left) // 2, int((bottom - top) * 0.40)))
        sd.rounded_rectangle((left, top, right, bottom), radius=radius, fill=(0, 0, 0, shadow_alpha))
        pd.rounded_rectangle((left, top, right, bottom), radius=radius, fill=(0, 0, 0, plate_alpha))
        drew = True

    if not drew:
        return

    shadow = shadow.filter(ImageFilter.GaussianBlur(blur_amount))
    img.alpha_composite(shadow)
    img.alpha_composite(plate)
# ------------------------------------------------------------
#  FORSIDE-TITTEL - navn som tekst + Styrken-logo som linje 2
# ------------------------------------------------------------

def remove_white_background(logo_img, thresh=25, defringe_thresh=0):
    """Flood fill white background from image edges."""
    from PIL import ImageDraw as _ID

    logo_rgba = logo_img.convert("RGBA")
    w, h = logo_rgba.size
    seeds = [
        (0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
        (w // 2, 0), (w // 2, h - 1),
        (0, h // 2), (w - 1, h // 2),
    ]
    for pt in seeds:
        px = logo_rgba.getpixel(pt)
        if px[3] > 0 and max(255 - px[0], 255 - px[1], 255 - px[2]) <= thresh:
            _ID.floodfill(logo_rgba, pt, (0, 0, 0, 0), thresh=thresh)

    if defringe_thresh > 0:
        pix = logo_rgba.load()
        to_fix = []
        for y in range(h):
            for x in range(w):
                r, g, b, a = pix[x, y]
                if a == 0:
                    continue
                dist = max(255 - r, 255 - g, 255 - b)
                if dist > defringe_thresh:
                    continue
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if 0 <= nx < w and 0 <= ny < h and pix[nx, ny][3] == 0:
                        to_fix.append((x, y, dist))
                        break
        for x, y, dist in to_fix:
            r, g, b, _ = pix[x, y]
            if dist <= 25:
                pix[x, y] = (r, g, b, 0)
            else:
                alpha = int(255 * (dist - 25) / (defringe_thresh - 25))
                pix[x, y] = (r, g, b, alpha)

    return logo_rgba


def crop_logo_to_visible_alpha(logo_img, alpha_threshold=8):
    logo_rgba = logo_img.convert("RGBA")
    alpha = logo_rgba.getchannel("A")
    bbox = alpha.point(lambda p: 255 if p > alpha_threshold else 0).getbbox()
    if bbox:
        return logo_rgba.crop(bbox)
    return logo_rgba


def resolve_front_cover_logo(base_dir: str | None = None) -> str | None:
    """Resolve Styrken cover logo from C:/DreamPage-OS/assets/logo/<locale>."""
    locale_logo_name = {
        "nb": "styrken-logo-nb.png",
        "nn": "styrken-logo-nb.png",
        "en-US": "styrken-logo-en.png",
        "en-GB": "styrken-logo-en.png",
        "sv": "styrken-logo-sv.png",
    }.get(SCRIPT_LOCALE, "styrken-logo-nb.png")

    candidates = [os.path.join(LOGO_DIR, locale_logo_name)]
    if SCRIPT_LOCALE == "nn":
        candidates.append(os.path.join(SCRIPT_ROOT_DIR, "logo", "nb", "styrken-logo-nb.png"))
    if SCRIPT_LOCALE == "en-GB":
        candidates.append(os.path.join(SCRIPT_ROOT_DIR, "logo", "en-US", "styrken-logo-en.png"))
    if SCRIPT_LOCALE == "en-US":
        candidates.append(os.path.join(SCRIPT_ROOT_DIR, "logo", "en-GB", "styrken-logo-en.png"))

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return None


def draw_centered_title_cover(img, text, base_dir: str | None = None):
    """
    Forside-tittel:
    - Linje 1: barnets navn + bindeord
    - Linje 2: Styrken-logo fra script/logo/<locale>
    Parametre matcher DP Title Tester / Preview logo-oppsettet.
    """
    draw = ImageDraw.Draw(img)
    w, h = img.size
    base = min(w, h)

    line1 = text.split("\n")[0] if text else ""
    font_small = ImageFont.truetype(COVER_TITLE_FONT, int(base * (81 / 1024)))

    gold = ((255, 255, 255), (255, 255, 255))   # ren hvit, som en-US/en-GB
    shadow = (10, 15, 25)
    top_margin = 0.03
    line_spacing = 0.04
    logo_scale = 0.78
    logo_x_offset = 0
    shadow_offset = max(3, int(font_small.size * 0.04))

    def _make_text_mask(size, x, y, t, fnt):
        mask = Image.new("L", size, 0)
        d = ImageDraw.Draw(mask)
        d.text((x, y), t, font=fnt, fill=255)
        return mask

    def _paste_gradient(base_img, mask, bbox, top, bottom):
        x0, y0, x1, y1 = bbox
        grad = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
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

    bbox1 = draw.textbbox((0, 0), line1, font=font_small)
    w1 = bbox1[2] - bbox1[0]
    h1 = bbox1[3] - bbox1[1]
    y1_pos = int(h * top_margin)
    x1_pos = (w - w1) // 2

    if line1:
        sm = _make_text_mask(img.size, x1_pos + shadow_offset, y1_pos + shadow_offset, line1, font_small)
        sm = sm.filter(ImageFilter.GaussianBlur(max(1, shadow_offset // 2)))
        img.paste((*shadow, 255), (0, 0), sm)
        tm = _make_text_mask(img.size, x1_pos, y1_pos, line1, font_small)
        bbox = draw.textbbox((x1_pos, y1_pos), line1, font=font_small)
        _paste_gradient(img, tm, bbox, gold[0], gold[1])

    logo_path = resolve_front_cover_logo(base_dir)
    if not logo_path:
        print("ADVARSEL: Fant ikke Styrken-logo i", LOGO_DIR)
        return

    logo = Image.open(logo_path).convert("RGBA")
    logo = remove_white_background(logo, thresh=25, defringe_thresh=0)
    logo = crop_logo_to_visible_alpha(logo, alpha_threshold=8)

    target_w = int(w * logo_scale)
    target_h = int(logo.height * (target_w / logo.width))
    logo = logo.resize((target_w, target_h), Image.LANCZOS)

    descender_cut = int(h1 * 0.15) if h1 else 0
    y2_pos = y1_pos + h1 - descender_cut + int(h * line_spacing)
    lx = ((w - target_w) // 2) + logo_x_offset
    lx = max(0, min(w - target_w, lx))

    shadow_blur = max(8, int(target_h * 0.20))
    shadow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    logo_alpha = logo.split()[3]
    shadow_img = Image.new("RGBA", (target_w, target_h), (*shadow, 180))
    shadow_img.putalpha(logo_alpha)
    shadow_layer.paste(shadow_img, (lx + shadow_offset, y2_pos + shadow_offset))
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(shadow_blur))
    img.alpha_composite(shadow_layer)
    img.alpha_composite(logo, (lx, y2_pos))


def draw_inside_title(img, text):
    """
    Elegant dark title for the first inside page only.
    No cover gradient, no heavy shadow.
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
    print("Lagret:", right_path)

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
            "filename": "forside(styrken).png",
            "type": "cover",
            "text": p("[NAVN] og\nDen skjulte styrken"),
        },
        {
            "filename": "ryggrad.png",
            "type": "cover",
        },

        # Side 1
        {
            "filename": "01(styrken).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Det var en helt vanlig morgen, av den typen der sola kiler i øynene og lufta lukter ny dag. (Navn) gikk den samme veien til skolen som alltid, men i dag føltes alt litt ekstra spennende.\n"
                    "Sekken dunket lett mot ryggen, og inni magen kriblet det av forventning. For i dag skulle hele klassen på tur, og det hadde (Navn) gledet seg til i ukevis."
                ),
                "font_size": 38,
                "color": "#FFFFFF",
                "highlights": ["vanlig", "sola", "spennende", "kriblet", "klassen"],
                "y_offset": 20,
                "width_offset": 140
            }],
        },

        # Side 2
        {
            "filename": "02(styrken).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Plutselig stoppet (Navn) midt i steget. En merkelig lyd kom fra et smalt smug ved siden av gata, som en svak summing blandet med et fjernt klingende ekko.\n"
                    "(Navn) klarte ikke å la være. Han gikk forsiktig nærmere, helt til han kikket inn i mørket. Der, midt i lufta, glødet noe varmt og oransje. Hva i all verden kunne det være?"
                ),
                "font_size": 38,
                "color": "#FFFFFF",
                "highlights": ["merkelig", "smug", "forsiktig", "glødet", "verden"],
                "y_offset": 30,
                "width_offset": 130

            }],
        },

        # Side 3
        {
            "filename": "03(styrken).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Lyset ble så sterkt at (Navn) måtte myse. Hele smuget badet i en gnistrende glød.\n"
                    "Da lyset roet seg, sto det noe foran ham. Et skimrende hologram svevde i lufta, og bak det hang en superhelt-drakt.\n"
                    "Hologrammet smilte og sa: «Du er den utvalgte, (Navn). Du er byens eneste håp.»"
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": ["sterkt", "skimrende", "smilte", "utvalgte", "håp"],
                "y_offset": 120,
                "x_offset": 20
            }],
        },

        # Side 4
        {
            "filename": "04(styrken).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "(Navn) løp så fort han kunne bort fra smuget, mens hjertet banket hardt i brystet. Han var redd, helt skikkelig redd.\n"
                    "«Jeg er ikke klar for dette,» hvisket (Navn) til seg selv. «Jeg er jo bare en helt vanlig gutt.»\n"
                    "Inni seg kjente han både tårer og en liten klump av sinne. Hvorfor måtte det være akkurat han som var den utvalgte?"
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": ["smuget", "banket", "hvisket", "vanlig", "utvalgte"],
            }],
        },

        # Side 5
        {
            "filename": "05(styrken).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "(Navn) klatret opp til favorittstedet sitt. Derfra kunne han se utover hele byen.\n"
                    "Han sto stille og tenkte. Langt der nede så han mørke skygger bevege seg sakte mot sentrum.\n"
                    "Var det dette hologrammet hadde ment? Skulle han virkelig redde byen alene?"
                ),
                "font_size": 32,
                "color": "#FFFFFF",
                "highlights": ["favorittstedet", "stille", "skygger", "redde"],
            }],
        },

        # Side 6
        {
            "filename": "06(styrken).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Akkurat da kom superheltdrakten flyvende ut av det blå. Den snurret raskt rundt (Navn) – én gang, to ganger – og i neste øyeblikk hadde han den på seg.\n"
                    "(Navn) tok et dypt sats, og med et høyt Swoooosh fløy han rett mot sentrum og landet midt i gata. (Navn) hadde blitt en superhelt."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": ["superheltdrakten", "snurret", "Swoooosh", "superhelt"],
            }],
        },

        # Side 7
        {
            "filename": "07(styrken).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "(Navn) kjente at hjertet fortsatt banket av redsel, men nå kunne han ikke snu. Han tok et dypt pust og tenkte på alle menneskene som trengte hjelp.\n"
                    "Langt der nede hadde skyggene sendt en søyle av sterkt, oransje lys rett opp mot himmelen. (Navn) visste at det var dit han måtte dra."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": ["banket", "menneskene", "skyggene", "himmelen", "måtte"],
                "x_offset": 100
            }],
        },

        # Side 8
        {
            "filename": "08(styrken).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Nå sto (Navn) rett foran det sterke lyset, så nær at han kjente varmen mot kinnene. Dette var øyeblikket hologrammet hadde snakket om.\n"
                    "(Navn) stilte seg støtt på bakken, knyttet nevene hardt og gjorde seg klar til å kjempe."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": ["lyset", "varmen", "nevene", "kjempe"],
                "x_offset": 100
            }],
        },

        # Side 9
        {
            "filename": "09(styrken).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Mørket samlet seg foran (Navn) og vokste til en høy skygge midt i gata. Den vred seg i luften, som om den var laget av røyk og torden.\n"
                    "(Navn) kjente redselen prikke i hendene, men han ble stående. Inni brystet våknet en varm styrke, og han visste at han måtte holde ut litt til."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": ["mørket", "skygge", "redselen", "styrke", "holde"],
                "x_offset": 100
            }],
        },

        # Side 10
        {
            "filename": "10(styrken).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "(Navn) strakte begge armene rett opp mot lyset og knyttet nevene så hardt han kunne.\n"
                    "Plutselig sprutet et sterkt, blått lys ut av hendene hans og traff den mørke skyggen med et kraftig BANG som fikk hele byen til å riste."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": ["armene", "nevene", "blått", "skyggen", "BANG", "riste"],
                "x_offset": 230,
                "width_offset": 115
            }],
        },

        # Side 11
        {
            "filename": "11(styrken).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Takket være (Navn) var byen trygg igjen. Lyset var borte, skyggene forsvunnet, og menneskene begynte å smile.\n"
                    "(Navn) hadde alltid trodd at han bare var en vanlig gutt. Men nå visste han noe viktig: han var en ekte superhelt."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": ["trygg", "skyggene", "smile", "vanlig", "superhelt"],
                "x_offset": 80
            }],
        },

        # Side 12
        {
            "filename": "12(styrken).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Plutselig dukket hologrammet opp igjen, lysende svakt og vennlig i lufta foran ham.\n"
                    "«Veldig bra jobbet, (Navn),» sa hologrammet stolt. «Hvis byen trenger hjelp igjen, finner jeg deg.»\n"
                    "(Navn) smilte. «Jeg er alltid klar.»"
                ),
                "font_size": 32,
                "color": "#FFFFFF",
                "highlights": ["hologrammet", "vennlig", "stolt", "hjelp", "klar"],
            }],
        },

        # Side 13
        {
            "filename": "13(styrken).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "(Navn) tok et siste blikk utover byen. Alt var stille nå, og lysene blinket fredelig i kveldsmørket.\n"
                    "Han tenkte på alt som hadde skjedd. (Navn) smilte, for innerst inne visste han noe viktig: Det var han som var den utvalgte."
                ),
                "font_size": 35,
                "color": "#FFFFFF",
                "highlights": ["blikk", "stille", "smilte", "utvalgte"],

            }],
        },

        # Side 14
        {
            "filename": "14(styrken).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "(Navn) hadde byttet tilbake til sine vanlige klær og gikk den samme veien til skolen som alltid.\n"
                    "Klassen var allerede på tur, og han hadde gått glipp av den. «Litt kjipt,» lo (Navn). «Men nå har jeg en helt utrolig historie å fortelle vennene mine.»"
                ),
                "font_size": 32,
                "color": "#FFFFFF",
                "highlights": ["vanlige", "skolen", "klassen", "glipp", "utrolig"],
                "width_offset": 120
            }],
        },

        # Bakside
        {
            "filename": "bakside(styrken).png",
            "type": "cover",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Denne boken handler om mot – om å være redd og likevel våge å prøve. Den viser at helter ikke alltid er store og sterke, men ofte vanlige barn som finner styrken i seg selv når det virkelig gjelder.\n"
                    "Derfor er det (Navn) som er helten i denne historien. En personlig fortelling som gir barn trygghet, selvtillit og troen på seg selv."

                ),
                "font_size": 54,
                "color": "#FFFFFF",
                "highlights": ["styrken", "mot", "helter", "sterke", "(Navn)", "helten", "troen", "våge"],

            }],
        },


     ] 

    name_highlights = [child_name]
    name_highlights.extend(part for part in child_name.replace("-", " ").split() if part)

    for page in pages:
        for block in page.get("blocks", []):
            highlights = block.setdefault("highlights", [])
            for name_word in name_highlights:
                if name_word and name_word not in highlights:
                    highlights.append(name_word)

    return pages



# ------------------------------------------------------------
#  render_page – skalering + A5-splitt (samme struktur)
# ------------------------------------------------------------

try:
    from dream_text_layout import draw_text as draw_text
except Exception as exc:
    print("Kunne ikke laste felles tekstlayout:", exc)


# ------------------------ ryggrad per språk (script/ryggrad/<book-slug>/) ------------------------
RYGGRAD_BOOK_SLUG = "den-skjulte-styrken"
RYGGRAD_LOCALES = {"nb", "nn", "en-US", "en-GB"}


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

    # ------------------------ blank side ------------------------
    if page.get("type") == "blank":
        blank_path = os.path.join(SCRIPT_DIR, "dreampage-first.png")

        if not os.path.exists(blank_path):
            raise FileNotFoundError("Fant ikke dreampage-first.png i script-mappen")

        img = Image.open(blank_path).convert("RGBA")
        draw = ImageDraw.Draw(img)

        img_w, img_h = img.size
        scale_x = img_w / INNER_WIDTH
        scale_y = img_h / INNER_HEIGHT

        # --- 1) Elegant inside-page title ---
        title_text = page.get("text")
        if title_text:
            draw_inside_title(img, title_text)

        # --- 2) Tegn beskrivende tekst ---
        for block in page.get("blocks", []):
            base_size = block.get("font_size", 40)
            font_size = int(base_size * min(scale_x, scale_y))
            font = ImageFont.truetype(INNER_FONT, font_size)

            box = (
                int(img_w * 0.18),
                int(img_h * 0.40),
                int(img_w * 0.82),
                int(img_h * 0.88)
            )

            draw_text(
                draw=draw,
                text=block["text"],
                box=box,
                font=font,
                color=block.get("color", "#111111"),
                highlights=block.get("highlights", []),
                gradient=None,
                img=img,
                align="center"
            )

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
        column_width = sx(1080)
        x_center = img_w // 2
        x1 = x_center - column_width // 2
        x2 = x_center + column_width // 2

        line_spacing = max(8, int(22 * scale_y))

        # Tekstfeltet er baandet mellom toppmargen og DreamPage-logoen nederst.
        # Blokka sentreres i det baandet slik at kort baksidetekst ikke klumper
        # seg oppe i hjornet med et tomt felt under.
        back_top = sy(110)
        back_bottom = int(img_h * 0.76)

        y = back_top
        for block in page.get("blocks", []):
            base_size = block.get("font_size", 30)
            font_size = max(8, int(base_size * scale))
            back_font_path = BACK_TEXT_FONT if os.path.exists(BACK_TEXT_FONT) else INNER_FONT
            font = ImageFont.truetype(back_font_path, font_size)
            _, _text_h = measure_wrapped_text(
                draw, block["text"], x2 - x1, font, line_spacing,
                highlights=block.get("highlights", []),
            )
            y = back_top + max(0, (back_bottom - back_top - _text_h) // 2)
            box = (x1, y, x2, back_bottom)

            use_gradient = "color" not in block


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
            ly = img_h - logo.height - sy(70)
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


def render_dreampage_first(child_name: str, out_dir: str) -> str:
    """
    Legger en personlig dedikasjon på den hvite øvre halvdelen av dreampage-first.png
    og lagrer resultatet til out_dir.
    """
    src = _dp_first(STYRKEN_DREAMPAGE_FIRST)
    dst = os.path.join(out_dir, "dreampage-first-rendered.png")

    img = Image.open(src).convert("RGBA")
    draw = ImageDraw.Draw(img)
    w, h = img.size

    title_line = f"Til {child_name}"
    body_lines = [
        "Denne boka er laga spesielt for deg.",
        f"Du er {child_name} — helten i historia.",
        "",
        "Inni deg bur det ei skjult kraft,",
        "varm og levande, sterkare enn du trur.",
        "",
        "Tru alltid på deg sjølv,",
        "akkurat som du gjer i denne historia.",
    ]

    font_title_size = int(h * 0.045)
    font_body_size  = int(h * 0.030)

    try:
        font_title = ImageFont.truetype(COVER_FONT, font_title_size)
        font_body  = ImageFont.truetype(COVER_FONT, font_body_size)
    except Exception:
        font_title = ImageFont.load_default()
        font_body  = ImageFont.load_default()

    text_color = (35, 30, 25, 255)

    t_bbox  = draw.textbbox((0, 0), title_line, font=font_title)
    t_h     = t_bbox[3] - t_bbox[1]

    line_gap   = int(font_body_size * 0.55)
    blank_gap  = int(font_body_size * 0.70)
    title_gap  = int(font_body_size * 3.10)

    total_h = t_h + title_gap
    for line in body_lines:
        if line:
            bb = draw.textbbox((0, 0), line, font=font_body)
            total_h += (bb[3] - bb[1]) + line_gap
        else:
            total_h += blank_gap

    usable_h = int(h * 0.65)
    start_y  = max(int(h * 0.12), (usable_h - total_h) // 2)

    t_w = t_bbox[2] - t_bbox[0]
    draw.text(((w - t_w) // 2, start_y), title_line, font=font_title, fill=text_color)
    y = start_y + t_h + title_gap

    for line in body_lines:
        if not line:
            y += blank_gap
            continue
        bb = draw.textbbox((0, 0), line, font=font_body)
        lw = bb[2] - bb[0]
        lh = bb[3] - bb[1]
        draw.text(((w - lw) // 2, y), line, font=font_body, fill=text_color)
        y += lh + line_gap

    # --- Tagline (rendret av scriptet, over "© 2026 DreamPage") ---
    _dpf_tag_lines = DREAMPAGE_FIRST_TAGLINE.splitlines()
    _dpf_tag_fs = int(h * 0.033)
    try:
        _dpf_tag_font = ImageFont.truetype(COVER_FONT, _dpf_tag_fs)
    except Exception:
        _dpf_tag_font = ImageFont.load_default()
    _dpf_tag_gap = int(_dpf_tag_fs * 0.30)
    _dpf_tag_dims = [draw.textbbox((0, 0), _t, font=_dpf_tag_font) for _t in _dpf_tag_lines]
    _dpf_tag_total = sum((b[3] - b[1]) for b in _dpf_tag_dims) + _dpf_tag_gap * (len(_dpf_tag_lines) - 1)
    _dpf_ty = int(h * 0.735) - _dpf_tag_total // 2
    for _t, _b in zip(_dpf_tag_lines, _dpf_tag_dims):
        _dpf_lw = _b[2] - _b[0]
        draw.text(((w - _dpf_lw) // 2, _dpf_ty), _t, font=_dpf_tag_font, fill=(35, 30, 25, 255))
        _dpf_ty += (_b[3] - _b[1]) + _dpf_tag_gap
    os.makedirs(out_dir, exist_ok=True)
    img.save(dst)
    return dst


def process_book(base_dir: str, out_dir: str, child_name: str, cover_type: str, gelato_api_key: str):
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

    # Prepend personlig dedikasjon (side 1), legg blank-back.png på slutten, og append per-bok Lastpage(superhelt).png aller sist.
    dreampage_first = _dp_first(STYRKEN_DREAMPAGE_FIRST)
    # Ordrens egen blank-back.png (f.eks. "Fortsett eventyret"-siden med QR)
    # har forrang; den delte malen er fallback for boker uten oppsalg.
    blank_back = os.path.join(base_dir, "blank-back.png")
    if not os.path.exists(blank_back):
        blank_back = os.path.join(SCRIPT_DIR, "blank-back.png")
    else:
        print("[INNER PDF] Bruker siste innerside fra ordremappen:", blank_back)
    last_page = resolve_lastpage_path("Lastpage(superhelt).png")
    if os.path.exists(dreampage_first):
        rendered_first = render_dreampage_first(child_name, out_dir)
        inner_paths.insert(0, rendered_first)
    else:
        print("ADVARSEL: Fant ikke dreampage-first.png")
    if os.path.exists(blank_back):
        inner_paths.append(blank_back)
    else:
        raise FileNotFoundError("Fant ikke blank-back.png i script-mappen")
    if last_page:
        inner_paths.append(last_page)
    else:
        print(f"ADVARSEL: Fant ikke Lastpage(superhelt).png i {LASTPAGE_DIR} - hopper over")




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
    need = ["bakside(styrken).png", "ryggrad.png", "forside(styrken).png"]
    missing = [n for n in need if n not in cover_rendered]

    if missing:
        print("Cover PDF ble IKKE laget. Mangler rendret cover-del(er):", ", ".join(missing))
        return

    back_path  = cover_rendered["bakside(styrken).png"]
    spine_path = cover_rendered["ryggrad.png"]
    front_path = cover_rendered["forside(styrken).png"]

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




# --- DreamPage translated text table (nn) ---
_DREAMPAGE_TRANSLATIONS = {
  "{name} og\nDen skjulte styrken": "{name} og\nDen skjulte styrken",
  "Det var en helt vanlig morgen, av den typen der sola kiler i øynene og lufta lukter ny dag. {name} gikk den samme veien til skolen som alltid, men i dag føltes alt litt ekstra spennende.\nSekken dunket lett mot ryggen, og inni magen kriblet det av forventning. For i dag skulle hele klassen på tur, og det hadde {name} gledet seg til i ukevis.": "Det var ein heilt vanleg morgon, av den typen der sola kilar i auga og lufta lukter ny dag. {name} gjekk den same vegen til skulen som alltid, men i dag kjendest alt litt ekstra spennande.\nSekken dunka lett mot ryggen, og inni magen kribla det av forventning. For i dag skulle heile klassen på tur, og det hadde {name} gledd seg til i vekevis.",
  "Plutselig stoppet {name} midt i steget. En merkelig lyd kom fra et smalt smug ved siden av gata, som en svak summing blandet med et fjernt klingende ekko.\n{name} klarte ikke å la være. Han gikk forsiktig nærmere, helt til han kikket inn i mørket. Der, midt i lufta, glødet noe varmt og oransje. Hva i all verden kunne det være?": "Plutseleg stoppa {name} midt i steget. Ein merkeleg lyd kom frå eit smalt smau ved sida av gata, som ei svak summing blanda med eit fjernt klingande ekko.\n{name} klarte ikkje å la vere. Han gjekk forsiktig nærare, heilt til han kikket inn i mørket. Der, midt i lufta, glødde noko varmt og oransje. Kva i all verda kunne det vere?",
  "Lyset ble så sterkt at {name} måtte myse. Hele smuget badet i en gnistrende glød.\nDa lyset roet seg, sto det noe foran ham. Et skimrende hologram svevde i lufta, og bak det hang en superhelt-drakt.\nHologrammet smilte og sa: «Du er den utvalgte, {name}. Du er byens eneste håp.»": "Lyset vart så sterkt at {name} måtte myse. Heile smauet bada i ein gnistrande glød.\nDå lyset roa seg, stod det noko framfor han. Eit skimrande hologram sveva i lufta, og bak det hang ei superhelt-drakt.\nHologrammet smilte og sa: «Du er den utvalde, {name}. Du er byens einaste håp.»",
  "{name} løp så fort han kunne bort fra smuget, mens hjertet banket hardt i brystet. Han var redd, helt skikkelig redd.\n«Jeg er ikke klar for dette,» hvisket {name} til seg selv. «Jeg er jo bare en helt vanlig gutt.»\nInni seg kjente han både tårer og en liten klump av sinne. Hvorfor måtte det være akkurat han som var den utvalgte?": "{name} sprang så fort han kunne bort frå smauet, medan hjartet banka hardt i brystet. Han var redd, heilt skikkeleg redd.\n«Eg er ikkje klar for dette,» kviskra {name} til seg sjølv. «Eg er jo berre ein heilt vanleg gut.»\nInni seg kjende han både tårer og ein liten klump av sinne. Kvifor måtte det vere akkurat han som var den utvalde?",
  "{name} klatret opp til favorittstedet sitt. Derfra kunne han se utover hele byen.\nHan sto stille og tenkte. Langt der nede så han mørke skygger bevege seg sakte mot sentrum.\nVar det dette hologrammet hadde ment? Skulle han virkelig redde byen alene?": "{name} klatra opp til favorittstaden sin. Derfrå kunne han sjå utover heile byen.\nHan stod stille og tenkte. Langt der nede så han mørke skyggjer bevege seg sakte mot sentrum.\nVar det dette hologrammet hadde meint? Skulle han verkeleg redde byen åleine?",
  "Akkurat da kom superheltdrakten flyvende ut av det blå. Den snurret raskt rundt {name} – én gang, to ganger – og i neste øyeblikk hadde han den på seg.\n{name} tok et dypt sats, og med et høyt Swoooosh fløy han rett mot sentrum og landet midt i gata. {name} hadde blitt en superhelt.": "Akkurat då kom superheltdrakta flygande ut av det blå. Den snurra raskt rundt {name} – éin gong, to gonger – og i neste augneblink hadde han han på seg.\n{name} tok eit djupt sats, og med eit høgt *Swoooosh flaug han rett mot sentrum og landa midt i gata. {name} hadde vorte ein superhelt.",
  "{name} kjente at hjertet fortsatt banket av redsel, men nå kunne han ikke snu. Han tok et dypt pust og tenkte på alle menneskene som trengte hjelp.\nLangt der nede hadde skyggene sendt en søyle av sterkt, oransje lys rett opp mot himmelen. {name} visste at det var dit han måtte dra.": "{name} kjende at hjartet framleis banka av redsel, men no kunne han ikkje snu. Han tok eit djupt pust og tenkte på alle menneska som trong hjelp.\nLangt der nede hadde skuggane sendt ei søyle av sterkt, oransje lys rett opp mot himmelen. {name} visste at det var dit han måtte dra.",
  "Nå sto {name} rett foran det sterke lyset, så nær at han kjente varmen mot kinnene. Dette var øyeblikket hologrammet hadde snakket om.\n{name} stilte seg støtt på bakken, knyttet nevene hardt og gjorde seg klar til å kjempe.": "No stod {name} rett framfor det sterke lyset, så nær at han kjende varmen mot kinna. Dette var augneblinken hologrammet hadde snakka om.\n{name} stilte seg støtt på bakken, knytte nevane hardt og gjorde seg klar til å kjempe.",
  "Mørket samlet seg foran {name} og vokste til en høy skygge midt i gata. Den vred seg i luften, som om den var laget av røyk og torden.\n{name} kjente redselen prikke i hendene, men han ble stående. Inni brystet våknet en varm styrke, og han visste at han måtte holde ut litt til.": "Mørket samla seg framfor {name} og voks til ein høg skugge midt i gata. Den vrei seg i lufta, som om den var laga av røyk og tore.\n{name} kjende redselen prikke i hendene, men han vart ståande. Inni brystet vakna ein varm styrke, og han visste at han måtte halde ut litt til.",
  "{name} strakte begge armene rett opp mot lyset og knyttet nevene så hardt han kunne.\nPlutselig sprutet et sterkt, blått lys ut av hendene hans og traff den mørke skyggen med et kraftig BANG som fikk hele byen til å riste.": "{name} strakk begge armane rett opp mot lyset og knytte nevane så hardt han kunne.\nPlutseleg spruta eit sterkt, blått lys ut av hendene hans og trefte den mørke skuggen med eit kraftig BANG som fekk heile byen til å riste.",
  "Takket være {name} var byen trygg igjen. Lyset var borte, skyggene forsvunnet, og menneskene begynte å smile.\n{name} hadde alltid trodd at han bare var en vanlig gutt. Men nå visste han noe viktig: han var en ekte superhelt.": "Takka vere {name} var byen trygg igjen. Lyset var borte, skuggane forsvunne, og menneska byrja å smile.\n{name} hadde alltid trudd at han berre var ein vanleg gut. Men no visste han noko viktig: han var ein ekte superhelt.",
  "Plutselig dukket hologrammet opp igjen, lysende svakt og vennlig i lufta foran ham.\n«Veldig bra jobbet, {name},» sa hologrammet stolt. «Hvis byen trenger hjelp igjen, finner jeg deg.»\n{name} smilte. «Jeg er alltid klar.»": "Plutseleg dukka hologrammet opp igjen, lysande svakt og vennleg i lufta framfor han.\n«Veldig bra jobba, {name},» sa hologrammet stolt. «Viss byen treng hjelp igjen, finn eg deg.»\n{name} smilte. «Eg er alltid klar.»",
  "{name} tok et siste blikk utover byen. Alt var stille nå, og lysene blinket fredelig i kveldsmørket.\nHan tenkte på alt som hadde skjedd. {name} smilte, for innerst inne visste han noe viktig: Det var han som var den utvalgte.": "{name} tok eit siste blikk utover byen. Alt var stille no, og lysa blinka fredeleg i kveldsmørket.\nHan tenkte på alt som hadde skjedd. {name} smilte, for inst inne visste han noko viktig: Det var han som var den utvalde.",
  "{name} hadde byttet tilbake til sine vanlige klær og gikk den samme veien til skolen som alltid.\nKlassen var allerede på tur, og han hadde gått glipp av den. «Litt kjipt,» lo {name}. «Men nå har jeg en helt utrolig historie å fortelle vennene mine.»": "{name} hadde bytt tilbake til dei vanlege kleda sine og gjekk den same vegen til skulen som alltid.\nKlassen var allereie på tur, og han hadde gått glipp av den. «Litt kjipt,» lo {name}. «Men no har eg ei heilt utruleg historie å fortelje vennene mine.»",
  "Denne boken handler om mot – om å være redd og likevel våge å prøve. Den viser at helter ikke alltid er store og sterke, men ofte vanlige barn som finner styrken i seg selv når det virkelig gjelder.\nDerfor er det {name} som er helten i denne historien. En personlig fortelling som gir barn trygghet, selvtillit og troen på seg selv.": "Denne boka handlar om mot – om å vere redd og likevel våga å prøve. Den viser at heltar ikkje alltid er store og sterke, men ofte vanlege barn som finn styrken i seg sjølv når det verkeleg gjeld.\nDerfor er det {name} som er helten i denne historia. Ei personleg forteljing som gir barn tryggleik, sjølvtillit og trua på seg sjølv."
}
_DREAMPAGE_ORIGINAL_BUILD_PAGES = build_pages

def _dreampage_text_key(text: str, child_name: str) -> str:
    return str(text).replace(child_name, "{name}")

def _dreampage_apply_translation(text: str, child_name: str) -> str:
    key = _dreampage_text_key(text, child_name)
    translated = _DREAMPAGE_TRANSLATIONS.get(key)
    if translated is None:
        return text
    return translated.replace("{name}", child_name)


def _balanced_story_split(text: str) -> tuple[str, str] | None:
    raw = str(text).strip()
    if not raw:
        return None

    parts = [part.strip() for part in raw.split("\n") if part.strip()]
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])

    clean = re.sub(r"\s+", " ", raw)
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    sentences = [s.strip() for s in sentences if s.strip()]
    if len(sentences) < 2:
        return None

    target = len(clean) / 2
    best = 1
    best_delta = float("inf")
    for idx in range(1, len(sentences)):
        first_len = len(" ".join(sentences[:idx]))
        delta = abs(first_len - target)
        if delta < best_delta:
            best = idx
            best_delta = delta
    first = " ".join(sentences[:best]).strip()
    second = " ".join(sentences[best:]).strip()
    return (first, second) if first and second else None


def _split_inner_story_blocks(page: dict) -> None:
    if page.get("type") != "inner":
        return
    blocks = page.get("blocks") or []
    if len(blocks) != 1:
        return

    block = blocks[0]
    split = _balanced_story_split(block.get("text", ""))
    if not split:
        return

    first, second = split
    side = page.get("side", "right")
    filename = str(page.get("filename", ""))

    top_y = 25
    bottom_y = 345
    if filename.startswith(("03", "10")):
        top_y = 40
        bottom_y = 365
    if filename.startswith(("12", "13")):
        top_y = 50
        bottom_y = 365
    if filename.startswith("07"):
        top_y = 115
        bottom_y = 410

    first_block = dict(block)
    second_block = dict(block)
    first_block["text"] = first
    second_block["text"] = second
    first_block["y_offset"] = top_y
    second_block["y_offset"] = bottom_y

    first_block["font_size"] = min(int(first_block.get("font_size", 30)), 30)
    second_block["font_size"] = min(int(second_block.get("font_size", 30)), 30)

    first_block.setdefault("width_offset", 95)
    second_block.setdefault("width_offset", 95)
    first_block["text_backdrop"] = True
    second_block["text_backdrop"] = True
    if filename.startswith(("09", "10")):
        first_block["text_backdrop_strength"] = "strong"
        second_block["text_backdrop_strength"] = "strong"
    if filename.startswith("08"):
        second_block["text_backdrop_strength"] = "strong"

    if side == "left":
        second_block["x_offset"] = int(second_block.get("x_offset", 0)) - 10
    else:
        second_block["x_offset"] = int(second_block.get("x_offset", 0)) + 10

    if filename.startswith("07"):
        first_block["x_offset"] = 25
        second_block["x_offset"] = 25

    page["blocks"] = [first_block, second_block]

def build_pages(child_name: str):
    pages = _DREAMPAGE_ORIGINAL_BUILD_PAGES(child_name)
    for page in pages:
        if isinstance(page.get("text"), str):
            page["text"] = _dreampage_apply_translation(page["text"], child_name)
        for block in page.get("blocks") or []:
            if isinstance(block.get("text"), str):
                block["text"] = _dreampage_apply_translation(block["text"], child_name)
        _split_inner_story_blocks(page)
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


def draw_text_backdrop(img, box, text, font, line_spacing, highlights=None, align="left", strength="normal"):
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

    drew = False
    for lb in line_boxes:
        left = max(0, lb[0] - pad_x)
        top = max(0, lb[1] - pad_y)
        right = min(img.size[0], lb[2] + pad_x)
        bottom = min(img.size[1], lb[3] + pad_y)
        if right <= left or bottom <= top:
            continue
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
    number = _dp_page_number(filename)
    top_y = 25
    bottom_y = 345
    if number in (3, 10):
        top_y = 40
        bottom_y = 365
    if number in (12, 13):
        top_y = 50
        bottom_y = 365
    if number == 7:
        top_y = 115
        bottom_y = 410
    return number, top_y, bottom_y


def _dp_mark_backdrop(block: dict, filename: str, child_name: str, *, second: bool = False) -> None:
    block["text_backdrop"] = True
    block["color"] = "#FFFFFF"
    block["highlights"] = _dp_auto_highlights(block.get("text", ""), child_name, block.get("highlights", []))
    number = _dp_page_number(filename)
    if number in (8, 9, 10) and (number in (9, 10) or second):
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

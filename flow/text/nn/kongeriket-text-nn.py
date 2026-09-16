


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

# Lastpage(dinosaur).png ligger etter blank-back, så total innersider = 31.
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


SCRIPT_LOCALES = {"nb", "nn", "en-US", "en-GB"}
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

COVER_FONT     = os.path.join(SCRIPT_DIR, "PlayfairDisplay.ttf")
LOGO_DIR = os.path.join(SCRIPT_ROOT_DIR, "logo", SCRIPT_LOCALE)
INNER_FONT     = os.path.join(SCRIPT_DIR, "Georgia.ttf")

BOOK_DREAMPAGE_FIRST = os.path.join(
    DP_ROOT, "books", "kongerikets-hemmelighet", "dreampage-first-kongeriket.png"
)
DREAMPAGE_FIRST_TAGLINE = "Trykt med omtanke for\nkvalitet"
HIGHLIGHT_FONT = os.path.join(SCRIPT_DIR, "Georgia Bold.ttf")
BACK_TEXT_FONT = os.path.join(globals().get("SCRIPT_ROOT_DIR", os.path.dirname(SCRIPT_DIR)), "pre", "Fredoka.ttf")

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
def wrap_paragraph_balanced(draw, words, fonts, max_width, short_last_line_ratio=0.38):
    """
    Lager linjer med word wrap og prøver å unngå veldig kort siste linje.
    """
    lines = []
    current_words = []
    current_fonts = []
    current_width = 0

    for word, fnt in zip(words, fonts):
        piece = ("" if not current_words else " ") + word
        piece_width = draw.textlength(piece, font=fnt)

        if current_words and (current_width + piece_width > max_width):
            lines.append((current_words[:], current_fonts[:], current_width))
            current_words = [word]
            current_fonts = [fnt]
            current_width = draw.textlength(word, font=fnt)
        else:
            current_words.append(piece)
            current_fonts.append(fnt)
            current_width += piece_width

    if current_words:
        lines.append((current_words[:], current_fonts[:], current_width))

    if len(lines) >= 2:
        prev_words, prev_fonts, prev_width = lines[-2]
        last_words, last_fonts, last_width = lines[-1]

        while len(prev_words) > 1 and last_width < max_width * short_last_line_ratio:
            moved_word = prev_words[-1].lstrip()
            moved_font = prev_fonts[-1]

            trial_prev_words = prev_words[:-1]
            trial_prev_fonts = prev_fonts[:-1]

            trial_last_words = [moved_word]
            trial_last_fonts = [moved_font]

            for w, f in zip(last_words, last_fonts):
                trial_last_words.append(" " + w.lstrip())
                trial_last_fonts.append(f)

            new_prev_width = sum(draw.textlength(w, font=f) for w, f in zip(trial_prev_words, trial_prev_fonts))
            new_last_width = sum(draw.textlength(w, font=f) for w, f in zip(trial_last_words, trial_last_fonts))

            if new_last_width > max_width or new_prev_width < max_width * 0.45:
                break

            prev_words, prev_fonts, prev_width = trial_prev_words, trial_prev_fonts, new_prev_width
            last_words, last_fonts, last_width = trial_last_words, trial_last_fonts, new_last_width

        lines[-2] = (prev_words, prev_fonts, prev_width)
        lines[-1] = (last_words, last_fonts, last_width)

    return lines


def draw_text(draw, text, box, font,
              color=TEXT_COLOR,
              stroke_color=STROKE_COLOR,
              line_spacing=10,
              highlights=None,
              gradient=None,
              img=None,
              align="left"):
    """
    Skriver avsnitttekst inni en boks med balansert word-wrapping.
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
    try:
        highlight_font = ImageFont.truetype(HIGHLIGHT_FONT, base_font.size)
    except Exception:
        highlight_font = base_font

    paragraphs = text.split("\n")
    y = y1

    for para in paragraphs:
        para = para.strip()
        if not para:
            y += base_font.size + line_spacing
            continue

        words = para.split(" ")
        word_fonts: List[ImageFont.FreeTypeFont] = []

        for word in words:
            clean = word.strip(".,!?…:;«»\"'").lower()
            fnt = highlight_font if clean in hl_set else base_font
            word_fonts.append(fnt)

        lines = wrap_paragraph_balanced(
            draw=draw,
            words=words,
            fonts=word_fonts,
            max_width=max_width,
            short_last_line_ratio=0.38,
        )

        for line_words, line_fonts, line_width in lines:
            if align == "center":
                x = x1 + max(0, int((max_width - line_width) / 2))
            elif align == "right":
                x = x2 - int(line_width)
            else:
                x = x1

            for w, fnt in zip(line_words, line_fonts):
                if gradient:
                    draw_gradient_word(
                        img, draw, w, x, y, fnt,
                        gradient["colors"],
                        gradient["shadow"],
                    )
                else:
                    draw.text((x, y), w, font=fnt, fill=color)

                x += draw.textlength(w, font=fnt)

            y += base_font.size + line_spacing

        y += line_spacing


# ------------------------------------------------------------
#  FORSIDE-TITTEL – render-title.py logikk + dine farger
# ------------------------------------------------------------

def draw_inside_title(img, text):
    """
    Elegant dark title for the first inside page only.
    No gold gradient, no heavy shadow — clean, book-like, premium.
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

    title_color = "#1c1c1e"   # near-black charcoal — premium, not flashy

    # Krymp til tittelen faar plass. "Kongerikets Hemmelighet" er lengre enn
    # titlene denne malen ble laget for, og fast fontstoerrelse lot linje 2
    # renne ut over begge kantene paa introsiden.
    INSIDE_TITLE_MAX_W = 0.78

    def _fit(line, font):
        if not line:
            return font
        limit = int(w * INSIDE_TITLE_MAX_W)
        size = font.size
        while size > 8:
            bbox = draw.textbbox((0, 0), line, font=font)
            if bbox[2] - bbox[0] <= limit:
                break
            size -= 2
            try:
                font = ImageFont.truetype(COVER_FONT, size)
            except Exception:
                break
        return font

    font1 = _fit(line1, font1)
    font2 = _fit(line2, font2)

    def _tw(t, f):
        if not t:
            return 0, 0
        bbox = draw.textbbox((0, 0), t, font=f)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    w1, h1 = _tw(line1, font1)
    w2, h2 = _tw(line2, font2)

    top_y   = int(h * 0.10)
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

    font_small = ImageFont.truetype(COVER_FONT, int(min(img.size) * 0.08))
    font_large = ImageFont.truetype(COVER_FONT, int(min(img.size) * 0.095))

    # Krymp til tittelen faar plass. "Kongerikets Hemmelighet" er mye
    # lengre enn titlene denne malen ble laget for, og en fast fontstoerrelse
    # lot den renne ut over begge kantene paa forsiden.
    FRONT_COVER_TEXT_MAX_W = 0.90

    def _fc_fit(line, font):
        if not line:
            return font
        limit = int(w * FRONT_COVER_TEXT_MAX_W)
        size = font.size
        while size > 8:
            bbox = draw.textbbox((0, 0), line, font=font)
            if bbox[2] - bbox[0] <= limit:
                break
            size -= 2
            font = ImageFont.truetype(COVER_FONT, size)
        return font

    font_small = _fc_fit(line1, font_small)
    font_large = _fc_fit(line2, font_large)


    gold   = ((160, 130, 80), (245, 232, 205))
    shadow = (45, 30, 18)

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

    top_y = int(h * 0.020)
    spacing = int(h * 0.027)

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


# ---------------------------------------------------------------------------
#  FORSIDE-TITTEL - navn som tekst + Kongerikets Hemmelighet-logo som linje 2
#  Verdiene speiler config/next_book_titles.json (nb) fra DP Title Tester.
# ---------------------------------------------------------------------------
FRONT_COVER_LOGO_SCALE = 0.75
FRONT_COVER_LOGO_X_OFFSET = 0
FRONT_COVER_TOP_MARGIN = 0.03
FRONT_COVER_LINE_SPACING = 0.02
FRONT_COVER_LINE1_SIZE = 73 / 1024          # andel av kortsiden
FRONT_COVER_GOLD = ((255, 255, 255), (255, 255, 255))
FRONT_COVER_SHADOW = (60, 35, 70)

# Logoen inneholder HELE tittelen ("Kongerikets Hemmelighet"), saa linje 1 er
# bare "Prinsesse <navn> og" - ingenting skal henge paa. Speiler
# line1_prefix/line1_suffix i config/next_book_titles.json.
FRONT_COVER_LINE1_EXTRA = ""


def _crop_logo_to_visible_alpha(logo_img, alpha_threshold=8):
    logo_rgba = logo_img.convert("RGBA")
    bbox = logo_rgba.getchannel("A").point(
        lambda a: 255 if a > alpha_threshold else 0).getbbox()
    return logo_rgba.crop(bbox) if bbox else logo_rgba


def resolve_front_cover_logo():
    """Logo for gjeldende spraak, eller None hvis den ikke finnes.

    None betyr med vilje "tegn linje 2 som tekst" - en norsk logo skal aldri
    havne paa en engelsk eller svensk bok. nn peker paa den norske logoen fordi
    tittelen er identisk paa bokmaal og nynorsk.
    """
    name = {
        "nb": "kongeriket-logo-nb.png",
        "nn": "kongeriket-logo-nb.png",
        "en-US": "kongeriket-logo-en.png",
        "en-GB": "kongeriket-logo-en.png",
        "sv": "kongeriket-logo-sv.png",
    }.get(SCRIPT_LOCALE, "kongeriket-logo-nb.png")
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

    line1 = (text.split("\n")[0] if text else "") + FRONT_COVER_LINE1_EXTRA
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
            "filename": "forside(kongeriket).png",
            "type": "cover",
            "text": p("Prinsesse (Navn) og\nKongerikets Hemmelighet"),
        },
        {
            "filename": "ryggrad.png",
            "type": "cover",
        },
        {
            "type": "blank",
            "side": "right",
            "text": p("Prinsesse (Navn) og\nKongerikets Hemmelighet"),
            "blocks": [{
                "text": p(
                    "Takk for at du kjøpte denne personlige historien!\n"
                    "I denne boken våkner (Navn) til sin aller første dag som prinsesse, og oppdager en hemmelighet dypt under slottet som kan redde hele kongeriket.\n"
                    "Vi håper historien bringer glede, spenning og fantasifulle øyeblikk."
                ),
                "font_size": 42,
                "color": "#111111",
                "y_offset": 420,
            }]
        },

        # Side 1
        {
            "filename": "01(kongeriket).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Det var den første morgenen til (Navn) som prinsesse.\n"
                    "Fra balkongen kunne hun se hele kongeriket våkne.\n"
                    "Elven glitret mellom åsene, og fuglene fløy over tårnene.\n"
                    "(Navn) ante ikke at en stor oppgave allerede ventet."
                ),
                "font_size": 34,
                "color": "#FFFFFF",
                "highlights": [child_name, "prinsesse", "kongeriket", "oppgave"],
            }],
        },

        # Side 2
        {
            "filename": "02(kongeriket).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Senere gikk (Navn) gjennom slottsgården da hun stoppet.\n"
                    "Den store fontenen, som alltid sprutet mot himmelen, var stille.\n"
                    "Blomstene hang tungt, og bare noen dråper rant fra steinen.\n"
                    "«Hvor har alt vannet blitt av?» undret (Navn)."
                ),
                "font_size": 34,
                "color": "#FFFFFF",
                "highlights": [child_name, "fontenen", "stille", "vannet"],
            }],
        },

        # Side 3
        {
            "filename": "03(kongeriket).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Dronningen kom bort og så alvorlig på den tomme fontenen.\n"
                    "«Elven som gir vann til hele kongeriket blir svakere,» sa hun.\n"
                    "Ingen visste hvorfor, og snart kunne alle mangle vann.\n"
                    "(Navn) rettet ryggen. Dette skulle bli hennes første oppgave."
                ),
                "font_size": 34,
                "color": "#FFFFFF",
                "highlights": [child_name, "Dronningen", "svakere", "oppgave"],
            }],
        },

        # Side 4
        {
            "filename": "04(kongeriket).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "(Navn) skyndte seg til det gamle biblioteket for å lete etter svar.\n"
                    "Mellom støvete bøker fant hun et gammelt kart over slottet.\n"
                    "Under slottet var det tegnet en vannvei hun aldri hadde sett.\n"
                    "«Kanskje vannet ikke bare kommer fra elven,» tenkte hun."
                ),
                "font_size": 34,
                "color": "#FFFFFF",
                "highlights": [child_name, "biblioteket", "kart", "vannvei"],
            }],
        },

        # Side 5
        {
            "filename": "05(kongeriket).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Kartet førte (Navn) til en bortgjemt del av slottsgården.\n"
                    "Bak eføy og gamle roser oppdaget hun en liten steindør.\n"
                    "Da hun skjøv greinene til side, strømmet kald luft ut fra mørket.\n"
                    "(Navn) tok et dypt pust og åpnet døren."
                ),
                "font_size": 34,
                "color": "#FFFFFF",
                "highlights": [child_name, "steindør", "mørket", "eføy"],
            }],
        },

        # Side 6
        {
            "filename": "06(kongeriket).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Med en lykt i hånden gikk (Navn) ned trappene under slottet.\n"
                    "Steinveggene var kalde, og dryppende vann fulgte henne.\n"
                    "Jo lenger hun gikk, desto tydeligere hørte hun noe som rant.\n"
                    "Hun løftet lykten og fortsatte."
                ),
                "font_size": 34,
                "color": "#FFFFFF",
                "highlights": [child_name, "lykt", "trappene", "rant"],
            }],
        },

        # Side 7
        {
            "filename": "07(kongeriket).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Plutselig åpnet tunnelen seg til en enorm hule.\n"
                    "Foran (Navn) rant en skjult blå elv mellom gamle steinkanaler.\n"
                    "Vannet glitret svakt, som en hemmelig verden under slottet.\n"
                    "«Så det er her vannet kommer fra!» hvisket hun."
                ),
                "font_size": 34,
                "color": "#FFFFFF",
                "highlights": [child_name, "hule", "elv", "hemmelig"],
            }],
        },

        # Side 8
        {
            "filename": "08(kongeriket).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "(Navn) fulgte elven videre, men strømmen ble svakere.\n"
                    "Til slutt var det bare små dammer igjen mellom steinene.\n"
                    "Hun satte seg ned og studerte vannet nøye.\n"
                    "Fant hun ut hvor strømmen stoppet, kunne hun redde kongeriket."
                ),
                "font_size": 34,
                "color": "#FFFFFF",
                "highlights": [child_name, "strømmen", "dammer", "redde"],
            }],
        },

        # Side 9
        {
            "filename": "09(kongeriket).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Bak en gammel steinbue fant (Navn) et skjult rom.\n"
                    "På veggene var det skåret ut elver, fontener og vannveier.\n"
                    "Midt i rommet stod en stor mekanisme av stein og metall.\n"
                    "Noen hadde bygget dette stedet for å lede vannet."
                ),
                "font_size": 34,
                "color": "#FFFFFF",
                "highlights": [child_name, "skjult", "mekanisme", "vannveier"],
            }],
        },

        # Side 10
        {
            "filename": "10(kongeriket).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Bak kammeret fant hun noe enda mer utrolig.\n"
                    "En klar kilde fylte et gammelt steinbasseng med friskt vann.\n"
                    "Det var mer enn nok vann. Problemet var at det ikke kom videre.\n"
                    "Da visste (Navn) at løsningen måtte være like i nærheten."
                ),
                "font_size": 34,
                "color": "#FFFFFF",
                "highlights": [child_name, "kilde", "friskt", "løsningen"],
            }],
        },

        # Side 11
        {
            "filename": "11(kongeriket).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Hun fulgte kanalen til en gammel steinport og fant årsaken.\n"
                    "Store steiner hadde rast ned og satt seg fast foran porten.\n"
                    "Bak dem presset vannet på, men det hadde ingen vei ut.\n"
                    "«Jeg har funnet det!» ropte (Navn)."
                ),
                "font_size": 34,
                "color": "#FFFFFF",
                "highlights": [child_name, "steinport", "steiner", "funnet"],
            }],
        },

        # Side 12
        {
            "filename": "12(kongeriket).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "(Navn) hentet hjelp og viste arbeiderne veien gjennom tunnelene.\n"
                    "Sammen flyttet de steinene og reparerte den gamle vannporten.\n"
                    "(Navn) fulgte nøye med og viste hvor vannet skulle ledes.\n"
                    "Så, med et kraftig brus, åpnet porten seg."
                ),
                "font_size": 34,
                "color": "#FFFFFF",
                "highlights": [child_name, "hjelp", "vannporten", "brus"],
            }],
        },

        # Side 13
        {
            "filename": "13(kongeriket).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Vannet strømmet gjennom kanalene og tilbake til kongeriket.\n"
                    "I slottsgården sprutet fontenen igjen, og blomstene løftet seg.\n"
                    "Folk jublet mens (Navn) så utover alt hun hadde reddet.\n"
                    "«Du fant løsningen da ingen andre visste hvor de skulle lete.»"
                ),
                "font_size": 34,
                "color": "#FFFFFF",
                "highlights": [child_name, "strømmet", "fontenen", "jublet"],
            }],
        },

        # Side 14
        {
            "filename": "14(kongeriket).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Den kvelden stod (Navn) sammen med dronningen på balkongen.\n"
                    "Elven glitret igjen, og fontenene danset i slottsgården.\n"
                    "(Navn) hadde lært at det å være prinsesse er mer enn en krone.\n"
                    "Det handler om å lytte, tenke og ta vare på dem som trenger deg."
                ),
                "font_size": 34,
                "color": "#FFFFFF",
                "highlights": [child_name, "dronningen", "prinsesse", "lytte"],
            }],
        },

        # EKSTRA BLANK SISTE INNERSIDE
        {
            "filename": "blank-back.png",
            "type": "inner",
            "side": "left",
            "blank_only": True
        },

        # Bakside
        {
            "filename": "bakside(kongeriket).png",
            "type": "cover",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Denne boken handler om å lete videre når andre gir opp. Om å stille spørsmål, tenke selv og finne svar der ingen har lett før.\n"
                    "Når vannet forsvinner fra kongeriket, følger (Navn) et gammelt kart ned i mørket under slottet – og finner en hemmelighet som har ligget skjult i mange år.\n"
                    "En varm og spennende historie om mot, nysgjerrighet og om å ta ansvar for noe større enn seg selv.\n"
                    "En bok som minner barnet på at små hender kan utgjøre en stor forskjell."
                ),
                "font_size": 46,
                "color": "#FFFFFF",
                "highlights": [child_name, "hemmelighet", "kongeriket", "mot", "nysgjerrighet", "ansvar", "barnet"],
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
RYGGRAD_BOOK_SLUG = "kongerikets-hemmelighet"
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


# ------------------------------------------------------------
#  1:1 KVADRATSIDE (ingen A5-splitt) - brukt for side 07 venstre/hoyre.
#  Kolonnene skaleres x4/3 slik at teksten havner samme sted paa skjermen
#  som paa en vanlig venstre-/hoyreside. Hoyrekolonnen trekkes ned i
#  sidens eget koordinatrom (den ligger i par-rommet 1024-2048).
# ------------------------------------------------------------
SQUARE_DESIGN = 1024
SQ_LEFT_X1, SQ_LEFT_X2 = 187, 720
SQ_RIGHT_X1, SQ_RIGHT_X2 = 1328 - SQUARE_DESIGN, 1861 - SQUARE_DESIGN


def _render_square_page(page, base_path, out_dir):
    img = Image.open(base_path).convert("RGBA")
    img_w, img_h = img.size
    draw = ImageDraw.Draw(img)
    s = img_w / SQUARE_DESIGN

    def sq(v):
        return int(v * s)

    side = page.get("side", "left")
    if side == "left":
        x1, x2 = sq(SQ_LEFT_X1), sq(SQ_LEFT_X2)
    elif side == "right":
        x1, x2 = sq(SQ_RIGHT_X1), sq(SQ_RIGHT_X2)
    else:
        x1, x2 = sq(160), img_w - sq(160)

    y_top = sq(MARGIN_Y + 150)
    y_bottom = sq(SQUARE_DESIGN - 80)

    # box_frac lar en side sette tekstboksen eksplisitt (andeler av bildet) naar
    # motivet ikke gir plass i standardkolonnen. Brukes for 07-hoyre.
    box_frac = page.get("box_frac")
    if box_frac:
        x1 = int(img_w * box_frac[0])
        y_top = int(img_h * box_frac[1])
        x2 = int(img_w * box_frac[2])
        y_bottom = int(img_h * box_frac[3])

    for block in page.get("blocks", []):
        base_size = block.get("font_size", DEFAULT_FONT_SIZE)
        font_size = max(8, int(base_size * s))
        font = ImageFont.truetype(INNER_FONT, font_size)

        bx1 = x1 + sq(block.get("x_offset", 0))
        bx2 = x2 + sq(block.get("width_offset", 0))
        by1 = y_top + (0 if box_frac else sq(block.get("y_offset", 0)))
        box = (bx1, by1, bx2, y_bottom)

        use_gradient = "color" not in block
        text_line_spacing = max(6, int(16 * s))
        shadow_offset = max(2, int(font_size * 0.05))
        shadow_blur = max(2, int(font_size * 0.07))

        if block.get("text_backdrop", False):
            draw_text_backdrop(img, box, block["text"], font, text_line_spacing,
                               highlights=block.get("highlights", []),
                               strength=block.get("text_backdrop_strength", "normal"))

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

    out_name = os.path.splitext(os.path.basename(page["filename"]))[0] + ".png"
    out_path = os.path.join(out_dir, out_name)
    os.makedirs(out_dir, exist_ok=True)
    img.convert("RGB").save(out_path)
    print("Lagret (square):", out_path)
    return [out_path]


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
        blank_path = _dp_first(BOOK_DREAMPAGE_FIRST)

        if not os.path.exists(blank_path):
            print("Fant ikke dreampage-first.png:", blank_path)
            return []

        img = Image.open(blank_path).convert("RGBA")
        draw = ImageDraw.Draw(img)

        img_w, img_h = img.size
        scale_x = img_w / INNER_WIDTH
        scale_y = img_h / INNER_HEIGHT

        # --- 1) Elegant inside-page title (not the gold cover style) ---
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
                int(img_h * 0.88),
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

        # --- Tagline (rendret av scriptet, over "© 2026 DreamPage") ---
        _dpf_tag_lines = DREAMPAGE_FIRST_TAGLINE.splitlines()
        _dpf_tag_fs = int(img_h * 0.033)
        try:
            _dpf_tag_font = ImageFont.truetype(COVER_FONT, _dpf_tag_fs)
        except Exception:
            _dpf_tag_font = ImageFont.load_default()
        _dpf_tag_gap = int(_dpf_tag_fs * 0.30)
        _dpf_tag_dims = [draw.textbbox((0, 0), _t, font=_dpf_tag_font) for _t in _dpf_tag_lines]
        _dpf_tag_total = sum((b[3] - b[1]) for b in _dpf_tag_dims) + _dpf_tag_gap * (len(_dpf_tag_lines) - 1)
        _dpf_ty = int(img_h * 0.735) - _dpf_tag_total // 2
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

    if page.get("square"):
        return _render_square_page(page, base_path, out_dir)

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

            # Baksiden er type "cover", saa _dp_split_inner_story_blocks roerer
            # den ikke - den la aldri paa backdrop her. Teksten sto derfor rett
            # paa illustrasjonen. Vi legger den paa eksplisitt, i "strong" siden
            # baksidebildet er lyst og travelt.
            draw_text_backdrop(
                img, box, block["text"], font, line_spacing,
                highlights=block.get("highlights", []),
                align="center", strength="strong",
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
    need = ["bakside(kongeriket).png", "ryggrad.png", "forside(kongeriket).png"]
    missing = [n for n in need if n not in cover_rendered]

    if missing:
        print("Cover PDF ble IKKE laget. Mangler rendret cover-del(er):", ", ".join(missing))
        return

    back_path  = cover_rendered["bakside(kongeriket).png"]
    spine_path = cover_rendered["ryggrad.png"]
    front_path = cover_rendered["forside(kongeriket).png"]

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
  'Prinsesse {name} og\nKongerikets Hemmelighet': 'Prinsesse {name} og\nKongerikets Hemmelighet',
  'Takk for at du kjøpte denne personlige historien!\nI denne boken våkner {name} til sin aller første dag som prinsesse, og oppdager en hemmelighet dypt under slottet som kan redde hele kongeriket.\nVi håper historien bringer glede, spenning og fantasifulle øyeblikk.': 'Takk for at du kjøpte denne personlege historia!\nI denne boka vaknar {name} til sin aller første dag som prinsesse, og oppdagar ein løyndom djupt under slottet som kan redde heile kongeriket.\nVi håper historia gjev glede, spaning og fantasifulle augneblinkar.',
  'Det var den første morgenen til {name} som prinsesse.\nFra balkongen kunne hun se hele kongeriket våkne.\nElven glitret mellom åsene, og fuglene fløy over tårnene.\n{name} ante ikke at en stor oppgave allerede ventet.': 'Det var den første morgonen til {name} som prinsesse.\nFrå balkongen kunne ho sjå heile kongeriket vakne.\nElva glitra mellom åsane, og fuglane flaug over tårna.\n{name} ana ikkje at ei stor oppgåve alt venta.',
  'Senere gikk {name} gjennom slottsgården da hun stoppet.\nDen store fontenen, som alltid sprutet mot himmelen, var stille.\nBlomstene hang tungt, og bare noen dråper rant fra steinen.\n«Hvor har alt vannet blitt av?» undret {name}.': 'Seinare gjekk {name} gjennom slottsgarden då ho stoppa.\nDen store fontenen, som alltid spruta mot himmelen, var stille.\nBlomane hang tungt, og berre nokre dropar rann frå steinen.\n«Kvar har alt vatnet blitt av?» undra {name}.',
  'Dronningen kom bort og så alvorlig på den tomme fontenen.\n«Elven som gir vann til hele kongeriket blir svakere,» sa hun.\nIngen visste hvorfor, og snart kunne alle mangle vann.\n{name} rettet ryggen. Dette skulle bli hennes første oppgave.': 'Dronninga kom bort og såg alvorleg på den tomme fontenen.\n«Elva som gjev vatn til heile kongeriket blir svakare,» sa ho.\nIngen visste kvifor, og snart kunne alle mangle vatn.\n{name} retta ryggen. Dette skulle bli hennar første oppgåve.',
  '{name} skyndte seg til det gamle biblioteket for å lete etter svar.\nMellom støvete bøker fant hun et gammelt kart over slottet.\nUnder slottet var det tegnet en vannvei hun aldri hadde sett.\n«Kanskje vannet ikke bare kommer fra elven,» tenkte hun.': '{name} skunda seg til det gamle biblioteket for å leite etter svar.\nMellom støvete bøker fann ho eit gammalt kart over slottet.\nUnder slottet var det teikna ein vassveg ho aldri hadde sett.\n«Kanskje vatnet ikkje berre kjem frå elva,» tenkte ho.',
  'Kartet førte {name} til en bortgjemt del av slottsgården.\nBak eføy og gamle roser oppdaget hun en liten steindør.\nDa hun skjøv greinene til side, strømmet kald luft ut fra mørket.\n{name} tok et dypt pust og åpnet døren.': 'Kartet førte {name} til ein bortgøymd del av slottsgarden.\nBak eføy og gamle roser oppdaga ho ei lita steindør.\nDå ho skuva greinene til side, strøymde kald luft ut frå mørkret.\n{name} tok eit djupt pust og opna døra.',
  'Med en lykt i hånden gikk {name} ned trappene under slottet.\nSteinveggene var kalde, og dryppende vann fulgte henne.\nJo lenger hun gikk, desto tydeligere hørte hun noe som rant.\nHun løftet lykten og fortsatte.': 'Med ei lykt i handa gjekk {name} ned trappene under slottet.\nSteinveggene var kalde, og dryppande vatn følgde henne.\nJo lenger ho gjekk, dess tydelegare høyrde ho noko som rann.\nHo lyfte lykta og heldt fram.',
  'Plutselig åpnet tunnelen seg til en enorm hule.\nForan {name} rant en skjult blå elv mellom gamle steinkanaler.\nVannet glitret svakt, som en hemmelig verden under slottet.\n«Så det er her vannet kommer fra!» hvisket hun.': 'Brått opna tunnelen seg til ei enorm hole.\nFramfor {name} rann ei løynd blå elv mellom gamle steinkanalar.\nVatnet glitra svakt, som ei hemmeleg verd under slottet.\n«Så det er her vatnet kjem frå!» kviskra ho.',
  '{name} fulgte elven videre, men strømmen ble svakere.\nTil slutt var det bare små dammer igjen mellom steinene.\nHun satte seg ned og studerte vannet nøye.\nFant hun ut hvor strømmen stoppet, kunne hun redde kongeriket.': '{name} følgde elva vidare, men straumen blei svakare.\nTil slutt var det berre små dammar att mellom steinane.\nHo sette seg ned og studerte vatnet nøye.\nFann ho ut kvar straumen stoppa, kunne ho redde kongeriket.',
  'Bak en gammel steinbue fant {name} et skjult rom.\nPå veggene var det skåret ut elver, fontener og vannveier.\nMidt i rommet stod en stor mekanisme av stein og metall.\nNoen hadde bygget dette stedet for å lede vannet.': 'Bak ein gammal steinboge fann {name} eit løynd rom.\nPå veggene var det skore ut elvar, fontener og vassvegar.\nMidt i rommet stod ein stor mekanisme av stein og metall.\nNokon hadde bygd denne staden for å leie vatnet.',
  'Bak kammeret fant hun noe enda mer utrolig.\nEn klar kilde fylte et gammelt steinbasseng med friskt vann.\nDet var mer enn nok vann. Problemet var at det ikke kom videre.\nDa visste {name} at løsningen måtte være like i nærheten.': 'Bak kammeret fann ho noko endå meir utruleg.\nEi klar kjelde fylte eit gammalt steinbasseng med friskt vatn.\nDet var meir enn nok vatn. Problemet var at det ikkje kom vidare.\nDå visste {name} at løysinga måtte vere like i nærleiken.',
  'Hun fulgte kanalen til en gammel steinport og fant årsaken.\nStore steiner hadde rast ned og satt seg fast foran porten.\nBak dem presset vannet på, men det hadde ingen vei ut.\n«Jeg har funnet det!» ropte {name}.': 'Ho følgde kanalen til ein gammal steinport og fann årsaka.\nStore steinar hadde rasa ned og sett seg fast framfor porten.\nBak dei pressa vatnet på, men det hadde ingen veg ut.\n«Eg har funne det!» ropte {name}.',
  '{name} hentet hjelp og viste arbeiderne veien gjennom tunnelene.\nSammen flyttet de steinene og reparerte den gamle vannporten.\n{name} fulgte nøye med og viste hvor vannet skulle ledes.\nSå, med et kraftig brus, åpnet porten seg.': '{name} henta hjelp og viste arbeidarane vegen gjennom tunnelane.\nSaman flytta dei steinane og reparerte den gamle vassporten.\n{name} følgde nøye med og viste kvar vatnet skulle leiast.\nSå, med eit kraftig brus, opna porten seg.',
  'Vannet strømmet gjennom kanalene og tilbake til kongeriket.\nI slottsgården sprutet fontenen igjen, og blomstene løftet seg.\nFolk jublet mens {name} så utover alt hun hadde reddet.\n«Du fant løsningen da ingen andre visste hvor de skulle lete.»': 'Vatnet strøymde gjennom kanalane og tilbake til kongeriket.\nI slottsgarden spruta fontenen igjen, og blomane lyfte seg.\nFolk jubla medan {name} såg utover alt ho hadde redda.\n«Du fann løysinga då ingen andre visste kvar dei skulle leite.»',
  'Den kvelden stod {name} sammen med dronningen på balkongen.\nElven glitret igjen, og fontenene danset i slottsgården.\n{name} hadde lært at det å være prinsesse er mer enn en krone.\nDet handler om å lytte, tenke og ta vare på dem som trenger deg.': 'Den kvelden stod {name} saman med dronninga på balkongen.\nElva glitra igjen, og fontenene dansa i slottsgarden.\n{name} hadde lært at det å vere prinsesse er meir enn ei krone.\nDet handlar om å lytte, tenkje og ta vare på dei som treng deg.',
  'Denne boken handler om å lete videre når andre gir opp. Om å stille spørsmål, tenke selv og finne svar der ingen har lett før.\nNår vannet forsvinner fra kongeriket, følger {name} et gammelt kart ned i mørket under slottet – og finner en hemmelighet som har ligget skjult i mange år.\nEn varm og spennende historie om mot, nysgjerrighet og om å ta ansvar for noe større enn seg selv.\nEn bok som minner barnet på at små hender kan utgjøre en stor forskjell.': 'Denne boka handlar om å leite vidare når andre gjev opp. Om å stille spørsmål, tenkje sjølv og finne svar der ingen har leita før.\nNår vatnet forsvinn frå kongeriket, følgjer {name} eit gammalt kart ned i mørkret under slottet – og finn ein løyndom som har lege skjult i mange år.\nEi varm og spennande historie om mot, nysgjerrigheit og om å ta ansvar for noko større enn seg sjølv.\nEi bok som minner barnet på at små hender kan utgjere ein stor skilnad.',
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
    if number in (2, 9, 11, 13, 14):
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
    if page.get("no_split"):
        _dp_mark_backdrop(block, filename, child_name)
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

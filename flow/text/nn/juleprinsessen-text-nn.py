

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

# 14 oppslag x 2 + intro + blank-back = 30. Ingen Lastpage enda.
EXPECTED_INNER_PAGES = 30

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
# Linje 1 paa forsiden bruker Fredoka Bold, samme font som logoen i linje 2.
FRONT_COVER_LINE1_FONT = os.path.join(SCRIPT_DIR, "Fredoka-Bold.ttf")
LOGO_DIR = os.path.join(SCRIPT_ROOT_DIR, "logo", SCRIPT_LOCALE)
INNER_FONT     = os.path.join(SCRIPT_DIR, "Georgia.ttf")

BOOK_DREAMPAGE_FIRST = os.path.join(
    DP_ROOT, "books", "juleprinsessen", "dreampage-first-juleprinsessen.png"
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

    font_small = ImageFont.truetype(_dp_line1_font(), int(min(img.size) * 0.08))
    font_large = ImageFont.truetype(COVER_FONT, int(min(img.size) * 0.095))


    # prinsesse (BRUKES I PRINSESSE BOKEN)
    gold   = ((255, 255, 255), (255, 245, 220))
    shadow = (10, 14, 35)


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

    # Lange titler (engelsk) var bredere enn forsiden og ble kuttet.
    max_w2 = int(w * 0.92)
    while line2 and w2 > max_w2 and font_large.size > 12:
        font_large = ImageFont.truetype(COVER_FONT, font_large.size - 2)
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
#  FORSIDE-TITTEL - navn som tekst + Motet i Hjertet-logo som linje 2
# ---------------------------------------------------------------------------
FRONT_COVER_LOGO_SCALE = 0.46
FRONT_COVER_LOGO_X_OFFSET = 0
FRONT_COVER_TOP_MARGIN = 0.030
FRONT_COVER_LINE_SPACING = 0.0              # ubrukt i inline-oppsettet
FRONT_COVER_LINE1_SIZE = 96 / 1254          # andel av kortsiden (malen er 1254 px)
FRONT_COVER_GAP = 0.022                     # luft mellom logo og navn, andel av bredden
FRONT_COVER_MAX_WIDTH = 0.90                # hele gruppa krympes til aa passe innenfor
FRONT_COVER_NAME_Y = 0.42                   # navnets midtlinje, andel av logohoyden
FRONT_COVER_GOLD = ((255, 255, 255), (255, 245, 220))
FRONT_COVER_SHADOW = (10, 14, 35)

FRONT_COVER_LINE1_EXTRA = ""


def _dp_line1_font() -> str:
    """Fredoka Bold hvis den finnes, ellers dagens Playfair - aldri krasj."""
    path = globals().get("FRONT_COVER_LINE1_FONT", "")
    return path if path and os.path.exists(path) else COVER_FONT


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
        "nb": "juleprinsessen-logo-nb.png",
        "nn": "juleprinsessen-logo-nb.png",
        "en-US": "juleprinsessen-logo-en.png",
        "en-GB": "juleprinsessen-logo-en.png",
        "sv": "juleprinsessen-logo-sv.png",
    }.get(SCRIPT_LOCALE, "juleprinsessen-logo-nb.png")
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

    name = (text.splitlines()[0] if text else "").strip()
    logo = _crop_logo_to_visible_alpha(Image.open(logo_path).convert("RGBA"))

    def _measure(scale):
        lw = max(1, int(w * FRONT_COVER_LOGO_SCALE * scale))
        lh = max(1, int(logo.height * (lw / logo.width)))
        fs = max(8, int(base * FRONT_COVER_LINE1_SIZE * scale))
        fnt = ImageFont.truetype(_dp_line1_font(), fs)
        if not name:
            return lw, lh, fnt, (0, 0, 0, 0), 0, lw
        bb = draw.textbbox((0, 0), name, font=fnt)
        gap = int(w * FRONT_COVER_GAP * scale)
        return lw, lh, fnt, bb, gap, lw + gap + (bb[2] - bb[0])

    lw, lh, font_small, bb, gap, total = _measure(1.0)
    limit = int(w * FRONT_COVER_MAX_WIDTH)
    if total > limit:
        # mal om med den samlede krympefaktoren - fonten runder av, saa
        # bredden maales paa nytt i stedet for aa regnes ut.
        lw, lh, font_small, bb, gap, total = _measure(limit / float(total))

    logo = logo.resize((lw, lh), Image.LANCZOS)
    shadow_offset = max(3, int(font_small.size * 0.04))

    # Gruppa forankres til VENSTRE marg, ikke midtstilles: jenta staar i
    # hoeyre halvdel, og en midtstilt gruppe flytter logoen inn i tiaraen
    # hennes saa snart navnet er kort. Venstreforankring gir logoen samme
    # plass i hver eneste ordre.
    x0 = max(0, (w - int(w * FRONT_COVER_MAX_WIDTH)) // 2
             + FRONT_COVER_LOGO_X_OFFSET)
    y_top = int(h * FRONT_COVER_TOP_MARGIN)

    def _mask(x, y, t, fnt):
        m = Image.new("L", img.size, 0)
        ImageDraw.Draw(m).text((x, y), t, font=fnt, fill=255)
        return m

    def _gradient(mask, bbox, top, bottom):
        x0b, y0b, x1b, y1b = bbox
        grad = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(grad)
        height = max(1, y1b - y0b)
        for i in range(y0b, y1b):
            t = (i - y0b) / height
            d.line([(x0b, i), (x1b, i)], fill=(
                int(top[0] + (bottom[0] - top[0]) * t),
                int(top[1] + (bottom[1] - top[1]) * t),
                int(top[2] + (bottom[2] - top[2]) * t),
                255,
            ))
        img.paste(grad, (0, 0), mask)

    # logoen foerst
    shadow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow_img = Image.new("RGBA", (lw, lh), (*FRONT_COVER_SHADOW, 180))
    shadow_img.putalpha(logo.split()[3])
    shadow_layer.paste(shadow_img, (x0 + shadow_offset, y_top + shadow_offset))
    shadow_layer = shadow_layer.filter(
        ImageFilter.GaussianBlur(max(8, int(lh * 0.20))))
    img.alpha_composite(shadow_layer)
    img.alpha_composite(logo, (x0, y_top))

    if not name:
        return

    # navnet etter, loddrett midtstilt mot logoen
    tx = x0 + lw + gap - bb[0]
    # Midtstilles mot ORDET i logoen, ikke mot hele bildefila: nederste
    # tredjedel av logoen er kristtorn og krusedull, og 0.5 la navnet lavt.
    ty = y_top + int(lh * FRONT_COVER_NAME_Y) - (bb[3] - bb[1]) // 2 - bb[1]

    sm = _mask(tx + shadow_offset, ty + shadow_offset, name, font_small)
    sm = sm.filter(ImageFilter.GaussianBlur(max(1, shadow_offset // 2)))
    img.paste((*FRONT_COVER_SHADOW, 255), (0, 0), sm)
    tm = _mask(tx, ty, name, font_small)
    _gradient(tm, draw.textbbox((tx, ty), name, font=font_small),
              FRONT_COVER_GOLD[0], FRONT_COVER_GOLD[1])

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
            "filename": "forside(juleprinsessen).png",
            "type": "cover",
            "text": p("(Navn)\nJuleprinsessen"),
        },
        {
            "filename": "ryggrad.png",
            "type": "cover",
        },

        # Side 1
        {
            "filename": "01(juleprinsessen).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Høyt oppe på en frostglitrende ås lå slottet der (Navn) bodde.\n"
                    "Hun hadde hørt om snø. Hun hadde sett bilder av snø.\n"
                    "Men aldri hadde et eneste snøfnugg landet i hånden hennes.\n"
                    "Hver vinter så hun opp på himmelen og håpet at akkurat denne skulle bli annerledes."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "slottet", "snøfnugg", "himmelen"],
            }],
        },

        # Side 2
        {
            "filename": "02(juleprinsessen).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Nå var det julaften, og hele slottet skinte.\n"
                    "Juletreet lyste, lysene brant, og det luktet kaker i hver eneste gang.\n"
                    "Men (Navn) stod ved vinduet og så ut på den bare bakken.\n"
                    "«Jeg ønsker meg bare ett eneste snøfnugg,» hvisket hun."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "julaften", "vinduet", "snøfnugg"],
            }],
        },

        # Side 3
        {
            "filename": "03(juleprinsessen).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Akkurat da fór et gyllent lys over den mørkeblå himmelen.\n"
                    "Det var varmere enn en stjerne, og det la igjen et glitrende spor.\n"
                    "(Navn) trykket hendene mot det kalde vinduet.\n"
                    "Det føltes ikke som noe hun bare skulle se på. Det føltes som om lyset hadde funnet henne."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "gyllent", "stjerne", "glitrende"],
            }],
        },

        # Side 4
        {
            "filename": "04(juleprinsessen).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Hun tok på seg den røde kappen, luen og de varme støvlene.\n"
                    "Så åpnet (Navn) den store slottsporten og gikk ut i vinternatten.\n"
                    "Bak henne ble det varme lyset fra slottet mindre og mindre.\n"
                    "Foran henne lå det gyldne sporet og ventet mellom trærne."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "kappen", "slottsporten", "vinternatten"],
            }],
        },

        # Side 5
        {
            "filename": "05(juleprinsessen).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Inne mellom grantrærne hørte hun en liten lyd ved røttene.\n"
                    "Et par lange ører kom til syne. Så en liten, hvit snøhare.\n"
                    "«Hei,» sa (Navn) forsiktig. «Så du lyset, du også?»\n"
                    "Haren pekte med nesen mot sporet på himmelen. Fra nå av het han Fnugg, og nå var de to."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "snøhare", "Fnugg", "sporet"],
            }],
        },

        # Side 6
        {
            "filename": "06(juleprinsessen).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Sporet førte dem ned til et vann som lå blankt og stille mellom trærne.\n"
                    "Isen speilet stjernene, og det gyldne lyset glitret under føttene deres.\n"
                    "(Navn) skled, fektet med armene og fant balansen igjen.\n"
                    "Så begynte hun å le, og Fnugg hoppet etter henne over hele isen."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "Isen", "stjernene", "le"],
            }],
        },

        # Side 7
        {
            "filename": "07(juleprinsessen).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "På den andre siden av vannet stoppet de helt opp.\n"
                    "Hele himmelen hadde fylt seg med grønne og fiolette bølger som beveget seg sakte.\n"
                    "(Navn) satte seg ned i snøen ved siden av Fnugg og glemte å puste.\n"
                    "Midt inne i fargene lyste det gyldne sporet videre, ned mot dalen."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "himmelen", "bølger", "dalen"],
            }],
        },

        # Side 8
        {
            "filename": "08(juleprinsessen).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Under dem lå en landsby hun aldri hadde sett på noe kart.\n"
                    "Små hus med snødekte tak sto tett i tett, og fra hvert vindu kom det varmt lys.\n"
                    "Men det var altfor stille dernede. Ingen sang, ingen bjeller.\n"
                    "«Noe er galt,» sa (Navn), og begynte å gå ned mot lysene."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "landsby", "lys", "stille"],
            }],
        },

        # Side 9
        {
            "filename": "09(juleprinsessen).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Inne i det største huset sto det lange benker fulle av leker.\n"
                    "Små nisser løp fram og tilbake, og midt i rommet sto en gammel mann med hvitt skjegg.\n"
                    "Han snudde seg og så på (Navn) med trøtte øyne.\n"
                    "«Du kom,» sa han stille. «Jeg håpet noen ville følge etter lyset.»"
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "leker", "nisser", "lyset"],
            }],
        },

        # Side 10
        {
            "filename": "10(juleprinsessen).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Han tok henne med ut og pekte opp mot den mørke himmelen.\n"
                    "«Julestjernen falt av sleden i natt. Uten den finner ikke reinsdyrene veien.»\n"
                    "Nede ved gjerdet sto sleden ferdig pakket, og reinsdyrene ventet urolig.\n"
                    "(Navn) kjente hjertet slå fortere. Hun visste hvor lyset hadde landet."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "Julestjernen", "sleden", "reinsdyrene"],
            }],
        },

        # Side 11
        {
            "filename": "11(juleprinsessen).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Hun og Fnugg lette seg oppover bakken, dit sporet hadde sluttet.\n"
                    "Og der, halvveis nede i den myke snøen, lå den.\n"
                    "En gyllen stjerne som fortsatt pustet med et varmt lys.\n"
                    "Forsiktig løftet (Navn) den opp med begge hendene."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "Fnugg", "gyllen", "stjerne"],
            }],
        },

        # Side 12
        {
            "filename": "12(juleprinsessen).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Stjernen var tyngre enn den så ut, men (Navn) bar den hele veien.\n"
                    "Opp gjennom skogen, forbi de snødekte grantrærne, helt til toppen av åsen.\n"
                    "Månen sto stor over dalen, og langt der nede ventet landsbyen.\n"
                    "«Nå,» hvisket hun, og løftet stjernen så høyt hun kunne."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "Stjernen", "Månen", "landsbyen"],
            }],
        },

        # Side 13
        {
            "filename": "13(juleprinsessen).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Stjernen tente seg i hendene hennes og skjøt lyset ut over hele himmelen.\n"
                    "Fjellene, vannet og hvert eneste tak i landsbyen ble badet i gull.\n"
                    "Langt nede hørte hun bjeller, latter og en slede som lettet fra bakken.\n"
                    "Julen var reddet, og det var (Navn) som hadde gjort det."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "Stjernen", "gull", "bjeller"],
            }],
        },

        # Side 14
        {
            "filename": "14(juleprinsessen).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Da (Navn) kom hjem til slottet, var himmelen helt stille igjen.\n"
                    "Og så, langsomt, kom det første snøfnugget dalende ned og landet i hånden hennes.\n"
                    "Så ett til. Og ett til. Snøen la seg over takene, over trærne, over hele åsen.\n"
                    "(Navn) snurret rundt med Fnugg i den hvite julemorgenen, og lo."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "snøfnugget", "Snøen", "Fnugg"],
            }],
        },

        # Bakside
        {
            "filename": "bakside(juleprinsessen).png",
            "type": "cover",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Denne boken handler om et lite juleønske. Om å tørre å gå ut i vinternatten alene, fordi noe inni deg sier at du må.\n"
                    "Når (Navn) følger det gyldne lyset over himmelen, møter hun snøharen Fnugg, en glemt landsby og en jul som trenger akkurat henne.\n"
                    "En varm fortelling om mot, vennskap og om å gi bort noe til noen andre.\n"
                    "En bok som minner barnet på at de aller minste hendene kan redde den største kvelden."
                ),
                "font_size": 46,
                "color": "#FFFFFF",
                "highlights": [child_name, "juleønske", "Fnugg", "mot", "vennskap", "barnet"],
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
RYGGRAD_BOOK_SLUG = "juleprinsessen"
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
        blank_path = os.path.join(SCRIPT_DIR, "dreampage-first.png")

        if not os.path.exists(blank_path):
            raise FileNotFoundError("Fant ikke dreampage-first.png i script-mappen")

        img = Image.open(blank_path).convert("RGBA")
        draw = ImageDraw.Draw(img)

        img_w, img_h = img.size
        scale_x = img_w / INNER_WIDTH
        scale_y = img_h / INNER_HEIGHT

        # --- 1) Tegn samme tittel som forsiden ---
        title_text = page.get("text")
        if title_text:
            draw_centered_title_cover(img, title_text)

        # --- 2) Tegn beskrivende tekst ---
        for block in page.get("blocks", []):
            base_size = block.get("font_size", 40)
            font_size = int(base_size * min(scale_x, scale_y))
            font = ImageFont.truetype(INNER_FONT, font_size)

            box = (
                int(img_w * 0.15),
                int(img_h * 0.30) + int(block.get("y_offset", 0)),
                int(img_w * 0.85),
                int(img_h * 0.90)
            )

            draw_text(
                draw=draw,
                text=block["text"],
                box=box,
                font=font,
                color=block.get("color", TEXT_COLOR), 
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

            # Ett samlet felt bak hele bakside-teksten (ikke per linje).
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
    og lagrer resultatet til out_dir. Returnerer stien til den renderte filen.
    """
    src = _dp_first(BOOK_DREAMPAGE_FIRST)
    dst = os.path.join(out_dir, "dreampage-first-rendered.png")

    img = Image.open(src).convert("RGBA")
    draw = ImageDraw.Draw(img)
    w, h = img.size

    title_line = f"Til {child_name}"
    body_lines = [
        "Denne boka er laga spesielt for deg.",
        f"Du er {child_name} — den modige i denne historia.",
        "",
        "Det er draumane dine, motet ditt",
        "og måla dine som fyller desse sidene.",
        "",
        "Tru alltid på deg sjølv,",
        "akkurat som du gjer i denne historia.",
    ]

    font_title_size = int(h * 0.045)   # ~184 px ved 4096
    font_body_size  = int(h * 0.030)   # ~122 px ved 4096

    try:
        font_title = ImageFont.truetype(COVER_FONT, font_title_size)
        font_body  = ImageFont.truetype(COVER_FONT, font_body_size)
    except Exception:
        font_title = ImageFont.load_default()
        font_body  = ImageFont.load_default()

    text_color = (35, 30, 25, 255)   # varm mørk brun

    # --- Mål opp tekstblokken ---
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

    # Sentrer blokken vertikalt i øverste 65 % av siden
    usable_h = int(h * 0.65)
    start_y  = max(int(h * 0.12), (usable_h - total_h) // 2)

    # --- Tegn tittellinje ---
    t_w = t_bbox[2] - t_bbox[0]
    draw.text(((w - t_w) // 2, start_y), title_line, font=font_title, fill=text_color)
    y = start_y + t_h + title_gap

    # --- Tegn brødtekst ---
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


    # Legg til dreampage-first.png f?rst, blank-back.png deretter, og per-bok Lastpage(prinsesse).png aller sist.
    # Disse er enkelt-sider (4096x4096) som ikke skal splittes - bare inkluderes direkte.
    dreampage_first = _dp_first(BOOK_DREAMPAGE_FIRST)
    # Ordrens egen blank-back.png (f.eks. "Fortsett eventyret"-siden med QR)
    # har forrang; den delte malen er fallback for boker uten oppsalg.
    blank_back = os.path.join(base_dir, "blank-back.png")
    if not os.path.exists(blank_back):
        blank_back = os.path.join(SCRIPT_DIR, "blank-back.png")
    else:
        print("[INNER PDF] Bruker siste innerside fra ordremappen:", blank_back)
    last_page = resolve_lastpage_path("Lastpage(juleprinsessen).png")
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
        print(f"ADVARSEL: Fant ikke Lastpage(juleprinsessen).png i {LASTPAGE_DIR} - hopper over")





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
    need = ["bakside(juleprinsessen).png", "ryggrad.png", "forside(juleprinsessen).png"]
    missing = [n for n in need if n not in cover_rendered]

    if missing:
        print("Cover PDF ble IKKE laget. Mangler rendret cover-del(er):", ", ".join(missing))
        return

    back_path  = cover_rendered["bakside(juleprinsessen).png"]
    spine_path = cover_rendered["ryggrad.png"]
    front_path = cover_rendered["forside(juleprinsessen).png"]

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
  '{name}\nJuleprinsessen': '{name}\nJuleprinsessen',
  'Høyt oppe på en frostglitrende ås lå slottet der {name} bodde.\nHun hadde hørt om snø. Hun hadde sett bilder av snø.\nMen aldri hadde et eneste snøfnugg landet i hånden hennes.\nHver vinter så hun opp på himmelen og håpet at akkurat denne skulle bli annerledes.': 'Høgt oppe på ein frostglitrande ås låg slottet der {name} budde.\nHo hadde høyrt om snø. Ho hadde sett bilete av snø.\nMen aldri hadde eit einaste snøfnugg landa i handa hennar.\nKvar vinter såg ho opp på himmelen og håpa at nettopp denne skulle bli annleis.',
  'Nå var det julaften, og hele slottet skinte.\nJuletreet lyste, lysene brant, og det luktet kaker i hver eneste gang.\nMen {name} stod ved vinduet og så ut på den bare bakken.\n«Jeg ønsker meg bare ett eneste snøfnugg,» hvisket hun.': 'No var det julaftan, og heile slottet skein.\nJuletreet lyste, lysa brann, og det lukta kaker i kvar einaste gang.\nMen {name} stod ved vindauget og såg ut på den bare bakken.\n«Eg ønskjer meg berre eitt einaste snøfnugg,» kviskra ho.',
  'Akkurat da fór et gyllent lys over den mørkeblå himmelen.\nDet var varmere enn en stjerne, og det la igjen et glitrende spor.\n{name} trykket hendene mot det kalde vinduet.\nDet føltes ikke som noe hun bare skulle se på. Det føltes som om lyset hadde funnet henne.': 'Akkurat då fór eit gylent lys over den mørkeblå himmelen.\nDet var varmare enn ei stjerne, og det la att eit glitrande spor.\n{name} trykte hendene mot det kalde vindauget.\nDet kjendest ikkje som noko ho berre skulle sjå på. Det kjendest som om lyset hadde funne henne.',
  'Hun tok på seg den røde kappen, luen og de varme støvlene.\nSå åpnet {name} den store slottsporten og gikk ut i vinternatten.\nBak henne ble det varme lyset fra slottet mindre og mindre.\nForan henne lå det gyldne sporet og ventet mellom trærne.': 'Ho tok på seg den raude kappa, lua og dei varme støvlane.\nSå opna {name} den store slottsporten og gjekk ut i vinternatta.\nBak henne vart det varme lyset frå slottet mindre og mindre.\nFramfor henne låg det gylne sporet og venta mellom trea.',
  'Inne mellom grantrærne hørte hun en liten lyd ved røttene.\nEt par lange ører kom til syne. Så en liten, hvit snøhare.\n«Hei,» sa {name} forsiktig. «Så du lyset, du også?»\nHaren pekte med nesen mot sporet på himmelen. Fra nå av het han Fnugg, og nå var de to.': 'Inne mellom granene høyrde ho ein liten lyd ved røtene.\nEit par lange øyre kom til syne. Så ein liten, kvit snøhare.\n«Hei,» sa {name} forsiktig. «Såg du lyset, du òg?»\nHaren peika med nasen mot sporet på himmelen. Frå no av heitte han Fnugg, og no var dei to.',
  'Sporet førte dem ned til et vann som lå blankt og stille mellom trærne.\nIsen speilet stjernene, og det gyldne lyset glitret under føttene deres.\n{name} skled, fektet med armene og fant balansen igjen.\nSå begynte hun å le, og Fnugg hoppet etter henne over hele isen.': 'Sporet førte dei ned til eit vatn som låg blankt og stille mellom trea.\nIsen spegla stjernene, og det gylne lyset glitra under føtene deira.\n{name} skleid, fekta med armane og fann balansen igjen.\nSå byrja ho å le, og Fnugg hoppa etter henne over heile isen.',
  'På den andre siden av vannet stoppet de helt opp.\nHele himmelen hadde fylt seg med grønne og fiolette bølger som beveget seg sakte.\n{name} satte seg ned i snøen ved siden av Fnugg og glemte å puste.\nMidt inne i fargene lyste det gyldne sporet videre, ned mot dalen.': 'På den andre sida av vatnet stoppa dei heilt opp.\nHeile himmelen hadde fylt seg med grøne og fiolette bølgjer som rørte seg sakte.\n{name} sette seg ned i snøen ved sida av Fnugg og gløymde å puste.\nMidt inne i fargane lyste det gylne sporet vidare, ned mot dalen.',
  'Under dem lå en landsby hun aldri hadde sett på noe kart.\nSmå hus med snødekte tak sto tett i tett, og fra hvert vindu kom det varmt lys.\nMen det var altfor stille dernede. Ingen sang, ingen bjeller.\n«Noe er galt,» sa {name}, og begynte å gå ned mot lysene.': 'Under dei låg ein landsby ho aldri hadde sett på noko kart.\nSmå hus med snødekte tak stod tett i tett, og frå kvart vindauge kom det varmt lys.\nMen det var altfor stille der nede. Ingen song, ingen bjøller.\n«Noko er gale,» sa {name}, og byrja å gå ned mot lysa.',
  'Inne i det største huset sto det lange benker fulle av leker.\nSmå nisser løp fram og tilbake, og midt i rommet sto en gammel mann med hvitt skjegg.\nHan snudde seg og så på {name} med trøtte øyne.\n«Du kom,» sa han stille. «Jeg håpet noen ville følge etter lyset.»': 'Inne i det største huset stod det lange benker fulle av leiker.\nSmå nissar sprang fram og tilbake, og midt i rommet stod ein gammal mann med kvitt skjegg.\nHan snudde seg og såg på {name} med trøytte auge.\n«Du kom,» sa han stille. «Eg håpa nokon ville følgje etter lyset.»',
  'Han tok henne med ut og pekte opp mot den mørke himmelen.\n«Julestjernen falt av sleden i natt. Uten den finner ikke reinsdyrene veien.»\nNede ved gjerdet sto sleden ferdig pakket, og reinsdyrene ventet urolig.\n{name} kjente hjertet slå fortere. Hun visste hvor lyset hadde landet.': 'Han tok henne med ut og peika opp mot den mørke himmelen.\n«Julestjerna fall av sleden i natt. Utan henne finn ikkje reinsdyra vegen.»\nNede ved gjerdet stod sleden ferdig pakka, og reinsdyra venta uroleg.\n{name} kjende hjartet slå fortare. Ho visste kvar lyset hadde landa.',
  'Hun og Fnugg lette seg oppover bakken, dit sporet hadde sluttet.\nOg der, halvveis nede i den myke snøen, lå den.\nEn gyllen stjerne som fortsatt pustet med et varmt lys.\nForsiktig løftet {name} den opp med begge hendene.': 'Ho og Fnugg leita seg oppover bakken, dit sporet hadde slutta.\nOg der, halvvegs nede i den mjuke snøen, låg ho.\nEi gylen stjerne som framleis pusta med eit varmt lys.\nForsiktig lyfte {name} henne opp med begge hendene.',
  'Stjernen var tyngre enn den så ut, men {name} bar den hele veien.\nOpp gjennom skogen, forbi de snødekte grantrærne, helt til toppen av åsen.\nMånen sto stor over dalen, og langt der nede ventet landsbyen.\n«Nå,» hvisket hun, og løftet stjernen så høyt hun kunne.': 'Stjerna var tyngre enn ho såg ut, men {name} bar henne heile vegen.\nOpp gjennom skogen, forbi dei snødekte granene, heilt til toppen av åsen.\nMånen stod stor over dalen, og langt der nede venta landsbyen.\n«No,» kviskra ho, og lyfte stjerna så høgt ho kunne.',
  'Stjernen tente seg i hendene hennes og skjøt lyset ut over hele himmelen.\nFjellene, vannet og hvert eneste tak i landsbyen ble badet i gull.\nLangt nede hørte hun bjeller, latter og en slede som lettet fra bakken.\nJulen var reddet, og det var {name} som hadde gjort det.': 'Stjerna tende seg i hendene hennar og skaut lyset ut over heile himmelen.\nFjella, vatnet og kvart einaste tak i landsbyen vart bada i gull.\nLangt nede høyrde ho bjøller, latter og ein slede som letta frå bakken.\nJula var redda, og det var {name} som hadde gjort det.',
  'Da {name} kom hjem til slottet, var himmelen helt stille igjen.\nOg så, langsomt, kom det første snøfnugget dalende ned og landet i hånden hennes.\nSå ett til. Og ett til. Snøen la seg over takene, over trærne, over hele åsen.\n{name} snurret rundt med Fnugg i den hvite julemorgenen, og lo.': 'Då {name} kom heim til slottet, var himmelen heilt stille igjen.\nOg så, langsamt, kom det første snøfnugget dalande ned og landa i handa hennar.\nSå eitt til. Og eitt til. Snøen la seg over taka, over trea, over heile åsen.\n{name} snurra rundt med Fnugg i den kvite julemorgonen, og lo.',
  'Denne boken handler om et lite juleønske. Om å tørre å gå ut i vinternatten alene, fordi noe inni deg sier at du må.\nNår {name} følger det gyldne lyset over himmelen, møter hun snøharen Fnugg, en glemt landsby og en jul som trenger akkurat henne.\nEn varm fortelling om mot, vennskap og om å gi bort noe til noen andre.\nEn bok som minner barnet på at de aller minste hendene kan redde den største kvelden.': 'Denne boka handlar om eit lite juleønske. Om å våge å gå ut i vinternatta åleine, fordi noko inni deg seier at du må.\nNår {name} følgjer det gylne lyset over himmelen, møter ho snøharen Fnugg, ein gløymd landsby og ei jul som treng nettopp henne.\nEi varm forteljing om mot, venskap og om å gje bort noko til nokon andre.\nEi bok som minner barnet på at dei aller minste hendene kan redde den største kvelden.',
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
    number = _dp_page_number(filename)
    top_y = 25
    bottom_y = 345
    return number, top_y, bottom_y


def _dp_mark_backdrop(block: dict, filename: str, child_name: str, *, second: bool = False) -> None:
    block["text_backdrop"] = True
    block["color"] = "#FFFFFF"
    block["highlights"] = _dp_auto_highlights(block.get("text", ""), child_name, block.get("highlights", []))
    number = _dp_page_number(filename)


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
    page["blocks"] = [first_block, second_block]


# Minste tekstkolonne paa innersider, i designenheter (1536x1024-rommet).
# Grunnkolonnen er 400; per-side x_offset/width_offset trakk den ned til
# 310-375, som ga unoedvendig mange linjer. Hoeyrekanten skyves ut til
# denne bredden; venstrekanten roeres ikke.
DP_MIN_TEXT_WIDTH = 400


def _dp_block_column(block: dict, side: str):
    """Venstre/hoeyre kant av blokkens tekstkolonne i designenheter."""
    if side == "left":
        base_x1 = globals().get("LEFT_X1", 140)
        base_x2 = globals().get("LEFT_X2", 540)
    elif side == "right":
        base_x1 = globals().get("RIGHT_X1", 996)
        base_x2 = globals().get("RIGHT_X2", 1396)
    else:
        return None
    try:
        x_offset = int(block.get("x_offset", 0) or 0)
        width_offset = int(block.get("width_offset", 0) or 0)
    except (TypeError, ValueError):
        return None
    return base_x1 + x_offset, base_x2 + width_offset, width_offset


def _dp_widen_narrow_blocks(page: dict) -> None:
    """Utvid for smale tekstkolonner til DP_MIN_TEXT_WIDTH.

    Kjoeres etter _dp_split_inner_story_blocks, saa den ser de endelige
    x_offset-verdiene (inkludert +-10 paa nederste blokk).
    """
    if page.get("type") != "inner":
        return
    side = page.get("side", "right")
    for block in page.get("blocks") or []:
        if not isinstance(block, dict) or not block.get("text"):
            continue
        column = _dp_block_column(block, side)
        if column is None:
            continue
        x1, x2, width_offset = column
        missing = DP_MIN_TEXT_WIDTH - (x2 - x1)
        if missing > 0:
            block["width_offset"] = width_offset + missing


def _dp_apply_universal_layout(pages, child_name: str):
    for page in pages:
        for block in page.get("blocks") or []:
            if isinstance(block, dict) and block.get("text"):
                block["highlights"] = _dp_auto_highlights(block.get("text", ""), child_name, block.get("highlights", []))
        _dp_split_inner_story_blocks(page, child_name)
        _dp_widen_narrow_blocks(page)
    return pages


_DREAM_UNIVERSAL_ORIGINAL_BUILD_PAGES = build_pages


def build_pages(child_name: str):
    return _dp_apply_universal_layout(_DREAM_UNIVERSAL_ORIGINAL_BUILD_PAGES(child_name), child_name)

if __name__ == "__main__":
    main()

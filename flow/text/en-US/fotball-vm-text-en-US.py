


from reportlab.pdfgen import canvas
from reportlab.lib.units import inch

import shutil  

import filecmp
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

# 13 oppslag x 2 + 2 kvadratsider (side 12) + intro + blank-back = 30.
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

COVER_FONT       = os.path.join(SCRIPT_DIR, "PlayfairDisplay.ttf")
COVER_TITLE_FONT = os.path.join(SCRIPT_DIR, "Trebuchet MS Bold.ttf")
INNER_FONT     = os.path.join(SCRIPT_DIR, "Georgia.ttf")
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

LULU_TRIM_IN   = 8.5
LULU_SPINE_IN  = 0.25
LULU_COVER_W_IN = 19.0
LULU_COVER_H_IN = 10.25

# Avleder wrap fra krav (robust: hvis du endrer cover W/H senere)
LULU_WRAP_IN = (LULU_COVER_H_IN - LULU_TRIM_IN) / 2.0

def in_to_px(x: float, dpi: int = COVER_DPI) -> int:
    return int(round(x * dpi))

def cover_fit(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Skaler/crop så bildet fyller target (ingen hvite kanter)."""
    iw, ih = img.size
    scale = max(target_w / iw, target_h / ih)
    nw, nh = int(round(iw * scale)), int(round(ih * scale))
    img2 = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - target_w) // 2
    top  = (nh - target_h) // 2
    return img2.crop((left, top, left + target_w, top + target_h))



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
#  BAKGRUNNS-FJERNING (portert fra render-title.py)
# ------------------------------------------------------------

def remove_white_background(logo_img, thresh=25, defringe_thresh=0):
    """Flood fill hvit bakgrunn fra kantene. defringe_thresh=0 hopper over defringe-passet."""
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
                for nx, ny in [(x-1, y), (x+1, y), (x, y-1), (x, y+1)]:
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
    """
    Crop the logo using a thresholded alpha mask so faint semi-transparent
    background haze in the asset does not affect scaling or placement.
    """
    logo_rgba = logo_img.convert("RGBA")
    alpha = logo_rgba.getchannel("A")
    bbox = alpha.point(lambda p: 255 if p > alpha_threshold else 0).getbbox()
    if bbox:
        return logo_rgba.crop(bbox)
    return logo_rgba


# ---------------------------------------------------------------------------
#  FORSIDE-TITTEL - navn som tekst (linje 1) + Fotball-VM-logo (linje 2)
#  Verdiene speiler Set-noden "fotball-vm" i DP Title Tester og
#  config/next_book_titles.json, slik at trykk og forhandsvisning er like.
# ---------------------------------------------------------------------------
FRONT_COVER_LINE1_SIZE = 80 / 1024          # andel av kortsiden
FRONT_COVER_LINE2_SIZE = 120 / 1024         # brukes bare av tekst-fallbacken
FRONT_COVER_TOP_MARGIN = 0.02
FRONT_COVER_LINE_SPACING = 0.035
FRONT_COVER_LOGO_SCALE = 0.55
FRONT_COVER_LOGO_X_OFFSET = 0
FRONT_COVER_GOLD = ((255, 255, 255), (255, 255, 255))
FRONT_COVER_SHADOW = (15, 35, 65)
FRONT_COVER_GLOW = (12, 28, 55)
FRONT_COVER_GLOW_OPACITY = 0.85
FRONT_COVER_GLOW_RADIUS_SCALE = 0.55
FRONT_COVER_LOGO_SHADOW_OPACITY = 70


def resolve_front_cover_logo(base_dir=None):
    """Logo for gjeldende spraak, eller None hvis den ikke finnes.

    None betyr med vilje "tegn linje 2 som tekst" - den norske VM-logoen skal
    aldri havne paa en engelsk eller svensk bok.
    """
    name = {
        "nb": "fotball-vm-logo-nb.png",
        "nn": "fotball-vm-logo-nb.png",
        "en-US": "fotball-vm-logo-en.png",
        "en-GB": "fotball-vm-logo-en.png",
        "sv": "fotball-vm-logo-sv.png",
    }.get(SCRIPT_LOCALE, "fotball-vm-logo-nb.png")
    path = os.path.join(LOGO_DIR, name)
    if os.path.exists(path):
        return path
    print("[FORSIDE] Fant ingen logo for", SCRIPT_LOCALE, "- linje 2 tegnes som tekst")
    return None


def _dp_cover_trim_logo(logo):
    """Samme beskjaering som render-title-line2logo.py: flood fill, bbox og et
    tetthetspass som fjerner nesten tomme rader over og under logoen."""
    logo = remove_white_background(logo, thresh=25, defringe_thresh=0)
    bbox = logo.getbbox()
    if bbox:
        logo = logo.crop(bbox)
    lw, lh = logo.size
    px = logo.load()
    threshold = max(1, lw * 2 // 100)      # 2 % av bredden

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


def _dp_cover_paint(img, draw, text, x, y, font):
    """Glod + skygge + gradienttekst - samme rekkefolge som testeren."""
    def _mask(mx, my):
        m = Image.new("L", img.size, 0)
        ImageDraw.Draw(m).text((mx, my), text, font=font, fill=255)
        return m

    shadow_offset = max(3, int(font.size * 0.04))

    if FRONT_COVER_GLOW_OPACITY > 0:
        radius = max(18, int(font.size * FRONT_COVER_GLOW_RADIUS_SCALE))
        gm = _mask(x, y).filter(ImageFilter.GaussianBlur(radius))
        gm = gm.point(lambda p: int(p * FRONT_COVER_GLOW_OPACITY))
        img.alpha_composite(Image.merge("RGBA", (
            Image.new("L", img.size, FRONT_COVER_GLOW[0]),
            Image.new("L", img.size, FRONT_COVER_GLOW[1]),
            Image.new("L", img.size, FRONT_COVER_GLOW[2]),
            gm,
        )))

    sm = _mask(x + shadow_offset, y + shadow_offset)
    sm = sm.filter(ImageFilter.GaussianBlur(max(1, shadow_offset // 2)))
    img.paste((*FRONT_COVER_SHADOW, 255), (0, 0), sm)

    x0, y0, x1, y1 = draw.textbbox((x, y), text, font=font)
    grad = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(grad)
    top, bottom = FRONT_COVER_GOLD
    height = max(1, y1 - y0)
    for i in range(y0, y1):
        t = (i - y0) / height
        d.line([(x0, i), (x1, i)], fill=(
            int(top[0] + (bottom[0] - top[0]) * t),
            int(top[1] + (bottom[1] - top[1]) * t),
            int(top[2] + (bottom[2] - top[2]) * t),
            255,
        ))
    img.paste(grad, (0, 0), _mask(x, y))


def _dp_cover_fit_font(draw, text, font_path, size, max_w):
    """Krymp til teksten faar plass - lange navn skal ikke renne ut av forsiden."""
    font = ImageFont.truetype(font_path, size)
    while size > 8:
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_w:
            break
        size = max(8, int(size * 0.95))
        font = ImageFont.truetype(font_path, size)
    return font


def draw_centered_title_cover(img, text, base_dir=None):
    draw = ImageDraw.Draw(img)
    w, h = img.size
    base = min(w, h)
    lines = (text or "").split("\n")
    line1 = lines[0] if lines else ""
    line2 = lines[1] if len(lines) > 1 else ""
    max_w = int(w * 0.92)

    font_small = _dp_cover_fit_font(draw, line1, COVER_TITLE_FONT,
                                    int(base * FRONT_COVER_LINE1_SIZE), max_w)
    bbox1 = draw.textbbox((0, 0), line1, font=font_small)
    w1, h1 = bbox1[2] - bbox1[0], bbox1[3] - bbox1[1]
    y1_pos = int(h * FRONT_COVER_TOP_MARGIN)
    x1_pos = (w - w1) // 2
    if line1:
        _dp_cover_paint(img, draw, line1, x1_pos, y1_pos, font_small)

    y2_pos = y1_pos + h1 - int(h1 * 0.15) + int(h * FRONT_COVER_LINE_SPACING)

    logo_path = resolve_front_cover_logo(base_dir)
    if not logo_path:
        if line2:
            font_large = _dp_cover_fit_font(draw, line2, COVER_FONT,
                                            int(base * FRONT_COVER_LINE2_SIZE), max_w)
            b2 = draw.textbbox((0, 0), line2, font=font_large)
            _dp_cover_paint(img, draw, line2, (w - (b2[2] - b2[0])) // 2, y2_pos,
                            font_large)
        return

    logo = _dp_cover_trim_logo(Image.open(logo_path).convert("RGBA"))
    target_w = int(w * FRONT_COVER_LOGO_SCALE)
    target_h = int(logo.height * (target_w / logo.width))
    logo = logo.resize((target_w, target_h), Image.LANCZOS)
    lx = max(0, min(w - target_w,
                    ((w - target_w) // 2) + FRONT_COVER_LOGO_X_OFFSET))

    shadow_offset = max(3, int(font_small.size * 0.04))
    if FRONT_COVER_LOGO_SHADOW_OPACITY > 0:
        logo_alpha = logo.split()[3]
        if FRONT_COVER_LOGO_SHADOW_OPACITY < 255:
            logo_alpha = logo_alpha.point(
                lambda p: int(p * FRONT_COVER_LOGO_SHADOW_OPACITY / 255))
        shadow_img = Image.new("RGBA", (target_w, target_h),
                               (*FRONT_COVER_SHADOW, 255))
        shadow_img.putalpha(logo_alpha)
        shadow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
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


def resolve_base_image_path(base_dir: str, filename: str) -> str:
    """
    Finn eksakt fil hvis den finnes, ellers prøv samme stem med annen filendelse.
    Gjør scriptet robust for f.eks. jpg-template som senere blir rendret videre som png.
    """
    exact = os.path.join(base_dir, filename)
    if os.path.exists(exact):
        return exact

    stem = os.path.splitext(filename)[0]
    try:
        for name in os.listdir(base_dir):
            if os.path.splitext(name)[0] == stem:
                return os.path.join(base_dir, name)
    except FileNotFoundError:
        pass

    return exact


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
            "filename": "forside(fotball-vm).png",
            "type": "cover",
            "text": p("(Navn) vinner\nFotball-VM"),
        },
        {
            "filename": "ryggrad.png",
            "type": "cover",
        },

        # Side 1
        {
            "filename": "01(fotball-vm).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Noen dager etter den store finalen var (Navn) tilbake på treningsbanen.\n"
                    "Alt så helt vanlig ut, helt til treneren ropte ham bort.\n"
                    "I hånden holdt han en konvolutt med et lite norsk flagg på.\n"
                    "(Navn) kjente hjertet begynne å hamre."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "treneren", "konvolutt", "flagg"],
            }],
        },

        # Side 2
        {
            "filename": "02(fotball-vm).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "En landslagsspeider hadde sittet på tribunen under finalen.\n"
                    "Han hadde sett at (Navn) kjempet videre da kampen ble vanskelig.\n"
                    "Nå ville de se ham igjen.\n"
                    "(Navn) åpnet brevet: han var invitert til landslagssamling."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "landslagsspeider", "brevet", "landslagssamling"],
            }],
        },

        # Side 3
        {
            "filename": "03(fotball-vm).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "På samlingen møtte (Navn) spillere han aldri hadde sett før.\n"
                    "De var raske. Veldig raske.\n"
                    "Allerede i den første øvelsen mistet han ballen. Så én gang til.\n"
                    "Men han husket hva treneren hadde lært ham, og jaget ballen igjen."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "raske", "ballen", "treneren"],
            }],
        },

        # Side 4
        {
            "filename": "04(fotball-vm).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "På slutten av dagen leste landslagstreneren opp navnene.\n"
                    "Det var bare én plass igjen på laget som skulle til VM.\n"
                    "(Navn) hørte mange andre bli valgt, men ikke sitt eget navn.\n"
                    "Så løftet treneren blikket, og alt ble stille."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "landslagstreneren", "plass", "stille"],
            }],
        },

        # Side 5
        {
            "filename": "05(fotball-vm).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "«(Navn)!»\n"
                    "Lagkameratene jublet, og (Navn) fikk landslagsdrakten i hendene.\n"
                    "På brystet satt det norske flagget.\n"
                    "Nå var det ikke lenger bare trening. Han skulle spille for Norge."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "landslagsdrakten", "flagget", "Norge"],
            }],
        },

        # Side 6
        {
            "filename": "06(fotball-vm).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Flyet landet i vertslandet.\n"
                    "Gjennom vinduet så (Navn) enorme stadioner og flagg fra hele verden.\n"
                    "På hotellet fikk laget vite hvem de skulle møte først:\n"
                    "et av verdens beste lag. VM hadde begynt."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "vertslandet", "stadioner", "verden"],
            }],
        },

        # Side 7
        {
            "filename": "07(fotball-vm).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Den første kampen gikk ikke slik Norge håpet.\n"
                    "Motstanderne scoret. Så scoret de igjen.\n"
                    "(Navn) mistet ballen i et viktig angrep, og kampen endte med tap.\n"
                    "I garderoben sa nesten ingen noe."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "Norge", "ballen", "garderoben"],
            }],
        },

        # Side 8
        {
            "filename": "08(fotball-vm).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "«Dere er ikke her fordi alt alltid går perfekt,» sa treneren.\n"
                    "«Dere er her fordi dere reiser dere igjen.»\n"
                    "(Navn) tenkte på sitt aller første bomskudd hjemme på banen.\n"
                    "Så reiste han seg: «Da vinner vi den neste.»"
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "treneren", "bomskudd", "neste"],
            }],
        },

        # Side 9
        {
            "filename": "09(fotball-vm).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Den neste kampen ble vill. Norge lå under, og tiden rant ut.\n"
                    "(Navn) fikk ballen på kanten og driblet forbi den ene, så den andre.\n"
                    "Han kunne skutt selv, men foran mål sto en lagkamerat helt alene.\n"
                    "(Navn) sendte ballen inn. Mål! 1–1."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "vill", "driblet", "lagkamerat"],
            }],
        },

        # Side 10
        {
            "filename": "10(fotball-vm).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Det sto bare sekunder igjen da ballen havnet hos (Navn) igjen.\n"
                    "Tribunen reiste seg.\n"
                    "Han løp mot mål mens forsvarerne kom fra begge sider.\n"
                    "(Navn) så målet og trakk foten bakover."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "sekunder", "Tribunen", "målet"],
            }],
        },

        # Side 11
        {
            "filename": "11(fotball-vm).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Skuddet suste mot hjørnet. Keeperen strakte seg, men rakk den ikke.\n"
                    "MÅL! Lagkameratene stormet mot (Navn), og Norge var videre.\n"
                    "Så vant de den neste kampen. Og den neste.\n"
                    "Helt til bare fire lag var igjen i hele verden."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "Keeperen", "videre", "verden"],
            }],
        },

        # Side 12 - venstre kvadrat (comfy-headswap, ingen tekst)
        {
            "filename": "12(fotball-vm-left).png",
            "type": "inner",
            "square": True,
            "blocks": [],
        },

        # Side 12 - hoyre kvadrat (statisk bilde, baerer teksten)
        {
            "filename": "12(fotball-vm-right).png",
            "type": "inner",
            "square": True,
            "side": "right",
            "no_split": True,
            "box_frac": [0.07, 0.66, 0.93, 0.98],
            "blocks": [{
                "text": p(
                    "Semifinalen ble den tøffeste kampen (Navn) hadde spilt.\n"
                    "Det sto uavgjort helt mot slutten da motstanderne kom alene mot mål.\n"
                    "(Navn) spurtet tilbake og klarte akkurat å stoppe angrepet.\n"
                    "Sekunder senere kontret Norge, og lagkameraten scoret. Finale!"
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "Semifinalen", "spurtet", "Finale"],
            }],
        },

        # Side 13
        {
            "filename": "13(fotball-vm).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Finaledagen kom, og (Navn) sto i spillertunnelen.\n"
                    "Foran ham lå den største stadion han noen gang hadde sett.\n"
                    "Ved siden av banen glitret VM-pokalen under lysene.\n"
                    "Én kamp. Det var alt som gjensto. Så åpnet dørene seg."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "spillertunnelen", "stadion", "lysene"],
            }],
        },

        # Side 14
        {
            "filename": "14(fotball-vm).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Finalen sto 1–1 da Norge fikk frispark like utenfor sekstenmeteren.\n"
                    "(Navn) la ballen til rette, løp frem og skjøt. Rett i krysset!\n"
                    "Da dommeren blåste av, løftet lagkameratene (Navn) opp i konfettien.\n"
                    "Han hadde vært fotballstjerne. Nå var han verdensmester."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "frispark", "krysset", "verdensmester"],
            }],
        },

        # Bakside
        {
            "filename": "bakside(fotball-vm).png",
            "type": "cover",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Denne boken handler om å reise seg igjen. Om lagånd, om nerver før en stor kamp, og om å tro på seg selv mens hele verden ser på.\n"
                    "Etter finalen hjemme får (Navn) et brev han knapt tør å åpne: landslaget vil ha ham med til VM.\n"
                    "En varm og spennende fortelling om vennskap, mot og drømmer som blir større enn man tør å håpe på.\n"
                    "For den største forskjellen mellom en drøm og et eventyr er at noen tør å fortsette når det blir vanskelig."
                ),
                "font_size": 46,
                "color": "#FFFFFF",
                "highlights": [child_name, "lagånd", "landslaget", "vennskap", "mot", "eventyr"],
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
RYGGRAD_BOOK_SLUG = "fotball-vm"
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
#  1:1 KVADRATSIDE (ingen A5-splitt) - brukt for side 14 (left/right)
#  Kolonner skaleres x4/3 slik at teksten havner i samme skjermposisjon
#  som en vanlig venstre/hoyre-side (som ellers strekkes 1536->5250).
# ------------------------------------------------------------
SQUARE_DESIGN = 1024
SQ_LEFT_X1, SQ_LEFT_X2 = 187, 720
SQ_RIGHT_X1, SQ_RIGHT_X2 = 1328 - SQUARE_DESIGN, 1861 - SQUARE_DESIGN


def _draw_end_text(img, text, s):
    """Stor, sentrert avslutningstekst litt under midten (ingen pills)."""
    draw = ImageDraw.Draw(img)
    img_w, img_h = img.size
    font_size = max(24, int(48 * s))
    font = ImageFont.truetype(INNER_FONT, font_size)
    box_w = int(img_w * 0.84)
    bx1 = (img_w - box_w) // 2
    bx2 = bx1 + box_w
    by1 = int(img_h * 0.55)
    by2 = int(img_h * 0.95)
    line_spacing = max(6, int(font_size * 0.34))
    draw_text(
        draw=draw,
        text=text,
        box=(bx1, by1, bx2, by2),
        font=font,
        color="#FFFFFF",
        stroke_color=STROKE_COLOR,
        line_spacing=line_spacing,
        highlights=[],
        gradient=None,
        img=img,
        align="center",
        shadow=True,
        shadow_offset=max(2, int(font_size * 0.045)),
        shadow_blur=max(2, int(font_size * 0.06)),
        shadow_alpha=150,
    )


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

    if page.get("endtext") and page.get("text"):
        _draw_end_text(img, str(page["text"]), s)

    y = sq(MARGIN_Y + 150)
    y2_default = sq(SQUARE_DESIGN - 80)
    box_frac = page.get("box_frac")
    if box_frac:
        x1 = int(img_w * box_frac[0])
        y = int(img_h * box_frac[1])
        x2 = int(img_w * box_frac[2])
        y2_default = int(img_h * box_frac[3])

    for block in page.get("blocks", []):
        base_size = block.get("font_size", DEFAULT_FONT_SIZE)
        font_size = max(8, int(base_size * s))
        font = ImageFont.truetype(INNER_FONT, font_size)

        bx1 = x1 + (0 if box_frac else sq(block.get("x_offset", 0)))
        bx2 = x2 + (0 if box_frac else sq(block.get("width_offset", 0)))
        by1 = y + (0 if box_frac else sq(block.get("y_offset", 0)))
        by2 = y2_default
        box = (bx1, by1, bx2, by2)

        use_gradient = "color" not in block
        text_line_spacing = max(6, int(16 * s))
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

    out_name = os.path.splitext(os.path.basename(page["filename"]))[0] + ".png"
    out_path = os.path.join(out_dir, out_name)
    os.makedirs(out_dir, exist_ok=True)
    img.convert("RGB").save(out_path)
    print("Lagret (square):", out_path)
    return [out_path]


def render_page(page: Dict[str, Any], base_dir: str, out_dir: str) -> List[str]:

        # ------------------------ blank side ------------------------
    if page.get("type") == "blank":
        img = Image.new(
            "RGBA",
            (INNER_WIDTH, INNER_HEIGHT),
            (255, 255, 255, 255)
        )

        # (Valgfritt) Tegn tekst senere via blocks
        draw = ImageDraw.Draw(img)

        out_path = os.path.join(out_dir, "blank.png")
        os.makedirs(out_dir, exist_ok=True)
        img.save(out_path)

        print("Lagret blank side:", out_path)
        return [out_path]



    base_path = resolve_base_image_path(base_dir, page["filename"])

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
                draw_centered_title_cover(img, text, base_dir=base_dir)

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
            save_img = img.convert("RGB") if out_path.lower().endswith((".jpg", ".jpeg")) else img
            save_img.save(out_path)
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












FOTBALL_DREAMPAGE_FIRST = os.path.join(
    DP_ROOT, "books", "fotball-vm",
    "dreampage-first(fotball-vm).png"
)
if not os.path.exists(FOTBALL_DREAMPAGE_FIRST):
    # Boka har ingen egen intro-side enda - bruk bok 1 sin.
    FOTBALL_DREAMPAGE_FIRST = os.path.join(
        DP_ROOT, "books", "fotballstjernen",
        "dreampage-first(fotballstjernen).png"
    )
DREAMPAGE_FIRST_TAGLINE = "Printed with care\nfor quality"


def render_dreampage_first(child_name: str, out_dir: str) -> str:
    """
    Legger en personlig dedikasjon på den hvite øvre halvdelen av dreampage-first.png
    og lagrer resultatet til out_dir. Returnerer stien til den renderte filen.
    """
    src = _dp_first(FOTBALL_DREAMPAGE_FIRST)
    dst = os.path.join(out_dir, "dreampage-first-rendered.png")

    img = Image.open(src).convert("RGBA")
    draw = ImageDraw.Draw(img)
    w, h = img.size

    title_line = f"For {child_name}"
    body_lines = [
        "This book was made especially for you.",
        f"You are {child_name} — the hero of the story.",
        "",
        "It is your dreams, your courage",
        "and the goals that fill these pages.",
        "",
        "Always believe in yourself,",
        "just like you do in this story.",
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

    # --- Tagline (rendres av scriptet, over "© 2026 DreamPage") ---
    tag_lines = DREAMPAGE_FIRST_TAGLINE.splitlines()
    tag_font_size = int(h * 0.033)
    try:
        tag_font = ImageFont.truetype(COVER_FONT, tag_font_size)
    except Exception:
        tag_font = font_body
    tag_gap = int(tag_font_size * 0.30)
    tag_dims = [draw.textbbox((0, 0), tl, font=tag_font) for tl in tag_lines]
    tag_total = sum((b[3] - b[1]) for b in tag_dims) + tag_gap * (len(tag_lines) - 1)
    ty = int(h * 0.735) - tag_total // 2
    for tl, b in zip(tag_lines, tag_dims):
        lw = b[2] - b[0]
        lh = b[3] - b[1]
        draw.text(((w - lw) // 2, ty), tl, font=tag_font, fill=text_color)
        ty += lh + tag_gap

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

    # Skille cover fra innersider basert på filnavn
    inner_paths: List[str] = []
    cover_paths: List[str] = []

    for p in all_paths:
        name = os.path.basename(p).lower()
        if name == "ryggrad.png" or name.startswith("forside") or name.startswith("bakside"):
            cover_paths.append(p)
        else:
            inner_paths.append(p)

    cover_rendered = {os.path.basename(p).lower(): p for p in cover_paths}

    # Legg til dreampage-first.png først og blank-back.png bakerst (ingen Lastpage - det finnes ingen bok 3 i serien enda).
    # Disse er enkelt-sider (4096x4096) som ikke skal splittes – bare inkluderes direkte.
    dreampage_first = _dp_first(FOTBALL_DREAMPAGE_FIRST)
    # Ordrens egen blank-back.png (f.eks. "Fortsett eventyret"-siden med QR)
    # har forrang; den delte malen er fallback for boker uten oppsalg.
    blank_back = os.path.join(base_dir, "blank-back.png")
    if not os.path.exists(blank_back):
        blank_back = os.path.join(SCRIPT_DIR, "blank-back.png")
    else:
        print("[INNER PDF] Bruker siste innerside fra ordremappen:", blank_back)
    if os.path.exists(dreampage_first):
        rendered_first = render_dreampage_first(child_name, out_dir)
        inner_paths.insert(0, rendered_first)
    else:
        print("ADVARSEL: Fant ikke dreampage-first.png")
    if os.path.exists(blank_back):
        inner_paths.append(blank_back)
    else:
        raise FileNotFoundError("Fant ikke blank-back.png i script-mappen")

    # -------------------- PDF 1: INNERSIDER --------------------
    if inner_paths:
        inner_pdf_path = os.path.join(out_dir, f"{child_name}_innersider.pdf")
        inner_paths = log_inner_page_order(
            inner_paths,
            script_name=os.path.basename(__file__),
            expected_count=EXPECTED_INNER_PAGES,
        )

        PAGE_INCH = 8.5
        PAGE_SIZE = PAGE_INCH * inch

        c = canvas.Canvas(inner_pdf_path, pagesize=(PAGE_SIZE, PAGE_SIZE))

        tmp_dir = os.path.join(out_dir, "_pdf_tmp_inner")
        os.makedirs(tmp_dir, exist_ok=True)

        for i, path in enumerate(inner_paths):
            im = Image.open(path)

            if im.mode in ("RGBA", "P", "LA"):
                im = im.convert("RGB")

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

    # -------------------- PDF 2: COVER (robust) --------------------
    def find_key(prefix: str):
        for k in cover_rendered.keys():
            if k.startswith(prefix):
                return k
        return None

    back_k = find_key("bakside")
    spine_k = "ryggrad.png" if "ryggrad.png" in cover_rendered else None
    front_k = find_key("forside")

    missing = []
    if not back_k:
        missing.append("bakside*.png")
    if not spine_k:
        missing.append("ryggrad.png")
    if not front_k:
        missing.append("forside*.png")

    if missing:
        print("Cover PDF ble IKKE laget. Mangler:", ", ".join(missing))
    else:
        back_path = cover_rendered[back_k]
        spine_path = cover_rendered[spine_k]
        front_path = cover_rendered[front_k]

        back = Image.open(back_path).convert("RGB")
        spine = Image.open(spine_path).convert("RGB")
        front = Image.open(front_path).convert("RGB")

        total_w_px = in_to_px(LULU_COVER_W_IN)
        total_h_px = in_to_px(LULU_COVER_H_IN)

        wrap_px = in_to_px(LULU_WRAP_IN)
        trim_px = in_to_px(LULU_TRIM_IN)
        spine_px = in_to_px(LULU_SPINE_IN)

        back_box_w = wrap_px + trim_px
        front_box_w = trim_px + wrap_px

        back_f = cover_fit(back, back_box_w, total_h_px)
        front_f = cover_fit(front, front_box_w, total_h_px)
        spine_f = cover_fit(spine, spine_px, total_h_px)

        cover_img = Image.new("RGB", (total_w_px, total_h_px), (255, 255, 255))

        x = 0
        cover_img.paste(back_f, (x, 0))
        x += back_box_w
        cover_img.paste(spine_f, (x, 0))
        x += spine_px
        cover_img.paste(front_f, (x, 0))

        cover_tmp = os.path.join(out_dir, "_cover_composite.jpg")
        cover_img.save(cover_tmp, "JPEG", quality=95)

        cover_pdf_path = os.path.join(out_dir, f"{child_name}_cover.pdf")

        c = canvas.Canvas(
            cover_pdf_path,
            pagesize=(LULU_COVER_W_IN * inch, LULU_COVER_H_IN * inch),
        )
        c.drawImage(
            cover_tmp,
            0,
            0,
            width=LULU_COVER_W_IN * inch,
            height=LULU_COVER_H_IN * inch,
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

    # -------------------- CLEANUP (behold kun PDF-er) --------------------
    keep = {f"{child_name}_innersider.pdf", f"{child_name}_cover.pdf"}

    for fname in os.listdir(out_dir):
        path = os.path.join(out_dir, fname)

        if fname in keep:
            continue

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




# --- DreamPage translated text table (en-US) ---
_DREAMPAGE_TRANSLATIONS = {
  '{name} vinner\nFotball-VM': '{name} Wins the\nWorld Cup',
  'Noen dager etter den store finalen var {name} tilbake på treningsbanen.\nAlt så helt vanlig ut, helt til treneren ropte ham bort.\nI hånden holdt han en konvolutt med et lite norsk flagg på.\n{name} kjente hjertet begynne å hamre.': 'A few days after the big final, {name} was back at the training ground.\nEverything looked normal, until the coach called him over.\nIn his hand he held an envelope with a small Norwegian flag on it.\n{name} felt his heart start to pound.',
  'En landslagsspeider hadde sittet på tribunen under finalen.\nHan hadde sett at {name} kjempet videre da kampen ble vanskelig.\nNå ville de se ham igjen.\n{name} åpnet brevet: han var invitert til landslagssamling.': 'A national team scout had been sitting in the stands during the final.\nHe had seen {name} keep fighting when the game got hard.\nNow they wanted to see him again.\n{name} opened the letter: he was invited to the national team camp.',
  'På samlingen møtte {name} spillere han aldri hadde sett før.\nDe var raske. Veldig raske.\nAllerede i den første øvelsen mistet han ballen. Så én gang til.\nMen han husket hva treneren hadde lært ham, og jaget ballen igjen.': 'At the camp {name} met players he had never seen before.\nThey were fast. Very fast.\nIn the very first drill he lost the ball. Then once more.\nBut he remembered what his coach had taught him, and chased the ball again.',
  'På slutten av dagen leste landslagstreneren opp navnene.\nDet var bare én plass igjen på laget som skulle til VM.\n{name} hørte mange andre bli valgt, men ikke sitt eget navn.\nSå løftet treneren blikket, og alt ble stille.': 'At the end of the day the national coach read out the names.\nThere was only one place left on the team going to the World Cup.\n{name} heard many others being picked, but not his own name.\nThen the coach looked up, and everything went quiet.',
  '«{name}!»\nLagkameratene jublet, og {name} fikk landslagsdrakten i hendene.\nPå brystet satt det norske flagget.\nNå var det ikke lenger bare trening. Han skulle spille for Norge.': '"{name}!"\nHis teammates cheered, and {name} was handed the national jersey.\nOn the chest sat the Norwegian flag.\nThis was no longer just practice. He was going to play for Norway.',
  'Flyet landet i vertslandet.\nGjennom vinduet så {name} enorme stadioner og flagg fra hele verden.\nPå hotellet fikk laget vite hvem de skulle møte først:\net av verdens beste lag. VM hadde begynt.': 'The plane landed in the host country.\nThrough the window {name} saw huge stadiums and flags from all over the world.\nAt the hotel the team learned who they would face first:\none of the best teams in the world. The World Cup had begun.',
  'Den første kampen gikk ikke slik Norge håpet.\nMotstanderne scoret. Så scoret de igjen.\n{name} mistet ballen i et viktig angrep, og kampen endte med tap.\nI garderoben sa nesten ingen noe.': 'The first game did not go the way Norway had hoped.\nThe opponents scored. Then they scored again.\n{name} lost the ball in an important attack, and the game ended in defeat.\nIn the locker room almost nobody said a word.',
  '«Dere er ikke her fordi alt alltid går perfekt,» sa treneren.\n«Dere er her fordi dere reiser dere igjen.»\n{name} tenkte på sitt aller første bomskudd hjemme på banen.\nSå reiste han seg: «Da vinner vi den neste.»': '"You are not here because everything always goes perfectly," said the coach.\n"You are here because you get back up."\n{name} thought about his very first missed shot back home on the field.\nThen he stood up: "Then we win the next one."',
  'Den neste kampen ble vill. Norge lå under, og tiden rant ut.\n{name} fikk ballen på kanten og driblet forbi den ene, så den andre.\nHan kunne skutt selv, men foran mål sto en lagkamerat helt alene.\n{name} sendte ballen inn. Mål! 1–1.': 'The next game was wild. Norway were behind, and time was running out.\n{name} got the ball on the wing and dribbled past one, then another.\nHe could have shot himself, but a teammate stood all alone in front of goal.\n{name} passed it in. Goal! 1-1.',
  'Det sto bare sekunder igjen da ballen havnet hos {name} igjen.\nTribunen reiste seg.\nHan løp mot mål mens forsvarerne kom fra begge sider.\n{name} så målet og trakk foten bakover.': 'There were only seconds left when the ball found {name} again.\nThe whole stand rose to its feet.\nHe ran toward the goal while defenders closed in from both sides.\n{name} saw the goal and pulled his foot back.',
  'Skuddet suste mot hjørnet. Keeperen strakte seg, men rakk den ikke.\nMÅL! Lagkameratene stormet mot {name}, og Norge var videre.\nSå vant de den neste kampen. Og den neste.\nHelt til bare fire lag var igjen i hele verden.': 'The shot flew toward the corner. The keeper stretched, but could not reach it.\nGOAL! His teammates stormed toward {name}, and Norway were through.\nThen they won the next game. And the next.\nUntil only four teams were left in the whole world.',
  'Semifinalen ble den tøffeste kampen {name} hadde spilt.\nDet sto uavgjort helt mot slutten da motstanderne kom alene mot mål.\n{name} spurtet tilbake og klarte akkurat å stoppe angrepet.\nSekunder senere kontret Norge, og lagkameraten scoret. Finale!': 'The semifinal was the toughest game {name} had ever played.\nIt was tied right to the end when the opponents broke through alone.\n{name} sprinted back and just managed to stop the attack.\nSeconds later Norway countered, and a teammate scored. The final!',
  'Finaledagen kom, og {name} sto i spillertunnelen.\nForan ham lå den største stadion han noen gang hadde sett.\nVed siden av banen glitret VM-pokalen under lysene.\nÉn kamp. Det var alt som gjensto. Så åpnet dørene seg.': "Final day came, and {name} stood in the players' tunnel.\nIn front of him lay the biggest stadium he had ever seen.\nBeside the field the World Cup trophy glittered under the lights.\nOne game. That was all that was left. Then the doors opened.",
  'Finalen sto 1–1 da Norge fikk frispark like utenfor sekstenmeteren.\n{name} la ballen til rette, løp frem og skjøt. Rett i krysset!\nDa dommeren blåste av, løftet lagkameratene {name} opp i konfettien.\nHan hadde vært fotballstjerne. Nå var han verdensmester.': 'The final was 1-1 when Norway won a free kick just outside the box.\n{name} placed the ball, ran up and struck it. Right in the top corner!\nWhen the referee blew the whistle, his teammates lifted {name} into the confetti.\nHe had become a soccer star. Now he was a world champion.',
  'Denne boken handler om å reise seg igjen. Om lagånd, om nerver før en stor kamp, og om å tro på seg selv mens hele verden ser på.\nEtter finalen hjemme får {name} et brev han knapt tør å åpne: landslaget vil ha ham med til VM.\nEn varm og spennende fortelling om vennskap, mot og drømmer som blir større enn man tør å håpe på.\nFor den største forskjellen mellom en drøm og et eventyr er at noen tør å fortsette når det blir vanskelig.': 'This book is about getting back up. About team spirit, about nerves before a big game, and about believing in yourself while the whole world is watching.\nAfter the final back home, {name} receives a letter he hardly dares to open: the national team wants him at the World Cup.\nA warm and exciting story about friendship, courage and dreams that grow bigger than you dare to hope for.\nBecause the biggest difference between a dream and an adventure is that someone dares to keep going when it gets hard.',
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
        shadow_alpha = 175
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
    if number == 13:
        # VM-pokalen staar midt paa venstresida (y 0.24-0.62). Toppblokken
        # loftes opp i publikum over pokalen, bunnblokken ned paa sokkelen,
        # slik at selve pokalen blir staaende fri.
        top_y = -155
        bottom_y = 445
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
    if page.get("no_split") or page.get("square"):
        _dp_mark_backdrop(block, filename, child_name)
        return

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

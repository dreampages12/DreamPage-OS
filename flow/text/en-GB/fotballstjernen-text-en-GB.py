


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

# Lastpage(fotball).png ligger etter blank-back, så total innersider = 31.
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


def resolve_front_cover_logo(base_dir: str | None = None) -> str | None:
    """Resolve the cover logo from C:/DreamPage-OS/assets/logo/<locale>."""
    candidates = [
        os.path.join(LOGO_DIR, "fotballstjerne-logo.webp"),
        os.path.join(LOGO_DIR, "fotballstjerne-logo.png"),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return None

def draw_centered_title_cover(img, text, base_dir: str | None = None):
    """
    Forside-tittel:
    - Linje 1: tekst med Trebuchet MS Bold
    - Linje 2: logo-bilde fra script/logo/<locale>
    Parametre matcher preview-oppsettet som brukes som ground truth.
    """
    draw = ImageDraw.Draw(img)
    w, h = img.size
    base = min(w, h)

    line1 = text.split("\n")[0] if text else ""

    font_small = ImageFont.truetype(COVER_TITLE_FONT, 240)

    GOLD         = ((173, 216, 230), (255, 255, 255))
    SHADOW_COL   = (15, 35, 65)
    TOP_MARGIN   = 0.04
    LINE_SPACING = 0.045
    LOGO_SCALE   = 0.66
    LOGO_X_OFFSET = 14

    size_large    = int(base * 0.10)
    shadow_offset = max(3, int(size_large * 0.04))

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

    line1_bbox = draw.textbbox((0, 0), line1, font=font_small)
    w1 = line1_bbox[2] - line1_bbox[0]
    h1 = line1_bbox[3] - line1_bbox[1]
    top_y   = int(h * TOP_MARGIN)
    spacing = int(h * LINE_SPACING)

    x1_pos = (w - w1) // 2
    y1_pos = top_y
    descender_cut = int(h1 * 0.15)
    y2_pos = y1_pos + h1 - descender_cut + spacing

    # --- Linje 1: glød ---
    glow_radius = max(18, int(font_small.size * 0.35))
    gm = _make_text_mask(img.size, x1_pos, y1_pos, line1, font_small)
    gm = gm.filter(ImageFilter.GaussianBlur(glow_radius))
    gm = gm.point(lambda p: int(p * 0.55))
    glow_layer = Image.merge("RGBA", (
        Image.new("L", img.size, 255),
        Image.new("L", img.size, 248),
        Image.new("L", img.size, 215),
        gm,
    ))
    img.alpha_composite(glow_layer)

    # --- Linje 1: shadow ---
    sm = _make_text_mask(img.size, x1_pos + shadow_offset, y1_pos + shadow_offset, line1, font_small)
    sm = sm.filter(ImageFilter.GaussianBlur(max(1, shadow_offset // 2)))
    img.paste((*SHADOW_COL, 255), (0, 0), sm)

    # --- Linje 1: gradient tekst ---
    tm   = _make_text_mask(img.size, x1_pos, y1_pos, line1, font_small)
    bbox = draw.textbbox((x1_pos, y1_pos), line1, font=font_small)
    _paste_gradient(img, tm, bbox, GOLD[0], GOLD[1])

    # --- Linje 2: logo-bilde ---
    logo_path = resolve_front_cover_logo(base_dir)
    if not logo_path:
        print("ADVARSEL: Fant ikke fotball-logo:", logo_path)
        return

    logo = Image.open(logo_path).convert("RGBA")
    logo = remove_white_background(logo, thresh=25, defringe_thresh=0)
    logo = crop_logo_to_visible_alpha(logo, alpha_threshold=8)

    target_w = int(w * LOGO_SCALE)
    target_h = int(logo.height * (target_w / logo.width))
    logo = logo.resize((target_w, target_h), Image.LANCZOS)
    lx = ((w - target_w) // 2) + LOGO_X_OFFSET
    lx = max(0, min(w - target_w, lx))

    shadow_blur  = max(8, int(target_h * 0.20))
    shadow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    logo_alpha   = logo.split()[3]
    shadow_img   = Image.new("RGBA", (target_w, target_h), (*SHADOW_COL, 180))
    shadow_img.putalpha(logo_alpha)
    shadow_layer.paste(shadow_img, (lx + shadow_offset, y2_pos + shadow_offset))
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(shadow_blur))
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
            "filename": "forside(fotballstjernen).png",
            "type": "cover",
            "text": p("[NAVN] blir"),
        },
        {
            "filename": "ryggrad.png",
            "type": "cover",
        },

        # Side 1 – child left-center, goal open right → text RIGHT, white
        {
            "filename": "01(fotballstjernen).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "(Navn) sto på banen med ballen ved foten og kjente gresset kile under skoene.\n"
                    "Han hadde drømt om å bli en ekte fotballstjerne så lenge han kunne huske.\n\n"
                    "I dag virket målet litt nærmere enn før. Han trakk pusten dypt og hvisket: «Jeg skal prøve så godt jeg kan.»"
                ),
                "font_size": 29,
                "color": "#000000",
                "highlights": [child_name, "fotballstjerne"],
            }],
        },

        # Side 2 – child fills right half, bright sunbeams left → text LEFT, black
        {
            "filename": "02(fotballstjernen).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "(Navn) så opp mot lyset som skinte over banen.\n"
                    "Det glitret i gresset, og hele stedet føltes som starten på noe viktig.\n\n"
                    "Han tenkte på alle gangene han hadde sparket ball i hagen, bommet, ledd og prøvd igjen. Kanskje var det nettopp slik store drømmer begynte."
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name],
            }],
        },

        # Side 3 – child left, open field right → text RIGHT, black
        {
            "filename": "03(fotballstjernen).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "(Navn) begynte å øve med ballen, først sakte og så litt raskere.\n"
                    "Han prøvde å drible slik de store spillerne gjorde på TV, men ballen trillet ikke alltid dit han ville.\n\n"
                    "Han bet tennene forsiktig sammen. «Jeg må bare lære litt mer,» tenkte han. «Ingen blir god uten å øve.»"
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name],
            }],
        },

        # Side 4 left – static missed shot without a visible face
        {
            "filename": "04-left(fotballstjernen).png",
            "type": "inner",
            "side": "left",
            "square": True,
            "blocks": [{
                "text": p(
                    "Så kom et skudd som gikk helt feil vei.\n"
                    "(Navn) satte seg ned i gresset og kjente skuffelsen prikke bak øynene.\n\n"
                    "Ballen lå stille ved siden av ham, som om den også ventet. «Kanskje jeg ikke er god nok,» tenkte han, selv om han ønsket å være modig."
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name],
            }],
        },

        # Side 4 right – personalized head-swapped reaction image
        {
            "filename": "04-right(fotballstjernen).png",
            "type": "inner",
            "side": "right",
            "square": True,
            "blocks": [],
        },

        # Side 5 – child left, coach right, open background right → text RIGHT, white
        {
            "filename": "05(fotballstjernen).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Treneren kom bort og satte seg rolig ved siden av (Navn).\n"
                    "«Vet du hva de beste spillerne gjør når de bommer?» spurte han. «De prøver én gang til.»\n\n"
                    "(Navn) så opp. Treneren smilte varmt. «Jeg tror på deg.» Da kjente (Navn) motet vende tilbake, lite først, men sterkere for hvert sekund."
                ),
                "font_size": 28,
                "color": "#FFFFFF",
                "highlights": [child_name, "treneren"],
            }],
        },

        # Side 6 – child left-center running, open right → text RIGHT, black
        {
            "filename": "06(fotballstjernen).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "(Navn) reiste seg, tørket gresset av hendene og prøvde igjen.\n"
                    "Denne gangen holdt han ballen nær foten og lyttet til rytmen i stegene sine.\n\n"
                    "Han bommet fortsatt litt, men han stoppet ikke. For hver berøring ble han roligere, og inni seg tenkte han: «Jeg gir meg ikke.»"
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name],
            }],
        },

        # Side 7 – child center dribbling, open background right → text RIGHT, white
        {
            "filename": "07(fotballstjernen).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Etter hvert begynte føttene å forstå det hjertet allerede ville.\n"
                    "(Navn) vendte, driblet og fant små åpninger mellom kjeglene på banen.\n\n"
                    "Målet virket ikke så langt unna lenger. Han smilte for seg selv, for nå merket han det tydelig: øving gjorde ham bedre."
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name],
            }],
        },

        # Side 8 – child right in dark locker room, dark wall left → text LEFT, white
        {
            "filename": "08(fotballstjernen).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Senere satt (Navn) stille i garderoben mens de andre snakket lavt rundt ham.\n"
                    "Den store kampen nærmet seg, og treneren skulle velge laget.\n\n"
                    "Hjertet hans dunket så fort at han nesten kunne høre det i rommet. Han håpet, men turte nesten ikke håpe for mye."
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name],
            }],
        },

        # Side 9 – child left in locker room, dark background right → text RIGHT, white
        {
            "filename": "09(fotballstjernen).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "(Navn) lyttet nøye da treneren begynte å lese opp navnene.\n"
                    "Ett navn kom, så et til, og så enda et.\n\n"
                    "Han knyttet hendene rundt kanten av benken. Da treneren tok en liten pause, holdt (Navn) pusten og ventet på ordene som kunne forandre hele dagen."
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name],
            }],
        },

        # Side 10 – child left, dark locker room right → text RIGHT, white
        {
            "filename": "10(fotballstjernen).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Plutselig hørte han navnet sitt.\n"
                    "«(Navn), du er med i finalen,» sa treneren tydelig.\n\n"
                    "Først satt (Navn) helt stille. Så kjente han smilet vokse, større og større, helt til han nesten ikke klarte å sitte i ro."
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name, "finalen"],
            }],
        },

        # Side 11 – child in tunnel walking toward stadium, dark tunnel wall left → text LEFT, white
        {
            "filename": "11-left(fotballstjernen).png",
            "type": "inner",
            "side": "left",
            "square": True,
            "blocks": [{
                "text": p(
                    "(Navn) sto i tunnelen med laget rundt seg og kjente hjertet banke hardt.\n"
                    "Foran ham lyste stadion som en egen liten sol i natten.\n\n"
                    "Han tenkte på alle skuddene, alle bommene og alle gangene han hadde reist seg igjen. Så tok han et skritt frem. Det var hans tur nå."
                ),
                "font_size": 28,
                "color": "#FFFFFF",
                "highlights": [child_name, "drømt", "lyset"],
            }],
        },

        # Side 12 – child center on stadium pitch, dark crowd left → text LEFT, white
        {
            "filename": "11-right(fotballstjernen).png",
            "type": "inner",
            "side": "right",
            "square": True,
            "blocks": [],
        },

        {
            "filename": "12(fotballstjernen).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "(Navn) gikk ut på den store stadion, og lyden fra tribunen skylte mot ham som bølger.\n"
                    "Lysene skinte så sterkt at gresset glitret under skoene hans.\n\n"
                    "Han tok et dypt pust og kjente nervene bli til energi. Dette var øyeblikket han hadde drømt om."
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name, "stadion"],
            }],
        },

        # Side 13 – child center-left dribbling in stadium, dark crowd right → text RIGHT, white
        {
            "filename": "13(fotballstjernen).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Kampen startet, og plutselig kom ballen rullende mot (Navn).\n"
                    "Han tok imot den, løftet blikket og så en liten åpning foran seg.\n\n"
                    "Publikum jublet, men han hørte mest sin egen pust. Beina husket treningen, og (Navn) driblet framover mot målet."
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name],
            }],
        },

        # Side 14 – child center celebrating arms wide, body right-of-center → text LEFT, white
        {
            "filename": "14-left(fotballstjernen).webp",
            "type": "inner",
            "side": "left",
            "square": True,
            "blocks": [{
                "text": p(
                    "(Navn) trakk foten tilbake og skjøt med alt motet han hadde samlet.\n"
                    "Ballen suste gjennom luften, traff nettet og ble liggende der som et lite mirakel.\n\n"
                    "Hele stadion jublet. (Navn) løftet armene og lo, for nå visste han det: en ekte stjerne gir aldri opp."
                ),
                "font_size": 28,
                "color": "#FFFFFF",
                "highlights": [child_name, "finalen", "scoret"],
            }],
        },

        # Bakside
        {
            "filename": "14-right(fotballstjernen).png",
            "type": "inner",
            "side": "right",
            "square": True,
            "blocks": [],
        },

        {
            "filename": "bakside(fotballstjernen).png",
            "type": "cover",
            "side": "left",
            "blocks": [{
                "text": p(
                    "En liten spiller. En stor drøm.\n\n"
                    "Når (Navn) får sjansen til å spille sin største kamp noensinne, begynner et spennende eventyr fylt med mot, håp og fotballglede.\n\n"
                    "Fra trening og nervøse øyeblikk i garderoben til den store finalen, får barnet oppleve hvordan det føles å tro på seg selv — og skinne på banen.\n\n"
                    "En personlig historie om drømmer, mestring og et mål barnet aldri vil glemme."
                ),
                "font_size": 40,
                "color": "#FFFFFF",
                "highlights": [child_name, "fotballglede", "finalen", "drømmer", "mestring"],
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
RYGGRAD_BOOK_SLUG = "fotballstjernen"
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
SQ_RIGHT_X1, SQ_RIGHT_X2 = 1328, 1861


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
    for block in page.get("blocks", []):
        base_size = block.get("font_size", DEFAULT_FONT_SIZE)
        font_size = max(8, int(base_size * s))
        font = ImageFont.truetype(INNER_FONT, font_size)

        bx1 = x1 + sq(block.get("x_offset", 0))
        bx2 = x2 + sq(block.get("width_offset", 0))
        by1 = y + sq(block.get("y_offset", 0))
        by2 = sq(SQUARE_DESIGN - 80)
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
    DP_ROOT, "books", "fotballstjernen", "dreampage-first(fotballstjernen).png"
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

    # Legg til dreampage-first.png først, blank-back.png deretter, og per-bok Lastpage(fotball).png aller sist.
    # Disse er enkelt-sider (4096x4096) som ikke skal splittes – bare inkluderes direkte.
    dreampage_first = _dp_first(FOTBALL_DREAMPAGE_FIRST)
    # Ordrens egen blank-back.png (f.eks. "Fortsett eventyret"-siden med QR)
    # har forrang; den delte malen er fallback for boker uten oppsalg.
    blank_back = os.path.join(base_dir, "blank-back.png")
    if not os.path.exists(blank_back):
        blank_back = os.path.join(SCRIPT_DIR, "blank-back.png")
    else:
        print("[INNER PDF] Bruker siste innerside fra ordremappen:", blank_back)
    last_page = resolve_lastpage_path("Lastpage(fotball).png")
    if os.path.exists(dreampage_first):
        rendered_first = render_dreampage_first(child_name, out_dir)
        inner_paths.insert(0, rendered_first)
    else:
        print("ADVARSEL: Fant ikke dreampage-first.png")
    # Siste historieside er ordrens blank-back.png: "Fortsett eventyret"-siden
    # med QR fra build_last_page.py. Foer 18.09.2026 rendret ComfyUI ogsaa en
    # side 15 (gutten med pokalen), som denne siden saa ERSTATTET - paa hver
    # ordre med oppsalg, altsaa alle. Side 15 er fjernet fra boka: GPU-tiden
    # gikk til en side som aldri ble trykt.
    #
    # prepare_order kopierer ALLTID den delte blank-back.png inn i ordren, saa
    # bare eksistens er ikke nok: bare en fil som skiller seg fra malen er en
    # ekte fortsett-eventyret-side. Mangler den, brukes malen - som i de andre
    # boekene - men det sies fra: alle nye ordre skal ha en fortsett-side.
    order_last_page = os.path.join(base_dir, "blank-back.png")
    shared_blank_back = os.path.join(SCRIPT_DIR, "blank-back.png")
    is_continue_page = os.path.exists(order_last_page) and not (
        os.path.exists(shared_blank_back)
        and filecmp.cmp(order_last_page, shared_blank_back, shallow=False)
    )
    if is_continue_page:
        inner_paths.append(order_last_page)
        print("[INNER PDF] Fortsett-eventyret-siden:", order_last_page)
    else:
        inner_paths.append(blank_back)
        print("ADVARSEL: ordren har ingen fortsett-eventyret-side - bruker den "
              "delte blank-back-malen:", blank_back)
    if last_page:
        inner_paths.append(last_page)
    else:
        print(f"ADVARSEL: Fant ikke Lastpage(fotball).png i {LASTPAGE_DIR} - hopper over")

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




# --- DreamPage translated text table (en-GB) ---
_DREAMPAGE_TRANSLATIONS = {
  "{name} blir": "{name} Becomes\na Football Star",
  "{name} sto på banen med ballen ved foten og kjente gresset kile under skoene.\nHan hadde drømt om å bli en ekte fotballstjerne så lenge han kunne huske.\n\nI dag virket målet litt nærmere enn før. Han trakk pusten dypt og hvisket: «Jeg skal prøve så godt jeg kan.»": "{name} stood on the pitch with the ball at his feet and felt the grass tickle under his shoes.\nHe had dreamed of becoming a real football star for as long as he could remember.\n\nToday the goal seemed a little closer than before. He took a deep breath and whispered, \"I'll try my best.\"",
  "{name} så opp mot lyset som skinte over banen.\nDet glitret i gresset, og hele stedet føltes som starten på noe viktig.\n\nHan tenkte på alle gangene han hadde sparket ball i hagen, bommet, ledd og prøvd igjen. Kanskje var det nettopp slik store drømmer begynte.": "{name} looked up at the light shining across the pitch.\nThe grass sparkled, and the whole place felt like the start of something important.\n\nHe thought of all the times he had kicked a ball in the garden, missed, laughed and tried again. Perhaps that was precisely how big dreams began.",
  "{name} begynte å øve med ballen, først sakte og så litt raskere.\nHan prøvde å drible slik de store spillerne gjorde på TV, men ballen trillet ikke alltid dit han ville.\n\nHan bet tennene forsiktig sammen. «Jeg må bare lære litt mer,» tenkte han. «Ingen blir god uten å øve.»": "{name} started practicing with the ball, slowly at first and then a little faster.\nHe tried to dribble like the great players did on TV, but the ball didn't always roll where he wanted.\n\nHe gritted his teeth carefully. \"I just have to learn a little more,\" he thought. \"Nobody gets good without practice.\"",
  "Så kom et skudd som gikk helt feil vei.\n{name} satte seg ned i gresset og kjente skuffelsen prikke bak øynene.\n\nBallen lå stille ved siden av ham, som om den også ventet. «Kanskje jeg ikke er god nok,» tenkte han, selv om han ønsket å være modig.": "Then came a shot that went completely the wrong way.\n{name} sat down in the grass and felt disappointment sting behind his eyes.\n\nThe ball lay still beside him, as if it too was waiting. \"Maybe I'm not good enough,\" he thought, though he wanted to be brave.",
  "Treneren kom bort og satte seg rolig ved siden av {name}.\n«Vet du hva de beste spillerne gjør når de bommer?» spurte han. «De prøver én gang til.»\n\n{name} så opp. Treneren smilte varmt. «Jeg tror på deg.» Da kjente {name} motet vende tilbake, lite først, men sterkere for hvert sekund.": "The trainer came over and calmly sat down next to the {name}.\n\"Do you know what the best players do when they miss?\" he asked. \"They try one more time.\"\n\n{name} looked up. The trainer smiled warmly. \"I believe in you.\" Then {name} felt his courage return, little at first, but stronger every second.",
  "{name} reiste seg, tørket gresset av hendene og prøvde igjen.\nDenne gangen holdt han ballen nær foten og lyttet til rytmen i stegene sine.\n\nHan bommet fortsatt litt, men han stoppet ikke. For hver berøring ble han roligere, og inni seg tenkte han: «Jeg gir meg ikke.»": "{name} stood up, wiped the grass off his hands and tried again.\nThis time he kept the ball close to his foot and listened to the rhythm of his steps.\n\nHe still missed a bit, but he didn't stop. With each touch he calmed down, and inside he thought, \"I won't give up.\"",
  "Etter hvert begynte føttene å forstå det hjertet allerede ville.\n{name} vendte, driblet og fant små åpninger mellom kjeglene på banen.\n\nMålet virket ikke så langt unna lenger. Han smilte for seg selv, for nå merket han det tydelig: øving gjorde ham bedre.": "Eventually the feet began to understand what the heart already wanted.\n{name} turned, dribbled and found small openings between the cones on the court.\n\nThe goal didn't seem so far away anymore. He smiled to himself, because now he could clearly see it: practice made him better.",
  "Senere satt {name} stille i garderoben mens de andre snakket lavt rundt ham.\nDen store kampen nærmet seg, og treneren skulle velge laget.\n\nHjertet hans dunket så fort at han nesten kunne høre det i rommet. Han håpet, men turte nesten ikke håpe for mye.": "Later, {name} sat quietly in the dressing room while the others talked softly around him.\nThe big game was approaching, and the coach was going to choose the team.\n\nHis heart was beating so fast he could almost hear it in the room. He hoped, but hardly dared to hope too much.",
  "{name} lyttet nøye da treneren begynte å lese opp navnene.\nEtt navn kom, så et til, og så enda et.\n\nHan knyttet hendene rundt kanten av benken. Da treneren tok en liten pause, holdt {name} pusten og ventet på ordene som kunne forandre hele dagen.": "{name} listened carefully as the trainer began to read out the names.\nOne name came, then another, and then another.\n\nHe clasped his hands around the edge of the bench. When the trainer took a short break, {name} held his breath and waited for the words that could change his entire day.",
  "Plutselig hørte han navnet sitt.\n«{name}, du er med i finalen,» sa treneren tydelig.\n\nFørst satt {name} helt stille. Så kjente han smilet vokse, større og større, helt til han nesten ikke klarte å sitte i ro.": "Suddenly he heard his name.\n\"{name}, you're in the finals,\" the trainer said plainly.\n\nAt first the {name} sat completely still. Then he felt his smile grow, bigger and bigger, until he could hardly sit still.",
  "{name} sto i tunnelen med laget rundt seg og kjente hjertet banke hardt.\nForan ham lyste stadion som en egen liten sol i natten.\n\nHan tenkte på alle skuddene, alle bommene og alle gangene han hadde reist seg igjen. Så tok han et skritt frem. Det var hans tur nå.": "{name} stood in the tunnel with the team around him and felt his heart beating hard.\nIn front of him, the stadium shone like its own little sun in the night.\n\nHe thought about all the shots, all the misses and all the times he had gotten back up. Then he took a step forward. It was his turn now.",
  "{name} gikk ut på den store stadion, og lyden fra tribunen skylte mot ham som bølger.\nLysene skinte så sterkt at gresset glitret under skoene hans.\n\nHan tok et dypt pust og kjente nervene bli til energi. Dette var øyeblikket han hadde drømt om.": "{name} walked out into the large stadium, and the sound from the stands washed over him like waves.\nThe lights shone so brightly that the grass glistened under his shoes.\n\nHe took a deep breath and felt his nerves turn into energy. This was the moment he had dreamed of.",
  "Kampen startet, og plutselig kom ballen rullende mot {name}.\nHan tok imot den, løftet blikket og så en liten åpning foran seg.\n\nPublikum jublet, men han hørte mest sin egen pust. Beina husket treningen, og {name} driblet framover mot målet.": "The match started, and suddenly the ball came rolling towards the {name}.\nHe accepted it, looked up and saw a small opening in front of him.\n\nThe crowd cheered, but he mostly heard his own breathing. The legs remembered the training, and {name} dribbled forward towards the goal.",
  "{name} trakk foten tilbake og skjøt med alt motet han hadde samlet.\nBallen suste gjennom luften, traff nettet og ble liggende der som et lite mirakel.\n\nHele stadion jublet. {name} løftet armene og lo, for nå visste han det: en ekte stjerne gir aldri opp.": "{name} pulled his foot back and shot with all the courage he had mustered.\nThe ball whizzed through the air, hit the net and stayed there like a small miracle.\n\nThe whole stadium cheered. {name} raised his arms and laughed, because now he knew: a true star never gives up.",
  "En liten spiller. En stor drøm.\n\nNår {name} får sjansen til å spille sin største kamp noensinne, begynner et spennende eventyr fylt med mot, håp og fotballglede.\n\nFra trening og nervøse øyeblikk i garderoben til den store finalen, får barnet oppleve hvordan det føles å tro på seg selv — og skinne på banen.\n\nEn personlig historie om drømmer, mestring og et mål barnet aldri vil glemme.": "A small player. A big dream.\n\nWhen {name} gets the chance to play his biggest match ever, an exciting adventure begins filled with courage, hope and the joy of football.\n\nFrom training and nervous moments in the dressing room to the big final, the child gets to experience what it feels like to believe in himself - and shine on the pitch.\n\nA personal story about dreams, coping and a goal the child will never forget."
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

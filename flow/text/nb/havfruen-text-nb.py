


from reportlab.pdfgen import canvas
from reportlab.lib.units import inch

import shutil

import os
import re
import filecmp
import argparse
from typing import List, Dict, Any
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from gelato_cover import build_gelato_cover_pdf
from dream_pdf_guard import (
    log_inner_page_order,
    validate_inner_pdf_page_count,
)

# Havfruen-specific count: 1 opening (dreampage-first-rendered) + 28 story spread
# halves (14 spreads * 2) + blank-back + lastpage = 31. Differs from the
# 30-page default baked into dream_pdf_guard.
EXPECTED_HAVFRUEN_INNER_PAGES = 31

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT_LOCALES = {"nb", "nn", "en-US", "en-GB"}
SCRIPT_LOCALE = os.path.basename(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR) in SCRIPT_LOCALES else "nb"
SCRIPT_ROOT_DIR = os.path.dirname(SCRIPT_DIR) if SCRIPT_LOCALE in SCRIPT_LOCALES else SCRIPT_DIR
LOGO_DIR = os.path.join(SCRIPT_ROOT_DIR, "logo", SCRIPT_LOCALE)
LASTPAGE_DIR = os.path.join(SCRIPT_ROOT_DIR, "lastpages", SCRIPT_LOCALE)


# ------------------------------------------------------------
#  SISTE INNERSIDE - bokas egen "Dette eventyer er over"-side
# ------------------------------------------------------------
# Erstatter den delte blank-back.png, men viker ALLTID for ordrens egen
# "Fortsett eventyret"-side (QR-oppsalget). Tom streng = ingen egen side for
# dette spraket -> delt mal, som for.
_BB_LOCALES = {"nb", "nn", "en-US", "en-GB", "sv"}
_BB_LOCALE = os.path.basename(SCRIPT_DIR)
if _BB_LOCALE not in _BB_LOCALES:
    _BB_LOCALE = "nb"
_BB_NAME = {'nb': 'blank-back(havfruen).png'}.get(_BB_LOCALE, "")
HAVFRUEN_BLANK_BACK = os.path.join(
    os.path.dirname(globals().get("SCRIPT_ROOT_DIR", os.path.dirname(SCRIPT_DIR))),
    "books", 'havfruen', _BB_NAME,
) if _BB_NAME else ""


def _is_shared_blank_back(path):
    """True hvis fila er en av de delte malene - altsa IKKE ordrens egen side.

    prepare_order kopierer alltid en mal inn i ordren, saa vi maa sammenligne
    innhold. Begge malene sjekkes: script/blank-back.png og
    script/<locale>/blank-back.png er ulike filer for nn/en/sv.
    """
    root = globals().get("SCRIPT_ROOT_DIR", os.path.dirname(SCRIPT_DIR))
    for tmpl in (os.path.join(SCRIPT_DIR, "blank-back.png"),
                 os.path.join(root, "blank-back.png")):
        if os.path.exists(tmpl) and filecmp.cmp(path, tmpl, shallow=False):
            return True
    return False


def resolve_book_blank_back(filename, base_dir):
    """Ordrens egen side > bokas egen side > None (= kalleren bruker malen)."""
    if os.path.basename(filename).lower() != "blank-back.png":
        return None
    order_page = os.path.join(base_dir, filename)
    if os.path.exists(order_page) and not _is_shared_blank_back(order_page):
        print("[INNER PDF] Fortsett-eventyret-siden erstatter siste side:", order_page)
        return order_page
    if HAVFRUEN_BLANK_BACK and os.path.exists(HAVFRUEN_BLANK_BACK):
        return HAVFRUEN_BLANK_BACK
    return None


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

    book_page = resolve_book_blank_back(filename, base_dir)
    if book_page:
        return book_page

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

HAVFRUEN_DREAMPAGE_FIRST = os.path.join(
    os.path.dirname(SCRIPT_ROOT_DIR), "books", "havfruen", "dreampage-first-havfruen.png"
)
DREAMPAGE_FIRST_TAGLINE = "Trykket med omtanke for\nkvalitet"
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
        "colors": ((30, 60, 120), (90, 110, 160)),
        "shadow": (5, 8, 18),
    }
}

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
        os.path.join(LOGO_DIR, "havfruen-logo.png"),
        os.path.join(LOGO_DIR, "havfruen-logo.webp"),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return None

def draw_centered_title_cover(img, text, base_dir: str | None = None):
    """
    Forside-tittel:
    - Linje 1: tekst (navn) med Trebuchet MS Bold (samme stil som fotballstjernen)
    - Linje 2: havfruen-logo.png fra script/logo/<locale> (mindre enn linje 1-bredden)
    """
    draw = ImageDraw.Draw(img)
    w, h = img.size
    base = min(w, h)

    line1 = text.split("\n")[0] if text else ""

    # Skaler font med canvas-størrelse (mindre enn fotballstjernen)
    font_size_line1 = max(50, int(base * 0.07))
    font_small = ImageFont.truetype(COVER_TITLE_FONT, font_size_line1)

    # Hvit linje 1 med subtil glød + shadow (samme oppskrift som fotballstjernen)
    GOLD         = ((255, 255, 255), (255, 255, 255))
    SHADOW_COL   = (15, 35, 65)
    TOP_MARGIN   = 0.04
    LINE_SPACING = 0.060          # mer luft mellom linje 1 og logo
    LOGO_SCALE   = 0.50
    LOGO_X_OFFSET = 0

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

    # --- Linje 2: havfruen-logo ---
    logo_path = resolve_front_cover_logo(base_dir)
    if not logo_path:
        print("ADVARSEL: Fant ikke havfruen-logo")
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
    mask = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(mask)
    d.text((x, y), text, font=font, fill=255)

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
    Deler et oppslag i to kvadrater (venstre og høyre).
    """
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
    Finn eksakt fil hvis den finnes, ellers prøv samme stem med annen filendelse,
    eller varianter med " (1)"-suffiks.
    """
    exact = os.path.join(base_dir, filename)
    if os.path.exists(exact):
        return exact

    stem, ext = os.path.splitext(filename)
    try:
        for name in os.listdir(base_dir):
            n_stem, n_ext = os.path.splitext(name)
            if n_stem == stem:
                return os.path.join(base_dir, name)
            # tillat " (1)"-varianter
            if n_stem.startswith(stem + " ") and n_stem.replace(stem, "", 1).strip().startswith("("):
                return os.path.join(base_dir, name)
    except FileNotFoundError:
        pass

    return exact


# ------------------------------------------------------------
#  build_pages – Havfruen historie (14 sider)
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
            "filename": "forside(havfrue).png",
            "type": "cover",
            "text": p("[NAVN] blir"),
        },
        {
            "filename": "ryggrad.png",
            "type": "cover",
        },

        # Side 1 – det mystiske skjellet → tekst VENSTRE
        {
            "filename": "01(havfrue).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "En varm sommerdag lekte (Navn) ved stranden.\n"
                    "Hun hoppet mellom steinene og lette etter fine skjell i sanden.\n"
                    "\n"
                    "Plutselig glitret noe mellom to våte steiner. Det var et skjell som skinte i blått og lilla.\n"
                    "\n"
                    "(Navn) hadde aldri sett noe lignende."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "skjell", "glitret"],
                "x_offset": 0,
                "y_offset": -10,
            }],
        },

        # Side 2 – stemmen fra havet → tekst HØYRE
        {
            "filename": "02(havfrue).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "(Navn) løftet skjellet opp til øret.\n"
                    "Men i stedet for bølgesus hørte hun en svak stemme.\n"
                    "\n"
                    "«Hallo? Kan du høre meg?»\n"
                    "\n"
                    "Ute mellom bølgene dukket et ansikt opp. Det var en ekte havfrue, og hun vinket (Navn) nærmere."
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name, "stemme", "havfrue"],
                "x_offset": 10,
                "y_offset": -10,
                "width_offset": -10,
            }],
        },

        # Side 3 – den skjulte lagunen → tekst VENSTRE
        {
            "filename": "03(havfrue).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Havfruen viste vei mellom to høye klipper.\n"
                    "Bak dem lå en lagune (Navn) aldri hadde sett før.\n"
                    "\n"
                    "Vannet var helt klart, og langt der nede lyste et sterkt blått lys.\n"
                    "\n"
                    "«Dette stedet er hemmelig,» sa havfruen. «Og jeg tror skjellet valgte akkurat deg.»"
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name, "lagune", "hemmelig"],
                "x_offset": 0,
                "y_offset": -10,
            }],
        },

        # Side 4 – den magiske perlen → tekst HØYRE
        {
            "filename": "04(havfrue).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Midt i lagunen løftet havfruen frem en lysende perle.\n"
                    "\n"
                    "«Magien våkner bare for noen som virkelig vil hjelpe havet,» forklarte hun.\n"
                    "\n"
                    "(Navn) strakte hånden forsiktig frem. Da fingertuppene traff perlen, begynte hele lagunen å glitre."
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name, "perle", "Magien"],
                "x_offset": 10,
                "y_offset": -10,
                "width_offset": -10,
            }],
        },

        # Side 5 – (Navn) blir havfrue → tekst VENSTRE
        {
            "filename": "05(havfrue).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Vann og lys virvlet rundt (Navn), og hun kjente en merkelig kribling helt ned i tærne.\n"
                    "\n"
                    "Så forsvant beina hennes — og i stedet fikk hun en lang, glitrende havfruehale!\n"
                    "\n"
                    "«Jeg er en havfrue!» ropte hun."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "havfruehale", "havfrue"],
                "x_offset": 0,
                "y_offset": -10,
            }],
        },

        # Side 6 – den forste svommeturen → tekst HØYRE (barnet står på venstre side)
        {
            "filename": "06(havfrue).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Havfruen tok (Navn) med under vann.\n"
                    "Først var halen vanskelig å styre, men snart suste hun av gårde.\n"
                    "\n"
                    "Hun svømte mellom fargerike fisker, store koraller og bobler som danset rundt henne.\n"
                    "\n"
                    "(Navn) hadde aldri følt seg så lett og fri."
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name, "koraller", "fri"],
                "x_offset": 0,
                "y_offset": -10,
            }],
        },

        # Side 7 – havfruenes rike → tekst VENSTRE
        {
            "filename": "07(havfrue).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Bak en stor undervannsportal ventet et helt havfruerike.\n"
                    "\n"
                    "Tårn av koraller strakte seg opp fra havbunnen, og små hus av skjell glitret mellom lysende planter.\n"
                    "\n"
                    "(Navn) klarte nesten ikke å se på alt samtidig. Det var det vakreste hun visste."
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name, "havfruerike", "vakreste"],
                "x_offset": 0,
                "y_offset": -10,
            }],
        },

        # Side 8 – noe er galt → tekst HØYRE
        {
            "filename": "08(havfrue).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Men lenger inne i riket la (Navn) merke til noe.\n"
                    "Flere av lysene hadde sluknet.\n"
                    "\n"
                    "Korallene hadde mistet fargene sine, og fiskene gjemte seg mellom steinene.\n"
                    "\n"
                    "«Havets magi forsvinner,» sa havfruen. «Finner vi ikke årsaken, blir hele riket mørkt.»"
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name, "magi", "mørkt"],
                "x_offset": 10,
                "y_offset": -10,
                "width_offset": -10,
            }],
        },

        # Side 9 – den morke passasjen → tekst VENSTRE
        {
            "filename": "09(havfrue).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "På havbunnen oppdaget (Navn) små spor av blått lys.\n"
                    "Hun og havfruen fulgte dem inn i en gammel tunnel.\n"
                    "\n"
                    "Jo lenger de svømte, desto mørkere ble det. Bare de blå lysene viste vei.\n"
                    "\n"
                    "Plutselig hørte (Navn) en svak lyd. Noen trengte hjelp."
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name, "tunnel", "hjelp"],
                "x_offset": 0,
                "y_offset": -10,
            }],
        },

        # Side 10 – havskilpadden → tekst HØYRE (barnet står på venstre side)
        {
            "filename": "10(havfrue).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Bak noen store steiner satt en havskilpadde fast mellom ødelagte koraller.\n"
                    "\n"
                    "«Vi må hjelpe den!» sa (Navn).\n"
                    "\n"
                    "Sammen dyttet de steinene unna. Skilpadden svømte en takknemlig sirkel rundt (Navn) og vinket med hodet. Den ville at de skulle følge etter."
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name, "havskilpadde", "hjelpe"],
                "x_offset": 0,
                "y_offset": -10,
            }],
        },

        # Side 11 – den hemmelige hulen → tekst VENSTRE
        {
            "filename": "11(havfrue).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Skilpadden ledet dem dypere ned i havet.\n"
                    "Snart kom de til en enorm steinvegg dekket av gamle symboler.\n"
                    "\n"
                    "Da skilpadden svømte mot veggen, begynte symbolene å lyse.\n"
                    "\n"
                    "En skjult åpning kom til syne — inn til en hule ingen hadde besøkt på svært lenge."
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name, "symbolene", "hule"],
                "x_offset": 0,
                "y_offset": -10,
            }],
        },

        # Side 12 – havets hjerte → tekst HØYRE (barnet står på venstre side)
        {
            "filename": "12(havfrue).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Innerst i hulen lyste en enorm krystall, men lyset var svakt.\n"
                    "\n"
                    "«Havets hjerte,» hvisket havfruen. «Det gir lys og liv til hele riket.»\n"
                    "\n"
                    "Da begynte skjellet i hånden til (Navn) å gløde. Hun holdt det nærmere, og de to lysene svarte hverandre."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "krystall", "hjerte"],
                "x_offset": 0,
                "y_offset": 200,
            }],
        },

        # Side 13 – lyset vender tilbake → tekst VENSTRE
        {
            "filename": "13(havfrue).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "(Navn) la skjellet forsiktig mot Havets hjerte.\n"
                    "\n"
                    "BOOM! En bølge av blått og gyllent lys fór gjennom havet.\n"
                    "\n"
                    "Korallene fikk fargene tilbake, gatene begynte å lyse, og fiskene kom frem igjen. Havfruer jublet over hele riket. (Navn) hadde reddet dem alle."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "lys", "reddet"],
                "x_offset": 0,
                "y_offset": -10,
            }],
        },

        # Side 14 – en ny hemmelighet → tekst HØYRE
        {
            "filename": "14(havfrue).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Havfruene samlet seg rundt (Navn).\n"
                    "«Du vil alltid være velkommen her,» sa venninnen hennes.\n"
                    "\n"
                    "Da blinket Havets hjerte igjen. En lysstråle skjøt ut i det mørke havet, og langt borte tentes lys i et gammelt palass.\n"
                    "\n"
                    "«Det kan ikke være sant …» hvisket havfruen.\n"
                    "\n"
                    "(Navn) smilte. Eventyret var ikke over ennå."
                ),
                "font_size": 28,
                "color": "#FFFFFF",
                "highlights": [child_name, "palass", "Eventyret"],
                "x_offset": 10,
                "y_offset": -10,
                "width_offset": -10,
            }],
        },

        # EKSTRA BLANK SISTE INNERSIDE
        {
            "filename": "blank-back.png",
            "type": "inner",
            "side": "left",
            "blank_only": True
        },
        # PER-BOK LASTPAGE — kommer ETTER blank-back, lastes fra base_dir
        {
            "filename": "lastpage(havfrue).png",
            "type": "inner",
            "side": "right",
            "blank_only": True
        },

        # Bakside
        {
            "filename": "bakside(havfrue).png",
            "type": "cover",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Et glitrende skjell. En stemme fra havet. Et helt rike under bølgene.\n"
                    "\n"
                    "Når (Navn) finner et skjell som lyser i blått og lilla, åpner det døren til havfruenes hemmelige verden. Men magien i riket holder på å slukne, og bare noen med et ekte hjerte for havet kan vekke den igjen.\n"
                    "\n"
                    "Sammen med en havfrue og en havskilpadde leter (Navn) etter Havets hjerte — dypt inne i en hule ingen har besøkt på svært lenge.\n"
                    "\n"
                    "En personlig fortelling om mot, vennskap og magien i å hjelpe andre."
                ),
                "font_size": 38,
                "color": "#FFFFFF",
                "highlights": [child_name, "havfruenes", "Havets", "mot", "vennskap", "magien"],
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
RYGGRAD_BOOK_SLUG = "havfruen"
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

    # ------------------------ SISTE INNERSIDE (Lastpage / blank-back) ------------------------
    if page.get("blank_only"):
        blank_path = resolve_final_inner_path(page["filename"], base_dir)
        if blank_path is None:
            return []
        img = Image.open(blank_path).convert("RGBA")

        out_path = os.path.join(out_dir, page["filename"])
        os.makedirs(out_dir, exist_ok=True)
        save_img = img.convert("RGB") if out_path.lower().endswith((".jpg", ".jpeg")) else img
        save_img.save(out_path)

        print("Lagret siste innerside:", out_path)
        return [out_path]


    # ------------------------ blank side ------------------------
    if page.get("type") == "blank":
        img = Image.new(
            "RGBA",
            (INNER_WIDTH, INNER_HEIGHT),
            (255, 255, 255, 255)
        )

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

        x_offset     = block.get("x_offset", 0)
        y_offset     = block.get("y_offset", 0)
        width_offset = block.get("width_offset", 0)

        bx1 = x1 + sx(x_offset)
        bx2 = x2 + sx(width_offset)
        by1 = y  + sy(y_offset)
        by2 = sy(INNER_HEIGHT - 80)

        box = (bx1, by1, bx2, by2)


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
    src = HAVFRUEN_DREAMPAGE_FIRST if os.path.exists(HAVFRUEN_DREAMPAGE_FIRST) else os.path.join(SCRIPT_DIR, "dreampage-first.png")
    dst = os.path.join(out_dir, "dreampage-first-rendered.png")

    img = Image.open(src).convert("RGBA")
    draw = ImageDraw.Draw(img)
    w, h = img.size

    title_line = f"Til {child_name}"
    body_lines = [
        "Denne boken er laget spesielt for deg.",
        f"Du er {child_name} — helten i historien.",
        "",
        "Det er drømmene dine, motet ditt",
        "og fantasien din som fyller disse sidene.",
        "",
        "Tro alltid på deg selv,",
        "akkurat som du gjør i denne historien.",
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

    all_paths: List[str] = []
    for page in pages:
        paths = render_page(page=page, base_dir=base_dir, out_dir=out_dir)
        all_paths.extend(paths)

    inner_paths: List[str] = []
    cover_paths: List[str] = []

    for p in all_paths:
        name = os.path.basename(p).lower()
        if name == "ryggrad.png" or name.startswith("forside") or name.startswith("bakside"):
            cover_paths.append(p)
        else:
            inner_paths.append(p)

    cover_rendered = {os.path.basename(p).lower(): p for p in cover_paths}

    dreampage_first = HAVFRUEN_DREAMPAGE_FIRST if os.path.exists(HAVFRUEN_DREAMPAGE_FIRST) else os.path.join(SCRIPT_DIR, "dreampage-first.png")
    blank_back      = os.path.join(SCRIPT_DIR, "blank-back.png")
    if os.path.exists(dreampage_first):
        rendered_first = render_dreampage_first(child_name, out_dir)
        inner_paths.insert(0, rendered_first)
    else:
        print("ADVARSEL: Fant ikke dreampage-first.png")
    # blank-back.png is already produced by the render loop via the blank_only
    # entry in build_pages, so do NOT append it again here — that duplicated it
    # and pushed the page count over the guard limit.

    # -------------------- PDF 1: INNERSIDER --------------------
    if inner_paths:
        inner_pdf_path = os.path.join(out_dir, f"{child_name}_innersider.pdf")
        inner_paths = log_inner_page_order(
            inner_paths,
            script_name=os.path.basename(__file__),
            expected_count=EXPECTED_HAVFRUEN_INNER_PAGES,
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
        validate_inner_pdf_page_count(inner_pdf_path, EXPECTED_HAVFRUEN_INNER_PAGES)
        print("Innersider PDF lagret:", inner_pdf_path)
    else:
        print("Ingen innersider å bygge PDF av.")

    # -------------------- PDF 2: COVER --------------------
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


# Vertikal plassering av de to tekstblokkene, per sidetall. Maalt mot den NYE
# kunsten - se patch_havfruen_page_offsets.py for hvorfor 6 og 10 skiller seg ut.
_DP_PAGE_OFFSETS = {
    3:  (40, 365),
    6:  (370, 555),    # tekst flyttet til hoyre side - blokkene under havfruens arm
    7:  (115, 410),
    10: (330, 530),    # tekst flyttet til hoyre side - blokkene pa skilpaddeskallet
    12: (330, 545),    # tekst flyttet til hoyre side - blokkene under krystallen
    13: (50, 365),
}


def _dp_layout_offsets(filename: str):
    number = _dp_page_number(filename)
    top_y, bottom_y = _DP_PAGE_OFFSETS.get(number, (25, 345))
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

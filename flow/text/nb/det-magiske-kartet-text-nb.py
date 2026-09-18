

from reportlab.pdfgen import canvas
from reportlab.lib.units import inch

import shutil  

import os
import sys
import re
import filecmp
import argparse
from typing import List, Dict, Any
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from gelato_cover import build_gelato_cover_pdf
from dream_pdf_guard import (
    EXPECTED_INNER_PAGES,
    log_inner_page_order,
    validate_inner_pdf_page_count,
)

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

FRONT_LOGO_PATH = os.path.join(SCRIPT_DIR, "DreamPage_logo.png")
BACK_LOGO_PATH  = os.path.join(SCRIPT_DIR, "DreamPage_logo.png")

COVER_FONT       = os.path.join(SCRIPT_DIR, "PlayfairDisplay.ttf")
COVER_TITLE_FONT = os.path.join(SCRIPT_DIR, "Trebuchet MS Bold.ttf")
INNER_FONT     = os.path.join(SCRIPT_DIR, "Georgia.ttf")

MAGISK_DREAMPAGE_FIRST = os.path.join(
    DP_ROOT,
    "books", "den-magiske-reisen-gutt", "dreampage-first-magisk.png"
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

    return logo_rgba


def crop_logo_to_visible_alpha(logo_img, alpha_threshold=8):
    """Crop the logo using a thresholded alpha mask so faint semi-transparent
    background haze in the asset does not affect scaling or placement."""
    logo_rgba = logo_img.convert("RGBA")
    alpha = logo_rgba.getchannel("A")
    bbox = alpha.point(lambda p: 255 if p > alpha_threshold else 0).getbbox()
    if bbox:
        return logo_rgba.crop(bbox)
    return logo_rgba


def resolve_front_cover_logo(base_dir: str | None = None) -> str | None:
    """Resolve the cover logo from C:/DreamPage-OS/assets/logo/<locale>."""
    candidates = [
        os.path.join(LOGO_DIR, "magiske-reise-logo.png"),
        os.path.join(LOGO_DIR, "magiske-reise-logo.webp"),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return None


def draw_centered_title_cover(img, text, base_dir: str | None = None):
    """
    Forside-tittel:
    - Linje 1: tekst (f.eks. "[NAVN] sin") med Trebuchet MS Bold
    - Linje 2: magiske-reise-logo.png fra script/logo/<locale>
    """
    draw = ImageDraw.Draw(img)
    w, h = img.size
    base = min(w, h)

    line1 = text.split("\n")[0] if text else ""

    font_size_line1 = max(50, int(base * 0.07))
    font_small = ImageFont.truetype(COVER_TITLE_FONT, font_size_line1)

    GOLD         = ((255, 255, 255), (255, 255, 255))
    SHADOW_COL   = (15, 35, 65)
    TOP_MARGIN   = 0.04
    LINE_SPACING = 0.060
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

    # --- Linje 1: gradient tekst (hvit) ---
    tm   = _make_text_mask(img.size, x1_pos, y1_pos, line1, font_small)
    bbox = draw.textbbox((x1_pos, y1_pos), line1, font=font_small)
    _paste_gradient(img, tm, bbox, GOLD[0], GOLD[1])

    # --- Linje 2: magiske-reise-logo ---
    logo_path = resolve_front_cover_logo(base_dir)
    if not logo_path:
        print("ADVARSEL: Fant ikke magiske-reise-logo")
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


# ------------------------------------------------------------
#  build_pages – (uendret, din tekst)
# ------------------------------------------------------------

def build_pages_legacy_template(child_name: str) -> List[Dict[str, Any]]:
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
            "filename": "forside(prinsessen).png",
            "type": "cover",
            "text": p("Prinsesse [NAVN] og\nMotet I Hjertet"),
        },
        {
            "filename": "ryggrad.png",
            "type": "cover",
        },

        {
           "type": "blank",
           "side": "right",
           "text": p("Prinsesse [NAVN] og\nMotet I Hjertet"),
           "blocks": [{
                "text": p(
                    "Denne boken er laget spesielt for deg, (Navn).\n"
                    "Du er helten i dette eventyret – modig, god og full av lys.\n"
                    "Vi håper historien varmer hjertet ditt og følger deg lenge."
                ),
                "font_size": 42,
           
                "y_offset": 420,
                "color": "#000000"
           }]
        },



        # Side 1
        {
            "filename": "01(Prinsessen).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Det var en gang en prinsesse som het (Navn).\n"
                    "Hun bodde i et rosa slott omgitt av blomster i alle farger.\n"
                    "Men denne morgenen kjente (Navn) noe nytt i hjertet.\n"
                    "En liten stemme hvisket: «Det er noe der ute som venter på deg.»"
                ),
                "font_size": 35,
                "color": "#FFF5EB",
                "highlights": ["eventyr", "hjertet"],
                "x_offset": 60,
                "y_offset": 0,
                "paragraph_gap": 0.4,
                "line_height": 1.5,
                "width_offset": 0
            }],
        },

        # Side 2
        {
            "filename": "02(Prinsessen).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "(Navn) fulgte stien inn i den lysende skogen.\n"
                    "Blomstene bøyde seg mykt da hun gikk forbi, som om de hilste på henne.\n"
                    "Sollyset danset gjennom løvet og varmet kinnene hennes.\n"
                    "Hun smilte og tok et nytt steg fremover."
                ),
                "font_size": 35,
                "color": "#FFF5EB",
                "highlights": ["smilte", "fremover"],
                "line_height": 1.5,
                "width_offset": -40,
                "paragraph_gap": 0.4,
                "x_offset": 20,
                "y_offset": -40,

            }],
        },

        # Side 3
        {
            "filename": "03(Prinsessen).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Dypt inne i skogen begynte luften å glitre.\n"
                    "Gyldne gnister svevde rundt (Navn) som stille stjerner.\n"
                    "En sommerfugl i oransje og blått fløy sakte mot henne.\n"
                    "«Denne skogen er magisk,» tenkte (Navn) og lo av ren glede."
                ),
                "font_size": 35,
                "color": "#FFF5EB",
                "highlights": ["magisk", "glede"],
                "x_offset": 60,
                "y_offset": -45,
                "paragraph_gap": 0.4,
                "line_height": 1.5,
                "width_offset": 0
            }],
        },

        # Side 4
        {
            "filename": "04(Prinsessen).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Farger (Navn) aldri hadde sett før blomstret rundt henne.\n"
                    "En blå sommerfugl landet stille på en blomst ved siden av stien.\n"
                    "«Ser du det?» hvisket skogen. «Du er akkurat der du skal være.\"\n"
                    "(Navn) kjente en varm og rolig følelse vokse i brystet."
                ),
                "font_size": 35,
                "color": "#000000",
                "highlights": ["rolig", "vokse"],
                "line_height": 1.5,
                "width_offset": -60,
                "paragraph_gap": 0.4,
                "x_offset": 20,
                "y_offset": -45,
            }],
        },

        # Side 5
        {
            "filename": "05(Prinsessen).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Et fossefall glitret mellom trærne, og lyset danset på vannet.\n"
                    "Rosa sommerfugler fløy rundt (Navn) som om de feiret henne.\n"
                    "Luften luktet søtt og friskt på samme tid.\n"
                    "«Jeg er ikke redd,» sa (Navn) høyt. «Jeg er klar.\""
                ),
                "font_size": 35,
                 "color": "#FFF5EB",
                "highlights": ["klar", "feiret"],
                "line_height": 1.5,
                "width_offset": -40,
                "paragraph_gap": 0.4,
                "x_offset": 20,
                "y_offset": -45,
            }],
        },

        # Side 6
        {
            "filename": "06(Prinsessen).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Så stoppet (Navn) opp ved en gammel trebridge over bekken.\n"
                    "På den andre siden fortsatte stien videre, inn i det ukjente.\n"
                    "Hjertet hennes slo litt fortere. Hva om det var vanskelig der fremme?\n"
                    "(Navn) holdt pusten – og valgte å gå over."
                ),
                "font_size": 35,
                "color": "#FFF5EB",
                "highlights": ["ukjente", "valgte"],
                "x_offset": 60,
                "y_offset": -45,
                "paragraph_gap": 0.4,
                "line_height": 1.5,
                "width_offset": 0
            }],
        },

        # Side 7
        {
            "filename": "07(Prinsessen).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "På den andre siden åpnet verden seg i et hav av farger.\n"
                    "En regnbue strakte seg fra sky til sky, akkurat foran henne.\n"
                    "(Navn) snudde seg og smilte tilbake mot broen hun hadde krysset.\n"
                    "«Det var ikke så farlig likevel,» tenkte hun stolt."
                ),
                "font_size": 35,
                "color": "#FFF5EB",
                "highlights": ["stolt", "regnbue"],
                "x_offset": 60,
                "y_offset": -45,
                "paragraph_gap": 0.4,
                "line_height": 1.5,
                "width_offset": 0
            }],
        },

        # Side 8
        {
            "filename": "08(Prinsessen).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Men så stoppet (Navn) opp foran noe enda vanskeligere.\n"
                    "Elven var bred, og de glatte steinene lå langt fra hverandre.\n"
                    "En klump av uro satte seg i magen. «Hva om jeg faller?\"\n"
                    "Hun lukket øynene, la hånden mot hjertet og pustet rolig."
                ),
                "font_size": 35,
                "color": "#FFF5EB",
                "highlights": ["uro", "hjertet"],
                "line_height": 1.5,
                "width_offset": -40,
                "paragraph_gap": 0.4,
                "x_offset": 20,
                "y_offset": 40,
            }],
        },

        # Side 9
        {
            "filename": "09(Prinsessen).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Så husket (Navn) noe viktig: mot er ikke å være uten frykt.\n"
                    "Mot er å ta et steg selv når knærne skjelver litt.\n"
                    "Hun åpnet øynene og smilte rolig mot vannet.\n"
                    "«Jeg klarer det,» sa hun stille – og mente det."
                ),
                "font_size": 35,
                "color": "#FFF5EB",
                "highlights": ["mot", "klarer"],
                "line_height": 1.5,
                "width_offset": -40,
                "paragraph_gap": 0.4,
                "x_offset": 20,
                "y_offset": 40,
            }],
        },

        # Side 10
        {
            "filename": "10(Prinsessen).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "(Navn) hoppet fra stein til stein med et stort smil om munnen.\n"
                    "Vannet sprutet rundt de nakne føttene hennes, kaldt og herlig.\n"
                    "En regnbue lyste opp himmelen, og slottet glitret i det fjerne.\n"
                    "Hun lo høyt og kjente seg friere enn noen gang."
                ),
                "font_size": 35,
                "color": "#FFF5EB",
                "highlights": ["friere", "smil"],
                "x_offset": 60,
                "y_offset": -45,
                "paragraph_gap": 0.4,
                "line_height": 1.5,
                "width_offset": 0
            }],
        },

        # Side 11
        {
            "filename": "11(Prinsessen).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Stien hjem gikk gjennom en hage av tusen blomster.\n"
                    "Hvert steg (Navn) tok, føltes lettere enn det forrige.\n"
                    "Hun bar med seg noe nytt nå – ikke i hånden, men i hjertet.\n"
                    "Motet hadde alltid vært der. Hun hadde bare funnet det."
                ),
                "font_size": 35,
                "color": "#FFF5EB",
                "highlights": ["motet", "funnet"],
                "x_offset": 60,
                "y_offset": -45,
                "paragraph_gap": 0.4,
                "line_height": 1.5,
                "width_offset": 0
            }],
        },

        # Side 12
        {
            "filename": "12(Prinsessen).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Slottet stod foran henne, enda vakrere enn hun husket det.\n"
                    "Blomstene langs broen lyste i alle regnbuens farger.\n"
                    "(Navn) stoppet et øyeblikk og lot synet synke inn.\n"
                    "«Jeg dro ut som prinsesse,» tenkte hun. «Jeg kommer hjem som helt.\""
                ),
                "font_size": 35,
                "color": "#FFF5EB",
                "highlights": ["helt", "hjem"],
                "line_height": 1.5,
                "width_offset": -40,
                "paragraph_gap": 0.4,
                "x_offset": 20,
                "y_offset": 40,
            }],
        },

        # Side 13
        {
            "filename": "13(Prinsessen).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Inne i slottsporten ventet musikk, lys og kjente stemmer.\n"
                    "(Navn) snudde seg ett siste gong og så tilbake på veien hun hadde gått.\n"
                    "Hvert steg hadde telt. Hvert øyeblikk hadde formet henne.\n"
                    "Hun tok et dypt pust og gikk inn – med hodet hevet og hjertet varmt."
                ),
                "font_size": 35,
                 "color": "#FFF5EB",
                "highlights": ["formet", "varmt"],
                "x_offset": 60,
                "y_offset": -45,
                "paragraph_gap": 0.4,
                "line_height": 1.5,
                "width_offset": 0
               
            }],
        },

        # Side 14
        {
            "filename": "14(Prinsessen).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Den kvelden lyste himmelen i rosa og gull over slottet.\n"
                    "Fyrverkeri sprakk som stjerner over elven og skogen.\n"
                    "Og midt i det hele stod prinsesse (Navn) – og smilte.\n"
                    "For hun visste nå: det modigste hun noen gang hadde gjort,\n"
                    "var å tro på seg selv."
                ),
                "font_size": 35,
                "color": "#FFF5EB",
                "highlights": ["tro", "modigste"],
                "line_height": 1.5,
                "width_offset": -40,
                "paragraph_gap": 0.4,
                "x_offset": 20,
                "y_offset": 40,
            }],
        },

        # Bakside
        {
            "filename": "bakside(prinsessen).png",
            "type": "cover",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Denne boken handler om mot.\n"
                    "Om å være usikker, men likevel våge å ta et steg videre.\n"
                    "Den viser at ekte mot ikke alltid handler om å være sterk eller fryktløs, men om å lytte til hjertet sitt og tørre å prøve når det betyr mest.\n"
                    "Derfor er det prinsesse (Navn) som er helten i denne historien. En helt som lærer at mot kan være stille, vennlig og fullt av håp.\n"
                    "En personlig fortelling som gir barn trygghet, selvtillit og troen på seg selv – og minner dem på at de er modigere enn de tror."
                
                ),
                "font_size": 46,
                "color": "#FFFFFF",
                "highlights": ["styrken", "mot", "helter", "sterke", "(Navn)", "helten", "troen", "modigere", "våge"],
               
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
RYGGRAD_BOOK_SLUG = "den-magiske-reisen-gutt"
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
#  SISTE INNERSIDE - bokas egen "Dette eventyer er over"-side
# ------------------------------------------------------------
# Erstatter den delte blank-back.png, men viker ALLTID for ordrens egen
# "Fortsett eventyret"-side (QR-oppsalget). Tom streng = ingen egen side for
# dette spraket -> delt mal, som for.
_BB_LOCALES = {"nb", "nn", "en-US", "en-GB", "sv"}
_BB_LOCALE = os.path.basename(SCRIPT_DIR)
if _BB_LOCALE not in _BB_LOCALES:
    _BB_LOCALE = "nb"
_BB_NAME = {'nb': 'blank-back(magisk).png'}.get(_BB_LOCALE, "")
MAGISK_BLANK_BACK = os.path.join(
    DP_ROOT,
    "books", 'den-magiske-reisen-gutt', _BB_NAME,
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
    if MAGISK_BLANK_BACK and os.path.exists(MAGISK_BLANK_BACK):
        return MAGISK_BLANK_BACK
    return None


def render_page(page: Dict[str, Any], base_dir: str, out_dir: str) -> List[str]:

    if page.get("blank_only"):
        blank_path = (resolve_book_blank_back(page["filename"], base_dir)
                      or os.path.join(SCRIPT_DIR, page["filename"]))

        if not os.path.exists(blank_path):
            raise FileNotFoundError(f"Fant ikke final inner/back page: {blank_path}")

        img = Image.open(blank_path)
        out_path = os.path.join(out_dir, page["filename"])
        os.makedirs(out_dir, exist_ok=True)
        img.save(out_path)

        print("Lagret final inner/back page:", out_path)
        return [out_path]

    # ------------------------ blank side ------------------------
    if page.get("type") == "blank":
        blank_path = _dp_first(MAGISK_DREAMPAGE_FIRST)

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
                align="center",
                # Defaulten er 10 px absolutt (arvet fra en 1024 px-mal) og
                # klistret linjene sammen paa 4096 px-sida. 0.55 * fontstorrelsen
                # er samme forhold som den-magiske-reisen-jente fikk 14.09.2026.
                line_spacing=max(10, int(font_size * 0.55)),
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

        y = sy(200)
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


def build_pages_verden_template(child_name: str) -> List[Dict[str, Any]]:
    def p(text: str) -> str:
        return (
            text.replace("[NAVN]", child_name)
                .replace("[ NAVN ]", child_name)
                .replace("(navn)", child_name)
                .replace("(Navn)", child_name)
                .replace("{{name}}", child_name)
                .replace("{{['name']}}", child_name)
        )

    return [
        {
            "filename": "forside(verden).png",
            "type": "cover",
            "text": p("[NAVN] og\nDen Skjulte Verdenen"),
        },
        {
            "filename": "ryggrad.png",
            "type": "cover",
        },
        {
            "type": "blank",
            "side": "right",
            "text": p("[NAVN] og\nDen Skjulte Verdenen"),
            "blocks": [{
                "text": p(
                    "Denne boken er laget spesielt for deg, [NAVN].\n"
                    "Noen hemmeligheter viser seg bare for dem som tør å lytte.\n"
                    "Vi håper denne historien fyller deg med undring, mot og magi."
                ),
                "font_size": 34,
                "y_offset": 110,
                "color": "#111111",
            }],
        },
        {
            "filename": "01(verden).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Etter en helt vanlig dag gikk [NAVN] langs stien han kjente så godt.\n"
                    "Da hørte han en dyp, brusende lyd mellom trærne.\n"
                    "Den lød som en foss langt borte.\n"
                    "Likevel visste han at det ikke fantes noen foss her."
                ),
                "font_size": 35,
                "color": "#FFF8F0",
                "highlights": ["lyd", "foss"],
                "x_offset": 60,
                "y_offset": -20,
            }],
        },
        {
            "filename": "02(verden).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "[NAVN] fulgte lyden bort fra den vanlige stien.\n"
                    "Mellom mose og gamle steiner fant han en smal åpning i skogen.\n"
                    "Stien så gammel ut, men ikke skummel.\n"
                    "Det føltes nesten som om den hadde ventet på ham."
                ),
                "font_size": 35,
                "color": "#FFF8F0",
                "highlights": ["stien", "ventet"],
                "x_offset": 10,
                "y_offset": -30,
                "width_offset": -30,
            }],
        },
        {
            "filename": "03(verden).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Stien åpnet seg brått, og [NAVN] stanset helt.\n"
                    "Foran ham falt en mektig foss mellom mørke fjell.\n"
                    "Midt i vannet glødet et varmt, gyllent lys.\n"
                    "Skogen hadde gjemt på en hemmelighet hele tiden."
                ),
                "font_size": 34,
                "color": "#FFF8F0",
                "highlights": ["gyllent", "hemmelighet"],
                "x_offset": 0,
                "y_offset": -15,
                "width_offset": -20,
            }],
        },
        {
            "filename": "04(verden).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "[NAVN] gikk nærmere og kjente kald damp mot kinnet.\n"
                    "Bak det fallende vannet skimtet han en åpning.\n"
                    "Han visste at han kanskje burde snu.\n"
                    "Men nysgjerrigheten var sterkere enn frykten."
                ),
                "font_size": 35,
                "color": "#FFF8F0",
                "highlights": ["åpning", "nysgjerrigheten"],
                "x_offset": 60,
                "y_offset": -10,
            }],
        },
        {
            "filename": "05(verden).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Da [NAVN] rørte ved vannet, ble han stående helt stille.\n"
                    "Det føltes ikke kaldt og vått, men varmt som lys.\n"
                    "Han tok et dypt pust og gikk ett skritt frem.\n"
                    "Et øyeblikk var alt gull, glans og brusende lyd."
                ),
                "font_size": 35,
                "color": "#FFF8F0",
                "highlights": ["lys", "gull"],
                "x_offset": 20,
                "y_offset": -15,
                "width_offset": -20,
            }],
        },
        {
            "filename": "06(verden).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "På den andre siden ventet en dal ingen hadde sett.\n"
                    "Elven var klar som glass, og gresset bølget mykt i vinden.\n"
                    "Fjellene rundt glødet svakt i det gylne lyset.\n"
                    "[NAVN] skjønte at han hadde funnet en skjult verden."
                ),
                "font_size": 35,
                "color": "#FFF8F0",
                "highlights": ["dal", "skjult"],
                "x_offset": 60,
                "y_offset": -25,
            }],
        },
        {
            "filename": "07(verden).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "En liten bro førte ham over elven til en gammel hytte.\n"
                    "Den lå stille mellom røtter og stein, med døren på gløtt.\n"
                    "Inne på et bord lå en støvete bok.\n"
                    "På forsiden sto det: Den skjulte verdenen må aldri glemmes."
                ),
                "font_size": 34,
                "color": "#FFF8F0",
                "highlights": ["boken", "glemmes"],
                "x_offset": 70,
                "y_offset": -30,
                "width_offset": 10,
            }],
        },
        {
            "filename": "08(verden).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Sidene var fulle av tegninger av fossen, dalen og et stort tre.\n"
                    "Boken fortalte at fossen holdt verdenen skjult og trygg.\n"
                    "Men på den siste siden sto en advarsel.\n"
                    "Når lyset i fossen slukner, forsvinner verdenen for alltid."
                ),
                "font_size": 34,
                "color": "#FFF8F0",
                "highlights": ["advarsel", "lyset"],
                "x_offset": 70,
                "y_offset": 25,
                "width_offset": 10,
            }],
        },
        {
            "filename": "09(verden).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "[NAVN] løp ut av hytta og så mot fossen.\n"
                    "Det gyldne lyset var svakere nå, som om dagen holdt på å gi opp.\n"
                    "Skygger gled stille inn over dalen.\n"
                    "Da forsto han at stedet ikke bare var vakkert. Det trengte hjelp."
                ),
                "font_size": 34,
                "color": "#FFF8F0",
                "highlights": ["lyset", "hjelp"],
                "x_offset": 20,
                "y_offset": 35,
                "width_offset": -10,
            }],
        },
        {
            "filename": "10(verden).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "[NAVN] bladde tilbake i boken og fant et gammelt tegn.\n"
                    "Et solmerke hørte hjemme ved det store treet midt i dalen.\n"
                    "Bare når merket kom på plass, ville lyset våkne igjen.\n"
                    "Han så opp mot høyden og visste hvor han måtte gå."
                ),
                "font_size": 34,
                "color": "#FFF8F0",
                "highlights": ["solmerke", "lyset"],
                "x_offset": 60,
                "y_offset": -20,
            }],
        },
        {
            "filename": "11(verden).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "[NAVN] fulgte elven innover i den stille verdenen.\n"
                    "Han gikk gjennom høyt gress, over glatte steiner og forbi gamle trær.\n"
                    "Jo nærmere han kom, desto mørkere ble himmelen.\n"
                    "Det var som om hele dalen holdt pusten."
                ),
                "font_size": 35,
                "color": "#FFF8F0",
                "highlights": ["stille", "pusten"],
                "x_offset": 15,
                "y_offset": 0,
                "width_offset": -20,
            }],
        },
        {
            "filename": "12(verden).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Ved foten av treet fant han solmerket, halvveis skjult i jord og røtter.\n"
                    "Det glødet svakt, men lyset var nesten borte.\n"
                    "[NAVN] tok tak og prøvde å dra det løs.\n"
                    "Vinden svarte med et hardt sus gjennom grenene."
                ),
                "font_size": 34,
                "color": "#FFF8F0",
                "highlights": ["solmerket", "lyset"],
                "x_offset": 55,
                "y_offset": 10,
            }],
        },
        {
            "filename": "13(verden).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "[NAVN] satte seg ned, pustet dypt og prøvde igjen.\n"
                    "Han gravde med hendene, skjøv steiner unna og dro alt han kunne.\n"
                    "Til slutt løsnet solmerket og fylte hendene hans med varme.\n"
                    "Han løftet det opp og plasserte det forsiktig mellom røttene."
                ),
                "font_size": 34,
                "color": "#FFF8F0",
                "highlights": ["varme", "forsiktig"],
                "x_offset": 25,
                "y_offset": 10,
                "width_offset": -20,
            }],
        },
        {
            "filename": "14(verden).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Først ble alt helt stille.\n"
                    "Så strømmet lys gjennom treet, ned i bakken, ut i elven og tilbake til fossen.\n"
                    "Da [NAVN] kom ut i skogen igjen, lå et lite gyllent blad i hånden hans.\n"
                    "Han smilte for seg selv. En dag skulle han finne veien tilbake."
                ),
                "font_size": 34,
                "color": "#FFF8F0",
                "highlights": ["lys", "tilbake"],
                "x_offset": 60,
                "y_offset": -10,
            }],
        },
        {
            "filename": "bakside(verden).png",
            "type": "cover",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Bak en foss, skjult dypt i skogen, finner [NAVN] en verden ingen andre kjenner til.\n"
                    "Men når lyset i fossen begynner å svinne, må han følge motet sitt og redde hemmeligheten før den forsvinner.\n"
                    "Den skjulte verdenen er en varm og eventyrlig fortelling om nysgjerrighet, mot og små spor av magi som blir med oss hjem.\n"
                    "En personlig bok som minner barn om at store eventyr ofte begynner med ett lite steg."
                ),
                "font_size": 44,
                "color": "#FFFFFF",
                "highlights": [child_name, "mot", "magi", "eventyr", "hemmeligheten"],
            }],
        },
    ]
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

    return [
        {
            "filename": "forside(kartet).png",
            "type": "cover",
            "text": p("[NAVN] sin"),
        },
        {
            "filename": "ryggrad.png",
            "type": "cover",
        },
        {
            "type": "blank",
            "side": "right",
            "text": p("[NAVN] og\nDet Magiske Kartet"),
            "blocks": [{
                "text": p(
                    "Denne boken er laget spesielt for deg, [NAVN].\n"
                    "Noen kart viser veien til steder.\n"
                    "Dette kartet viser veien til motet, godheten og magien inni deg."
                ),
                "font_size": 42,
                "color": "#111111",
                "highlights": [child_name],
            }],
        },
        {
            "filename": "01(kartet).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "[NAVN] hadde nesten gjort seg klar for kvelden da han oppdaget noe merkelig.\n"
                    "Mellom bøkene på rommet lå et kart han aldri hadde sett før.\n"
                    "Det så gammelt og støvete ut, men da han løftet det opp, begynte kantene å gløde svakt i gull."
                ),
                "font_size": 34,
                "color": "#FFF8EA",
                "highlights": ["kart", "gløde"],
                "x_offset": 15,
                "y_offset": -25,
                "width_offset": -20,
            }],
        },
        {
            "filename": "02(kartet).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Kartet ble varmt i hendene hans.\n"
                    "Små tegn av gyllent lys steg opp fra papiret og danset rundt i rommet som hemmelige stjerner.\n"
                    "[NAVN] holdt pusten.\n"
                    "Dette var ikke et vanlig kart."
                ),
                "font_size": 35,
                "color": "#FFF8EA",
                "highlights": ["stjerner", "kart"],
                "x_offset": 10,
                "y_offset": -20,
                "width_offset": -30,
            }],
        },
        {
            "filename": "03(kartet).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Lyset fra kartet samlet seg ved vinduet.\n"
                    "Først var det lite som en gnist, men så vokste det til en rund, gyllen portal.\n"
                    "Inne i lyset skimtet [NAVN] en skog med glødende planter og blinkende blågrønne lys."
                ),
                "font_size": 34,
                "color": "#FFF8EA",
                "highlights": ["portal", "skog"],
                "x_offset": 55,
                "y_offset": -20,
            }],
        },
        {
            "filename": "04(kartet).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "[NAVN] tok et forsiktig skritt nærmere.\n"
                    "Portalen summet mykt, som om den ventet på ham.\n"
                    "Han var spent, men kartet lyste varmt i hånden hans.\n"
                    "Så rettet han ryggen og hvisket: Jeg tør."
                ),
                "font_size": 34,
                "color": "#FFF8EA",
                "highlights": ["Jeg", "tør"],
                "x_offset": 20,
                "y_offset": -10,
                "width_offset": -20,
            }],
        },
        {
            "filename": "05(kartet).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "I neste øyeblikk sto [NAVN] midt i den fortryllede skogen.\n"
                    "Trærne var høyere enn hus, og blomstene glødet svakt langs stien.\n"
                    "Bak ham blinket portalen stille mellom greinene.\n"
                    "Reisen hadde virkelig begynt."
                ),
                "font_size": 34,
                "color": "#FFF8EA",
                "highlights": ["fortryllede", "begynt"],
                "x_offset": 20,
                "y_offset": -20,
                "width_offset": -25,
            }],
        },
        {
            "filename": "06(kartet).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "På stien foran ham dukket en liten gyllen rev opp.\n"
                    "Den hadde kloke øyne og en hale som glitret som sollys.\n"
                    "\"Kartet viser veien,\" sa reven mykt.\n"
                    "\"Men du må selv tørre å følge den.\""
                ),
                "font_size": 32,
                "color": "#FFF8EA",
                "highlights": ["reven", "tørre"],
                "x_offset": 10,
                "y_offset": -15,
                "width_offset": -30,
            }],
        },
        {
            "filename": "07(kartet).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Reven ledet [NAVN] til et gammelt tre med et stjerneformet merke i barken.\n"
                    "Da han holdt kartet nærmere, begynte både treet og papiret å skinne.\n"
                    "Stjernemerket løsnet forsiktig og svevde inn i kartet.\n"
                    "\"Én del av veien er funnet,\" sa reven."
                ),
                "font_size": 33,
                "color": "#FFF8EA",
                "highlights": ["Stjernemerket", "funnet"],
                "x_offset": 50,
                "y_offset": -20,
                "width_offset": 20,
            }],
        },
        {
            "filename": "08(kartet).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Da stjernemerket landet på kartet, begynte linjene å flytte på seg.\n"
                    "Lyset samlet seg mellom trærne, og en ny portal åpnet seg.\n"
                    "På den andre siden svevde øyer høyt over skyene, med fossefall som falt rett ned i luften.\n"
                    "\"Kartet tror du er klar,\" sa reven."
                ),
                "font_size": 32,
                "color": "#FFF8EA",
                "highlights": ["portal", "klar"],
                "x_offset": 55,
                "y_offset": -25,
            }],
        },
        {
            "filename": "09(kartet).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "På en av de flyvende øyene hørte [NAVN] en svak lyd.\n"
                    "Bak glødende slyngplanter satt en liten drageunge fast med vingen sin.\n"
                    "Den så redd ut, men ikke farlig.\n"
                    "[NAVN] løsnet plantene én etter én, og dragen dyttet snuten takknemlig mot hånden hans."
                ),
                "font_size": 32,
                "color": "#FFF8EA",
                "highlights": ["drageunge", "takknemlig"],
                "x_offset": 55,
                "y_offset": -20,
            }],
        },
        {
            "filename": "10(kartet).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Drageungen ristet på vingene og pekte med snuten mot kartet.\n"
                    "Et nytt stjernemerke våknet på papiret.\n"
                    "Blått og gull blandet seg i luften foran dem, og en portal åpnet seg.\n"
                    "Inne i lyset lå en by under havet, full av koraller og små svevende måner."
                ),
                "font_size": 32,
                "color": "#FFF8EA",
                "highlights": ["stjernemerke", "havet"],
                "x_offset": 55,
                "y_offset": -20,
            }],
        },
        {
            "filename": "11(kartet).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Da [NAVN] gikk gjennom portalen, lukket en glødende luftboble seg rundt ham.\n"
                    "Utenfor danset vannet stille, og hele undervannsbyen lyste.\n"
                    "Midt i byen blinket et nytt stjernemerke på kartet.\n"
                    "Da han rørte ved merket, fløy lyset rett inn i papiret."
                ),
                "font_size": 30,
                "color": "#FFF8EA",
                "highlights": ["luftboble", "stjernemerke"],
                "x_offset": 55,
                "y_offset": -20,
            }],
        },
        {
            "filename": "12(kartet).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Det nye stjernemerket fikk kartet til å lyse kaldt og klart.\n"
                    "En portal åpnet seg, og [NAVN] steg ut i en verden av is og nordlys.\n"
                    "Fjellene ruvet rundt ham som blå krystaller.\n"
                    "Drageungen sto ved siden av ham, klar til å følge ham videre."
                ),
                "font_size": 33,
                "color": "#FFF8EA",
                "highlights": ["nordlys", "videre"],
                "x_offset": 15,
                "y_offset": -20,
                "width_offset": -25,
            }],
        },
        {
            "filename": "13(kartet).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Da det siste lyset fra nordlyset traff kartet, åpnet det seg en dør av stjerner.\n"
                    "Bak den lå Stjernebiblioteket, større og vakrere enn noe [NAVN] hadde sett før.\n"
                    "Bøker svevde mellom hyllene, og i midten sto en himmelglobus full av gyllent lys.\n"
                    "Alle stjernemerkene samlet seg til én strålende vei."
                ),
                "font_size": 31,
                "color": "#FFF8EA",
                "highlights": ["Stjernebiblioteket", "vei"],
                "x_offset": 55,
                "y_offset": -25,
                "width_offset": 15,
            }],
        },
        {
            "filename": "14(kartet).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Et øyeblikk senere sto [NAVN] tilbake på rommet sitt.\n"
                    "Alt så nesten vanlig ut igjen: sengen, bøkene og teleskopet ved vinduet.\n"
                    "Men kartet glødet fortsatt mykt, fullt av stjernemerker fra reisen.\n"
                    "Da forsto han det viktigste: Kartet hadde vist veien, men magien hadde vært i ham."
                ),
                "font_size": 29,
                "color": "#FFF8EA",
                "highlights": ["magien", "ham"],
                "x_offset": 15,
                "y_offset": -40,
                "width_offset": -25,
            }],
        },
        {
            "filename": "blank-back.png",
            "type": "inner",
            "side": "left",
            "blank_only": True,
        },
        {
            "filename": "bakside(kartet).png",
            "type": "cover",
            "side": "left",
            "blocks": [{
                "text": p(
                    "En kveld finner [NAVN] et gammelt kart som begynner å gløde i hendene hans.\n"
                    "Kartet åpner portaler til fortryllede skoger, flyvende øyer, en undervannsby, en isverden og et bibliotek av stjerner.\n"
                    "På reisen hjelper [NAVN] nye venner, samler stjernemerker og oppdager at ekte magi ikke bare finnes på kartet.\n"
                    "Den finnes i motet hans, i godheten hans og i troen på at han kan gå videre."
                ),
                "font_size": 43,
                "color": "#FFFFFF",
                "highlights": [child_name, "kartet", "magi", "motet", "godheten"],
            }],
        },
    ]


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
    need = ["bakside(kartet).png", "ryggrad.png", "forside(kartet).png"]
    missing = [n for n in need if n not in cover_rendered]

    if missing:
        print("Cover PDF ble IKKE laget. Mangler rendret cover-del(er):", ", ".join(missing))
        return

    back_path  = cover_rendered["bakside(kartet).png"]
    spine_path = cover_rendered["ryggrad.png"]
    front_path = cover_rendered["forside(kartet).png"]

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

    if gelato_api_key:
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
    else:
        print("Ingen Gelato API key funnet. Beholder Lulu-safe cover PDF:", cover_pdf_path)


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

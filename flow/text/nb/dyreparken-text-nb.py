


from reportlab.pdfgen import canvas
from reportlab.lib.units import inch

import shutil  
import filecmp

import os
import re
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
SCRIPT_LOCALES = {"nb", "nn", "en-US", "en-GB"}
SCRIPT_LOCALE = os.path.basename(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR) in SCRIPT_LOCALES else "nb"
SCRIPT_ROOT_DIR = os.path.dirname(SCRIPT_DIR) if SCRIPT_LOCALE in SCRIPT_LOCALES else SCRIPT_DIR
LOGO_DIR = os.path.join(SCRIPT_ROOT_DIR, "logo", SCRIPT_LOCALE)
LASTPAGE_DIR = os.path.join(SCRIPT_ROOT_DIR, "lastpages", SCRIPT_LOCALE)

FRONT_LOGO_PATH = os.path.join(SCRIPT_DIR, "DreamPage_logo.png")
BACK_LOGO_PATH  = os.path.join(SCRIPT_DIR, "DreamPage_logo.png")

COVER_FONT       = os.path.join(SCRIPT_DIR, "PlayfairDisplay.ttf")
COVER_TITLE_FONT = os.path.join(SCRIPT_DIR, "Trebuchet MS Bold.ttf")
INNER_FONT     = os.path.join(SCRIPT_DIR, "Georgia.ttf")

DYREPARKEN_DREAMPAGE_FIRST = os.path.join(
    os.path.dirname(SCRIPT_ROOT_DIR), "books", "dyreparken", "dreampage-first-dyrepark.png"
)
DREAMPAGE_FIRST_TAGLINE = "Trykket med omtanke for\nkvalitet"

# Dyreparkens egen siste innerside ("Dette eventyret er over ..." med dyr).
# Erstatter Lastpage(dyreparken).png. Faller tilbake til den gamle sida hvis
# fila mangler, og viker ALLTID for ordrens egen "Fortsett eventyret"-side.
DYREPARKEN_BLANK_BACK = os.path.join(
    os.path.dirname(SCRIPT_ROOT_DIR), "books", "dyreparken", "blank-back(dyreparken).png"
)
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
TEXT_BOX_TOP = 135
TEXT_BOX_BOTTOM = 895
TEXT_Y_OFFSET_SCALE = 0.18
TEXT_SHADOW_ALPHA = 110
TEXT_SHADOW_BLUR = 3

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
#  FORSIDE-TITTEL – hvit navnetekst + Dyreparken-logo
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


def crop_logo_to_visible_alpha(logo_img, alpha_threshold=8):
    logo_rgba = logo_img.convert("RGBA")
    alpha = logo_rgba.getchannel("A")
    bbox = alpha.point(lambda p: 255 if p > alpha_threshold else 0).getbbox()
    if bbox:
        return logo_rgba.crop(bbox)
    return logo_rgba


def resolve_front_cover_logo(base_dir: str | None = None) -> str | None:
    """Resolve the cover logo from C:/DreamPage-OS/assets/logo/<locale>."""
    candidates = [
        os.path.join(LOGO_DIR, "dyreparken-logo.png"),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return None

def draw_centered_title_cover(img, text, base_dir: str | None = None):
    """
    Forside:
    - Linje 1: hvit navnetekst
    - Linje 2: Dyreparken-logo fra script/logo/<locale>
    """
    draw = ImageDraw.Draw(img)
    w, h = img.size
    base = min(w, h)

    lines = text.split("\n")
    line1 = lines[0] if len(lines) > 0 else ""

    font_small = ImageFont.truetype(COVER_TITLE_FONT, int(min(img.size) * 0.08))
    text_color = (255, 255, 255, 255)
    shadow = (20, 30, 20)

    def _make_text_mask(size, x, y, t, fnt):
        mask = Image.new("L", size, 0)
        d = ImageDraw.Draw(mask)
        d.text((x, y), t, font=fnt, fill=255)
        return mask

    size_large = int(base * 0.10)
    shadow_offset = max(3, int(size_large * 0.04))

    def text_size(t, f):
        if not t:
            return 0, 0
        bbox = draw.textbbox((0, 0), t, font=f)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    w1, h1 = text_size(line1, font_small)

    top_y = int(h * 0.020)
    spacing = int(h * 0.027)

    x1 = (w - w1) // 2
    y1 = top_y

    descender_cut = int(h1 * 0.15) if h1 else 0
    y2 = y1 + h1 - descender_cut + spacing

    def draw_white_line(t, fnt, x, y):
        if not t:
            return

        sm = _make_text_mask(img.size, x + shadow_offset, y + shadow_offset, t, fnt)
        sm = sm.filter(ImageFilter.GaussianBlur(max(1, shadow_offset // 2)))
        img.paste((*shadow, 210), (0, 0), sm)

        draw.text((x, y), t, font=fnt, fill=text_color)

    draw_white_line(line1, font_small, x1, y1)

    logo_path = resolve_front_cover_logo(base_dir)
    if not logo_path:
        print("ADVARSEL: Fant ikke dyreparken-logo.png")
        return

    logo = Image.open(logo_path).convert("RGBA")
    logo = crop_logo_to_visible_alpha(logo, alpha_threshold=8)

    target_w = int(w * 0.62)
    target_h = int(logo.height * (target_w / logo.width))
    logo = logo.resize((target_w, target_h), Image.LANCZOS)

    lx = (w - target_w) // 2
    ly = y2 + int(h * 0.025)

    shadow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    logo_alpha = logo.split()[3]
    shadow_img = Image.new("RGBA", (target_w, target_h), (*shadow, 165))
    shadow_img.putalpha(logo_alpha)
    shadow_layer.paste(shadow_img, (lx + shadow_offset, ly + shadow_offset))
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(max(8, int(target_h * 0.08))))
    img.alpha_composite(shadow_layer)
    img.alpha_composite(logo, (lx, ly))


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

def build_pages_dinosaur_legacy(child_name: str) -> List[Dict[str, Any]]:
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
            "filename": "forside(dinosaur).png",
            "type": "cover",
            "text": p("[NAVN] og\nDinosaurenes dal"),
        },
        {
            "filename": "ryggrad.png",
            "type": "cover",
        },

        {
           "type": "blank",
           "side": "right",
           "text": p("[NAVN] og\nDinosaurenes dal"),
           "blocks": [{
                "text": p(
                    "Takk for at du kjøpte denne personlige historien!\n"
                    "I denne boken følger vi (Navn) på et eventyr i en magisk dal."
                    "(Navn) lærer seg og si ifra når noe ikke er greit.\n"
                    "Vi håper historien bringer glede, trygghet og fantasifulle øyeblikk."
                ),
                "font_size": 42,
                "color": "#111111",
                "y_offset": 420,
      
           }]
        },


        # Side 1
        {
            "filename": "01(dinosaur).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Det var en stille og fin dag. (Navn) sto ute og så seg rundt.\n"
                    "Luften var frisk, og naturen lå åpen foran ham.\n"
                    "Alt føltes rolig og trygt.\n"
                    "(Navn) visste det ikke ennå, men denne dagen skulle bli helt annerledes enn alle andre."
                
                    
                ),
                "font_size": 34,
                 "color": "#000000",
                "highlights": [child_name, "annerledes"],
        
            }],
        },

        # Side 2
        {
            "filename": "02(dinosaur).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "(Navn) gikk videre innover stien. Da fikk han øye på noe uvanlig.\n"
                    "Midt blant steiner og blader lå et egg som glødet svakt.\n"
                    "Lyset blinket i grønne og gylne farger.\n"
                    "(Navn) satte seg forsiktig ned. Hva kunne dette være?"
                    
                ),
                "font_size": 34,
                "color": "#FFFFFF",
                "highlights": [child_name, "uvanlig", "glødet"],
                
          

            }],
        },
	
	# Side 3
        {
            "filename": "03(dinosaur).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
	            "(Navn) så nærmere på egget.\n"
		    "Lyset ble sterkere, og bakken rundt begynte å gløde svakt.\n"
    		    "Steinene foran ham lyste opp i en rund form.\n"
                    "(Navn) trakk pusten dypt.\n"
                    "Det var ikke bare et egg.\n"
                    "Det var noe mer."

                ),
                "font_size": 34,
                "color": "#000000",
                "highlights": [child_name, "sterkere", "gløde"],
               # "y_offset": 120,
               # "x_offset": 20
            }],
        },

	# Side 4
        {
            "filename": "04(dinosaur).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "(Navn) reiste seg sakte.\n"
                    "Han tok noen forsiktige steg frem.\n"
                    "Den lysende sirkelen var stille, men levende.\n"
                    "Luften rundt kjentes varm og myk.\n"
                    "(Navn) løftet hånden.\n"
                    "Hva ville skje hvis han rørte den?"

                ),
                "font_size": 34,
                "color": "#000000",
                "highlights": [child_name, "lysende", "levende"],
               # "y_offset": 120,
               # "x_offset": 20
            }],
        },
        # Side 5
        {
            "filename": "05(dinosaur).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Da (Navn) rørte den lysende sirkelen, skjedde det noe.\n"
                    "Lyset begynte å bevege seg sakte.\n"
                    "Små gnister danset rundt hånden hans.\n"
                    "Luften summet lavt, som om portalen våknet.\n"
                    "(Navn) trakk pusten dypt. Dette var begynnelsen på noe nytt."
                 
                ),
                "font_size": 34,
                "color": "#000000",
                "highlights": [child_name, "gnister", "portalen"],
               # "y_offset": 120,
               # "x_offset": 20
            }],
        },

        # Side 6
        {
            "filename": "06(dinosaur).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "(Navn) tok et forsiktig steg frem. Foran ham lå Dinosaurdalen.\n"
                    "Høye fjell og fosser strakte seg rundt ham. Store skygger beveget seg i det fjerne.\n"
                    "Dette var et helt nytt sted. Og eventyret hadde så vidt begynt."
                    
                ),
                "font_size": 34,
                "color": "#FFFFFF",
                "highlights": [child_name, "Dinosaurdalen", "eventyret"],
            }],
        },

        # Side 7
        {
            "filename": "07(dinosaur).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Dinosauren kom rolig nærmere. Den var stor, men så snill ut.\n"
                    "«Jeg heter Lumo,» sa den lavt. «Jeg trenger hjelp.»\n"
                    "(Navn) nølte litt – så tok han et steg frem."
                   

                ),
                "font_size": 36,
                "color": "#FFFFFF",
                "highlights": [child_name, "Lumo", "hjelp"],
            }],
        },

        # Side 8
        {
            "filename": "08(dinosaur).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Plutselig begynte dinosauren å løpe. Den snudde seg og så på (Navn).\n"
                    "«Kom!» sa den vennlig. «Jeg trenger hjelpen din.»\n"
                    "(Navn) nølte litt. Så begynte han å løpe etter."
              

                ),
                "font_size": 34,
                "color": "#FFFFFF",
                "highlights": [child_name, "hjelpen"],
            }],
        },

        # Side 9
        {
            "filename": "09(dinosaur).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "(Navn) gikk ved siden av dinosauren. Stien var smal og stille.\n"
                    "«Hva trenger du hjelp med?» spurte (Navn). Dinosauren ristet på hodet.\n"
                    "«Jeg kan ikke si det,» sa den lavt. «Jeg må vise deg.»\n"
                    "De gikk videre sammen."
                   
                ),
                "font_size": 34,
                "color": "#000000",
                "highlights": [child_name, "hjelp", "sammen"],
            
            }],
        },

        # Side 10
        {
            "filename": "10(dinosaur).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Plutselig stoppet dinosauren. Øynene ble store.\n"
                    "«Å nei… der er han,» hvisket den. «Det er den jeg snakket om.»\n"
                    "Den pekte mot den store dinosauren. «Han har vært slem mot de andre.»\n"
                    "Den så på (Navn). «Det er han jeg trenger hjelp med.»"
                


                ),
                "font_size": 34,
                "color": "#FFFFFF",
                "highlights": [child_name, "slem", "hjelp"],
             
            }],
        },

        # Side 11
        {
            "filename": "11(dinosaur).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "(Navn) tok et steg frem. Hjertet banket fort, men han sto støtt.\n"
                    "«Du må slutte,» sa han rolig. «Det er ikke greit å være slem.»\n"
                    "T-rexen stoppet opp. Ingen hadde sagt det til ham før."
  

                ),
                "font_size": 34,
                "color": "#FFFFFF",
                "highlights": [child_name, "slem", "støtt"],
             
            }],
        },

        # Side 12
        {
            "filename": "12(dinosaur).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "T-rexen senket hodet. «Jeg forsto ikke at jeg gjorde vondt,» sa han lavt.\n"
                    "Han snudde seg sakte. Denne gangen uten brøl.\n"
                    "Og med tunge steg gikk han rolig sin vei."
                   
           
                ),
                "font_size": 34,
                "color": "#FFFFFF",
                "highlights": ["vondt", "rolig"],

            }],
        },

        # Side 13
        {
            "filename": "13(dinosaur).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "(Navn) og Lumi sto stille sammen. De så utover dalen der de andre dinosaurene levde i fred.\n"
                    "Lumi smilte forsiktig. Og (Navn) kjente seg varm og stolt inni seg.\n"
                    "De hadde gjort noe viktig – sammen."
                    
                
                ),
                "font_size": 36,
                "color": "#000000",
                "highlights": [child_name, "viktig", "stolt"],
   
            }],
        },

        # Side 14
        {
            "filename": "14(dinosaur).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Solen var i ferd med å gå ned. (Navn) visste at det var på tide å dra hjem.\n"
                    "Lumi så på ham og nikket stille. «Du vil alltid være en venn,» sa han.\n"
                    "(Navn) vinket farvel. Og med et smil tok han steget tilbake til sin egen verden."
        
                ),
                "font_size": 35,
                "color": "#FFFFFF",
                "highlights": [child_name, "venn"],
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
            "filename": "bakside(dinosaur).png",
            "type": "cover",
            "side": "left",
            "blocks": [{
                "text": p(
               
                    "Denne boken handler om mot. Om å tørre å si ifra når noe er urettferdig – selv når det føles litt skummelt.\n"
                    "Gjennom et magisk møte i Dinosaurdalen lærer (Navn) at ekte styrke ikke handler om å være størst eller sterkest, men om å være snill, modig og å bry seg om andre.\n"
                    "En varm og personlig historie som viser barn at én stemme kan gjøre en stor forskjell. Og at vennskap kan oppstå på de mest uventede steder.\n"
                    "En bok som gir trygghet, selvtillit – og minner barnet på at også de kan være en helt."
                 
                
                ),
                "font_size": 46,
                "color": "#FFFFFF",
                "highlights": [child_name, "Påskedalen", "hemmelige", "påskeskatten", "påskemagi", "barnet", "skattejakt", "modigere", "våge"],
               
            }],
        },


     ] 


    return pages


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
            "filename": "forside(dyreparken).png",
            "type": "cover",
            "text": p("[NAVN] i\nDyreparken"),
        },
        {
            "filename": "ryggrad.png",
            "type": "cover",
        },
        {
            "type": "blank",
            "side": "right",
            "text": p("[NAVN] i\nDyreparken"),
            "blocks": [{
                "text": p(
                    "Takk for at du kjøpte denne personlige historien!\n"
                    "I denne boken følger vi (Navn) på et spennende eventyr i dyreparken.\n"
                    "Her møter (Navn) dyr som trenger litt hjelp - og oppdager hvor langt vennlighet kan rekke.\n"
                    "Vi håper historien skaper varme, undring og fine lesestunder."
                ),
                "font_size": 42,
                "color": "#111111",
                "y_offset": 420,
            }],
        },
        {
            "filename": "01(dyreparken).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "\"Endelig er dagen her,\" sa (Navn) og smilte ved porten.\n"
                    "Bak inngangen ventet svingete stier, rare dyrelyder og lukten av varmt gress.\n"
                    "Alt kjentes nesten magisk, som om parken hadde våknet akkurat for ham.\n"
                    "Så hvisket vinden mellom trærne: Velkommen til dyreparken. Et eventyr venter."
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name, "eventyr", "dyreparken"],
            }],
        },
        {
            "filename": "02(dyreparken).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "(Navn) gikk videre og fikk øye på en høy giraff.\n"
                    "Den bøyde den lange halsen ned og smilte vennlig.\n"
                    "\"Hallo der nede,\" sa giraffen. \"Kan du hjelpe oss i dag?\"\n"
                    "\"Ja!\" svarte (Navn) uten å nøle."
                ),
                "font_size": 31,
                "color": "#FFFFFF",
                "highlights": [child_name, "giraffen", "hjelpe"],
                "y_offset": 260,
            }],
        },
        {
            "filename": "03(dyreparken).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Giraffen kom helt nær og senket stemmen, som om den delte en viktig hemmelighet.\n"
                    "\"Elefanten trenger hjelp først,\" sa den. \"Han prøver å nå de beste bladene, men de sitter for høyt.\"\n"
                    "(Navn) kjente hjertet hoppe av spenning. \"Da går jeg med en gang,\" sa han, og satte fart langs stien."
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name, "elefanten", "hjelp"],
                "y_offset": 260,
            }],
        },
        {
            "filename": "04(dyreparken).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "(Navn) skyndte seg langs stien mot elefantens område.\n"
                    "Solen glitret i vannet, og bladene raslet over ham som små grønne flagg.\n"
                    "Han fulgte de tunge fotsporene i sanden og ropte: \"Jeg kommer, elefant!\"\n"
                    "Nå var eventyret virkelig i gang."
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name, "elefant", "eventyret"],
                "y_offset": 250,
            }],
        },
        {
            "filename": "05(dyreparken).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Ved gjerdet sto elefanten og løftet snabelen håpefullt mot de grønne greinene.\n"
                    "(Navn) samlet friske blader, strakte seg så langt han kunne og rakte dem forsiktig frem.\n"
                    "Elefanten tok imot med snabelen og blunket takknemlig. \"Tusen takk,\" sa den. \"Du reddet dagen min.\""
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name, "elefanten", "reddet", "hjelper"],
                "y_offset": 255,
            }],
        },
        {
            "filename": "06(dyreparken).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Da elefanten var glad igjen, gikk (Navn) videre med lette steg.\n"
                    "Ved vannet ventet en zebra som stampet urolig med hoven og så nedover stien.\n"
                    "\"Jeg finner ikke veien tilbake til flokken min,\" sa zebraen. \"Kan du hjelpe meg også?\"\n"
                    "\"Selvfølgelig,\" sa (Navn). \"Vi finner dem sammen.\""
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name, "zebra", "hjelpe"],
                "y_offset": 250,
            }],
        },
        {
            "filename": "07(dyreparken).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Zebraen satte fart, og (Navn) sprang ved siden av så godt han kunne.\n"
                    "De fulgte små spor i sanden, forbi busker og rundt en dam som glitret i solen.\n"
                    "Til slutt fant zebraen flokken sin igjen. \"Nå går alt bra,\" sa den lykkelig. (Navn) lo. \"Vi er et godt team.\""
                ),
                "font_size": 28,
                "color": "#FFFFFF",
                "highlights": [child_name, "zebraen", "sammen", "team"],
                "x_offset": 80,
                "width_offset": 80,
                "y_offset": 255,
            }],
        },
        {
            "filename": "08(dyreparken).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Til slutt kom (Navn) til løven, som satt fast bak en tung gren.\n"
                    "(Navn) tok tak og skjøv så godt han kunne.\n"
                    "\"Du er modigere enn mange voksne,\" sa løven da veien ble fri.\n"
                    "\"Jeg ville bare hjelpe,\" sa (Navn)."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "løven", "modigere", "hjelpe"],
                "width_offset": -80,
                "y_offset": 255,
            }],
        },
        {
            "filename": "09(dyreparken).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Da oppdragene var ferdige, kom alle dyrene bort til (Navn).\n"
                    "\"Du hjalp oss alle,\" sa giraffen.\n"
                    "\"Du er vår venn nå,\" sa elefanten, mens zebraen nikket og løven brummet mykt.\n"
                    "(Navn) kjente seg varm av glede."
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name, "venn", "giraffen", "dyrene"],
                "y_offset": 250,
            }],
        },
        {
            "filename": "10(dyreparken).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "(Navn) løftet hånden og vinket til alle de nye vennene sine.\n"
                    "\"Ha det!\" ropte han, selv om stemmen ble litt myk av savn.\n"
                    "\"Kom tilbake en dag,\" ropte dyrene tilbake, én etter én.\n"
                    "Det var trist å gå, men hjertet hans var fullt av lys og varme minner."
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name, "dyrene", "tilbake", "lys"],
            }],
        },
        {
            "filename": "11(dyreparken).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Et stykke borte snudde (Navn) seg en siste gang.\n"
                    "I sollyset så det nesten ut som om dyrene smilte til ham fra det fjerne.\n"
                    "Han la hånden mot brystet og kjente hvor glad han var blitt i dem.\n"
                    "Dette var et farvel som ikke føltes helt som et farvel."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "farvel", "dyrene"],
            }],
        },
        {
            "filename": "12(dyreparken).png",
            "type": "inner",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Ved stien glitret noe lite i kveldssolen.\n"
                    "(Navn) bøyde seg ned og fant en liten elefantfigur i grusen.\n"
                    "\"Et minne fra oss,\" var det nesten som vinden hvisket.\n"
                    "\"Da glemmer jeg dere aldri,\" sa (Navn) stille."
                ),
                "font_size": 30,
                "color": "#FFFFFF",
                "highlights": [child_name, "elefantfigur", "minne", "aldri"],
                "y_offset": 255,
            }],
        },
        {
            "filename": "13(dyreparken).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Solen sank lavt mens (Navn) gikk hjemover.\n"
                    "Bak porten lå dyreparken stille, og foran ham ventet huset med varme lys.\n"
                    "Han holdt elefantfiguren tett og visste det i hele hjertet sitt:\n"
                    "Eventyret var ikke helt over."
                ),
                "font_size": 31,
                "color": "#FFFFFF",
                "highlights": [child_name, "dyreparken", "varme", "eventyret"],
                "y_offset": 220,
            }],
        },
        {
            "filename": "14(dyreparken).png",
            "type": "inner",
            "side": "right",
            "blocks": [{
                "text": p(
                    "Før (Navn) sovnet, så han bort på den lille elefanten ved lampen.\n"
                    "Rommet var stille, men han syntes nesten han kunne høre et mykt brøl og et vennlig tramp.\n"
                    "Kanskje, tenkte han, venter dyrevennene på meg igjen i morgen.\n"
                    "Og med det sovnet han med et smil."
                ),
                "font_size": 29,
                "color": "#FFFFFF",
                "highlights": [child_name, "elefanten", "dyrevennene", "smil"],
                "y_offset": 190,
            }],
        },
        {
            "filename": "blank-back.png",
            # Bildet hentes fra script/lastpages/<locale>/, men siden må hete
            # blank-back.png ut - dream_pdf_guard dropper alt som heter Lastpage*.
            "source": "Lastpage(dyreparken).png",
            "type": "inner",
            "side": "left",
            "blank_only": True
        },
        {
            "filename": "bakside(dyreparken).png",
            "type": "cover",
            "side": "left",
            "blocks": [{
                "text": p(
                    "Denne boken handler om små handlinger som betyr mye.\n"
                    "Når (Navn) går inn i dyreparken, venter et varmt og spennende eventyr bak hver sving. "
                    "En giraff ber om hjelp, en elefant blir lettet, en zebra finner smilet igjen, og en løve oppdager hva ekte vennskap er.\n"
                    "Gjennom møtene lærer (Navn) at omtanke, mot og vennlighet kan gjøre en stor forskjell.\n"
                    "En personlig historie fylt med dyreglede, nærhet og minner som varer lenge etter siste side."
                ),
                "font_size": 44,
                "color": "#FFFFFF",
                "highlights": [child_name, "dyreparken", "omtanke", "mot", "vennlighet", "vennskap"],
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
    import dream_text_layout as TEXT_LAYOUT
except Exception as exc:
    print("Kunne ikke laste felles tekstlayout:", exc)
    TEXT_LAYOUT = None


def _color_luminance(color: Any) -> float:
    if isinstance(color, str) and color.startswith("#") and len(color) >= 7:
        try:
            r = int(color[1:3], 16)
            g = int(color[3:5], 16)
            b = int(color[5:7], 16)
            return 0.2126 * r + 0.7152 * g + 0.0722 * b
        except ValueError:
            pass
    if isinstance(color, tuple) and len(color) >= 3:
        r, g, b = color[:3]
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    return 255


def _shadow_fill_for(color: Any) -> tuple[int, int, int, int]:
    if _color_luminance(color) > 150:
        return (0, 0, 0, TEXT_SHADOW_ALPHA)
    return (255, 255, 255, 85)


def _centered_text_box(draw, text, box, font, line_spacing, highlights):
    if TEXT_LAYOUT is None or not hasattr(TEXT_LAYOUT, "_layout_text"):
        return box

    x1, y1, x2, y2 = box
    max_height = y2 - y1
    current_font = font
    current_spacing = line_spacing

    _, total_height = TEXT_LAYOUT._layout_text(
        draw, text, box, current_font, current_spacing, highlights
    )

    min_size = max(16, int(font.size * 0.78))
    while total_height > max_height and current_font.size > min_size:
        next_size = current_font.size - 1
        current_font = TEXT_LAYOUT._load_font_like(current_font, next_size)
        current_spacing = max(3, int(line_spacing * (next_size / max(font.size, 1))))
        _, total_height = TEXT_LAYOUT._layout_text(
            draw, text, box, current_font, current_spacing, highlights
        )

    top = y1 + max(0, int((max_height - total_height) / 2))
    return (x1, top, x2, y2)


def draw_story_text(draw, text, box, font,
                    color=TEXT_COLOR,
                    stroke_color=STROKE_COLOR,
                    line_spacing=10,
                    highlights=None,
                    gradient=None,
                    img=None,
                    align="left",
                    shadow=True,
                    shadow_offset=3,
                    shadow_blur=TEXT_SHADOW_BLUR,
                    vertical_align="center"):
    base_draw_text = TEXT_LAYOUT.draw_text if TEXT_LAYOUT is not None else draw_text

    if vertical_align == "center":
        box = _centered_text_box(draw, text, box, font, line_spacing, highlights)

    if shadow and img is not None and gradient is None:
        shadow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        shadow_box = (
            box[0] + shadow_offset,
            box[1] + shadow_offset,
            box[2] + shadow_offset,
            box[3] + shadow_offset,
        )
        shadow_fill = _shadow_fill_for(color)
        shadow_kwargs = dict(
            draw=shadow_draw,
            text=text,
            box=shadow_box,
            font=font,
            color=shadow_fill,
            stroke_color=shadow_fill,
            line_spacing=line_spacing,
            highlights=highlights,
            gradient=None,
            img=shadow_layer,
            align=align,
        )
        if TEXT_LAYOUT is not None:
            shadow_kwargs["shadow"] = False
        base_draw_text(**shadow_kwargs)
        if shadow_blur > 0:
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(shadow_blur))
        img.alpha_composite(shadow_layer)

    text_kwargs = dict(
        draw=draw,
        text=text,
        box=box,
        font=font,
        color=color,
        stroke_color=stroke_color,
        line_spacing=line_spacing,
        highlights=highlights,
        gradient=gradient,
        img=img,
        align=align,
    )
    if TEXT_LAYOUT is not None:
        text_kwargs["shadow"] = False
    base_draw_text(**text_kwargs)


# ------------------------ ryggrad per språk (script/ryggrad/<book-slug>/) ------------------------
RYGGRAD_BOOK_SLUG = "dyreparken"
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

    # ------------------------ EKSTRA BLANK SISTE INNERSIDE ------------------------
    if page.get("blank_only"):
        # Lastpage(*).png hentes fra script/lastpages/<locale>/ (per bok, per språk).
        # Legacy blank-back.png ligger fortsatt ved siden av scriptet og deles av
        # flere bøker - den må ikke byttes ut her.
        source_name = page.get("source") or page["filename"]

        # Ordrens egen siste side ("Fortsett eventyret"-siden med QR) vinner over
        # alt. prepare_order kopierer ALLTID den delte blank-back.png inn i
        # ordren, saa eksistens alene sier ingenting - bare en fil som SKILLER
        # seg fra malen er en ekte fortsett-side (se build_last_page.py).
        blank_path = None
        order_last_page = os.path.join(base_dir, "blank-back.png")
        shared_blank_back = os.path.join(SCRIPT_DIR, "blank-back.png")
        if os.path.exists(order_last_page) and not (
            os.path.exists(shared_blank_back)
            and filecmp.cmp(order_last_page, shared_blank_back, shallow=False)
        ):
            print("[INNER PDF] Fortsett-eventyret-siden erstatter siste side:", order_last_page)
            blank_path = order_last_page
        elif os.path.exists(DYREPARKEN_BLANK_BACK):
            blank_path = DYREPARKEN_BLANK_BACK

        if blank_path is not None:
            pass
        elif os.path.basename(source_name).lower().startswith("lastpage"):
            blank_path = os.path.join(LASTPAGE_DIR, source_name)
            if not os.path.exists(blank_path):
                fallback = os.path.join(SCRIPT_ROOT_DIR, "lastpages", "nb", source_name)
                if os.path.exists(fallback):
                    print("ADVARSEL: Fant ikke " + source_name + " i " + LASTPAGE_DIR + " - bruker nb")
                    blank_path = fallback
        else:
            blank_path = os.path.join(SCRIPT_DIR, source_name)

        if not os.path.exists(blank_path):
            print("Fant ikke siste innerside:", blank_path)
            return []

        img = Image.open(blank_path)

        out_path = os.path.join(out_dir, page["filename"])
        os.makedirs(out_dir, exist_ok=True)
        img.save(out_path)

        print("Lagret blank-back som siste innerside:", out_path)
        return [out_path]


    # ------------------------ blank side ------------------------
    if page.get("type") == "blank":
        blank_path = DYREPARKEN_DREAMPAGE_FIRST if os.path.exists(DYREPARKEN_DREAMPAGE_FIRST) else os.path.join(SCRIPT_DIR, "dreampage-first.png")

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
        # Samme oppsett som de andre bokene sine apningssider: storrelsen kommer
        # fra blokken og skaleres med siden, luften mellom linjene folger
        # skriften (0.52) slik at avsnittsskillene faktisk leses som skiller,
        # og boksen er smal nok til at hvert avsnitt brekker i to jevne linjer
        # i stedet for en lang og en kort. Ingen skygge - sida er lys.
        for block in page.get("blocks", []):
            base_size = block.get("font_size", 42)
            font_size = int(base_size * min(scale_x, scale_y))
            font = ImageFont.truetype(INNER_FONT, font_size)
            line_spacing = int(font_size * 0.52)

            box = (
                int(img_w * 0.19),
                int(img_h * 0.32),
                int(img_w * 0.81),
                int(img_h * 0.72),
            )

            draw_text(
                draw=draw,
                text=block["text"],
                box=box,
                font=font,
                color=block.get("color", "#111111"),
                line_spacing=line_spacing,
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
        _dpf_ty = int(img_h * 0.79) - _dpf_tag_total // 2
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

            draw_story_text(
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
        effective_y_offset = y_offset if block.get("text_backdrop", False) else int(y_offset * TEXT_Y_OFFSET_SCALE)
        by1 = sy(TEXT_BOX_TOP + effective_y_offset)
        by2 = sy(TEXT_BOX_BOTTOM)

        box = (bx1, by1, bx2, by2)

        text_line_spacing = max(4, int(14 * scale))
        if block.get("text_backdrop", False):
            draw_text_backdrop(img, box, block["text"], font, text_line_spacing, highlights=block.get("highlights", []), strength=block.get("text_backdrop_strength", "normal"))


        # ✅ Gradient er default. Slå av per blokk med: "use_gradient": False
        use_gradient = "color" not in block


        draw_story_text(
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
            shadow_offset=max(2, int(3 * scale)),
            shadow_blur=max(1, int(TEXT_SHADOW_BLUR * scale)),
            vertical_align="top",
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
    need = ["bakside(dyreparken).png", "ryggrad.png", "forside(dyreparken).png"]
    missing = [n for n in need if n not in cover_rendered]

    if missing:
        print("Cover PDF ble IKKE laget. Mangler rendret cover-del(er):", ", ".join(missing))
        return

    back_path  = cover_rendered["bakside(dyreparken).png"]
    spine_path = cover_rendered["ryggrad.png"]
    front_path = cover_rendered["forside(dyreparken).png"]

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

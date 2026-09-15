# -*- coding: utf-8 -*-
"""Bygger fotball-vm-text-<locale>.py fra fotballstjernen-malene i script/<locale>/.

Malen er bok 1 i samme serie: den har allerede bakside-skyggen
(draw_text_backdrop med shape="block"), kvadratside-stotten og
forsidetittel som linje1-tekst + linje2-LOGO med glod.

Idempotent: kjor den om igjen naar som helst, den skriver hele fila paa nytt.

  python build_fotball_vm.py            # bare staging i script/out/
  python build_fotball_vm.py --apply    # skriver til C:/ComfyUI/script/<locale>/
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from story_fotball_vm import (  # noqa: E402
    COVER_NB, BACK_NB, BACK_HL, PAGES_NB, TRANSLATIONS,
)

SCRIPT_ROOT = r"C:\ComfyUI\script"
SRC_NAME = "fotballstjernen-text-%s.py"
DST_NAME = "fotball-vm-text-%s.py"
LOCALES = ["nb", "nn", "en-US", "en-GB", "sv"]
APPLY = "--apply" in sys.argv
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

# Side 12 er kvadratparet. Venstre kvadrat er comfy-headswappen (barnet i
# glideturneringen) og skal vaere ren; teksten staar paa hoyre kvadrat, som er
# et statisk bilde. Boksen gaar nesten fra kant til kant og ligger i nedre
# halvdel, over gresset - der er det ingenting som blir dekket til.
SQUARE_INDEX = 12                     # 1-basert sidenummer i PAGES_NB
SQUARE_BOX_FRAC = [0.07, 0.66, 0.93, 0.98]


def pylit(text, indent):
    """Kildetekst -> "...\\n" per linje, slik malene skriver den."""
    lines = text.split("\n")
    out = []
    for i, line in enumerate(lines):
        esc = line.replace("\\", "\\\\").replace('"', '\\"')
        suffix = "\\n" if i < len(lines) - 1 else ""
        out.append(" " * indent + '"' + esc + suffix + '"')
    return "\n".join(out)


def hl_list(words):
    return "[child_name, " + ", ".join('"%s"' % w for w in words) + "]"


def _inner_block(text, hls):
    b = []
    b.append('            "blocks": [{')
    b.append('                "text": p(')
    b.append(pylit(text, 20))
    b.append("                ),")
    b.append('                "font_size": 30,')
    b.append('                "color": "#FFFFFF",')
    b.append('                "highlights": %s,' % hl_list(hls))
    b.append("            }],")
    return b


def build_pages_block():
    b = []
    b.append("    pages: List[Dict[str, Any]] = [")
    b.append("        {")
    b.append('            "filename": "forside(fotball-vm).png",')
    b.append('            "type": "cover",')
    b.append('            "text": p("%s"),' % COVER_NB.replace("\n", "\\n"))
    b.append("        },")
    b.append("        {")
    b.append('            "filename": "ryggrad.png",')
    b.append('            "type": "cover",')
    b.append("        },")
    b.append("")

    for idx, (side, text, hls) in enumerate(PAGES_NB, start=1):
        if idx == SQUARE_INDEX:
            b.append("        # Side %d - venstre kvadrat (comfy-headswap, ingen tekst)" % idx)
            b.append("        {")
            b.append('            "filename": "%02d(fotball-vm-left).png",' % idx)
            b.append('            "type": "inner",')
            b.append('            "square": True,')
            b.append('            "blocks": [],')
            b.append("        },")
            b.append("")
            b.append("        # Side %d - hoyre kvadrat (statisk bilde, baerer teksten)" % idx)
            b.append("        {")
            b.append('            "filename": "%02d(fotball-vm-right).png",' % idx)
            b.append('            "type": "inner",')
            b.append('            "square": True,')
            b.append('            "side": "right",')
            b.append('            "no_split": True,')
            b.append('            "box_frac": %s,' % SQUARE_BOX_FRAC)
            b.extend(_inner_block(text, hls))
            b.append("        },")
            b.append("")
            continue

        b.append("        # Side %d" % idx)
        b.append("        {")
        b.append('            "filename": "%02d(fotball-vm).png",' % idx)
        b.append('            "type": "inner",')
        b.append('            "side": "%s",' % side)
        b.extend(_inner_block(text, hls))
        b.append("        },")
        b.append("")

    b.append("        # Bakside")
    b.append("        {")
    b.append('            "filename": "bakside(fotball-vm).png",')
    b.append('            "type": "cover",')
    b.append('            "side": "left",')
    b.append('            "blocks": [{')
    b.append('                "text": p(')
    b.append(pylit(BACK_NB, 20))
    b.append("                ),")
    b.append('                "font_size": 46,')
    b.append('                "color": "#FFFFFF",')
    b.append('                "highlights": %s,' % hl_list(BACK_HL))
    b.append("            }],")
    b.append("        },")
    b.append("    ]")
    return "\n".join(b) + "\n"


def keys_nb():
    """Kildenoklene i samme rekkefolge som verdiene i TRANSLATIONS."""
    to_key = lambda t: t.replace("(Navn)", "{name}")
    return [to_key(COVER_NB)] + [to_key(t) for _, t, _ in PAGES_NB] + [to_key(BACK_NB)]


def translation_block(locale):
    cover, pages, back = TRANSLATIONS[locale]
    values = [cover] + list(pages) + [back]
    keys = keys_nb()
    assert len(keys) == len(values) == 16, (len(keys), len(values))
    lines = ["_DREAMPAGE_TRANSLATIONS = {"]
    for k, v in zip(keys, values):
        lines.append("  %s: %s," % (repr(k).lstrip("u"), repr(v).lstrip("u")))
    lines.append("}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
#  Blokker som settes inn i malen
# --------------------------------------------------------------------------

# Forsiden: samme renderer som DP Title Tester (render-title-line2logo.py), med
# verdiene fra Set-noden "fotball-vm" / config/next_book_titles.json lagt ut som
# konstanter. Fontstorrelsene er andeler av kortsiden slik at de folger
# oppskaleringen fra 1024-malen til 4096-utskriften.
COVER_BLOCK = '''# ---------------------------------------------------------------------------
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
    lines = (text or "").split("\\n")
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


def draw_gradient_word('''

# Hoyre kvadrat maa trekkes inn i sidens EGET koordinatrom - 1328/1861 er
# koordinater i par-rommet (to sider = 2048). Malen brukte aldri hoyre
# kolonne paa en kvadratside, saa feilen har ligget der ubrukt.
SQRIGHT_OLD = "SQ_RIGHT_X1, SQ_RIGHT_X2 = 1328, 1861"
SQRIGHT_NEW = "SQ_RIGHT_X1, SQ_RIGHT_X2 = 1328 - SQUARE_DESIGN, 1861 - SQUARE_DESIGN"

# box_frac lar en kvadratside sette tekstboksen eksplisitt (andeler av bildet)
# naar motivet ikke gir plass i standardkolonnen.
BOXFRAC_OLD = '''    y = sq(MARGIN_Y + 150)
    for block in page.get("blocks", []):
        base_size = block.get("font_size", DEFAULT_FONT_SIZE)
        font_size = max(8, int(base_size * s))
        font = ImageFont.truetype(INNER_FONT, font_size)

        bx1 = x1 + sq(block.get("x_offset", 0))
        bx2 = x2 + sq(block.get("width_offset", 0))
        by1 = y + sq(block.get("y_offset", 0))
        by2 = sq(SQUARE_DESIGN - 80)
        box = (bx1, by1, bx2, by2)'''
BOXFRAC_NEW = '''    y = sq(MARGIN_Y + 150)
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
        box = (bx1, by1, bx2, by2)'''

# no_split: hopp over den automatiske to-blokk-splitten. Den regner i
# 1536x1024-rommet og gir bare mening for oppslag.
NOSPLIT_OLD = '''    block = blocks[0]
    split = _dp_balanced_story_split(block.get("text", ""))'''
NOSPLIT_NEW = '''    block = blocks[0]
    if page.get("no_split") or page.get("square"):
        _dp_mark_backdrop(block, filename, child_name)
        return

    split = _dp_balanced_story_split(block.get("text", ""))'''

# Innersidene: boka har ingen endetekst-side og ingen Lastpage (det finnes
# ingen bok 3 enda), saa blank-back legges rett bakerst.
ASSEMBLY_OLD_RE = (
    r'    last_page = resolve_lastpage_path\("Lastpage\(fotball\)\.png"\)'
    r".*?hopper over\"\)\n"
)
ASSEMBLY_NEW = '''    if os.path.exists(dreampage_first):
        rendered_first = render_dreampage_first(child_name, out_dir)
        inner_paths.insert(0, rendered_first)
    else:
        print("ADVARSEL: Fant ikke dreampage-first.png")
    if os.path.exists(blank_back):
        inner_paths.append(blank_back)
    else:
        raise FileNotFoundError("Fant ikke blank-back.png i script-mappen")
'''


# Malens per-side-finjusteringer (topp/bunn-offset og "strong" bakgrunnsplate)
# ble tunet mot bok 1 sine bilder. Fotball-VM har helt andre motiv, saa vi
# starter noytralt - juster per side senere om noe kolliderer.
LAYOUT_OFFSETS_OLD = """    top_y = 25
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
    if number == 14:
        top_y = -25
    return number, top_y, bottom_y"""
LAYOUT_OFFSETS_NEW = """    top_y = 25
    bottom_y = 345
    if number == 13:
        # VM-pokalen staar midt paa venstresida (y 0.24-0.62). Toppblokken
        # loftes opp i publikum over pokalen, bunnblokken ned paa sokkelen,
        # slik at selve pokalen blir staaende fri.
        top_y = -155
        bottom_y = 445
    return number, top_y, bottom_y"""

BACKDROP_STRENGTH_OLD = (
    '    number = _dp_page_number(filename)\n'
    '    if number in (8, 9, 10) and (number in (9, 10) or second):\n'
    '        block["text_backdrop_strength"] = "strong"'
)
BACKDROP_STRENGTH_NEW = "    number = _dp_page_number(filename)"


# Baksideskyggen (draw_text_backdrop med shape="block": EN myk sky bak hele
# bolken i stedet for en pille per linje).
#
# To ting maa fikses her:
#  * Alfa 110 er tunet mot moerke bakgrunnsbilder. Fotball-VM sin bakside er
#    lys himmel med hvitt konfetti, og de tre oeverste linjene forsvinner.
#  * Bare nb-malen HAR block-grenen i det hele tatt. nn/en-US/en-GB/sv tegner
#    baksideteksten hvit rett paa bildet, uten noe bak. Den porteres inn.
BLOCK_SHADOW_ALPHA = 175

BLOCK_BRANCH = """    if shape == "block":
        # Baksiden: EN myk sky bak hele bolken - ingen synlig kant.
        # Den crisp platen droppes (plate_alpha = 0); i stedet blurres
        # skyggen kraftig slik at den toner ut i illustrasjonen.
        pad_x = int(pad_x * 1.9)
        pad_y = int(pad_y * 2.4)
        plate_alpha = 0
        shadow_alpha = %d
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
    for lb in boxes:""" % BLOCK_SHADOW_ALPHA

BLOCK_SIG_OLD = ('def draw_text_backdrop(img, box, text, font, line_spacing, '
                 'highlights=None, align="left", strength="normal"):')
BLOCK_SIG_NEW = ('def draw_text_backdrop(img, box, text, font, line_spacing, '
                 'highlights=None, align="left", strength="normal", shape="lines"):')

BLOCK_LOOP_OLD = """    drew = False
    for lb in line_boxes:"""

BLOCK_RADIUS_OLD = ("        radius = max(6, min((right - left) // 2, "
                    "int((bottom - top) * 0.40)))")
BLOCK_RADIUS_NEW = """        if shape == "block":
            radius = max(24, int(fs * 0.9))
        else:
            radius = max(6, min((right - left) // 2, int((bottom - top) * 0.40)))"""

# Selve kallet paa baksida - finnes bare i nb-malen.
BAKSIDE_CALL_OLD = """            use_gradient = "color" not in block


            draw_text("""
BAKSIDE_CALL_NEW = """            use_gradient = "color" not in block

            # Ett samlet felt bak hele bakside-teksten (ikke per linje).
            if block.get("text_backdrop", True):
                draw_text_backdrop(
                    img, box, block["text"], font, line_spacing,
                    highlights=block.get("highlights", []),
                    align="center", shape="block",
                    strength=block.get("text_backdrop_strength", "strong"),
                )

            draw_text("""


def patch_back_cover_shadow(out, locale):
    """Sorg for at alle fem sprak har den samme, tette bakside-skyen."""
    if 'shape="block"' in out:
        # nb: grenen finnes allerede, bare gjor skyen tettere.
        old = "        plate_alpha = 0\n        shadow_alpha = 110"
        new = "        plate_alpha = 0\n        shadow_alpha = %d" % BLOCK_SHADOW_ALPHA
        assert out.count(old) == 1, "bakside-alfa ikke funnet i " + locale
        return out.replace(old, new)

    for old in (BLOCK_SIG_OLD, BLOCK_LOOP_OLD, BLOCK_RADIUS_OLD, BAKSIDE_CALL_OLD):
        assert out.count(old) == 1, "bakside-anker mangler i " + locale

    out = out.replace(BLOCK_SIG_OLD, BLOCK_SIG_NEW)
    out = out.replace(BLOCK_LOOP_OLD, BLOCK_BRANCH)
    out = out.replace(BLOCK_RADIUS_OLD, BLOCK_RADIUS_NEW)
    out = out.replace(BAKSIDE_CALL_OLD, BAKSIDE_CALL_NEW)
    return out


def transform(src, locale):
    out = src

    # 1) build_pages-listen
    new = build_pages_block()
    out, n = re.subn(
        # Malen lukker lista med "     ] " (innrykk og etterslepende mellomrom).
        r"    pages: List\[Dict\[str, Any\]\] = \[.*?\n[ \t]*\][ \t]*\n",
        lambda m: new,
        out,
        count=1,
        flags=re.S,
    )
    assert n == 1, "build_pages ikke funnet"

    # 2) forside-renderer (logo, glod, tekst-fallback)
    out, n = re.subn(
        r"def resolve_front_cover_logo\(base_dir: str \| None = None\) -> str \| None:"
        r".*?\ndef draw_gradient_word\(",
        lambda m: COVER_BLOCK,
        out,
        count=1,
        flags=re.S,
    )
    assert n == 1, "forside-renderer ikke funnet"

    # 3) bok-slug for ryggrad/bakside
    assert out.count('RYGGRAD_BOOK_SLUG = "fotballstjernen"') == 1
    out = out.replace('RYGGRAD_BOOK_SLUG = "fotballstjernen"',
                      'RYGGRAD_BOOK_SLUG = "fotball-vm"')

    # 4) intro-siden: bokas egen dreampage-first hvis den finnes, ellers
    #    fotballstjernens (samme serie, samme utseende).
    old = ('    os.path.dirname(SCRIPT_ROOT_DIR), "books", "fotballstjernen", '
           '"dreampage-first(fotballstjernen).png"\n)')
    assert out.count(old) == 1, "dreampage-first ikke funnet"
    out = out.replace(old, '''    os.path.dirname(SCRIPT_ROOT_DIR), "books", "fotball-vm",
    "dreampage-first(fotball-vm).png"
)
if not os.path.exists(FOTBALL_DREAMPAGE_FIRST):
    # Boka har ingen egen intro-side enda - bruk bok 1 sin.
    FOTBALL_DREAMPAGE_FIRST = os.path.join(
        os.path.dirname(SCRIPT_ROOT_DIR), "books", "fotballstjernen",
        "dreampage-first(fotballstjernen).png"
    )''')

    # 5) hardkodede cover-filnavn utenfor build_pages
    out = out.replace("bakside(fotballstjernen).png", "bakside(fotball-vm).png")
    out = out.replace("forside(fotballstjernen).png", "forside(fotball-vm).png")

    # 6) sideregnskap: 13 oppslag x 2 + 2 kvadratsider (side 12) + intro +
    #    blank-back = 30. Ingen Lastpage - det finnes ingen bok 3 enda.
    out = re.sub(r"EXPECTED_INNER_PAGES = \d+", "EXPECTED_INNER_PAGES = 30",
                 out, count=1)
    out = out.replace(
        "# Lastpage(fotball).png ligger etter blank-back, så total innersider = 31.",
        "# 13 oppslag x 2 + 2 kvadratsider (side 12) + intro + blank-back = 30.",
    )

    out = out.replace(
        "    # Legg til dreampage-first.png først, blank-back.png deretter, "
        "og per-bok Lastpage(fotball).png aller sist.",
        "    # Legg til dreampage-first.png først og blank-back.png bakerst "
        "(ingen Lastpage - det finnes ingen bok 3 i serien enda).",
    )

    # 7) innerside-rekkefolgen
    out, n = re.subn(ASSEMBLY_OLD_RE, lambda m: ASSEMBLY_NEW, out, count=1, flags=re.S)
    assert n == 1, "innerside-blokken ikke funnet"

    # 8) kvadratside: hoyre kolonne + box_frac + no_split
    assert out.count(SQRIGHT_OLD) == 1, "SQ_RIGHT ikke funnet"
    out = out.replace(SQRIGHT_OLD, SQRIGHT_NEW)
    assert out.count(BOXFRAC_OLD) == 1, "box_frac-punkt ikke funnet"
    out = out.replace(BOXFRAC_OLD, BOXFRAC_NEW)
    assert out.count(NOSPLIT_OLD) == 1, "split-punkt ikke funnet"
    out = out.replace(NOSPLIT_OLD, NOSPLIT_NEW)

    # 9) bakside-skygge: samme tette sky i alle fem sprak
    out = patch_back_cover_shadow(out, locale)

    # 10) noytrale sidejusteringer. Malen har per-side-finjusteringer som ble
    #    tunet mot bok 1 sine illustrasjoner - de gir ingen mening her.
    out, n = re.subn(
        r"    top_y = 25\n    bottom_y = 345\n(?:    if number.*?\n(?:        \w.*?\n)+)+"
        r"    return number, top_y, bottom_y",
        lambda m: LAYOUT_OFFSETS_NEW,
        out,
        count=1,
    )
    assert n == 1, "layout-offsets ikke funnet"
    assert out.count(BACKDROP_STRENGTH_OLD) == 1, "backdrop-strength ikke funnet"
    out = out.replace(BACKDROP_STRENGTH_OLD, BACKDROP_STRENGTH_NEW)

    # 10) oversettelsestabellen
    if locale in TRANSLATIONS:
        old_t = re.search(r"_DREAMPAGE_TRANSLATIONS = \{.*?\n\}", out, flags=re.S)
        assert old_t, "oversettelsestabell ikke funnet i " + locale
        out = out[: old_t.start()] + translation_block(locale) + out[old_t.end():]

    for leftover in ("fotballstjernen-", "Lastpage(fotball)",
                     "15(fotballstjernen)", "fotballstjerne-logo"):
        assert leftover not in out, "rester av %s i %s" % (leftover, locale)
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for locale in LOCALES:
        src_path = os.path.join(SCRIPT_ROOT, locale, SRC_NAME % locale)
        src = io.open(src_path, encoding="utf-8").read()
        out = transform(src, locale)
        compile(out, DST_NAME % locale, "exec")

        staged = os.path.join(OUT_DIR, DST_NAME % locale)
        io.open(staged, "w", encoding="utf-8", newline="\n").write(out)
        print("staged:", staged, len(out))

        if APPLY:
            dst = os.path.join(SCRIPT_ROOT, locale, DST_NAME % locale)
            if os.path.exists(dst):
                bak = dst + ".backup-before-fotball-vm-20260828"
                if not os.path.exists(bak):
                    io.open(bak, "w", encoding="utf-8", newline="\n").write(
                        io.open(dst, encoding="utf-8").read())
                    print("  backup:", bak)
            io.open(dst, "w", encoding="utf-8", newline="\n").write(out)
            print("  -> skrev", dst)


if __name__ == "__main__":
    main()

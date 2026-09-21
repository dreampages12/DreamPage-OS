# -*- coding: utf-8 -*-
"""Bygger den-skjulte-verdenen-text-<locale>.py fra bursdagen-malene i script/<locale>/.

Malen er `den-magiske-bursdagen-jente-text-<locale>.py` (motet-i-hjertet-familien)
fordi den har den riktige BAKSIDE-SKYGGEN (draw_text_backdrop med
shape="block") og forsidetittel som linje1-tekst + linje2-LOGO.

Idempotent: kjor den om igjen naar som helst, den skriver hele fila paa nytt.

  python build_verdenen.py            # bare staging i script/out/
  python build_verdenen.py --apply    # skriver til C:/DreamPage-OS/flow/<locale>/
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from story_verdenen import (  # noqa: E402
    COVER_NB, BACK_NB, BACK_HL, PAGES_NB, TRANSLATIONS,
)

# DreamPage-roten finnes ved aa gaa OPPOVER til mappa som har books/ og flow/
# i seg - ikke ved aa telle mapper med dirname(dirname(...)), som brekker
# neste gang noe flyttes, og ikke ved aa hardkode en diskbokstav, som ikke
# finnes paa en Linux-server. Samme moenster som _dp_find_root i
# tekstscriptene; se CLAUDE.md.
def _dp_find_root(start):
    cur = os.path.dirname(os.path.abspath(start))
    while True:
        if (os.path.isdir(os.path.join(cur, "books"))
                and os.path.isdir(os.path.join(cur, "flow"))):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            raise RuntimeError("fant ingen DreamPage-rot (mappe med books/ "
                               "og flow/) over " + str(start))
        cur = parent


DP_ROOT = _dp_find_root(__file__)


def under(*parts):
    """En sti under DreamPage-roten, med plattformens separator.

    "/" i argumentet deles opp, slik at under("state/reprint") gir
    noeyaktig samme streng som under("state", "reprint") - og samme
    streng som flow/paths.py sin under(). Uten oppdelingen ville
    Windows fatt en sti med begge separatorer i seg. Den virker, men
    den er ikke den samme strengen koden hadde foer.
    """
    bits = [b for part in parts for b in str(part).split("/") if b]
    return os.path.join(DP_ROOT, *bits)

SCRIPT_ROOT = under("flow")
SRC_NAME = "den-magiske-bursdagen-jente-text-%s.py"
DST_NAME = "den-skjulte-verdenen-text-%s.py"
LOCALES = ["nb", "nn", "en-US", "en-GB", "sv"]
APPLY = "--apply" in sys.argv
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

# Side 4 er to kvadratsider. Teksten staar paa venstre kvadrat (handbildet);
# hoyre kvadrat er comfy-headswappen og skal vaere ren. Tekstboksen gaar
# nesten fra kant til kant - en smal boks presset teksten opp i hjoernet.
# Den faar gjerne ligge oppa handa; pillsene holder den lesbar.
SQUARE_INDEX = 4                      # 1-basert sidenummer i PAGES_NB
SQUARE_BOX_FRAC = [0.07, 0.08, 0.88, 0.60]


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


def _inner_block(text, hls, extra_indent=""):
    b = []
    b.append(extra_indent + '            "blocks": [{')
    b.append(extra_indent + '                "text": p(')
    b.append(pylit(text, 20 + len(extra_indent)))
    b.append(extra_indent + "                ),")
    b.append(extra_indent + '                "font_size": 30,')
    b.append(extra_indent + '                "color": "#FFFFFF",')
    b.append(extra_indent + '                "highlights": %s,' % hl_list(hls))
    b.append(extra_indent + "            }],")
    return b


def build_pages_block():
    b = []
    b.append("    pages: List[Dict[str, Any]] = [")
    b.append("        {")
    b.append('            "filename": "forside(verdenen).png",')
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
            b.append("        # Side %d - venstre kvadrat (statisk handbilde, baerer teksten)" % idx)
            b.append("        {")
            b.append('            "filename": "%02d(verdenen-left).png",' % idx)
            b.append('            "type": "inner",')
            b.append('            "square": True,')
            b.append('            "side": "left",')
            b.append('            "no_split": True,')
            b.append('            "box_frac": %s,' % SQUARE_BOX_FRAC)
            b.extend(_inner_block(text, hls))
            b.append("        },")
            b.append("")
            b.append("        # Side %d - hoyre kvadrat (comfy-headswap, ingen tekst)" % idx)
            b.append("        {")
            b.append('            "filename": "%02d(verdenen-right).png",' % idx)
            b.append('            "type": "inner",')
            b.append('            "square": True,')
            b.append('            "blocks": [],')
            b.append("        },")
            b.append("")
            continue

        b.append("        # Side %d" % idx)
        b.append("        {")
        b.append('            "filename": "%02d(verdenen).png",' % idx)
        b.append('            "type": "inner",')
        b.append('            "side": "%s",' % side)
        b.extend(_inner_block(text, hls))
        b.append("        },")
        b.append("")

    b.append("        # Bakside")
    b.append("        {")
    b.append('            "filename": "bakside(verdenen).png",')
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

COVER_CONSTS = '''FRONT_COVER_LOGO_SCALE = 0.78
FRONT_COVER_LOGO_X_OFFSET = 0
FRONT_COVER_TOP_MARGIN = 0.032
FRONT_COVER_LINE_SPACING = 0.043
FRONT_COVER_LINE1_SIZE = 75 / 1024          # andel av kortsiden
FRONT_COVER_GOLD = ((255, 255, 255), (255, 255, 255))
FRONT_COVER_SHADOW = (25, 20, 5)

# Logoen inneholder HELE tittelen ("Den Skjulte Verdenen"), saa linje 1 er bare
# "<navn> og" - ingenting skal henge paa. Speiler line1_prefix/line1_suffix i
# config/next_book_titles.json.
FRONT_COVER_LINE1_EXTRA = ""'''

LOGO_MAP = '''        "nb": "verdenen-logo-nb.png",
        "nn": "verdenen-logo-nb.png",
        "en-US": "verdenen-logo-en.png",
        "en-GB": "verdenen-logo-en.png",
        "sv": "verdenen-logo-sv.png",
    }.get(SCRIPT_LOCALE, "verdenen-logo-nb.png")'''

# 1:1-kvadratsider. Hoyrekolonnen trekkes ned i sidens EGET koordinatrom -
# 1328/1861 er koordinater i par-rommet (to sider = 2048).
SQUARE_BLOCK = '''
# ------------------------------------------------------------
#  1:1 KVADRATSIDE (ingen A5-splitt) - brukt for side 04 venstre/hoyre.
#  Kolonnene skaleres x4/3 slik at teksten havner samme sted paa skjermen
#  som paa en vanlig venstre-/hoyreside.
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
    # motivet ikke gir plass i standardkolonnen. Brukes for 04-venstre.
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

        bx1 = x1 + (0 if box_frac else sq(block.get("x_offset", 0)))
        bx2 = x2 + (0 if box_frac else sq(block.get("width_offset", 0)))
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


'''

SQUARE_HOOK_OLD = '''    if not os.path.exists(base_path):
        print("Fant ikke bilde:", base_path)
        return []
'''
SQUARE_HOOK_NEW = '''    if not os.path.exists(base_path):
        print("Fant ikke bilde:", base_path)
        return []

    # Kvadratsider (side 04) splittes ikke i A5 - de ER en ferdig bokside.
    if page.get("square"):
        return _render_square_page(page, base_path, out_dir)
'''

# no_split: hopp over den automatiske to-blokk-splitten (brukt paa kvadratsida,
# der teksten ligger i en eksplisitt box_frac).
NOSPLIT_OLD = '''    block = blocks[0]
    split = _dp_balanced_story_split(block.get("text", ""))'''
NOSPLIT_NEW = '''    block = blocks[0]
    if page.get("no_split") or page.get("square"):
        _dp_mark_backdrop(block, filename, child_name)
        return

    split = _dp_balanced_story_split(block.get("text", ""))'''

# _dp_widen_narrow_blocks regner i 1536x1024-rommet og gir mening bare for
# oppslag - den maa ikke roere kvadratsidene.
WIDEN_OLD = '''    if page.get("type") != "inner":
        return
    side = page.get("side", "right")
    for block in page.get("blocks") or []:'''
WIDEN_NEW = '''    if page.get("type") != "inner" or page.get("square"):
        return
    side = page.get("side", "right")
    for block in page.get("blocks") or []:'''

# Tekst-fallbacken (en/sv, der det ikke finnes logo) arvet prinsesse-rosa fra
# malen. Denne boka er gull/hvit. Krymp-til-passe finnes allerede i malen.
GOLD_OLD = """    gold   = ((210, 120, 150), (255, 245, 235))
    shadow = (40, 30, 60)"""
GOLD_NEW = """    gold   = ((255, 255, 255), (255, 245, 220))
    shadow = (25, 20, 5)"""


def transform(src, locale):
    out = src

    # 1) build_pages-listen
    new = build_pages_block()
    out, n = re.subn(
        r"    pages: List\[Dict\[str, Any\]\] = \[.*?\n    \]\n",
        lambda m: new,
        out,
        count=1,
        flags=re.S,
    )
    assert n == 1, "build_pages ikke funnet"

    # 2) forsidelogo per sprak
    old_logo = re.search(
        r'        "nb": "magiske-bursdag-logo-nb\.png",.*?\.get\(SCRIPT_LOCALE, "magiske-bursdag-logo-nb\.png"\)',
        out,
        flags=re.S,
    )
    assert old_logo, "logo-map ikke funnet"
    out = out[: old_logo.start()] + LOGO_MAP + out[old_logo.end():]

    # 3) forside-tittelkonstanter
    old_c = re.search(
        r"FRONT_COVER_LOGO_SCALE = .*?FRONT_COVER_SHADOW = \(\d+, \d+, \d+\)",
        out,
        flags=re.S,
    )
    assert old_c, "forsidekonstanter ikke funnet"
    out = out[: old_c.start()] + COVER_CONSTS + out[old_c.end():]

    # 4) bok-slug for ryggrad/bakside
    assert out.count('RYGGRAD_BOOK_SLUG = "den-magiske-bursdagen-jente"') == 1
    out = out.replace(
        'RYGGRAD_BOOK_SLUG = "den-magiske-bursdagen-jente"',
        'RYGGRAD_BOOK_SLUG = "den-skjulte-verdenen"',
    )

    # 5) intro-bakgrunn (bokas egen dreampage-first)
    assert out.count('"books", "den-magiske-bursdagen-jente", "dreampage-first-rosa.png"') == 1
    out = out.replace(
        '"books", "den-magiske-bursdagen-jente", "dreampage-first-rosa.png"',
        '"books", "den-skjulte-verdenen", "dreampage-first-verdenen.png"',
    )
    out = out.replace("MOTET_DREAMPAGE_FIRST", "BOOK_DREAMPAGE_FIRST")

    # 6) hardkodede cover-filnavn i process_book (utenfor build_pages)
    out = out.replace("bakside(magiske-bursdag-jente).png", "bakside(verdenen).png")
    out = out.replace("forside(magiske-bursdag-jente).png", "forside(verdenen).png")
    out = out.replace("Lastpage(bursdag).png", "Lastpage(verdenen).png")

    # 7) sideregnskap: 13 oppslag x 2 + 2 kvadrat + intro + blank-back = 30.
    #    Boka har ingen Lastpage (ingen fortsettelsesbok enda).
    out = re.sub(r"EXPECTED_INNER_PAGES = \d+", "EXPECTED_INNER_PAGES = 30", out, count=1)
    out = out.replace(
        "# Lastpage(prinsesse).png ligger etter blank-back, så total innersider = 31.",
        "# 13 oppslag x 2 + 2 kvadratsider (side 4) + intro + blank-back = 30.",
    )

    # 8) kvadratside-stotte
    anchor = "def render_page(page: Dict[str, Any], base_dir: str, out_dir: str) -> List[str]:"
    assert out.count(anchor) == 1, "render_page ikke funnet"
    out = out.replace(anchor, SQUARE_BLOCK.lstrip("\n") + anchor)

    assert out.count(SQUARE_HOOK_OLD) == 1, "hook-punkt i render_page ikke funnet"
    out = out.replace(SQUARE_HOOK_OLD, SQUARE_HOOK_NEW)

    assert out.count(NOSPLIT_OLD) == 1, "split-punkt ikke funnet"
    out = out.replace(NOSPLIT_OLD, NOSPLIT_NEW)

    assert out.count(WIDEN_OLD) == 1, "widen-punkt ikke funnet"
    out = out.replace(WIDEN_OLD, WIDEN_NEW)

    # 9) farger paa tekst-fallbacken for forsidetittelen
    assert out.count(GOLD_OLD) == 1, "gold/shadow-punkt ikke funnet"
    out = out.replace(GOLD_OLD, GOLD_NEW)

    # 10) oversettelsestabellen
    if locale in TRANSLATIONS:
        old_t = re.search(r"_DREAMPAGE_TRANSLATIONS = \{.*?\n\}", out, flags=re.S)
        assert old_t, "oversettelsestabell ikke funnet i " + locale
        out = out[: old_t.start()] + translation_block(locale) + out[old_t.end():]

    for leftover in ("magiske-bursdag", "magiske-bursdagen", "bursdag"):
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
                bak = dst + ".backup-before-verdenen-20260828"
                if not os.path.exists(bak):
                    io.open(bak, "w", encoding="utf-8", newline="\n").write(
                        io.open(dst, encoding="utf-8").read())
                    print("  backup:", bak)
            io.open(dst, "w", encoding="utf-8", newline="\n").write(out)
            print("  -> skrev", dst)


if __name__ == "__main__":
    main()

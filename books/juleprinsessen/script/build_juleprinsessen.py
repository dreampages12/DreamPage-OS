# -*- coding: utf-8 -*-
"""Bygger juleprinsessen-text-<locale>.py fra bursdagen-malene i script/<locale>/.

Malen er `den-magiske-bursdagen-jente-text-<locale>.py` (motet-i-hjertet-familien)
fordi den har den riktige BAKSIDE-SKYGGEN (draw_text_backdrop med shape="block")
og forsidetittel som linje1-tekst + linje2-LOGO.

Boka er 14 rene oppslag (2048x1024) - ingen kvadratsider, ingen Lastpage.
Sideregnskap: 14 oppslag x 2 + intro + blank-back = 30 innersider.

Idempotent: kjor den om igjen naar som helst, den skriver hele fila paa nytt.

  python build_juleprinsessen.py            # bare staging i script/out/
  python build_juleprinsessen.py --apply    # skriver til C:/DreamPage-OS/flow/<locale>/
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from story_juleprinsessen import (  # noqa: E402
    COVER_NB, BACK_NB, BACK_HL, PAGES_NB, TRANSLATIONS,
)

SCRIPT_ROOT = r"C:\DreamPage-OS\flow"
SRC_NAME = "den-magiske-bursdagen-jente-text-%s.py"
DST_NAME = "juleprinsessen-text-%s.py"
LOCALES = ["nb", "nn", "en-US", "en-GB", "sv"]
APPLY = "--apply" in sys.argv
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
BACKUP_SUFFIX = ".backup-before-juleprinsessen-20260914"

BRAND = "juleprinsessen"


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
    b.append('            "filename": "forside(%s).png",' % BRAND)
    b.append('            "type": "cover",')
    b.append('            "text": p("%s"),' % COVER_NB.replace("\n", "\\n"))
    b.append("        },")
    b.append("        {")
    b.append('            "filename": "ryggrad.png",')
    b.append('            "type": "cover",')
    b.append("        },")
    b.append("")

    for idx, (side, text, hls) in enumerate(PAGES_NB, start=1):
        b.append("        # Side %d" % idx)
        b.append("        {")
        b.append('            "filename": "%02d(%s).png",' % (idx, BRAND))
        b.append('            "type": "inner",')
        b.append('            "side": "%s",' % side)
        b.extend(_inner_block(text, hls))
        b.append("        },")
        b.append("")

    b.append("        # Bakside")
    b.append("        {")
    b.append('            "filename": "bakside(%s).png",' % BRAND)
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

# Logoen inneholder HELE tittelen ("Juleprinsessen"), saa linje 1 er bare
# barnets navn - ingenting skal henge paa. Speiler line1_prefix/line1_suffix i
# config/next_book_titles.json.
COVER_CONSTS = '''FRONT_COVER_LOGO_SCALE = 0.46
FRONT_COVER_LOGO_X_OFFSET = 0
FRONT_COVER_TOP_MARGIN = 0.030
FRONT_COVER_LINE_SPACING = 0.0              # ubrukt i inline-oppsettet
FRONT_COVER_LINE1_SIZE = 96 / 1254          # andel av kortsiden (malen er 1254 px)
FRONT_COVER_GAP = 0.022                     # luft mellom logo og navn, andel av bredden
FRONT_COVER_MAX_WIDTH = 0.90                # hele gruppa krympes til aa passe innenfor
FRONT_COVER_NAME_Y = 0.42                   # navnets midtlinje, andel av logohoyden
FRONT_COVER_GOLD = ((255, 255, 255), (255, 245, 220))
FRONT_COVER_SHADOW = (10, 14, 35)

FRONT_COVER_LINE1_EXTRA = ""'''

# en/sv har ingen egen logo - de faller MED VILJE tilbake til tekstvarianten
# (_draw_title_cover_text). En norsk logo skal aldri trykkes paa en engelsk bok.
LOGO_MAP = '''        "nb": "juleprinsessen-logo-nb.png",
        "nn": "juleprinsessen-logo-nb.png",
        "en-US": "juleprinsessen-logo-en.png",
        "en-GB": "juleprinsessen-logo-en.png",
        "sv": "juleprinsessen-logo-sv.png",
    }.get(SCRIPT_LOCALE, "juleprinsessen-logo-nb.png")'''

# Tekst-fallbacken (en/sv) arvet prinsesse-rosa fra malen. Denne boka er
# gull/hvit mot mørkeblå vinterhimmel.
GOLD_OLD = """    gold   = ((210, 120, 150), (255, 245, 235))
    shadow = (40, 30, 60)"""
GOLD_NEW = """    gold   = ((255, 255, 255), (255, 245, 220))
    shadow = (10, 14, 35)"""


# Inline-tittel: LOGO foerst, NAVN etter, paa EN linje. Brukeren bad om det
# 2026-09-15 - toppen av forsiden er smal, og to linjer skjoev logoen ned i
# ansiktet paa jenta. Hele gruppa maales foer den tegnes og krympes samlet
# (logo + font + luft i samme forhold) hvis den blir bredere enn
# FRONT_COVER_MAX_WIDTH, saa lange navn aldri sprenger sida.
FRONT_COVER_FN = '''def draw_centered_title_cover(img, text, base_dir=None):
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
'''

def transform(src, locale):
    out = src

    # 1) build_pages-listen
    new = build_pages_block()
    out, n = re.subn(
        r"    pages: List\[Dict\[str, Any\]\] = \[.*?\n[ \t]*\][ \t]*\n",
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
        'RYGGRAD_BOOK_SLUG = "juleprinsessen"',
    )

    # 5) intro-bakgrunn (bokas egen dreampage-first)
    assert out.count('"books", "den-magiske-bursdagen-jente", "dreampage-first-rosa.png"') == 1
    out = out.replace(
        '"books", "den-magiske-bursdagen-jente", "dreampage-first-rosa.png"',
        '"books", "juleprinsessen", "dreampage-first-juleprinsessen.png"',
    )
    out = out.replace("MOTET_DREAMPAGE_FIRST", "BOOK_DREAMPAGE_FIRST")

    # 6) hardkodede cover-filnavn i process_book (utenfor build_pages)
    out = out.replace("bakside(magiske-bursdag-jente).png", "bakside(%s).png" % BRAND)
    out = out.replace("forside(magiske-bursdag-jente).png", "forside(%s).png" % BRAND)
    out = out.replace("Lastpage(bursdag).png", "Lastpage(%s).png" % BRAND)

    # 7) sideregnskap: 14 oppslag x 2 + intro + blank-back = 30.
    #    Boka har ingen Lastpage (ingen fortsettelsesbok enda).
    out = re.sub(r"EXPECTED_INNER_PAGES = \d+", "EXPECTED_INNER_PAGES = 30", out, count=1)
    out = out.replace(
        "# Lastpage(prinsesse).png ligger etter blank-back, så total innersider = 31.",
        "# 14 oppslag x 2 + intro + blank-back = 30. Ingen Lastpage enda.",
    )

    # 8) farger paa tekst-fallbacken for forsidetittelen
    assert out.count(GOLD_OLD) == 1, "gold/shadow-punkt ikke funnet"
    out = out.replace(GOLD_OLD, GOLD_NEW)

    # 9) oversettelsestabellen
    if locale in TRANSLATIONS:
        old_t = re.search(r"_DREAMPAGE_TRANSLATIONS = \{.*?\n\}", out, flags=re.S)
        assert old_t, "oversettelsestabell ikke funnet i " + locale
        out = out[: old_t.start()] + translation_block(locale) + out[old_t.end():]

    # 10) tittelen paa EN linje: logo foerst, navn etter
    old_fn = re.search(
        r"def draw_centered_title_cover\(img, text, base_dir=None\):"
        r".*?\n\ndef draw_gradient_word",
        out, flags=re.S)
    assert old_fn, "draw_centered_title_cover ikke funnet"
    out = (out[: old_fn.start()] + FRONT_COVER_FN
           + "\ndef draw_gradient_word" + out[old_fn.end():])

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
                bak = dst + BACKUP_SUFFIX
                if not os.path.exists(bak):
                    io.open(bak, "w", encoding="utf-8", newline="\n").write(
                        io.open(dst, encoding="utf-8").read())
                    print("  backup:", bak)
            io.open(dst, "w", encoding="utf-8", newline="\n").write(out)
            print("  -> skrev", dst)


if __name__ == "__main__":
    main()

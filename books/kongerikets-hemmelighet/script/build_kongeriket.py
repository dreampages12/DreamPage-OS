# -*- coding: utf-8 -*-
"""Bygger kongeriket-text-<locale>.py fra dinosauregget-malene i script/<locale>/."""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from story_kongeriket import (  # noqa: E402
    COVER_NB, INTRO_NB, BACK_NB, BACK_HL, PAGES_NB, TRANSLATIONS,
)

SCRIPT_ROOT = r"C:\DreamPage-OS\flow"
LOCALES = ["nb", "nn", "en-US", "en-GB", "sv"]
APPLY = "--apply" in sys.argv
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")


def pylit(text, indent):
    """Norsk kildetekst -> \"...\\n\" per linje, slik malene skriver den."""
    lines = text.split("\n")
    out = []
    for i, line in enumerate(lines):
        esc = line.replace("\\", "\\\\").replace('"', '\\"')
        suffix = "\\n" if i < len(lines) - 1 else ""
        out.append(" " * indent + '"' + esc + suffix + '"')
    return "\n".join(out)


def hl_list(words):
    return "[child_name, " + ", ".join('"%s"' % w for w in words) + "]"


def build_pages_block():
    b = []
    b.append("    pages: List[Dict[str, Any]] = [")
    b.append("        {")
    b.append('            "filename": "forside(kongeriket).png",')
    b.append('            "type": "cover",')
    b.append('            "text": p("%s"),' % COVER_NB.replace("\n", "\\n"))
    b.append("        },")
    b.append("        {")
    b.append('            "filename": "ryggrad.png",')
    b.append('            "type": "cover",')
    b.append("        },")
    b.append("        {")
    b.append('            "type": "blank",')
    b.append('            "side": "right",')
    b.append('            "text": p("%s"),' % COVER_NB.replace("\n", "\\n"))
    b.append('            "blocks": [{')
    b.append('                "text": p(')
    b.append(pylit(INTRO_NB, 20))
    b.append("                ),")
    b.append('                "font_size": 42,')
    b.append('                "color": "#111111",')
    b.append('                "y_offset": 420,')
    b.append("            }]")
    b.append("        },")
    b.append("")

    for idx, (side, text, hls) in enumerate(PAGES_NB, start=1):
        b.append("        # Side %d" % idx)
        b.append("        {")
        b.append('            "filename": "%02d(kongeriket).png",' % idx)
        b.append('            "type": "inner",')
        b.append('            "side": "%s",' % side)
        b.append('            "blocks": [{')
        b.append('                "text": p(')
        b.append(pylit(text, 20))
        b.append("                ),")
        b.append('                "font_size": 34,')
        b.append('                "color": "#FFFFFF",')
        b.append('                "highlights": %s,' % hl_list(hls))
        b.append("            }],")
        b.append("        },")
        b.append("")

    b.append("        # EKSTRA BLANK SISTE INNERSIDE")
    b.append("        {")
    b.append('            "filename": "blank-back.png",')
    b.append('            "type": "inner",')
    b.append('            "side": "left",')
    b.append('            "blank_only": True')
    b.append("        },")
    b.append("")
    b.append("        # Bakside")
    b.append("        {")
    b.append('            "filename": "bakside(kongeriket).png",')
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
    """Kildenoklene, i samme rekkefolge som verdiene i TRANSLATIONS."""
    to_key = lambda t: t.replace("(Navn)", "{name}")
    return (
        [to_key(COVER_NB), to_key(INTRO_NB)]
        + [to_key(t) for _, t, _ in PAGES_NB]
        + [to_key(BACK_NB)]
    )


def translation_block(locale):
    cover, intro, pages, back = TRANSLATIONS[locale]
    values = [cover, intro] + list(pages) + [back]
    keys = keys_nb()
    assert len(keys) == len(values) == 17, (len(keys), len(values))
    lines = ["_DREAMPAGE_TRANSLATIONS = {"]
    for k, v in zip(keys, values):
        lines.append(
            "  %s: %s," % (repr(k).lstrip("u"), repr(v).lstrip("u"))
        )
    lines.append("}")
    return "\n".join(lines)


COVER_CONSTS = '''FRONT_COVER_LOGO_SCALE = 0.75
FRONT_COVER_LOGO_X_OFFSET = 0
FRONT_COVER_TOP_MARGIN = 0.03
FRONT_COVER_LINE_SPACING = 0.02
FRONT_COVER_LINE1_SIZE = 73 / 1024          # andel av kortsiden
FRONT_COVER_GOLD = ((255, 255, 255), (255, 255, 255))
FRONT_COVER_SHADOW = (60, 35, 70)

# Logoen inneholder HELE tittelen ("Kongerikets Hemmelighet"), saa linje 1 er
# bare "Prinsesse <navn> og" - ingenting skal henge paa. Speiler
# line1_prefix/line1_suffix i config/next_book_titles.json.
FRONT_COVER_LINE1_EXTRA = ""'''

LOGO_MAP = '''        "nb": "kongeriket-logo-nb.png",
        "nn": "kongeriket-logo-nb.png",
        "en-US": "kongeriket-logo-en.png",
        "en-GB": "kongeriket-logo-en.png",
        "sv": "kongeriket-logo-sv.png",
    }.get(SCRIPT_LOCALE, "kongeriket-logo-nb.png")'''


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
        r'        "nb": "dinosauregget-logo-nb\.png",.*?\.get\(SCRIPT_LOCALE, "dinosauregget-logo-nb\.png"\)',
        out,
        flags=re.S,
    )
    assert old_logo, "logo-map ikke funnet"
    out = out[: old_logo.start()] + LOGO_MAP + out[old_logo.end():]

    # 3) forside-tittelkonstanter
    old_c = re.search(
        r"FRONT_COVER_LOGO_SCALE = .*?FRONT_COVER_LINE1_EXTRA = .*?$",
        out,
        flags=re.S | re.M,
    )
    assert old_c, "forsidekonstanter ikke funnet"
    out = out[: old_c.start()] + COVER_CONSTS + out[old_c.end():]

    # 4) bok-slug for ryggrad/bakside
    out = out.replace(
        'RYGGRAD_BOOK_SLUG = "det-forsvunne-dinosauregget"',
        'RYGGRAD_BOOK_SLUG = "kongerikets-hemmelighet"',
    )

    # 5) intro-bakgrunn (faller tilbake til script/<locale>/dreampage-first.png)
    out = out.replace(
        '"books", "det-forsvunne-dinosauregget", "dreampage-first-dinosauregget.png"',
        '"books", "kongerikets-hemmelighet", "dreampage-first-kongeriket.png"',
    )

    # 6) hardkodede cover-filnavn i process_book (utenfor build_pages)
    out = out.replace("bakside(dinosauregget).png", "bakside(kongeriket).png")
    out = out.replace("forside(dinosauregget).png", "forside(kongeriket).png")

    # 6b) variabelnavn + kommentarer som fortsatt peker paa forrige bok
    out = out.replace("DINOSAUR_DREAMPAGE_FIRST", "BOOK_DREAMPAGE_FIRST")
    out = out.replace(
        '# Krymp til tittelen faar plass. "Det forsvunne dinosauregget" er mye',
        '# Krymp til tittelen faar plass. "Kongerikets Hemmelighet" er mye',
    )
    out = out.replace(
        "#  FORSIDE-TITTEL - navn som tekst + Det forsvunne dinosauregget-logo som linje 2",
        "#  FORSIDE-TITTEL - navn som tekst + Kongerikets Hemmelighet-logo som linje 2",
    )

    # 6c) introsidens tittel maa krympe til den faar plass
    old_it = '''    title_color = "#1c1c1e"   # near-black charcoal — premium, not flashy

    def _tw(t, f):'''
    new_it = '''    title_color = "#1c1c1e"   # near-black charcoal — premium, not flashy

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

    def _tw(t, f):'''
    assert out.count(old_it) == 1, "draw_inside_title ikke funnet"
    out = out.replace(old_it, new_it)

    # 7) oversettelsestabellen
    if locale in TRANSLATIONS:
        old_t = re.search(r"_DREAMPAGE_TRANSLATIONS = \{.*?\n\}", out, flags=re.S)
        assert old_t, "oversettelsestabell ikke funnet i " + locale
        out = out[: old_t.start()] + translation_block(locale) + out[old_t.end():]
        out = out.replace(
            "# --- DreamPage translated text table (%s) ---" % locale,
            "# --- DreamPage translated text table (%s) ---" % locale,
        )

    assert "dinosauregget" not in out, "rester av dinosauregget i " + locale
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for locale in LOCALES:
        src_path = os.path.join(SCRIPT_ROOT, locale, "dinosauregget-text-%s.py" % locale)
        src = io.open(src_path, encoding="utf-8").read()
        out = transform(src, locale)

        dst_name = "kongeriket-text-%s.py" % locale
        staged = os.path.join(OUT_DIR, dst_name)
        io.open(staged, "w", encoding="utf-8", newline="\n").write(out)
        print("staged:", staged, len(out))

        if APPLY:
            dst = os.path.join(SCRIPT_ROOT, locale, dst_name)
            io.open(dst, "w", encoding="utf-8", newline="\n").write(out)
            print("  -> skrev", dst)


if __name__ == "__main__":
    main()

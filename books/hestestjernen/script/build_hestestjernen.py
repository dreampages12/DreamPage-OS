# -*- coding: utf-8 -*-
"""Bygger hestestjernen-text-<locale>.py fra bursdagen-malene i flow/text/<locale>/.

Malen er `den-magiske-bursdagen-jente-text-<locale>.py` (motet-i-hjertet-
familien) fordi den har BEGGE tingene denne boka trenger:
  * bakside-skyggen (`draw_text_backdrop(..., shape="block")`)
  * forsidetittel som linje1-TEKST over linje2-LOGO

Dette scriptet er derfor ENKLERE enn build_juleprinsessen.py: juleprinsessen
maatte bytte ut hele `draw_centered_title_cover` med en inline-variant (logo
og navn paa samme linje), fordi toppen av den forsiden var for smal. Her er
den stablede standardvarianten riktig, saa malens egen funksjon staar urort.

Boka er 14 rene oppslag (2048x1024) - ingen kvadratsider, ingen Lastpage.
Sideregnskap: 14 oppslag x 2 + intro + blank-back = 30 innersider.

Idempotent: kjoer den om igjen naar som helst, den skriver hele fila paa nytt.

  python build_hestestjernen.py            # bare staging i script/out/
  python build_hestestjernen.py --apply    # skriver til flow/text/<locale>/
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from story_hestestjernen import (  # noqa: E402
    COVER_NB, BACK_NB, BACK_HL, PAGES_NB, TRANSLATIONS,
)

SCRIPT_ROOT = r"C:\DreamPage-OS\flow\text"
SRC_NAME = "den-magiske-bursdagen-jente-text-%s.py"
DST_NAME = "hestestjernen-text-%s.py"
LOCALES = ["nb", "nn", "en-US", "en-GB", "sv"]
APPLY = "--apply" in sys.argv
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
BACKUP_SUFFIX = ".backup-before-hestestjernen-20260916"

BRAND = "hestestjernen"

# ---------------------------------------------------------------------------
# Forsidetypografi
#
# FASIT er DP Title Tester-noden, som brukeren har tunet. Verdiene der:
#     logo_scale 0.60 | top_margin 0.04 | line_spacing 0.038
#     gold 255,255,255 | shadow 15,35,65
#     font_small: nb 109, en 78, sv 79  (absolutte px mot 1024-malen)
#     font_small_path: PlayfairDisplay.ttf
#
# font_small er ULIK per spraak fordi linje 1 er ulik lang:
# "(Navn) blir" mot "{name} Becomes a". Derfor er LINE1_SIZE per locale.
#
# Fonten: malen definerer FRONT_COVER_LINE1_FONT = Fredoka-Bold, men testeren
# bruker PlayfairDisplay. De MAA vaere enige, ellers spriker tester og trykk -
# det er noeyaktig fella fra det-morke-fjellet. Vi foelger testeren og lar
# `_dp_line1_font()` falle tilbake til COVER_FONT (Playfair) ved aa sette
# stien til en fil som ikke finnes... nei: vi setter den EKSPLISITT til
# Playfair, saa det staar hva som faktisk brukes.
#
# 17.09.2026 (ordre 1517): brukeren ville ha linje 1 hoeyere opp og litt
# mindre. Testerens 109/0.04/0.038 er derfor ikke lenger fasit for denne boka.
# LINE1_SIZE er ca. 10 % ned og TOP_MARGIN fra 0.04 til 0.022.
#
# FELLA her: logoen er IKKE plassert uavhengig. Rendreren regner
#     y2 = y1 + h1 - 0.15*h1 + h*LINE_SPACING
# saa baade et lavere TOP_MARGIN og en mindre linje 1 drar LOGOEN opp ogsaa.
# Brukeren ba bare om at linje 1 skulle flytte seg. LINE_SPACING er derfor
# regnet ut PER SPRAAK slik at logoens y2 lander paa samme piksel som foer
# (nb/nn 687, en 581, sv 586 paa en 4096-mal) - ulike verdier fordi h1 er
# ulik naar linje 1 er ulik lang. Endrer du LINE1_SIZE eller TOP_MARGIN,
# maa LINE_SPACING regnes om, ellers vandrer logoen.
# ---------------------------------------------------------------------------
LINE1_SIZE = {"nb": 98, "nn": 98, "en-US": 70, "en-GB": 70, "sv": 71}
TOP_MARGIN = 0.022
LINE_SPACING = {"nb": 0.0649, "nn": 0.0649, "en-US": 0.0620,
                "en-GB": 0.0620, "sv": 0.0623}


def cover_consts(locale):
    return '''FRONT_COVER_LOGO_SCALE = 0.60
FRONT_COVER_LOGO_X_OFFSET = 0
FRONT_COVER_TOP_MARGIN = %s
FRONT_COVER_LINE_SPACING = %s          # holder logoen der den var, se kommentar over
FRONT_COVER_LINE1_SIZE = %d / 1024          # andel av kortsiden (malen er 1024 px)
FRONT_COVER_GOLD = ((255, 255, 255), (255, 255, 255))
FRONT_COVER_SHADOW = (15, 35, 65)''' % (TOP_MARGIN, LINE_SPACING[locale],
                                        LINE1_SIZE[locale])


# Logoen inneholder HELE tittelen ("Hestestjerne"), saa linje 1 er bare
# "(Navn) blir" - ingenting henger paa. Speiler line1_suffix i
# config/next_book_titles.json.
COVER_LINE1_EXTRA = 'FRONT_COVER_LINE1_EXTRA = ""'

# Alle tre spraak HAR egen logo her - i motsetning til juleprinsessen, der
# en/sv med vilje falt tilbake til tekst. Filnavnene foelger ikke
# <slug>-logo-<locale>-moenstret, de er de som alt laa i flow/text/logo/.
LOGO_MAP = '''        "nb": "hestestjerne-logo.png",
        "nn": "hestestjerne-logo.png",
        "en-US": "riding-star-logo-en.png",
        "en-GB": "riding-star-logo-en.png",
        "sv": "ridstjarna-logo-sv.png",
    }.get(SCRIPT_LOCALE, "hestestjerne-logo.png")'''

# Tekst-fallbacken arvet prinsesse-ROSA fra malen. Denne boka er hvit med
# moerk blaagroenn skygge, som testeren.
GOLD_OLD = """    gold   = ((210, 120, 150), (255, 245, 235))
    shadow = (40, 30, 60)"""
GOLD_NEW = """    gold   = ((255, 255, 255), (255, 255, 255))
    shadow = (15, 35, 65)"""


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
    """Kildenoeklene i samme rekkefoelge som verdiene i TRANSLATIONS.

    Ordboka slaar opp paa den NORSKE kildeteksten med (Navn) byttet til
    {name}. Endres kildeteksten uten at noekkelen endres, faller de andre
    spraakene stille tilbake til norsk.
    """
    def to_key(t):
        return t.replace("(Navn)", "{name}")
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


def transform(src, locale):
    out = src

    # 1) build_pages-listen.
    #    Regexen maa taale etterslepende mellomrom foer `]` - fotballstjernen
    #    lukket lista med fem mellomrom, og `\n    \]\n` spiste da 18k tegn.
    new = build_pages_block()
    out, n = re.subn(
        r"    pages: List\[Dict\[str, Any\]\] = \[.*?\n[ \t]*\][ \t]*\n",
        lambda m: new, out, count=1, flags=re.S)
    assert n == 1, "build_pages ikke funnet"

    # 2) forsidelogo per spraak
    old_logo = re.search(
        r'        "nb": "magiske-bursdag-logo-nb\.png",.*?'
        r'\.get\(SCRIPT_LOCALE, "magiske-bursdag-logo-nb\.png"\)',
        out, flags=re.S)
    assert old_logo, "logo-map ikke funnet"
    out = out[:old_logo.start()] + LOGO_MAP + out[old_logo.end():]

    # 3) forside-tittelkonstanter
    old_c = re.search(
        r"FRONT_COVER_LOGO_SCALE = .*?FRONT_COVER_SHADOW = \(\d+, \d+, \d+\)",
        out, flags=re.S)
    assert old_c, "forsidekonstanter ikke funnet"
    out = out[:old_c.start()] + cover_consts(locale) + out[old_c.end():]

    # 3b) linje1-fonten. Malen setter Fredoka-Bold; testeren bruker Playfair.
    #     De maa vaere enige - ellers viser testeren noe annet enn det som
    #     trykkes.
    old_font = re.search(r'FRONT_COVER_LINE1_FONT = os\.path\.join\([^\n]*\)', out)
    assert old_font, "FRONT_COVER_LINE1_FONT ikke funnet"
    out = (out[:old_font.start()]
           + 'FRONT_COVER_LINE1_FONT = os.path.join(SCRIPT_ROOT_DIR, "PlayfairDisplay.ttf")'
           + out[old_font.end():])

    # 3c) line1_suffix
    if "FRONT_COVER_LINE1_EXTRA" in out:
        out = re.sub(r'FRONT_COVER_LINE1_EXTRA = "[^"]*"',
                     COVER_LINE1_EXTRA, out, count=1)

    # 4) bok-slug for ryggrad/bakside
    assert out.count('RYGGRAD_BOOK_SLUG = "den-magiske-bursdagen-jente"') == 1
    out = out.replace('RYGGRAD_BOOK_SLUG = "den-magiske-bursdagen-jente"',
                      'RYGGRAD_BOOK_SLUG = "%s"' % BRAND)

    # 5) intro-bakgrunn: bokas EGEN dreampage-first.
    #
    #    Maa vaere bokas egen. Den DELTE `flow/dreampage-first.png` har
    #    taglinen bakt inn i bildet, og tekstscriptet tegner sin egen oppaa -
    #    resultatet er dobbel tekst i to fonter. Malens rosa bursdagsvariant
    #    ville dessuten vaert rosa i en hestebok.
    #
    #    Fila er bygget av hesteskoen fra bokas egen logo, med samme
    #    hjoerne-og-(c)-oppsett som de andre boekene (maalt fra
    #    den-skjulte-styrken: (c)-linja sentrert paa y 0.9197).
    assert out.count(
        '"books", "den-magiske-bursdagen-jente", "dreampage-first-rosa.png"') == 1
    out = out.replace(
        '"books", "den-magiske-bursdagen-jente", "dreampage-first-rosa.png"',
        '"books", "%s", "dreampage-first-%s.png"' % (BRAND, BRAND))

    # 6) hardkodede cover-filnavn i process_book, UTENFOR build_pages.
    #    Bytter du bare navnene i build_pages, rendres alt fint og cover-PDF-en
    #    bygges bare aldri - med en linje til slutt som lett drukner.
    out = out.replace("bakside(magiske-bursdag-jente).png", "bakside(%s).png" % BRAND)
    out = out.replace("forside(magiske-bursdag-jente).png", "forside(%s).png" % BRAND)
    out = out.replace("Lastpage(bursdag).png", "Lastpage(%s).png" % BRAND)

    # 7) sideregnskap. Boka har ingen Lastpage (ingen fortsettelsesbok enda);
    #    monteringen skriver "hopper over" og lander paa 30.
    out = re.sub(r"EXPECTED_INNER_PAGES = \d+", "EXPECTED_INNER_PAGES = 30",
                 out, count=1)

    # 7b) Kommentarer arvet fra malen som na LYVER. De knekker ingenting, men
    #     de er noeyaktig det som sender neste person i feil retning.
    out = out.replace(
        "# Lastpage(prinsesse).png ligger etter blank-back, "
        "så total innersider = 31.",
        "# 14 oppslag x 2 + intro + blank-back = 30. Ingen Lastpage: boka har\n"
        "# ingen fortsettelsesbok enda, og monteringen hopper da over den.")
    out = out.replace(
        "    # prinsesse (BRUKES I PRINSESSE BOKEN)",
        "    # Hestestjernen: hvit tittel med moerk blaagroenn skygge, som i\n"
        "    # DP Title Tester. Dette er tekst-FALLBACKEN - brukes bare hvis\n"
        "    # logoen for spraaket mangler.")
    out = out.replace(
        "per-bok Lastpage(prinsesse).png aller sist.",
        "og per-bok Lastpage aller sist (finnes ikke for denne boka).")

    # 7c) Variabelnavnet peker ikke paa motet-i-hjertet lenger.
    out = out.replace("MOTET_DREAMPAGE_FIRST", "BOOK_DREAMPAGE_FIRST")

    # 8) farger paa tekst-fallbacken
    assert out.count(GOLD_OLD) == 1, "gold/shadow-punkt ikke funnet"
    out = out.replace(GOLD_OLD, GOLD_NEW)

    # 9) oversettelsestabellen
    if locale in TRANSLATIONS:
        old_t = re.search(r"_DREAMPAGE_TRANSLATIONS = \{.*?\n\}", out, flags=re.S)
        assert old_t, "oversettelsestabell ikke funnet i " + locale
        out = out[:old_t.start()] + translation_block(locale) + out[old_t.end():]

    # MERK: ingen steg 10. Malens egen `draw_centered_title_cover` (linje1-tekst
    # over linje2-logo) er riktig for denne boka og staar urort.

    for leftover in ("magiske-bursdag", "magiske-bursdagen"):
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
        print("staged: %-44s %6d tegn" % (DST_NAME % locale, len(out)))

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

# -*- coding: utf-8 -*-
"""Bygger ryggraden for Hestestjernen i alle fem spraak.

    python build_ryggrad_hestestjernen.py            # staging i script/out/
    python build_ryggrad_hestestjernen.py --apply    # flow/text/ryggrad/hestestjernen/

125x2700 er maalet ALLE de 16 andre boekene bruker - ikke et valg, men
formatet omslags-PDF-en forventer.

Hvorfor per spraak, og ikke en kopi av den norske: tittelen staar paa ryggen.
`ryggrad-nb.png` paa en engelsk bok gir en rygg som sier "Hestestjerne" mens
omslaget sier "Riding Star". Flere boeker har den feilen i dag fordi ryggraden
ble kopiert fra norsk - se merknaden om fotball-vm i notatene.

Fargene er hentet fra bokas EGEN forside (medianen i tre baand), og skyggen er
den samme (15, 35, 65) som forsidetittelen bruker, saa rygg og omslag henger
sammen naar de trykkes paa samme ark.

FELLE som kostet tid: paddingen rundt teksten havner paa TVERS av ryggen etter
rotasjonen. Med romslig padding ble fonten presset ned til 68 px i stedet for
100, og tittelen ble en tynn stripe. Paddingen er derfor bare saa stor som
skyggen trenger.
"""
from __future__ import annotations

import argparse
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

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

ROOT = under()
W, H = 125, 2700
FONT = os.path.join(ROOT, "flow", "PlayfairDisplay.ttf")
DST_DIR = os.path.join(ROOT, "flow", "text", "ryggrad", "hestestjernen")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

# Medianfarger fra forside(hestestjernen).png, tre baand.
TOP, MID, BOT = (152, 185, 211), (198, 156, 118), (140, 112, 86)
GOLD_T, GOLD_B = (255, 248, 222), (222, 170, 74)
SHADOW = (15, 35, 65)          # = FRONT_COVER_SHADOW i tekstscriptene

# Tittelen slik den staar paa omslaget i hvert spraak. Logoen sier bare
# "Hestestjerne" / "Riding Star" / "Ridstjarna"; ryggen gjentar det, uten
# barnets navn.
TITLES = {
    "nb": "Hestestjerne",
    "nn": "Hestestjerne",
    "en-US": "Riding Star",
    "en-GB": "Riding Star",
    "sv": "Ridstj\u00e4rna",
}


def vertical_text(txt: str, size: int, top, bot, shadow_alpha: float = 0.62):
    """Tekst tegnet VANNRETT med gradient, deretter rotert 90 grader.

    Rekkefoelgen er poenget: en gradient tegnet i det roterte rommet ville
    gaatt paa tvers av ryggen i stedet for langs den.
    """
    font = ImageFont.truetype(FONT, size)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bb = probe.textbbox((0, 0), txt, font=font)
    off = max(2, size // 22)
    pad = off * 2 + max(2, size // 26)
    w, h = bb[2] - bb[0] + pad * 2, bb[3] - bb[1] + pad * 2

    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((pad - bb[0], pad - bb[1]), txt, font=font, fill=255)

    grad = Image.new("RGBA", (w, h))
    gd = ImageDraw.Draw(grad)
    for y in range(h):
        u = y / max(1, h - 1)
        gd.line([(0, y), (w, y)],
                fill=tuple(int(top[i] + (bot[i] - top[i]) * u) for i in range(3)) + (255,))
    glyph = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    glyph.paste(grad, (0, 0), mask)

    sh = Image.new("RGBA", (w, h), SHADOW + (0,))
    sh.putalpha(mask.point(lambda v: int(v * shadow_alpha)))
    sh = sh.filter(ImageFilter.GaussianBlur(max(1, size // 30)))

    plate = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    plate.alpha_composite(sh, (off, off))
    plate.alpha_composite(glyph, (0, 0))
    return plate.rotate(-90, expand=True, resample=Image.BICUBIC)


def fit(txt: str, top, bot, limit_frac: float = 0.94):
    """Stoerste fontstoerrelse som holder seg innenfor ryggbredden."""
    limit = int(W * limit_frac)
    img = None
    size = 170
    while size > 24:
        img = vertical_text(txt, size, top, bot)
        if img.width <= limit:
            return img, size
        size -= 2
    return img, size


def gold_star(size: int):
    """Femtakket gullstjerne - samme motiv de andre ryggradene har nederst."""
    ss = size * 4
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        r = ss * 0.47 if i % 2 == 0 else ss * 0.20
        pts.append((ss / 2 + r * math.cos(ang), ss / 2 + r * math.sin(ang)))
    mask = Image.new("L", (ss, ss), 0)
    ImageDraw.Draw(mask).polygon(pts, fill=255)
    grad = Image.new("RGBA", (ss, ss))
    gd = ImageDraw.Draw(grad)
    for y in range(ss):
        u = y / max(1, ss - 1)
        gd.line([(0, y), (ss, y)],
                fill=tuple(int(GOLD_T[i] + (GOLD_B[i] - GOLD_T[i]) * u)
                           for i in range(3)) + (255,))
    star = Image.new("RGBA", (ss, ss), (0, 0, 0, 0))
    star.paste(grad, (0, 0), mask)
    return star.resize((size, size), Image.LANCZOS)


def background():
    grad = Image.new("RGB", (1, H))
    gd = ImageDraw.Draw(grad)
    for y in range(H):
        t = y / (H - 1)
        c0, c1, u = ((TOP, MID, t / 0.5) if t < 0.5
                     else (MID, BOT, (t - 0.5) / 0.5))
        gd.point((0, y),
                 fill=tuple(int(c0[i] + (c1[i] - c0[i]) * u) for i in range(3)))
    return grad.resize((W, H), Image.BICUBIC).convert("RGBA")


def build(locale: str) -> Image.Image:
    spine = background()

    # Tittelen er HVIT, som paa forsiden. Gull mot den lyse himmelen oeverst
    # paa ryggen ga for lav kontrast.
    title, ts = fit(TITLES[locale], (255, 255, 255), (255, 255, 255))
    spine.alpha_composite(title, ((W - title.width) // 2, int(H * 0.050)))

    brand, bs = fit("DreamPage", (255, 255, 255), (255, 255, 255))
    spine.alpha_composite(brand, ((W - brand.width) // 2, int(H * 0.565)))

    star = gold_star(int(W * 0.46))
    for i in range(4):
        spine.alpha_composite(star, ((W - star.width) // 2,
                                     int(H * 0.820) + i * int(star.height * 1.42)))
    print("  %-6s %-14s font %3d -> %4d px (%2.0f%% av ryggen), DreamPage font %d"
          % (locale, TITLES[locale], ts, title.height, 100 * title.height / H, bs))
    return spine.convert("RGB")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    if args.apply:
        os.makedirs(DST_DIR, exist_ok=True)

    for locale in TITLES:
        img = build(locale)
        assert img.size == (W, H), img.size
        staged = os.path.join(OUT_DIR, "ryggrad-%s.png" % locale)
        img.save(staged)
        if args.apply:
            dst = os.path.join(DST_DIR, "ryggrad-%s.png" % locale)
            img.save(dst)
            print("         -> %s" % dst)
    if not args.apply:
        print("\n  TOERRKJOERING - bare staging i %s. Kjoer med --apply." % OUT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())

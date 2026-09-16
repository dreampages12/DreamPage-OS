from __future__ import annotations

import argparse
import os
import sys
import re
import shutil
from typing import Any, Dict, List, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

from dream_pdf_guard import (
    EXPECTED_INNER_PAGES as _DEFAULT_EXPECTED_INNER_PAGES,
    log_inner_page_order,
    validate_inner_pdf_page_count,
)

# Denne boka har Lastpage(enhjørning).png som ekstra siste innerside etter blank-back,
# så total innersider er 31 (default er 30 for bøker uten Lastpage).
EXPECTED_INNER_PAGES = 31
from gelato_cover import build_gelato_cover_pdf

try:
    from dream_text_layout import draw_text
except Exception as exc:  # pragma: no cover - visible in n8n logs
    print("Kunne ikke laste felles tekstlayout:", exc)


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


SCRIPT_LOCALES = {"nb", "nn", "en-US", "en-GB", "sv"}
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
BACK_LOGO_PATH = os.path.join(SCRIPT_DIR, "DreamPage_logo.png")

COVER_FONT = os.path.join(SCRIPT_DIR, "PlayfairDisplay.ttf")
COVER_TITLE_FONT = os.path.join(SCRIPT_ROOT_DIR, "pre", "Fredoka-Bold.ttf")
INNER_FONT = os.path.join(SCRIPT_DIR, "Georgia.ttf")

ENHJORNING_DREAMPAGE_FIRST = os.path.join(
    DP_ROOT, "books", "enhjorning", "dreampage-first-rosa.png"
)
DREAMPAGE_FIRST_TAGLINE = "Tryckt med omtanke för\nkvalitet"
BACK_TEXT_FONT = os.path.join(globals().get("SCRIPT_ROOT_DIR", os.path.dirname(SCRIPT_DIR)), "pre", "Fredoka.ttf")

TEXT_COLOR = "#FFFFFF"
STROKE_COLOR = "#000000"

INNER_WIDTH = 2048
INNER_HEIGHT = 1024
LULU_DPI = 300
LULU_PAGE_PX = 2625

LEFT_X1 = 105
LEFT_X2 = 855
RIGHT_X1 = 1190
RIGHT_X2 = 1940
MARGIN_Y = 300
DEFAULT_FONT_SIZE = 35

COVER_DPI = 300
LULU_COVER_W_IN = 19.0
LULU_COVER_H_IN = 10.25

COVER_TOP_MARGIN = 0.034
COVER_LINE_SPACING = 0.020
COVER_SMALL_SIZE = 340
COVER_LARGE_SIZE = 400
COVER_GRADIENT = ((255, 255, 255), (255, 255, 255))
COVER_SHADOW = (0, 0, 0)
COVER_LOGO_SCALE = 0.78
COVER_LOGO_X_OFFSET = 0
COVER_LOGO_SHADOW = (0, 0, 0)


def in_to_px(value: float, dpi: int = COVER_DPI) -> int:
    return int(round(value * dpi))


def pformat(text: str, child_name: str) -> str:
    return (
        text.replace("[NAVN]", child_name)
        .replace("[ NAVN ]", child_name)
        .replace("(navn)", child_name)
        .replace("(Navn)", child_name)
        .replace("{{name}}", child_name)
        .replace("{{['name']}}", child_name)
    )


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> Tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def draw_gradient_text(
    img: Image.Image,
    text: str,
    position: Tuple[int, int],
    font: ImageFont.FreeTypeFont,
    colors: Tuple[Tuple[int, int, int], Tuple[int, int, int]],
    shadow: Tuple[int, int, int],
) -> None:
    x, y = position
    mask = Image.new("L", img.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text((x, y), text, font=font, fill=255)

    shadow_offset = max(4, int(font.size * 0.018))
    shadow_mask = Image.new("L", img.size, 0)
    shadow_draw = ImageDraw.Draw(shadow_mask)
    shadow_draw.text((x + shadow_offset, y + shadow_offset), text, font=font, fill=255)
    shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(max(3, int(font.size * 0.018))))
    shadow_mask = shadow_mask.point(lambda value: int(value * 0.72))
    shadow_layer = Image.new("RGBA", img.size, (*shadow, 0))
    shadow_layer.putalpha(shadow_mask)
    img.alpha_composite(shadow_layer)

    bbox = mask.getbbox()
    if not bbox:
        return
    _, y0, _, y1 = bbox
    height = max(1, y1 - y0)

    gradient = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gradient_draw = ImageDraw.Draw(gradient)
    for yy in range(y0, y1):
        t = (yy - y0) / height
        color = (
            int(colors[0][0] + (colors[1][0] - colors[0][0]) * t),
            int(colors[0][1] + (colors[1][1] - colors[0][1]) * t),
            int(colors[0][2] + (colors[1][2] - colors[0][2]) * t),
            255,
        )
        gradient_draw.line((bbox[0], yy, bbox[2], yy), fill=color)

    img.alpha_composite(Image.composite(gradient, Image.new("RGBA", img.size), mask))


def fit_font(draw: ImageDraw.ImageDraw, text: str, size: int, max_width: int) -> ImageFont.FreeTypeFont:
    current = size
    while current > 80:
        font = ImageFont.truetype(COVER_FONT, current)
        width, _ = text_size(draw, text, font)
        if width <= max_width:
            return font
        current -= 6
    return ImageFont.truetype(COVER_FONT, current)


def resolve_front_cover_logo() -> str:
    """Return the market-specific front-cover logo for line 2."""
    locale_logo = {
        "nb": "enhjorning-logo-nb.png",
        "nn": "enhjorning-logo-nb.png",
        "en-US": "enhjorning-logo-en.png",
        "en-GB": "enhjorning-logo-en.png",
        "sv": "enhjorning-logo-sv.png",
    }.get(SCRIPT_LOCALE, "enhjorning-logo-nb.png")
    return os.path.join(LOGO_DIR, locale_logo)


def remove_white_background(img: Image.Image, thresh: int = 25) -> Image.Image:
    img = img.convert("RGBA")
    data = []
    for r, g, b, a in img.getdata():
        if r > 255 - thresh and g > 255 - thresh and b > 255 - thresh:
            data.append((r, g, b, 0))
        else:
            data.append((r, g, b, a))
    img.putdata(data)
    return img


def trim_logo_alpha(img: Image.Image) -> Image.Image:
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
    alpha = img.getchannel("A")
    min_coverage = max(1, int(img.width * 0.02))
    rows = [y for y in range(img.height) if sum(1 for px in alpha.crop((0, y, img.width, y + 1)).getdata() if px > 0) >= min_coverage]
    if rows:
        img = img.crop((0, rows[0], img.width, rows[-1] + 1))
    return img


def draw_centered_title_cover(img: Image.Image, text: str) -> None:
    base = img.convert("RGBA")
    draw = ImageDraw.Draw(base)
    width, height = base.size
    line1 = (text.split("\n")[0] if text else "").strip()

    max_width = int(width * 0.92)
    line1_size = max(20, int(width * 0.095))
    title_font_path = COVER_TITLE_FONT if os.path.exists(COVER_TITLE_FONT) else COVER_FONT
    font1 = ImageFont.truetype(title_font_path, line1_size)
    while text_size(draw, line1, font1)[0] > max_width and line1_size > 20:
        line1_size -= 4
        font1 = ImageFont.truetype(title_font_path, line1_size)

    w1, h1 = text_size(draw, line1, font1)
    y1 = int(height * COVER_TOP_MARGIN)
    draw_gradient_text(base, line1, ((width - w1) // 2, y1), font1, COVER_GRADIENT, COVER_SHADOW)

    logo_path = resolve_front_cover_logo()
    if not os.path.exists(logo_path):
        print(f"Warning: front cover logo missing: {logo_path}")
        img.paste(base.convert(img.mode))
        return

    logo = trim_logo_alpha(remove_white_background(Image.open(logo_path)))
    if logo.width <= 0 or logo.height <= 0:
        print(f"Warning: front cover logo is empty after trimming: {logo_path}")
        img.paste(base.convert(img.mode))
        return

    target_w = int(width * COVER_LOGO_SCALE)
    target_h = int(logo.height * (target_w / logo.width))
    logo = logo.resize((target_w, target_h), Image.LANCZOS)

    y2 = y1 + h1 - int(h1 * 0.15) + int(height * COVER_LINE_SPACING)
    x2 = (width - target_w) // 2 + COVER_LOGO_X_OFFSET

    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow_alpha = logo.getchannel("A").filter(ImageFilter.GaussianBlur(max(8, int(target_h * 0.20))))
    shadow_layer = Image.new("RGBA", logo.size, (*COVER_LOGO_SHADOW, 180))
    shadow_layer.putalpha(shadow_alpha)
    shadow.alpha_composite(shadow_layer, (x2 + max(2, int(target_h * 0.04)), y2 + max(2, int(target_h * 0.05))))

    base.alpha_composite(shadow)
    base.alpha_composite(logo, (x2, y2))
    img.paste(base.convert(img.mode))


def save_split_a5(img: Image.Image, out_dir: str, base_filename: str) -> List[str]:
    width, height = img.size
    mid = width // 2
    left = img.crop((0, 0, mid, height)).resize((LULU_PAGE_PX, LULU_PAGE_PX), Image.LANCZOS).convert("RGB")
    right = img.crop((mid, 0, width, height)).resize((LULU_PAGE_PX, LULU_PAGE_PX), Image.LANCZOS).convert("RGB")

    stem, _ = os.path.splitext(base_filename)
    left_path = os.path.join(out_dir, f"{stem}_L.png")
    right_path = os.path.join(out_dir, f"{stem}_R.png")
    os.makedirs(out_dir, exist_ok=True)
    left.save(left_path)
    right.save(right_path)
    print("Lagret:", left_path)
    print("Lagret:", right_path)
    return [left_path, right_path]


def story_block(
    text: str,
    child_name: str,
    highlights: List[str],
    *,
    side: str,
    font_size: int = DEFAULT_FONT_SIZE,
    x_offset: int = 0,
    y_offset: int = 0,
    width_offset: int = 0,
    color: str = TEXT_COLOR,
) -> Dict[str, Any]:
    return {
        "text": pformat(text, child_name),
        "font_size": font_size,
        "color": color,
        "highlights": [child_name, *highlights],
        "x_offset": x_offset,
        "y_offset": y_offset,
        "width_offset": width_offset,
        "side": side,
    }


def build_pages(child_name: str) -> List[Dict[str, Any]]:
    title = f"{child_name} og\nEnhjørningsdalen"

    story: List[Dict[str, Any]] = [
        {
            "filename": "01(enhjorning).png",
            "side": "left",
            "block": story_block(
                "En helt vanlig eftermiddag gick (navn) i skogen.\n"
                "Mitt i den mjuka jorden låg något märkligt.\n"
                "Små hovspår, tätt efter varandra.\n"
                "Och varje enda spår glittrade svagt som silver."
                ,
                child_name,
                ["hovspår", "glittrade", "silver", "märkligt"],
                side="left",
            ),
        },
        {
            "filename": "02(enhjorning).png",
            "side": "right",
            "block": story_block(
                "(navn) följde spåren djupare in i skogen.\n"
                "Små ljus svävade mellan träden, och okända blommor slog ut.\n"
                "Till slut stannade hovspåren framför ett högt vattenfall.\n"
                "Bakom vattnet lyste något svagt och gyllene."
                ,
                child_name,
                ["spåren", "ljus", "blommor", "vattenfall", "gyllene"],
                side="right",
            ),
        },
        # Side 3 - venstre kvadrat (statisk handbilde, baerer teksten)
        {
            "filename": "03(enhjorning-left).png",
            "side": "left",
            "square": True,
            "no_split": True,
            "box_frac": [0.07, 0.05, 0.93, 0.34],
            "block": story_block(
                "(navn) sträckte handen försiktigt in i vattenfallet.\n"
                "Vattnet var ljummet, och det glittrade runt fingrarna.\n"
                "Bakom fallet låg en smal tunnel i berget.\n"
                "(navn) gick igenom, och hela dalen öppnade sig."
                ,
                child_name,
                ["handen", "vattenfallet", "glittrade", "tunnel", "dalen"],
                side="left",
            ),
        },
        # Side 3 - hoyre kvadrat (comfy-headswap, ingen tekst)
        {
            "filename": "03(enhjorning-right).png",
            "side": "right",
            "square": True,
        },
        {
            "filename": "04(enhjorning).png",
            "side": "right",
            "block": story_block(
                "En liten enhörning kom springande bland blommorna.\n"
                "Den stannade rakt framför (navn) och såg på henne.\n"
                "Men hornet lyste bara svagt.\n"
                "Så skakade marken, och ett djupt dån kom från bergen."
                ,
                child_name,
                ["enhörning", "hornet", "svagt", "dån"],
                side="right",
            ),
        },
        {
            "filename": "05(enhjorning).png",
            "side": "left",
            "block": story_block(
                "Enhörningen sprang mot en stor, klar sjö.\n"
                "Ovanför vattnet svävade tre lysande stjärnstenar.\n"
                "En blå, en grön och en lila.\n"
                "Men platsen där den fjärde skulle ha varit var mörk."
                ,
                child_name,
                ["sjö", "stjärnstenar", "blå", "grön", "lila", "mörk"],
                side="left",
            ),
        },
        {
            "filename": "06(enhjorning).png",
            "side": "right",
            "block": story_block(
                "Den äldsta enhörningen kom fram till vattenbrynet.\n"
                "Hornet sken, och en bild dök upp i sjön.\n"
                "(navn) såg en mörk gestalt smyga mellan träden.\n"
                "Den fjärde stjärnstenen var stulen."
                ,
                child_name,
                ["äldsta", "Hornet", "bild", "gestalt", "stulen"],
                side="right",
            ),
        },
        {
            "filename": "07(enhjorning).png",
            "side": "left",
            "block": story_block(
                "Utan stenen skulle magin i dalen försvinna.\n"
                "Den lilla enhörningen stampade bestämt i marken.\n"
                "Tillsammans följde de ett spår av svarta, glittrande märken.\n"
                "Spåret ledde dem långt bort från sjön."
                ,
                child_name,
                ["magin", "bestämt", "spår", "märken"],
                side="left",
            ),
        },
        {
            "filename": "08(enhjorning).png",
            "side": "right",
            "block": story_block(
                "Stigen förde dem in i Kristallskogen.\n"
                "Enorma genomskinliga träd kastade regnbågar över marken.\n"
                "Plötsligt började grenarna röra sig.\n"
                "Stigen bakom dem försvann, och de var fångade."
                ,
                child_name,
                ["Kristallskogen", "regnbågar", "grenarna", "fångade"],
                side="right",
            ),
        },
        {
            "filename": "09(enhjorning).png",
            "side": "left",
            "block": story_block(
                "(navn) hittade de mörka spåren igen på marken.\n"
                "De följde dem hela vägen ut på andra sidan.\n"
                "Framför dem låg en djup klyfta.\n"
                "På kanten stod ett litet hus som lyste i mörkret."
                ,
                child_name,
                ["spåren", "klyfta", "litet hus", "lyste"],
                side="left",
            ),
        },
        {
            "filename": "10(enhjorning).png",
            "side": "right",
            "block": story_block(
                "En gammal stenbro sträckte sig över klyftan.\n"
                "Försiktigt gick de ut på de gamla stenarna.\n"
                "Mitt på bron kom ett nytt dån, och stenarna sprack.\n"
                "(navn) hann precis över till andra sidan."
                ,
                child_name,
                ["stenbro", "klyftan", "dån", "sprack"],
                side="right",
            ),
        },
        {
            "filename": "11(enhjorning).png",
            "side": "left",
            "block": story_block(
                "Inne i huset låg stjärnstenen på en pelare.\n"
                "(navn) lyfte upp den mycket försiktigt.\n"
                "Med ens lyste hela rummet.\n"
                "På väggen syntes en stor symbol: en svart halvmåne."
                ,
                child_name,
                ["stjärnstenen", "pelare", "lyste", "halvmåne"],
                side="left",
            ),
        },
        {
            "filename": "12(enhjorning).png",
            "side": "right",
            "block": story_block(
                "De skyndade sig tillbaka till sjön.\n"
                "När stenen kom på plats sköt fyra ljusstrålar mot himlen.\n"
                "Magin strömmade tillbaka genom hela dalen.\n"
                "Blommorna vaknade, och floderna glittrade igen."
                ,
                child_name,
                ["ljusstrålar", "Magin", "vaknade", "glittrade"],
                side="right",
            ),
        },
        {
            "filename": "13(enhjorning).png",
            "side": "left",
            "block": story_block(
                "Hela flocken samlades runt (navn).\n"
                "Den äldsta enhörningen böjde huvudet mot henne.\n"
                "Ett litet silvermärke började glöda på hennes hand.\n"
                "(navn) hade blivit en vän till Enhörningsdalen."
                ,
                child_name,
                ["flocken", "äldsta", "silvermärke", "vän"],
                side="left",
            ),
        },
        {
            "filename": "14(enhjorning).png",
            "side": "right",
            "block": story_block(
                "På kvällen var (navn) hemma igen.\n"
                "Men utanför huset låg ett svart, glittrande spår.\n"
                "Bredvid det låg en sten med en svart halvmåne.\n"
                "Och långt borta lyste något lila mellan bergen."
                ,
                child_name,
                ["hemma", "spår", "halvmåne", "lila"],
                side="right",
            ),
        },
    ]
    pages: List[Dict[str, Any]] = [
        {"filename": "forside(enhjorning).png", "type": "cover", "text": title},
        {"filename": "ryggrad.png", "type": "cover"},
        {
            "filename": "blank.png",
            "type": "blank",
            "text": title,
            "blocks": [
                {
                    "text": pformat(
                        "Den här boken är gjord speciellt för dig, (Navn).\n"
                        "Du är hjälten i ett äventyr fyllt av färger, mod och magi.\n"
                        "Må berättelsen påminna dig om att ditt hjärta vet vägen.",
                        child_name,
                    ),
                    "font_size": 116,
                    "color": "#17121F",
                    "highlights": [
                        child_name,
                        "hjälten",
                        "färger",
                        "mod",
                        "magi",
                        "hjärta",
                    ],
                    "y_offset": 480,
                }
            ],
        },
    ]

    for item in story:
        block = item.get("block")
        page: Dict[str, Any] = {
            "filename": item["filename"],
            "type": "inner",
            "side": item.get("side") or (block["side"] if block else "left"),
            "blocks": [block] if block else [],
        }
        # Kvadratsider (03 venstre/hoyre) baerer egne layout-flagg.
        for key in ("square", "no_split", "box_frac"):
            if key in item:
                page[key] = item[key]
        pages.append(page)

    pages.extend(
        [
            {
                "filename": "blank-back.png",
                "type": "inner",
                "side": "left",
                "blank_only": True,
            },
            {
                "filename": "Lastpage(enhjørning).png",
                "type": "inner",
                "side": "right",
                "blank_only": True,
            },
            {
                "filename": "bakside(enhjorning).png",
                "type": "cover",
                "side": "left",
                "blocks": [
                    {
                        "text": pformat(
                            "När (navn) hittade glittrande hovspår i skogen ledde de till en dal ingen kände till.\n"
                            "I Enhörningsdalen är en av de fyra stjärnstenarna stulen, och magin håller på att slockna.\n"
                            "Tillsammans med en liten enhörning följer (navn) ett mörkt spår genom Kristallskogen, över en spräckt stenbro och in i ett litet hus i berget.\n"
                            "En personlig berättelse om mod, vänskap och om att våga följa spåret man ser.\n"
                            "Vissa äventyr är ändå på riktigt.",
                            child_name,
                        ),
                        "font_size": 82,
                        "color": "#FFFFFF",
                        "highlights": [
                            child_name,
                            "Enhörningsdalen",
                            "stjärnstenarna",
                            "magin",
                            "Kristallskogen",
                            "mod",
                            "vänskap",
                            "riktigt",
                        ],
                    }
                ],
            },
        ]
    )

    return pages


def render_blank_page(page: Dict[str, Any], out_dir: str) -> List[str]:
    blank_path = _dp_first(ENHJORNING_DREAMPAGE_FIRST)
    if not os.path.exists(blank_path):
        raise FileNotFoundError("Fant ikke dreampage-first.png i script-mappen")

    img = Image.open(blank_path).convert("RGBA")
    draw = ImageDraw.Draw(img)
    width, height = img.size

    title_font = ImageFont.truetype(COVER_FONT, max(90, int(width * 0.075)))
    title = page.get("text", "")
    title_lines = title.split("\n")
    y = int(height * 0.16)
    for line in title_lines:
        tw, th = text_size(draw, line, title_font)
        draw.text(((width - tw) // 2, y), line, font=title_font, fill="#17121F")
        y += th + 16

    for block in page.get("blocks", []):
        font = ImageFont.truetype(INNER_FONT, block.get("font_size", 38))
        box = (
            int(width * 0.05),
            int(height * 0.30) + int(block.get("y_offset", 0)),
            int(width * 0.95),
            int(height * 0.88),
        )
        draw_text(
            draw=draw,
            text=block["text"],
            box=box,
            font=font,
            color=block.get("color", "#17121F"),
            stroke_color=STROKE_COLOR,
            line_spacing=max(18, int(font.size * 0.20)),
            highlights=block.get("highlights", []),
            gradient=None,
            img=img,
            align="center",
            shadow=False,
        )

    # --- Tagline (rendret av scriptet, over "© 2026 DreamPage") ---
    _dpf_tag_lines = DREAMPAGE_FIRST_TAGLINE.splitlines()
    _dpf_tag_fs = int(height * 0.033)
    try:
        _dpf_tag_font = ImageFont.truetype(COVER_FONT, _dpf_tag_fs)
    except Exception:
        _dpf_tag_font = ImageFont.load_default()
    _dpf_tag_gap = int(_dpf_tag_fs * 0.30)
    _dpf_tag_dims = [draw.textbbox((0, 0), _t, font=_dpf_tag_font) for _t in _dpf_tag_lines]
    _dpf_tag_total = sum((b[3] - b[1]) for b in _dpf_tag_dims) + _dpf_tag_gap * (len(_dpf_tag_lines) - 1)
    _dpf_ty = int(height * 0.735) - _dpf_tag_total // 2
    for _t, _b in zip(_dpf_tag_lines, _dpf_tag_dims):
        _dpf_lw = _b[2] - _b[0]
        draw.text(((width - _dpf_lw) // 2, _dpf_ty), _t, font=_dpf_tag_font, fill=(35, 30, 25, 255))
        _dpf_ty += (_b[3] - _b[1]) + _dpf_tag_gap
    out_path = os.path.join(out_dir, "blank.png")
    os.makedirs(out_dir, exist_ok=True)
    img.convert("RGB").save(out_path)
    print("Lagret intro-side med tekst:", out_path)
    return [out_path]


# ------------------------ ryggrad per språk (script/ryggrad/<book-slug>/) ------------------------
RYGGRAD_BOOK_SLUG = "enhjorning"
RYGGRAD_LOCALES = {"nb", "nn", "en-US", "en-GB", "sv"}


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
#  1:1 KVADRATSIDE (ingen A5-splitt) - brukt for side 03 venstre/hoyre.
#  Kolonnene er de vanlige venstre-/hoyrekolonnene flyttet inn i
#  kvadratets eget 1024-rom, slik at teksten havner samme sted paa
#  skjermen som paa en vanlig halvside.
# ------------------------------------------------------------
SQUARE_DESIGN = 1024
SQ_LEFT_X1, SQ_LEFT_X2 = LEFT_X1, LEFT_X2
SQ_RIGHT_X1, SQ_RIGHT_X2 = RIGHT_X1 - SQUARE_DESIGN, RIGHT_X2 - SQUARE_DESIGN


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

    y_top = sq(MARGIN_Y)
    y_bottom = sq(SQUARE_DESIGN - 95)

    # box_frac lar en side sette tekstboksen eksplisitt (andeler av bildet)
    # naar motivet ikke gir plass i standardkolonnen. Brukes for 03-venstre.
    box_frac = page.get("box_frac")
    if box_frac:
        x1 = int(img_w * box_frac[0])
        y_top = int(img_h * box_frac[1])
        x2 = int(img_w * box_frac[2])
        y_bottom = int(img_h * box_frac[3])

    for block in page.get("blocks", []):
        font_size = max(18, int(block.get("font_size", DEFAULT_FONT_SIZE) * s))
        font = ImageFont.truetype(INNER_FONT, font_size)
        bx1 = x1 + (0 if box_frac else sq(block.get("x_offset", 0)))
        bx2 = x2 + (0 if box_frac else sq(block.get("width_offset", 0)))
        by1 = y_top + (0 if box_frac else sq(block.get("y_offset", 0)))
        box = (bx1, by1, bx2, y_bottom)

        text_line_spacing = max(8, int(14 * s))
        if block.get("text_backdrop", False):
            draw_text_backdrop(img, box, block["text"], font, text_line_spacing,
                               highlights=block.get("highlights", []), align="center",
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
            gradient=None,
            img=img,
            align="center",
            shadow=True,
            shadow_alpha=110,
        )

    out_name = os.path.splitext(os.path.basename(page["filename"]))[0] + ".png"
    out_path = os.path.join(out_dir, out_name)
    os.makedirs(out_dir, exist_ok=True)
    img.convert("RGB").save(out_path)
    print("Lagret (square):", out_path)
    return [out_path]


def render_page(page: Dict[str, Any], base_dir: str, out_dir: str) -> List[str]:
    if page.get("blank_only"):
        # Prefer locale Lastpage(*).png from script/lastpages/<locale>;
        # fall back to base/script only for legacy blank-back.png.
        source = resolve_final_inner_path(page["filename"], base_dir)
        if source is None:
            return []
        out_path = os.path.join(out_dir, page["filename"])
        os.makedirs(out_dir, exist_ok=True)
        Image.open(source).convert("RGB").save(out_path)
        print("Lagret final inner/back page:", out_path)
        return [out_path]

    if page.get("type") == "blank":
        return render_blank_page(page, out_dir)

    base_path = os.path.join(base_dir, page["filename"])
    if page["filename"].lower() == "ryggrad.png":
        ryggrad_src = resolve_ryggrad_path(base_dir)
        if ryggrad_src:
            base_path = ryggrad_src

    if os.path.basename(page.get("filename", "")).lower().startswith("bakside"):
        _bakside = resolve_bakside_path(page["filename"], base_dir)
        if _bakside:
            base_path = _bakside
    if not os.path.exists(base_path):
        raise FileNotFoundError(f"Fant ikke bilde: {base_path}")

    if page.get("square"):
        return _render_square_page(page, base_path, out_dir)

    img = Image.open(base_path).convert("RGBA")
    draw = ImageDraw.Draw(img)
    img_w, img_h = img.size
    scale_x = img_w / INNER_WIDTH
    scale_y = img_h / INNER_HEIGHT
    scale = min(scale_x, scale_y)

    def sx(value: int) -> int:
        return int(value * scale_x)

    def sy(value: int) -> int:
        return int(value * scale_y)

    if page.get("type") == "cover":
        if page["filename"].lower().startswith("forside"):
            draw_centered_title_cover(img, page.get("text", ""))
        elif page["filename"].lower().startswith("bakside"):
            x1 = int(img_w * 0.06)
            x2 = int(img_w * 0.94)
            y1 = int(img_h * 0.13)
            y2 = int(img_h * 0.80)
            for block in page.get("blocks", []):
                back_font_path = BACK_TEXT_FONT if os.path.exists(BACK_TEXT_FONT) else INNER_FONT
                font = ImageFont.truetype(back_font_path, max(18, int(block.get("font_size", 34) * scale)))
                draw_text(
                    draw=draw,
                    text=block["text"],
                    box=(x1, y1, x2, y2),
                    font=font,
                    color=block.get("color", TEXT_COLOR),
                    stroke_color=STROKE_COLOR,
                    line_spacing=max(6, int(16 * scale_y)),
                    highlights=block.get("highlights", []),
                    gradient=None,
                    img=img,
                    align="center",
                    shadow=True,
                    shadow_alpha=110,
                )

            try:
                logo = Image.open(BACK_LOGO_PATH).convert("RGBA")
                max_logo_width = int(img_w * 0.27)
                logo_scale = min(max_logo_width / logo.width, 1.0)
                logo = logo.resize((int(logo.width * logo_scale), int(logo.height * logo_scale)), Image.LANCZOS)
                img.alpha_composite(logo, ((img_w - logo.width) // 2, img_h - logo.height - int(img_h * 0.06)))
            except FileNotFoundError:
                print("Fant ikke bakside-logo:", BACK_LOGO_PATH)

        out_path = os.path.join(out_dir, page["filename"])
        os.makedirs(out_dir, exist_ok=True)
        img.convert("RGB").save(out_path)
        print("Lagret:", out_path)
        return [out_path]

    side = page.get("side", "right")
    if side == "left":
        x1, x2 = sx(LEFT_X1), sx(LEFT_X2)
    else:
        x1, x2 = sx(RIGHT_X1), sx(RIGHT_X2)

    for block in page.get("blocks", []):
        font_size = max(18, int(block.get("font_size", DEFAULT_FONT_SIZE) * scale))
        font = ImageFont.truetype(INNER_FONT, font_size)
        bx1 = x1 + sx(block.get("x_offset", 0))
        bx2 = x2 + sx(block.get("width_offset", 0))
        by1 = sy(MARGIN_Y + block.get("y_offset", 0))
        by2 = sy(INNER_HEIGHT - 95)

        text_line_spacing = max(8, int(14 * scale_y))
        if block.get("text_backdrop", False):
            draw_text_backdrop(img, (bx1, by1, bx2, by2), block["text"], font, text_line_spacing, highlights=block.get("highlights", []), align="center", strength=block.get("text_backdrop_strength", "normal"))

        draw_text(
            draw=draw,
            text=block["text"],
            box=(bx1, by1, bx2, by2),
            font=font,
            color=block.get("color", TEXT_COLOR),
            stroke_color=STROKE_COLOR,
            line_spacing=text_line_spacing,
            highlights=block.get("highlights", []),
            gradient=None,
            img=img,
            align="center",
            shadow=True,
            shadow_alpha=110,
        )

    return save_split_a5(img, out_dir, page["filename"])


def build_inner_pdf(inner_paths: List[str], out_dir: str, child_name: str) -> str:
    inner_pdf_path = os.path.join(out_dir, f"{child_name}_innersider.pdf")
    ordered_paths = log_inner_page_order(
        inner_paths,
        script_name=os.path.basename(__file__),
        expected_count=EXPECTED_INNER_PAGES,
    )

    page_size = 8.5 * inch
    pdf = canvas.Canvas(inner_pdf_path, pagesize=(page_size, page_size))
    tmp_dir = os.path.join(out_dir, "_pdf_tmp_inner")
    os.makedirs(tmp_dir, exist_ok=True)

    for index, path in enumerate(ordered_paths):
        im = Image.open(path).convert("RGB")
        if im.size != (LULU_PAGE_PX, LULU_PAGE_PX):
            im = im.resize((LULU_PAGE_PX, LULU_PAGE_PX), Image.LANCZOS)
        tmp_path = os.path.join(tmp_dir, f"page_{index:04d}.jpg")
        im.save(tmp_path, "JPEG", quality=95)
        pdf.drawImage(tmp_path, 0, 0, width=page_size, height=page_size)
        pdf.showPage()

    pdf.save()
    validate_inner_pdf_page_count(inner_pdf_path, EXPECTED_INNER_PAGES)
    print("Innersider PDF lagret:", inner_pdf_path)
    return inner_pdf_path


def make_preview_cover_pdf(back_path: str, spine_path: str, front_path: str, out_path: str) -> None:
    page_w = LULU_COVER_W_IN * inch
    page_h = LULU_COVER_H_IN * inch
    cover = canvas.Canvas(out_path, pagesize=(page_w, page_h))
    panel_w = page_w / 2
    cover.drawImage(back_path, 0, 0, width=panel_w, height=page_h)
    cover.drawImage(front_path, panel_w, 0, width=panel_w, height=page_h)
    # Spine preview is intentionally centered and narrow; Gelato rebuilds exact geometry below.
    cover.drawImage(spine_path, panel_w - (0.25 * inch / 2), 0, width=0.25 * inch, height=page_h)
    cover.showPage()
    cover.save()


def process_book(base_dir: str, out_dir: str, child_name: str, cover_type: str, gelato_api_key: str | None) -> None:
    os.makedirs(out_dir, exist_ok=True)

    all_paths: List[str] = []
    for page in build_pages(child_name):
        all_paths.extend(render_page(page, base_dir, out_dir))

    cover_paths: Dict[str, str] = {}
    inner_paths: List[str] = []
    for path in all_paths:
        name = os.path.basename(path).lower()
        if name.startswith("forside") or name.startswith("bakside") or name == "ryggrad.png":
            cover_paths[name] = path
        else:
            inner_paths.append(path)

    inner_pdf_path = build_inner_pdf(inner_paths, out_dir, child_name)

    need = ["bakside(enhjorning).png", "ryggrad.png", "forside(enhjorning).png"]
    missing = [name for name in need if name not in cover_paths]
    if missing:
        raise FileNotFoundError("Cover PDF ble ikke laget. Mangler: " + ", ".join(missing))

    back_path = cover_paths["bakside(enhjorning).png"]
    spine_path = cover_paths["ryggrad.png"]
    front_path = cover_paths["forside(enhjorning).png"]
    cover_pdf_path = os.path.join(out_dir, f"{child_name}_cover.pdf")

    make_preview_cover_pdf(back_path, spine_path, front_path, cover_pdf_path)
    print("Cover PDF lagret (preview):", cover_pdf_path)

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
        print("Ingen Gelato API key satt; beholdt preview cover PDF.")

    keep = {os.path.basename(inner_pdf_path), os.path.basename(cover_pdf_path)}
    for filename in os.listdir(out_dir):
        path = os.path.join(out_dir, filename)
        if filename in keep:
            continue
        if os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)


def main() -> None:
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




# --- DreamPage translated text table (sv) ---
_DREAMPAGE_TRANSLATIONS = {
  "{name} og\nEnhjørningsdalen": "{name} och\nEnhörningsdalen",
  "Denne boken er laget spesielt for deg, {name}.\nDu er helten i et eventyr fylt med farger, mot og magi.\nMå historien minne deg på at hjertet ditt vet veien.": "Den här boken är skapad särskilt för dig, {name}.\nDu är hjälten i ett äventyr fyllt av färger, mod och magi.\nMå berättelsen påminna dig om att ditt hjärta vet vägen.",
  "Det var en gang en jente som het {name}.\nHun elsket farger, fantasi og historier om skjulte verdener.\nOfte føltes det som om noe ventet på henne.\nSom om eventyret bare manglet det riktige øyeblikket.": "Det var en gång en flicka som hette {name}.\nHon älskade färger, fantasi och berättelser om dolda världar.\nOfta kändes det som om något väntade på henne.\nSom om äventyret bara saknade det rätta ögonblicket.",
  "En dag oppdaget {name} noe uvanlig.\nEt svakt spor av regnbuefarger lyste foran henne.\nDet var nesten usynlig, men hun kunne se det.\nOg det føltes som om sporet kalte på henne.": "En dag upptäckte {name} något ovanligt.\nEtt svagt spår av regnbågsfärger lyste framför henne.\nDet var nästan osynligt, men hon kunde se det.\nOch det kändes som om spåret kallade på henne.",
  "{name} stoppet opp og tenkte seg om.\nHun kunne snu og gå tilbake, akkurat som før.\nEller hun kunne følge sporet videre.\nHjertet hennes banket litt raskere.": "{name} stannade upp och tänkte efter.\nHon kunde vända om och gå tillbaka, precis som förut.\nEller så kunde hon följa spåret vidare.\nHennes hjärta slog lite snabbare.",
  "Da {name} tok et steg frem, skjedde det noe.\nLuften rundt henne forandret seg.\nFargene ble sterkere og klarere enn før.\nHun visste at hun hadde funnet noe hemmelig.": "När {name} tog ett steg fram hände något.\nLuften omkring henne förändrades.\nFärgerna blev starkare och klarare än förut.\nHon visste att hon hade hittat något hemligt.",
  "Foran {name} åpnet det seg en dal.\nEn dal full av lys, liv og farger.\nHun hadde aldri sett noe lignende.\nDet var som om verden smilte til henne.": "Framför {name} öppnade sig en dal.\nEn dal full av ljus, liv och färger.\nHon hade aldrig sett något liknande.\nDet var som om världen log mot henne.",
  "Plutselig kjente {name} at hun ikke var alene.\nNoe beveget seg stille i det fjerne.\nHun ble ikke redd, bare nysgjerrig.\nDette stedet føltes trygt og riktig.": "Plötsligt kände {name} att hon inte var ensam.\nNågot rörde sig tyst i fjärran.\nHon blev inte rädd, bara nyfiken.\nDen här platsen kändes trygg och rätt.",
  "Da fikk {name} øye på dem.\nEnhjørningene kom rolig frem, én etter én.\nDe så på henne med kloke, vennlige øyne.\nSom om de hadde ventet på akkurat henne.": "Då fick {name} syn på dem.\nEnhörningarna kom lugnt fram, en efter en.\nDe såg på henne med kloka, vänliga ögon.\nSom om de hade väntat på just henne.",
  "Enhjørningene fortalte om dalen.\nDette stedet var hemmelig og sårbart.\nBare noen få fikk lov til å se det.\nOg nå hvilte ansvaret hos {name}.": "Enhörningarna berättade om dalen.\nDen här platsen var hemlig och sårbar.\nBara några få fick lov att se den.\nOch nu vilade ansvaret hos {name}.",
  "{name} kjente en uro i magen.\nHva om hun ikke var god nok?\nHva om hun gjorde noe feil?\nHun så rundt seg og tok et dypt pust.": "{name} kände en oro i magen.\nTänk om hon inte var tillräckligt bra?\nTänk om hon gjorde fel?\nHon såg sig omkring och tog ett djupt andetag.",
  "Da lyttet {name} til hjertet sitt.\nHun visste ikke alt, men hun visste én ting.\nHun ville gjøre det rette.\nOg noen ganger er det nok.": "Då lyssnade {name} till sitt hjärta.\nHon visste inte allt, men hon visste en sak.\nHon ville göra det rätta.\nOch ibland är det tillräckligt.",
  "Plutselig glødet dalen sterkere igjen.\nFargene blomstret rundt {name}.\nLyset vendte tilbake, klarere enn før.\nValget hennes hadde betydd noe.": "Plötsligt glödde dalen starkare igen.\nFärgerna blommade runt {name}.\nLjuset återvände, klarare än förut.\nHennes val hade betytt något.",
  "Enhjørningene samlet seg rundt {name}.\nDe stolte på henne nå.\nHun følte seg rolig og stolt.\nIkke fordi hun var perfekt, men fordi hun hadde våget.": "Enhörningarna samlades runt {name}.\nDe litade på henne nu.\nHon kände sig lugn och stolt.\nInte för att hon var perfekt, utan för att hon hade vågat.",
  "Det var på tide å dra tilbake.\n{name} visste at hun ikke trengte å være trist.\nNoen farvel betyr ikke slutten.\nDe betyr at noe viktig alltid vil være med deg.": "Det var dags att gå tillbaka.\n{name} visste att hon inte behövde vara ledsen.\nVissa farväl betyder inte slutet.\nDe betyder att något viktigt alltid kommer att finnas med dig.",
  "Verden utenfor så nesten lik ut som før.\nMen {name} var ikke den samme.\nHun bar en hemmelighet i hjertet sitt.\nNoen eventyr er ekte, selv når ikke alle kan se dem.": "Världen utanför såg nästan likadan ut som förut.\nMen {name} var inte densamma.\nHon bar en hemlighet i sitt hjärta.\nVissa äventyr är verkliga, även när inte alla kan se dem.",
  "Denne boken handler om å oppdage noe bare noen få kan se.\nOm å følge et spor når hjertet sier at noe er viktig.\nDen handler om stille mot, om å ta valg og om å ta vare på en hemmelighet.\nI denne historien er det {name} som blir valgt, fordi hun tør å lytte til seg selv.\nEn personlig fortelling som gir barn trygghet, selvtillit og troen på at noen eventyr er ekte.": "Den här boken handlar om att upptäcka något som bara några få kan se.\nOm att följa ett spår när hjärtat säger att något är viktigt.\nDen handlar om stilla mod, om att göra val och om att ta hand om en hemlighet.\nI den här berättelsen är det {name} som blir utvald, för att hon vågar lyssna på sig själv.\nEn personlig berättelse som ger barn trygghet, självförtroende och tron på att vissa äventyr är verkliga."
}
_DREAMPAGE_ORIGINAL_BUILD_PAGES = build_pages

def _dreampage_text_key(text: str, child_name: str) -> str:
    return str(text).replace(child_name, "{name}")

def _dreampage_sv_genitive(child_name: str) -> str:
    clean_name = str(child_name)
    return clean_name if clean_name.lower().endswith(("s", "x", "z")) else clean_name + "s"

def _dreampage_apply_translation(text: str, child_name: str) -> str:
    key = _dreampage_text_key(text, child_name)
    translated = _DREAMPAGE_TRANSLATIONS.get(key)
    if translated is None:
        return text
    return (
        translated
        .replace("{name_genitive}", _dreampage_sv_genitive(child_name))
        .replace("{name}", child_name)
    )

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
    if page.get("no_split") or page.get("square"):
        _dp_mark_backdrop(block, filename, child_name)
        return

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

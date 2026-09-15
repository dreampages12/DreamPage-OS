import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import os
import argparse
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# --------------------------------------------------
# ARGUMENTS (fra n8n)
# --------------------------------------------------

parser = argparse.ArgumentParser()
parser.add_argument("--image", required=True)
parser.add_argument("--out", required=True)

parser.add_argument("--line1", required=True)
parser.add_argument("--line2", default="")          # tekst-fallback (optional når --line2_image brukes)
parser.add_argument("--line2_image", default="")    # NYTT: bruk bilde som andre linje

parser.add_argument("--top_margin", type=float, required=True)
parser.add_argument("--line_spacing", type=float, required=True)

parser.add_argument("--font_small", type=int, required=True)
parser.add_argument("--font_large", type=int, required=True)
parser.add_argument("--font_small_path", default="")
parser.add_argument("--font_large_path", default="")

parser.add_argument("--gold", required=True)     # "R,G,B" eller "R,G,B,R,G,B"
parser.add_argument("--shadow", required=True)   # "R,G,B"

parser.add_argument("--logo_scale", type=float, default=0.38)   # NYTT: bildets bredde som andel av coverbredde
parser.add_argument("--logo_x_offset", type=int, default=0)     # pikselforskyvning høyre (+) / venstre (-)

# Glød bak linje 1. Standardverdiene er nøyaktig den varme stadion-gløden
# som alltid har vært der. En mørk glow_color (f.eks. samme som --shadow)
# gjør den om til en halo som gir hvit tekst kontrast mot lys himmel.
parser.add_argument("--glow_color", default="255,248,215")
parser.add_argument("--glow_opacity", type=float, default=0.55)
parser.add_argument("--glow_radius_scale", type=float, default=0.35)

# Styrken på skyggen bak line2-logoen (0-255). 255 = slik det alltid har vært
# (den gamle 180-verdien ble overskrevet av putalpha og hadde ingen effekt),
# lavere verdi gir en svakere/mykere skygge for bøker som ikke tåler så mye.
parser.add_argument("--logo_shadow_opacity", type=int, default=255)

# Skygge bak tekstlinje 1. 255 + blur 0 = nøyaktig slik det alltid har vært
# (hard, nesten svart drop shadow). Lavere opacity og større blur gir en myk,
# moderne skygge i stedet for den harde 2000-talls-kanten.
parser.add_argument("--shadow_opacity", type=int, default=255)
parser.add_argument("--shadow_blur", type=int, default=0)   # 0 = auto (shadow_offset // 2)

# Nedre DreamPage-logo. Tom sti = standardlogoen ved siden av dette scriptet,
# slik at bøker som ikke sier noe fortsatt ser nøyaktig ut som før.
parser.add_argument("--bottom_logo", default="")
parser.add_argument("--bottom_logo_scale", type=float, default=0.40)   # bredde som andel av coverbredde
parser.add_argument("--bottom_logo_margin", type=float, default=0.03)  # luft under, andel av coverhøyde
parser.add_argument("--bottom_logo_x_offset", type=int, default=0)

# Skygge bak den nedre DreamPage-logoen. 0 = av, slik den alltid har vaert.
# En lav verdi (20-60) gir et svakt loft mot lyse bakgrunner uten aa synes.
parser.add_argument("--bottom_logo_shadow_opacity", type=int, default=0)
parser.add_argument("--bottom_logo_shadow_blur", type=int, default=0)   # 0 = auto (12 % av logohoyden)
parser.add_argument("--bottom_logo_shadow_offset", type=int, default=0)  # 0 = samme lille offset som teksten (4px)

args = parser.parse_args()

# --------------------------------------------------
# INPUT
# --------------------------------------------------

IMAGE_PATH = args.image
OUT_PATH = args.out


def clean(s: str) -> str:
    return (s or "").replace("\\n", " ").replace("\r", " ").replace("\n", " ").strip()


LINE1 = clean(args.line1)
LINE2 = clean(args.line2)
LINE2_IMAGE_PATH = (args.line2_image or "").strip()

print("DEBUG line1:", repr(LINE1))
print("DEBUG line2:", repr(LINE2))
print("DEBUG line2_image:", repr(LINE2_IMAGE_PATH))

FONT_SMALL_SIZE = args.font_small
FONT_LARGE_SIZE = args.font_large

gold_parts = list(map(int, args.gold.split(",")))

if len(gold_parts) == 3:
    GOLD = (tuple(gold_parts), tuple(gold_parts))
elif len(gold_parts) == 6:
    GOLD = (tuple(gold_parts[:3]), tuple(gold_parts[3:]))
else:
    raise ValueError("gold må være 'R,G,B' eller 'R,G,B,R,G,B'")

SHADOW = tuple(map(int, args.shadow.split(",")))

GLOW_COLOR = tuple(map(int, args.glow_color.split(",")))
if len(GLOW_COLOR) != 3:
    raise ValueError("glow_color må være 'R,G,B'")
GLOW_OPACITY = max(0.0, min(1.0, args.glow_opacity))
GLOW_RADIUS_SCALE = max(0.0, args.glow_radius_scale)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def resolve_font_path(value: str, fallback_name: str) -> str:
    font_value = (value or "").strip()
    if font_value:
        if os.path.isabs(font_value):
            return font_value
        return os.path.join(SCRIPT_DIR, font_value)
    return os.path.join(SCRIPT_DIR, fallback_name)

# --------------------------------------------------
# LOAD IMAGE
# --------------------------------------------------

img = Image.open(IMAGE_PATH).convert("RGBA")
draw = ImageDraw.Draw(img)
w, h = img.size
base = min(w, h)

# --------------------------------------------------
# FONT
# --------------------------------------------------

font_large_path = resolve_font_path(args.font_large_path, "PlayfairDisplay.ttf")
font_large = ImageFont.truetype(font_large_path, FONT_LARGE_SIZE)

# Linje 1: Trebuchet MS Bold
font_small_path = resolve_font_path(args.font_small_path, "Trebuchet MS Bold.ttf")
if os.path.exists(font_small_path):
    font_small = ImageFont.truetype(font_small_path, FONT_SMALL_SIZE)
    print(f"Font linje 1: {font_small_path}")
else:
    print(f"ADVARSEL: Fant ikke 'Trebuchet MS Bold.ttf' – faller tilbake til PlayfairDisplay")
    font_small = ImageFont.truetype(font_large_path, FONT_SMALL_SIZE)

print(f"Font linje 2: {font_large_path}")

# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def _make_text_mask(size, x, y, text, font):
    mask = Image.new("L", size, 0)
    d = ImageDraw.Draw(mask)
    d.text((x, y), text, font=font, fill=255)
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

# --------------------------------------------------
# SHADOW SETTINGS
# --------------------------------------------------

size_large = int(base * 0.10)
shadow_offset = max(3, int(size_large * 0.04))

# --------------------------------------------------
# POSITION
# --------------------------------------------------

w1, h1 = draw.textbbox((0, 0), LINE1, font=font_small)[2:]

top = int(h * args.top_margin)
spacing = int(h * args.line_spacing)

x1_pos = (w - w1) // 2
y1_pos = top
descender_cut = int(h1 * 0.15)
y2_pos = y1_pos + h1 - descender_cut + spacing


# --------------------------------------------------
# DRAW TEXT FUNCTION
# --------------------------------------------------

def draw_line(text, font, x, y, glow=False):
    if not text:
        return

    # Valgfri glød – varmt stadionlys bak teksten som standard. Med en mørk
    # glow-farge blir den i stedet en myk halo som løfter hvit tekst fra en
    # lys bakgrunn (himmel/skyer), der den varme gløden bare vasker den ut.
    if glow:
        glow_radius = max(18, int(font.size * GLOW_RADIUS_SCALE))
        gm = _make_text_mask(img.size, x, y, text, font)
        gm = gm.filter(ImageFilter.GaussianBlur(glow_radius))
        gm = gm.point(lambda p: int(p * GLOW_OPACITY))
        glow_r = Image.new("L", img.size, GLOW_COLOR[0])
        glow_g = Image.new("L", img.size, GLOW_COLOR[1])
        glow_b = Image.new("L", img.size, GLOW_COLOR[2])
        glow_layer = Image.merge("RGBA", (glow_r, glow_g, glow_b, gm))
        img.alpha_composite(glow_layer)

    shadow_alpha = max(0, min(255, args.shadow_opacity))
    if shadow_alpha > 0:
        blur = args.shadow_blur if args.shadow_blur > 0 else max(1, shadow_offset // 2)
        sm = _make_text_mask(img.size, x + shadow_offset, y + shadow_offset, text, font)
        sm = sm.filter(ImageFilter.GaussianBlur(blur))
        if shadow_alpha < 255:
            sm = sm.point(lambda p: int(p * shadow_alpha / 255))
        img.paste((*SHADOW, 255), (0, 0), sm)

    tm = _make_text_mask(img.size, x, y, text, font)
    bbox = draw.textbbox((x, y), text, font=font)
    _paste_gradient(img, tm, bbox, GOLD[0], GOLD[1])


# --------------------------------------------------
# DRAW IMAGE-LINE FUNCTION (for line2_image)
# --------------------------------------------------

def remove_white_background(logo_img, thresh=25, defringe_thresh=55):
    # defringe_thresh=0 hopper over defringe-passet
    """
    Trinn 1 – Flood fill fra bildekantene:
      Fjerner all bakgrunns-hvit som er koblet til yttergrensen.
      Bevarer hvite indre høylys inne i bokstavene fordi de er
      omsluttet av fargede konturstrek og ikke er tilgjengelig utenfra.

    Trinn 2 – Defringe-pass:
      Etter flood fill sitter det igjen en tynn ring av nær-hvite piksler
      på innsiden av bokstavkonturene (inner-edge anti-aliasing mellom
      mørk kontur og hvit bokstavflate). Disse er ikke nåbare fra
      bakgrunnen via flood fill, men er synlige som en hvit linje på mørk
      bakgrunn. Denne passet fjerner dem ved å finne alle ugjennomskinnelige
      nær-hvite piksler som er direkte naboer til gjennomsiktige piksler.
    """
    from PIL import ImageDraw as _ID

    logo_rgba = logo_img.convert("RGBA")
    w, h = logo_rgba.size

    # --- Trinn 1: flood fill fra alle kant-frøpunkter ---
    seeds = [
        (0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
        (w // 2, 0), (w // 2, h - 1),
        (0, h // 2), (w - 1, h // 2),
    ]
    for pt in seeds:
        px = logo_rgba.getpixel(pt)
        if px[3] > 0 and max(255 - px[0], 255 - px[1], 255 - px[2]) <= thresh:
            _ID.floodfill(logo_rgba, pt, (0, 0, 0, 0), thresh=thresh)

    # --- Trinn 2: defringe – fjern nær-hvite piksler langs transparente kanter ---
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
                    continue  # farget piksel, behold
                # Er pikselet nabo til en gjennomsiktig piksel?
                for nx, ny in [(x-1, y), (x+1, y), (x, y-1), (x, y+1)]:
                    if 0 <= nx < w and 0 <= ny < h and pix[nx, ny][3] == 0:
                        to_fix.append((x, y, dist))
                        break

        for x, y, dist in to_fix:
            r, g, b, _ = pix[x, y]
            if dist <= 25:
                # Nesten hvit: fjern helt
                pix[x, y] = (r, g, b, 0)
            else:
                # Mjuk overgang: delvis gjennomsiktig fra 0 ved dist=25 til 255 ved dist=defringe_thresh
                alpha = int(255 * (dist - 25) / (defringe_thresh - 25))
                pix[x, y] = (r, g, b, alpha)

    return logo_rgba


def draw_logo_line(logo_path, y_start):
    """
    Laster inn logoen, fjerner hvit bakgrunn, skalerer til logo_scale * cover-bredde,
    sentrerer horisontalt og legger den på y_start.
    Legger på en myk skygge for premium-utseende.
    """
    if not logo_path or not os.path.exists(logo_path):
        print("ADVARSEL: Fant ikke line2_image:", logo_path)
        return

    logo = Image.open(logo_path).convert("RGBA")

    # Fjern hvit bakgrunn med flood fill fra kantene (ingen defringe-pass –
    # flood fill gir rene (0,0,0,0)-piksler som ikke blør inn i kanter under resize,
    # samme som DreamPage-logoen som allerede har ekte transparent bakgrunn).
    logo = remove_white_background(logo, thresh=25, defringe_thresh=0)

    # Beskjær til tight bounding box (fjern tom luft rundt logoen)
    # getbbox() kan fange sparsomme/støy-piksler i tomme rader — bruk
    # en tetthetsgranskning for å trimme rader med < 2 % dekning i tillegg.
    bbox = logo.getbbox()
    if bbox:
        logo = logo.crop(bbox)

    lw, lh = logo.size
    pixels = logo.load()
    threshold = max(1, lw * 2 // 100)   # 2 % av bredden

    top_trim = 0
    for row in range(lh):
        if sum(1 for x in range(lw) if pixels[x, row][3] > 10) >= threshold:
            break
        top_trim = row + 1

    bottom_trim = lh
    for row in range(lh - 1, -1, -1):
        if sum(1 for x in range(lw) if pixels[x, row][3] > 10) >= threshold:
            break
        bottom_trim = row

    if top_trim > 0 or bottom_trim < lh:
        logo = logo.crop((0, top_trim, lw, bottom_trim))
        print(f"  Tett-beskjær: fjernet {top_trim}px topp, {lh - bottom_trim}px bunn → ny høyde {logo.height}px")

    # Skaler til ønsket bredde – samme enkle resize som DreamPage-logoen
    target_w = int(w * args.logo_scale)
    target_h = int(logo.height * (target_w / logo.width))
    logo = logo.resize((target_w, target_h), Image.LANCZOS)

    lx = (w - target_w) // 2 + args.logo_x_offset

    # --- Skygge under logoen (myk, naturlig) ---
    shadow_opacity = max(0, min(255, args.logo_shadow_opacity))
    if shadow_opacity > 0:
        shadow_blur = max(8, int(target_h * 0.20))
        shadow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        logo_alpha = logo.split()[3]
        if shadow_opacity < 255:
            logo_alpha = logo_alpha.point(lambda p: int(p * shadow_opacity / 255))
        shadow_img = Image.new("RGBA", (target_w, target_h), (*SHADOW, 255))
        shadow_img.putalpha(logo_alpha)
        shadow_layer.paste(shadow_img, (lx + shadow_offset, y_start + shadow_offset))
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(shadow_blur))
        img.alpha_composite(shadow_layer)
        print(f"  Logo-skygge: opacity {shadow_opacity}/255, blur {shadow_blur}px")
    else:
        print("  Logo-skygge: av (logo_shadow_opacity=0)")

    # --- Selve logoen ---
    img.alpha_composite(logo, (lx, y_start))

    print(f"Lagt inn logo-bilde: {logo_path}  ({target_w}x{target_h}) @ ({lx},{y_start})")


# --------------------------------------------------
# RENDER
# --------------------------------------------------

# Linje 1 (tekst – alltid, med glød)
draw_line(LINE1, font_small, x1_pos, y1_pos, glow=True)

# Linje 2 – bilde hvis --line2_image er satt, ellers tekst
if LINE2_IMAGE_PATH:
    draw_logo_line(LINE2_IMAGE_PATH, y2_pos)
else:
    w2, h2 = draw.textbbox((0, 0), LINE2, font=font_large)[2:]
    x2_pos = (w - w2) // 2
    draw_line(LINE2, font_large, x2_pos, y2_pos)


# --------------------------------------------------
# RENDER LOGO (DreamPage – bunnen av siden)
# --------------------------------------------------

logo_path = (args.bottom_logo or "").strip()
if logo_path and not os.path.isabs(logo_path):
    logo_path = os.path.join(SCRIPT_DIR, logo_path)
if not logo_path:
    logo_path = os.path.join(SCRIPT_DIR, "DreamPage_logo.png")

if os.path.exists(logo_path):
    logo = Image.open(logo_path).convert("RGBA")

    target_width = int(w * args.bottom_logo_scale)
    scale = target_width / logo.width
    new_size = (target_width, int(logo.height * scale))
    logo = logo.resize(new_size, Image.LANCZOS)

    margin_bottom = int(h * args.bottom_logo_margin)
    logo_x = (w - new_size[0]) // 2 + args.bottom_logo_x_offset
    logo_y = h - new_size[1] - margin_bottom

    bl_alpha = max(0, min(255, args.bottom_logo_shadow_opacity))
    if bl_alpha > 0:
        bl_blur = args.bottom_logo_shadow_blur if args.bottom_logo_shadow_blur > 0 else max(4, int(new_size[1] * 0.12))
        bl_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        bl_mask = logo.split()[3].point(lambda p: int(p * bl_alpha / 255))
        bl_img = Image.new("RGBA", new_size, (*SHADOW, 255))
        bl_img.putalpha(bl_mask)
        bl_off = args.bottom_logo_shadow_offset if args.bottom_logo_shadow_offset > 0 else shadow_offset
        bl_layer.paste(bl_img, (logo_x + bl_off, logo_y + bl_off))
        bl_layer = bl_layer.filter(ImageFilter.GaussianBlur(bl_blur))
        img.alpha_composite(bl_layer)
        print(f"  Nedre logo-skygge: opacity {bl_alpha}/255, blur {bl_blur}px, offset {bl_off}px")

    img.alpha_composite(logo, (logo_x, logo_y))
    print(f"Nedre logo: {logo_path} ({new_size[0]}x{new_size[1]}) @ ({logo_x},{logo_y})")
else:
    print("ADVARSEL: Fant ikke nedre logo:", logo_path)

# --------------------------------------------------
# SAVE
# --------------------------------------------------

os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
img.save(OUT_PATH)

print("OK:", OUT_PATH)

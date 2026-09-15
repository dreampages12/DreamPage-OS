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
parser.add_argument("--line2", required=True)

parser.add_argument("--top_margin", type=float, required=True)
parser.add_argument("--line_spacing", type=float, required=True)


parser.add_argument("--font_small", type=int, required=True)
parser.add_argument("--font_large", type=int, required=True)
parser.add_argument("--font_small_path", default="")
parser.add_argument("--font_large_path", default="")

parser.add_argument("--gold", required=True)     # "30,60,120" eller "30,60,120,210,220,235"
parser.add_argument("--shadow", required=True)   # "5,8,18"

# Nedre DreamPage-logo. Tom sti = standardlogoen ved siden av dette scriptet,
# slik at boeker som ikke sier noe fortsatt ser noeyaktig ut som foer.
parser.add_argument("--bottom_logo", default="")
parser.add_argument("--bottom_logo_scale", type=float, default=0.40)   # bredde som andel av coverbredde
parser.add_argument("--bottom_logo_margin", type=float, default=0.03)  # luft under, andel av coverhoeyde
parser.add_argument("--bottom_logo_x_offset", type=int, default=0)

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

print("DEBUG line1:", repr(LINE1))
print("DEBUG line2:", repr(LINE2))

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

font_small_path = resolve_font_path(args.font_small_path, "PlayfairDisplay.ttf")
font_large_path = resolve_font_path(args.font_large_path, "PlayfairDisplay.ttf")
font_small = ImageFont.truetype(font_small_path, FONT_SMALL_SIZE)
font_large = ImageFont.truetype(font_large_path, FONT_LARGE_SIZE)
print("Font line1:", font_small_path)
print("Font line2:", font_large_path)

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
w2, h2 = draw.textbbox((0, 0), LINE2, font=font_large)[2:]

top = int(h * args.top_margin)
spacing = int(h * args.line_spacing)


x1 = (w - w1) // 2
x2 = (w - w2) // 2
y1 = top
descender_cut = int(h1 * 0.15)
y2 = y1 + h1 - descender_cut + spacing


# --------------------------------------------------
# DRAW FUNCTION
# --------------------------------------------------

def draw_line(text, font, x, y):
    if not text:
        return

    sm = _make_text_mask(img.size, x + shadow_offset, y + shadow_offset, text, font)
    sm = sm.filter(ImageFilter.GaussianBlur(max(1, shadow_offset // 2)))
    img.paste((*SHADOW, 255), (0, 0), sm)

    tm = _make_text_mask(img.size, x, y, text, font)
    bbox = draw.textbbox((x, y), text, font=font)
    _paste_gradient(img, tm, bbox, GOLD[0], GOLD[1])

# --------------------------------------------------
# RENDER TEXT
# --------------------------------------------------

draw_line(LINE1, font_small, x1, y1)
draw_line(LINE2, font_large, x2, y2)

# --------------------------------------------------
# RENDER LOGO (NY – KUN DETTE ER LAGT TIL)
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

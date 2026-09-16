"""Bygg siste innerside ("Fortsett eventyret") med QR-kode og rabattkode.

Siste synlige innerside i dagens bøker er `blank-back.png` — en helt blank side.
Canva-Lastpage-siden ble sentralt fjernet i dream_pdf_guard.log_inner_page_order,
så innmaten er i dag 30 sider: opening + 28 story + blank-back.

Dette scriptet ERSTATTER innholdet i den blanke siste siden. Sideantallet endres
ikke — vi bytter bare ut bildet som allerede ligger i slot 30. Derfor trenger
verken tekst-scriptene, dream_pdf_guard, build_gelato_pdf eller Gelato-produktet
noen endring.

Tre moduser:

  cover  Ta rå ComfyUI-output for neste bok sin forside (page99_next) og legg på
         tittel/logo med samme renderer som nettsidens preview bruker, slik at
         forsiden i boka er identisk med den kunden ser på landingssiden.

  image  Komponer selve siste innerside (overskrift, neste-forside, QR,
         rabattkode) som 2625x2625 PNG og skriv den til ordrens input-mappe som
         `blank-back.png`. Kjøres ETTER Prepare Pages og FØR Run Text Script.

  stamp  Stemple en ekte VEKTOR-QR oppå siste side i `<navn>_innersider.pdf`.
         Kjøres ETTER Run Text Script og FØR Count Innersider Pages. Rasteren
         fra `image` ligger under som fallback, så siden er skannbar uansett.

Siden har TO QR-koder: oppsalget i midten, og et lite Trustpilot-kort nede i
høyre hjørne. Hjørnekortet er alltid på (`--review-url` har standardverdi) og
tegnes i både `image` og `stamp`. Send `--review-url ""` for å slå det av.

Alt er fail-soft: uten --strict logges feil og exit-koden er 0, slik at et
oppsalg aldri kan blokkere en betalt ordre.

Bruk:
  python build_last_page.py cover --raw <page99_next.png> --next-slug den-skjulte-styrken \
      --child-name Håkon --lang nb --out <titled.png>

  python build_last_page.py image --next-cover <titled.png> --child-name Håkon \
      --next-title "Den Skjulte Styrken" --qr-url https://dreampage.store/f/8A3DHTKA \
      --coupon NESTE-8A3DHTKA --lang nb --out <orderPath>/input/blank-back.png

  python build_last_page.py stamp --pdf <orderPath>/pdf/Håkon_innersider.pdf \
      --qr-url https://dreampage.store/f/8A3DHTKA
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import traceback
from typing import Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PRE_DIR = os.path.join(SCRIPT_DIR, "pre")
TITLES_CONFIG = "C:/DreamPage-OS/config/next_book_titles.json"

PAGE_PX = 2625            # 8.75 tommer * 300 dpi — samme som LULU_PAGE_PX
PAGE_INCH = 8.5           # tekst-scriptene tegner siden som 8.5x8.5 i PDF-en

# QR-flate som andel av siden. 0.22 * 8.5" = 1.87" = 4.75 cm trykt, godt over
# 2 cm-kravet, med stille sone innenfor flaten.
QR_FRACTION = 0.160
QR_CENTER_X = 0.5
QR_CENTER_Y = 0.655         # senter, målt fra toppen av siden

BG_COLOR = (255, 255, 255)
INK = (34, 32, 36)
MUTED = (104, 100, 108)

# Siden bruker bokas egen åpningsside som bakgrunn, slik at første og siste side
# rammer inn boka. Åpningssiden har illustrasjoner i hjørnene og "© DreamPage"
# nederst; senterkolonnen under er den eneste flaten som er ren hele veien ned.
SAFE_X0, SAFE_X1 = 0.28, 0.72     # tekstkolonne: ren hele veien ned
WIDE_X0, WIDE_X1 = 0.20, 0.80     # bildebelte: ren mellom y 0.22 og 0.68
FOOTER_Y = 0.88          # alt under dette tilhører bakgrunnens bunntekst

# Trustpilot-oppfordringen nede i høyre hjørne. Den er bevisst holdt helt
# utenfor "Fortsett eventyret"-kortet: egen QR, egne konstanter, ingen delt
# geometri. Da kan den flyttes eller fjernes uten å røre oppsalget.
REVIEW_URL = "https://no.trustpilot.com/evaluate/dreampage.store"
REVIEW_CARD_RIGHT = 0.955        # høyre kant av kortet, målt fra venstre
REVIEW_CARD_W = 0.190
REVIEW_CARD_TOP = 0.726
REVIEW_CARD_BOTTOM = 0.930       # over "© DreamPage", som står sentrert
REVIEW_QR_FRACTION = 0.115       # 0.115 * 8.5" = 2.5 cm trykt, over 2 cm-kravet
REVIEW_QR_ERROR = "m"            # se qr_matrix: H ville gitt 0,4 mm moduler
REVIEW_QR_CENTER_X = REVIEW_CARD_RIGHT - REVIEW_CARD_W / 2
REVIEW_QR_CENTER_Y = 0.8595
TRUSTPILOT_GREEN = (0, 182, 122)

# QR-kortet
CARD_WIDTH = 0.42
CARD_TOP = 0.552
CARD_BOTTOM = 0.868
CARD_BORDER = (228, 223, 214)

# Mellomrom inne i kortet, i piksler. Faste verdier framfor sideandeler, saa
# rytmen holder seg selv om kortet flyttes.
GAP_QR_SCAN = 56
GAP_SCAN_LINE = 24
GAP_LINE_LABEL = 28
GAP_LABEL_CODE = 6

# Teksten er vinklet mot å låse opp noe som allerede finnes og venter, ikke mot
# å kjøpe noe nytt. Boka er alt laget ferdig med barnets ansikt — det er den
# konkrete grunnen til å skanne, og den som konverterer.
TEXTS = {
    "nb": {
        "headline": "Lås opp fortsettelsen, {name}.",
        "body": "Neste bok står klar — med deg i hovedrollen igjen.",
        "scan": "Skann og se boken din",
        "coupon_label": "RABATTKODEN DIN",
        "review": "Fornøyd med boken?\nGi oss en anmeldelse",
    },
    "nn": {
        "headline": "Lås opp framhaldet, {name}.",
        "body": "Neste bok står klar — med deg i hovudrolla igjen.",
        "scan": "Skann og sjå boka di",
        "coupon_label": "RABATTKODEN DIN",
        "review": "Nøgd med boka?\nGi oss ei vurdering",
    },
    "sv": {
        "headline": "Lås upp fortsättningen, {name}.",
        "body": "Nästa bok står klar — med dig i huvudrollen igen.",
        "scan": "Skanna och se din bok",
        "coupon_label": "DIN RABATTKOD",
        "review": "Nöjd med boken?\nGe oss ett omdöme",
    },
    "en": {
        "headline": "Unlock the next chapter, {name}.",
        "body": "Your next book is ready — starring you once again.",
        "scan": "Scan to see your book",
        "coupon_label": "YOUR DISCOUNT CODE",
        "review": "Happy with the book?\nLeave us a review",
    },
}

STRICT = False


def log(msg: str) -> None:
    print("[LAST PAGE] " + msg)


def warn(msg: str) -> None:
    print("[LAST PAGE WARNING] " + msg)


def normalize_lang(value: str) -> str:
    v = str(value or "nb").strip().lower().replace("_", "-")
    if v.startswith("nn"):
        return "nn"
    if v.startswith("sv") or v in {"se", "swedish", "svensk", "svenska"}:
        return "sv"
    if v.startswith("en"):
        return "en"
    return "nb"


def load_font(candidates, size: int):
    for name in candidates:
        path = name if os.path.isabs(name) else os.path.join(SCRIPT_DIR, name)
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


# Fredoka — samme rundede skrift som DreamPage-logoen og bokomslagene. Den
# leser som en oppfordring, ikke som brødtekst, og det er det siden skal være.
def title_font(size: int):
    return load_font([
        os.path.join(PRE_DIR, "Fredoka-Bold.ttf"),
        "Fredoka-Bold.ttf", "Georgia-Bold.ttf",
    ], size)


def body_font(size: int):
    return load_font([
        os.path.join(PRE_DIR, "Fredoka.ttf"),
        "Fredoka.ttf", "Georgia.ttf",
    ], size)


def mono_font(size: int):
    return load_font([
        os.path.join(PRE_DIR, "Fredoka-Bold.ttf"),
        "Fredoka-Bold.ttf", "Georgia-Bold.ttf",
    ], size)


def resolve_background(book_slug: str, explicit: str = "") -> str:
    """Bokas åpningsside — samme bakgrunn som første side i boka."""
    if explicit:
        if os.path.isfile(explicit):
            return explicit
        warn(f"oppgitt bakgrunn finnes ikke: {explicit}")
    if book_slug:
        import glob
        hits = sorted(glob.glob(f"C:/DreamPage-OS/books/{book_slug}/dreampage-first*.png"))
        if hits:
            return hits[0]
        warn(f"fant ingen dreampage-first*.png for {book_slug}")
    shared = os.path.join(SCRIPT_DIR, "dreampage-first.png")
    return shared if os.path.isfile(shared) else ""


def text_width(draw, text: str, font) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def fit_font(draw, text: str, maker, max_width: int, start: int, minimum: int = 24):
    """Største fontstørrelse der teksten holder seg innenfor den trygge sonen."""
    size = start
    while size > minimum:
        font = maker(size)
        if max(text_width(draw, line, font) for line in text.split("\n")) <= max_width:
            return font
        size -= 2
    return maker(minimum)


def draw_centered(draw, text: str, cy: int, font, color, line_gap: float = 1.35,
                  center_x: Optional[int] = None) -> int:
    """Tegn (fler-linjers) tekst sentrert horisontalt. Returnerer y under teksten.

    `center_x` er sidens midte når den ikke oppgis — Trustpilot-kortet i hjørnet
    sender inn sin egen midte i stedet.
    """
    lines = text.split("\n")
    ascent, descent = font.getmetrics()
    line_h = int((ascent + descent) * line_gap)
    cx = PAGE_PX // 2 if center_x is None else center_x
    y = cy
    for line in lines:
        w = text_width(draw, line, font)
        draw.text((cx - w // 2, y), line, font=font, fill=color)
        y += line_h
    return y


# ---------------------------------------------------------------- QR geometry
def qr_rect_px() -> Tuple[int, int, int]:
    size = int(round(PAGE_PX * QR_FRACTION))
    x = int(round(PAGE_PX * QR_CENTER_X - size / 2))
    y = int(round(PAGE_PX * QR_CENTER_Y - size / 2))
    return x, y, size


def qr_matrix(url: str, error: str = "h"):
    """Returner (matrise, antall moduler) inkl. 4 moduler stille sone.

    Oppsalgs-QR-en bruker ECC H fordi den er hele inntekten på siden. Den lange
    Trustpilot-lenken ville blitt 49 moduler med H, altså 0,4 mm per modul på
    2 cm — for tett for trykk. Den bruker M, som er standard for print.
    """
    import segno

    qr = segno.make(url, error=error)
    border = 4
    rows = [list(r) for r in qr.matrix]
    n = len(rows) + 2 * border
    grid = [[0] * n for _ in range(n)]
    for ry, row in enumerate(rows):
        for rx, val in enumerate(row):
            if val:
                grid[ry + border][rx + border] = 1
    return grid, n


# ------------------------------------------------------------------- mode: cover
def resolve_title_params(next_slug: str, lang: str) -> Optional[Dict]:
    try:
        with open(TITLES_CONFIG, encoding="utf-8-sig") as fh:
            cfg = json.load(fh)
    except Exception as exc:
        warn(f"kunne ikke lese {TITLES_CONFIG}: {exc}")
        return None
    book = cfg.get(next_slug)
    if not book:
        warn(f"ingen tittelparametre for bok '{next_slug}' i {TITLES_CONFIG}")
        return None
    return book.get(lang) or book.get("nb") or next(iter(book.values()), None)


def resolve_raw_cover(raw: str, prefix: str) -> str:
    """--raw kan være en fil, eller comfy-mappa der pageXX_00001_.png havner."""
    if os.path.isfile(raw):
        return raw
    if os.path.isdir(raw):
        hits = [
            os.path.join(raw, n) for n in os.listdir(raw)
            if n.startswith(prefix) and os.path.splitext(n)[1].lower() in
            (".png", ".jpg", ".jpeg", ".webp")
        ]
        hits = [p for p in hits if os.path.getsize(p) > 0]
        if hits:
            hits.sort(key=os.path.getmtime, reverse=True)
            return hits[0]
    return ""


def template_size(next_slug: str) -> Optional[int]:
    """Bredden på forside-malen tittelparametrene er tunet mot."""
    try:
        with open(f"C:/DreamPage-OS/books/{next_slug}/config.json", encoding="utf-8-sig") as fh:
            cfg = json.load(fh)
        front = next(p for p in cfg.get("pages", []) if p.get("page_key") == "page00")
        path = os.path.join("C:/DreamPage-OS/input", front["template_image"])
        if os.path.isfile(path):
            with Image.open(path) as im:
                return im.width
    except Exception as exc:
        warn(f"fant ikke forside-malens størrelse for {next_slug}: {exc}")
    return None


def font_scale(raw_path: str, next_slug: str) -> float:
    """Hvor mye fontstørrelsene må ganges med for dette bildet.

    render-title bruker ABSOLUTTE pikselstørrelser for fonten, mens logo_scale,
    top_margin og line_spacing er andeler av bredden. Tittelparametrene er tunet
    mot forside-malen (1024px), så et 4096px ComfyUI-bilde trenger 4x fonten for
    å se likt ut. Vi skalerer fonten i stedet for å krympe bildet, slik at boka
    og landingssiden får full oppløsning.
    """
    baseline = template_size(next_slug) or 1024
    try:
        with Image.open(raw_path) as im:
            actual = im.width
    except Exception as exc:
        warn(f"kunne ikke lese bildestørrelsen ({exc}) — bruker fontskala 1.0")
        return 1.0
    if actual == baseline:
        return 1.0
    factor = actual / baseline
    log(f"fontskala {factor:.2f}x (bilde {actual}px vs. mal {baseline}px)")
    return factor


def mode_cover(args) -> int:
    resolved = resolve_raw_cover(args.raw, args.raw_prefix)
    if not resolved:
        warn(f"rå forside mangler: {args.raw} (prefiks {args.raw_prefix})")
        return 1
    args.raw = resolved
    params = resolve_title_params(args.next_slug, normalize_lang(args.lang))
    if not params:
        # Uten tittelparametre er den rå forsiden fortsatt bedre enn ingenting.
        Image.open(args.raw).convert("RGB").save(args.out)
        log(f"skrev utitulert forside: {args.out}")
        return 0

    logo = (params.get("line2_image") or "").strip()
    if logo and not os.path.isfile(logo):
        # For flere boeker ER logoen hele andre linje ("line2": ""). Da blir
        # tittelen staaende som en halv setning - ordre 1510 fikk en
        # trykkeklar forside som bare sa "Henry og det".
        #
        # render-title-line2logo.py skriver "ADVARSEL: Fant ikke line2_image"
        # og avslutter med 0, saa ingenting oppstroems merket det. Vi roper
        # her i stedet, med samme "!!!"-markoer som resten av kjeden bruker.
        # Fortsatt fail-soft: et oppsalg skal aldri stoppe en betalt ordre.
        fallback = (params.get("line2") or "").strip()
        warn("!!! line2-logoen mangler: %s"
             "\n    Konfigurert for %s i config/next_book_titles.json."
             "\n    %s"
             "\n    Sjekk alle stiene med: python tools/check_assets.py"
             % (logo, args.next_slug,
                ("Faller tilbake paa tekstlinja '%s'." % fallback) if fallback
                else "Boka har ingen tekst-fallback ('line2' er tom), saa "
                     "tittelen blir en halv setning. SE OVER FORSIDEN."))
    renderer = "render-title-line2logo.py" if logo else "render-title.py"
    fs = font_scale(args.raw, args.next_slug)
    cmd = [
        sys.executable, os.path.join(PRE_DIR, renderer),
        "--image", args.raw,
        "--out", args.out,
        # line1_prefix gir titler som "Prinsesse Emma og" - samme form som
        # bokas egen trykte forside.
        "--line1", " ".join(p for p in (
            (params.get("line1_prefix", "") or "").strip(),
            args.child_name,
            (params.get("line1_suffix", "") or "").strip(),
        ) if p),
        "--line2", params.get("line2", "") or "",
        "--font_small", str(round(params.get("font_small", 80) * fs)),
        "--font_large", str(round(params.get("font_large", 90) * fs)),
        "--gold", params.get("gold", "255, 255, 255"),
        "--shadow", params.get("shadow", "0, 0, 0"),
        "--top_margin", str(params.get("top_margin", 0.04)),
        "--line_spacing", str(params.get("line_spacing", 0.01)),
        "--font_small_path", params.get("font_small_path", "") or "",
        "--font_large_path", params.get("font_large_path", "") or "",
    ]
    if logo:
        cmd += [
            "--line2_image", logo,
            "--logo_scale", str(params.get("logo_scale", 0.38)),
            "--logo_x_offset", str(params.get("logo_x_offset", 0)),
        ]

    # Glod bak linje 1. Sendes bare naar boka har bedt om den, saa alle andre
    # boeker beholder rendererens standard (lys, svak glod).
    for key, flag in (("glow_color", "--glow_color"),
                      ("glow_opacity", "--glow_opacity"),
                      ("glow_radius_scale", "--glow_radius_scale"),
                      # Skyggen bak line2-logoen. 255 er rendererens standard;
                      # en logo med egen kontur trenger langt mindre.
                      ("logo_shadow_opacity", "--logo_shadow_opacity")):
        value = params.get(key)
        if value not in (None, ""):
            cmd += [flag, str(value)]

    # Nedre DreamPage-logo. Sendes bare naar boka faktisk har bedt om en egen -
    # ellers beholder rendereren standardlogoen, og alle andre boeker er urort.
    bottom = (params.get("bottom_logo") or "").strip()
    if bottom:
        cmd += [
            "--bottom_logo", bottom,
            "--bottom_logo_scale", str(params.get("bottom_logo_scale", 0.40)),
            "--bottom_logo_margin", str(params.get("bottom_logo_margin", 0.03)),
            "--bottom_logo_x_offset", str(params.get("bottom_logo_x_offset", 0)),
        ]

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0 or not os.path.isfile(args.out):
        warn(f"{renderer} feilet (rc={proc.returncode}): {(proc.stderr or '').strip()[-800:]}")
        Image.open(args.raw).convert("RGB").save(args.out)
        log(f"fallback: skrev utitulert forside: {args.out}")
        write_cover_mockup(args)
        return 0
    log(f"forside med tittel klar: {args.out}")
    write_cover_mockup(args)
    return 0


def write_cover_mockup(args) -> None:
    """Lagre ogsaa en 3D-mockup av forsiden, hvis --mockup-out er oppgitt.

    Landingssiden skal vise NOEYAKTIG det samme som staar trykt i boka, og i
    boka staar mockupen - ikke den flate forsiden. Derfor lages begge her:
    den flate brukes til aa bygge siste side, mockupen lastes opp til
    continue_callback.
    """
    out = getattr(args, "mockup_out", "")
    if not out:
        return
    try:
        art = fetch_server_mockup(args.out)
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        art.save(out)
        log(f"mockup for landingssiden lagret: {out}")
    except Exception as exc:
        warn(f"kunne ikke lage mockup for landingssiden ({exc}) — "
             "landingssiden faar den flate forsiden i stedet")


# ------------------------------------------------------------------- mode: image
MOCKUP_SERVER = os.environ.get("DP_MOCKUP_SERVER", "http://127.0.0.1:8790")
MOCKUP_TEMPLATE = os.environ.get("DP_MOCKUP_TEMPLATE", "")
MOCKUP_SECRET = os.environ.get("DP_MOCKUP_SECRET", "")
# Settes av --mockup-template. Et flagg er tryggere enn en miljovariabel her:
# n8n sin executeCommand arver ikke nodvendigvis miljoet vi tester i.
MOCKUP_TEMPLATE_OVERRIDE = ""


def fetch_server_mockup(cover_path: str):
    """Hent mockup fra dp-mockup-server (PSD-kalibrert).

    Faller tilbake til den innebygde geometriske mockupen hvis serveren er nede,
    slik at en betalt ordre aldri stopper paa en oppsalgsside.
    """
    import io as _io
    import urllib.request
    import uuid

    template = MOCKUP_TEMPLATE_OVERRIDE or MOCKUP_TEMPLATE
    if not template:
        warn("ingen mockup-mal oppgitt (--mockup-template / DP_MOCKUP_TEMPLATE)"
             " — bruker innebygd mockup")
        return make_book_mockup(cover_path, height=1500)

    boundary = "----dpmockup" + uuid.uuid4().hex
    with open(cover_path, "rb") as fh:
        payload = fh.read()
    parts = []
    for name, value in (("template_id", template), ("format", "png")):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"cover\"; "
        f"filename=\"{os.path.basename(cover_path)}\"\r\n"
        "Content-Type: image/png\r\n\r\n".encode()
    )
    parts.append(payload)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)

    req = urllib.request.Request(f"{MOCKUP_SERVER}/v1/mockup", data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    if MOCKUP_SECRET:
        req.add_header("X-DreamPage-Secret", MOCKUP_SECRET)
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = resp.read()
            cached = resp.headers.get("X-Mockup-Cached")
            rect = resp.headers.get("X-Mockup-Cover-Rect")
        log(f"mockup fra server ({len(data) // 1024} kB, cache={cached})")
        img = Image.open(_io.BytesIO(data))
        img.load()
        img = img.convert("RGBA")
        # Bokas rektangel i bildet. Uten dette ville sidelayouten skalert etter
        # hele lerretet inkludert den brede, myke skyggen, og boka ville blitt
        # for liten. Skyggen skal få lov til å tone ut utenfor.
        if rect:
            try:
                img.info["cover_rect"] = tuple(int(v) for v in rect.split(","))
            except ValueError:
                pass
        return img
    except Exception as exc:
        warn(f"mockup-serveren svarte ikke ({exc}) — bruker innebygd mockup")
        return make_book_mockup(cover_path, height=1500)


def _perspective_coeffs(dst, src):
    """Koeffisienter for PIL sin PERSPECTIVE (den mapper ut -> inn)."""
    import numpy as np

    m = []
    for (dx, dy), (sx, sy) in zip(dst, src):
        m.append([dx, dy, 1, 0, 0, 0, -sx * dx, -sx * dy])
        m.append([0, 0, 0, dx, dy, 1, -sy * dx, -sy * dy])
    A = np.array(m, dtype=float)
    B = np.array(src, dtype=float).reshape(8)
    return np.linalg.solve(A, B) if A.shape[0] == 8 else \
        np.linalg.lstsq(A, B, rcond=None)[0]


def _warp_into(canvas: Image.Image, src: Image.Image, quad) -> None:
    """Legg src inn i canvas forvrengt til quad (TL, TR, BR, BL)."""
    from PIL import ImageDraw as _D

    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    x0, y0 = int(min(xs)) - 1, int(min(ys)) - 1
    w, h = int(max(xs)) - x0 + 2, int(max(ys)) - y0 + 2
    rel = [(p[0] - x0, p[1] - y0) for p in quad]
    sw, sh = src.size
    coeffs = _perspective_coeffs(rel, [(0, 0), (sw, 0), (sw, sh), (0, sh)])
    warped = src.convert("RGBA").transform((w, h), Image.PERSPECTIVE, coeffs,
                                           Image.BICUBIC)
    mask = Image.new("L", (w, h), 0)
    _D.Draw(mask).polygon(rel, fill=255)
    canvas.paste(warped, (x0, y0), mask)


def make_book_mockup(cover_path: str, height: int = 1400) -> Image.Image:
    """Bygg en 3D-bokmockup av den flate forsiden.

    Hardcover sett litt fra venstre: ryggen nærmest, forsiden viker bakover mot
    høyre. Alt regnes ut fra forsiden, så ingen PSD eller Photoshop trengs.
    """
    from PIL import ImageDraw, ImageEnhance, ImageFilter

    cover = Image.open(cover_path).convert("RGB")
    side = height
    cover = cover.resize((side, side), Image.LANCZOS)

    # Betrakteren står litt til høyre: forsidens HØYRE kant er nærmest, så
    # papirblokken (forkanten) er synlig til høyre. Ryggen ligger skjult bak
    # venstre kant. Det er papirblokken som gjør at hjernen leser "bok".
    tilt = 0.93          # venstre kant er kortere (viker bakover)
    depth = 0.88         # forsiden er forkortet i bredden
    block_w = int(side * 0.062)

    h_r = side
    h_l = int(side * tilt)
    cw = int(side * depth)
    d = (h_r - h_l) // 2

    pad = int(side * 0.10)
    x0, y0 = pad, int(side * 0.05)

    cover_quad = [(x0, y0 + d), (x0 + cw, y0),
                  (x0 + cw, y0 + h_r), (x0, y0 + d + h_l)]

    h_b = int(h_r * 0.955)
    db = (h_r - h_b) // 2
    block_quad = [(x0 + cw, y0), (x0 + cw + block_w, y0 + db),
                  (x0 + cw + block_w, y0 + db + h_b), (x0 + cw, y0 + h_r)]

    canvas = Image.new("RGBA",
                       (x0 + cw + block_w + pad, y0 + h_r + int(side * 0.09)),
                       (0, 0, 0, 0))

    # --- slagskygge ---
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon(
        [(p[0] - int(side * 0.012), p[1] + int(side * 0.026)) for p in
         [cover_quad[0], block_quad[1], block_quad[2], cover_quad[3]]],
        fill=(22, 20, 26, 110))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(side // 42)))

    # --- papirblokk: lyse ark med fine skiller ---
    pages = Image.new("RGB", (64, 256), (245, 241, 233))
    pd = ImageDraw.Draw(pages)
    for i in range(0, 64, 3):
        pd.line([(i, 0), (i, 256)], fill=(219, 212, 199), width=1)
    pd.line([(0, 0), (0, 256)], fill=(176, 168, 154), width=3)
    _warp_into(canvas, pages, block_quad)

    # --- forside ---
    _warp_into(canvas, cover, cover_quad)

    # --- lys: mørkest mot venstre (som viker bakover) ---
    shade = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    grad = Image.new("L", (cw, 1))
    for x in range(cw):
        grad.putpixel((x, 0), int(255 * (1.0 - x / max(1, cw - 1)) ** 1.5))
    tone = Image.new("RGB", (cw, h_r), (18, 16, 24))
    tone.putalpha(grad.resize((cw, h_r), Image.BILINEAR))
    _warp_into(shade, tone, cover_quad)
    shade.putalpha(shade.getchannel("A").point(lambda v: int(v * 0.30)))
    canvas.alpha_composite(shade)

    # --- hengsel: myk mørk fals langs venstre kant ---
    hinge = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    hw = max(4, int(side * 0.018))
    ImageDraw.Draw(hinge).polygon(
        [cover_quad[0], (cover_quad[0][0] + hw, cover_quad[0][1] - hw // 3),
         (cover_quad[3][0] + hw, cover_quad[3][1] + hw // 3), cover_quad[3]],
        fill=(0, 0, 0, 90))
    canvas.alpha_composite(hinge.filter(ImageFilter.GaussianBlur(max(2, side // 200))))

    return canvas


def paste_cover(page: Image.Image, cover_path: str, top: int, bottom: int,
                style: str = "mockup") -> int:
    """Lim inn neste-forsiden mellom y=top og y=bottom. Returnerer y under bildet."""
    max_h = bottom - top
    # Mockupen får bruke det brede, rene beltet i midten av åpningssiden
    # (x 0.20-0.80 er fritt for illustrasjoner mellom y 0.22 og 0.68), ikke bare
    # den smale tekstkolonnen.
    max_w = int(PAGE_PX * (WIDE_X1 - WIDE_X0) * 0.88)

    if style == "server":
        art = fetch_server_mockup(cover_path)
    elif style == "mockup":
        art = make_book_mockup(cover_path, height=1500)
    else:
        art = Image.open(cover_path).convert("RGB")

    # Skaler etter BOKA, ikke etter lerretet: mockupen har en bred, myk skygge
    # som skal få tone ut utenfor rammen i stedet for å presse boka liten.
    rect = art.info.get("cover_rect") if hasattr(art, "info") else None
    if rect and len(rect) == 4:
        bw = max(1, rect[2] - rect[0])
        bh = max(1, rect[3] - rect[1])
        scale = min(max_w / bw, max_h / bh)
    else:
        scale = min(max_w / art.width, max_h / art.height)

    w, h = max(1, int(art.width * scale)), max(1, int(art.height * scale))
    art = art.resize((w, h), Image.LANCZOS)

    if rect and len(rect) == 4:
        # Sentrer boka, ikke lerretet.
        bx = (rect[0] + rect[2]) / 2 * scale
        by = (rect[1] + rect[3]) / 2 * scale
        x = int(PAGE_PX / 2 - bx)
        y = int((top + bottom) / 2 - by)
    else:
        x = (PAGE_PX - w) // 2
        y = top + (max_h - h) // 2

    if art.mode == "RGBA":
        # Mockupen har sin egen skygge og kanter innebygd.
        page.paste(art, (x, y), art)
    else:
        from PIL import ImageFilter
        shadow = Image.new("RGBA", (w + 60, h + 60), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rectangle([30, 30, 30 + w, 30 + h], fill=(0, 0, 0, 60))
        page.paste(shadow.filter(ImageFilter.GaussianBlur(18)), (x - 30, y - 22),
                   shadow.filter(ImageFilter.GaussianBlur(18)))
        page.paste(art, (x, y))
        ImageDraw.Draw(page).rectangle([x, y, x + w, y + h],
                                       outline=(214, 206, 194), width=4)
    return y + h


def draw_raster_qr(page: Image.Image, url: str,
                   center_x: float = QR_CENTER_X, center_y: float = QR_CENTER_Y,
                   fraction: float = QR_FRACTION, error: str = "h") -> None:
    """Tegn QR som raster-fallback på eksakt samme flate som vektor-stemplet."""
    grid, n = qr_matrix(url, error)
    size = int(round(PAGE_PX * fraction))
    x = int(round(PAGE_PX * center_x - size / 2))
    y = int(round(PAGE_PX * center_y - size / 2))
    module = max(1, size // n)
    qr_px = module * n
    qr_img = Image.new("RGB", (qr_px, qr_px), (255, 255, 255))
    d = ImageDraw.Draw(qr_img)
    for ry in range(n):
        for rx in range(n):
            if grid[ry][rx]:
                d.rectangle(
                    [rx * module, ry * module, (rx + 1) * module - 1, (ry + 1) * module - 1],
                    fill=(0, 0, 0),
                )
    # Hvit plate under, slik at QR-en aldri står på farge
    plate = int(size * 1.06)
    px = int(PAGE_PX * center_x - plate / 2)
    py = int(PAGE_PX * center_y - plate / 2)
    ImageDraw.Draw(page).rectangle([px, py, px + plate, py + plate], fill=(255, 255, 255))
    page.paste(qr_img, (x + (size - qr_px) // 2, y + (size - qr_px) // 2))
    log(f"raster-QR: {n} moduler, {module}px/modul, {qr_px}px ({qr_px / 300 * 2.54:.1f} cm trykt)")


def draw_qr_card(page: Image.Image, draw, t, args) -> int:
    """Et rolig hvitt kort som samler QR, oppfordring og rabattkode.

    Kortet gjør to ting: det gir QR-en den rene hvite flaten den trenger for å
    skannes, og det binder koden visuelt til rabatten så de leses som én ting.
    Returnerer y under kortet.
    """
    card_w = int(PAGE_PX * CARD_WIDTH)
    x0 = (PAGE_PX - card_w) // 2
    y0 = int(PAGE_PX * CARD_TOP)
    y1 = int(PAGE_PX * CARD_BOTTOM)
    r = int(PAGE_PX * 0.016)

    # Svak skygge, så kortet løfter seg fra siden uten å rope.
    from PIL import ImageFilter
    shadow = Image.new("RGBA", page.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [x0, y0 + int(PAGE_PX * 0.004), x0 + card_w, y1 + int(PAGE_PX * 0.004)],
        radius=r, fill=(60, 55, 70, 26))
    page.paste(Image.alpha_composite(page.convert("RGBA"),
               shadow.filter(ImageFilter.GaussianBlur(int(PAGE_PX * 0.006)))).convert("RGB"),
               (0, 0))
    draw = ImageDraw.Draw(page)
    draw.rounded_rectangle([x0, y0, x0 + card_w, y1], radius=r,
                           fill=(255, 255, 255), outline=CARD_BORDER, width=3)

    draw_raster_qr(page, args.qr_url)
    draw = ImageDraw.Draw(page)

    # Innholdet stables ned fra QR-ens underkant med faste mellomrom, slik at
    # luften over QR-en og under koden blir like stor. Tidligere ble avstandene
    # regnet i andeler av HELE siden, og da vokste toppmargen mens bunnen ble
    # klemt.
    inner_w = card_w - int(PAGE_PX * 0.06)
    lx = int(card_w * 0.10)
    y = int(PAGE_PX * (QR_CENTER_Y + QR_FRACTION * 0.5)) + GAP_QR_SCAN

    y = draw_centered(draw, t["scan"], y,
                      fit_font(draw, t["scan"], title_font, inner_w, 50), INK, line_gap=1.06)

    ly = y + GAP_SCAN_LINE
    draw.line([(x0 + lx, ly), (x0 + card_w - lx, ly)], fill=CARD_BORDER, width=2)

    y = ly + GAP_LINE_LABEL
    y = draw_centered(draw, t["coupon_label"], y,
                      fit_font(draw, t["coupon_label"], body_font, inner_w, 30),
                      MUTED, line_gap=1.06)

    code = (args.coupon or "").strip()
    if code:
        y = draw_centered(draw, code, y + GAP_LABEL_CODE,
                          fit_font(draw, code, mono_font, inner_w, 54), INK, line_gap=1.06)

    bottom_pad = y1 - y
    top_pad = int(PAGE_PX * (QR_CENTER_Y - QR_FRACTION * 0.5)) - y0
    if abs(bottom_pad - top_pad) > PAGE_PX * 0.012:
        warn(f"kortet er skjevt: {top_pad}px luft over QR, {bottom_pad}px under koden")
    return max(y, y1)


def draw_trustpilot_stars(draw, center_x: int, top: int, box: int, gap: int) -> int:
    """Fem grønne Trustpilot-ruter med hvit stjerne. Returnerer y under raden."""
    import math

    total = box * 5 + gap * 4
    x = center_x - total // 2
    r = box * 0.40
    for _ in range(5):
        draw.rectangle([x, top, x + box, top + box], fill=TRUSTPILOT_GREEN)
        cx, cy = x + box / 2, top + box / 2
        pts = []
        for i in range(10):
            ang = -math.pi / 2 + i * math.pi / 5
            rr = r if i % 2 == 0 else r * 0.42
            pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
        draw.polygon(pts, fill=(255, 255, 255))
        x += box + gap
    return top + box


def draw_review_card(page: Image.Image, t, url: str) -> None:
    """Lite Trustpilot-kort nede i høyre hjørne.

    Kortet står for seg selv: det deler ingen geometri med "Fortsett
    eventyret"-kortet, og det holder seg innenfor x 0.765-0.955 og y
    0.726-0.930 — klar av bildebeltet, av oppsalgskortet og av den sentrerte
    "© DreamPage"-linjen i bakgrunnen.
    """
    from PIL import ImageFilter

    x1 = int(PAGE_PX * REVIEW_CARD_RIGHT)
    w = int(PAGE_PX * REVIEW_CARD_W)
    x0 = x1 - w
    y0 = int(PAGE_PX * REVIEW_CARD_TOP)
    y1 = int(PAGE_PX * REVIEW_CARD_BOTTOM)
    cx = (x0 + x1) // 2
    r = int(PAGE_PX * 0.012)

    shadow = Image.new("RGBA", page.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [x0, y0 + int(PAGE_PX * 0.003), x1, y1 + int(PAGE_PX * 0.003)],
        radius=r, fill=(60, 55, 70, 22))
    page.paste(Image.alpha_composite(page.convert("RGBA"),
               shadow.filter(ImageFilter.GaussianBlur(int(PAGE_PX * 0.005)))).convert("RGB"),
               (0, 0))
    draw = ImageDraw.Draw(page)
    draw.rounded_rectangle([x0, y0, x1, y1], radius=r,
                           fill=(255, 255, 255), outline=CARD_BORDER, width=3)

    pad = int(PAGE_PX * 0.016)
    box = int(PAGE_PX * 0.0165)
    y = draw_trustpilot_stars(draw, cx, y0 + pad, box, max(2, box // 7))

    text = t.get("review", TEXTS["nb"]["review"])
    inner_w = w - 2 * pad
    draw_centered(draw, text, y + int(PAGE_PX * 0.007),
                  fit_font(draw, text, body_font, inner_w, 34, minimum=18),
                  MUTED, line_gap=1.18, center_x=cx)

    draw_raster_qr(page, url, REVIEW_QR_CENTER_X, REVIEW_QR_CENTER_Y,
                   REVIEW_QR_FRACTION, REVIEW_QR_ERROR)


def mode_image(args) -> int:
    lang = normalize_lang(args.lang)
    t = TEXTS.get(lang, TEXTS["nb"])
    name = (args.child_name or "").strip()

    bg_path = resolve_background(args.book_slug, args.background)
    if bg_path:
        page = Image.open(bg_path).convert("RGB")
        if page.size != (PAGE_PX, PAGE_PX):
            page = page.resize((PAGE_PX, PAGE_PX), Image.LANCZOS)
        log(f"bakgrunn: {os.path.basename(bg_path)} (bokas åpningsside)")
    else:
        page = Image.new("RGB", (PAGE_PX, PAGE_PX), BG_COLOR)
        warn("fant ingen åpningsside — bruker blank bakgrunn")

    draw = ImageDraw.Draw(page)
    safe_w = int(PAGE_PX * (SAFE_X1 - SAFE_X0))

    # Overskrift og ingress, begge klemt inn i den rene senterkolonnen.
    headline = t["headline"].format(name=name)
    y = int(PAGE_PX * 0.055)
    y = draw_centered(draw, headline, y, fit_font(draw, headline, title_font, safe_w, 86),
                      INK, line_gap=1.22)
    y += int(PAGE_PX * 0.008)
    draw_centered(draw, t["body"], y, fit_font(draw, t["body"], body_font, safe_w, 50),
                  MUTED, line_gap=1.3)

    cover_top = int(PAGE_PX * 0.165)
    cover_bottom = int(PAGE_PX * 0.498)
    if args.next_cover and os.path.isfile(args.next_cover):
        paste_cover(page, args.next_cover, cover_top, cover_bottom, args.cover_style)
    else:
        warn(f"neste-forside mangler ({args.next_cover}) — siden bygges uten bilde")
        if args.next_title:
            draw_centered(draw, args.next_title, int(PAGE_PX * 0.34),
                          fit_font(draw, args.next_title, title_font, safe_w, 78), INK)

    y = draw_qr_card(page, draw, t, args)

    review_url = (args.review_url or "").strip()
    if review_url:
        draw_review_card(page, t, review_url)
        log(f"Trustpilot-kort i hjørnet: {review_url}")

    if y > PAGE_PX * FOOTER_Y:
        warn(f"innholdet naar {y / PAGE_PX:.2f} av siden — kan kollidere med "
             f"bakgrunnens bunntekst ved {FOOTER_Y}")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    page.save(args.out)
    log(f"siste innerside skrevet: {args.out}")
    return 0


# ------------------------------------------------------------------- mode: stamp
def mode_stamp(args) -> int:
    from io import BytesIO
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas as rl_canvas

    if not os.path.isfile(args.pdf):
        warn(f"innersider-PDF mangler: {args.pdf}")
        return 1

    reader = PdfReader(args.pdf)
    pages = list(reader.pages)
    if not pages:
        warn("innersider-PDF har ingen sider")
        return 1

    last = pages[-1]
    pw = float(last.mediabox.width)
    ph = float(last.mediabox.height)

    def stamp(c, url: str, center_x: float, center_y: float, fraction: float,
              error: str = "h"):
        """Tegn én vektor-QR på overlegget. Returnerer (moduler, cm trykt)."""
        grid, n = qr_matrix(url, error)
        size = pw * fraction
        module = size / n
        x0 = pw * center_x - size / 2
        # PDF-koordinater går nedenfra; center_y måles ovenfra.
        y0 = ph * (1.0 - center_y) - size / 2
        plate = size * 1.06
        c.setFillColorRGB(1, 1, 1)
        c.rect(pw * center_x - plate / 2, ph * (1.0 - center_y) - plate / 2,
               plate, plate, stroke=0, fill=1)
        c.setFillColorRGB(0, 0, 0)
        for ry in range(n):
            for rx in range(n):
                if grid[ry][rx]:
                    c.rect(x0 + rx * module,
                           y0 + (n - 1 - ry) * module,
                           module + 0.06, module + 0.06, stroke=0, fill=1)
        return n, size / 72.0 * 2.54

    buf = BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(pw, ph))
    n, printed_cm = stamp(c, args.qr_url, QR_CENTER_X, QR_CENTER_Y, QR_FRACTION)

    review_url = (args.review_url or "").strip()
    if review_url:
        rn, rcm = stamp(c, review_url, REVIEW_QR_CENTER_X, REVIEW_QR_CENTER_Y,
                        REVIEW_QR_FRACTION, REVIEW_QR_ERROR)
        log(f"Trustpilot-QR stemplet: {rn} moduler, {rcm:.1f} cm ({review_url})")
        if rcm < 2.0:
            warn(f"Trustpilot-QR er kun {rcm:.1f} cm — under 2 cm-kravet")
    c.showPage()
    c.save()
    buf.seek(0)

    overlay = PdfReader(buf).pages[0]
    last.merge_page(overlay)

    writer = PdfWriter()
    for p in pages:
        writer.add_page(p)

    tmp = args.pdf + ".qrtmp"
    with open(tmp, "wb") as fh:
        writer.write(fh)

    # Windows kan holde fila låst et øyeblikk (virusskanner, indeksering).
    last_error = None
    for attempt in range(5):
        try:
            os.replace(tmp, args.pdf)
            last_error = None
            break
        except PermissionError as exc:  # noqa: PERF203
            last_error = exc
            import time
            time.sleep(0.4 * (attempt + 1))
    if last_error is not None:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise last_error

    log(f"vektor-QR stemplet på side {len(pages)} av {len(pages)}: "
        f"{n} moduler, {printed_cm:.1f} cm, ECC H ({args.pdf})")
    if printed_cm < 2.0:
        warn(f"QR er kun {printed_cm:.1f} cm — under 2 cm-kravet")
    return 0


# ------------------------------------------------------------------ mode: upload
def mode_upload(args) -> int:
    """Last opp den ferdige neste-forsiden til nettsidens continue_callback.

    Landingssiden skal vise nøyaktig samme bilde som står trykt i boka. Kallet
    er idempotent; feiler det, skal ordren likevel gå videre.
    """
    import mimetypes
    import urllib.error
    import urllib.request
    import uuid

    # Mockupen er førstevalget, men den lages av en ekstern server som kan
    # svare tomt. Da laster vi opp den flate forsiden i stedet for ingenting.
    src = args.file
    if not os.path.isfile(src) and args.fallback and os.path.isfile(args.fallback):
        log(f"mockup mangler ({src}) — bruker {args.fallback}")
        src = args.fallback
    if not os.path.isfile(src):
        warn(f"filen som skulle lastes opp mangler: {src}")
        return 1

    with open(src, "rb") as fh:
        payload = fh.read()

    filename = os.path.basename(src)
    ctype = mimetypes.guess_type(filename)[0] or "image/png"
    boundary = "----dreampage" + uuid.uuid4().hex

    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
        f"Content-Type: {ctype}\r\n\r\n".encode(),
        payload,
        f"\r\n--{boundary}--\r\n".encode(),
    ])

    req = urllib.request.Request(args.callback, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Content-Length", str(len(body)))
    # Cloudflare foran dreampage.store svarer 1010 på default urllib-UA.
    req.add_header("User-Agent", args.user_agent)
    req.add_header("Accept", "application/json, */*")
    if args.secret:
        req.add_header("X-DreamPage-Secret", args.secret)

    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            log(f"opplasting HTTP {resp.status}: {raw[:400]}")
            try:
                data = json.loads(raw)
            except Exception:
                data = {}
            if resp.status >= 400 or data.get("ok") is False:
                warn("nettsiden svarte ikke ok — landingssiden kan mangle forsiden")
                return 1
    except urllib.error.HTTPError as exc:
        warn(f"opplasting feilet HTTP {exc.code}: {exc.read()[:400]!r}")
        return 1
    except Exception as exc:
        warn(f"opplasting feilet: {exc}")
        return 1

    log(f"neste-forside lastet opp til {args.callback}")
    return 0


# ------------------------------------------------------------------------ main
def main() -> int:
    global STRICT, MOCKUP_TEMPLATE_OVERRIDE
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=["cover", "image", "stamp", "upload"])
    ap.add_argument("--strict", action="store_true",
                    help="La feil bli exit-kode != 0 (default: fail-soft)")

    ap.add_argument("--raw", default="")
    ap.add_argument("--raw-prefix", default="page99_next")
    ap.add_argument("--next-slug", default="")

    ap.add_argument("--file", default="")
    ap.add_argument("--fallback", default="",
                    help="brukes hvis --file mangler (f.eks. flat forside naar "
                         "mockup-serveren ikke svarte)")
    ap.add_argument("--callback", default="")
    ap.add_argument("--secret", default="")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--user-agent", default=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 DreamPage-Worker/1.0"))

    ap.add_argument("--next-cover", default="")
    ap.add_argument("--child-name", default="")
    ap.add_argument("--next-title", default="")
    ap.add_argument("--coupon", default="")

    ap.add_argument("--qr-url", default="")
    ap.add_argument("--review-url", default=REVIEW_URL,
                    help="Trustpilot-lenke i hjørnet av siste side. Tom streng "
                         "slår hjørnekortet av; oppsalget er upåvirket.")
    ap.add_argument("--book-slug", default="",
                    help="Bok som trykkes — bestemmer bakgrunn (bokas aapningsside)")
    ap.add_argument("--background", default="", help="Overstyr bakgrunnsbildet")
    ap.add_argument("--mockup-out", default="",
                    help="lagre ogsaa en 3D-mockup av forsiden hit (cover-modus)")
    ap.add_argument("--mockup-template", default="",
                    help="mal-id paa dp-mockup-server (overstyrer DP_MOCKUP_TEMPLATE)")
    ap.add_argument("--cover-style", choices=["server", "mockup", "flat"], default="server",
                    help="server = PSD-mockup via dp-mockup-server (standard), mockup = innebygd geometri, flat = uten mockup")
    ap.add_argument("--lang", default="nb")
    ap.add_argument("--out", default="")
    ap.add_argument("--pdf", default="")

    args = ap.parse_args()
    STRICT = args.strict
    MOCKUP_TEMPLATE_OVERRIDE = args.mockup_template

    try:
        if args.mode == "cover":
            required = {"--raw": args.raw, "--next-slug": args.next_slug, "--out": args.out}
        elif args.mode == "image":
            required = {"--qr-url": args.qr_url, "--out": args.out}
        elif args.mode == "upload":
            required = {"--file": args.file, "--callback": args.callback}
        else:
            required = {"--pdf": args.pdf, "--qr-url": args.qr_url}
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise SystemExit(f"mangler påkrevde argumenter: {', '.join(missing)}")

        rc = {"cover": mode_cover, "image": mode_image,
              "stamp": mode_stamp, "upload": mode_upload}[args.mode](args)
    except ImportError:
        # En manglende pakke er feil i miljoeet, ikke i ordren. Fail-soft her
        # sendte ordre 1248 videre uten QR paa siste side: boka ville blitt
        # trykt uten "Fortsett eventyret", og ingen ville sett det foer den laa
        # i posten. Miljoefeil skal alltid stoppe ordren.
        warn("MANGLENDE PYTHON-PAKKE — stopper ordren (ingen fail-soft):\n"
             + traceback.format_exc())
        return 2
    except Exception:
        warn("uventet feil — siste side bygges ikke om:\n" + traceback.format_exc())
        rc = 1

    if rc and not STRICT:
        warn("fail-soft: fortsetter ordren med dagens siste side (exit 0)")
        return 0
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

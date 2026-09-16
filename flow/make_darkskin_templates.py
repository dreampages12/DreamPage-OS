# -*- coding: utf-8 -*-
"""Lag utgaver av malsidene der barnets kropp har moerk hudfarge.

Problemet: malene er tegnet med et lyst barn. Headswappen bytter HODET, saa
ansiktet faar barnets egen hudfarge - men hendene, armene, halsen og beina i
malen ligger UTENFOR headmasken og blir sydd tilbake uendret av
InpaintStitchImproved. Et moerkt barn faar altsaa lyse hender. Det er
geometri, ikke kvalitet: ingen prompt eller seed fikser det per ordre.

Loesningen er den samme som for haaret: lag malen om EN gang. Samme side,
samme komposisjon, samme klaer og bakgrunn - bare huden paa kroppen er moerk.

Filene heter det samme pluss suffikset fra dp_order.SKIN_VARIANTS:

    01(magisk-resie-jente).png -> 01(magisk-resie-jente)mork.png

og plukkes opp av variantmekanikken i dp_order. Headmasken lages IKKE paa
nytt: ingenting flytter seg, bare fargen paa huden endrer seg.

TRE masker i spill, ikke bland dem:

* headmasken (manuell, din) - hva headswappen bytter ut per ordre. Roeres ikke.
* haarmasken (make_shorthair_templates) - hvor det lange haaret er.
* hudmasken (denne fila) - den synlige huden PAA KROPPEN, altsaa det som blir
  igjen naar headmasken er trukket fra. Ansiktet males aldri om her: det blir
  likevel erstattet av barnets eget under headswappen, og aa la det staa gjoer
  inpaintingen baade mindre og tryggere.

Hudmasken segmenteres inne i et UTSNITT forankret i headmasken, ikke paa hele
siden - ellers treffer den bamsen, dragen eller hvem andre som staar i scenen.
Bommer den: tegn masken for haand som input/<NN>-skinmask(<brand>).png, saa
brukes din i stedet.

    python make_darkskin_templates.py --book den-magiske-reisen-jente --dry-run
    python make_darkskin_templates.py --book den-magiske-reisen-jente --masks-only
    python make_darkskin_templates.py --book den-magiske-reisen-jente --apply
    python make_darkskin_templates.py --book den-magiske-reisen-jente --apply --region face

TO PASS, i denne rekkefoelgen. `--region hands` lager mork-fila fra malen.
`--region face` maler ansikt og hals oppaa den samme fila. Hendene er det
eneste som betyr noe for den ferdige boka - ansiktet bytter headswappen ut
uansett - men uten ansiktspasset ser base-bildet lyst ut, og da ser man ikke
at varianten virker.

Har boka alt korthaars-maler og du vil ha kombinasjonen, bygg oppaa dem:

    python make_darkskin_templates.py --book den-magiske-reisen-jente --apply \
        --from-variant kort        # -> 01(...)kortmork.png
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import io
import json
import os
import random
import sys

from PIL import Image, ImageChops, ImageFilter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import dp_order

_spec = importlib.util.spec_from_file_location(
    "regen_page", os.path.join(SCRIPT_DIR, "regen_page.py"))
regen = importlib.util.module_from_spec(_spec)
sys.modules["regen_page"] = regen
_spec.loader.exec_module(regen)

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

INPUT_DIR = r"C:\DreamPage-OS\input"
OUTPUT_DIR = r"C:\DreamPage-OS\output"
BOOKS_DIR = r"C:\DreamPage-OS\books"
WORKDIR = os.path.join(INPUT_DIR, "_maskwork")

# Instruksjonen til Klein. To ting maa staa der: at BARE huden endrer seg, og
# at lys og skygge foelger med. Uten det siste blir hendene flate brune
# flekker uten skyggen fra scenen rundt.
DARK_PROMPT = (
    "Change only the skin colour of the child's body. Make the visible skin - "
    "the hands, fingers, arms, neck, legs and feet - a rich deep brown, dark "
    "brown Black skin tone, evenly and naturally, as if the child had always "
    "been drawn with dark brown skin.\n"
    "Keep the existing lighting on the skin: the same highlights, shadows, "
    "warm rim light and reflections, just on darker skin. Keep the exact same "
    "shape, pose and position of every hand, finger, arm and leg.\n"
    "Keep everything else identical: the same clothing, sleeves, colours, "
    "background, objects, composition, lighting and photographic illustration "
    "style. Do not change the clothes. Do not move anything. Do not add or "
    "remove anything. Same art style as the original image.")

# Mixed: mellom malens lyse hud og den moerke varianten. Tonen maa forankres
# i BEGGE retninger, og den nedre grensen maa sies HOEYT: foerste forsoek sa
# bare "medium brown / light brown" og kom ut paa luminans 30 mot morks 27 -
# altsaa praktisk talt den moerke igjen. Modellen trekker mot "brown skin" saa
# snart ordet brown staar der alene. Derfor: konkrete lyse referanser (tan,
# caramel, latte), "only a few shades darker than the original", og et
# eksplisitt forbud mot dark brown.
MEDIUM_PROMPT = (
    "Change only the skin colour of the child's body. Make the visible skin - "
    "the hands, fingers, arms, neck, legs and feet - a medium golden brown, "
    "warm caramel complexion, exactly halfway between the original fair skin "
    "and dark brown skin. This is the skin of a mixed-race child with one "
    "Black parent and one white parent: clearly and noticeably browner and "
    "darker than the original fair skin, but not dark brown. Do not lighten "
    "or brighten the skin.\n"
    "Keep the existing lighting on the skin: the same highlights, shadows, "
    "warm rim light and reflections, just on browner skin. Keep the exact "
    "same shape, pose and position of every hand, finger, arm and leg.\n"
    "Keep everything else identical: the same clothing, sleeves, colours, "
    "background, objects, composition, lighting and photographic illustration "
    "style. Do not change the clothes. Do not move anything. Do not add or "
    "remove anything. Same art style as the original image.")

# Hvilken instruksjon hver variant faar. Staar en variant ikke her, faller den
# tilbake til den moerke - da er det bedre aa legge den inn enn aa gjette.
VARIANT_PROMPTS = {
    "mork": DARK_PROMPT,
    "mixed": MEDIUM_PROMPT,
}

# Ansiktspasset. Kjoeres ETTER hendene, paa mork-fila, og males inne i
# headmasken (pluss en liten margin for halsen). Headswappen bytter uansett
# ut hele det omraadet per ordre, saa dette er for at MALEN skal se ut som
# et moerkt barn - i botten, i testboka og naar du ser over sidene. Uten det
# ser base-bildet lyst ut selv om hendene er moerke, og da ser man ikke at
# varianten virker.
FACE_PROMPT = (
    "Change only the skin colour of the child's face and neck. Make the skin "
    "a rich deep brown, dark brown Black skin tone, evenly and naturally, as "
    "if the child had always been drawn with dark brown skin.\n"
    "Keep the existing lighting: the same highlights, shadows and warm rim "
    "light, just on darker skin. Keep the exact same facial features, the "
    "same expression, the same smile, the same gaze and eye colour, the same "
    "nose and mouth shape, the same head pose and head size.\n"
    "Keep everything else identical: the same hair, the same hair colour, the "
    "same clothing, collar, background, composition and photographic "
    "illustration style. Do not change the hair. Do not move anything. Same "
    "art style as the original image.")

FACE_MEDIUM_PROMPT = FACE_PROMPT.replace(
    "a rich deep brown, dark brown Black skin tone",
    "a light golden tan, soft caramel mixed-race skin tone, only a few shades "
    "darker than fair skin and clearly not dark brown")

FACE_VARIANT_PROMPTS = {
    "mork": FACE_PROMPT,
    "mixed": FACE_MEDIUM_PROMPT,
}

# Ansiktet, ikke hodet: "head" tar med haaret, og da blir haaret brunsvart.
FACE_SEG_PROMPT = "face . neck . ear"

# Hva GroundingDINO skal lete etter. "hand", ikke "arm" og ikke "barn":
# * "barn" tar hele figuren, og da males klaerne om sammen med huden.
# * "arm" tar hele armen INKLUDERT ermet - proevd, den lakkerte jakka roed.
# Figurene i disse boekene har lange ermer og lange bukser, saa hendene ER
# den synlige huden paa kroppen. Har en bok bare armer eller bein, utvid med
#     --seg-prompt "hand . bare arm . bare leg"
# og se over overlayet i output/darkskin/<bok>/ foer du rendrer.
SEG_PROMPT = "hand"


# --------------------------------------------------------------------------
# Hudmaske
# --------------------------------------------------------------------------
def _bbox_of(mask: Image.Image):
    solid = mask.convert("L").point(lambda v: 255 if v > 32 else 0)
    box = solid.getbbox()
    if not box:
        raise SystemExit("headmasken er tom")
    return box


def _crop_box(template: Image.Image, head: Image.Image,
              side_pad: float, down_pad: float):
    """Utsnittet segmenteringen kjoerer paa.

    Forankret i hodet og strukket NEDOVER: kroppen henger under hodet, og
    alt som ligger langt til siden er scenen - bamser, moebler, andre figurer
    - som vi ikke vil at DINO skal finne hender paa.
    """
    x0, y0, x1, y1 = _bbox_of(head)
    w, h = x1 - x0, y1 - y0
    cx = (x0 + x1) / 2.0
    half_w = w * side_pad / 2.0
    return (max(0, int(cx - half_w)), max(0, int(y0)),
            min(template.width, int(cx + half_w)),
            min(template.height, int(y1 + h * down_pad)))


def _segment(crop_name: str, tag: str, prompt_text: str, threshold: float) -> Image.Image:
    out_dir = os.path.join(OUTPUT_DIR, "darkskin", "_seg")
    os.makedirs(out_dir, exist_ok=True)
    for stale in glob.glob(os.path.join(out_dir, tag + "_*")):
        os.remove(stale)
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": crop_name}},
        "2": {"class_type": "SAMModelLoader (segment anything)",
              "inputs": {"model_name": "sam_vit_h (2.56GB)"}},
        "3": {"class_type": "GroundingDinoModelLoader (segment anything)",
              "inputs": {"model_name": "GroundingDINO_SwinB (938MB)"}},
        "4": {"class_type": "GroundingDinoSAMSegment (segment anything)",
              "inputs": {"sam_model": ["2", 0], "grounding_dino_model": ["3", 0],
                         "image": ["1", 0], "prompt": prompt_text,
                         "threshold": threshold}},
        "8": {"class_type": "MaskToImage", "inputs": {"mask": ["4", 1]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"filename_prefix": "darkskin/_seg/" + tag,
                         "images": ["8", 0]}},
    }
    pid = regen.comfy_post("/prompt", {"prompt": graph})["prompt_id"]
    regen.wait_for(pid, timeout=900)
    files = sorted(glob.glob(os.path.join(out_dir, tag + "_*")))
    if not files:
        raise SystemExit("segmenteringen ga ingen maske for " + tag)
    return Image.open(files[-1]).convert("L")


def skin_mask_name(mask_image: str) -> str:
    """01-headmask(magisk-resie-jente).png -> 01-skinmask(magisk-resie-jente).png"""
    return (mask_image or "").replace("-headmask(", "-skinmask(")


def build_skin_mask(template_file: str, head_file: str, tag: str,
                    side_pad: float = 2.6, down_pad: float = 3.0,
                    threshold: float = 0.25, grow: int = 6, feather: int = 4,
                    head_margin: int = 12,
                    prompt_text: str = SEG_PROMPT) -> Image.Image:
    """Hudmaske = segmentert hud MINUS den manuelle headmasken.

    Hodet trekkes fra fordi det likevel byttes av headswappen. Blir det med,
    males ansiktet om til ingen nytte - og en stoerre maske er en stoerre
    sjanse for at noe annet driver.
    """
    os.makedirs(WORKDIR, exist_ok=True)
    template = Image.open(os.path.join(INPUT_DIR, template_file)).convert("RGB")
    head = Image.open(os.path.join(INPUT_DIR, head_file)).convert("L")
    if head.size != template.size:
        head = head.resize(template.size)

    box = _crop_box(template, head, side_pad, down_pad)
    crop_rel = "_maskwork/%s-skincrop.png" % tag
    template.crop(box).save(os.path.join(INPUT_DIR, crop_rel.replace("/", os.sep)))
    seg = _segment(crop_rel, tag, prompt_text, threshold)
    seg = seg.resize((box[2] - box[0], box[3] - box[1]))

    full = Image.new("L", template.size, 0)
    full.paste(seg, box[:2])
    full = full.point(lambda v: 255 if v > 96 else 0)
    if grow:
        full = full.filter(ImageFilter.MaxFilter(grow * 2 + 1))

    # Headmasken vokser litt foer den trekkes fra, saa vi ikke maler en
    # brun kant rundt kjeven som headswappen siden legger ansikt oppaa.
    solid_head = head.point(lambda v: 255 if v > 32 else 0)
    if head_margin:
        solid_head = solid_head.filter(ImageFilter.MaxFilter(head_margin * 2 + 1))
    full = ImageChops.subtract(full, solid_head)

    if feather:
        full = full.filter(ImageFilter.GaussianBlur(feather))
    return full


def face_mask_name(mask_image: str) -> str:
    """01-headmask(magisk-resie-jente).png -> 01-facemask(magisk-resie-jente).png"""
    return (mask_image or "").replace("-headmask(", "-facemask(")


def build_face_mask(template_file: str, head_file: str, tag: str,
                    pad: float = 1.3, threshold: float = 0.25,
                    grow: int = 4, feather: int = 6, head_margin: int = 10,
                    prompt_text: str = FACE_SEG_PROMPT) -> Image.Image:
    """Ansiktsmaske = segmentert ansikt BEGRENSET til headmasken.

    Motsatt av hudmasken, som trekker headmasken FRA. Her vil vi nettopp
    inn i hodet - men bare der, og bare paa ansiktet: haaret ligger ogsaa
    inne i headmasken, og segmenteringen er det eneste som skiller dem.
    Headmasken faar en liten margin saa halsen rett under kjeven blir med.
    """
    os.makedirs(WORKDIR, exist_ok=True)
    template = Image.open(os.path.join(INPUT_DIR, template_file)).convert("RGB")
    head = Image.open(os.path.join(INPUT_DIR, head_file)).convert("L")
    if head.size != template.size:
        head = head.resize(template.size)

    x0, y0, x1, y1 = _bbox_of(head)
    w, h = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    hw, hh = w * pad / 2.0, h * pad / 2.0
    box = (max(0, int(cx - hw)), max(0, int(cy - hh)),
           min(template.width, int(cx + hw)),
           min(template.height, int(cy + hh)))

    crop_rel = "_maskwork/%s-facecrop.png" % tag
    template.crop(box).save(os.path.join(INPUT_DIR, crop_rel.replace("/", os.sep)))
    seg = _segment(crop_rel, tag + "-face", prompt_text, threshold)
    seg = seg.resize((box[2] - box[0], box[3] - box[1]))

    full = Image.new("L", template.size, 0)
    full.paste(seg, box[:2])
    full = full.point(lambda v: 255 if v > 96 else 0)
    if grow:
        full = full.filter(ImageFilter.MaxFilter(grow * 2 + 1))

    solid_head = head.point(lambda v: 255 if v > 32 else 0)
    if head_margin:
        solid_head = solid_head.filter(ImageFilter.MaxFilter(head_margin * 2 + 1))
    full = ImageChops.darker(full, solid_head)

    if feather:
        full = full.filter(ImageFilter.GaussianBlur(feather))
    return full


# --------------------------------------------------------------------------
# Moerk hud
# --------------------------------------------------------------------------
def _darkskin_graph(template_file: str, skinmask_file: str, prefix: str,
                    seed: int, steps: int, guidance: float,
                    expand: int, prompt_text: str) -> dict:
    return {
        "192": {"class_type": "LoadImage", "inputs": {"image": template_file}},
        "165": {"class_type": "LoadImageMask",
                "inputs": {"image": skinmask_file, "channel": "red"}},
        "184": {"class_type": "InpaintCropImproved", "inputs": {
            "downscale_algorithm": "lanczos", "upscale_algorithm": "lanczos",
            "preresize": False, "preresize_mode": "ensure minimum resolution",
            "preresize_min_width": 1024, "preresize_min_height": 1024,
            "preresize_max_width": 8192, "preresize_max_height": 8192,
            "mask_fill_holes": True, "mask_expand_pixels": expand,
            "mask_invert": False, "mask_blend_pixels": 32,
            "mask_hipass_filter": 0.1, "extend_for_outpainting": False,
            "extend_up_factor": 1, "extend_down_factor": 1,
            "extend_left_factor": 1, "extend_right_factor": 1,
            "context_from_mask_extend_factor": 1.6,
            "output_resize_to_target_size": True,
            "output_target_width": 1024, "output_target_height": 1024,
            "output_padding": "32", "device_mode": "gpu (much faster)",
            "image": ["192", 0], "mask": ["165", 0]}},
        "102": {"class_type": "VAELoader",
                "inputs": {"vae_name": "flux2-vae.safetensors"}},
        "201": {"class_type": "UNETLoader",
                "inputs": {"unet_name": "flux-2-klein-9b.safetensors",
                           "weight_dtype": "default"}},
        "202": {"class_type": "CLIPLoaderGGUF",
                "inputs": {"clip_name": "Qwen3-8B-Q8_0.gguf",
                           "type": "stable_diffusion"}},
        "107": {"class_type": "CLIPTextEncode",
                "inputs": {"text": prompt_text, "clip": ["202", 0]}},
        "136": {"class_type": "ConditioningZeroOut",
                "inputs": {"conditioning": ["107", 0]}},
        "150": {"class_type": "VAEEncode",
                "inputs": {"pixels": ["184", 1], "vae": ["102", 0]}},
        "112": {"class_type": "ReferenceLatent",
                "inputs": {"conditioning": ["107", 0], "latent": ["150", 0]}},
        "100": {"class_type": "FluxGuidance",
                "inputs": {"guidance": guidance, "conditioning": ["112", 0]}},
        "152": {"class_type": "SetLatentNoiseMask",
                "inputs": {"samples": ["150", 0], "mask": ["184", 2]}},
        "156": {"class_type": "LanPaint_KSampler", "inputs": {
            "seed": seed, "steps": steps, "cfg": 1, "sampler_name": "euler",
            "scheduler": "simple", "denoise": 1, "LanPaint_NumSteps": 2,
            "LanPaint_PromptMode": "Image First",
            "LanPaint_Info": "LanPaint KSampler.",
            "Inpainting_mode": "\U0001f5bc\ufe0f Image Inpainting",
            "More Info, Bug Report, Star on GitHub \u2b50": "lanpaint_star_button",
            "model": ["201", 0], "positive": ["100", 0], "negative": ["136", 0],
            "latent_image": ["152", 0]}},
        "104": {"class_type": "VAEDecode",
                "inputs": {"samples": ["156", 0], "vae": ["102", 0]}},
        "183": {"class_type": "InpaintStitchImproved",
                "inputs": {"stitcher": ["184", 0], "inpainted_image": ["104", 0]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"filename_prefix": prefix, "images": ["183", 0]}},
    }


def render_darkskin(template_file: str, skinmask_file: str, book: str,
                    tag: str, count: int, steps: int, guidance: float,
                    expand: int, prompt_text: str) -> list[str]:
    rel = "darkskin/%s/%s" % (book, tag)
    out_dir = os.path.join(OUTPUT_DIR, "darkskin", book)
    for stale in glob.glob(os.path.join(out_dir, tag + "_*")):
        os.remove(stale)
    for _ in range(count):
        graph = _darkskin_graph(template_file, skinmask_file, rel,
                                random.randrange(1, 2 ** 53), steps,
                                guidance, expand, prompt_text)
        pid = regen.comfy_post("/prompt", {"prompt": graph})["prompt_id"]
        regen.wait_for(pid, timeout=1800)
    return sorted(glob.glob(os.path.join(out_dir, tag + "_*")))


# --------------------------------------------------------------------------
def load_config(book: str) -> dict:
    with io.open(os.path.join(BOOKS_DIR, book, "config.json"),
                 encoding="utf-8-sig") as fh:
        return json.load(fh)


def source_template(template: str, from_variant: str) -> str:
    """Malen vi bygger oppaa: standarden, eller en haarvariant av den."""
    if not from_variant:
        return template
    suffix = dp_order.HAIR_VARIANTS.get(from_variant, {}).get("suffix")
    if suffix is None:
        raise SystemExit("ukjent --from-variant %r (kjenner %s)"
                         % (from_variant, ", ".join(dp_order.HAIR_VARIANTS)))
    stem, ext = os.path.splitext(template)
    return "%s%s%s" % (stem, suffix, ext)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--masks-only", action="store_true",
                    help="lag bare hudmaskene + overlay, ingen rendring")
    ap.add_argument("--pages", default="", help="komma-separert, f.eks. page01,page08")
    ap.add_argument("--skip", default="", help="komma-separert, sider som staar over")
    ap.add_argument("--variant", default="mork",
                    help="navn i dp_order.SKIN_VARIANTS")
    ap.add_argument("--from-variant", default="",
                    help="bygg oppaa en haarvariant, f.eks. kort")
    ap.add_argument("--region", default="hands", choices=("hands", "face"),
                    help="hands: hendene paa kroppen (kjoeres foerst, lager "
                         "mork-fila). face: ansikt og hals, males oppaa "
                         "mork-fila som alt finnes.")
    ap.add_argument("--count", type=int, default=1, help="forslag per side")
    ap.add_argument("--steps", type=int, default=6)
    ap.add_argument("--guidance", type=float, default=6.0)
    ap.add_argument("--expand", type=int, default=12)
    ap.add_argument("--side-pad", type=float, default=2.6)
    ap.add_argument("--down-pad", type=float, default=3.0)
    ap.add_argument("--threshold", type=float, default=0.25)
    ap.add_argument("--grow", type=int, default=6)
    ap.add_argument("--feather", type=int, default=4)
    ap.add_argument("--head-margin", type=int, default=12)
    ap.add_argument("--seg-prompt", default=SEG_PROMPT)
    ap.add_argument("--skin-prompt", default=None,
                    help="overstyr instruksjonen; ellers VARIANT_PROMPTS[variant]")
    ap.add_argument("--remask", action="store_true",
                    help="lag hudmasken paa nytt selv om fila finnes")
    ap.add_argument("--overwrite", action="store_true",
                    help="lag varianten paa nytt selv om fila finnes")
    args = ap.parse_args()
    if not (args.apply or args.dry_run or args.masks_only):
        ap.error("bruk --dry-run, --masks-only eller --apply")

    if args.skin_prompt is None:
        args.skin_prompt = (FACE_VARIANT_PROMPTS.get(args.variant, FACE_PROMPT)
                            if args.region == "face"
                            else VARIANT_PROMPTS.get(args.variant, DARK_PROMPT))
    if args.region == "face" and args.seg_prompt == SEG_PROMPT:
        args.seg_prompt = FACE_SEG_PROMPT
    suffix = dp_order.SKIN_VARIANTS.get(args.variant, {}).get("suffix")
    if not suffix:
        ap.error("ukjent hudvariant %r (kjenner %s)"
                 % (args.variant, ", ".join(dp_order.SKIN_VARIANTS)))

    config = load_config(args.book)
    pages = config.get("pages") or []
    if args.pages:
        wanted = {p.strip() for p in args.pages.split(",") if p.strip()}
        pages = [p for p in pages if p["page_key"] in wanted]
    if args.skip:
        unwanted = {p.strip() for p in args.skip.split(",") if p.strip()}
        pages = [p for p in pages if p["page_key"] not in unwanted]
    if not pages:
        raise SystemExit("ingen sider å kjøre")

    plan = []
    for page in pages:
        template = page.get("template_image")
        head = page.get("mask_image")
        if not template or not head:
            print("  hopper over %s: mangler mal eller maske" % page["page_key"])
            continue
        src = source_template(template, args.from_variant)
        stem, ext = os.path.splitext(src)
        out = "%s%s%s" % (stem, suffix, ext)
        if args.region == "face":
            # Ansiktspasset males OPPAA mork-fila, ikke ved siden av den:
            # kilde og resultat er samme fil. Kjoerer du det foer hendene,
            # finnes ikke fila - og da skal vi si det, ikke lage en variant
            # med moerkt ansikt og lyse hender.
            src = out
        if not os.path.isfile(os.path.join(INPUT_DIR, src)):
            print("  hopper over %s: mangler kildemal %s%s"
                  % (page["page_key"], src,
                     " (kjoer --region hands foerst)" if args.region == "face" else ""))
            continue
        plan.append({
            "page_key": page["page_key"],
            "template": src,
            "head": head,
            # Hud- og ansiktsmasken er FELLES for haarvariantene: haaret
            # ligger ikke i dem, saa de er de samme uansett hvilken mal vi
            # bygger paa.
            "skin": (face_mask_name(head) if args.region == "face"
                     else skin_mask_name(head)),
            "out": out,
            "tag": page["page_key"] + ("-face" if args.region == "face" else ""),
        })

    print("bok %s, hudvariant %s (suffiks %r), omraade %s%s"
          % (args.book, args.variant, suffix, args.region,
             ", bygger paa %s" % args.from_variant if args.from_variant else ""))
    for item in plan:
        skin_path = os.path.join(INPUT_DIR, item["skin"])
        note = "hudmaske finnes" if os.path.isfile(skin_path) else "segmenteres"
        done = " [finnes]" if os.path.isfile(
            os.path.join(INPUT_DIR, item["out"])) else ""
        print("  %-8s %-32s -> %-36s (%s)%s"
              % (item["page_key"], item["template"], item["out"], note, done))
    if args.dry_run and not (args.apply or args.masks_only):
        print("dry-run (ingenting kjørt)")
        return 0

    book_out = os.path.join(OUTPUT_DIR, "darkskin", args.book)
    os.makedirs(book_out, exist_ok=True)
    for n, item in enumerate(plan, 1):
        out_path = os.path.join(INPUT_DIR, item["out"])
        # Ansiktspasset skriver til fila det leser fra, saa "finnes fila" sier
        # ingenting - og masken kan vaere laget av --masks-only uten at noe er
        # rendret. Markoeren er rendringens EGEN utdatafil: bare
        # render_darkskin lager den. Uten den ville et nytt ansiktspass malt
        # oppaa et allerede moerkt ansikt og gjort det svart.
        if args.region == "face":
            skip_done = bool(glob.glob(os.path.join(
                OUTPUT_DIR, "darkskin", args.book, item["tag"] + "_*")))
        else:
            skip_done = os.path.isfile(out_path)
        if args.apply and skip_done and not args.overwrite:
            print("[%d/%d] %s: finnes alt, hopper over" % (n, len(plan), item["page_key"]))
            continue
        print("[%d/%d] %s" % (n, len(plan), item["page_key"]))

        skin_path = os.path.join(INPUT_DIR, item["skin"])
        if args.remask or not os.path.isfile(skin_path):
            print("    %smaske ..." % ("ansikts" if args.region == "face" else "hud"))
            if args.region == "face":
                mask = build_face_mask(
                    item["template"], item["head"], item["tag"],
                    threshold=args.threshold, grow=args.grow,
                    feather=args.feather, head_margin=args.head_margin,
                    prompt_text=args.seg_prompt)
            else:
                mask = build_skin_mask(
                    item["template"], item["head"], item["tag"],
                    side_pad=args.side_pad, down_pad=args.down_pad,
                    threshold=args.threshold, grow=args.grow,
                    feather=args.feather, head_margin=args.head_margin,
                    prompt_text=args.seg_prompt)
            if not mask.getbbox():
                print("    TOM maske - ingen hud funnet, hopper over."
                      "\n    Tegn input/%s for haand om sida faktisk har hud."
                      % item["skin"])
                continue
            mask.save(skin_path)
        else:
            print("    maske: bruker %s" % item["skin"])

        # overlay saa du kan se hva som ble maskert
        mask = Image.open(skin_path).convert("L")
        tpl = Image.open(os.path.join(INPUT_DIR, item["template"])).convert("RGB")
        if mask.size != tpl.size:
            mask = mask.resize(tpl.size)
        red = Image.new("RGB", tpl.size, (255, 0, 0))
        ov = tpl.copy()
        ov.paste(red, (0, 0), mask.point(lambda v: int(v * 0.55)))
        ov.save(os.path.join(book_out, item["tag"] + "-maske.png"))

        if args.masks_only:
            print("    -> output/darkskin/%s/%s-maske.png" % (args.book, item["tag"]))
            continue

        print("    moerk %s ..." % ("ansikt" if args.region == "face" else "hud"))
        files = render_darkskin(item["template"], item["skin"], args.book,
                                item["tag"], args.count, args.steps,
                                args.guidance, args.expand, args.skin_prompt)
        if not files:
            print("    INGEN utdata")
            continue
        Image.open(files[0]).convert("RGB").save(out_path)
        print("    -> input/%s" % item["out"])

    print("ferdig. se over output/darkskin/%s/ foer du tar variantene i bruk."
          % args.book)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

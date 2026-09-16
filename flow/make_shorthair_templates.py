# -*- coding: utf-8 -*-
"""Lag korthaarede utgaver av malsidene i en bok.

Problemet: malene har en jente med langt haar. Er barnet en baby eller har
kort haar, kan headswappen ikke fikse det - haaret utenfor headmasken blir
sydd tilbake uendret av InpaintStitchImproved, saa det lange haaret HENGER
IGJEN uansett prompt og seed. Se ordre 1423.

Loesningen er aa lage malen om EN gang i stedet for aa slaass med den per
ordre: samme side, samme hode, men kort haar. Da fungerer den vanlige
headswappen som den skal, og du ser resultatet foer det gaar til en kunde.

Filene heter det samme pluss suffikset fra dp_order.HAIR_VARIANTS:

    08(havfrue).png -> 08(havfrue)kort.png

og plukkes opp av variantmekanikken i dp_order. Headmasken lages IKKE paa
nytt: hodet staar paa samme sted i samme stoerrelse, saa den manuelle
headmasken gjelder uendret.

To masker i spill, ikke bland dem:

* headmasken (manuell, din) - hva headswappen bytter ut per ordre. Roeres ikke.
* haarmasken (denne fila) - hvor det lange haaret ER, og dermed hva som males
  om naar malen lages. Brukes bare her, aldri per ordre.

Haarmasken segmenteres inne i et UTSNITT rundt headmasken, ikke paa hele
siden. Kjoerer du segmenteringen paa hele siden treffer den havfrua, dragen
eller hvem andre som staar i scenen. Bommer den likevel: tegn masken for haand
som input/<NN>-hairmask(<brand>).png, saa brukes din i stedet.

    python make_shorthair_templates.py --book havfruen --dry-run
    python make_shorthair_templates.py --book havfruen --apply
    python make_shorthair_templates.py --book havfruen --apply --pages page03,page08
    python make_shorthair_templates.py --book havfruen --apply --skip page00
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

# Instruksjonen til Klein. "Fortsett bakgrunnen" er den viktige delen: uten
# den maler modellen gjerne en skulder eller en flekk der haaret laa.
HAIR_PROMPT = (
    "Change only the hairstyle of the child. Give the child a short haircut: "
    "a soft, fine, chin-length toddler bob with light wispy baby hair, ending "
    "at the jawline. Remove all of the long hair below the jaw. Where the long "
    "hair used to be, continue the existing background and the child's "
    "clothing and shoulders seamlessly and naturally, matching the surrounding "
    "colours, lighting and painting style exactly.\n"
    "Keep everything else identical: the same face, identity, expression, "
    "gaze, head pose, head size and position, skin tone, hair colour, "
    "clothing, body, background, composition, lighting and illustration "
    "style. Do not change the face. Do not add accessories. Same art style as "
    "the original image.")

# Halvlangt: mellom malens lange haar og bob-en over. Lengden maa forankres i
# noe modellen ser i bildet - "shoulder length" alene gir like gjerne en bob
# eller uendret haar - derfor sies BAADE hvor det slutter (skuldrene) og hva
# som skal vekk (alt under skulderbladene).
MEDIUM_PROMPT = (
    "Change only the hairstyle of the child. Give the child medium-length "
    "hair that ends at the shoulders: clearly shorter than the original long "
    "hair, but clearly longer than a chin-length bob. The hair should just "
    "touch the top of the shoulders and stop there. Remove all of the hair "
    "below the shoulder blades. Where the long hair used to be, continue the "
    "existing background and the child's clothing and shoulders seamlessly "
    "and naturally, matching the surrounding colours, lighting and painting "
    "style exactly.\n"
    "Keep everything else identical: the same face, identity, expression, "
    "gaze, head pose, head size and position, skin tone, hair colour, "
    "clothing, body, background, composition, lighting and illustration "
    "style. Do not change the face. Do not add accessories. Same art style as "
    "the original image.")

# Hvilken instruksjon hver variant faar. Staar en variant ikke her, faller den
# tilbake til kort-prompten - da er det bedre aa legge den inn enn aa gjette.
VARIANT_PROMPTS = {
    "kort": HAIR_PROMPT,
    "medium": MEDIUM_PROMPT,
}


# --------------------------------------------------------------------------
# Haarmaske
# --------------------------------------------------------------------------
def _bbox_of(mask: Image.Image):
    solid = mask.convert("L").point(lambda v: 255 if v > 32 else 0)
    box = solid.getbbox()
    if not box:
        raise SystemExit("headmasken er tom")
    return box


def _crop_box(template: Image.Image, head: Image.Image, pad: float):
    """Utsnittet segmenteringen kjoerer paa.

    Sentrert litt UNDER hodet: haaret henger nedover, saa det trengs mer luft
    under enn over. Alt utenfor er andre figurer vi ikke vil treffe.
    """
    x0, y0, x1, y1 = _bbox_of(head)
    w, h = x1 - x0, y1 - y0
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0 + h * 0.25
    half_w, half_h = w * pad / 2.0, h * pad / 2.0
    return (max(0, int(cx - half_w)), max(0, int(cy - half_h)),
            min(template.width, int(cx + half_w)),
            min(template.height, int(cy + half_h)))


def _segment(crop_name: str, tag: str, prompt_text: str, threshold: float) -> Image.Image:
    out_dir = os.path.join(OUTPUT_DIR, "shorthair", "_seg")
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
              "inputs": {"filename_prefix": "shorthair/_seg/" + tag,
                         "images": ["8", 0]}},
    }
    pid = regen.comfy_post("/prompt", {"prompt": graph})["prompt_id"]
    regen.wait_for(pid, timeout=900)
    files = sorted(glob.glob(os.path.join(out_dir, tag + "_*")))
    if not files:
        raise SystemExit("segmenteringen ga ingen maske for " + tag)
    return Image.open(files[-1]).convert("L")


def hair_mask_name(mask_image: str) -> str:
    """01-headmask(havfrue).png -> 01-hairmask(havfrue).png"""
    return (mask_image or "").replace("-headmask(", "-hairmask(")


def build_hair_mask(template_file: str, head_file: str, tag: str,
                    pad: float = 1.6, threshold: float = 0.25,
                    grow: int = 8, feather: int = 6,
                    prompt_text: str = "hair") -> Image.Image:
    """Full haarmaske = segmentert haar UNION den manuelle headmasken."""
    os.makedirs(WORKDIR, exist_ok=True)
    template = Image.open(os.path.join(INPUT_DIR, template_file)).convert("RGB")
    head = Image.open(os.path.join(INPUT_DIR, head_file)).convert("L")
    if head.size != template.size:
        head = head.resize(template.size)

    box = _crop_box(template, head, pad)
    crop_rel = "_maskwork/%s-crop.png" % tag
    template.crop(box).save(os.path.join(INPUT_DIR, crop_rel.replace("/", os.sep)))
    seg = _segment(crop_rel, tag, prompt_text, threshold)
    seg = seg.resize((box[2] - box[0], box[3] - box[1]))

    full = Image.new("L", template.size, 0)
    full.paste(seg, box[:2])
    merged = ImageChops.lighter(full, head).point(lambda v: 255 if v > 96 else 0)
    if grow:
        merged = merged.filter(ImageFilter.MaxFilter(grow * 2 + 1))
    if feather:
        merged = merged.filter(ImageFilter.GaussianBlur(feather))
    return merged


# --------------------------------------------------------------------------
# Kort haar
# --------------------------------------------------------------------------
def _shorthair_graph(template_file: str, hairmask_file: str, prefix: str,
                     seed: int, steps: int, guidance: float,
                     expand: int, prompt_text: str) -> dict:
    return {
        "192": {"class_type": "LoadImage", "inputs": {"image": template_file}},
        "165": {"class_type": "LoadImageMask",
                "inputs": {"image": hairmask_file, "channel": "red"}},
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


def render_shorthair(template_file: str, hairmask_file: str, book: str,
                     tag: str, count: int, steps: int, guidance: float,
                     expand: int, prompt_text: str) -> list[str]:
    rel = "shorthair/%s/%s" % (book, tag)
    out_dir = os.path.join(OUTPUT_DIR, "shorthair", book)
    for stale in glob.glob(os.path.join(out_dir, tag + "_*")):
        os.remove(stale)
    for _ in range(count):
        graph = _shorthair_graph(template_file, hairmask_file, rel,
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pages", default="", help="komma-separert, f.eks. page01,page08")
    ap.add_argument("--skip", default="", help="komma-separert, sider som staar over")
    ap.add_argument("--variant", default="kort",
                    help="navn i dp_order.HAIR_VARIANTS")
    ap.add_argument("--count", type=int, default=1, help="forslag per side")
    ap.add_argument("--steps", type=int, default=6)
    ap.add_argument("--guidance", type=float, default=6.0)
    ap.add_argument("--expand", type=int, default=25)
    ap.add_argument("--pad", type=float, default=1.6)
    ap.add_argument("--threshold", type=float, default=0.25)
    ap.add_argument("--hair-prompt", default=None,
                    help="overstyr instruksjonen; ellers VARIANT_PROMPTS[variant]")
    ap.add_argument("--any-book", action="store_true",
                    help="kjør selv om boka ikke er i HAIR_VARIANT_BOOKS")
    ap.add_argument("--remask", action="store_true",
                    help="lag haarmasken paa nytt selv om fila finnes")
    ap.add_argument("--overwrite", action="store_true",
                    help="lag varianten paa nytt selv om fila finnes")
    args = ap.parse_args()
    if not args.apply and not args.dry_run:
        ap.error("bruk --dry-run eller --apply")

    if args.hair_prompt is None:
        args.hair_prompt = VARIANT_PROMPTS.get(args.variant, HAIR_PROMPT)
    suffix = dp_order.HAIR_VARIANTS.get(args.variant, {}).get("suffix")
    if not suffix:
        ap.error("ukjent hårvariant %r (kjenner %s)"
                 % (args.variant, ", ".join(dp_order.HAIR_VARIANTS)))

    config = load_config(args.book)
    if not dp_order.book_has_hair_variants(config) and not args.any_book:
        raise SystemExit(
            "%s er ikke i dp_order.HAIR_VARIANT_BOOKS - bare jentebøkene har "
            "figurer med langt hår, og bare der gir kort-varianten mening.\n"
            "Er det feil, legg boka inn i settet. Vil du kjøre den likevel: "
            "--any-book (malene lages, men botten viser ingen 💇-knapp)."
            % args.book)
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
        stem, ext = os.path.splitext(template)
        plan.append({
            "page_key": page["page_key"],
            "template": template,
            "head": head,
            "hair": hair_mask_name(head),
            "out": "%s%s%s" % (stem, suffix, ext),
            "tag": page["page_key"],
        })

    print("bok %s, variant %s (suffiks %r)" % (args.book, args.variant, suffix))
    for item in plan:
        hair_path = os.path.join(INPUT_DIR, item["hair"])
        note = "haarmaske finnes" if os.path.isfile(hair_path) else "segmenteres"
        done = " [finnes]" if os.path.isfile(
            os.path.join(INPUT_DIR, item["out"])) else ""
        print("  %-8s %-24s -> %-28s (%s)%s"
              % (item["page_key"], item["template"], item["out"], note, done))
    if not args.apply:
        print("dry-run (ingenting kjørt)")
        return 0

    os.makedirs(os.path.join(OUTPUT_DIR, "shorthair", args.book), exist_ok=True)
    for n, item in enumerate(plan, 1):
        out_path = os.path.join(INPUT_DIR, item["out"])
        if os.path.isfile(out_path) and not args.overwrite:
            print("[%d/%d] %s: finnes alt, hopper over" % (n, len(plan), item["page_key"]))
            continue
        print("[%d/%d] %s" % (n, len(plan), item["page_key"]))

        hair_path = os.path.join(INPUT_DIR, item["hair"])
        if args.remask or not os.path.isfile(hair_path):
            print("    haarmaske ...")
            mask = build_hair_mask(item["template"], item["head"], item["tag"],
                                   pad=args.pad, threshold=args.threshold,
                                   prompt_text="hair")
            mask.save(hair_path)
            # overlay saa du kan se hva som ble maskert
            tpl = Image.open(os.path.join(INPUT_DIR, item["template"])).convert("RGB")
            red = Image.new("RGB", tpl.size, (255, 0, 0))
            ov = tpl.copy()
            ov.paste(red, (0, 0), mask.point(lambda v: int(v * 0.55)))
            ov.save(os.path.join(OUTPUT_DIR, "shorthair", args.book,
                                 item["tag"] + "-maske.png"))
        else:
            print("    haarmaske: bruker %s" % item["hair"])

        print("    kort haar ...")
        files = render_shorthair(item["template"], item["hair"], args.book,
                                 item["tag"], args.count, args.steps,
                                 args.guidance, args.expand, args.hair_prompt)
        if not files:
            print("    INGEN utdata")
            continue
        Image.open(files[0]).convert("RGB").save(out_path)
        print("    -> input/%s" % item["out"])

    print("ferdig. se over output/shorthair/%s/ foer du tar variantene i bruk."
          % args.book)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

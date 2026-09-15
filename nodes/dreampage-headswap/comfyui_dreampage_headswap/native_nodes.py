"""DreamPage Studio: usable with the user's existing distilled Klein 9B model."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import numpy as np
import torch
from PIL import Image, ImageDraw, ImageOps

from dreampage_headswap.inference.native_references import prepare_references, reference_contact_sheet
from dreampage_headswap.inference.native_image_ops import prepare_native_scene, finish_native_crop, review_diagnostics
from dreampage_headswap.inference.native_klein import encode_identity, build_swap_prompt, condition_klein, sample_klein
from dreampage_headswap.evaluation.metrics import preservation_metrics
from dreampage_headswap.utils.images import resize_array
from .conversion import image_to_array, images_to_arrays, mask_to_array, array_to_image, array_to_mask

CATEGORY = "DreamPage/Studio"


def result(values, report):
    text = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False, default=str)
    return {"ui": {"dp_report": [text]}, "result": (*values, text)}


class DP_LoadPhoto:
    CATEGORY = CATEGORY
    DESCRIPTION = "Load one still photo with Pillow into CPU float32. Keeps a defined RGB pixel baseline for exact final PNG checks. Also exposes a chosen mask channel; white is editable. Animated inputs are rejected."
    FUNCTION = "load"
    RETURN_TYPES = ("IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("image", "mask", "report")

    @classmethod
    def INPUT_TYPES(cls):
        import folder_paths
        Image.init()
        supported = set(Image.registered_extensions())
        files = sorted(p.name for p in Path(folder_paths.get_input_directory()).iterdir()
                       if p.is_file() and p.suffix.lower() in supported)
        return {"required": {"image": (files, {"image_upload": True}),
                             "mask_channel": (["red", "green", "blue", "alpha"], {"default": "red"})}}

    @classmethod
    def IS_CHANGED(cls, image, mask_channel="red"):
        import folder_paths
        return hashlib.sha256(Path(folder_paths.get_annotated_filepath(image)).read_bytes()).hexdigest()

    @classmethod
    def VALIDATE_INPUTS(cls, image, mask_channel="red"):
        import folder_paths
        return True if folder_paths.exists_annotated_filepath(image) else "Selected photo does not exist"

    def load(self, image, mask_channel="red"):
        import folder_paths
        path = Path(folder_paths.get_annotated_filepath(image))
        with Image.open(path) as file:
            if getattr(file, "n_frames", 1) != 1:
                raise ValueError("DreamPage requires one still photo, not an animation or multiple frames")
            oriented = ImageOps.exif_transpose(file)
            if oriented.mode in {"I", "F", "I;16", "I;16B", "I;16L"}:
                raise ValueError("Convert high-bit-depth images explicitly to 8-bit sRGB before loading")
            pixels = np.asarray(oriented.convert("RGB"), dtype=np.uint8).copy()
            if mask_channel == "alpha":
                if "A" not in oriented.getbands() and "transparency" not in oriented.info:
                    raise ValueError("Photo has no alpha channel; choose red for a grayscale headmask")
                mask = np.asarray(oriented.convert("RGBA"), dtype=np.float32)[...,3] / 255
            elif mask_channel in {"red", "green", "blue"}:
                mask = pixels[..., {"red":0,"green":1,"blue":2}[mask_channel]].astype(np.float32)/255
            else:
                raise ValueError("Unknown mask channel")
        report = {"decoder": "Pillow RGB8 with EXIF orientation", "shape": list(pixels.shape),
                  "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                  "decoded_rgb_sha256": hashlib.sha256(pixels.tobytes()).hexdigest(),
                  "mask_channel": mask_channel, "alpha_inverted": False,
                  "training_enrollment": False}
        return result((array_to_image(pixels), array_to_mask(mask)), report)


class DP_ReferenceStudio:
    CATEGORY = CATEGORY
    DESCRIPTION = "Prepare up to three distinct views of ONE person. Keeps aspect ratio. Optional white headmasks isolate head/hair; without them supply tightly framed portraits. No face recognition or training."
    FUNCTION = "prepare"
    RETURN_TYPES = ("DP_REFERENCES", "IMAGE", "STRING")
    RETURN_NAMES = ("references", "prepared_views", "report")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"person": ("IMAGE", {"tooltip": "One person; one image or a batch of up to three distinct views."}),
                "resolution": ("INT", {"default": 768, "min": 128, "max": 1536, "step": 32}),
                "context": ("FLOAT", {"default": 1.25, "min": 1.0, "max": 3.0, "step": 0.05}),
                "background_strength": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "Suppress background only when the corresponding source headmask is supplied."})},
                "optional": {"headmask": ("MASK",), "view_2": ("IMAGE",), "headmask_2": ("MASK",),
                             "view_3": ("IMAGE",), "headmask_3": ("MASK",)}}

    def prepare(self, person, resolution, context, background_strength, headmask=None,
                view_2=None, headmask_2=None, view_3=None, headmask_3=None):
        images, masks = [], []
        for value, mask in [(person, headmask), (view_2, headmask_2), (view_3, headmask_3)]:
            if value is None:
                if mask is not None:
                    raise ValueError("A source mask is connected without its reference image")
                continue
            views = images_to_arrays(value)
            if mask is not None and len(views) != 1:
                raise ValueError("Connect masked views separately; a single mask cannot be reused across a batch")
            images.extend(views)
            masks.extend([mask_to_array(mask) if mask is not None else None] * len(views))
        references = prepare_references(images, masks, resolution=int(resolution), context=float(context),
                                        background_strength=float(background_strength))
        return result((references, array_to_image(reference_contact_sheet(references["images"]))), references["report"])


class DP_IdentityEncoder:
    CATEGORY = CATEGORY
    DESCRIPTION = "Encodes individual prepared identity views with the pretrained FLUX.2 VAE. This is working visual conditioning, not the future trained DreamFace encoder. No random identity weights."
    FUNCTION = "encode"
    RETURN_TYPES = ("DP_KLEIN_IDENTITY", "STRING")
    RETURN_NAMES = ("identity", "report")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"references": ("DP_REFERENCES",), "vae": ("VAE",)}}

    def encode(self, references, vae):
        identity = encode_identity(vae, references)
        return result((identity,), identity["report"])


class DP_SceneStudio:
    CATEGORY = CATEGORY
    DESCRIPTION = "Build an exact head crop, safe latent anchor and edge-adaptive blend mask. White is editable. 'original' retains pose AND target identity cues; 'neutral' removes both. Final write area never exceeds your mask."
    FUNCTION = "prepare"
    RETURN_TYPES = ("DP_SCENE", "IMAGE", "MASK", "IMAGE", "STRING")
    RETURN_NAMES = ("scene", "scene_reference", "generation_mask", "mask_overlay", "report")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"template": ("IMAGE",), "headmask": ("MASK", {"tooltip": "Aligned full-page mask, white=head+hair to replace. Use red channel for a grayscale mask file."}),
            "resolution": ("INT", {"default": 1024, "min": 128, "max": 2048, "step": 32}),
            "context": ("FLOAT", {"default": 1.5, "min": 1.0, "max": 4.0, "step": 0.05}),
            "expand": ("INT", {"default": 0, "min": 0, "max": 128, "tooltip": "Extra generation context in page pixels; never enlarges final write permission."}),
            "feather": ("FLOAT", {"default": 8.0, "min": 0.0, "max": 128.0, "step": 0.5, "tooltip": "Inward feather in original page pixels."}),
            "edge_protection": ("FLOAT", {"default": 0.65, "min": 0.0, "max": 1.0, "step": 0.05, "tooltip": "Reduces inward feather near strong edges. Heuristic; inspect hair boundaries."}),
            "scene_mode": (["original", "blur", "neutral"], {"default": "original", "tooltip": "Original preserves pose/expression but may leak target identity. Neutral suppresses the entire target head. Blur is an intermediate ablation."})}}

    def prepare(self, template, headmask, resolution, context, expand, feather, edge_protection, scene_mode):
        scene = prepare_native_scene(image_to_array(template), mask_to_array(headmask),
                    resolution=int(resolution), context=float(context), expand=int(expand),
                    feather=float(feather), edge_protection=float(edge_protection), scene_mode=scene_mode)
        overlay = scene["template"].copy()
        alpha = scene["crop"].masks.original[..., None] * 0.38
        overlay = overlay*(1-alpha) + np.array([0.1, 0.9, 0.7], np.float32)*alpha
        return result((scene, array_to_image(scene["scene_reference"]), array_to_mask(scene["crop"].mask),
                       array_to_image(overlay)), scene["report"])


class DP_SwapPrompt:
    CATEGORY = CATEGORY
    DESCRIPTION = "Build a concise headswap instruction with the correct scene/reference order. Extra instructions are optional. Identity views are never confused with the base scene."
    FUNCTION = "build"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("prompt", "report")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"identity": ("DP_KLEIN_IDENTITY",), "scene": ("DP_SCENE",),
                             "extra_instructions": ("STRING", {"default": "", "multiline": True})}}

    def build(self, identity, scene, extra_instructions):
        prompt = build_swap_prompt(len(identity["latents"]), scene["report"]["scene_mode"], extra_instructions)
        return result((prompt,), {"prompt": prompt})


class DP_KleinConditioning:
    CATEGORY = CATEGORY
    DESCRIPTION = "Encode scene and text, then route scene first and individual identity views afterward. The noise anchor has its original head removed before resizing/VAE. Uses Qwen3-8B + FLUX.2 VAE."
    FUNCTION = "condition"
    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT", "STRING")
    RETURN_NAMES = ("positive", "negative", "masked_latent", "report")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"clip": ("CLIP",), "vae": ("VAE",), "identity": ("DP_KLEIN_IDENTITY",),
                             "scene": ("DP_SCENE",), "prompt": ("STRING", {"forceInput": True})}}

    def condition(self, clip, vae, identity, scene, prompt):
        positive, negative, latent, report = condition_klein(clip, vae, identity, scene, prompt)
        return result((positive, negative, latent), report)


class DP_DreamSwap:
    CATEGORY = CATEGORY
    DESCRIPTION = "Generate with existing distilled Klein 9B. Native or installed LanPaint sampler, CFG 1, full denoise. Model input accepts a future compatible model-only LoRA. No training is started."
    FUNCTION = "sample"
    RETURN_TYPES = ("LATENT", "STRING")
    RETURN_NAMES = ("samples", "report")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": ("MODEL",), "positive": ("CONDITIONING",), "negative": ("CONDITIONING",),
            "masked_latent": ("LATENT",),
            "seed": ("INT", {"default": 19347, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True}),
            "steps": ("INT", {"default": 4, "min": 1, "max": 30, "tooltip": "4 steps is the initial distilled-model setting. More steps do not guarantee better identity."}),
            "engine": (["native", "lanpaint"], {"default": "native"}),
            "sampler": (["euler", "heun"], {"default": "euler"}),
            "scheduler": (["simple", "beta"], {"default": "simple"}),
            "lanpaint_steps": ("INT", {"default": 2, "min": 1, "max": 10, "tooltip": "Used only with the LanPaint engine."})}}

    def sample(self, model, positive, negative, masked_latent, seed, steps, engine, sampler, scheduler, lanpaint_steps):
        samples, report = sample_klein(model, positive, negative, masked_latent, seed=int(seed), steps=int(steps),
                    engine=engine, sampler=sampler, scheduler=scheduler, lanpaint_steps=int(lanpaint_steps))
        return result((samples,), report)


class DP_SeamFinish:
    CATEGORY = CATEGORY
    DESCRIPTION = "Bounded color correction from the unedited context ring, followed by edge-adaptive exact compositing. Color strength 0 is a full correction bypass. This is deterministic finishing, not a trained DreamRefine network."
    FUNCTION = "finish"
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("final_image", "report")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"generated_crop": ("IMAGE",), "scene": ("DP_SCENE",),
            "color_strength": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.05}),
            "max_shift": ("FLOAT", {"default": 0.04, "min": 0.0, "max": 0.1, "step": 0.005})}}

    def finish(self, generated_crop, scene, color_strength, max_shift):
        final, report = finish_native_crop(image_to_array(generated_crop), scene,
                                        color_strength=float(color_strength), max_shift=float(max_shift))
        return result((array_to_image(final),), report)


class DP_ReviewBoard:
    CATEGORY = CATEGORY
    DESCRIPTION = "Compare reference, original crop, finished crop, mask and protected-pixel difference. Pixel protection is measured exactly. Identity/photorealism need human review and are never assigned a fabricated score."
    FUNCTION = "review"
    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("review_board", "status", "report")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"final_image": ("IMAGE",), "scene": ("DP_SCENE",), "references": ("DP_REFERENCES",),
                             "tile_size": ("INT", {"default": 384, "min": 192, "max": 768, "step": 32})}}

    def review(self, final_image, scene, references, tile_size):
        final = image_to_array(final_image)
        metrics = preservation_metrics(scene["template"], final, scene["crop"].masks.original)
        diagnostics = review_diagnostics(scene["template"], final, scene["crop"].masks.original)
        status = "REVIEW" if metrics["outside_mask_exact"] else "FAIL"
        # Apply the stored transform, not a newly inferred crop box.
        transform = scene["crop"].transform
        x0, y0, x1, y1 = transform.box_xyxy
        l, t, r, b = transform.padding_ltrb
        output_crop = resize_array(np.pad(final[y0:y1, x0:x1], ((t,b),(l,r),(0,0)), mode="edge"), transform.model_hw)
        authority = scene["crop"].masks.original
        delta = np.clip(np.abs(final-scene["template"]) * (authority == 0)[...,None] * 20, 0, 1)
        panels = [("PERSON / VIEW 1", references["images"][0]), ("BEFORE / SCENE", scene["crop"].image),
                  ("AFTER / HEAD", output_crop), ("WRITE AUTHORITY", np.repeat(authority[...,None], 3, axis=-1)),
                  ("PROTECTED DIFFERENCE x20", delta)]
        width = int(tile_size)
        canvas = Image.new("RGB", (width * len(panels), width + 76), (17, 24, 30))
        draw = ImageDraw.Draw(canvas)
        for i, (label, pixels) in enumerate(panels):
            tile = reference_contact_sheet([pixels], tile_size=width)
            canvas.paste(Image.fromarray(np.rint(tile*255).astype(np.uint8)), (i*width, 32))
            draw.text((i*width+12, 10), label, fill=(132,221,203))
        draw.text((12, width+46), f"{status} | outside mask exact: {metrics['outside_mask_exact']} | identity and realism: human review", fill=(231,238,245))
        report = {**metrics, "status": status, "identity_score": None, "realism_score": None,
                  "diagnostics": diagnostics,
                  "note": "REVIEW means pixel checks passed; a person must judge identity and realism.",
                  "reference_views": len(references["images"])}
        return result((array_to_image(np.asarray(canvas)), status), report)


NODE_CLASS_MAPPINGS = {cls.__name__: cls for cls in [DP_LoadPhoto, DP_ReferenceStudio, DP_IdentityEncoder, DP_SceneStudio,
    DP_SwapPrompt, DP_KleinConditioning, DP_DreamSwap, DP_SeamFinish, DP_ReviewBoard]}
NODE_DISPLAY_NAME_MAPPINGS = {
    "DP_LoadPhoto": "DP Load Photo · Exact RGB",
    "DP_ReferenceStudio": "DP Reference Studio", "DP_IdentityEncoder": "DP Identity Encoder · Klein",
    "DP_SceneStudio": "DP Scene & Mask Studio", "DP_SwapPrompt": "DP Swap Direction",
    "DP_KleinConditioning": "DP Klein Conditioning", "DP_DreamSwap": "DP DreamSwap · Klein 9B",
    "DP_SeamFinish": "DP Seam Finish", "DP_ReviewBoard": "DP Review Board"}

"""Native node contracts with fake inference providers, never real model training.

These checks prove wiring, geometry, validation and compositing only. They provide
no evidence of pretrained headswap quality, model speed, or real GPU execution.
"""
from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import torch
from PIL import Image, ImageOps

from comfyui_dreampage_headswap import native_nodes as studio
from comfyui_dreampage_headswap.conversion import array_to_image, array_to_mask, image_to_array
from dreampage_headswap.inference.native_image_ops import prepare_native_scene
from dreampage_headswap.inference.native_klein import (
    build_swap_prompt, condition_klein, encode_identity, sample_klein,
)
from dreampage_headswap.inference.native_references import prepare_references


def reference(height=240, width=120, value=0.3):
    image = np.full((height, width, 3), value, np.float32)
    image[..., 1] += np.linspace(0, 0.1, height, dtype=np.float32)[:, None]
    return image


def scene():
    rng = np.random.default_rng(281)
    image = rng.random((128, 192, 3), dtype=np.float32)
    mask = np.zeros((128, 192), np.float32)
    mask[30:95, 60:122] = 1
    mask[44:47, 73:76] = 0
    return prepare_native_scene(image, mask, resolution=128, context=1.7)


class FakeVAE:
    latent_channels = 128

    def __init__(self, stride=16, bad_geometry=False):
        self.stride = stride
        self.bad_geometry = bad_geometry
        self.encoded = []

    def spacial_compression_encode(self):
        return self.stride

    def encode(self, image):
        if torch.is_grad_enabled():
            raise AssertionError("VAE operation did not run under inference mode")
        self.encoded.append(image.clone())
        channels = 64 if self.bad_geometry else self.latent_channels
        return torch.full((1, channels, image.shape[1] // 16, image.shape[2] // 16),
                          float(image.mean()), dtype=torch.float32)


class FakeClip:
    def __init__(self, widths=(12288,)):
        self.conditioning = [[torch.ones((1, 3, width)),
                              {"pooled_output": torch.ones((1, 4)), "existing": index,
                               "reference_latents": ["old-reference"]}]
                             for index, width in enumerate(widths)]
        self.prompt = None

    def tokenize(self, prompt):
        self.prompt = prompt
        return {"prompt": prompt}

    def encode_from_tokens_scheduled(self, tokens):
        if torch.is_grad_enabled():
            raise AssertionError("CLIP operation did not run under inference mode")
        return self.conditioning


class FakeModel:
    def __init__(self, **config):
        values = {"image_model": "flux2", "context_in_dim": 12288, "guidance_embed": False}
        values.update(config)
        self.model = types.SimpleNamespace(model_config=types.SimpleNamespace(unet_config=values))
        self.model_options = {"existing": True}
        self.clones = []

    def clone(self):
        result = FakeModel(**self.model.model_config.unet_config)
        result.model_options = self.model_options.copy()
        self.clones.append(result)
        return result


def helpers_module():
    module = types.ModuleType("node_helpers")

    def conditioning_set_values(conditioning, values):
        return [[tensor, {**metadata, **values}] for tensor, metadata in conditioning]

    module.conditioning_set_values = conditioning_set_values
    return module


def samplers_module(calls, *, lanpaint=False):
    module = types.ModuleType("nodes")

    def execute(*args, **kwargs):
        if torch.is_grad_enabled():
            raise AssertionError("Sampler did not run under inference mode")
        calls.append((args, kwargs))
        args[0].model_options["sampler_touched_clone"] = True
        latent = args[8]
        return ({**latent, "samples": latent["samples"] + 0.03},)

    module.common_ksampler = execute

    class FakeLanPaint:
        def sample(self, *args, **kwargs):
            return execute(*args, **kwargs)

    module.NODE_CLASS_MAPPINGS = {"LanPaint_KSampler": FakeLanPaint} if lanpaint else {}
    return module


def folder_paths_module(directory):
    module = types.ModuleType("folder_paths")
    directory = Path(directory)
    module.get_input_directory = lambda: str(directory)
    module.get_annotated_filepath = lambda name: str(directory / name)
    module.exists_annotated_filepath = lambda name: (directory / name).is_file()
    return module


def conditioning_case(reference_count=2):
    images = [reference(value=0.2 + index * 0.2, height=240 if index % 2 == 0 else 120,
                        width=120 if index % 2 == 0 else 240) for index in range(reference_count)]
    refs = prepare_references(images, resolution=128)
    vae = FakeVAE()
    identity = encode_identity(vae, refs)
    return vae, identity, scene(), FakeClip()


class ReferenceContracts(unittest.TestCase):
    def test_three_views_keep_independent_aspect_and_order(self):
        images = [reference(240, 120, 0.2), reference(120, 240, 0.4), reference(180, 180, 0.6)]
        prepared = prepare_references(images, resolution=128)
        self.assertEqual([image.shape[:2] for image in prepared["images"]], [(128, 64), (64, 128), (128, 128)])
        for original, output in zip(images, prepared["images"]):
            self.assertAlmostEqual(float(original[..., 0].mean()), float(output[..., 0].mean()), places=5)
        self.assertFalse(prepared["report"]["identity_consistency_verified"])

    def test_mask_crop_uses_own_reference_geometry_and_preserves_inputs(self):
        original = reference(128, 160)
        retained = original.copy()
        mask = np.zeros((128, 160), np.float32)
        mask[32:96, 64:96] = 1
        prepared = prepare_references([original], [mask], resolution=128, context=1,
                                      background_strength=1)
        self.assertEqual(prepared["images"][0].shape, (128, 64, 3))
        self.assertEqual(prepared["report"]["views"][0]["crop_xyxy"], (64, 32, 96, 96))
        np.testing.assert_array_equal(original, retained)
        self.assertAlmostEqual(float(prepared["images"][0][..., 0].mean()), 0.3, places=5)

    def test_duplicate_empty_and_excess_views_are_refused(self):
        photo = reference()
        for images in ([], [photo, photo.copy()], [reference(value=0.1 * i) for i in range(4)]):
            with self.subTest(count=len(images)), self.assertRaises(ValueError):
                prepare_references(images, resolution=128)

    def test_mask_count_size_range_and_empty_mask_are_refused(self):
        photo = reference()
        for masks in ([], [np.ones((3, 3), np.float32)],
                      [np.zeros(photo.shape[:2], np.float32)],
                      [np.full(photo.shape[:2], 2, np.float32)]):
            with self.subTest(masks=len(masks)), self.assertRaises(ValueError):
                prepare_references([photo], masks, resolution=128)

    def test_reference_controls_are_checked(self):
        for options in ({"resolution": 129}, {"resolution": 64}, {"context": 0.5},
                        {"context": float("nan")}, {"background_strength": 2}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                prepare_references([reference()], **options)

    def test_node_rejects_orphan_masks_and_reusing_one_mask_for_a_batch(self):
        node = studio.DP_ReferenceStudio()
        photo = array_to_image(reference())
        mask = array_to_mask(np.ones((240, 120), np.float32))
        with self.assertRaisesRegex(ValueError, "without its reference image"):
            node.prepare(photo, 128, 1.25, 0, headmask_2=mask)
        with self.assertRaisesRegex(ValueError, "masked views separately"):
            node.prepare(torch.cat([photo, photo + 0.1]), 128, 1.25, 0, headmask=mask)


class NativeConditioningContracts(unittest.TestCase):
    def setUp(self):
        self.module_patch = mock.patch.dict(sys.modules, {"node_helpers": helpers_module()})
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)

    def test_vae_encodes_all_reference_views_separately(self):
        vae, identity, _, _ = conditioning_case(3)
        self.assertEqual(len(vae.encoded), 3)
        self.assertEqual([tuple(x.shape) for x in identity["latents"]],
                         [(1, 128, 8, 4), (1, 128, 4, 8), (1, 128, 8, 4)])
        self.assertFalse(identity["report"]["dreamface_checkpoint_loaded"])
        self.assertFalse(identity["report"]["identity_quality_validated"])
        self.assertTrue(all(not latent.requires_grad for latent in identity["latents"]))

    def test_wrong_vae_type_stride_and_encoded_geometry_are_refused(self):
        references = prepare_references([reference()], resolution=128)
        wrong_channels = FakeVAE()
        wrong_channels.latent_channels = 16
        for vae in (wrong_channels, FakeVAE(stride=8), FakeVAE(bad_geometry=True)):
            with self.subTest(vae=vae), self.assertRaises(ValueError):
                encode_identity(vae, references)

    def test_mixed_vae_loaders_are_refused_before_encoding(self):
        vae, identity, prepared_scene, clip = conditioning_case()
        different = FakeVAE()
        with self.assertRaisesRegex(ValueError, "SAME VAE"):
            condition_klein(clip, different, identity, prepared_scene, "swap")
        self.assertEqual(len(different.encoded), 0)

    def test_conditioning_orders_scene_then_each_view_and_uses_safe_anchor(self):
        vae, identity, prepared_scene, clip = conditioning_case(3)
        positive, negative, latent, report = condition_klein(clip, vae, identity, prepared_scene, "swap")
        ordered = positive[0][1]["reference_latents"]
        self.assertEqual(len(ordered), 4)
        for actual, expected in zip(ordered[1:], identity["latents"]):
            self.assertIs(actual, expected)
        np.testing.assert_array_equal(vae.encoded[-2][0].numpy(), prepared_scene["scene_reference"])
        np.testing.assert_array_equal(vae.encoded[-1][0].numpy(), prepared_scene["safe_anchor"])
        np.testing.assert_array_equal(latent["noise_mask"][0].numpy(), prepared_scene["crop"].mask)
        self.assertEqual(tuple(latent["samples"].shape), (1, 128, 8, 8))
        self.assertEqual(report["reference_order"], ["scene", "person_view_1", "person_view_2", "person_view_3"])
        self.assertIs(negative[0][1]["reference_latents"], ordered)

    def test_conditioning_does_not_mutate_clip_conditioning(self):
        vae, identity, prepared_scene, clip = conditioning_case()
        original_tensor = clip.conditioning[0][0].clone()
        original_metadata = clip.conditioning[0][1].copy()
        positive, negative, _, _ = condition_klein(clip, vae, identity, prepared_scene, "swap")
        torch.testing.assert_close(clip.conditioning[0][0], original_tensor)
        self.assertEqual(clip.conditioning[0][1]["reference_latents"], ["old-reference"])
        self.assertEqual(clip.conditioning[0][1]["existing"], original_metadata["existing"])
        self.assertIsNot(positive[0][1], clip.conditioning[0][1])
        self.assertIsNot(negative[0][1], clip.conditioning[0][1])
        self.assertEqual(int(torch.count_nonzero(negative[0][0])), 0)

    def test_every_text_segment_requires_klein_9b_feature_width(self):
        vae, identity, prepared_scene, _ = conditioning_case()
        for widths in ((), (7680,), (12288, 7680)):
            with self.subTest(widths=widths), self.assertRaisesRegex(ValueError, "12288"):
                condition_klein(FakeClip(widths), vae, identity, prepared_scene, "swap")

    def test_prompt_matches_reference_count_and_discloses_scene_instruction(self):
        one = build_swap_prompt(1, "original", "Keep the light warm.")
        three = build_swap_prompt(3, "neutral")
        self.assertIn("person from image 2", one)
        self.assertIn("rotation, tilt, gaze and expression", one)
        self.assertIn("person from images 2, 3, 4", three)
        self.assertNotIn("rotation, tilt, gaze and expression", three)
        self.assertTrue(one.endswith("Keep the light warm."))
        with self.assertRaises(ValueError):
            build_swap_prompt(4, "original")


class NativeSamplerContracts(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.module_patch = mock.patch.dict(sys.modules, {"nodes": samplers_module(self.calls)})
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        self.latent = {"samples": torch.zeros((1, 128, 8, 8)), "noise_mask": torch.ones((1, 128, 128))}

    def test_sampler_clones_model_fixes_cfg_and_keeps_original_inputs(self):
        model = FakeModel()
        sampled, report = sample_klein(model, [], [], self.latent, seed=44)
        self.assertEqual(len(self.calls), 1)
        args, kwargs = self.calls[0]
        self.assertIs(args[0], model.clones[0])
        self.assertIsNot(args[0], model)
        self.assertNotIn("sampler_touched_clone", model.model_options)
        self.assertEqual(args[3], 1.0)
        self.assertEqual(kwargs["denoise"], 1.0)
        self.assertEqual(int(torch.count_nonzero(self.latent["samples"])), 0)
        self.assertFalse(torch.equal(sampled["samples"], self.latent["samples"]))
        self.assertFalse(report["adapter_provenance_verified"])
        self.assertFalse(report["distillation_verified"])

    def test_wrong_model_architecture_refused_without_sampling(self):
        for config in ({"image_model": "flux"}, {"context_in_dim": 7680}, {"guidance_embed": True}):
            with self.subTest(config=config), self.assertRaisesRegex(ValueError, "distilled"):
                sample_klein(FakeModel(**config), [], [], self.latent)
        self.assertEqual(self.calls, [])

    def test_unmasked_and_wrong_channel_latents_are_refused(self):
        for latent in ({"samples": self.latent["samples"]},
                       {"samples": torch.zeros((1, 16, 8, 8)), "noise_mask": self.latent["noise_mask"]}):
            with self.subTest(channels=latent["samples"].shape[1]), self.assertRaises(ValueError):
                sample_klein(FakeModel(), [], [], latent)
        self.assertEqual(self.calls, [])

    def test_empty_and_subcell_masks_are_refused_before_model_clone(self):
        empty = torch.zeros((1, 128, 128))
        tiny = empty.clone()
        tiny[0, 0, 0] = 1
        for mask in (empty, tiny):
            for engine in ("native", "lanpaint"):
                model = FakeModel()
                with self.subTest(engine=engine, pixels=int(mask.sum())), self.assertRaisesRegex(ValueError, "disappears"):
                    sample_klein(model, [], [], {**self.latent, "noise_mask": mask}, engine=engine)
                self.assertEqual(model.clones, [])
        self.assertEqual(self.calls, [])

    def test_lanpaint_refuses_soft_mask_that_has_no_effective_cells(self):
        soft = {**self.latent, "noise_mask": torch.full((1, 128, 128), 0.25)}
        with self.assertRaisesRegex(ValueError, "disappears"):
            sample_klein(FakeModel(), [], [], soft, engine="lanpaint")
        self.assertEqual(self.calls, [])
        _, report = sample_klein(FakeModel(), [], [], soft, engine="native")
        self.assertEqual(report["editable_latent_cells"], 64)

    def test_nonfinite_or_invalid_mask_shape_and_latent_are_refused(self):
        masks = [torch.full((1, 128, 128), float("nan")),
                 torch.full((1, 128, 128), -0.1), torch.full((1, 128, 128), 1.1),
                 torch.ones((2, 128, 128)), torch.ones((1, 2, 128, 128))]
        for mask in masks:
            with self.subTest(shape=tuple(mask.shape)), self.assertRaises(ValueError):
                sample_klein(FakeModel(), [], [], {**self.latent, "noise_mask": mask})
        with self.assertRaisesRegex(ValueError, "non-finite"):
            sample_klein(FakeModel(), [], [], {**self.latent, "samples": torch.full_like(self.latent["samples"], float("nan"))})
        self.assertEqual(self.calls, [])

    def test_invalid_sampler_settings_are_refused_without_sampling(self):
        for options in ({"seed": -1}, {"seed": 2**64}, {"seed": 1.5}, {"steps": 0},
                        {"steps": 2.5}, {"sampler": "unregistered"}, {"scheduler": "unregistered"},
                        {"lanpaint_steps": 0}, {"engine": "unknown"}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                sample_klein(FakeModel(), [], [], self.latent, **options)
        self.assertEqual(self.calls, [])

    def test_lanpaint_is_explicit_and_missing_extension_does_not_fallback(self):
        with self.assertRaisesRegex(RuntimeError, "LanPaint is not installed"):
            sample_klein(FakeModel(), [], [], self.latent, engine="lanpaint")
        self.assertEqual(self.calls, [])
        with mock.patch.dict(sys.modules, {"nodes": samplers_module(self.calls, lanpaint=True)}):
            _, report = sample_klein(FakeModel(), [], [], self.latent, engine="lanpaint", lanpaint_steps=3)
        _, kwargs = self.calls[0]
        self.assertEqual(kwargs["LanPaint_NumSteps"], 3)
        self.assertEqual(kwargs["LanPaint_PromptMode"], "Image First")
        self.assertEqual(report["engine"], "lanpaint")


class NativeNodeChainContracts(unittest.TestCase):
    def test_scene_mask_output_cannot_mutate_the_bound_scene(self):
        prepared = scene()
        output = studio.DP_SceneStudio().prepare(
            array_to_image(prepared["template"]), array_to_mask(prepared["crop"].masks.original),
            128, 1.7, 2, 8, 0.65, "original")
        retained_scene, _, mask_output, _, _ = output["result"]
        original_mask = retained_scene["crop"].mask.copy()
        mask_output.zero_()
        np.testing.assert_array_equal(retained_scene["crop"].mask, original_mask)

    def test_all_nine_nodes_have_complete_ui_contracts(self):
        self.assertEqual(len(studio.NODE_CLASS_MAPPINGS), 9)
        self.assertEqual(set(studio.NODE_CLASS_MAPPINGS), set(studio.NODE_DISPLAY_NAME_MAPPINGS))
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(sys.modules, {"folder_paths": folder_paths_module(directory)}):
                for name, node in studio.NODE_CLASS_MAPPINGS.items():
                    with self.subTest(node=name):
                        inputs = node.INPUT_TYPES()
                        self.assertIn("required", inputs)
                        self.assertEqual(len(node.RETURN_TYPES), len(node.RETURN_NAMES))
                        self.assertTrue(callable(getattr(node, node.FUNCTION)))
                        self.assertTrue(node.DESCRIPTION)
                        self.assertEqual(node.CATEGORY, "DreamPage/Studio")
                        for section in ("required", "optional"):
                            for value in inputs.get(section, {}).values():
                                self.assertIsInstance(value, tuple)

    def test_complete_fake_cpu_node_chain_and_review_have_exact_preservation(self):
        calls = []
        modules = {"node_helpers": helpers_module(), "nodes": samplers_module(calls)}
        with mock.patch.dict(sys.modules, modules):
            reference_result = studio.DP_ReferenceStudio().prepare(
                array_to_image(reference()), 128, 1.25, 0,
                view_2=array_to_image(reference(120, 240, 0.5)))
            references, preview, _ = reference_result["result"]
            self.assertEqual(tuple(preview.shape), (1, 256, 512, 3))
            vae = FakeVAE()
            identity_result = studio.DP_IdentityEncoder().encode(references, vae)
            identity = identity_result["result"][0]
            base_scene = scene()
            original = base_scene["template"]
            mask = base_scene["crop"].masks.original
            scene_result = studio.DP_SceneStudio().prepare(
                array_to_image(original), array_to_mask(mask), 128, 1.7, 2, 8, 0.65, "original")
            prepared_scene = scene_result["result"][0]
            prompt_result = studio.DP_SwapPrompt().build(identity, prepared_scene, "")
            condition_result = studio.DP_KleinConditioning().condition(
                FakeClip(), vae, identity, prepared_scene, prompt_result["result"][0])
            positive, negative, latent, _ = condition_result["result"]
            sample_result = studio.DP_DreamSwap().sample(
                FakeModel(), positive, negative, latent, 42, 4, "native", "euler", "simple", 2)
            self.assertEqual(tuple(sample_result["result"][0]["samples"].shape), (1, 128, 8, 8))
            # Deliberately destructive fake decoded crop exercises final protection.
            generated = array_to_image(np.zeros((128, 128, 3), np.float32))
            finish_result = studio.DP_SeamFinish().finish(generated, prepared_scene, 0, 0.04)
            final = finish_result["result"][0]
            np.testing.assert_array_equal(image_to_array(final)[mask == 0], original[mask == 0])
            review_result = studio.DP_ReviewBoard().review(final, prepared_scene, references, 192)
            board, status, report_text = review_result["result"]
            self.assertEqual(tuple(board.shape), (1, 268, 960, 3))
            self.assertEqual(status, "REVIEW")
            report = json.loads(report_text)
            self.assertTrue(report["outside_mask_exact"])
            self.assertIsNone(report["identity_score"])
            self.assertIsNone(report["realism_score"])
            self.assertEqual(report["reference_views"], 2)
            for output in (reference_result, identity_result, scene_result, prompt_result,
                           condition_result, sample_result, finish_result, review_result):
                self.assertEqual(output["ui"]["dp_report"], [output["result"][-1]])
                json.loads(output["result"][-1])

    def test_review_board_fails_actual_protected_pixel_changes(self):
        prepared_scene = scene()
        changed = prepared_scene["template"].copy()
        changed[0, 0] = 1 - changed[0, 0]
        references = prepare_references([reference()], resolution=128)
        result = studio.DP_ReviewBoard().review(array_to_image(changed), prepared_scene, references, 192)
        self.assertEqual(result["result"][1], "FAIL")
        self.assertFalse(json.loads(result["result"][2])["outside_mask_exact"])


class PhotoLoaderContracts(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        patch = mock.patch.dict(sys.modules, {"folder_paths": folder_paths_module(self.directory)})
        patch.start()
        self.addCleanup(patch.stop)
        self.node = studio.DP_LoadPhoto()

    def test_jpeg_exif_orientation_and_cpu_float32_are_explicit(self):
        pixels = np.zeros((32, 64, 3), np.uint8)
        pixels[:, :32, 0] = 250
        pixels[:, 32:, 2] = 250
        exif = Image.Exif()
        exif[274] = 6
        path = self.directory / "oriented.jpg"
        Image.fromarray(pixels).save(path, exif=exif)
        loaded, mask, report_text = self.node.load(path.name)["result"]
        with Image.open(path) as file:
            expected = np.asarray(ImageOps.exif_transpose(file).convert("RGB"))
        self.assertEqual(tuple(loaded.shape), (1, 64, 32, 3))
        self.assertEqual(loaded.device.type, "cpu")
        self.assertEqual(loaded.dtype, torch.float32)
        np.testing.assert_array_equal((loaded[0].numpy() * 255).astype(np.uint8), expected)
        np.testing.assert_array_equal(mask[0].numpy(), expected[..., 0].astype(np.float32) / 255)
        report = json.loads(report_text)
        self.assertFalse(report["training_enrollment"])
        self.assertFalse(report["alpha_inverted"])

    def test_png_rgb_and_gray_mask_channels_retain_exact_values(self):
        gray = np.arange(256, dtype=np.uint8).reshape(16, 16)
        path = self.directory / "gray.png"
        Image.fromarray(gray).save(path)
        for channel in ("red", "green", "blue"):
            with self.subTest(channel=channel):
                image, mask, _ = self.node.load(path.name, channel)["result"]
                np.testing.assert_array_equal((image[0].numpy() * 255).astype(np.uint8), np.repeat(gray[..., None], 3, -1))
                np.testing.assert_array_equal(mask[0].numpy(), gray.astype(np.float32) / 255)

    def test_rgba_alpha_is_not_inverted_and_rgb_keeps_original_channels(self):
        pixels = np.zeros((16, 16, 4), np.uint8)
        pixels[..., 0] = 64
        pixels[..., 1] = 128
        pixels[..., 2] = 192
        pixels[..., 3] = np.arange(256, dtype=np.uint8).reshape(16, 16)
        path = self.directory / "alpha.png"
        Image.fromarray(pixels, "RGBA").save(path)
        image, mask, report_text = self.node.load(path.name, "alpha")["result"]
        np.testing.assert_array_equal((image[0].numpy() * 255).astype(np.uint8), pixels[..., :3])
        np.testing.assert_array_equal(mask[0].numpy(), pixels[..., 3].astype(np.float32) / 255)
        self.assertFalse(json.loads(report_text)["alpha_inverted"])

    def test_nonalpha_unknown_channel_high_bit_depth_and_animation_are_refused(self):
        rgb_path = self.directory / "rgb.png"
        Image.fromarray(np.zeros((16, 16, 3), np.uint8)).save(rgb_path)
        with self.assertRaisesRegex(ValueError, "no alpha channel"):
            self.node.load(rgb_path.name, "alpha")
        with self.assertRaisesRegex(ValueError, "Unknown mask channel"):
            self.node.load(rgb_path.name, "luminance")
        high_path = self.directory / "high.png"
        Image.fromarray(np.full((16, 16), 65535, np.uint16)).save(high_path)
        with self.assertRaisesRegex(ValueError, "high-bit-depth"):
            self.node.load(high_path.name)
        animation_path = self.directory / "animation.gif"
        first = Image.new("RGB", (16, 16), "red")
        first.save(animation_path, save_all=True, append_images=[Image.new("RGB", (16, 16), "blue")], duration=100, loop=0)
        with self.assertRaisesRegex(ValueError, "still photo"):
            self.node.load(animation_path.name)

    def test_supported_photo_listing_validation_and_content_hash(self):
        first = self.directory / "first.jpg"
        second = self.directory / "second.png"
        Image.new("RGB", (8, 8), "red").save(first)
        Image.new("RGB", (8, 8), "blue").save(second)
        (self.directory / "note.txt").write_text("not an image", encoding="utf-8")
        inputs = self.node.INPUT_TYPES()["required"]["image"][0]
        self.assertEqual(inputs, ["first.jpg", "second.png"])
        self.assertIs(self.node.VALIDATE_INPUTS(first.name), True)
        self.assertIsInstance(self.node.VALIDATE_INPUTS("missing.png"), str)
        initial = self.node.IS_CHANGED(second.name)
        self.assertEqual(initial, self.node.IS_CHANGED(second.name))
        Image.new("RGB", (8, 8), "green").save(second)
        self.assertNotEqual(initial, self.node.IS_CHANGED(second.name))

    def test_mpo_selects_explicit_frame_without_batch_reduction(self):
        path = self.directory / "mobile.jpg"
        Image.new("RGB", (16, 16), "red").save(
            path, format="MPO", save_all=True,
            append_images=[Image.new("RGB", (16, 16), "blue")])
        for index in (0, 1):
            loaded, _, report = self.node.load(path.name, mpo_frame=index)["result"]
            with Image.open(path) as source:
                source.seek(index)
                expected = np.asarray(source.convert("RGB"))
            np.testing.assert_array_equal((loaded[0].numpy() * 255).astype(np.uint8), expected)
            self.assertEqual(json.loads(report)["selected_frame"], index)
            self.assertEqual(json.loads(report)["embedded_frames"], 2)
        with self.assertRaisesRegex(ValueError, "frame does not exist"):
            self.node.load(path.name, mpo_frame=2)

    def test_jpeg_and_png_full_scene_finish_standard_saveimage_preserves_exterior(self):
        rng = np.random.default_rng(1119)
        pixels = rng.integers(0, 256, (128, 192, 3), dtype=np.uint8)
        authority = np.zeros((128, 192), np.float32)
        authority[32:96, 64:128] = 1
        authority[42:46, 74:79] = 0
        for extension in ("jpg", "png"):
            with self.subTest(extension=extension):
                source = self.directory / f"source.{extension}"
                Image.fromarray(pixels).save(source)
                loaded = self.node.load(source.name)["result"][0]
                scene_result = studio.DP_SceneStudio().prepare(
                    loaded, array_to_mask(authority), 128, 1.7, 4, 8, 0.65, "original")
                prepared = scene_result["result"][0]
                generated = array_to_image(np.zeros((128, 128, 3), np.float32))
                finished = studio.DP_SeamFinish().finish(generated, prepared, 0, 0.04)["result"][0]
                # Standard ComfyUI SaveImage conversion deliberately truncates.
                saved_pixels = np.clip(255 * finished[0].cpu().numpy(), 0, 255).astype(np.uint8)
                destination = self.directory / f"finished_{extension}.png"
                Image.fromarray(saved_pixels).save(destination)
                with Image.open(source) as file:
                    original_rgb = np.asarray(ImageOps.exif_transpose(file).convert("RGB"))
                with Image.open(destination) as file:
                    final_rgb = np.asarray(file)
                np.testing.assert_array_equal(final_rgb[authority == 0], original_rgb[authority == 0])


if __name__ == "__main__":
    unittest.main()

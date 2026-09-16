"""End-to-end inference and the ComfyUI integration layer.

The pipeline runs on random tiny weights here. What is being asserted is the contract: the
template outside the supplied mask comes back byte-identical, the quality gate refuses to pass
an unvalidated model, and each node is a faithful adapter over the same library calls.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import numpy as np
import torch

from _fixtures import REPOSITORY, reference_image, template_and_mask, write_image, write_mask
from comfyui_dreampage_headswap import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from comfyui_dreampage_headswap import nodes as dp_nodes
from comfyui_dreampage_headswap.conversion import (array_to_image, array_to_mask, image_to_array,
                                                   images_to_arrays, mask_to_array)
from dreampage_headswap.inference.pipeline import HeadSwapPipeline, InferenceConfig, load_pipeline, save_debug
from dreampage_headswap.template import CropConfig
from dreampage_headswap.training import build_model
from dreampage_headswap.types import ChildIdentityInput, HeadMask, TemplateInput
from dreampage_headswap.utils.checkpoint import seed_everything

TINY_CONFIG = REPOSITORY / "configs" / "inference" / "tiny_smoke.yaml"


def tiny_pipeline(**overrides) -> HeadSwapPipeline:
    seed_everything(7)
    model = build_model({"model": {"backbone": "tiny", "identity_dim": 32, "structure_dim": 16, "width": 24}})
    config = InferenceConfig(crop=CropConfig(resolution=32, context=1.5), steps=3, seed=5,
                             reference_resolution=32, **overrides)
    return HeadSwapPipeline(model, config=config)


def run_pipeline(pipeline=None, *, references=1, config=None, **kwargs):
    pipeline = pipeline or tiny_pipeline()
    template, mask = template_and_mask()
    child = ChildIdentityInput([reference_image(index + 1) for index in range(references)])
    output = pipeline(child, TemplateInput(template), HeadMask(mask), config=config, **kwargs)
    return template, mask, output


class PipelineTests(unittest.TestCase):
    def test_template_outside_the_mask_is_returned_unchanged(self):
        template, mask, output = run_pipeline()
        self.assertEqual(output.image.shape, template.shape)
        outside = mask == 0
        self.assertTrue(np.array_equal(output.image[outside], template[outside]))
        self.assertTrue(output.quality.measurements["outside_mask_exact"])
        self.assertEqual(output.quality.measurements["outside_mask_changed_percentage"], 0.0)
        self.assertFalse(np.array_equal(output.image[mask > 0], template[mask > 0]))

    def test_an_unvalidated_model_can_never_report_pass(self):
        _, _, output = run_pipeline()
        self.assertNotEqual(output.quality.status, "PASS")
        self.assertIsNone(output.quality.overall_score)
        self.assertIsNone(output.quality.identity_score)
        self.assertTrue(any("held-out" in reason for reason in output.quality.reasons))
        self.assertTrue(any("Uncalibrated or unavailable" in reason for reason in output.quality.reasons))

    def test_multiple_references_are_accepted(self):
        _, _, output = run_pipeline(references=3)
        self.assertTrue(output.quality.measurements["outside_mask_exact"])

    def test_an_empty_mask_is_a_reported_no_op_rather_than_a_silent_pass(self):
        pipeline = tiny_pipeline()
        template, _ = template_and_mask()
        child = ChildIdentityInput([reference_image(1)])
        output = pipeline(child, TemplateInput(template), HeadMask(np.zeros(template.shape[:2], np.float32)))
        self.assertTrue(np.array_equal(output.image, template))
        self.assertEqual(output.quality.status, "FAIL")
        self.assertTrue(output.debug["no_op"])

    def test_seeds_are_reproducible_and_distinct(self):
        pipeline = tiny_pipeline()
        first = run_pipeline(pipeline, config=replace(pipeline.config, seed=3))[2]
        again = run_pipeline(pipeline, config=replace(pipeline.config, seed=3))[2]
        other = run_pipeline(pipeline, config=replace(pipeline.config, seed=4))[2]
        self.assertTrue(np.array_equal(first.image, again.image))
        self.assertFalse(np.array_equal(first.image, other.image))

    def test_refinement_requires_an_explicitly_loaded_refiner(self):
        pipeline = tiny_pipeline()
        with self.assertRaisesRegex(ValueError, "refine_strength"):
            run_pipeline(pipeline, config=replace(pipeline.config, refine_strength=0.5))

    def test_invalid_inference_settings_are_rejected_at_construction(self):
        for override in ({"steps": 0}, {"identity_strength": 9.0}, {"refine_strength": 2.0},
                         {"degradation": "make_something_up"}, {"reference_resolution": 4}):
            with self.assertRaises(ValueError):
                InferenceConfig(**override)

    def test_missing_references_and_impossible_ages_are_rejected(self):
        pipeline = tiny_pipeline()
        template, mask = template_and_mask()
        with self.assertRaises(ValueError):
            pipeline(ChildIdentityInput([]), TemplateInput(template), HeadMask(mask))
        with self.assertRaises(ValueError):
            pipeline(ChildIdentityInput([reference_image(1)], age=500),
                     TemplateInput(template), HeadMask(mask))

    def test_a_mask_of_the_wrong_size_is_rejected_rather_than_resized(self):
        pipeline = tiny_pipeline()
        template, _ = template_and_mask()
        with self.assertRaises(ValueError):
            pipeline(ChildIdentityInput([reference_image(1)]), TemplateInput(template),
                     HeadMask(np.ones((8, 8), np.float32)))

    def test_internal_face_mask_must_stay_inside_the_supplied_headmask(self):
        pipeline = tiny_pipeline()
        template, mask = template_and_mask()
        outside = np.zeros_like(mask)
        outside[0:4, 0:4] = 1.0
        with self.assertRaisesRegex(ValueError, "within the original headmask"):
            pipeline(ChildIdentityInput([reference_image(1)]), TemplateInput(template),
                     HeadMask(mask), internal_face_mask=outside)

    def test_mask_expansion_widens_context_without_widening_authority(self):
        pipeline = tiny_pipeline()
        from dreampage_headswap.masking import MaskConfig
        config = replace(pipeline.config, mask=MaskConfig(expand=3, feather=1.0))
        template, mask, output = run_pipeline(pipeline, config=config)
        outside = mask == 0
        self.assertTrue(np.array_equal(output.image[outside], template[outside]))

    def test_debug_mode_exposes_every_stage(self):
        pipeline = tiny_pipeline()
        template, mask, output = run_pipeline(pipeline, config=replace(pipeline.config, debug=True))
        for key in ("child_images", "template", "original_headmask", "generation_mask", "blend_mask",
                    "head_crop", "crop_mask", "identity_suppressed_template", "dreamswap_raw",
                    "dreamrefine_output", "final_composite", "outside_mask_difference"):
            self.assertIn(key, output.debug)
        self.assertEqual(float(np.abs(output.debug["outside_mask_difference"]).max()), 0.0)
        suppressed = output.debug["identity_suppressed_template"]
        head_crop = output.debug["head_crop"]
        crop_mask = output.debug["crop_mask"] > 0
        self.assertFalse(np.array_equal(suppressed[crop_mask], head_crop[crop_mask]))
        # Suppression happens at native resolution, so the crop's mask edge carries
        # interpolated values. The interior must still be one flat neutral colour.
        from scipy.ndimage import binary_erosion
        interior = binary_erosion(crop_mask, iterations=2)
        self.assertTrue(interior.any())
        self.assertEqual(len(np.unique(np.round(suppressed[interior], 5))), 3)

    def test_save_debug_writes_inspectable_artifacts(self):
        pipeline = tiny_pipeline()
        _, _, output = run_pipeline(pipeline, config=replace(pipeline.config, debug=True))
        with tempfile.TemporaryDirectory() as tmp:
            save_debug(output, tmp)
            written = {path.name for path in Path(tmp).iterdir()}
            self.assertIn("debug.json", written)
            self.assertIn("final_composite.png", written)
            self.assertIn("child_0.png", written)
            metadata = json.loads(Path(tmp, "debug.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["quality"]["status"], output.quality.status)
            self.assertIn("crop_transform", metadata)


class LoadPipelineTests(unittest.TestCase):
    def test_a_checkpoint_is_required_unless_smoke_testing_is_explicit(self):
        with self.assertRaisesRegex(ValueError, "trained DreamSwap checkpoint is required"):
            load_pipeline(TINY_CONFIG)
        pipeline = load_pipeline(TINY_CONFIG, allow_untrained=True)
        self.assertTrue(pipeline.checkpoint_metadata["untrained"])
        self.assertFalse(pipeline.model_validated)
        self.assertEqual(pipeline.config.crop.model_hw, (64, 64))

    def test_cuda_is_not_silently_downgraded_to_cpu(self):
        if torch.cuda.is_available():
            self.skipTest("CUDA is available on this machine, so the refusal path cannot be exercised")
        with self.assertRaisesRegex(RuntimeError, "CUDA requested but unavailable"):
            load_pipeline(TINY_CONFIG, allow_untrained=True, device="cuda")


class CommandLineTests(unittest.TestCase):
    def test_cli_writes_a_lossless_png_and_a_provenance_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template, mask = template_and_mask(size=(96, 72), box=(24, 14, 70, 56))
            from dreampage_headswap.utils.images import save_rgb
            save_rgb(root / "template.png", template)
            write_mask(root / "mask.png", (96, 72), (24, 14, 70, 56))
            write_image(root / "child.png", 31, (64, 64))
            output = root / "result.png"
            argv = ["dp-headswap", "--config", str(TINY_CONFIG), "--child", str(root / "child.png"),
                    "--template", str(root / "template.png"), "--mask", str(root / "mask.png"),
                    "--output", str(output), "--allow-untrained", "--debug-dir", str(root / "debug")]
            from dreampage_headswap.inference import cli
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
                cli.main()
            self.assertTrue(output.is_file())
            report = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertNotEqual(report["quality"]["status"], "PASS")
            self.assertIsNone(report["peak_vram_bytes"])
            self.assertIn("excludes model load", report["latency_scope"])
            self.assertTrue(report["checkpoint_metadata"]["untrained"])
            self.assertTrue((root / "debug" / "debug.json").is_file())

            from dreampage_headswap.utils.images import load_rgb
            result = load_rgb(output)
            source = np.rint(template * 255).astype(np.uint8)
            outside = mask == 0
            self.assertTrue(np.array_equal(result[outside], source[outside]))

    def test_output_must_be_a_lossless_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            from dreampage_headswap.utils.images import save_rgb
            with self.assertRaisesRegex(ValueError, "lossless"):
                save_rgb(Path(tmp) / "result.jpg", template_and_mask()[0])


class ConversionTests(unittest.TestCase):
    def test_image_round_trip_preserves_values(self):
        array = reference_image(2, 16)
        self.assertTrue(np.allclose(image_to_array(array_to_image(array)), array, atol=1e-6))

    def test_mask_round_trip_preserves_values(self):
        mask = template_and_mask()[1]
        self.assertTrue(np.array_equal(mask_to_array(array_to_mask(mask)), mask))

    def test_an_image_batch_is_not_silently_reduced(self):
        batch = torch.rand(3, 8, 8, 3)
        with self.assertRaisesRegex(ValueError, "batch this node"):
            image_to_array(batch)
        self.assertEqual(len(images_to_arrays(batch)), 3)

    def test_alpha_is_dropped_and_invalid_tensors_are_rejected(self):
        self.assertEqual(image_to_array(torch.rand(1, 8, 8, 4)).shape, (8, 8, 3))
        with self.assertRaises(ValueError):
            image_to_array(torch.full((1, 4, 4, 3), float("nan")))
        with self.assertRaises(ValueError):
            mask_to_array(torch.full((1, 4, 4), 2.0))
        with self.assertRaises(ValueError):
            mask_to_array(None)
        with self.assertRaises(ValueError):
            image_to_array(None)


DREAMPAGE_CATEGORIES = {"DreamPage/HeadSwap", "DreamPage/Studio"}


class NodeContractTests(unittest.TestCase):
    def test_every_node_declares_a_complete_comfyui_contract(self):
        self.assertEqual(sorted(NODE_CLASS_MAPPINGS), sorted(NODE_DISPLAY_NAME_MAPPINGS))
        for name, node in NODE_CLASS_MAPPINGS.items():
            with self.subTest(node=name):
                try:
                    types = node.INPUT_TYPES()
                except ModuleNotFoundError as exc:
                    # De ni native Studio-nodene slaar opp modellkataloger via
                    # ComfyUI sin egen `folder_paths`, som bare finnes inne i
                    # ComfyUI-prosessen. De KAN ikke introspiseres herfra.
                    # Registreringen deres verifiseres i stedet mot en kjoerende
                    # instans: tools/node_requirements.py --check --object-info.
                    self.skipTest(f"{name} krever ComfyUI-runtime ({exc.name})")
                    raise AssertionError("uansett ikke naadd")  # pragma: no cover
                self.assertIn("required", types)
                self.assertTrue(callable(getattr(node, node.FUNCTION)))
                self.assertEqual(len(node.RETURN_TYPES), len(node.RETURN_NAMES))
                # To bevisste nodefamilier: "DreamPage/HeadSwap" er den
                # trente modellen, "DreamPage/Studio" er de ni native
                # Klein-nodene som kom til senere. Kontrakten er at en
                # node ligger under et DreamPage-navnerom saa operatoeren
                # finner den - ikke at det finnes bare ett.
                self.assertIn(node.CATEGORY, DREAMPAGE_CATEGORIES)
                # ComfyUI viser DESCRIPTION, ikke __doc__. Kontrakten er at
                # operatoeren ser NOE - derfor godtas begge. Testen krevde
                # foer bare __doc__, altsaa nettopp det feltet ComfyUI ikke
                # leser, og lot de sju HeadSwap-nodene staa uten synlig
                # beskrivelse i grensesnittet.
                self.assertTrue(getattr(node, "DESCRIPTION", None) or node.__doc__,
                                f"{name} needs an operator-visible description")
                for section in ("required", "optional"):
                    for key, spec in types.get(section, {}).items():
                        self.assertIsInstance(spec, tuple, f"{name}.{key}")

    def test_mask_node_reports_authority_and_clamps_the_blend(self):
        mask = template_and_mask()[1]
        original, generation, blend, report = dp_nodes.DP_UseHeadMask().process(array_to_mask(mask), 4, 2.0)
        values = json.loads(report)
        self.assertTrue(values["blend_within_supplied_authority"])
        self.assertGreater(values["generation_fraction"], values["editable_fraction"])
        self.assertLessEqual(values["blend_fraction"], values["editable_fraction"])
        self.assertTrue(np.array_equal(mask_to_array(original), mask))
        self.assertTrue(np.all(mask_to_array(blend) <= mask_to_array(generation) + 1e-7))

    def test_crop_then_composite_preserves_protected_pixels_exactly(self):
        template, mask = template_and_mask()
        crop_node = dp_nodes.DP_PrepareTemplateCrop()
        bundle, crop_image, crop_mask, transform = crop_node.prepare(
            array_to_image(template), array_to_mask(mask), 32, 1.5, 0, 0.0)
        self.assertEqual(image_to_array(crop_image).shape, (32, 32, 3))
        self.assertEqual(json.loads(transform)["model_hw"], [32, 32])

        painted = image_to_array(crop_image).copy()
        painted[:] = 1.0  # a deliberately destructive "generated" crop
        result, report = dp_nodes.DP_CompositeToTemplate().composite(
            array_to_image(template), array_to_image(painted), bundle)
        final = image_to_array(result)
        outside = mask == 0
        self.assertTrue(np.array_equal(final[outside], template[outside]))
        self.assertTrue(json.loads(report)["outside_mask_exact"])
        self.assertTrue(np.allclose(final[mask > 0], 1.0))

    def test_composite_refuses_a_crop_of_the_wrong_resolution(self):
        template, mask = template_and_mask()
        bundle = dp_nodes.DP_PrepareTemplateCrop().prepare(
            array_to_image(template), array_to_mask(mask), 32, 1.5, 0, 0.0)[0]
        with self.assertRaisesRegex(ValueError, "expected"):
            dp_nodes.DP_CompositeToTemplate().composite(
                array_to_image(template), array_to_image(reference_image(1, 16)), bundle)

    def test_crop_node_refuses_an_empty_mask(self):
        template, _ = template_and_mask()
        with self.assertRaisesRegex(ValueError, "Empty headmask"):
            dp_nodes.DP_PrepareTemplateCrop().prepare(
                array_to_image(template), array_to_mask(np.zeros(template.shape[:2], np.float32)),
                32, 1.5, 0, 0.0)

    def test_quality_node_reports_failure_when_protected_pixels_moved(self):
        template, mask = template_and_mask()
        node = dp_nodes.DP_QualityCheck()
        untouched = template.copy()
        untouched[mask > 0] = 0.5
        report, status, preservation = node.check(array_to_image(template), array_to_image(untouched),
                                                  array_to_mask(mask), 0.8)
        self.assertEqual(preservation, 1.0)
        self.assertEqual(status, "RETRY")

        drifted = template.copy()
        drifted[0, 0] = 0.0
        report, status, preservation = node.check(array_to_image(template), array_to_image(drifted),
                                                  array_to_mask(mask), 0.8)
        self.assertEqual(status, "FAIL")
        self.assertEqual(preservation, 0.0)
        self.assertIn("Protected template pixels changed", json.loads(report)["reasons"])

    def test_loader_encoder_and_pipeline_nodes_run_together(self):
        pipeline, metadata = dp_nodes.DP_LoadHeadSwapModel().load(
            str(TINY_CONFIG), "cpu", checkpoint_path="", allow_untrained=True)
        self.assertTrue(json.loads(metadata)["untrained"])

        children = torch.stack([torch.from_numpy(reference_image(index, 32)) for index in (1, 2)])
        identity, summary = dp_nodes.DP_EncodeChildIdentity().encode(pipeline, children, 64)
        values = json.loads(summary)
        self.assertEqual(values["reference_count"], 2)
        self.assertEqual(tuple(identity["references"].shape)[:2], (1, 2))
        self.assertFalse(values["identity_quality_validated"])

        template, mask = template_and_mask(size=(96, 72), box=(24, 14, 70, 56))
        image, quality, debug, preservation = dp_nodes.DP_HeadSwapPipeline().run(
            pipeline, children, array_to_image(template), array_to_mask(mask),
            identity_strength=1.0, refine_strength=0.0, mask_expand=0, mask_feather=1.0,
            steps=2, seed=11, quality_threshold=0.8, crop_resolution=32, crop_context=1.5, age=6.0)
        final = image_to_array(image)
        outside = mask == 0
        self.assertEqual(preservation, 1.0)
        self.assertTrue(np.array_equal(final[outside], template[outside]))
        self.assertNotEqual(json.loads(quality)["status"], "PASS")
        self.assertEqual(json.loads(debug)["config"]["seed"], 11)
        self.assertIsNone(json.loads(debug)["debug_images_written_to"])

    def test_pipeline_node_writes_debug_artifacts_when_asked(self):
        pipeline = dp_nodes.DP_LoadHeadSwapModel().load(str(TINY_CONFIG), "cpu", allow_untrained=True)[0]
        template, mask = template_and_mask(size=(96, 72), box=(24, 14, 70, 56))
        children = torch.from_numpy(reference_image(4, 32))[None]
        with tempfile.TemporaryDirectory() as tmp:
            _, _, debug, _ = dp_nodes.DP_HeadSwapPipeline().run(
                pipeline, children, array_to_image(template), array_to_mask(mask),
                identity_strength=1.0, refine_strength=0.0, mask_expand=0, mask_feather=0.0,
                steps=2, seed=1, quality_threshold=0.8, crop_resolution=32, debug_dir=tmp)
            self.assertEqual(json.loads(debug)["debug_images_written_to"], tmp)
            self.assertTrue(Path(tmp, "final_composite.png").is_file())


if __name__ == "__main__":
    unittest.main()

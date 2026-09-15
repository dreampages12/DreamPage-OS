"""Pure image-operation contracts: no model loading, optimization, or training."""
from __future__ import annotations

import unittest

import numpy as np

from dreampage_headswap.inference.native_image_ops import (
    edge_adaptive_masks, finish_native_crop, prepare_native_scene, review_diagnostics,
)


def example():
    rng = np.random.default_rng(731)
    template = rng.random((128, 128, 3), dtype=np.float32)
    mask = np.zeros((128, 128), np.float32)
    mask[40:88, 40:88] = 1
    return template, mask


class NativeImageOpsTests(unittest.TestCase):
    def test_edge_adaptive_feather_never_expands_external_authority(self):
        template, mask = example()
        mask[50:56, 51:58] = 0
        mask[40:44, 40:88] = 0.3
        plain, _ = edge_adaptive_masks(template, mask, expand=6, edge_protection=0)
        adaptive, report = edge_adaptive_masks(template, mask, expand=6, edge_protection=0.9)
        self.assertTrue(np.isfinite(adaptive.blend).all())
        np.testing.assert_array_equal(adaptive.original, mask)
        np.testing.assert_array_equal(adaptive.generation, plain.generation)
        self.assertTrue(np.all(adaptive.blend <= mask))
        self.assertTrue(np.all(adaptive.blend[mask == 0] == 0))
        self.assertTrue(np.all(adaptive.blend >= plain.blend))
        self.assertTrue(np.any(adaptive.blend > plain.blend))
        self.assertTrue(report["blend_within_supplied_authority"])
        self.assertFalse(report["hair_segmentation_available"])

    def test_neutral_anchor_cannot_read_target_rgb_even_at_padded_edge(self):
        rng = np.random.default_rng(887)
        first = rng.random((73, 91, 3), dtype=np.float32)
        mask = np.zeros((73, 91), np.float32)
        mask[:26, :21] = 1
        second = first.copy()
        second[mask > 0] = 1 - first[mask > 0]
        a = prepare_native_scene(first, mask, resolution=64, context=2, expand=4, scene_mode="neutral")
        b = prepare_native_scene(second, mask, resolution=64, context=2, expand=4, scene_mode="neutral")
        self.assertGreater(sum(a["crop"].transform.padding_ltrb), 0)
        np.testing.assert_array_equal(a["safe_anchor"], b["safe_anchor"])
        np.testing.assert_array_equal(a["scene_reference"], b["scene_reference"])
        self.assertFalse(a["report"]["scene_reference_retains_target_identity"])
        self.assertFalse(a["report"]["pose_extracted"])

    def test_original_and_blur_modes_disclose_retained_target_identity(self):
        template, mask = example()
        for mode in ("original", "blur"):
            with self.subTest(mode=mode):
                scene = prepare_native_scene(template, mask, resolution=64, scene_mode=mode)
                self.assertTrue(scene["report"]["scene_reference_retains_target_identity"])
                if mode == "original":
                    np.testing.assert_array_equal(scene["scene_reference"], scene["crop"].image)
                self.assertFalse(np.array_equal(scene["safe_anchor"], scene["scene_reference"]))

    def test_preparation_binds_a_copy_and_finish_preserves_protected_pixels(self):
        template, mask = example()
        retained = template.copy()
        scene = prepare_native_scene(template, mask, resolution=64, expand=4)
        template[:] = 0
        mask[:] = 1
        generated = np.ones((64, 64, 3), np.float32)
        final, report = finish_native_crop(generated, scene)
        authority = scene["crop"].masks.original
        np.testing.assert_array_equal(scene["template"], retained)
        np.testing.assert_array_equal(final[authority == 0], retained[authority == 0])
        self.assertTrue(report["outside_mask_exact"])
        self.assertFalse(report["semantic_quality_validated"])
        self.assertIsNone(report["identity_score"])
        self.assertEqual(report["color_correction"]["method"], "disabled_by_operator")
        self.assertFalse(scene["template"].flags.writeable)

    def test_same_shape_wrong_template_is_rejected(self):
        template, mask = example()
        scene = prepare_native_scene(template, mask, resolution=64)
        scene["template"] = 1 - scene["template"]
        with self.assertRaisesRegex(ValueError, "changed after preparation"):
            finish_native_crop(np.zeros((64, 64, 3), np.float32), scene)

    def test_changed_blend_or_geometry_is_rejected(self):
        from dataclasses import replace
        template, mask = example()
        for part in ("blend", "transform"):
            with self.subTest(part=part):
                scene = prepare_native_scene(template, mask, resolution=64)
                crop = scene["crop"]
                if part == "blend":
                    crop.masks.blend = np.zeros_like(crop.masks.blend)
                else:
                    crop.transform = replace(crop.transform, padding_ltrb=(1, 0, 0, 0))
                with self.assertRaisesRegex(ValueError, "changed after preparation"):
                    finish_native_crop(np.zeros((64, 64, 3), np.float32), scene)

    def test_empty_exterior_ring_bypasses_color_correction(self):
        template = np.full((64, 64, 3), 0.5, np.float32)
        scene = prepare_native_scene(template, np.ones((64, 64), np.float32),
                                     resolution=64, context=1, feather=0)
        generated = np.full((64, 64, 3), 0.8, np.float32)
        final, report = finish_native_crop(generated, scene, color_strength=1)
        correction = report["color_correction"]
        self.assertEqual(correction["exterior_ring_pixel_count"], 0)
        self.assertEqual(correction["method"], "insufficient_unedited_exterior_ring")
        np.testing.assert_array_equal(final, generated)

    def test_exterior_color_estimate_is_bounded_and_ignores_generated_head(self):
        template = np.full((128, 128, 3), 0.5, np.float32)
        _, mask = example()
        scene = prepare_native_scene(template, mask, resolution=96, context=2, feather=0)
        first = np.full((96, 96, 3), 0.7, np.float32)
        second = first.copy()
        first[scene["crop"].mask > 0] = 0.9
        second[scene["crop"].mask > 0] = 0.2
        final, report = finish_native_crop(first, scene, color_strength=1, max_shift=0.04)
        _, other = finish_native_crop(second, scene, color_strength=1, max_shift=0.04)
        correction = report["color_correction"]
        self.assertEqual(correction["method"], "bounded_exterior_ring_median")
        np.testing.assert_allclose(correction["applied_rgb_shift"], [-0.04] * 3, atol=1e-7)
        np.testing.assert_array_equal(correction["estimated_rgb_shift"],
                                      other["color_correction"]["estimated_rgb_shift"])
        np.testing.assert_array_equal(final[mask == 0], template[mask == 0])
        np.testing.assert_allclose(final[64, 64], [0.86] * 3, atol=1e-6)

    def test_bad_geometry_and_invalid_controls_are_rejected(self):
        template, mask = example()
        for options in ({"resolution": 48}, {"scene_mode": "automatic"},
                        {"edge_protection": float("nan")}, {"feather": -1},
                        {"edge_protection": 2}, {"expand": 0.5}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                prepare_native_scene(template, mask, **options)
        with self.assertRaisesRegex(ValueError, "Empty headmask"):
            prepare_native_scene(template, mask * 0, resolution=64)
        with self.assertRaisesRegex(ValueError, "contraction removed"):
            prepare_native_scene(template, mask, resolution=64, expand=-32)
        scene = prepare_native_scene(template, mask, resolution=64)
        with self.assertRaisesRegex(ValueError, "no implicit resizing"):
            finish_native_crop(np.zeros((32, 64, 3), np.float32), scene)
        for options in ({"color_strength": 2}, {"max_shift": float("inf")}, {"max_shift": -1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                finish_native_crop(np.zeros((64, 64, 3), np.float32), scene, **options)

    def test_non_square_native_crop_retains_exact_page_dimensions(self):
        template, mask = example()
        scene = prepare_native_scene(template, mask, resolution=(64, 96), expand=3)
        result, report = finish_native_crop(np.zeros((64, 96, 3), np.float32), scene)
        self.assertEqual(result.shape, template.shape)
        self.assertTrue(report["outside_mask_exact"])


class ReviewDiagnosticsTests(unittest.TestCase):
    def test_unchanged_editable_region_is_reported_without_semantic_scores(self):
        template, mask = example()
        report = review_diagnostics(template, template.copy(), mask)
        self.assertEqual(report["masked_changed_fraction"], 0)
        self.assertEqual(report["editable_pixel_count"], 48 * 48)
        self.assertTrue(any("identical" in warning for warning in report["warnings"]))
        self.assertNotIn("status", report)
        self.assertNotIn("identity_score", report)
        self.assertTrue(report["heuristic_only"])

    def test_black_missing_head_reports_constant_color_and_clipping(self):
        template, mask = example()
        output = template.copy()
        output[mask > 0] = 0
        report = review_diagnostics(template, output, mask)
        self.assertEqual(report["masked_changed_fraction"], 1)
        self.assertEqual(report["masked_near_black_fraction"], 1)
        self.assertEqual(report["masked_near_white_fraction"], 0)
        self.assertEqual(report["masked_channel_variance"], [0, 0, 0])
        self.assertTrue(any("constant color" in warning for warning in report["warnings"]))
        self.assertTrue(any("clipping" in warning for warning in report["warnings"]))

    def test_exact_pixel_fractions_variance_and_exclusion_of_protected_area(self):
        template = np.full((4, 4, 3), 0.5, np.float32)
        mask = np.zeros((4, 4), np.float32)
        mask[:2, :2] = 1
        output = np.zeros_like(template)
        output[0, 0] = 0
        output[0, 1] = 1
        output[1, 0] = 0.25
        output[1, 1] = 0.5
        report = review_diagnostics(template, output, mask)
        self.assertEqual(report["masked_changed_fraction"], 0.75)
        self.assertEqual(report["masked_near_black_fraction"], 0.25)
        self.assertEqual(report["masked_near_white_fraction"], 0.25)
        self.assertEqual(report["masked_near_black_or_white_fraction"], 0.5)
        np.testing.assert_allclose(report["masked_channel_variance"], [0.13671875] * 3)
        output[mask == 0] = 1
        self.assertEqual(report, review_diagnostics(template, output, mask))

    def test_uint8_and_float_input_measurements_have_the_same_scale(self):
        before = np.full((4, 4, 3), 128, np.uint8)
        after = before.copy()
        after[0] = 255
        after[1] = 0
        mask = np.ones((4, 4), np.float32)
        integer = review_diagnostics(before, after, mask)
        floating = review_diagnostics(before.astype(np.float64) / 255,
                                      after.astype(np.float64) / 255, mask)
        self.assertEqual(integer, floating)

    def test_flat_midgray_is_warned_even_without_black_or_white_clipping(self):
        before, mask = example()
        after = before.copy()
        after[mask > 0] = 0.5
        report = review_diagnostics(before, after, mask)
        self.assertEqual(report["masked_near_black_or_white_fraction"], 0)
        self.assertEqual(len(report["warnings"]), 1)
        self.assertIn("constant color", report["warnings"][0])

    def test_empty_mask_returns_unavailable_measurements(self):
        template, mask = example()
        report = review_diagnostics(template, template, mask * 0)
        self.assertEqual(report["editable_pixel_count"], 0)
        self.assertIsNone(report["masked_changed_fraction"])
        self.assertIsNone(report["masked_channel_variance"])
        self.assertIsNone(report["masked_near_black_fraction"])
        self.assertTrue(report["warnings"])

    def test_mismatched_shapes_and_nonfinite_images_are_rejected(self):
        before, mask = example()
        with self.assertRaisesRegex(ValueError, "same dimensions"):
            review_diagnostics(before, before[:64], mask)
        with self.assertRaises(ValueError):
            review_diagnostics(before, np.full_like(before, np.nan), mask)


if __name__ == "__main__":
    unittest.main()

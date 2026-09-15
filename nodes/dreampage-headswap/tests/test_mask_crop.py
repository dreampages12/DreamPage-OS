import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from dreampage_headswap.compositing import composite_to_template
from dreampage_headswap.masking import MaskConfig, load_headmask, process_mask, validate_mask
from dreampage_headswap.template import CropConfig, extract_crop, map_points_to_model, map_points_to_original, restore_crop
from dreampage_headswap.evaluation.metrics import preservation_metrics


class MaskCropTests(unittest.TestCase):
    def test_red_and_alpha_conventions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mask.png"
            rgba = np.zeros((12, 14, 4), np.uint8)
            rgba[3:7, 4:8, 0] = 255
            rgba[1:2, :, 3] = 255
            Image.fromarray(rgba).save(path)
            np.testing.assert_array_equal(load_headmask(path, channel="red").values, rgba[..., 0] / 255)
            np.testing.assert_array_equal(load_headmask(path, channel="alpha").values, rgba[..., 3] / 255)

    def test_invalid_masks(self):
        for mask in [np.full((3, 3), np.nan), np.full((3, 3), 255), np.zeros((3, 3, 3)), np.zeros((0, 3))]:
            with self.assertRaises(ValueError):
                validate_mask(mask)
        with self.assertRaises(ValueError):
            validate_mask(np.zeros((2, 3)), (3, 2))

    def test_expansion_only_changes_generation_authority(self):
        mask = np.zeros((30, 40), np.float32)
        mask[10:20, 10:20] = 1
        masks = process_mask(mask, MaskConfig(expand=4, feather=3))
        self.assertGreater(masks.generation.sum(), mask.sum())
        self.assertTrue(np.all(masks.blend[mask == 0] == 0))
        self.assertTrue(np.all(masks.blend <= mask))
        self.assertGreater(masks.blend[15, 15], masks.blend[10, 10])
        self.assertLess(process_mask(mask, MaskConfig(expand=-2)).generation.sum(), mask.sum())

    def test_empty_mask_rejects_crop(self):
        with self.assertRaises(ValueError):
            extract_crop(np.zeros((10, 10, 3), np.uint8), process_mask(np.zeros((10, 10))))

    def test_coordinate_roundtrip_at_image_edge(self):
        image = np.zeros((53, 97, 3), np.uint8)
        mask = np.zeros(image.shape[:2], np.float32)
        mask[:13, :17] = 1
        crop = extract_crop(image, process_mask(mask), CropConfig(resolution=(64, 96), context=2))
        self.assertGreater(sum(crop.transform.padding_ltrb), 0)
        points = np.array([[0, 0], [16, 12], [30.25, 19.625], [96, 52]])
        np.testing.assert_allclose(map_points_to_original(map_points_to_model(points, crop.transform), crop.transform), points, atol=1e-12)

    def test_identity_crop_restore_without_resizing(self):
        rng = np.random.default_rng(3)
        image = rng.random((32, 32, 3), dtype=np.float32)
        masks = process_mask(np.ones((32, 32), np.float32))
        crop = extract_crop(image, masks, CropConfig(32, context=1))
        np.testing.assert_array_equal(restore_crop(crop.image, crop.transform), image)
        np.testing.assert_array_equal(composite_to_template(image, crop.image, crop), image)

    def test_disconnected_mask_holes_and_edges_preserved(self):
        rng = np.random.default_rng(7)
        for dtype in (np.uint8, np.float32, np.float64):
            for resolution in (32, (48, 64)):
                with self.subTest(dtype=dtype, resolution=resolution):
                    image = rng.random((73, 101, 3))
                    image = np.rint(image * 255).astype(dtype) if dtype == np.uint8 else image.astype(dtype)
                    mask = np.zeros(image.shape[:2], np.float32)
                    mask[:12, :16] = 1
                    mask[25:40, 48:66] = 0.4
                    mask[29:33, 51:55] = 0
                    mask[-3:, -4:] = 1
                    crop = extract_crop(image, process_mask(mask, MaskConfig(3, 2)), CropConfig(resolution))
                    generated = rng.random((*crop.transform.model_hw, 3), dtype=np.float32)
                    output = composite_to_template(image, generated, crop)
                    np.testing.assert_array_equal(output[mask == 0], image[mask == 0])
                    self.assertEqual(output.shape, image.shape)
                    self.assertEqual(output.dtype, image.dtype)
                    metrics = preservation_metrics(image, output, mask)
                    self.assertTrue(metrics["outside_mask_exact"])
                    self.assertEqual(metrics["outside_mask_mae"], 0)
                    self.assertEqual(metrics["unexpected_altered_region_percentage"], 0)

    def test_soft_mask_alpha_applied_once(self):
        image = np.zeros((32, 32, 3), np.uint8)
        mask = np.zeros((32, 32), np.float32)
        mask[8:24, 8:24] = 0.5
        crop = extract_crop(image, process_mask(mask), CropConfig(32, context=1))
        out = composite_to_template(image, np.ones((32, 32, 3), np.float32), crop)
        self.assertTrue(np.all(out[mask > 0] == 128))

    def test_unauthorized_blend_rejected(self):
        image = np.zeros((32, 32, 3), np.uint8)
        mask = np.zeros((32, 32), np.float32)
        mask[8:24, 8:24] = 1
        crop = extract_crop(image, process_mask(mask), CropConfig(32))
        crop.masks.blend[0, 0] = 1
        with self.assertRaises(ValueError):
            composite_to_template(image, crop.image, crop)

    def test_lossless_png_preserves_protected_pixels(self):
        from dreampage_headswap.utils.images import save_rgb, load_rgb
        rng = np.random.default_rng(99)
        image = rng.integers(0, 256, (40, 60, 3), dtype=np.uint8)
        mask = np.zeros((40, 60), np.float32)
        mask[10:24, 20:38] = 1
        crop = extract_crop(image, process_mask(mask), CropConfig(32))
        output = composite_to_template(image, np.zeros_like(crop.image), crop)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "result.png"
            save_rgb(path, output)
            np.testing.assert_array_equal(load_rgb(path)[mask == 0], image[mask == 0])


if __name__ == "__main__":
    unittest.main()

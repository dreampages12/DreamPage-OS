"""Regression tests for identity leakage and preservation at real API boundaries.

All images are procedural rectangles; the spatial encoder is a three-pixel averaging
operator, not pretrained face software. These tests prove software invariants only.
"""
from __future__ import annotations

import unittest

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from comfyui_dreampage_headswap.conversion import image_to_array
from dreampage_headswap.backbones.base import GenerativeBackbone
from dreampage_headswap.dreamface import DreamFaceEncoder
from dreampage_headswap.dreamswap import DreamSwap
from dreampage_headswap.evaluation.metrics import outside_difference_image, preservation_metrics
from dreampage_headswap.evaluation.quality import QualityConfig, evaluate_quality
from dreampage_headswap.geometry import MaskContextGeometry
from dreampage_headswap.inference.pipeline import HeadSwapPipeline, InferenceConfig
from dreampage_headswap.masking import MaskConfig, process_mask, validate_mask
from dreampage_headswap.template import CropConfig, extract_crop
from dreampage_headswap.template.degradation import prepare_condition_crop
from dreampage_headswap.types import ChildIdentityInput, GeometryCondition, HeadMask, TemplateInput
from dreampage_headswap.utils.images import resize_array, to_tensor


def contrasting_templates(*, at_edge=False):
    mask = np.zeros((101, 113), np.float32)
    if at_edge:
        mask[:31, :29] = 1
    else:
        mask[31:64, 37:72] = 1
    first = np.full((*mask.shape, 3), 0.25, np.float32)
    second = first.copy()
    first[mask > 0] = 0.1
    second[mask > 0] = 0.9
    return first, second, mask


class RecordingModel(nn.Module):
    """Expose the orchestration's conditions without introducing model randomness."""

    def __init__(self):
        super().__init__()
        self.anchor = nn.Parameter(torch.zeros(()))
        self.conditions = []

    def sample(self, **kwargs):
        self.conditions.append({
            "template": kwargs["condition_template"].clone(),
            "geometry_spatial": kwargs["geometry"].spatial.clone(),
            "geometry_vector": kwargs["geometry"].vector.clone(),
        })
        return kwargs["condition_template"].clone()


class RecordingGeometry:
    def __init__(self):
        self.mask = None

    def extract(self, template, mask, metadata=None):
        self.mask = mask.detach().cpu().clone()
        return MaskContextGeometry().extract(template, mask, metadata)


class SpatialEncoderBackbone(GenerativeBackbone):
    """A receptive field makes leakage across a latent-mask boundary observable."""

    def encode_images(self, images):
        return F.avg_pool2d(images * 2 - 1, 3, stride=1, padding=1)

    def decode_latents(self, latents):
        return (latents + 1) / 2

    def predict_velocity(self, sample, t, condition):
        return F.avg_pool2d(sample, 3, stride=1, padding=1)


class IdentityIsolationRegressionTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)

    def test_native_suppression_precedes_resizing_and_edge_padding(self):
        for at_edge in (False, True):
            first, second, mask = contrasting_templates(at_edge=at_edge)
            for expand in (-4, 0, 8):
                masks = process_mask(mask, MaskConfig(expand=expand))
                crops = [extract_crop(image, masks, CropConfig(16, context=1.5))
                         for image in (first, second)]
                self.assertFalse(np.array_equal(crops[0].image, crops[1].image))
                if at_edge:
                    self.assertGreater(sum(crops[0].transform.padding_ltrb), 0)
                for strategy in ("neutral", "noise"):
                    with self.subTest(at_edge=at_edge, expand=expand, strategy=strategy):
                        prepared = [prepare_condition_crop(image, crop, strategy, seed=19)
                                    for image, crop in zip((first, second), crops)]
                        np.testing.assert_array_equal(prepared[0], prepared[1])

    def test_pipeline_geometry_and_condition_are_isolated_before_crop_resize(self):
        for at_edge in (False, True):
            with self.subTest(at_edge=at_edge):
                first, second, mask = contrasting_templates(at_edge=at_edge)
                model = RecordingModel()
                pipeline = HeadSwapPipeline(model, config=InferenceConfig(
                    crop=CropConfig(16, context=1.5), reference_resolution=16,
                    steps=2, degradation="neutral"))
                child = ChildIdentityInput([np.full((16, 16, 3), 0.3, np.float32)])
                outputs = [pipeline(child, TemplateInput(image), HeadMask(mask))
                           for image in (first, second)]
                for key in ("template", "geometry_spatial", "geometry_vector"):
                    torch.testing.assert_close(model.conditions[0][key], model.conditions[1][key],
                                               rtol=0, atol=0)
                for image, output in zip((first, second), outputs):
                    np.testing.assert_array_equal(image[mask == 0], output.image[mask == 0])

    def test_protected_latent_anchor_cannot_read_raw_template_identity(self):
        torch.manual_seed(42)
        model = DreamSwap(DreamFaceEncoder(dim=16), SpatialEncoderBackbone())
        mask = torch.zeros(1, 1, 16, 16)
        mask[:, :, 5:11, 5:11] = 1
        base = torch.full((1, 3, 16, 16), 0.25)
        first = torch.where(mask > 0, 0.1, base)
        second = torch.where(mask > 0, 0.9, base)
        sanitized = torch.where(mask > 0, 0.5, base)
        geometry = GeometryCondition(torch.zeros(1, 4, 16, 16), torch.zeros(1, 16))
        references = torch.zeros(1, 1, 3, 16, 16)
        outputs = [model.sample(references, template, mask, geometry, steps=3,
                                seed=7, condition_template=sanitized)
                   for template in (first, second)]
        # Raw-template anchors previously changed masked output by approximately .0351.
        torch.testing.assert_close(outputs[0], outputs[1], rtol=0, atol=0)

    def test_geometry_tracks_original_headmask_when_generation_mask_changes(self):
        image, _, mask = contrasting_templates()
        for expand in (-4, 8):
            with self.subTest(expand=expand):
                geometry = RecordingGeometry()
                config = InferenceConfig(crop=CropConfig(64, context=1.5),
                                         mask=MaskConfig(expand=expand), reference_resolution=16,
                                         steps=1)
                pipeline = HeadSwapPipeline(RecordingModel(), config=config, geometry=geometry)
                child = ChildIdentityInput([np.full((16, 16, 3), 0.3, np.float32)])
                output = pipeline(child, TemplateInput(image), HeadMask(mask))
                transform = output.debug["crop_transform"]
                x0, y0, x1, y1 = transform["box_xyxy"]
                left, top, right, bottom = transform["padding_ltrb"]
                padded = np.pad(mask[y0:y1, x0:x1], ((top, bottom), (left, right)))
                original_at_model = resize_array(padded, tuple(transform["model_hw"]), mask=True)
                np.testing.assert_array_equal(geometry.mask[0, 0].numpy() > 0,
                                              original_at_model > 0)

    def test_valid_saturated_images_stay_valid_after_internal_resize(self):
        image, _, mask = contrasting_templates()
        image[mask > 0] = 1.0
        crop = extract_crop(image, process_mask(mask), CropConfig(16, context=1.5))
        self.assertGreaterEqual(float(crop.image.min()), 0)
        self.assertLessEqual(float(crop.image.max()), 1)
        self.assertTrue(torch.isfinite(to_tensor(crop.image)).all())


class PrecisionAndAdmissionRegressionTests(unittest.TestCase):
    def test_float64_preservation_measurements_keep_sub_float32_changes(self):
        template = np.full((4, 4, 3), 0.5, np.float64)
        output = template.copy()
        output[0, 0, 0] += 1e-10
        delta = output[0, 0, 0] - template[0, 0, 0]
        mask = np.zeros((4, 4), np.float32)
        metrics = preservation_metrics(template, output, mask)
        self.assertFalse(metrics["outside_mask_exact"])
        self.assertEqual(metrics["outside_mask_max"], delta)
        self.assertEqual(metrics["outside_mask_mae"], delta / template.size)
        self.assertEqual(metrics["outside_mask_changed_percentage"], 6.25)
        difference = outside_difference_image(template, output, mask)
        self.assertEqual(float(difference[0, 0, 0]), delta)

    def test_invalid_mask_values_are_rejected_before_float32_rounding(self):
        for value in (1 + 1e-9, -1e-50, np.nan, np.inf, -np.inf):
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                validate_mask(np.full((2, 2), value, np.float64))

    def test_positive_mask_support_cannot_silently_underflow_to_protected(self):
        values = np.full((2, 2), 1e-50, np.float64)
        try:
            result = validate_mask(values)
        except ValueError:
            return  # Explicitly refusing unrepresentable precision is also safe.
        self.assertTrue(np.all(result > 0), "A supplied positive authority silently became zero")

    def test_omitting_quality_requirements_cannot_create_a_preservation_only_pass(self):
        try:
            config = QualityConfig(required=())
        except ValueError:
            return  # The configuration itself may enforce mandatory identity/realism.
        image = np.zeros((4, 4, 3), np.uint8)
        metrics = evaluate_quality(image, image.copy(), np.ones((4, 4), np.float32),
                                   config=config, model_validated=True)
        self.assertNotEqual(metrics.status, "PASS")

    def test_comfy_rejects_materially_out_of_range_external_image_values(self):
        for value in (-0.25, 1.25):
            with self.subTest(value=value), self.assertRaises(ValueError):
                image_to_array(torch.full((1, 2, 2, 3), value))


if __name__ == "__main__":
    unittest.main()

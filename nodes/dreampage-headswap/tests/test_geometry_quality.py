import unittest

import numpy as np
import torch

from dreampage_headswap.geometry import MaskContextGeometry
from dreampage_headswap.template.degradation import suppress_template
from dreampage_headswap.evaluation.quality import evaluate_quality


class GeometryQualityTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.template = torch.rand(1, 3, 32, 40)
        self.mask = torch.zeros(1, 1, 32, 40)
        self.mask[:, :, 8:24, 10:30] = 1

    def test_geometry_shape_and_identity_isolation(self):
        extractor = MaskContextGeometry()
        a = extractor.extract(self.template, self.mask)
        modified = torch.where(self.mask > 0, torch.rand_like(self.template), self.template)
        b = extractor.extract(modified, self.mask)
        torch.testing.assert_close(a.spatial, b.spatial)
        torch.testing.assert_close(a.vector, b.vector)
        self.assertEqual(a.spatial.shape, (1, 4, 32, 40))
        self.assertEqual(a.vector.shape, (1, 16))
        self.assertFalse(a.measurements["face_geometry_available"])

    def test_supplied_geometry(self):
        geometry = MaskContextGeometry().extract(self.template, self.mask, {"yaw": 30, "mouth_openness": 0.2})
        self.assertAlmostEqual(geometry.vector[0, 8].item(), 30 / 180)
        self.assertEqual(geometry.measurements["supplied"]["yaw"], 30)
        self.assertFalse(geometry.measurements["pose_estimated"])

    def test_neutral_suppression_removes_internal_rgb(self):
        modified = torch.where(self.mask > 0, torch.rand_like(self.template), self.template)
        a = suppress_template(self.template, self.mask)
        b = suppress_template(modified, self.mask)
        torch.testing.assert_close(a, b)
        protected = (self.mask == 0).expand_as(a)
        torch.testing.assert_close(a[protected], self.template[protected])

    def test_noise_reproducible_and_internal_requires_explicit_mask(self):
        a = suppress_template(self.template, self.mask, "noise", seed=42)
        b = suppress_template(self.template, self.mask, "noise", seed=42)
        torch.testing.assert_close(a, b)
        with self.assertRaises(ValueError):
            suppress_template(self.template, self.mask, "internal")
        self.assertEqual(suppress_template(self.template, self.mask, "blur").shape, self.template.shape)

    def test_perfect_preservation_cannot_fake_quality_pass(self):
        image = np.zeros((20, 20, 3), np.uint8)
        mask = np.zeros((20, 20), np.float32)
        mask[5:15, 5:15] = 1
        result = evaluate_quality(image, image.copy(), mask)
        self.assertEqual(result.template_preservation_score, 1)
        self.assertIsNone(result.identity_score)
        self.assertIsNone(result.overall_score)
        self.assertEqual(result.status, "RETRY")

    def test_any_outside_change_fails(self):
        image = np.zeros((20, 20, 3), np.uint8)
        output = image.copy()
        output[0, 0, 0] = 1
        result = evaluate_quality(image, output, np.zeros((20, 20), np.float32))
        self.assertEqual(result.status, "FAIL")
        self.assertGreater(result.measurements["outside_mask_mae"], 0)

    def test_quality_provider_and_required_age(self):
        class Provider:
            def score(self, *args):
                return dict(identity_score=0.95, pose_score=0.95, boundary_score=0.95, face_quality_score=0.95)
        image = np.zeros((20, 20, 3), np.uint8)
        mask = np.ones((20, 20), np.float32)
        self.assertEqual(evaluate_quality(image, image, mask, provider=Provider(), model_validated=True).status, "PASS")
        self.assertEqual(evaluate_quality(image, image, mask, provider=Provider(), model_validated=True, age=5).status, "RETRY")


if __name__ == "__main__":
    unittest.main()

"""Enrolment: headmask providers, ingest and the corpus quality report.

Enrolment is where a corpus's rights story is fixed, so the tests here are mostly about what is
refused: a capture nobody could mask, a licence nobody stated, a box measured on an image that
was then rotated, and a duplicate that would otherwise appear on both sides of a split.
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from _fixtures import load_script, rights, write_image, write_mask
from dreampage_headswap.data.headmasks import (CallableMaskProvider, FirstAvailableProvider, MaskResult,
                                               SidecarMaskProvider, SuppliedBoxMaskProvider,
                                               UnavailableMaskProvider, box_mask, build_provider)
from dreampage_headswap.data.records import read_jsonl


def raw_corpus(root: Path, *, identities: int = 2, captures: int = 2, masks: bool = True,
               size=(96, 96)) -> Path:
    for index in range(identities):
        directory = root / f"person_{index:03d}"
        for capture in range(captures):
            image = write_image(directory / f"capture_{capture}.png", index * 10 + capture, size)
            if masks:
                write_mask(image.with_name(image.stem + "_mask.png"), size, (24, 20, 72, 76))
    return root


class BoxMaskTests(unittest.TestCase):
    def test_an_ellipse_stays_inside_its_box_and_covers_the_centre(self):
        mask = box_mask((64, 64), (16, 16, 48, 48))
        self.assertEqual(mask[32, 32], 1.0)
        self.assertEqual(mask[0, 0], 0.0)
        rows, columns = np.nonzero(mask)
        self.assertGreaterEqual(rows.min(), 16)
        self.assertLessEqual(rows.max(), 47)
        self.assertLess(mask.mean(), (32 * 32) / (64 * 64))  # an ellipse is smaller than its box

    def test_padding_grows_it_and_a_rectangle_fills_the_box(self):
        plain = box_mask((64, 64), (16, 16, 48, 48))
        padded = box_mask((64, 64), (16, 16, 48, 48), padding=0.2)
        self.assertGreater(padded.sum(), plain.sum())
        rectangle = box_mask((64, 64), (16, 16, 48, 48), shape="rectangle")
        self.assertEqual(rectangle.sum(), 32 * 32)

    def test_feathering_softens_only_the_edge(self):
        feathered = box_mask((64, 64), (12, 12, 52, 52), shape="rectangle", feather=3)
        self.assertEqual(feathered[32, 32], 1.0)
        self.assertTrue(np.any((feathered > 0) & (feathered < 1)))

    def test_invalid_boxes_are_rejected(self):
        for box in ((10, 10, 10, 20), (10, 10, 20, 10), (0, 0, float("nan"), 5), (1, 2, 3)):
            with self.subTest(box=box), self.assertRaises(ValueError):
                box_mask((32, 32), box)


class ProviderTests(unittest.TestCase):
    def test_the_default_provider_refuses_with_a_reason(self):
        result = UnavailableMaskProvider().mask(np.zeros((8, 8, 3), np.float32), {})
        self.assertIsNone(result.values)
        self.assertIn("No headmask provider configured", result.reason)

    def test_a_sidecar_mask_claims_reviewed_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = write_image(root / "a.png", 1, (64, 64))
            write_mask(root / "a_mask.png", (64, 64), (16, 16, 48, 48))
            provider = SidecarMaskProvider()
            result = provider.mask(np.asarray(Image.open(image).convert("RGB")), {"path": str(image)})
            self.assertEqual(result.authority, "reviewed_external")
            self.assertTrue(result.license)
            self.assertAlmostEqual(float(result.values.mean()), (32 * 32) / (64 * 64), places=6)

    def test_a_sidecar_mask_of_the_wrong_size_or_full_frame_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = write_image(root / "a.png", 1, (64, 64))
            pixels = np.asarray(Image.open(image).convert("RGB"))
            write_mask(root / "a_mask.png", (32, 32), (4, 4, 20, 20))
            self.assertIn("dimensions", SidecarMaskProvider().mask(pixels, {"path": str(image)}).reason)
            write_mask(root / "a_mask.png", (64, 64), (0, 0, 64, 64))
            self.assertIn("whole frame", SidecarMaskProvider().mask(pixels, {"path": str(image)}).reason)

    def test_a_box_provider_marks_its_mask_as_derived(self):
        provider = SuppliedBoxMaskProvider()
        result = provider.mask(np.zeros((64, 64, 3), np.float32), {"head_bbox": [16, 16, 48, 48]})
        self.assertEqual(result.authority, "derived_geometric")
        self.assertIn("not a reviewed production mask", result.metadata["note"])
        self.assertIsNone(provider.mask(np.zeros((8, 8, 3), np.float32), {}).values)

    def test_a_model_provider_must_state_its_weights_licence(self):
        with self.assertRaisesRegex(ValueError, "licence"):
            CallableMaskProvider(lambda image, metadata: None, name="something", license="  ")
        provider = CallableMaskProvider(lambda image, metadata: box_mask(image.shape[:2], (2, 2, 6, 6)),
                                        name="fake_segmenter", license="Apache-2.0 weights, reviewed 2026-09")
        result = provider.mask(np.zeros((8, 8, 3), np.float32), {})
        self.assertEqual(result.authority, "derived_model")
        self.assertIn("Apache-2.0", result.license)

    def test_a_produced_mask_without_provenance_cannot_be_constructed(self):
        with self.assertRaises(ValueError):
            MaskResult(np.ones((4, 4), np.float32), "x", authority="reviewed_external", license=None)
        with self.assertRaises(ValueError):
            MaskResult(np.ones((4, 4), np.float32), "x", authority="invented", license="mit")
        with self.assertRaises(ValueError):
            MaskResult(None, "x")

    def test_first_available_prefers_reviewed_and_reports_both_reasons(self):
        provider = FirstAvailableProvider(SidecarMaskProvider(), SuppliedBoxMaskProvider())
        image = np.zeros((64, 64, 3), np.float32)
        result = provider.mask(image, {"head_bbox": [16, 16, 48, 48]})
        self.assertEqual(result.authority, "derived_geometric")
        empty = provider.mask(image, {})
        self.assertIn("sidecar_file", empty.reason)
        self.assertIn("supplied_box_geometry", empty.reason)

    def test_unknown_named_providers_point_at_the_code_path(self):
        self.assertIsInstance(build_provider("none"), UnavailableMaskProvider)
        with self.assertRaisesRegex(ValueError, "CallableMaskProvider"):
            build_provider("sam2")


class IngestTests(unittest.TestCase):
    def _run(self, args):
        script = load_script("ingest_dataset")
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            code = script.main(args)
        return code, stream.getvalue()

    def test_sidecar_ingest_produces_a_manifest_that_passes_the_rights_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_corpus(root / "raw")
            (root / "rights.json").write_text(json.dumps(rights()), encoding="utf-8")
            code, _ = self._run(["--root", str(root / "raw"), "--output-dir", str(root / "enrolled"),
                                 "--rights", str(root / "rights.json"), "--synthetic"])
            self.assertEqual(code, 0)
            rows = read_jsonl(root / "enrolled" / "identities.jsonl")
            self.assertEqual(len(rows), 2)
            self.assertEqual(len(rows[0]["images"]), 2)
            self.assertEqual(rows[0]["images"][0]["headmask_provenance"]["authority"], "reviewed_external")
            report = json.loads((root / "enrolled" / "ingest_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["identities_enrolled"], 2)
            self.assertEqual(report["mask_authority_counts"], {"reviewed_external": 4})
            self.assertIn("preprocess_dataset.py", report["next"])

    def test_captures_without_a_mask_are_rejected_not_invented(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_corpus(root / "raw", masks=False)
            (root / "rights.json").write_text(json.dumps(rights()), encoding="utf-8")
            code, _ = self._run(["--root", str(root / "raw"), "--output-dir", str(root / "enrolled"),
                                 "--rights", str(root / "rights.json"), "--synthetic"])
            self.assertEqual(code, 1)
            report = json.loads((root / "enrolled" / "ingest_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["identities_enrolled"], 0)
            self.assertTrue(all(row["reason"].startswith(("no_headmask", "fewer_than"))
                                for row in report["captures"]))

    def test_supplied_boxes_fill_in_where_reviewed_masks_are_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_corpus(root / "raw", identities=1, masks=False)
            (root / "rights.json").write_text(json.dumps(rights()), encoding="utf-8")
            boxes = {"person_000/capture_0": [20, 18, 76, 80], "person_000/capture_1": [22, 20, 74, 78]}
            (root / "boxes.json").write_text(json.dumps(boxes), encoding="utf-8")
            code, _ = self._run(["--root", str(root / "raw"), "--output-dir", str(root / "enrolled"),
                                 "--rights", str(root / "rights.json"), "--synthetic",
                                 "--mask-provider", "sidecar-then-box", "--boxes", str(root / "boxes.json")])
            self.assertEqual(code, 0)
            report = json.loads((root / "enrolled" / "ingest_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["mask_authority_counts"], {"derived_geometric": 2})
            self.assertIn("coarse box approximations", report["note"])

    def test_a_box_measured_before_reorientation_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_corpus(root / "raw", identities=1, masks=False)
            rotated = root / "raw" / "person_000" / "capture_0.png"
            with Image.open(rotated) as image:
                exif = image.getexif()
                exif[274] = 6  # rotate 90 degrees on load
                image.save(rotated, exif=exif)
            (root / "rights.json").write_text(json.dumps(
                {"person_000/capture_0": [20, 18, 76, 80]}), encoding="utf-8")
            (root / "boxes.json").write_text(json.dumps({"person_000/capture_0": [20, 18, 76, 80]}), encoding="utf-8")
            (root / "rights.json").write_text(json.dumps(rights()), encoding="utf-8")
            code, _ = self._run(["--root", str(root / "raw"), "--output-dir", str(root / "enrolled"),
                                 "--rights", str(root / "rights.json"), "--synthetic",
                                 "--mask-provider", "supplied-box", "--boxes", str(root / "boxes.json")])
            report = json.loads((root / "enrolled" / "ingest_report.json").read_text(encoding="utf-8"))
            refused = [row for row in report["captures"] if row.get("reason", "").startswith("supplied_box_with")]
            self.assertEqual(len(refused), 1)
            self.assertEqual(code, 1)

    def test_duplicate_captures_are_dropped_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_corpus(root / "raw", identities=1, captures=2)
            first = root / "raw" / "person_000" / "capture_0.png"
            copy = root / "raw" / "person_000" / "capture_2.png"
            copy.write_bytes(first.read_bytes())
            write_mask(copy.with_name("capture_2_mask.png"), (96, 96), (24, 20, 72, 76))
            (root / "rights.json").write_text(json.dumps(rights()), encoding="utf-8")
            self._run(["--root", str(root / "raw"), "--output-dir", str(root / "enrolled"),
                       "--rights", str(root / "rights.json"), "--synthetic"])
            report = json.loads((root / "enrolled" / "ingest_report.json").read_text(encoding="utf-8"))
            duplicates = [row for row in report["captures"] if row.get("reason", "").startswith("duplicate_of")]
            self.assertEqual(len(duplicates), 1)
            self.assertEqual(report["captures_enrolled"], 2)

    def test_incomplete_rights_stop_the_run_before_anything_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_corpus(root / "raw")
            broken = rights()
            broken["consent"] = {"status": "pending", "reference": "x", "training_permitted": True}
            (root / "rights.json").write_text(json.dumps(broken), encoding="utf-8")
            with self.assertRaises(ValueError):
                self._run(["--root", str(root / "raw"), "--output-dir", str(root / "enrolled"),
                           "--rights", str(root / "rights.json"), "--synthetic"])
            self.assertFalse((root / "enrolled").exists())


class DatasetReportTests(unittest.TestCase):
    def _report(self, manifest: Path, extra=()):
        script = load_script("dataset_report")
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            code = script.main(["--identities", str(manifest), "--allow-synthetic", *extra])
        return code, json.loads(stream.getvalue())

    def _enrolled(self, root: Path, **kwargs) -> Path:
        raw_corpus(root / "raw", **kwargs)
        (root / "rights.json").write_text(json.dumps(rights()), encoding="utf-8")
        script = load_script("ingest_dataset")
        with contextlib.redirect_stdout(io.StringIO()):
            script.main(["--root", str(root / "raw"), "--output-dir", str(root / "enrolled"),
                         "--rights", str(root / "rights.json"), "--synthetic"])
        return root / "enrolled" / "identities.jsonl"

    def test_a_small_corpus_reports_the_gaps_it_actually_has(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = self._enrolled(Path(tmp), identities=2, captures=2)
            code, report = self._report(manifest)
            self.assertEqual(code, 2)
            gaps = {item["criterion"] for item in report["criteria"] if item["status"] == "gap"}
            self.assertIn("distinct identities", gaps)
            self.assertIn("captures per identity", gaps)
            self.assertIn("ages recorded", gaps)
            self.assertIn("pose and expression metadata", gaps)
            passes = {item["criterion"] for item in report["criteria"] if item["status"] == "pass"}
            self.assertIn("headmask on every capture", passes)
            self.assertIn("reviewed masks", passes)
            self.assertIn("no duplicate captures", passes)

    def test_thresholds_are_explicit_and_a_corpus_can_meet_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = self._enrolled(Path(tmp), identities=6, captures=3)
            code, report = self._report(manifest, ["--min-identities", "6", "--min-captures", "3",
                                                   "--min-head-pixels", "40", "--min-blur", "10"])
            gaps = {item["criterion"] for item in report["criteria"] if item["status"] == "gap"}
            self.assertNotIn("distinct identities", gaps)
            self.assertNotIn("captures per identity", gaps)
            self.assertNotIn("head resolution", gaps)
            self.assertEqual(report["identities"], 6)
            self.assertEqual(report["captures"], 18)
            self.assertEqual(code, 2)  # ages and pose metadata remain genuinely absent

    def test_head_resolution_is_measured_across_the_mask_not_the_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self._enrolled(root, identities=2, captures=2)
            _, report = self._report(manifest, ["--min-head-pixels", "40", "--min-blur", "10"])
            head = [item for item in report["criteria"] if item["criterion"] == "head resolution"][0]
            # The fixture mask is a 48x56 box inside a 96x96 capture.
            self.assertEqual(head["measured"]["min"], 48.0)
            self.assertEqual(head["status"], "pass")

    def test_a_mask_covering_the_frame_or_touching_the_border_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_corpus(root / "raw", identities=2, captures=2)
            for mask in (root / "raw").rglob("*_mask.png"):
                write_mask(mask, (96, 96), (0, 0, 90, 90))
            (root / "rights.json").write_text(json.dumps(rights()), encoding="utf-8")
            script = load_script("ingest_dataset")
            with contextlib.redirect_stdout(io.StringIO()):
                script.main(["--root", str(root / "raw"), "--output-dir", str(root / "enrolled"),
                             "--rights", str(root / "rights.json"), "--synthetic"])
            _, report = self._report(root / "enrolled" / "identities.jsonl")
            by_name = {item["criterion"]: item for item in report["criteria"]}
            self.assertEqual(by_name["protected context remains"]["status"], "gap")
            self.assertEqual(by_name["head inside the frame"]["status"], "gap")


if __name__ == "__main__":
    unittest.main()

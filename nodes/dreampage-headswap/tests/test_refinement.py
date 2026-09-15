from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image
import torch
from torch.utils.data import DataLoader

from _fixtures import training_corpus
from dreampage_headswap.data.records import read_jsonl, write_jsonl, file_sha256
from dreampage_headswap.data.refinement import RefinementDataset
from dreampage_headswap.dreamface import DreamFaceEncoder
from dreampage_headswap.dreamrefine.system import RefinementObjective
from dreampage_headswap.training.refiner import build_refinement_system, load_refinement_system, train_refiner, verify_teacher
from dreampage_headswap.training.validation import dataset_fingerprint
from dreampage_headswap.utils.checkpoint import save_checkpoint


def refinement_fixture(root):
    base = training_corpus(root, identities=4, resolution=32)
    teacher = DreamFaceEncoder(32, 16, 2)
    teacher_path = root / "teacher-fixture.pt"
    # This is explicitly an unvalidated synthetic checkpoint fixture, not a learned evaluator.
    save_checkpoint(teacher_path, teacher, config={"model": {"identity_dim": 32, "structure_dim": 16, "token_grid": 2}},
                    step=1, metadata={"component": "dreamface_encoder", "synthetic": True,
                                     "scope": "Untrained checkpoint-format fixture"})
    paths = [base["dataset"]["manifest"], *base["dataset"]["peer_manifests"]]
    artifacts = []
    for path in paths:
        for row in read_jsonl(path):
            with Image.open(row["template"]) as image:
                pixels = np.array(image.convert("RGB"))
            changed = np.clip(pixels.astype(np.int16) + 5, 0, 255).astype(np.uint8)
            generated = root / (row["pair_id"] + ".png")
            Image.fromarray(changed).save(generated)
            artifacts.append({"pair_id": row["pair_id"], "generated": str(generated), "sha256": file_sha256(generated),
                              "generator": {"kind": "procedural_fixture", "recipe_sha256": "a" * 64}})
    artifacts_path = root / "artifacts.jsonl"
    write_jsonl(artifacts_path, artifacts)
    return {"model": {"width": 16, "max_delta": 0.08},
            "teacher": {"checkpoint": str(teacher_path), "allow_unvalidated_for_synthetic": True},
            "dataset": {**base["dataset"], "artifacts_manifest": str(artifacts_path), "source_crops": True},
            "optimizer": base["optimizer"], "scheduler": base["scheduler"],
            "training": {**base["training"], "max_steps": 3, "output_dir": str(root / "refiner")},
            "losses": {"reconstruction": 1, "boundary": 1, "identity_source": 1, "identity_anchor": 3},
            "validation": {"manifest": base["dataset"]["peer_manifests"][0], "every": 2, "max_batches": 1,
                           "samples": True}}


def dataset(config):
    d = config["dataset"]
    return RefinementDataset(d["manifest"], artifacts_manifest=d["artifacts_manifest"],
                              peer_manifests=d["peer_manifests"], allow_synthetic=True, resolution=32, source_crops=True)


class RefinementTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)

    def test_gradients_reach_refiner_but_teacher_remains_frozen(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = refinement_fixture(Path(tmp))
            system, _ = build_refinement_system(config)
            batch = next(iter(DataLoader(dataset(config), batch_size=2)))
            loss, metrics, result = RefinementObjective(config["losses"])(system, batch)
            loss.backward()
            self.assertTrue(any(p.grad is not None and p.grad.abs().sum() > 0 for p in system.refiner.parameters()))
            self.assertTrue(all(p.grad is None and not p.requires_grad for p in system.identity_encoder.parameters()))
            system.train()
            self.assertFalse(system.identity_encoder.training)
            self.assertEqual(metrics["protected_max_difference"], 0)

    def test_identity_constraints_cannot_be_disabled(self):
        with self.assertRaisesRegex(ValueError, "identity_source"):
            RefinementObjective({"reconstruction": 1})
        with self.assertRaises(ValueError):
            RefinementObjective({"reconstruction": float("nan"), "identity_source": 1, "identity_anchor": 1})

    def test_mutated_generated_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = refinement_fixture(Path(tmp))
            path = Path(read_jsonl(config["dataset"]["artifacts_manifest"])[0]["generated"])
            Image.new("RGB", (96, 96), (25, 30, 35)).save(path)
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                dataset(config)

    def test_wrong_generated_geometry_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = refinement_fixture(Path(tmp))
            rows = read_jsonl(config["dataset"]["artifacts_manifest"])
            Image.new("RGB", (20, 20)).save(rows[0]["generated"])
            rows[0]["sha256"] = file_sha256(rows[0]["generated"])
            write_jsonl(config["dataset"]["artifacts_manifest"], rows)
            with self.assertRaisesRegex(ValueError, "exact dimensions"):
                dataset(config)[0]

    def test_generated_artifact_cannot_copy_another_splits_base_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = refinement_fixture(Path(tmp))
            annotations = read_jsonl(config["dataset"]["artifacts_manifest"])
            validation = read_jsonl(config["dataset"]["peer_manifests"][0])[0]
            annotations[0]["generated"] = validation["template"]
            annotations[0]["sha256"] = file_sha256(validation["template"])
            write_jsonl(config["dataset"]["artifacts_manifest"], annotations)
            with self.assertRaisesRegex(ValueError, "pixel leakage"):
                dataset(config)

    def test_real_training_cannot_enable_unvalidated_teacher(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = refinement_fixture(Path(tmp))
            _, metadata = build_refinement_system(config)
            pairs = dataset(config)
            pairs.rows[0]["synthetic"] = False
            with self.assertRaisesRegex(ValueError, "restricted to synthetic"):
                verify_teacher(config["teacher"], metadata, [pairs])
            with self.assertRaisesRegex(ValueError, "teacher.review"):
                verify_teacher({"allow_unvalidated_for_synthetic": False}, metadata, [pairs])

    def test_short_training_bundle_and_pipeline_refinement(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            config = refinement_fixture(Path(tmp))
            result = train_refiner(config)
            self.assertEqual(result["step"], 3)
            self.assertFalse(result["identity_quality_validated"])
            self.assertTrue(Path(result["best_checkpoint"]).is_file())
            loaded = load_refinement_system(result["checkpoint"])
            batch = next(iter(DataLoader(dataset(config), batch_size=1)))
            with torch.no_grad():
                refined = loaded.refine(batch["generated"], batch["template"], (batch["mask"] > 0).float(), batch["references"])
            outside = (batch["mask"] == 0).expand_as(refined)
            self.assertTrue(torch.equal(refined[outside], batch["template"][outside]))
            inside = (batch["mask"] > 0).expand_as(refined)
            self.assertLessEqual(float((refined - batch["generated"]).abs()[inside].max()), 0.080001)
            from dreampage_headswap.training.factory import build_model
            from dreampage_headswap.inference.pipeline import HeadSwapPipeline, InferenceConfig
            from dreampage_headswap.template import CropConfig
            from dreampage_headswap.types import ChildIdentityInput, TemplateInput, HeadMask
            pipeline = HeadSwapPipeline(build_model({"backbone": "tiny", "identity_dim": 16, "width": 16}),
                        refiner=loaded, config=InferenceConfig(crop=CropConfig(32), steps=2, refine_strength=1))
            image = np.ones((40, 48, 3), dtype=np.float32) * .5
            mask = np.zeros((40, 48), dtype=np.float32)
            mask[8:30, 10:34] = 1
            output = pipeline(ChildIdentityInput([image]), TemplateInput(image), HeadMask(mask))
            np.testing.assert_array_equal(output.image[mask == 0], image[mask == 0])
            self.assertEqual(output.quality.status, "RETRY")

    def test_refiner_exact_resume_and_unchanged_frozen_encoder(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            root = Path(tmp)
            config = refinement_fixture(root)
            config["training"].update(max_steps=5, output_dir=str(root / "full"))
            full = train_refiner(config)
            interrupted = copy.deepcopy(config)
            interrupted["training"].update(max_steps=3, output_dir=str(root / "part"))
            part = train_refiner(interrupted)
            interrupted["training"]["max_steps"] = 5
            resumed = train_refiner(interrupted, part["checkpoint"])
            full_state = torch.load(full["checkpoint"], weights_only=False)["model"]
            resumed_state = torch.load(resumed["checkpoint"], weights_only=False)["model"]
            self.assertTrue(all(torch.equal(value, resumed_state[name]) for name, value in full_state.items()))
            teacher = torch.load(config["teacher"]["checkpoint"], weights_only=False)["model"]
            self.assertTrue(all(torch.equal(value, full_state["identity_encoder." + name]) for name, value in teacher.items()))

    def test_source_mask_bytes_are_part_of_exact_resume_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = refinement_fixture(Path(tmp))
            pairs = dataset(config)
            before = dataset_fingerprint(pairs)
            path = pairs.rows[0]["source_headmasks"][0]
            Image.new("L", (96, 96), 255).save(path)
            self.assertNotEqual(before, dataset_fingerprint(pairs))


if __name__ == "__main__":
    unittest.main()

"""The training loop, run for real on a small enrolled corpus of procedural noise.

The property worth protecting here is exact resume: stopping at step two and resuming must land
on the same parameters as running straight through to step four. Without that, a long run that
is interrupted quietly becomes a different experiment.
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch

from _fixtures import rights, training_corpus, write_image
from dreampage_headswap.data.records import read_jsonl, write_jsonl
from dreampage_headswap.training.loop import train


def state(path: Path) -> dict:
    return torch.load(path, map_location="cpu", weights_only=False)


class TrainLoopTests(unittest.TestCase):
    def test_nondefault_degradation_is_shared_by_training_and_validation(self):
        from contextlib import redirect_stdout
        import io
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            config = training_corpus(Path(tmp), validation={"every": 1, "max_batches": 1})
            config["dataset"]["degradation"] = "noise"
            config["training"]["max_steps"] = 1
            result = train(config)
            self.assertEqual(result["step"], 1)
            self.assertEqual(len(result["validation_history"]), 1)

    def test_a_short_run_trains_checkpoints_and_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = training_corpus(root)
            result = train(config)
            self.assertEqual(result["step"], 4)
            self.assertFalse(result["quality_validated"])
            self.assertEqual(len(result["loss_history"]), 4)
            checkpoint = Path(result["checkpoint"])
            self.assertTrue(checkpoint.is_file())
            saved = state(checkpoint)
            self.assertEqual(saved["step"], 4)
            self.assertEqual(saved["data_cursor"], 4)
            self.assertEqual(saved["metadata"]["world_size"], 1)
            self.assertTrue(saved["metadata"]["synthetic"])
            self.assertIsNotNone(saved["optimizer"])
            metrics = [json.loads(line) for line in
                       Path(root, "run", "metrics.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(metrics), 4)
            self.assertEqual([row["step"] for row in metrics], [1, 2, 3, 4])
            self.assertIn("outside_mask", metrics[0])
            self.assertIn("lr", metrics[0])

    def test_resume_reproduces_an_uninterrupted_run_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = training_corpus(root)

            straight = copy.deepcopy(config)
            straight["training"]["output_dir"] = str(root / "straight")
            train(straight)

            interrupted = copy.deepcopy(config)
            interrupted["training"]["output_dir"] = str(root / "interrupted")
            interrupted["training"]["max_steps"] = 2
            train(interrupted)
            resumed = copy.deepcopy(interrupted)
            resumed["training"]["max_steps"] = 4
            result = train(resumed, resume=str(root / "interrupted" / "checkpoint.pt"))
            self.assertEqual(result["step"], 4)

            expected = state(root / "straight" / "checkpoint.pt")["model"]
            actual = state(root / "interrupted" / "checkpoint.pt")["model"]
            self.assertEqual(sorted(expected), sorted(actual))
            for name, tensor in expected.items():
                self.assertTrue(torch.equal(tensor, actual[name]), name)

    def test_resume_refuses_a_changed_experiment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = training_corpus(root)
            config["training"]["max_steps"] = 2
            train(config)
            changed = copy.deepcopy(config)
            changed["training"]["max_steps"] = 4
            changed["losses"] = {"flow_matching": 1.0}
            with self.assertRaisesRegex(ValueError, "Cannot exactly resume"):
                train(changed, resume=str(root / "run" / "checkpoint.pt"))

    def test_a_split_too_small_for_one_batch_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = training_corpus(root, identities=1)
            config["training"]["batch_size"] = 4
            with self.assertRaises(ValueError):
                train(config)

    def test_unsupported_precision_optimizer_scheduler_and_tracker_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = training_corpus(root)
            for section, change, message in (
                    ("training", {"precision": "fp16"}, "precision must be"),
                    ("training", {"tracker": "wandb"}, "tracker must be"),
                    ("optimizer", {"name": "lion"}, "adamw"),
                    ("scheduler", {"name": "cosine"}, "constant")):
                config = copy.deepcopy(base)
                config[section] = {**config[section], **change}
                with self.assertRaisesRegex(ValueError, message):
                    train(config)

    def test_training_data_must_pass_the_same_leakage_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = training_corpus(root)
            config["dataset"]["allow_synthetic"] = False
            with self.assertRaisesRegex(ValueError, "Synthetic fixtures require"):
                train(config)


class TrainingConditionIsolationTests(unittest.TestCase):
    """The training condition must not depend on the template's own face pixels.

    Inference suppresses the native template before the crop is resized. Training has to use
    the same prepared crop, or interpolation spreads the target face into neighbouring pixels
    first and a falling loss stops being evidence that the child reference is being used.
    """

    def _dataset(self, root: Path, masked_value: float, resolution: int = 16):
        from PIL import Image
        from dreampage_headswap.data import PairDataset

        root.mkdir(parents=True, exist_ok=True)
        size = (64, 64)
        mask = np.zeros(size, np.uint8)
        mask[20:44, 18:46] = 255
        Image.fromarray(mask, mode="L").save(root / "mask.png")
        base = np.random.default_rng(5).integers(0, 255, (*size, 3), dtype=np.uint8)
        template = base.copy()
        template[mask > 0] = int(masked_value * 255)
        Image.fromarray(template).save(root / "template.png")
        truth = base.copy()
        truth[mask > 0] = 137
        Image.fromarray(truth).save(root / "truth.png")
        write_image(root / "source.png", 77, size)
        manifest = root / "pairs.train.jsonl"
        write_jsonl(manifest, [{"pair_id": "p1", "identity_id": "id_a", "split": "train",
                                "rights": rights(), "synthetic": True,
                                "source": str(root / "source.png"), "sources": [str(root / "source.png")],
                                "source_headmasks": [str(root / "mask.png")],
                                "template": str(root / "template.png"), "headmask": str(root / "mask.png"),
                                "ground_truth": str(root / "truth.png")}])
        return PairDataset(manifest, resolution=resolution, split="train", allow_synthetic=True)

    def test_prepared_condition_is_blind_to_the_templates_masked_pixels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dark = self._dataset(root / "dark", 0.1)[0]
            bright = self._dataset(root / "bright", 0.9)[0]
            self.assertFalse(torch.equal(dark["template"], bright["template"]))
            torch.testing.assert_close(dark["condition_template"], bright["condition_template"],
                                       rtol=0, atol=0)
            torch.testing.assert_close(dark["geometry_spatial"], bright["geometry_spatial"], rtol=0, atol=0)
            torch.testing.assert_close(dark["geometry_vector"], bright["geometry_vector"], rtol=0, atol=0)

    @staticmethod
    def _batch(item):
        return {key: value[None] if isinstance(value, torch.Tensor) else [value]
                for key, value in item.items()}

    def test_the_objective_feeds_the_model_the_prepared_crop(self):
        from torch import nn
        from dreampage_headswap.losses import LossSuite
        from dreampage_headswap.training import build_model
        from dreampage_headswap.training.loop import flow_objective

        class Recording(nn.Module):
            """Capture the exact template the objective hands to the model."""

            def __init__(self, inner):
                super().__init__()
                self.inner, self.backbone, self.seen = inner, inner.backbone, []

            def forward(self, sample, t, references, template, mask, geometry, age=None):
                self.seen.append(template.clone())
                return self.inner(sample, t, references, template, mask, geometry, age)

        with tempfile.TemporaryDirectory() as tmp:
            batch = self._batch(self._dataset(Path(tmp) / "one", 0.1)[0])
            model = Recording(build_model({"model": {"backbone": "tiny", "identity_dim": 32,
                                                     "structure_dim": 16, "width": 24}}))
            flow_objective(model, batch, LossSuite({"flow_matching": 1.0}), seed=3)
            self.assertEqual(len(model.seen), 1)
            torch.testing.assert_close(model.seen[0], batch["condition_template"], rtol=0, atol=0)
            self.assertFalse(torch.equal(model.seen[0], batch["template"]))

    def test_a_strategy_mismatch_between_dataset_and_trainer_is_refused(self):
        from dreampage_headswap.training.loop import condition_template as prepare

        with tempfile.TemporaryDirectory() as tmp:
            batch = self._batch(self._dataset(Path(tmp) / "one", 0.1)[0])
            mask = (batch["mask"] > 0).to(batch["template"])
            with self.assertRaisesRegex(ValueError, "same strategy"):
                prepare(batch, mask, "blur", 0)

    def test_a_batch_without_a_prepared_crop_still_suppresses(self):
        from dreampage_headswap.training.loop import condition_template as prepare
        from dreampage_headswap.training.overfit import synthetic_batch

        batch = synthetic_batch(resolution=16)
        mask = (batch["mask"] > 0).to(batch["template"])
        prepared = prepare(batch, mask, "neutral", 0)
        self.assertFalse(torch.equal(prepared, batch["template"]))
        self.assertEqual(len(torch.unique(prepared[0][:, mask[0, 0] > 0])), 3)


class ValidationTests(unittest.TestCase):
    """Periodic held-out validation, best-checkpoint selection and the dataset fingerprint."""

    def test_validation_runs_on_schedule_and_keeps_the_best_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = training_corpus(root, validation={"every": 2, "samples": True})
            result = train(config)
            self.assertEqual([row["step"] for row in result["validation_history"]], [2, 4])
            for row in result["validation_history"]:
                self.assertIn("validation/flow_matching", row)
                self.assertEqual(row["validation/pairs"], 1)
            self.assertEqual(result["best_metric"], "validation/total")

            scores = {row["step"]: row["validation/total"] for row in result["validation_history"]}
            best_step = min(scores, key=scores.get)
            self.assertEqual(result["best_score"], scores[best_step])
            best = state(Path(result["best_checkpoint"]))
            self.assertEqual(best["step"], best_step)
            self.assertEqual(best["metadata"]["best_score"], scores[best_step])
            self.assertEqual(best["metadata"]["best_metric"], "validation/total")
            self.assertIn("validation/total", best["metadata"]["validation"])
            self.assertFalse(result["quality_validated"])

            samples = sorted(path.parent.name for path in (root / "run" / "samples").rglob("sample.png"))
            self.assertEqual(samples, ["step_00000002", "step_00000004"])
            logged = [json.loads(line) for line in
                      Path(root, "run", "metrics.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len([row for row in logged if "validation/total" in row]), 2)

    def test_validation_does_not_disturb_exact_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = training_corpus(root, validation={"every": 2})

            straight = copy.deepcopy(config)
            straight["training"]["output_dir"] = str(root / "straight")
            train(straight)

            interrupted = copy.deepcopy(config)
            interrupted["training"]["output_dir"] = str(root / "interrupted")
            interrupted["training"]["checkpoint_every"] = 2
            interrupted["training"]["max_steps"] = 2
            train(interrupted)
            resumed = copy.deepcopy(interrupted)
            resumed["training"]["max_steps"] = 4
            train(resumed, resume=str(root / "interrupted" / "checkpoint.pt"))

            expected = state(root / "straight" / "checkpoint.pt")["model"]
            actual = state(root / "interrupted" / "checkpoint.pt")["model"]
            for name, tensor in expected.items():
                self.assertTrue(torch.equal(tensor, actual[name]), name)

    def test_a_resumed_run_keeps_the_earlier_best_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = training_corpus(root, validation={"every": 2})
            config["training"]["checkpoint_every"] = 2
            config["training"]["max_steps"] = 2
            first = train(config)
            resumed = copy.deepcopy(config)
            resumed["training"]["max_steps"] = 4
            second = train(resumed, resume=str(root / "run" / "checkpoint.pt"))
            self.assertLessEqual(second["best_score"], first["best_score"])
            self.assertEqual(state(Path(second["best_checkpoint"]))["metadata"]["best_score"],
                             second["best_score"])

    def test_an_unknown_validation_metric_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = training_corpus(Path(tmp), validation={"every": 2, "metric": "validation/identity"})
            with self.assertRaisesRegex(ValueError, "validation.metric"):
                train(config)

    def test_validation_without_a_held_out_split_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = training_corpus(root, validation={"every": 2, "split": "train"})
            with self.assertRaises(ValueError):
                train(config)

    def test_validation_identities_are_audited_against_training(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = training_corpus(root, validation={"every": 2})
            training_rows = read_jsonl(config["dataset"]["manifest"])
            leaked = dict(training_rows[0])
            leaked["split"] = "validation"
            leaked["pair_id"] = leaked["pair_id"] + "leak"
            write_jsonl(config["validation"]["manifest"], [leaked])
            with self.assertRaisesRegex(ValueError, "leakage"):
                train(config)

    def test_changed_image_bytes_block_a_claim_of_exact_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = training_corpus(root)
            config["training"]["checkpoint_every"] = 2
            config["training"]["max_steps"] = 2
            result = train(config)
            self.assertEqual(len(result["dataset_fingerprint"]), 64)

            edited = read_jsonl(config["dataset"]["manifest"])[0]["source"]
            write_image(Path(edited), 9999, (96, 96))
            resumed = copy.deepcopy(config)
            resumed["training"]["max_steps"] = 4
            with self.assertRaisesRegex(ValueError, "image bytes changed"):
                train(resumed, resume=str(root / "run" / "checkpoint.pt"))

    def test_the_fingerprint_can_be_switched_off_explicitly(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = training_corpus(Path(tmp))
            config["training"]["verify_dataset_fingerprint"] = False
            self.assertIsNone(train(config)["dataset_fingerprint"])

    def test_validation_keys_in_the_old_places_are_refused_rather_than_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = training_corpus(root, validation={"every": 2})
            misplaced = copy.deepcopy(base)
            misplaced["dataset"]["validation_manifest"] = misplaced["validation"]["manifest"]
            with self.assertRaisesRegex(ValueError, "moved into the top-level validation section"):
                train(misplaced)
            misplaced = copy.deepcopy(base)
            misplaced["training"]["validation_every"] = 2
            with self.assertRaisesRegex(ValueError, "validation.every"):
                train(misplaced)


class SyntheticFixtureScriptTests(unittest.TestCase):
    """The fixture script has to produce configs the shipped trainers actually accept."""

    def test_it_writes_runnable_configs_for_both_trainers(self):
        import contextlib
        import io
        import yaml
        from _fixtures import load_script
        from dreampage_headswap.training.identity import train_identity_encoder

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "fixture"
            script = load_script("make_synthetic_dataset")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(script.main(["--output-dir", str(root), "--identities", "8",
                                              "--captures", "2", "--resolution", "32"]), 0)
            self.assertTrue((root / "SYNTHETIC_FIXTURE.txt").is_file())
            self.assertTrue((root / "dataset_registry.json").is_file())

            flow = yaml.safe_load((root / "training_smoke.yaml").read_text(encoding="utf-8"))
            self.assertNotIn("validation_manifest", flow["dataset"])
            self.assertNotIn("validation_every", flow["training"])
            with contextlib.redirect_stdout(io.StringIO()):
                result = train(flow)
            self.assertTrue(result["validation_history"])
            self.assertTrue(result["best_checkpoint"])

            encoder = yaml.safe_load((root / "identity_smoke.yaml").read_text(encoding="utf-8"))
            self.assertTrue(encoder["dataset"]["source_crops"])
            self.assertGreaterEqual(encoder["objective"]["identities_per_batch"], 2)
            with contextlib.redirect_stdout(io.StringIO()):
                identity_result = train_identity_encoder(encoder)
            self.assertTrue(identity_result["validation_history"])
            self.assertFalse(identity_result["identity_quality_validated"])


if __name__ == "__main__":
    unittest.main()

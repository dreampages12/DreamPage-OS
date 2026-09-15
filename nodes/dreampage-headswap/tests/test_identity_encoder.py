"""The DreamFace encoder trainer, on its own objective and its own data path.

Procedural noise cannot say anything about faces. What is asserted here is that the objective
has negatives at all, that both views are framed the same way, that held-out identities are
never the identities it trained on, and that the run refuses to describe itself as validated.
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import torch

from _fixtures import identity_row, training_corpus
from dreampage_headswap.data import PairDataset, generate_pairs, load_identities
from dreampage_headswap.data.records import read_jsonl, write_jsonl
from dreampage_headswap.training.identity import (build_encoder, cross_view_objective, identity_batches,
                                                  retrieval_metrics, train_identity_encoder)


def encoder_config(root: Path, *, identities: int = 6, per_batch: int = 3, validation=True) -> dict:
    base = training_corpus(root, identities=identities, resolution=32, validation_identities=3,
                           validation={} if validation else None)
    config = {"model": {"identity_dim": 32, "structure_dim": 16, "token_grid": 2},
              "dataset": {**base["dataset"], "source_crops": True},
              "objective": {"name": "supervised_contrastive", "temperature": 0.1,
                            "identities_per_batch": per_batch},
              "optimizer": base["optimizer"], "scheduler": base["scheduler"],
              "training": {**base["training"], "max_steps": 4, "output_dir": str(root / "identity")}}
    if validation:
        config["validation"] = {"manifest": base["validation"]["manifest"], "split": "validation",
                                "every": 2, "seed": 4321, "identities_per_batch": 2, "max_batches": 2,
                                "metric": "validation/retrieval_top1"}
    return config


class SourceFramingTests(unittest.TestCase):
    def test_both_views_come_through_the_same_crop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = training_corpus(root, resolution=32)
            cropped = PairDataset(config["dataset"]["manifest"], resolution=32, split="train",
                                  allow_synthetic=True, source_crops=True)[0]
            resized = PairDataset(config["dataset"]["manifest"], resolution=32, split="train",
                                  allow_synthetic=True)[0]
            self.assertEqual(tuple(cropped["references"].shape), (1, 3, 32, 32))
            self.assertFalse(torch.equal(cropped["references"], resized["references"]))

    def test_source_crops_require_a_mask_for_every_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "ids.jsonl"
            write_jsonl(manifest, [identity_row(root, "a", 1, split="train", masked_from=1)])
            pairs = root / "pairs.train.jsonl"
            write_jsonl(pairs, generate_pairs(load_identities(manifest, allow_synthetic=True), seed=1))
            PairDataset(pairs, resolution=32, split="train", allow_synthetic=True)
            with self.assertRaisesRegex(ValueError, "headmask per source capture"):
                PairDataset(pairs, resolution=32, split="train", allow_synthetic=True, source_crops=True)

    def test_a_mask_list_that_does_not_match_the_sources_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = training_corpus(root)
            rows = read_jsonl(config["dataset"]["manifest"])
            rows[0]["source_headmasks"] = rows[0]["source_headmasks"] * 2
            write_jsonl(config["dataset"]["manifest"], rows)
            with self.assertRaisesRegex(ValueError, "one mask per source capture"):
                PairDataset(config["dataset"]["manifest"], resolution=32, split="train", allow_synthetic=True)


class BatchingTests(unittest.TestCase):
    def test_every_batch_holds_distinct_identities_and_repeats_deterministically(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = training_corpus(root, identities=6)
            dataset = PairDataset(config["dataset"]["manifest"], resolution=32, split="train",
                                  allow_synthetic=True, source_crops=True)
            batches = identity_batches(dataset, 3, seed=7, epoch=0)
            self.assertEqual(batches, identity_batches(dataset, 3, seed=7, epoch=0))
            self.assertNotEqual(batches, identity_batches(dataset, 3, seed=7, epoch=1))
            self.assertEqual(len(batches), 2)
            for batch in batches:
                names = [dataset.rows[index]["identity_id"] for index in batch]
                self.assertEqual(len(set(names)), 3)

    def test_a_batch_without_negatives_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = training_corpus(root, identities=4)
            dataset = PairDataset(config["dataset"]["manifest"], resolution=32, split="train",
                                  allow_synthetic=True, source_crops=True)
            with self.assertRaisesRegex(ValueError, "at least two distinct identities"):
                identity_batches(dataset, 1, seed=1, epoch=0)
            with self.assertRaisesRegex(ValueError, "identities_per_batch"):
                identity_batches(dataset, 9, seed=1, epoch=0)


class ObjectiveTests(unittest.TestCase):
    def test_retrieval_is_perfect_when_the_views_agree_and_chance_when_they_do_not(self):
        embeddings = torch.eye(4)
        perfect = retrieval_metrics(embeddings, embeddings, ["a", "b", "c", "d"])
        self.assertEqual(perfect["retrieval_top1"], 1.0)
        self.assertGreater(perfect["similarity_margin"], 0)
        swapped = retrieval_metrics(embeddings, embeddings.flip(0), ["a", "b", "c", "d"])
        self.assertEqual(swapped["retrieval_top1"], 0.0)

    def test_gradients_reach_the_encoder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = encoder_config(root, validation=False)
            dataset = PairDataset(config["dataset"]["manifest"], resolution=32, split="train",
                                  allow_synthetic=True, source_crops=True)
            indices = identity_batches(dataset, 3, seed=1, epoch=0)[0]
            from torch.utils.data import DataLoader, Subset
            batch = next(iter(DataLoader(Subset(dataset, indices), batch_size=len(indices))))
            encoder = build_encoder(config)
            loss, metrics = cross_view_objective(encoder, batch, 0.1)
            loss.backward()
            self.assertTrue(torch.isfinite(loss))
            self.assertIn("retrieval_top1", metrics)
            self.assertTrue(any(parameter.grad is not None and parameter.grad.abs().sum() > 0
                                for parameter in encoder.parameters()))


class EncoderTrainingTests(unittest.TestCase):
    def test_resume_in_middle_of_later_epoch_is_exact(self):
        from contextlib import redirect_stdout
        import io
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            root = Path(tmp)
            config = encoder_config(root, identities=6, per_batch=3, validation=False)
            config["training"].update(max_steps=5, output_dir=str(root / "straight"))
            full = train_identity_encoder(config)
            interrupted = copy.deepcopy(config)
            interrupted["training"].update(max_steps=3, output_dir=str(root / "interrupted"))
            part = train_identity_encoder(interrupted)
            interrupted["training"]["max_steps"] = 5
            resumed = train_identity_encoder(interrupted, resume=part["checkpoint"])
            expected = torch.load(full["checkpoint"], weights_only=False)["model"]
            actual = torch.load(resumed["checkpoint"], weights_only=False)["model"]
            self.assertTrue(all(torch.equal(value, actual[name]) for name, value in expected.items()))

    def test_encoder_checkpoint_initializes_dreamswap_and_can_be_frozen(self):
        from contextlib import redirect_stdout
        import io
        from dreampage_headswap.training.factory import build_model
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            config = encoder_config(Path(tmp), validation=False)
            result = train_identity_encoder(config)
            model = build_model({"backbone": "tiny", "identity_dim": 32, "structure_dim": 16,
                                 "token_grid": 2, "width": 24, "identity_checkpoint": result["checkpoint"],
                                 "freeze_encoder": True})
            saved = torch.load(result["checkpoint"], weights_only=False)["model"]
            self.assertTrue(all(torch.equal(value, model.encoder.state_dict()[name]) for name, value in saved.items()))
            self.assertTrue(all(not parameter.requires_grad for parameter in model.encoder.parameters()))

    def test_a_short_run_trains_validates_and_keeps_the_best_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = train_identity_encoder(encoder_config(root))
            self.assertEqual(result["step"], 4)
            self.assertEqual(len(result["loss_history"]), 4)
            self.assertTrue(result["source_crops"])
            self.assertEqual(result["identities_in_train_split"], 6)
            self.assertFalse(result["identity_quality_validated"])
            self.assertEqual([row["step"] for row in result["validation_history"]], [2, 4])
            self.assertIn("validation/retrieval_top1", result["validation_history"][0])
            best = torch.load(result["best_checkpoint"], map_location="cpu", weights_only=False)
            self.assertEqual(best["metadata"]["component"], "dreamface_encoder")
            self.assertEqual(best["metadata"]["best_metric"], "validation/retrieval_top1")
            self.assertEqual(best["metadata"]["best_score"], result["best_score"])
            self.assertEqual(len(best["metadata"]["dataset_fingerprint"]), 64)

    def test_the_best_checkpoint_tracks_the_highest_retrieval_not_the_lowest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = train_identity_encoder(encoder_config(root))
            scores = [row["validation/retrieval_top1"] for row in result["validation_history"]]
            self.assertEqual(result["best_score"], max(scores))

    def test_resume_continues_the_same_experiment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = encoder_config(root, validation=False)
            config["training"]["checkpoint_every"] = 2
            config["training"]["max_steps"] = 2
            train_identity_encoder(config)
            resumed = copy.deepcopy(config)
            resumed["training"]["max_steps"] = 4
            result = train_identity_encoder(resumed, resume=str(root / "identity" / "checkpoint.pt"))
            self.assertEqual(result["step"], 4)
            self.assertEqual(len(result["loss_history"]), 2)

            changed = copy.deepcopy(resumed)
            changed["objective"] = {**changed["objective"], "temperature": 0.5}
            with self.assertRaisesRegex(ValueError, "objective configuration changed"):
                train_identity_encoder(changed, resume=str(root / "identity" / "checkpoint.pt"))

    def test_an_unimplemented_objective_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = encoder_config(Path(tmp), validation=False)
            config["objective"] = {**config["objective"], "name": "arcface"}
            with self.assertRaisesRegex(ValueError, "supervised_contrastive"):
                train_identity_encoder(config)

    def test_validation_identities_are_disjoint_from_training(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = encoder_config(root)
            training_ids = {row["identity_id"] for row in read_jsonl(config["dataset"]["manifest"])}
            validation_ids = {row["identity_id"] for row in read_jsonl(config["validation"]["manifest"])}
            self.assertTrue(validation_ids)
            self.assertFalse(training_ids & validation_ids)

            leaked = dict(read_jsonl(config["dataset"]["manifest"])[0])
            leaked["split"] = "validation"
            leaked["pair_id"] = leaked["pair_id"] + "leak"
            write_jsonl(config["validation"]["manifest"], [leaked])
            with self.assertRaisesRegex(ValueError, "leakage"):
                train_identity_encoder(config)

    def test_metrics_are_logged_for_every_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            train_identity_encoder(encoder_config(root, validation=False))
            rows = [json.loads(line) for line in
                    Path(root, "identity", "metrics.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["step"] for row in rows], [1, 2, 3, 4])
            for row in rows:
                self.assertIn("contrastive", row)
                self.assertIn("retrieval_top1", row)


if __name__ == "__main__":
    unittest.main()

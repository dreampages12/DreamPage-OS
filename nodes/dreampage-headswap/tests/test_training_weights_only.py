"""Checkpoint-kontroller med testdobler. Ingen modeller eller optimeringssteg."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from dreampage_headswap.training import experiments
from dreampage_headswap.utils.checkpoint import initialize_weights
from dreampage_headswap.training.validation import dataset_fingerprint


class WeightsOnlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "parent.pt"
        self.path.write_bytes(b"trusted fixture; torch.load is mocked")
        self.config = {"model": {"identity_dim": 64}, "training": {
            "initialize_from": str(self.path), "initialize_sha256": experiments.sha256(self.path)}}
        self.state = {"format_version": 1, "step": 1, "config": copy.deepcopy(self.config),
                      "metadata": {"synthetic": False, "component": "dreamface_encoder", "training_identity_ids": ["ancestor"]},
                      "model": {"sentinel": "only this state is loaded"},
                      "optimizer": "must not be restored", "scheduler": "must not be restored", "rng": "must not be restored"}

    def test_only_model_weights_loaded(self):
        model = Mock()
        with patch("torch.load", return_value=self.state), patch("dreampage_headswap.utils.checkpoint.restore_rng", side_effect=AssertionError("RNG must remain fresh")):
            initialize_weights(model, self.config, component="identity")
        model.load_state_dict.assert_called_once_with(self.state["model"], strict=True)
        self.assertEqual(self.config["training"]["training_identity_lineage"], ["ancestor"])

    def test_resume_does_not_reinitialize(self):
        with patch("torch.load") as loader:
            initialize_weights(Mock(), self.config, component="identity", resume="current.pt")
        loader.assert_not_called()

    def test_all_trainers_refuse_before_gpu_or_optimizer(self):
        from dreampage_headswap.training.loop import train
        from dreampage_headswap.training.identity import train_identity_encoder
        from dreampage_headswap.training.refiner import train_refiner
        with patch("torch.cuda.set_device", side_effect=AssertionError("No GPU setup")), patch("torch.optim.AdamW", side_effect=AssertionError("No optimizer")):
            for trainer in (train, train_identity_encoder, train_refiner):
                with self.subTest(trainer=trainer.__name__), self.assertRaisesRegex(ValueError, "godkjenning"):
                    trainer(self.config)

    def test_synthetic_parent_rejected(self):
        self.state["metadata"]["synthetic"] = True
        with patch("torch.load", return_value=self.state), self.assertRaises(ValueError):
            initialize_weights(Mock(), self.config, component="identity")

    def test_architecture_change_rejected(self):
        self.config["model"]["identity_dim"] = 128
        with patch("torch.load", return_value=self.state), self.assertRaises(ValueError):
            initialize_weights(Mock(), self.config, component="identity")

    def test_changed_parent_refused_before_deserialization(self):
        self.path.write_bytes(b"changed")
        with patch("torch.load") as loader, self.assertRaises(ValueError):
            initialize_weights(Mock(), self.config, component="identity")
        loader.assert_not_called()

    def test_refiner_teacher_change_refused(self):
        self.state["metadata"].update(component="dreamrefine_system", teacher={"checkpoint_sha256": "old"})
        with patch("torch.load", return_value=self.state), self.assertRaises(ValueError):
            initialize_weights(Mock(), self.config, component="refiner", teacher_sha256="new")

    def test_fingerprint_portable_but_content_sensitive(self):
        from types import SimpleNamespace
        def dataset(folder):
            folder.mkdir()
            row = {"_manifest": str(folder / "pairs.jsonl"), "identity_id": "person", "split": "train"}
            for name in ("source", "template", "ground_truth", "headmask"):
                path = folder / name
                path.write_bytes(name.encode())
                row[name] = str(path)
            row["sources"] = [row["source"]]
            artifact = folder / "artifact.jsonl"
            artifact.write_bytes(b"same portable artifact manifest")
            row["generated"] = row["template"]
            row["refinement_artifact"] = {"generated": row["generated"], "artifact_manifest": str(artifact)}
            return SimpleNamespace(rows=[row])
        left = dataset(Path(self.temp.name) / "left")
        right = dataset(Path(self.temp.name) / "right")
        self.assertEqual(dataset_fingerprint(left), dataset_fingerprint(right))
        Path(right.rows[0]["source"]).write_bytes(b"changed")
        self.assertNotEqual(dataset_fingerprint(left), dataset_fingerprint(right))


if __name__ == "__main__":
    unittest.main()

"""Kun planlegging/godkjenningskontroll. Ingen modell, backward eller optimizer."""
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import sys
from types import SimpleNamespace
from unittest.mock import patch

from dreampage_headswap.training import experiments as ex
from dreampage_headswap.data.intake import inspect_intake


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.previous = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self.previous)
        self.data = self.root / "data"
        self.data.mkdir()
        rights = {"provenance": "unit-test metadata only", "license": "fixture", "consent": {
            "status": "granted", "reference": "test fixture, never trained", "training_permitted": True},
            "training_permitted": True, "commercial_use_permitted": True, "customer_data": False}
        for split in ("train", "validation"):
            row = {"pair_id": split, "identity_id": split + "_person", "split": split,
                   "synthetic": False, "rights": rights}
            for key in ("source", "template", "ground_truth", "headmask"):
                name = split + "_" + key + ".fixture"
                (self.data / name).write_bytes(name.encode())
                row[key] = name
            (self.data / f"{split}.jsonl").write_text(json.dumps(row) + "\n")
        self.registry()
        self.config = {"dataset": {"manifest": "data/train.jsonl", "allow_synthetic": False},
                       "validation": {"manifest": "data/validation.jsonl"},
                       "training": {"max_steps": 10}, "model": {"identity_dim": 64}}

    def registry(self):
        ex.write_json(self.data / "dataset_registry.json", {"schema_version": 1,
                      "scope": "complete_declared_enrolled_corpus", "manifests": [
                          {"path": p.name, "sha256": ex.sha256(p)} for p in sorted(self.data.glob("*.jsonl"))]})

    def approval(self, config=None):
        p = self.root / "approval.json"
        ex.write_json(p, {"approved": True, "photorealistic_only": True, "components": ["identity"],
                         "dataset_sha256": ex.dataset_snapshot(config or self.config)["sha256"],
                         "user_approval_reference": "Unit test receipt; dispatch is never called"})
        return p

    def plan(self, name="first", **kwargs):
        return ex.prepare_run(self.config, name, "identity", root=self.root, **kwargs)

    def parent(self):
        p = self.plan()
        (p / "model").mkdir()
        ckpt = p / "model/checkpoint.pt"
        ckpt.write_bytes(b"metadata-only fixture, not a model")
        run = json.loads((p / "run.json").read_text())
        run.update(approval={"approved": True}, checkpoints={ckpt.name: {"sha256": ex.sha256(ckpt)}})
        ex.write_json(p / "run.json", run)
        return ckpt

    def test_plan_never_approves_or_creates_model(self):
        p = self.plan()
        self.assertFalse(json.loads((p / "approval.request.json").read_text())["approved"])
        self.assertFalse((p / "model").exists())
        self.assertEqual(json.loads((p / "run.json").read_text())["status"], "awaiting_dataset_approval")

    def test_existing_run_is_immutable(self):
        p = self.plan()
        before = (p / "run.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.plan()
        self.assertEqual(before, (p / "run.json").read_bytes())

    def test_no_path_traversal(self):
        with self.assertRaises(ValueError):
            self.plan("../escape")

    def test_no_synthetic_training_plan(self):
        self.config["dataset"]["allow_synthetic"] = True
        with self.assertRaises(ValueError):
            self.plan()

    def test_missing_approval_refuses_before_dispatch(self):
        with self.assertRaises(ValueError):
            ex.authorize_training(self.config, "identity")

    def test_request_is_not_approval(self):
        p = self.plan()
        with self.assertRaises(ValueError):
            ex.execute_run(p, p / "approval.request.json")
        self.assertFalse((p / ".running.lock").exists())

    def test_changed_image_invalidates_approval(self):
        approval = self.approval()
        (self.data / "train_source.fixture").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "endret"):
            ex.require_approval(self.config, approval, "identity")

    def test_wrong_component_invalidates_approval(self):
        with self.assertRaises(ValueError):
            ex.require_approval(self.config, self.approval(), "swap")

    def test_changed_manifest_invalidates_registry(self):
        with (self.data / "train.jsonl").open("a") as f:
            f.write("\n")
        with self.assertRaisesRegex(ValueError, "Manifest"):
            ex.dataset_snapshot(self.config)

    def test_snapshot_survives_moved_root(self):
        before = ex.dataset_snapshot(self.config)
        relocated = self.root / "relocated"
        shutil.copytree(self.data, relocated / "data")
        os.chdir(relocated)
        self.assertEqual(before, ex.dataset_snapshot(self.config))

    def test_identity_leakage_refused(self):
        p = self.data / "validation.jsonl"
        row = json.loads(p.read_text())
        row["identity_id"] = "train_person"
        p.write_text(json.dumps(row))
        self.registry()
        with self.assertRaisesRegex(ValueError, "ulike splitter"):
            self.plan()

    def test_finetune_records_lineage(self):
        ckpt = self.parent()
        p = self.plan("child", mode="finetune", parent_checkpoint=ckpt)
        config = json.loads((p / "config.json").read_text())
        self.assertEqual(config["training"]["initialize_sha256"], ex.sha256(ckpt))
        self.assertEqual(config["training"]["training_identity_lineage"], ["train_person"])
        self.assertFalse((p / "model").exists())

    def test_finetune_rejects_parent_mutation(self):
        ckpt = self.parent()
        ckpt.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "endret"):
            self.plan("child", mode="finetune", parent_checkpoint=ckpt)

    def test_finetune_rejects_ancestor_train_in_validation(self):
        ckpt = self.parent()
        for split, identity in (("train", "new_person"), ("validation", "train_person")):
            p = self.data / f"{split}.jsonl"
            row = json.loads(p.read_text())
            row["identity_id"] = identity
            p.write_text(json.dumps(row))
        self.registry()
        with self.assertRaisesRegex(ValueError, "foreldermodellen"):
            self.plan("child", mode="finetune", parent_checkpoint=ckpt)

    def test_code_change_refuses_resume_before_dispatch(self):
        p = self.plan()
        with patch.object(ex, "source_snapshot", return_value={"sha256": "changed"}):
            with self.assertRaisesRegex(ValueError, "Treningskoden"):
                ex.execute_run(p, p / "approval.request.json", resume=True)

    def test_production_server_refused(self):
        osroot = self.root / "os"
        (osroot / "config").mkdir(parents=True)
        ex.write_json(osroot / "config/flow.json", {"server": {"role": "production"}})
        self.config["training"]["dataset_approval"] = str(self.approval())
        with patch.object(ex, "package_root", return_value=osroot / "nodes/headswap"):
            with self.assertRaisesRegex(ValueError, "production"):
                ex.authorize_training(self.config, "identity")

    def test_intake_preserves_originals_and_never_approves(self):
        from PIL import Image
        incoming = self.root / "incoming"
        incoming.mkdir()
        original = incoming / "photo.png"
        Image.new("RGB", (20, 30)).save(original)
        before = original.read_bytes()
        report = inspect_intake(incoming, self.root / "review")
        self.assertFalse(report["approved"])
        self.assertEqual(len(report["images"]), 1)
        self.assertEqual(original.read_bytes(), before)
        with self.assertRaises(FileExistsError):
            inspect_intake(incoming, self.root / "review")

    def test_intake_reports_corruption(self):
        incoming = self.root / "incoming"
        incoming.mkdir()
        (incoming / "bad.heic").write_bytes(b"not an image")
        report = inspect_intake(incoming, self.root / "review")
        self.assertEqual(len(report["errors"]), 1)
        self.assertFalse(report["approved"])

    def test_lifecycle_dispatch_with_fake_runner_no_training(self):
        p = self.plan()
        approval = self.approval()
        calls = []
        def fake_runner(config, resume):
            calls.append((copy.deepcopy(config), resume))
            (p / "model").mkdir(exist_ok=True)
            (p / "model/checkpoint.pt").write_bytes(b"fake runner, no tensors or optimizer")
            return {"step": config["training"]["max_steps"]}
        fake = SimpleNamespace(train_identity_encoder=fake_runner)
        # Kun dispatch-metadata testes. Ingen ekte trener importeres eller kjoeres.
        with patch.object(ex, "package_root", return_value=self.root), patch.object(ex, "source_snapshot", return_value=json.loads((p / "run.json").read_text())["source"]), patch.dict(sys.modules, {"dreampage_headswap.training.identity": fake}):
            self.assertEqual(ex.execute_run(p, approval)["status"], "completed")
            with self.assertRaises(ValueError):
                ex.execute_run(p, approval)
            ex.execute_run(p, approval, resume=True, max_steps=20)
            run = ex.execute_run(p, approval, resume=True)
        self.assertEqual([x[0]["training"]["max_steps"] for x in calls], [10, 20, 20])
        self.assertIsNone(calls[0][1])
        self.assertEqual(calls[1][1], str(p / "model/checkpoint.pt"))
        self.assertEqual(len(run["attempts"]), 3)
        self.assertFalse((p / ".running.lock").exists())
        self.assertFalse(run["quality_validated"])

    def test_recovery_refuses_live_process(self):
        import socket
        p = self.plan()
        ex.write_json(p / ".running.lock", {"pid": os.getpid(), "host": socket.gethostname()})
        with self.assertRaisesRegex(ValueError, "fortsatt"):
            ex.recover_run(p, "test", True)

    def test_recovery_records_operator_reason(self):
        p = self.plan()
        ex.write_json(p / ".running.lock", {"pid": 1, "host": "other-test-host"})
        with self.assertRaises(ValueError):
            ex.recover_run(p, "power failure")
        self.assertEqual(ex.recover_run(p, "power failure", True)["status"], "interrupted")
        self.assertFalse((p / ".running.lock").exists())


if __name__ == "__main__":
    unittest.main()

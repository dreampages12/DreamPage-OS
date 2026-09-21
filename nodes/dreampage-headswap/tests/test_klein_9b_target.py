"""9B-kontrakter uten innlasting av modellvekter, GPU eller optimalisering."""
import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest

from dreampage_headswap.model_target import (
    ARCHITECTURE, KLEIN_9B, KLEIN_BASE_9B, training_target, validate_snapshot_config, inspect_single_file,
)


class NineBTargetTests(unittest.TestCase):
    def test_standard_9b_accepted(self):
        training_target({"model": {"backbone": "flux_klein", "model_id": KLEIN_9B, "text_guidance_scale": 1.0}})
        validate_snapshot_config({"_class_name": "Flux2KleinPipeline", "is_distilled": True}, ARCHITECTURE, KLEIN_9B)

    def test_4b_target_rejected(self):
        with self.assertRaisesRegex(ValueError, "9B"):
            training_target({"model": {"backbone": "flux_klein", "model_id": "black-forest-labs/FLUX.2-klein-base-4B"}})

    def test_missing_target_rejected(self):
        with self.assertRaises(ValueError):
            training_target({"model": {"backbone": "flux_klein"}})

    def test_tiny_cannot_replace_real_training_target(self):
        with self.assertRaises(ValueError):
            training_target({"model": {"backbone": "tiny", "model_id": KLEIN_9B}})

    def test_independent_identity_model_is_not_misclassified(self):
        training_target({"model": {"identity_dim": 64}}, "identity")

    def test_9b_base_requires_explicit_variant(self):
        index = {"_class_name": "Flux2KleinPipeline", "is_distilled": False}
        with self.assertRaises(ValueError):
            validate_snapshot_config(index, ARCHITECTURE, KLEIN_9B)
        validate_snapshot_config(index, ARCHITECTURE, KLEIN_BASE_9B)

    def test_missing_variant_not_guessed(self):
        with self.assertRaises(ValueError):
            validate_snapshot_config({"_class_name": "Flux2KleinPipeline"}, ARCHITECTURE, KLEIN_9B)

    def test_every_9b_dimension_is_checked(self):
        for key in ARCHITECTURE:
            broken = {**ARCHITECTURE, key: -1}
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_snapshot_config({"_class_name": "Flux2KleinPipeline", "is_distilled": True}, broken, KLEIN_9B)

    def test_distilled_rejects_base_cfg(self):
        with self.assertRaises(ValueError):
            training_target({"model": {"backbone": "flux_klein", "model_id": KLEIN_9B, "text_guidance_scale": 4.0}})

    def test_single_file_header_does_not_claim_source_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "header_only.safetensors"
            header = {f"double_blocks.{i}.stub": {} for i in range(8)}
            header.update({f"single_blocks.{i}.stub": {} for i in range(24)})
            for key, shape in {"img_in.weight": [4096, 128], "txt_in.weight": [4096, 12288],
                               "double_blocks.7.img_attn.qkv.weight": [12288, 4096],
                               "single_blocks.23.linear1.weight": [36864, 4096]}.items():
                header[key] = {"shape": shape, "dtype": "BF16"}
            def write():
                raw = json.dumps(header).encode()
                p.write_bytes(struct.pack("<Q", len(raw)) + raw)
            write()
            report = inspect_single_file(p)
            self.assertTrue(report["architecture_verified"])
            self.assertFalse(report["variant_provenance_verified"])
            header["txt_in.weight"]["shape"] = [3072, 7680]
            write()
            with self.assertRaises(ValueError):
                inspect_single_file(p)

    def test_invalid_header_length_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "bad.safetensors"
            p.write_bytes(struct.pack("<Q", 2**40))
            with self.assertRaises(ValueError):
                inspect_single_file(p)

    def test_4b_plan_refused_before_reading_dataset(self):
        from dreampage_headswap.training.experiments import prepare_run
        with self.assertRaisesRegex(ValueError, "9B"):
            prepare_run({"model": {"backbone": "flux_klein", "model_id": "4b"}}, "rejected", "swap")

    def test_installed_pilot_matches_os_target(self):
        import yaml
        root = Path(__file__).resolve().parents[1]
        config = yaml.safe_load((root / "configs/training/flux_klein_9b_photoreal_pilot.yaml").read_text())
        training_target(config)
        self.assertEqual(config["model"]["model_id"], KLEIN_9B)
        self.assertEqual(config["validation"]["sampling_steps"], 4)


class DistilledPromptTests(unittest.TestCase):
    def test_distilled_prompt_cache_avoids_negative_text_encoder(self):
        from types import SimpleNamespace
        import torch
        from dreampage_headswap.backbones.flux_klein import FluxKleinBackbone
        # Smaa CPU-testdobler; ingen ekte transformer eller treningssteg.
        transformer = torch.nn.Linear(2, 2)
        transformer.config = SimpleNamespace(in_channels=128, joint_attention_dim=12288)
        pipeline = SimpleNamespace(config=SimpleNamespace(is_distilled=True), transformer=transformer,
                                   vae=torch.nn.Linear(2, 2), text_encoder=None, vae_scale_factor=8)
        embeddings = torch.zeros(1, 2, 12288)
        model = FluxKleinBackbone(pipeline, prompt_embeddings=embeddings, text_guidance_scale=1.0)
        self.assertTrue(model.is_distilled)
        self.assertTrue(torch.equal(model.prompt_embeddings, model.negative_prompt_embeddings))
        self.assertFalse(model.prompt_embeddings.requires_grad)
        with self.assertRaises(ValueError):
            FluxKleinBackbone(pipeline, prompt_embeddings=embeddings, text_guidance_scale=4.0)


class SnapshotLoadingTests(unittest.TestCase):
    def setUp(self):
        import hashlib
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        config_files = {"model_index.json": {"_class_name": "Flux2KleinPipeline", "is_distilled": True},
                        "transformer/config.json": ARCHITECTURE, "scheduler/scheduler_config.json": {},
                        "vae/config.json": {}, "text_encoder/config.json": {}}
        for name, value in config_files.items():
            p = self.path / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(value))
        for name in ("transformer/model.safetensors", "vae/model.safetensors", "text_encoder/model.safetensors"):
            (self.path / name).write_bytes(b"mock loader test; never deserialized")
        self.receipt = {"model_id": KLEIN_9B, "revision": "test", "license": "fixture", "commercial_use_reviewed": True,
                        "files": [{"path": p.relative_to(self.path).as_posix(), "bytes": p.stat().st_size,
                                   "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in self.path.rglob("*") if p.is_file()]}
        (self.path / "dreampage_provenance.json").write_text(json.dumps(self.receipt))

    def fake_pipeline(self):
        import torch
        from types import SimpleNamespace
        class Transformer(torch.nn.Linear):
            def forward(self, hidden_states, encoder_hidden_states, timestep, img_ids, txt_ids):
                raise AssertionError("No forward allowed in a loading test")
            def enable_gradient_checkpointing(self):
                self.checkpointing_enabled = True
        transformer = Transformer(2, 2)
        transformer.config = SimpleNamespace(in_channels=128, joint_attention_dim=12288)
        return SimpleNamespace(config=SimpleNamespace(is_distilled=True), transformer=transformer,
                               vae=torch.nn.Linear(2, 2), text_encoder=None, vae_scale_factor=8)

    def test_snapshot_uses_local_only_and_default_distilled_guidance(self):
        import sys
        import torch
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from dreampage_headswap.backbones.flux_klein import FluxKleinBackbone
        pipe = self.fake_pipeline()
        loader = Mock(return_value=pipe)
        fake = SimpleNamespace(Flux2KleinPipeline=SimpleNamespace(from_pretrained=loader))
        with patch.dict(sys.modules, {"diffusers": fake}):
            model = FluxKleinBackbone.from_local_pretrained(self.path, device="cpu", dtype=torch.float32,
                       prompt_embeddings=torch.zeros(1, 2, 12288))
        self.assertEqual(model.text_guidance_scale, 1.0)
        self.assertTrue(loader.call_args.kwargs["local_files_only"])
        self.assertTrue(pipe.transformer.checkpointing_enabled)

    def test_external_transformer_is_passed_to_supported_single_file_loader(self):
        import sys
        import torch
        import hashlib
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from dreampage_headswap.backbones.flux_klein import FluxKleinBackbone
        external = self.path / "external.safetensors"
        external.write_bytes(b"mocked header, no tensors")
        self.receipt["transformer_source"] = {"sha256": hashlib.sha256(external.read_bytes()).hexdigest()}
        (self.path / "dreampage_provenance.json").write_text(json.dumps(self.receipt))
        pipe = self.fake_pipeline()
        loader, single = Mock(return_value=pipe), Mock(return_value=pipe.transformer)
        fake = SimpleNamespace(Flux2KleinPipeline=SimpleNamespace(from_pretrained=loader),
                               Flux2Transformer2DModel=SimpleNamespace(from_single_file=single))
        with patch.dict(sys.modules, {"diffusers": fake}), patch("dreampage_headswap.backbones.flux_klein.inspect_single_file"):
            FluxKleinBackbone.from_local_pretrained(self.path, device="cpu", dtype=torch.float32,
                transformer_checkpoint=str(external), prompt_embeddings=torch.zeros(1, 2, 12288))
        self.assertEqual(single.call_args.kwargs["config"], str(self.path))
        self.assertEqual(single.call_args.kwargs["subfolder"], "transformer")
        self.assertTrue(single.call_args.kwargs["local_files_only"])
        self.assertIs(loader.call_args.kwargs["transformer"], pipe.transformer)

    def test_corrupted_component_refused_before_pipeline_loading(self):
        from dreampage_headswap.backbones.flux_klein import FluxKleinBackbone
        (self.path / "vae/model.safetensors").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "endret"):
            FluxKleinBackbone.from_local_pretrained(self.path, device="cpu")


if __name__ == "__main__":
    unittest.main()

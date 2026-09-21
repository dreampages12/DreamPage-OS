"""Model mechanics: forward, backward, sampling, losses and checkpoints.

Everything here runs on the tiny CPU backbone with random weights. It shows that the training
and sampling machinery is wired correctly. It says nothing about identity or realism.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import torch

from dreampage_headswap.dreamrefine import DreamRefine
from dreampage_headswap.geometry import MaskContextGeometry
from dreampage_headswap.losses import LossSuite
from dreampage_headswap.training import build_model
from dreampage_headswap.training.loop import flow_objective, make_optimizer, make_scheduler
from dreampage_headswap.training.overfit import run_overfit, synthetic_batch
from dreampage_headswap.utils.checkpoint import load_checkpoint, save_checkpoint, seed_everything

CONFIG = {"model": {"backbone": "tiny", "identity_dim": 32, "structure_dim": 16, "width": 24},
          "optimizer": {"name": "adamw", "lr": 0.002, "weight_decay": 0.0},
          "scheduler": {"name": "constant", "warmup_steps": 2},
          "losses": {"flow_matching": 1.0, "reconstruction": 0.2},
          "training": {"seed": 1234, "batch_size": 2, "accumulation_steps": 1, "precision": "fp32"},
          "dataset": {"synthetic": True, "resolution": 16}}


def fresh_model(config=None):
    seed_everything(1234)
    return build_model(config or CONFIG)


def sampling_inputs(resolution=16, batch=1, references=2):
    template = torch.rand(batch, 3, resolution, resolution)
    mask = torch.zeros(batch, 1, resolution, resolution)
    mask[..., 4:12, 5:13] = 1.0
    geometry = MaskContextGeometry().extract(template, mask)
    return torch.rand(batch, references, 3, resolution, resolution), template, mask, geometry


class ForwardBackwardTests(unittest.TestCase):
    def test_velocity_has_the_latent_shape(self):
        model = fresh_model()
        batch = synthetic_batch(resolution=16)
        latents = model.backbone.encode_images(batch["target"])
        velocity = model(latents, torch.rand(2), batch["references"], batch["template"],
                         batch["mask"], MaskContextGeometry().extract(batch["template"], batch["mask"]))
        self.assertEqual(velocity.shape, latents.shape)
        self.assertTrue(torch.isfinite(velocity).all())

    def test_gradients_reach_the_encoder_and_the_identity_adapter(self):
        model = fresh_model()
        loss, metrics = flow_objective(model, synthetic_batch(resolution=16),
                                       LossSuite(CONFIG["losses"]), seed=5)
        loss.backward()
        checked = 0
        for name, parameter in model.named_parameters():
            if "encoder." in name or "identity_adapter" in name:
                self.assertIsNotNone(parameter.grad, name)
                checked += 1
        self.assertGreater(checked, 4)
        self.assertTrue(any(p.grad.abs().sum() > 0 for n, p in model.named_parameters() if "encoder." in n))
        self.assertTrue(any(p.grad.abs().sum() > 0 for n, p in model.named_parameters() if "identity_adapter" in n))
        self.assertIn("flow_matching", metrics)
        self.assertIn("reconstruction", metrics)

    def test_optimizer_step_changes_parameters_and_scheduler_warms_up(self):
        model = fresh_model()
        optimizer = make_optimizer(model, CONFIG)
        scheduler = make_scheduler(optimizer, CONFIG)
        before = [parameter.detach().clone() for parameter in model.parameters()]
        self.assertAlmostEqual(optimizer.param_groups[0]["lr"], 0.002 * 0.5, places=9)
        for _ in range(2):
            optimizer.zero_grad(set_to_none=True)
            flow_objective(model, synthetic_batch(resolution=16), LossSuite(CONFIG["losses"]))[0].backward()
            optimizer.step()
            scheduler.step()
        self.assertAlmostEqual(optimizer.param_groups[0]["lr"], 0.002, places=9)
        self.assertTrue(any(not torch.equal(a, b) for a, b in zip(before, model.parameters())))


class SamplingTests(unittest.TestCase):
    def test_protected_pixels_survive_sampling_exactly(self):
        model = fresh_model()
        references, template, mask, geometry = sampling_inputs()
        generated = model.sample(references, template, mask, geometry, steps=3, seed=11)
        self.assertEqual(generated.shape, template.shape)
        protected = mask.expand_as(template) == 0
        self.assertTrue(torch.equal(generated[protected], template[protected]))
        self.assertFalse(torch.equal(generated, template))

    def test_sampling_is_seed_deterministic(self):
        model = fresh_model()
        references, template, mask, geometry = sampling_inputs()
        first = model.sample(references, template, mask, geometry, steps=3, seed=4)
        again = model.sample(references, template, mask, geometry, steps=3, seed=4)
        other = model.sample(references, template, mask, geometry, steps=3, seed=5)
        self.assertTrue(torch.equal(first, again))
        self.assertFalse(torch.equal(first, other))

    def test_empty_mask_returns_the_template_untouched(self):
        model = fresh_model()
        references, template, _, geometry = sampling_inputs()
        empty = torch.zeros(1, 1, 16, 16)
        self.assertTrue(torch.equal(model.sample(references, template, empty, geometry, steps=2), template))

    def test_invalid_sampling_arguments_are_rejected(self):
        model = fresh_model()
        references, template, mask, geometry = sampling_inputs()
        with self.assertRaises(ValueError):
            model.sample(references, template, mask, geometry, steps=0)
        with self.assertRaises(ValueError):
            model.sample(references, template, mask, geometry, steps=2, identity_strength=9.0)
        with self.assertRaises(ValueError):
            model.sample(references, template, torch.zeros(1, 1, 8, 8), geometry, steps=2)

    def test_model_stays_in_its_original_training_mode(self):
        model = fresh_model()
        model.train()
        references, template, mask, geometry = sampling_inputs()
        model.sample(references, template, mask, geometry, steps=2)
        self.assertTrue(model.training)

    def test_refiner_starts_as_an_identity_and_stays_inside_the_mask(self):
        model = fresh_model()
        references, template, mask, geometry = sampling_inputs()
        generated = model.sample(references, template, mask, geometry, steps=2, seed=1)
        refiner = DreamRefine(identity_dim=32, structure_dim=16, width=16).eval()
        with torch.inference_mode():
            identity = model.encoder(references)
            refined = refiner(generated, template, mask, identity)
        self.assertTrue(torch.allclose(refined, generated, atol=1e-6))


class LossSuiteTests(unittest.TestCase):
    def test_unavailable_estimators_cannot_be_enabled_without_a_provider(self):
        with self.assertRaisesRegex(ValueError, "licensed frozen differentiable estimator"):
            LossSuite({"flow_matching": 1.0, "global_identity": 1.0})
        LossSuite({"flow_matching": 1.0, "global_identity": 0.0})

    def test_unknown_negative_or_all_zero_weights_are_rejected(self):
        for weights in ({"flow_matching": 1.0, "made_up": 1.0}, {"flow_matching": -1.0},
                        {"flow_matching": 0.0, "reconstruction": 0.0}):
            with self.assertRaises(ValueError):
                LossSuite(weights)

    def test_flow_only_objective_skips_image_decoding(self):
        self.assertFalse(LossSuite({"flow_matching": 1.0}).needs_images)
        self.assertTrue(LossSuite({"flow_matching": 1.0, "outside_mask": 1.0}).needs_images)


class CheckpointTests(unittest.TestCase):
    def test_round_trip_restores_model_optimizer_and_scheduler(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.pt"
            model = fresh_model()
            optimizer = make_optimizer(model, CONFIG)
            scheduler = make_scheduler(optimizer, CONFIG)
            optimizer.zero_grad(set_to_none=True)
            flow_objective(model, synthetic_batch(resolution=16), LossSuite(CONFIG["losses"]))[0].backward()
            optimizer.step()
            scheduler.step()
            save_checkpoint(path, model, optimizer, scheduler, config=CONFIG, step=7, data_cursor=14,
                            metadata={"world_size": 1})

            restored = build_model(CONFIG)
            restored_optimizer = make_optimizer(restored, CONFIG)
            restored_scheduler = make_scheduler(restored_optimizer, CONFIG)
            state = load_checkpoint(path, restored, restored_optimizer, restored_scheduler,
                                    expected_config=CONFIG)
            self.assertEqual((state["step"], state["data_cursor"]), (7, 14))
            self.assertEqual(state["quality_claim"][:8], "Research")
            for (name, original), (_, loaded) in zip(model.state_dict().items(), restored.state_dict().items()):
                self.assertTrue(torch.equal(original, loaded), name)
            self.assertEqual(restored_scheduler.last_epoch, scheduler.last_epoch)
            self.assertAlmostEqual(restored_optimizer.param_groups[0]["lr"],
                                   optimizer.param_groups[0]["lr"], places=9)

    def test_changed_configuration_cannot_claim_an_exact_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.pt"
            model = fresh_model()
            save_checkpoint(path, model, config=CONFIG, step=1)
            for section, change in (("losses", {"flow_matching": 1.0}),
                                    ("dataset", {"synthetic": True, "resolution": 32})):
                changed = {**CONFIG, section: change}
                with self.assertRaisesRegex(ValueError, "Cannot exactly resume"):
                    load_checkpoint(path, build_model(CONFIG), expected_config=changed)
            changed_seed = {**CONFIG, "training": {**CONFIG["training"], "seed": 99}}
            with self.assertRaisesRegex(ValueError, "training.seed"):
                load_checkpoint(path, build_model(CONFIG), expected_config=changed_seed)

    def test_architecture_mismatch_is_rejected_rather_than_partially_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.pt"
            save_checkpoint(path, fresh_model(), config=CONFIG, step=1)
            wider = {**CONFIG, "model": {**CONFIG["model"], "width": 32}}
            with self.assertRaises(RuntimeError):
                load_checkpoint(path, build_model(wider))

    def test_rng_state_is_restored_so_a_resumed_run_continues_the_same_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.pt"
            seed_everything(99)
            save_checkpoint(path, fresh_model(), config=CONFIG, step=1)
            expected = torch.rand(4)
            load_checkpoint(path, build_model(CONFIG), restore_random=True)
            self.assertTrue(torch.equal(torch.rand(4), expected))


class BackboneFactoryTests(unittest.TestCase):
    def test_flux_backbone_refuses_to_load_without_a_reviewed_local_snapshot(self):
        with self.assertRaisesRegex(ValueError, "weights_path"):
            build_model({"model": {"backbone": "flux_klein", "model_id": "black-forest-labs/FLUX.2-klein-9B"}})

    def test_unknown_backbone_is_rejected(self):
        with self.assertRaises(ValueError):
            build_model({"model": {"backbone": "some_vendor"}})


class OverfitTests(unittest.TestCase):
    def test_synthetic_overfit_reduces_loss_and_records_its_own_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_overfit(output=tmp, steps=60, seed=1234, resolution=16, assert_improvement=False)
            self.assertLess(report["final_loss"], report["initial_loss"])
            self.assertFalse(report["identity_quality_validated"])
            self.assertTrue(Path(tmp, "checkpoint.pt").is_file())
            self.assertTrue(Path(tmp, "metrics.jsonl").is_file())
            self.assertEqual(len(Path(tmp, "metrics.jsonl").read_text(encoding="utf-8").strip().splitlines()), 60)


if __name__ == "__main__":
    unittest.main()

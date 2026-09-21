"""Optional real Diffusers contract tests. No model weights or network requests.

These instantiate real, randomly initialized small Flux2/Qwen3/AutoencoderKLFlux2
modules. They verify adapter mechanics, not BASE 4B weights or face quality.
Run the evidence writer: .venv-flux-test/Scripts/python scripts/verify_flux_contract.py
"""
from __future__ import annotations

import importlib.metadata
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from dreampage_headswap.backbones.flux_klein import FluxKleinBackbone
from dreampage_headswap.model_target import ARCHITECTURE, KLEIN_BASE_9B
from dreampage_headswap.dreamface import DreamFaceEncoder
from dreampage_headswap.types import GeometryCondition, SwapCondition

CONTRACT_EVIDENCE = {}
REQUIRED_DIFFUSERS = (0, 36)
FLUX2_SYMBOLS = ("AutoencoderKLFlux2", "Flux2KleinPipeline", "Flux2Transformer2DModel")


def flux2_support() -> tuple[bool, str]:
    """Report whether the real FLUX.2 classes exist here, and say why when they do not.

    The version gate runs before any import, so the ComfyUI environment pays nothing and
    is told precisely what it lacks instead of failing eight tests inside setUp.
    """
    if importlib.util.find_spec("diffusers") is None:
        return False, "Diffusers is not installed"
    try:
        installed = importlib.metadata.version("diffusers")
    except importlib.metadata.PackageNotFoundError:
        return False, "Diffusers version could not be determined"
    numbers = tuple(int(part) for part in installed.split(".")[:2] if part.isdigit())
    if numbers < REQUIRED_DIFFUSERS:
        return False, (f"Diffusers {installed} predates the FLUX.2 classes; "
                       f"{'.'.join(map(str, REQUIRED_DIFFUSERS))} or newer is required")
    import diffusers
    missing = [name for name in FLUX2_SYMBOLS if not hasattr(diffusers, name)]
    if missing:
        return False, f"Diffusers {installed} does not expose {', '.join(missing)}"
    if importlib.util.find_spec("transformers") is None or importlib.util.find_spec("tokenizers") is None:
        return False, "Transformers and tokenizers are required for the Qwen3 prompt path"
    return True, f"Diffusers {installed}"


FLUX2_AVAILABLE, FLUX2_REASON = flux2_support()


def make_real_tiny_pipeline():
    from diffusers import AutoencoderKLFlux2, Flux2KleinPipeline, Flux2Transformer2DModel, FlowMatchEulerDiscreteScheduler
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from transformers import Qwen2TokenizerFast, Qwen3Config, Qwen3ForCausalLM

    torch.manual_seed(2718)
    transformer = Flux2Transformer2DModel(in_channels=16, out_channels=16, num_layers=1,
        num_single_layers=1, attention_head_dim=16, num_attention_heads=2, joint_attention_dim=96,
        timestep_guidance_channels=16, mlp_ratio=2, axes_dims_rope=(4, 4, 4, 4), guidance_embeds=False)
    vae = AutoencoderKLFlux2(down_block_types=("DownEncoderBlock2D", "DownEncoderBlock2D"),
        up_block_types=("UpDecoderBlock2D", "UpDecoderBlock2D"), block_out_channels=(16, 16),
        layers_per_block=1, latent_channels=4, norm_num_groups=8, sample_size=16,
        mid_block_add_attention=False)
    # Nontrivial stats catch omitted/reversed patch-channel BN normalization.
    with torch.no_grad():
        vae.bn.running_mean.copy_(torch.linspace(-0.3, 0.3, 16))
        vae.bn.running_var.copy_(torch.linspace(0.6, 1.4, 16))
    qwen = Qwen3ForCausalLM(Qwen3Config(vocab_size=32, hidden_size=32, intermediate_size=48,
        num_hidden_layers=28, num_attention_heads=4, num_key_value_heads=2, head_dim=8,
        max_position_embeddings=64, pad_token_id=0, eos_token_id=2, use_cache=False))
    # A locally constructed toy vocabulary runs the actual Qwen3 hidden-layer
    # extraction. It provides no learned semantic/text capability.
    vocab = {word: index for index, word in enumerate([
        "<pad>", "<unk>", "<eos>", "Realistic", "head", "identity", "template", "pose", "lighting", "."])}
    tokenization = Tokenizer(WordLevel(vocab, unk_token="<unk>"))
    tokenization.pre_tokenizer = Whitespace()
    tokenizer = Qwen2TokenizerFast(tokenizer_object=tokenization, unk_token="<unk>",
                                  pad_token="<pad>", eos_token="<eos>")
    tokenizer.chat_template = "{{ messages[0]['content'] }} <eos>"
    scheduler = FlowMatchEulerDiscreteScheduler(use_dynamic_shifting=True)
    return Flux2KleinPipeline(scheduler=scheduler, vae=vae, text_encoder=qwen,
                              tokenizer=tokenizer, transformer=transformer, is_distilled=False)


def make_condition(encoder, *, dtype=torch.float32, device="cpu", batch_size=2):
    generator = torch.Generator().manual_seed(31415)
    references = torch.rand(batch_size, 2, 3, 16, 16, generator=generator).to(device=device, dtype=dtype)
    template = torch.rand(batch_size, 3, 16, 16, generator=generator).to(device=device, dtype=dtype)
    mask = torch.zeros(batch_size, 1, 16, 16, device=device, dtype=dtype)
    mask[:, :, 4:12, 4:12] = 1
    template = torch.where(mask > 0, 0.5, template)
    geometry = GeometryCondition(torch.zeros(batch_size, 4, 16, 16, device=device, dtype=dtype),
                                 torch.zeros(batch_size, 16, device=device, dtype=dtype))
    return SwapCondition(encoder(references), template, mask, geometry, torch.full((batch_size,), -1., device=device))


class FluxLoadingContractTests(unittest.TestCase):
    def snapshot(self, directory, *, distilled=None):
        folder = Path(directory)
        (folder / "transformer").mkdir()
        index = {"_class_name": "Flux2KleinPipeline"}
        if distilled is not None:
            index["is_distilled"] = distilled
        (folder / "model_index.json").write_text(json.dumps(index))
        (folder / "transformer" / "config.json").write_text(json.dumps(ARCHITECTURE))
        return folder

    def test_explicit_9b_requires_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = self.snapshot(directory, distilled=True)
            with self.assertRaisesRegex(ValueError, "dreampage_provenance"):
                FluxKleinBackbone.from_local_pretrained(folder)

    def test_distilled_snapshot_refused_for_explicit_base_target(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = self.snapshot(directory, distilled=True)
            with self.assertRaisesRegex(ValueError, "is_distilled"):
                FluxKleinBackbone.from_local_pretrained(folder, model_id=KLEIN_BASE_9B)


@unittest.skipUnless(FLUX2_AVAILABLE, FLUX2_REASON + "; run the isolated FLUX contract environment")
class RealFluxContractTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)
        self.pipeline = make_real_tiny_pipeline()
        self.backbone = FluxKleinBackbone(self.pipeline, identity_dim=16, structure_dim=8,
                                          adapter_width=16, prompt_max_sequence_length=16, text_guidance_scale=4.0)
        self.encoder = DreamFaceEncoder(dim=16, structure_dim=8, token_grid=2)

    def test_real_qwen3_prompt_extraction(self):
        self.assertEqual(self.backbone.prompt_embeddings.shape, (1, 16, 96))
        self.assertFalse(torch.equal(self.backbone.prompt_embeddings, self.backbone.negative_prompt_embeddings))
        self.assertFalse(self.backbone.prompt_embeddings.requires_grad)
        CONTRACT_EVIDENCE["qwen3_hidden_layers"] = [9, 18, 27]
        CONTRACT_EVIDENCE["prompt_embedding_shape"] = list(self.backbone.prompt_embeddings.shape)

    def test_real_vae_encoding_matches_upstream_and_decode_is_differentiable(self):
        image = torch.rand(2, 3, 16, 16, requires_grad=True)
        latents = self.backbone.encode_images(image)
        upstream = self.pipeline._encode_vae_image(image*2-1, generator=None)
        torch.testing.assert_close(latents, upstream, rtol=0, atol=0)
        self.assertEqual(latents.shape, (2, 16, 4, 4))
        packed = self.pipeline._pack_latents(latents)
        ids = self.pipeline._prepare_latent_ids(latents)
        unpacked = self.pipeline._unpack_latents_with_ids(packed, ids)
        torch.testing.assert_close(unpacked, latents, rtol=0, atol=0)
        decoded = self.backbone.decode_latents(latents)
        self.assertEqual(decoded.shape, image.shape)
        decoded.square().mean().backward()
        self.assertGreater(image.grad.abs().sum().item(), 0)
        self.assertTrue(all(parameter.grad is None for parameter in self.backbone.vae.parameters()))
        CONTRACT_EVIDENCE["vae_encode_matches_upstream_exactly"] = True
        CONTRACT_EVIDENCE["latent_shape"] = list(latents.shape)
        CONTRACT_EVIDENCE["vae_input_gradient_l1"] = image.grad.abs().sum().item()

    def test_actual_transformer_gradients_reach_identity_with_frozen_checkpointed_weights(self):
        self.backbone.transformer.enable_gradient_checkpointing()
        self.backbone.train()
        condition = make_condition(self.encoder)
        sample = torch.randn(2, 16, 4, 4, requires_grad=True)
        times = torch.tensor([0.25, 0.75])
        with patch.object(self.backbone.transformer, "_gradient_checkpointing_func",
                          wraps=self.backbone.transformer._gradient_checkpointing_func) as checkpoint_call:
            prediction = self.backbone.predict_velocity(sample, times, condition)
            loss = (prediction - torch.randn_like(prediction)).square().mean()
            loss.backward()
            self.assertGreater(checkpoint_call.call_count, 0)
        self.assertEqual(prediction.shape, sample.shape)
        for label, module in (("encoder", self.encoder), ("identity_attention", self.backbone.identity_adapter),
                              ("identity_context", self.backbone.identity_context), ("latent_adapter", self.backbone.latent_output)):
            gradient = sum(parameter.grad.abs().sum().item() for parameter in module.parameters() if parameter.grad is not None)
            self.assertGreater(gradient, 0, label)
            CONTRACT_EVIDENCE[label + "_gradient_l1"] = gradient
        self.assertGreater(sample.grad.abs().sum().item(), 0)
        self.assertTrue(all(parameter.grad is None for parameter in self.backbone.transformer.parameters()))
        CONTRACT_EVIDENCE["frozen_transformer_checkpointing_executed"] = True

    def test_batched_template_pairing_equals_individual_forward(self):
        self.backbone.eval()
        condition = make_condition(self.encoder)
        sample = torch.randn(2, 16, 4, 4)
        times = torch.tensor([0.1, 0.9])
        from dreampage_headswap.types import IdentityCondition
        with torch.no_grad():
            batched = self.backbone.predict_velocity(sample, times, condition)
            individual = []
            for index in range(2):
                part = slice(index, index+1)
                identity = IdentityCondition(condition.identity.global_embedding[part],
                    condition.identity.local_tokens[part], condition.identity.structure[part])
                one = SwapCondition(identity, condition.template[part], condition.mask[part],
                    GeometryCondition(condition.geometry.spatial[part], condition.geometry.vector[part]), condition.age[part])
                individual.append(self.backbone.predict_velocity(sample[part], times[part], one))
        torch.testing.assert_close(batched, torch.cat(individual), rtol=3e-5, atol=3e-6)
        CONTRACT_EVIDENCE["batch_vs_individual_max_error"] = (batched-torch.cat(individual)).abs().max().item()

    def test_continuous_timestep_and_reference_position_ids(self):
        condition = make_condition(self.encoder)
        sample = torch.randn(2, 16, 4, 4)
        times = torch.tensor([0.2, 0.8])
        observed = {}
        def inspect_call(module, args, kwargs):
            observed.update({key: value.detach().clone() if isinstance(value, torch.Tensor) else value
                             for key, value in kwargs.items()})
        hook = self.backbone.transformer.register_forward_pre_hook(inspect_call, with_kwargs=True)
        try:
            self.backbone.predict_velocity(sample, times, condition)
        finally:
            hook.remove()
        torch.testing.assert_close(observed["timestep"], times, rtol=0, atol=0)
        self.assertIsNone(observed["guidance"])
        self.assertEqual(observed["hidden_states"].shape, (2, 32, 16))
        self.assertEqual(observed["img_ids"].shape, (2, 32, 4))
        self.assertTrue((observed["img_ids"][:, :16, 0] == 0).all())
        self.assertTrue((observed["img_ids"][:, 16:, 0] == 10).all())
        CONTRACT_EVIDENCE["continuous_timesteps_passed_without_rescaling"] = True

    def test_base_cfg_formula_and_inference_reference_cache(self):
        condition = make_condition(self.encoder)
        sample = torch.randn(2, 16, 4, 4)
        times = torch.tensor([0.2, 0.8])
        with torch.no_grad(), patch.object(self.backbone.vae, "encode", wraps=self.backbone.vae.encode) as encode:
            guided = self.backbone.predict_sampling_velocity(sample, times, condition)
            conditional = self.backbone.predict_velocity(sample, times, condition)
            unconditional = self.backbone._predict_velocity(sample, times, condition, self.backbone.negative_prompt_embeddings)
            torch.testing.assert_close(guided, unconditional+4*(conditional-unconditional), rtol=0, atol=0)
            self.assertEqual(encode.call_count, 1)
            condition.template.add_(0.001)
            self.backbone.predict_velocity(sample, times, condition)
            self.assertEqual(encode.call_count, 2)
        CONTRACT_EVIDENCE["base_text_cfg_formula_verified"] = True
        CONTRACT_EVIDENCE["inference_reference_encode_calls_for_four_forwards"] = 1

    def test_scheduler_sigma_euler_matches_native_scheduler(self):
        schedule = self.backbone.sampling_schedule(4, torch.device("cpu"), (4, 4))
        self.assertEqual(schedule.shape, (5,))
        self.assertEqual(schedule[-1].item(), 0)
        sample = torch.randn(2, 16, 4, 4)
        velocity = torch.randn_like(sample)
        for index, timestep in enumerate(self.pipeline.scheduler.timesteps):
            expected = sample + (schedule[index+1]-schedule[index])*velocity
            actual = self.pipeline.scheduler.step(velocity, timestep, sample, return_dict=False)[0]
            torch.testing.assert_close(actual, expected, rtol=0, atol=0)
            sample = actual
        CONTRACT_EVIDENCE["scheduler_sigmas"] = schedule.tolist()
        CONTRACT_EVIDENCE["euler_matches_diffusers_scheduler_exactly"] = True

    def test_bf16_backbone_accepts_fp32_promoted_sample_and_decoder(self):
        self.backbone.to(dtype=torch.bfloat16)
        self.encoder.to(dtype=torch.bfloat16)
        condition = make_condition(self.encoder, dtype=torch.bfloat16)
        sample = torch.randn(2, 16, 4, 4, dtype=torch.float32, requires_grad=True)
        velocity = self.backbone.predict_velocity(sample, torch.tensor([0.4, 0.7]), condition)
        image = self.backbone.decode_latents(sample-0.4*velocity)
        image.float().square().mean().backward()
        self.assertTrue(torch.isfinite(velocity).all())
        self.assertTrue(torch.isfinite(sample.grad).all())
        self.assertGreater(sample.grad.abs().sum().item(), 0)
        CONTRACT_EVIDENCE["bf16_forward_decoder_backward"] = True


if __name__ == "__main__":
    unittest.main()

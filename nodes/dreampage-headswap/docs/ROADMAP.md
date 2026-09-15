# Roadmap and evidence gates

The project starts as an implemented research baseline. **Implemented** means code exists; **tested** means a recorded automated run passed; **trained** means a particular checkpoint has an identified dataset and optimization history; **benchmarked** means a reproducible named evaluation was actually run; **production ready** additionally requires calibrated quality, operational tests and release approval. A synthetic overfit checkpoint must never be labeled a trained realistic headswap model.

## Milestones

| Milestone | Delivered starting point | Exit evidence still required |
| --- | --- | --- |
| 0 — Inspect existing workflow | Three inputs, actual checkpoint/encoder, conditioning, sampler and stitch/upscale wiring documented | Record production workflow/checkpoint hashes when enrolling the real benchmark |
| 1 — Current-system benchmark | Case/pair formats, comparison infrastructure and human-review path | Consented/authorized held-out cases with genuine current outputs; baseline report before substantial training |
| 2 — Core contracts | Typed child/template/mask/crop/geometry/identity/output structures | Extend compatibility tests whenever contracts change |
| 3 — Preservation | Authoritative masks, deterministic crop transforms and direct protected-pixel copying | Passing invariants for edges, soft/empty masks, resizing, padding and dtypes; document downstream image encoders |
| 4 — DreamFace | Trainable multi-reference global/local/structure baseline and identity adapter | Approved data; identity discriminability, cross-pose validation and an independently validated evaluator |
| 5 — DreamSwap baseline | Native small flow implementation and optional FLUX BASE 4B integration | Real BASE 4B snapshot loaded; gradient, sampling, numerical and memory profiling on target GPU |
| 6 — Tiny overfit | Minimal trainer, checkpointing, configuration and synthetic debugging path | Overfit 10–100 approved real pairs, source-reference ablations, strong reconstruction plus recognizable source identity; do not scale on loss curves alone |
| 7 — First trained baseline | Training/evaluation architecture | Train on approved identities; compare against current pipeline on identical unseen identities and case inputs |
| 8 — Deeper fine-tuning | Backbone abstraction and staged-training design | Adapter vs selected blocks vs partial/full fine-tuning experiments with quality/VRAM/latency tradeoffs |
| 9 — DreamRefine | Bounded residual model, verified-artifact dataset, frozen-teacher trainer, bundled inference and synthetic execution | Approved real-artifact training, noninferior identity and improved human realism/integration rankings |
| 10 — Production integration | Thin ComfyUI nodes over the independent core | Full live-node execution, checkpoint/device lifecycle, concurrency/retry limits, calibrated quality gate, packaging/license and operational review |
| 11 — Proprietary backbone | Vendor-neutral latent/velocity/conditioning interface; small test backbone | Proven data/objectives and sufficient resources before developing a specialized 500M–2B backbone |

Automated tests verify software behavior, not recognition quality. Actual commands and latest local run evidence belong in `README.md` and `TRAINING.md`; this table must not be read as evidence that every exit gate has passed.

## Next engineering priority

After the local synthetic tests pass, **assemble the first approved, identity-disjoint benchmark and 10–100-pair overfit set, then prove the real BASE 4B adapter path with gradients and reconstruction on that set**. Obtain a complete local Apache-2.0 BASE 4B snapshot, pin its source revision/license/hashes, and profile one forward/backward step before extending the run. The installed 9B filename is not a substitute for this target or its rights record.

Benchmark input enrollment should cover frontal and three-quarter views, opposite angles, up/down pose, gaze/expression changes, warm/cold/challenging lighting, low-resolution references, different head sizes and hair crossing the mask boundary. Keep identities out of training even if the benchmark uses synthetic book templates. A true current-workflow output is mandatory for an honest current-versus-new comparison.

## Ordered experiments

1. **Preservation contract:** prove zero altered protected pixels at native template resolution; reject drift after every downstream change. Report both pre-upscale and delivered legacy output behavior explicitly.
2. **Identity reliance:** hold template fixed, vary source identity; hold source fixed, vary template identity/pose. Compare source-conditioning removal/shuffle ablations. Reject a model that copies target identity or ignores references.
3. **Degradation:** compare neutral masking, blur, noise and pixelation at matched seeds/data. Measure geometry retention and leakage rather than selecting solely on reconstruction loss.
4. **Reference count:** compare one, two and several captures with quality/view weighting, missing-view handling and consistent held-out cases.
5. **Conditioning depth:** compare projected tokens, spatial residuals and per-block identity injection. Tune trainable parameter count only after the simplest route shows real transfer.
6. **Age/pose/expression:** introduce reviewed annotations/providers; use supplied age metadata and stratified human review. Confirm that improvements in identity do not replace template pose or make children appear older.
7. **Refinement:** enable the second stage only when it improves realism without a material identity regression. Evaluate boundaries, hair, neck, sharpness and grain as well as facial detail.
8. **Scaling and serving:** validate BF16/VRAM at 512→768→1024, then distributed training, concurrency, bounded retries and observability. Choose thresholds from validation data and record their calibration.

## Release gates

- No undocumented model/dataset rights, no automatic customer-image training, no identity or duplicate-image split leakage.
- No unreported unavailable metrics, synthetic proxy results or invented current outputs; publish all failed cases and latency/VRAM measurement scope.
- Unit/integration tests pass; resumes restore training state; configs and checkpoint/model/data revisions are retained.
- Held-out identity/age/geometry and blinded human realism criteria meet explicitly agreed thresholds; source pose does not override template pose.
- Native output retains protected pixels exactly, with lossless export validation where required.
- Production packaging, ComfyUI integration, retention, license obligations, resource limits and recovery are verified. The current production workflow is replaced only after these gates pass.

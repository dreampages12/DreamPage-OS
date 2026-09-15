# Training

What is actually implemented, what it costs to run, and what each milestone has to show before
the next one starts. `docs/ARCHITECTURE.md` explains why the pieces are shaped this way;
`docs/ROADMAP.md` holds the gates.

## The objective

Rectified flow in the backbone's latent space. For a clean latent `x0` and noise `e` at a
timestep `t` drawn uniformly from `[0,1]`:

```
sample            = (1 - t) * x0 + t * e
target velocity   = e - x0
x0 estimate       = sample - t * prediction
```

The model sees the noisy sample, the timestep, the child references, the identity-suppressed
template crop, the mask and the geometry condition. That suppressed crop comes from the dataset,
which replaces the native template's masked pixels **before** the crop is resized. Suppressing
after the resize lets interpolation carry the target face into neighbouring pixels first, and a
falling loss then stops being evidence that the child reference is used at all. The trainer
refuses a batch whose prepared strategy differs from the one it was asked for.

Image-space losses decode the `x0` estimate, which is why enabling one costs decoder gradients
and, on a real backbone, significant VRAM. The flow loss alone does not need the decoder, and
`LossSuite.needs_images` reports which case you are in.

Sampling integrates from `t = 1` to `t = 0`, re-imposing the protected latent at every step, and
the final compositor then copies protected pixels from the original regardless.

## Loss inventory

Weights come from YAML. Nothing is hardcoded, and no weight has been tuned against real data.

| Loss | Runs today | What it actually measures |
| --- | --- | --- |
| `flow_matching` | yes | MSE against the target velocity |
| `reconstruction` | yes | masked L1 against the ground-truth crop |
| `outside_mask` | yes | L1 against the template outside the mask |
| `boundary` | yes | L1 in a one-pixel band around the mask edge |
| `lighting` | yes | low-frequency pixel statistics, not a lighting model |
| `local_texture` | yes | high-frequency pixel statistics, not a realism judgment |
| `global_identity` | needs a provider | identity similarity |
| `local_identity` | needs a provider | per-feature identity similarity |
| `facial_perceptual` | needs a provider | perceptual distance on faces |
| `pose`, `landmark`, `gaze`, `expression` | needs a provider | geometry agreement with the template |
| `age_consistency` | needs a provider | apparent age against the supplied age |

A provider is a licensed, frozen, independently validated differentiable estimator, passed in as
`callable(prediction_rgb, target_rgb, batch) -> scalar`. Setting a nonzero weight on one of the
bottom six without supplying it raises. That is deliberate: a missing identity loss reported as
zero looks exactly like a perfect one.

DreamFace must not be its own teacher. An encoder optimized jointly with the generator that also
scores it will happily agree with itself.

`supervised_identity_contrastive` is available separately for encoder training. It needs at least
two distinct identities in a batch, and it raises rather than degrading to a meaningless
single-identity objective.

## Configs

| File | Purpose |
| --- | --- |
| `configs/training/tiny.yaml` | CPU development on the tiny backbone. Runs today. |
| `configs/training/flux_klein_base_4b.yaml` | The BASE 4B adapter run. Needs a reviewed local snapshot. |
| `configs/training/identity_encoder_tiny.yaml` | DreamFace on its own contrastive objective. Runs today. |
| `configs/models/*.yaml` | Model shape only, for reuse across training and inference. |
| `configs/inference/tiny_smoke.yaml` | Mechanics smoke test. |
| `configs/inference/flux_klein.yaml` | Production-shaped inference. Needs weights and a checkpoint. |

The FLUX config trains DreamFace and the DreamPage adapters with `train_transformer: false` and
image losses at zero. That is the first stage of the staged plan, not a recommendation to leave
them off forever.

## Running

```powershell
python training/train.py --config configs/training/tiny.yaml
python training/train.py --config configs/training/tiny.yaml --resume runs/tiny/checkpoint.pt
```

Before the first real run, prove the machinery:

```powershell
python training/tiny_overfit.py --output runs/tiny-overfit --steps 120
```

Two procedural shapes, one fixed noise sample and one fixed timestep. The most recent run took
the loss from 1.33 to 0.011. That demonstrates that gradients reach the conditioning path. It
demonstrates nothing about faces, and the report says so in its own `scope` field.

## Validation and the best checkpoint

A `validation:` section turns on periodic held-out validation. It runs every `every` steps and
always at the final step, on rank zero only, on the unwrapped module, so no collective runs
inside it.

```yaml
validation:
  manifest: data/pairs/pairs.validation.jsonl
  split: validation
  every: 100
  seed: 4321
  batch_size: 1
  max_batches: 8
  samples: false          # write a reference/template/sample/target grid per validation
  metric: validation/total
```

The validation dataset is audited together with the training manifest, so a held-out split that
shares an identity, a file hash or decoded pixels with training fails here instead of producing
a flattering curve. Validation saves and restores the random state around itself, so enabling it
does not change the training stream: a run that stops and resumes still lands on the same
parameters, and a test asserts that with validation switched on.

`checkpoint.best.pt` tracks the best `metric` seen so far, carries the score and the full
validation record in its metadata, and survives a resume, so a later worse score cannot quietly
replace it. Selecting on a held-out flow loss measures optimization. It is not an identity,
realism or preservation result, and the run result says `quality_validated: false` for that
reason.

The old `dataset.validation_manifest` and `training.validation_every` keys are refused with a
message pointing here. A config that only looks configured would never validate.

## The dataset fingerprint

Each run hashes the enrolled records and the bytes of every asset they name, and stores the
digest in the checkpoint. A resume whose data changed is refused rather than described as exact.
Set `training.verify_dataset_fingerprint: false` to skip it on a corpus where hashing every file
is too slow, and accept that "same manifest path" is then all the resume can claim.

## Training the identity encoder

DreamFace has its own trainer, because an encoder optimized jointly with a generator and then
used to score it can agree with itself.

```powershell
python training/train_identity_encoder.py --config configs/training/identity_encoder_tiny.yaml
```

Two captures of one person are two views: the source capture and the target capture's head crop.
The supervised cross-view contrastive objective pulls the views of one identity together and
pushes different identities apart. Three things it insists on:

- **Negatives exist.** Batches are built identity-aware, `identities_per_batch` distinct people
  with one pair each, deterministic in the seed and epoch. A single-identity batch is refused
  rather than silently producing a meaningless objective.
- **Both views are framed the same way.** `dataset.source_crops: true` puts the source through
  the production crop using the source capture's own headmask, so the encoder cannot learn
  "whole photo versus head crop" instead of a face. It requires `source_headmasks` in the pair
  manifest, which `generate_training_pairs.py` writes when enrolment masked every capture.
- **Held-out identities are separate.** Validation reports within-batch cross-view top-1
  retrieval, both directions, plus the positive and negative similarities and their margin.

Selecting on `validation/retrieval_top1` is correct for this objective, and the trainer knows
that metric improves upwards. Read the number for what it is: separability of the enrolled
captures among the identities in one batch. On the procedural fixture it reaches 1.0 by telling
two coloured ellipses apart. It is not a calibrated identity evaluator and it is not evidence
about recognizing a child.

## Checkpoints and resume

Every checkpoint carries the model, optimizer, scheduler, step, data cursor, config, RNG state
for Python, NumPy and Torch, and a `quality_claim` string that refuses to imply validated
quality. Writes are atomic, through a temporary file and a replace.

Resume is exact. Stopping at step two and resuming to step four produces the same parameters,
bit for bit, as running straight through, and `tests/test_train_loop.py` asserts it. This works
because the epoch iterator is rebuilt deterministically at the stored cursor and the RNG state is
restored with the weights.

Resume refuses to continue when the model, optimizer, loss, dataset or seed configuration
changed, and when the world size changed. A resumed run that is quietly a different experiment is
worse than no resume at all.

## Precision, devices and scale

`fp32` and `bf16` are supported. `fp16` is refused, because its loss scaling is not implemented
and a silent fallback would be a lie about numerics. bf16 on CUDA is checked against the actual
device.

Distributed training is implemented with DistributedDataParallel, NCCL on Linux CUDA and Gloo
elsewhere, with gradient accumulation that suppresses synchronization on all but the last micro
step, and per-rank checkpoints. It has not been validated on more than one process. FLUX plus
distributed is refused outright: sharding a 4B backbone is its own integration milestone, not a
flag.

Gradient clipping is on by default, and a non-finite gradient norm aborts the step rather than
poisoning the optimizer state.

## Tracking

Local JSONL by default, TensorBoard optionally, both behind one interface. Neither uploads
images, identities or customer data. The metrics file records every loss term separately, plus
the learning rate, per step.

## The FLUX contract environment

The BASE 4B bridge is verified against the real Diffusers classes, with tiny random configs and
a toy local vocabulary. No weights are downloaded and no face data is involved. The tested and
pinned Diffusers version is **0.37.1**, with Transformers **4.56.2** in the isolated environment.
All ten contract tests passed. On an older install the integration tests skip with a precise reason.

```powershell
.venv-flux-test\Scripts\python scripts/verify_flux_contract.py --output runs/flux-contract/report.json
```

The report records library versions, interpreter paths and the measured evidence, and states
`pretrained_base_4b_executed: false`. Keep that environment separate; do not upgrade the
ComfyUI installation in place to obtain it.

Loading a real snapshot additionally requires `dreampage_provenance.json` beside it, naming the
model id, the source revision, `license: Apache-2.0` and `commercial_use_reviewed: true`. A
snapshot that declares `is_distilled` or whose transformer config does not match the audited
BASE 4B shape is refused. That is what stops a renamed 9B checkpoint from entering the stack.

## Evidence gates

Milestone 6, the tiny-dataset overfit, is not passed by a falling loss curve. It needs 10 to 100
approved real pairs, strong reconstruction **and** recognizable source identity, plus the
ablation that matters: remove or shuffle the child reference. If the output barely changes, the
model is reading the template, not the child, and scaling would only make that failure more
expensive.

Milestone 7 compares against the current workflow on identical inputs and identities that appear
in neither training nor validation. Do not claim an improvement without that comparison, and do
not compare a pre-upscale crop against a delivered upscaled page without saying so.

## Additional training work

The separate refiner trainer now exists: `training/train_refiner.py`. It uses verified generated
artifacts and a frozen independent DreamFace checkpoint; the objective and exact commands are in
`REFINEMENT.md`. Its synthetic-only mode cannot admit real pairs or claim a calibrated teacher.

Pose-aware sampling for the encoder is not implemented either. Batches currently pick one pair
per identity at random; once captures carry reviewed pose annotations, view selection should
prefer pose-diverse positives, which is the point of a cross-view objective in the first place.

## Latest execution evidence (2026-09-12)

- 188 local tests passed (nine environment-specific skips); all ten optional FLUX contract tests
  passed separately with real tiny library modules. These are not pretrained BASE 4B tests.
- A three-step BF16 tiny-model run completed on the RTX 3090, followed by held-out validation,
  checkpoint loading and inference with zero changed protected pixels.
- The separate refiner completed six steps on 48 procedural artifact/pair records with a
  frozen shape-trained encoder, held-out validation, best checkpoint and sample images.
- Exact-resume regression tests include interruption inside a later identity-training epoch,
  refiner training with validation, source-mask byte changes, and generator training.
- Training and validation now share configured degradation, source framing, registry, mask
  channel and context. Non-default noise degradation is covered by an actual training test.

The identity trainer directly supervises **global embeddings only**. Local spatial features
share its trained convolutional trunk, but anatomical local-token and structural supervision
remain research tasks. Checkpoint metadata states the supervised outputs. Initialize DreamSwap
from this encoder using `model.identity_checkpoint`; match its dimensions and `token_grid`.
`model.freeze_encoder: true` is optional and requires a supplied independent checkpoint.

Training metrics include per-rank throughput, gradient norms and CUDA peak allocated memory.
These exclude validation/checkpoint overhead. Exact bitwise resume is evidenced on CPU in the
tested environment; other GPU/library/distributed configurations require their own evidence.

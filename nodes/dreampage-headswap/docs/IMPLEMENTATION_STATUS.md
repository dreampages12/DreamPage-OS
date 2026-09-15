# Implementation status — 2026-09-12

DreamPage HeadSwap has working training and inference infrastructure. It is **not yet a
validated realistic child headswap model**. Tests of random modules and procedural shapes prove
software contracts, not identity likeness or print quality.

## Components and evidence

| Component | Implemented and executed | Still required |
| --- | --- | --- |
| Mask/crop/composite | Native-resolution suppression, geometry transforms, strict protected-pixel copying; CPU and CUDA smoke checks | Real template/identity visual evaluation |
| DreamFace | Multi-reference encoder; contrastive trainer, validation and exact resume | Broad face pretraining; local/anatomy supervision; independent real identity validation |
| DreamSwap | Tiny flow trainer, sampling, adapters and optional BASE 4B bridge | Execute pretrained BASE weights on suitable data; tune identity/pose objectives |
| FLUX contract | Ten tests passed with real tiny Diffusers 0.37.1 modules, BF16 backward and gradient checkpointing | Full pretrained memory/gradient/quality measurements |
| DreamRefine | Frozen independent teacher, bounded residual, artifact provenance, validation, bundled inference | Train on actual generator errors with an independently validated teacher |
| Data | Rights checks, capture/mask ingestion, hash registry, identity splits, quality report | Approved multi-capture face corpus and reviewed masks |
| Benchmark | Archived-result comparison, hash binding, review grids and blind A/B | Run current and new models on the same approved cases; human review |
| ComfyUI | Seven thin nodes and conversion contracts | End-to-end validation in the production application |

## Reproducible receipts

Paths below are relative to the project root. `runs/` and `local_data/` contain local artifacts
and are ignored by Git; code and documentation do not depend on publishing private data.

- `runs/session6/flux-contract.json`: ten optional tests, no skips; no pretrained weights.
- `runs/session6/cuda-smoke-v2/report.json`: RTX 3090, three BF16 training steps and checkpoint
  inference. Outside-mask changes: zero. Quality: RETRY, missing semantic metrics.
- `runs/session6/tiny-overfit/report.json`: 120 steps on two procedural shapes, 99.1846% loss drop.
- `runs/session6/fixture/identity_run/`: independent encoder trained for four fixture steps.
- `runs/session6/refiner-fixture/training_run/`: six fixture steps, validation and best checkpoint.
- Latest main-suite count before acquisition changes: 188 tests, nine environment-dependent skips.

## Acquire the actual backbone

```powershell
.venv-flux-test/Scripts/python.exe scripts/download_flux_base.py
```

The default target is `local_data/models/flux-klein-base-4b`. The download uses the official
publisher's Apache-2.0 release, a pinned commit, and verifies every downloaded file against
upstream hashes before writing `dreampage_provenance.json`.

**Completed locally:** all 20 files, 15,980,151,379 bytes, verified. The snapshot is ready;
full pretrained image inference and training have not yet run.

## Candidate review preparation

`configs/data/photoreal_candidates.json` proposes four fictional children with three camera views
each. `scripts/prepare_photoreal_candidates.py` performs inference only, freezes the weights and
leaves all outputs unapproved. Images, prompts, seeds, hashes and an HTML review go into
`local_data/photoreal-candidates-v1/`. The planned twelve-image pilot evaluates a potential data
source; it is not a sufficiently broad final training dataset.

GPU availability currently limits candidate generation because ComfyUI has active work. The CPU
prompt attempt was stopped without producing images or a cache. Do not interrupt active ComfyUI
jobs. When sufficient memory is available, encode with `--stage encode --text-device cuda`, then
run `--stage sample`. Neither operation is training; dataset approval is still required afterward.

## Data needed for realistic training

**User approval required before any training starts.** Prepare example images, source and rights,
quality findings, identity splits and an exact manifest hash, then request approval. Do not run
the training commands below, pretraining, refinement or optimizer tests until that approval arrives.

**Binding user requirement: only photorealistic images in training.** Stylized, CGI, cartoon and
procedural images are excluded, including encoder pretraining. Syn-Vis-v0 was considered and
rejected; its candidate downloads have never been enrolled or trained. Existing fixture-trained
checkpoints are software-test artifacts and must not initialize realistic training.

At least several distinct captures per identity, with pose/expression/lighting diversity, sufficient
head resolution, documented commercial training rights, and reviewed masks. Train/validation/test
identities must be disjoint. Use `scripts/ingest_dataset.py`, `scripts/preprocess_dataset.py`,
`scripts/generate_training_pairs.py` and `scripts/dataset_report.py` as described in DATASET and
DATA_ACQUISITION. Customer inference permission is not training enrollment.

The current FLUX config is `configs/training/flux_klein_base_4b.yaml`; the independently trained
encoder can initialize `model.identity_checkpoint`. Set actual manifest paths, registry and
`model.weights_path`, then run in the isolated environment:

```powershell
.venv-flux-test/Scripts/python.exe training/train_identity_encoder.py --config <enrolled-encoder-config.yaml>
.venv-flux-test/Scripts/python.exe training/train.py --config <enrolled-flux-config.yaml>
```

Realistic output, successful training, benchmark superiority and production readiness are separate
milestones. None follows from a falling fixture loss. Existing production workflows remain the
baseline documented in CURRENT_WORKFLOW, including their whole-page upscale preservation caveat.

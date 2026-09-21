# Implementation status — 2026-09-21

Current integration: DreamPage OS `nodes/dreampage-headswap`, separate training `.venv`,
hash-bound managed runs (fresh/resume/finetune), intake review with HEIC support, and
the 30-node LAB Studio workflow. All 16 DP classes were observed on the running server.
See [OS training guide](../../../docs/MODEL-TRAINING.md) and WORKLOG Session 10.
The historical evidence below predates this migration. No new optimization was executed;
the dataset is still empty/unapproved and real training/VRAM/quality validation remains pending.

DreamPage HeadSwap has working training and inference infrastructure. It is **not yet a
validated realistic child headswap model**. Tests of random modules and procedural shapes prove
software contracts, not identity likeness or print quality.

## Components and evidence

| Component | Implemented and executed | Still required |
| --- | --- | --- |
| Mask/crop/composite | Native-resolution suppression, geometry transforms, strict protected-pixel copying; CPU and CUDA smoke checks | Real template/identity visual evaluation |
| DreamFace | Multi-reference encoder; contrastive trainer, validation and exact resume | Broad face pretraining; local/anatomy supervision; independent real identity validation |
| DreamSwap | Explicit Klein 9B bridge, adapter training and variant/shape/hash checks | Obtain reviewed 9B components; validate actual loading/memory/optimization after dataset approval |
| FLUX contract | Ten tests passed with real tiny Diffusers 0.37.1 modules, BF16 backward and gradient checkpointing | Full pretrained memory/gradient/quality measurements |
| DreamRefine | Frozen independent teacher, bounded residual, artifact provenance, validation, bundled inference | Train on actual generator errors with an independently validated teacher |
| Data | Rights checks, capture/mask ingestion, hash registry, identity splits, quality report | Approved multi-capture face corpus and reviewed masks |
| Benchmark | Archived-result comparison, hash binding, review grids and blind A/B | Run current and new models on the same approved cases; human review |
| ComfyUI | Seven core nodes plus nine native Klein Studio nodes; separate LAB graph installed | Current migrated graph's real-image quality and final-file evaluation; no production rollout |

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

## Current backbone and data source

Tobias explicitly chose **Klein 9B** on 21.09.2026; 4B is retired. Use
`configs/training/flux_klein_9b_photoreal_pilot.yaml` and
`scripts/prepare_klein_9b.py`. The local 9B transformer exists, but official
support-component access currently returns GatedRepoError. See the
[OS training guide](../../../docs/MODEL-TRAINING.md) for the exact revision and steps.
The older 4B download/candidate-generator configuration is archived. User-supplied
photos and DreamPage swap examples remain the planned training-data source.

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

The current FLUX config is `configs/training/flux_klein_9b_photoreal_pilot.yaml`; the independently trained
encoder can initialize `model.identity_checkpoint`. Set actual manifest paths, registry and
`model.weights_path`, then run in the isolated environment:

```powershell
.venv-flux-test/Scripts/python.exe training/train_identity_encoder.py --config <enrolled-encoder-config.yaml> --approval <approved-dataset.json>
.venv-flux-test/Scripts/python.exe training/train.py --config <enrolled-flux-config.yaml> --approval <approved-dataset.json>
```

Realistic output, successful training, benchmark superiority and production readiness are separate
milestones. None follows from a falling fixture loss. Existing production workflows remain the
baseline documented in CURRENT_WORKFLOW, including their whole-page upscale preservation caveat.

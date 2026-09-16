# DreamRefine training and serving

Implemented and tested on synthetic fixtures. No trained realistic-skin checkpoint, identity
improvement or production readiness is claimed.

## Architecture and objective

`RefinementSystem` contains two components: an independently trained, **frozen** DreamFace encoder
and the trainable bounded residual `DreamRefine` CNN. The encoder supplies source identity
conditioning and differentiable global-identity distances. Encoder weights never update; image
gradients still flow through it into the refiner. The checkpoint bundles both components, so
inference cannot accidentally substitute the DreamSwap encoder's different representation.

The refiner receives the generated crop, protected template context, binary generation mask and
source identity. It predicts at most `model.max_delta` RGB change per channel in the editable
crop (default 0.08 on `[0,1]`). The pipeline applies the original full-resolution soft blend mask
only at the final composite. Protected output pixels are copied from the original template.

YAML weights combine:

- masked reconstruction and boundary L1;
- optional low-frequency lighting and high-frequency texture differences;
- global source-identity cosine distance;
- cosine distance to the generated head's identity, constraining drift;
- optional residual magnitude penalty.

Both identity terms must have positive weights. These distances depend on the teacher's quality.
A low loss from an unvalidated encoder cannot establish recognizable identity or realism. Local
anatomy and age evaluation still require trained, independently assessed providers.

## Artifact manifest

Keep the enrolled pair corpus and its `dataset_registry.json`. A separate JSONL annotation file
links generated artifacts to those exact pairs:

```json
{"pair_id":"enrolled-pair-id","generated":"images/generated.png","sha256":"64 lowercase hex digits","generator":{"kind":"model","checkpoint_sha256":"64 lowercase hex digits","config_sha256":"64 lowercase hex digits"}}
```

Each image must match the original template dimensions. The dataset applies the same crop
transform as the target and rejects missing artifacts, changed bytes, malformed provenance,
and exact generated/base-image duplicates crossing splits. Artifact paths resolve relative to
their manifest. The manifest belongs in `dataset.artifacts_manifest`; the ordinary pair manifest
remains `dataset.manifest`.

Generated files and source headmasks are included in the checkpoint's dataset fingerprint.
Changing them prevents exact resume. The artifact manifest records provenance declarations;
it cannot independently prove that a declared checkpoint actually generated those pixels.

## Frozen teacher admission

`teacher.checkpoint` must be a standalone DreamFace checkpoint produced by the identity trainer.
For real data, `teacher.review` points to a reviewed JSON record:

```json
{
  "checkpoint_sha256": "SHA256 of the exact DreamFace checkpoint",
  "commercial_use_reviewed": true,
  "independent_validation_report": "teacher-validation-report.json",
  "independent_validation_sha256": "SHA256 of that report"
}
```

The report path resolves relative to the review file. This is an evidence-bound admission record,
not a machine-generated commercial license or automatic validation. The teacher checkpoint must
record its training identity inventory. Refiner validation rejects identities that the teacher
trained on. The output quality gate still needs its separately calibrated providers.

`teacher.allow_unvalidated_for_synthetic: true` is restricted to a synthetic teacher checkpoint
and exclusively synthetic train/validation pairs. It cannot authorize training on real people.

## Commands

From `C:\DreamPage-OS\DreamPage-image\dreampage-headswap`, with `$env:PYTHONPATH = "src;."`:

```powershell
..\venv\Scripts\python.exe training/train_refiner.py --config configs/training/refiner.yaml
..\venv\Scripts\python.exe training/train_refiner.py --config configs/training/refiner.yaml --resume runs/refiner/checkpoint.pt
```

For a complete synthetic mechanics check, use fresh directories:

```powershell
..\venv\Scripts\python.exe scripts/make_synthetic_dataset.py --output-dir runs/refine-demo-data --identities 8 --captures 3
..\venv\Scripts\python.exe training/train_identity_encoder.py --config runs/refine-demo-data/identity_smoke.yaml
..\venv\Scripts\python.exe scripts/make_refinement_fixture.py --pairs-dir runs/refine-demo-data --teacher-checkpoint runs/refine-demo-data/identity_run/checkpoint.pt --output-dir runs/refine-demo
..\venv\Scripts\python.exe training/train_refiner.py --config runs/refine-demo/refiner_smoke.yaml
```

The fixture introduces small color/noise perturbations into procedural shapes. These are not
DreamSwap face outputs. On 2026-09-12 the six-step run completed, frozen weights stayed fixed,
validation/best checkpoints and sample images were written, and protected pixel difference was
zero. `tests/test_refinement.py` also checks exact interrupted/resumed equivalence.

To use the bundled trained system from the standalone pipeline or the ComfyUI production node:

```yaml
refiner:
  checkpoint: runs/refiner/checkpoint.best.pt
inference:
  refine_strength: 0.5
```

Merge these fields into the inference config; its model, mask, crop and other fields still apply.
The checkpoint embeds its identity encoder and max-delta/model configuration. The original
teacher file is not required at serving time. The trainer currently supports one CPU/GPU process,
FP32/BF16, gradient accumulation, local JSONL/TensorBoard, validation, sample outputs and exact
CPU resume. Distributed refinement and real-data quality remain unverified.

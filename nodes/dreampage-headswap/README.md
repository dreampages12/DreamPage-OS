# DreamPage HeadSwap

Identity-conditioned head reconstruction for personalized children's books.

```
child reference(s)  ->  who the person is
template            ->  pose, expression, lighting, scene, composition
supplied headmask   ->  where editing is permitted
                    ->  the original template with only the head region reconstructed
```

The template is already the desired image. The system does not regenerate the page. It crops
around the supplied mask, reconstructs inside it, and composites back into the untouched
full-resolution template. Pixels the mask protects are copied from the original after all
arithmetic, so no denoiser, VAE or refiner can drift them.

## Status

**Current user requirements (2026-09-12):** use only photorealistic images in training and
obtain the user's approval of the exact dataset before any pretraining, fine-tuning or optimizer
test. The commands below describe capabilities; they are not permission to start training.
See `AGENTS.md` and `docs/IMPLEMENTATION_STATUS.md` for the latest handoff.

Read this table with the vocabulary in `docs/ROADMAP.md`. **Implemented** means code exists.
**Tested** means an automated run passes. **Trained**, **benchmarked** and **production ready**
mean what they say, and nothing in this repository has reached them yet.

| Component | Implemented | Tested | Trained | Benchmarked |
| --- | --- | --- | --- | --- |
| Mask, crop, transform and compositing | yes | yes | not applicable | not applicable |
| Quality gate and preservation metrics | yes | yes | not applicable | no |
| Dataset enrollment, pairing, leakage audit | yes | yes | not applicable | not applicable |
| DreamFace encoder and its own trainer | yes | yes | no | no |
| DreamSwap with the tiny CPU backbone | yes | yes | synthetic overfit only | no |
| DreamSwap with FLUX Klein BASE 4B | yes | loading refusals here, adapter contract in an isolated environment | no | no |
| DreamRefine and its separate frozen-teacher trainer | yes | gradients, exact resume, provenance, bundled inference | synthetic mechanics only | no |
| Training loop, checkpoints, exact resume | yes | yes | not applicable | not applicable |
| Held-out validation and best-checkpoint selection | yes | yes | not applicable | not applicable |
| Benchmark and blind human review | yes | yes, on synthetic fixtures | not applicable | no |
| ComfyUI nodes | yes | yes | not applicable | not applicable |

Nothing here has seen a real face. The automated suite runs on procedural noise and random
weights, which tests software behavior and says nothing about identity or realism.

## Install

Python 3.10 or newer, with PyTorch 2.5 or newer.

```powershell
cd C:\ComfyUI\dreampage-headswap
pip install -e ".[dev]"
```

Without the editable install, put both packages on the path instead. On Windows the separator is
a semicolon in every shell, Git Bash included.

```powershell
$env:PYTHONPATH = "src;."
```

The FLUX backbone needs the optional extra, `pip install -e ".[flux]"`, plus a reviewed local
BASE 4B snapshot. It is never downloaded automatically. See `docs/LICENSE_AUDIT.md`.

## Commands

Every command below was run from the repository root and produced the described output.

**Run the tests.** 188 tests, about twenty seconds on CPU. Nine skip: eight need the isolated
FLUX environment, one needs a machine without CUDA.

```powershell
python -m unittest discover -s tests
```

The interpreter already verified in this workspace is `..\venv\Scripts\python.exe`.
Use it instead of `python` when your shell has no project environment selected.
The separate FLUX command runs all ten optional contract tests:

```powershell
.\.venv-flux-test\Scripts\python.exe scripts/verify_flux_contract.py --output runs/flux-contract/report.json
```

**Prove the training machinery can overfit.** Two procedural shapes, fixed noise and timestep.
This is a mechanics check, not a face result; the report says so in its own `scope` field.

```powershell
python training/tiny_overfit.py --output runs/tiny-overfit --steps 120
```

The last run reduced the loss from 1.33 to 0.011, a 99 percent reduction.

**Run inference end to end** on the tiny CPU backbone. `--allow-untrained` exists so the
mechanics can be smoke-tested; without it a checkpoint is required and random weights are
refused.

```powershell
python -m dreampage_headswap.inference.cli `
  --config configs/inference/tiny_smoke.yaml `
  --child path\to\child.png `
  --template path\to\template.png `
  --mask path\to\headmask.png `
  --output runs/smoke/result.png `
  --allow-untrained `
  --debug-dir runs/smoke/debug
```

It writes a lossless PNG, a provenance report beside it, and fourteen debug artifacts covering
every stage from the supplied mask to the outside-mask difference image.

**Build a runnable fixture** when you want to exercise the plumbing without real data. It
writes procedural shapes, a registry and two ready training configs.

```powershell
python scripts/make_synthetic_dataset.py --output-dir runs/fixture --identities 8 --captures 3
```

**Enroll a dataset and build pairs.** Ingest takes one directory per person, validates the
rights record before writing anything, normalizes orientation, and obtains a headmask through an
explicit provider. Every step refuses data without complete rights metadata, and the last one
re-validates every manifest it wrote, together, for identity and pixel leakage.

```powershell
python scripts/ingest_dataset.py --root data/raw --output-dir data/enrolled --rights data/rights.json --mask-provider sidecar
python scripts/dataset_report.py --identities data/enrolled/identities.jsonl --report data/enrolled/quality.json
python scripts/preprocess_dataset.py --identities data/enrolled/identities.jsonl --output-dir data/clean
python scripts/generate_training_pairs.py --identities data/clean/identities.clean.jsonl --output-dir data/pairs
```

The quality report scores the corpus against an explicit target and names each gap. See
`docs/DATA_ACQUISITION.md` for where data can legitimately come from and what the targets mean.

**Train.** Point `dataset.manifest` in the config at a real pair manifest first.

```powershell
python training/train.py --config configs/training/tiny.yaml
python training/train.py --config configs/training/tiny.yaml --resume runs/tiny/checkpoint.pt
```

Resume is bit-exact: stopping at step two and resuming to step four lands on the same parameters
as running straight through, with held-out validation switched on or off. Tests assert both.
The run hashes the enrolled records and their image bytes, so a resume whose data changed is
refused rather than described as exact. A `validation:` section adds periodic held-out
validation and keeps `checkpoint.best.pt`.

**Train the identity encoder separately**, on its own cross-view contrastive objective, because
an encoder that scores the generator it was trained with can agree with itself.

```powershell
python training/train_identity_encoder.py --config configs/training/identity_encoder_tiny.yaml
```

Set `model.identity_checkpoint` and optionally `model.freeze_encoder: true` in the DreamSwap
training YAML to start from that independently trained encoder. Match `identity_dim`,
`structure_dim` and `token_grid`. Its current independent objective supervises the global
embedding; anatomical local tokens and the structure head are not separately trained by it.

**Train DreamRefine** against verified paired artifacts with a separately trained, frozen
DreamFace teacher. The checkpoint bundles that exact teacher for inference. Real-data training
requires recorded teacher validation and commercial-use review; synthetic mechanics have a
strictly synthetic-only option. See `docs/REFINEMENT.md` for the objective and artifact schema.

```powershell
python training/train_refiner.py --config configs/training/refiner.yaml
```

This complete local sequence uses generated shapes only, and needs no downloaded model weights.
Use fresh output directories:

```powershell
python scripts/make_synthetic_dataset.py --output-dir runs/fixture-next --identities 8 --captures 3
python training/train_identity_encoder.py --config runs/fixture-next/identity_smoke.yaml
python scripts/make_refinement_fixture.py --pairs-dir runs/fixture-next --teacher-checkpoint runs/fixture-next/identity_run/checkpoint.pt --output-dir runs/refinement-next
python training/train_refiner.py --config runs/refinement-next/refiner_smoke.yaml
```

**Exercise CUDA/BF16** on the tiny model and that same synthetic corpus:

```powershell
python scripts/smoke_gpu.py --config runs/fixture-next/training_smoke.yaml --output-dir runs/cuda-next
```

On the RTX 3090 this executed three optimizer steps, validation, checkpoint loading and
inference, with exactly zero changed outside-mask pixels. This is a small software test,
not a memory or speed estimate for the real BASE 4B model.

**Benchmark against the current production workflow.** The benchmark tool cannot generate an
image. It compares results that were produced elsewhere and recorded with their provenance.

```powershell
python scripts/benchmark.py archive-baseline --workflow ..\books\fotballstjernen\workflow_api.json --config ..\books\fotballstjernen\config.json --destination benchmarks/baseline_v6
python scripts/benchmark.py record-run --source child.png --template template.png --headmask mask.png --result current.png --workflow workflow.json --config config.yaml --method-id current_klein_v6 --destination runs/current.run.json
python scripts/benchmark.py compare --manifest benchmarks/cases.jsonl --output-dir runs/benchmark --training-manifest data/pairs/pairs.train.jsonl
```

**Check one stored result** against its template, and **run a blind human review**.

```powershell
python scripts/evaluate.py --template template.png --output result.png --mask mask.png
python scripts/human_review.py create --manifest benchmarks/cases.jsonl --destination runs/review
python scripts/human_review.py store --packet-dir runs/review/voter --responses responses.json --destination runs/review/log.jsonl
python scripts/human_review.py summarize --assignments runs/review/organizer_private/assignments.json --responses runs/review/log.jsonl
```

## Layout

| Path | What lives there |
| --- | --- |
| `src/dreampage_headswap/` | The stack. Runs without ComfyUI. |
| `comfyui_dreampage_headswap/` | Thin nodes over that stack. See `docs/COMFYUI.md`. |
| `configs/` | Model, training and inference configuration. No experiment is hardcoded. |
| `scripts/` | Dataset, benchmark, evaluation and review entry points. |
| `training/` | `train.py`, `train_identity_encoder.py`, `train_refiner.py` and `tiny_overfit.py`. |
| `tests/` | The suite above. `_fixtures.py` holds the procedural fixtures. |
| `benchmarks/` | Enrolled benchmark cases. See `benchmarks/README.md`. |
| `docs/` | Architecture, current workflow, dataset, training, ComfyUI, licenses, roadmap, worklog. |

## Where to read next

- `docs/ARCHITECTURE.md` for the design and what each component does and does not claim.
- `docs/CURRENT_WORKFLOW.md` for how the existing production graph actually works.
- `docs/DATASET.md` for the enrollment format and the rights rules.
- `docs/DATA_ACQUISITION.md` for where training data can legally come from, and the quality bar.
- `docs/TRAINING.md` for the loss inventory, configs and the evidence each milestone needs.
- `docs/ROADMAP.md` for the milestones and release gates.
- `docs/WORKLOG.md` for who changed what, and why.
- `docs/IMPLEMENTATION_STATUS.md` for the latest verified evidence and remaining external inputs.

## The rules this repository enforces in code, not in prose

- Customer images can be used for inference. They cannot enter training without explicit
  enrollment, and the rights gate raises rather than assumes.
- A benchmark identity that appears in training is an error, checked by identity, by file hash
  and by decoded pixels.
- An identity, pose, expression or realism metric that has no calibrated provider is reported as
  null with a reason. It is never replaced by a proxy.
- The quality gate cannot return PASS because outside-mask pixels matched.
- A loss that needs a licensed estimator cannot be enabled without one.
- Synthetic fixtures require an explicit opt-in, and every report they touch is labelled.
- The template's own face is suppressed before the crop is resized, in training and in inference,
  so interpolation cannot carry it into the pixels around the mask.
- A resume is only called exact when the enrolled records and their image bytes still hash the
  same, and when the model, optimizer, loss, dataset, validation and objective configs match.

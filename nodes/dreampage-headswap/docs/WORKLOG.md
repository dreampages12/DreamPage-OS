# Worklog

Chronological record of who changed what, so the project lead can pick the thread back up
without re-reading every file. Newest session last.

## Session 1 — Codex (project lead)

Established the repository: the three-input contract, the mask, crop and composite preservation
core, typed contracts, the DreamFace encoder, DreamSwap and DreamRefine, the backbone abstraction
with a native tiny flow backbone and an optional FLUX Klein BASE 4B path, the loss suite, the
rights-validated data layer, benchmark and blind human-review infrastructure, the quality gate,
the training loop with exact resume, the synthetic overfit harness, and 17 tests covering masks,
crops, coordinate round trips, preservation and the quality gate.

Delivered `docs/CURRENT_WORKFLOW.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`,
`docs/LICENSE_AUDIT.md` and the `configs/` tree.

## Session 2 — Claude Code, standing in while the Codex limit was exhausted

Continued the same plan and changed no architectural decision. The scope was the layer the
repository was missing between the library and an operator: entry points, integration, tests and
the written record. Nothing in `src/dreampage_headswap/` was modified.

Added:

1. `scripts/preprocess_dataset.py` — rights-validated identity manifest in, cleaned manifest and
   audit report out. No face estimation; annotation stays unavailable without a licensed provider.
2. `scripts/generate_training_pairs.py` — deterministic identity-level splitting, then
   re-validates every written manifest together, so the leakage gate runs against what actually
   reached disk rather than against an in-memory list.
3. `scripts/benchmark.py` — `archive-baseline`, `record-run` and `compare`, over stored outputs
   only. The script cannot generate an image, which is what keeps the comparison honest.
4. `scripts/evaluate.py` — the quality gate applied to a stored result. It cannot report PASS.
5. `scripts/human_review.py` — create, store and summarize blind A/B packets.
6. `comfyui_dreampage_headswap/` — seven thin nodes over the standalone core, with the whole
   tensor-convention boundary in one module.
7. Four new test files, taking the suite from 17 to 107 tests in about five seconds on CPU.
8. `README.md`, `docs/DATASET.md`, `docs/TRAINING.md`, `docs/COMFYUI.md`, `benchmarks/README.md`
   and this worklog. `ARCHITECTURE.md` had been pointing at a `TRAINING.md` that did not exist.

### What the new tests cover

- `test_data_pairs.py`, 19 tests — the rights gate refusing incomplete consent and unenrolled
  customer data, duplicate-capture and mask-geometry rejection, deterministic pairing, identity
  and decoded-pixel split leakage, dataset shapes, and both dataset scripts end to end.
- `test_model_training.py`, 19 tests — forward shapes, gradients reaching the encoder *and* the
  identity adapter, seeded sampling, protected pixels surviving sampling, loss-suite refusals,
  checkpoint round trip, RNG restore, and the FLUX backbone refusing to load without a snapshot.
- `test_pipeline_nodes.py`, 29 tests — end-to-end inference, the unvalidated model never
  reporting PASS, the empty-mask no-op, debug artifacts, the inference CLI writing a lossless PNG
  with a provenance report, the conversion boundary, and every node's contract and behavior.
- `test_benchmark_review.py`, 17 tests — baseline archiving, run-record provenance, a result
  edited after its record being caught, mismatched inputs being caught, identity and pixel
  leakage into training being caught, unmeasured metrics staying null, and blind packets keeping
  the method hidden.
- `test_train_loop.py`, 6 tests — a real short run over an enrolled corpus, and the property
  worth protecting most: **resume is bit-exact**. Two steps plus a resumed two steps land on the
  same parameters as four straight steps. This was verified before it was asserted.

### Verified by hand, not only in tests

The tiny overfit run took the loss from 1.33 to 0.011 in 120 steps. The documented inference
command produced a lossless PNG, a provenance report and fourteen debug artifacts. The dataset
scripts, a six-step training run and a resumed run were all executed from the shell on a
generated corpus before the commands went into the README.

### Deliberately not done, and why

- **`train_identity_encoder.py` and `train_refiner.py`.** Both need an objective decision that
  belongs to the lead. The encoder trainer needs the contrastive objective wired to an approved
  multi-identity corpus with pose-aware sampling; the refiner trainer needs paired artifacts and
  an approved frozen identity teacher. Either one written as a thin copy of `train.py` would look
  like a training pipeline with no objective behind it.
- **Standalone `DP_DreamSwap` and `DP_DreamRefine` nodes.** Splitting them means either exposing
  the pipeline's stages as public API or duplicating the sampler inside the node package. The
  reasoning is written up in `COMFYUI.md`.
- **Anything needing approved data, real weights or a GPU.** Unchanged: no such evidence exists.

Nothing added in this session is trained, benchmarked or production ready, and the live ComfyUI
installation was not touched.

### Suggested next step for the lead

The roadmap's stated priority still holds: assemble the first approved, identity-disjoint
benchmark and a 10 to 100 pair overfit set, then prove the BASE 4B adapter path with gradients
and reconstruction on it. The infrastructure to enroll, audit, train, compare and review that
data is now in place and tested, so the blocking input is the data and the snapshot, not the code.

## Session 3 — Codex (project lead)

Rewrote the FLUX Klein BASE 4B bridge against the real Diffusers APIs: provenance-gated loading,
cached Qwen3 prompt embeddings, patch-channel VAE normalization, paired reference position ids,
BASE text CFG as a sampling-only operation, a scheduler-native sigma schedule, and an inference
reference cache that never caches a training graph. Added the contract tests that instantiate
real tiny Flux2, Qwen3 and AutoencoderKLFlux2 modules, and the evidence writer for them.

Added the dataset registry, the synthetic fixture generator, and per-capture mask channels.

**Found a real identity leak and fixed the inference half.** Downscaling could blend the
template's own face into neighbouring pixels before that face was suppressed, and the protected
latent anchor was encoded from the raw template. Suppression now happens at native resolution,
before padding and resizing, and the anchor uses the sanitized input. Wrote the regression tests
for it in `test_identity_isolation.py`.

Wrote `training/validation.py` and began wiring periodic validation into the loop. The session
ended at the usage limit partway through that work.

## Session 4 — Claude Code, standing in while the Codex limit was exhausted

Picked up exactly where session 3 stopped. The suite was red on arrival: eight errors and four
failures.

**Finished the leak fix.** The inference half was done; training still suppressed after the crop
was resized, which is the same bug on the other side. `flow_objective` now takes the dataset's
prepared crop, refuses a batch whose strategy differs from the one requested, and falls back only
for batches that have no prepared crop, such as the synthetic overfit fixture. The validation
sample grid was corrected the same way. The test that guards this was checked by reverting the
fix and confirming it fails.

**Made the red tests pass, as written.**

- `outside_difference_image` measured in float32, which rounded a real one-part-in-ten-billion
  change to zero. Measurement now normalizes in float64 through a named helper, with the reason
  recorded next to it.
- The ComfyUI image boundary clipped anything into range. It now clamps float roundoff below one
  8-bit step and refuses values materially outside `[0,1]`, because those mean a wrong range or
  colour space rather than noise.
- The eight FLUX contract tests errored inside setup on Diffusers 0.35.1. The guard now checks
  the version and the actual FLUX.2 symbols before importing anything, so this environment skips
  with a precise reason and the isolated environment still runs them.
- One of my own session-2 assertions was stale: suppression moved before the resize, so the mask
  edge now carries interpolated values. It asserts the eroded interior instead.

**Finished the validation work.** Periodic held-out validation, `checkpoint.best.pt` selected on
a configurable metric, sample grids, and the dataset fingerprint bound into checkpoint metadata
so a resume whose image bytes changed is refused. Validation saves and restores the random state,
so enabling it does not perturb exact resume, and a test asserts that.

**Resolved a config conflict.** The fixture generator wrote `dataset.validation_manifest` and
`training.validation_every`; the checkpoint code expected a top-level `validation` section. I
kept the section, migrated the generator, and made both old keys raise with a message pointing at
the new place. A config that only looks configured would never validate.

**Built the identity-encoder trainer** the lead had started on. It needed two honest views of one
person, so the pair format now records `source_headmasks` and the dataset can put the source
through the production crop. Batches are identity-aware, because the contrastive objective has no
negatives otherwise. Validation reports within-batch cross-view retrieval, and the trainer knows
that metric improves upwards. The fixture generator now emits a ready config for it.

The suite went from 107 to 154 tests, nine skipped: eight need the isolated FLUX environment, one
needs a machine without CUDA. Both trainers, the fixture generator and the inference command were
run from the shell on a generated corpus before anything went into the documentation.

Still not done, and still the lead's call: `train_refiner.py`, pose-aware view selection for the
encoder, standalone DreamSwap and DreamRefine nodes, and everything that needs approved data, the
real BASE 4B snapshot or a GPU. On the procedural fixture the encoder reaches perfect retrieval
by telling two coloured ellipses apart, which is the reason every number in this repository
carries its scope next to it.

## Session 5 — Claude Code, data acquisition and enrolment

Asked to prepare training data. I did not obtain any, and the reason is written up rather than
worked around: the well-known face datasets are all non-commercial or retracted, this is a
children's product, and the rights gate in this repository would refuse every one of them. What I
delivered instead is the research, the quality bar, and the tooling that stands between a folder
of photos and an enrolled corpus.

**Licence research, with sources.** `docs/DATA_ACQUISITION.md` records what FFHQ, CelebA,
CelebAMask-HQ, VGGFace2, MS-Celeb-1M and MegaFace actually permit, the five routes that are open,
and what a consent flow for customer captures would need under Norwegian and EU rules. The
findings are mirrored into `docs/LICENSE_AUDIT.md` as two new register sections.

The sharpest finding is a trap this stack was one careless import away from: several face-parsing
projects carry an MIT repository while their weights were trained on CelebAMask-HQ, whose terms
forbid commercial use of derived data. A permissive repository licence does not launder the
provenance of the weights inside it. SAM 2 is the defensible automated route, since Meta releases
its code and weights under Apache-2.0.

**`data/headmasks.py`.** Every capture needs a headmask before it can be enrolled, and there was
no way to obtain one. Providers now state the licence of whatever produced the mask and record
how much authority it has. Reviewed sidecar masks are the only ones that claim
`reviewed_external`. A box supplied by an operator can be rasterized as an ellipse, marked
`derived_geometric` so it is counted separately and never mistaken for a production page mask. A
model-backed provider is wired in code through `CallableMaskProvider`, which refuses to exist
without a licence string. The default provider produces nothing and says why, because an invented
mask is worse than a missing one.

**`scripts/ingest_dataset.py`.** One directory per person in, an enrolled manifest out. It
validates the rights record before creating any directory, normalizes orientation into lossless
copies, drops duplicates by decoded pixels, masks through an explicit provider, and reports every
accepted and rejected capture. A box measured before a capture needed rotation is refused rather
than silently misaligned, which is the sort of error that would otherwise show up as a model that
mysteriously will not converge.

**`scripts/dataset_report.py`.** "A good dataset" made checkable: eleven criteria with measured
values next to their targets, and a non-zero exit while gaps remain. Head resolution is measured
across the masked head rather than the image, because that is the resolution that actually
reaches the model. Pose, expression and lighting are reported as gaps when nobody recorded them,
never estimated.

Twenty-two new tests, mostly about what is refused. The whole chain was then run for real on a
generated raw folder: ingest, quality report, preprocessing, pair generation with the leakage
audit passing. The report correctly flagged the three genuine gaps in that corpus, which were
box-derived masks, unassigned splits and missing pose metadata.

The suite is 176 tests. The blocking input is still data, and it is now a consent and procurement
decision rather than a code one.

## Session 6 — Codex, continuation after reviewing Claude's sessions

Implemented the complete DreamRefine trainer: independently trained frozen identity teacher,
source and generated-image identity anchors, bounded residuals, artifact manifests with image
and generator hashes, held-out validation, best checkpoints and exact resume. Inference loads
the bundled teacher; serving does not depend on the original teacher checkpoint path. Added
`training/train_refiner.py`, `configs/training/refiner.yaml`, `scripts/make_refinement_fixture.py`,
`tests/test_refinement.py` and `docs/REFINEMENT.md`.

Fixed identity-encoder resume in later epochs, source-mask channel propagation, dataset option
propagation into validation, mask and generated-artifact fingerprint coverage, cross-split
generated-to-enrolled image leakage, and CUDA device canonicalization. Added independent encoder
checkpoint initialization and a GPU smoke command. Quality PASS still requires identity and face
quality measurements; preservation alone cannot certify a result.

Executed evidence under `runs/session6/`:

- Main suite: 188 tests, nine environment-dependent skips. Isolated Diffusers 0.37.1 environment:
  all ten FLUX contract tests passed, including real tiny Qwen3, VAE, transformer, BF16 backward,
  gradient checkpointing and native schedule equivalence. No pretrained weights in those tests.
- Four-step independent encoder training and six-step refiner training on procedural fixtures;
  refiner validation loss 0.0417096 to 0.0411103. These are colored shapes, not face quality evidence.
- RTX 3090: three BF16 optimizer steps, validation, checkpoint reload and FP32 inference;
  `cuda-smoke-v2/report.json` records zero changed pixels outside the mask and RETRY quality.
- Tiny fixed-noise overfit: loss 1.33175647 to 0.01085956 over 120 steps. Mechanical test only.
- Built a wheel in the isolated environment; no production ComfyUI dependencies upgraded.

Updated README, ARCHITECTURE, TRAINING, COMFYUI and ROADMAP to match the implementation.
The pretrained BASE 4B model and a suitable face corpus were still missing at this point.

## Session 7 — Codex, actual model and face-data acquisition (2026-09-12, in progress)

The user explicitly asked to continue training toward realistic head swaps. Confirmed that local
enrolled data still consisted only of procedural fixtures. Requested the location of an approved
real multi-capture corpus; no customer images were automatically enrolled.

Started downloading the official public BASE 4B Diffusers snapshot, pinned to
`a3b4f4849157f664bdbc776fd7453c2783562f4d`, using `scripts/download_flux_base.py`.
The script downloads 20 required files (15,980,151,379 bytes), verifies upstream content hashes
and writes provenance only after successful verification. It uses no account token and excludes
the duplicate standalone checkpoint. Download start is not model execution or training evidence.

Investigated additional public datasets from primary publisher pages. DigiFace1M and Multiface
carry non-commercial restrictions. Syn-Vis-v0 has CC0 images and CC-BY-SA curation, with paired
base/headshot variants. Its CGI style, adult female-only distribution, two correlated views and
missing reviewed headmasks make it unsuitable as the final child headswap corpus. A 32-identity
candidate subset is being downloaded for visual review and possible encoder pretraining.
No inferred DeepFace demographic scores are treated as ground truth.

**User correction, binding requirement:** training data must contain only realistic,
photorealistic images. Syn-Vis-v0 is rejected for its stylized/CGI appearance and must not be
enrolled or used even for encoder pretraining. No Syn-Vis image has been used for training.
Existing procedural runs remain software-test evidence only and must never initialize a
realistic production training run. Resume acquisition with this requirement, not the abandoned
Syn-Vis pilot plan above.

**Subsequent user approval requirement:** notify the user and obtain their approval of the
dataset before training in any form. This includes pretraining, fine-tuning, refiner training and
optimizer smoke/test runs. Data review and weight acquisition may continue. No training has run
since this instruction; the active BASE download only retrieves and hashes files. The requirement
is also recorded in the project `AGENTS.md` for future Codex/Claude continuations.

**Acquisition completed:** all 20 BASE files verified against upstream hashes; total
15,980,151,379 bytes. Receipt: `local_data/models/flux-klein-base-4b/dreampage_provenance.json`.
This is now a real downloaded model snapshot, not just a bridge scaffold.

Added `configs/data/photoreal_candidates.json` and `scripts/prepare_photoreal_candidates.py`:
inference-only generation of twelve proposed images of four fictional children, three views each,
with recorded prompts/seeds/source weights and an HTML review. Every output remains unapproved.
This is a small source-quality pilot, not a complete training corpus. No new training code is
called by the script; model parameters are frozen and inference mode is used throughout.

CPU prompt encoding was started, then stopped before producing a cache because it was too slow.
An attempt to release idle ComfyUI model memory correctly refused when a new job appeared. No
active job was interrupted and no cached models were released. Asked the user to notify when GPU
jobs are finished. Candidate images have not yet been generated. Resume with GPU prompt encoding
only when memory is available:

```powershell
.venv-flux-test/Scripts/python.exe scripts/prepare_photoreal_candidates.py --stage encode --text-device cuda
.venv-flux-test/Scripts/python.exe scripts/prepare_photoreal_candidates.py --stage sample
```

Verified Python syntax for `src`, `scripts`, `training` and the Comfy nodes with compileall.
Did not rerun training/optimizer tests after the user's approval requirement.
Loaded the actual local tokenizer and checked all thirteen candidate prompts (twelve image
prompts plus empty CFG text): longest 177 tokens, below the configured 256-token limit. No prompt
truncation and no training was involved in this check.

Current run receipts and remaining requirements are consolidated in `docs/IMPLEMENTATION_STATUS.md`.

## Session 8 — Manual dataset collection instructions (2026-09-13)

The user asked how to assemble and deliver the images manually. Prepared a receiving folder,
`local_data/fra_tobias/`, with five empty per-person folders and a Norwegian LES_MEG.txt.
The suggested first batch is five identities with about eight distinct photographic views each,
explicitly a review pilot rather than a sufficient final training corpus. The user can submit one
person first for quality feedback. Instructions cover framing, pose/expression/lighting variety,
photo-realism, actual identity consistency for AI-generated variants, original files and source/
rights records. No images have been added, enrolled, generated or trained in this session.
The current next step is reviewing the user's supplied first batch; dataset approval is still pending.

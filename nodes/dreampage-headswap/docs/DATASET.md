# Dataset

Two manifests, both JSONL, both explicit. Nothing is discovered by scanning a folder of customer
orders, and nothing enters training because it happened to be on disk.

`docs/DATA_ACQUISITION.md` covers where data may legitimately come from and what a good corpus
has to contain. This document is the format and the tooling once it is here.

## Identity manifest

One JSON object per line. One line is one person, with at least two distinct captures.

```json
{
  "identity_id": "consented_0001",
  "split": "train",
  "age": 6,
  "synthetic": false,
  "rights": {
    "provenance": "studio session 2026-03-14, contract DP-114",
    "license": "perpetual research and commercial use, signed release on file",
    "consent": {"status": "granted", "reference": "DP-114/rel-03", "training_permitted": true},
    "training_permitted": true,
    "commercial_use_permitted": true,
    "customer_data": false,
    "explicit_training_enrollment": false
  },
  "images": [
    {"image_id": "image_001", "path": "consented_0001/image_001.jpg", "headmask": "consented_0001/image_001_mask.png"},
    {"image_id": "image_002", "path": "consented_0001/image_002.jpg", "headmask": "consented_0001/image_002_mask.png"}
  ]
}
```

Relative paths resolve against the manifest's own directory. `split` is optional; when it is
absent the split is derived from a hash of the identity, which is deterministic and identical
across machines.

### What the rights gate rejects

Every one of these raises rather than warns:

- a missing or non-granted consent record, or consent without an auditable reference
- consent that does not explicitly permit training
- `training_permitted` or `commercial_use_permitted` that is anything other than `true`
- `customer_data: true` without `explicit_training_enrollment: true`
- a `synthetic: true` row without an explicit opt-in from the caller

Customer images may be used for inference under the product's privacy policy. That is a
different permission from training, and the code treats it as one.

## Ingest

```powershell
python scripts/ingest_dataset.py --root data/raw --output-dir data/enrolled --rights data/rights.json --mask-provider sidecar --ages data/ages.json
```

One directory per person, several captures inside each. Ingest validates the rights record
before writing anything, normalizes each capture's orientation into a lossless copy, obtains a
headmask through an explicit provider, drops duplicates by decoded pixels, and reports every
accepted and rejected capture. A capture it could not mask is rejected, never enrolled with an
invented mask.

Mask providers live in `data/headmasks.py`. Reviewed sidecar masks are preferred and are the only
ones that claim reviewed authority. `--mask-provider sidecar-then-box` with a `--boxes` file draws
an ellipse from a head box you supply, recorded as `derived_geometric` so the quality report can
count it. A box measured before a capture needed rotation is refused rather than silently
misaligned. Model-backed providers are wired in code through `CallableMaskProvider`, which
requires the weights' licence to be stated.

## Measuring the corpus

```powershell
python scripts/dataset_report.py --identities data/enrolled/identities.jsonl --report data/enrolled/quality.json
```

Scores identity count, captures per identity, head resolution measured across the mask rather
than the image, sharpness, mask authority and coverage, duplicates, split population, ages and
supplied pose metadata. Each criterion reports pass or gap with the measured value next to its
target, and the exit code is non-zero while gaps remain. It measures the corpus, never a model.

## Preprocessing

```powershell
python scripts/preprocess_dataset.py --identities data/identities.jsonl --output-dir data/clean --min-width 64 --min-height 64 --min-laplacian-variance 20
```

Each capture is checked for file integrity, minimum resolution, blur, canonical EXIF
orientation, and an authoritative headmask that matches the image's own dimensions, is not empty,
and does not cover the whole frame. Exact duplicate captures are found by decoded pixels, not by
filename, and **all** copies are rejected rather than silently deduplicated. An identity with
fewer than two surviving captures is dropped, with the reason recorded.

Face detection, landmarks, pose and segmentation are not performed. The preprocessing report
carries an annotation block that says `available: false` with a reason, until a licensed
calibrated provider implements the `AnnotationProvider` protocol and is passed in explicitly. A
bounding box is not a yaw angle, and the report never pretends otherwise.

The outputs are `identities.clean.jsonl`, which can be fed straight back through the same rights
gate, and `preprocess_report.json`, which records every accepted and rejected capture.

## Pairs

```powershell
python scripts/generate_training_pairs.py --identities data/clean/identities.clean.jsonl --output-dir data/pairs --max-pairs-per-identity 8
```

The implemented strategy is `same_identity`: one capture of a person supplies the identity, a
different capture of the same person supplies the template, pose, expression and lighting, that
capture's own headmask defines the editable region, and that same capture, undegraded, is the
ground truth. The target's face is degraded before it reaches the model, so the model cannot
learn to copy the identity that is already in the template.

A target without a headmask cannot become a pair. Sources and targets must be distinct captures,
by decoded pixels as well as by path.

Register new strategies in `PAIR_STRATEGIES`. The file format is stable across strategies, so a
cross-identity or curated-pair strategy needs no downstream change.

Each row records `source_headmasks` alongside `sources` when enrolment masked the source
captures. Identity-encoder training needs it: without the source's own mask the two views are a
whole photo and a head crop, and a contrastive objective will happily learn that difference
instead of the face. The list must hold one mask per source capture or loading refuses it.

One manifest is written per split. The script then re-reads everything it wrote, together, and
runs the full audit on the files as they exist on disk, which is the only version of the audit
that can be trusted.

## The dataset registry

`dataset_registry.json` names every manifest in the enrolled corpus with its hash, which is what
turns "the manifests I was handed" into "the whole corpus". Real, non-synthetic data requires
one: the audit has to know its own scope before it can claim an identity appears in one split.
Adding an unregistered manifest afterwards is refused, and a hash that no longer matches is an
error rather than a warning.

A registry cannot discover identities nobody enrolled, and it cannot decide that two differently
named records are the same person. Resolving one stable identity per person is enrolment's job,
and every leakage guarantee in this repository rests on it being done correctly.

## The leakage audit

`validate_pair_manifests` checks every supplied manifest as one corpus, before any split
filtering:

- one identity appears in exactly one split
- pair identifiers are unique across all manifests
- every referenced asset exists
- no image content crosses a split boundary, checked by file hash **and** by decoded pixels, so a
  re-encoding or a re-crop-free copy under a new filename is still caught
- source and target are not the same capture

`benchmark` runs the same audit from the other side: a benchmark identity that appears in a
supplied training or validation manifest is an error, and so is benchmark image content that
appears in training. The audit can only see the manifests it is given, so the report records
which ones were checked and marks itself incomplete when none were supplied.

## Splits

Splitting is by identity, never by image. `identity_split` hashes the identity with a seed, so
the assignment is stable, reproducible and independent of manifest ordering. The defaults are 80
percent train, 10 percent validation, 10 percent test.

Benchmark and test identities stay out of training even when the templates are synthetic.

## A runnable fixture

```powershell
python scripts/make_synthetic_dataset.py --output-dir runs/fixture --identities 8 --captures 3
```

Procedural coloured shapes, never people. It writes identities, pairs per split, a registry, a
notice file, and two ready configs: one for the flow trainer and one for the identity encoder.
Use it to exercise plumbing end to end. Every artifact it touches is labelled a synthetic
fixture, and results from it are never quality evidence: on this corpus the encoder reaches
perfect retrieval by telling two coloured ellipses apart.

## Loading

`PairDataset` reads a pair manifest, filters to one split, and uses the production crop geometry
and the authoritative mask. It also prepares the identity-suppressed condition crop, suppressing
the native template before the crop is resized, so the trainer never has to do it late. With
`source_crops=True` the source view goes through the same crop as the target.

It returns the template crop, the prepared condition crop, the ground-truth crop, the mask, the
references, the geometry condition and the age, with unavailable geometry flagged as unavailable
rather than zero-filled and forgotten. Requesting more references than an identity has enrolled
is an error at construction, not a surprise at step 4000.

## Retention

Debug artifacts contain child references. `save_debug` writes only where it is explicitly told
to. Metrics tracking is local JSONL by default and never uploads images or identities. Any
external tracker must be checked against the product's retention policy before it is enabled.

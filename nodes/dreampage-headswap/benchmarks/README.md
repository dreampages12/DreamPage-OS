# Benchmarks

This directory holds enrolled benchmark cases and frozen baseline archives. It is empty of real
cases on purpose: there are none yet, and an invented one would be worse than none.

## What a case is

One case fixes the three inputs, and both systems must have been run on those exact files. The
comparison tool verifies this by hash and refuses to proceed otherwise. It cannot generate an
image itself, which is what keeps a current-versus-new comparison from quietly becoming a
new-versus-new one.

`cases.jsonl`, one object per line:

```json
{
  "case_id": "frontal_to_three_quarter_001",
  "identity_id": "consented_0042",
  "split": "test",
  "tags": ["strong_three_quarter", "warm_light", "generated_template"],
  "synthetic": false,
  "source": "inputs/0042_child.png",
  "template": "inputs/0042_template.png",
  "headmask": "inputs/0042_mask.png",
  "current_result": "results/0042_current.png",
  "new_result": "results/0042_new.png",
  "current_run": "runs/0042_current.run.json",
  "new_run": "runs/0042_new.run.json",
  "ground_truth": "inputs/0042_truth.png"
}
```

`ground_truth` is optional and only exists for reconstruction-style cases. Paths resolve against
the manifest's directory.

## Enrolling a case

1. Freeze the baseline once, with checksums and no execution:

   ```powershell
   python scripts/benchmark.py archive-baseline --workflow ..\books\fotballstjernen\workflow_api.json --config ..\books\fotballstjernen\config.json --destination benchmarks/baseline_v6
   ```

2. Run each system yourself, outside this tool, on the identical input files.

3. Record each run. The record is an attestation: it stores the input, result, workflow, config
   and checkpoint hashes, and the caller is responsible for these having been the real inputs.

   ```powershell
   python scripts/benchmark.py record-run --source inputs/0042_child.png --template inputs/0042_template.png --headmask inputs/0042_mask.png --result results/0042_current.png --workflow benchmarks/baseline_v6/workflow.json --config benchmarks/baseline_v6/config.json --method-id current_klein_v6 --destination runs/0042_current.run.json --latency-ms 8200 --peak-vram-bytes 12000000000 --measurement-protocol "warm run, one warmup, excludes model load" --hardware "RTX 3090 24GB"
   ```

   A latency or VRAM number without a measurement protocol and hardware is refused. Two numbers
   measured differently are not a comparison.

4. Compare, supplying every training and validation manifest so the leakage audit is complete:

   ```powershell
   python scripts/benchmark.py compare --manifest benchmarks/cases.jsonl --output-dir runs/benchmark --training-manifest data/pairs/pairs.train.jsonl --training-manifest data/pairs/pairs.validation.jsonl
   ```

   The report marks itself incomplete when no training manifest was supplied. Read that field
   before quoting the numbers.

## Coverage

The report lists which recommended tags are missing. Aim to cover all of them:

frontal to frontal, slight three-quarter, strong three-quarter, opposite angle, looking up,
looking down, different gaze, happy, sad, neutral, closed mouth, challenging lighting, warm
light, cold light, small face, large face, different hairstyle, hair crossing the mask boundary,
realistic template, generated template, high-resolution template, low-resolution reference.

Every case needs at least one tag. An untagged case is refused.

## What is measured, and what is not

Measured today: outside-mask error and exact-preservation, the changed-region percentage, the
boundary band, and reconstruction error against ground truth when it exists. Latency and VRAM are
compared only when both runs report the same hardware and protocol.

Reported as null with a reason: identity similarity, local identity, pose, expression, perceptual
difference, realism, age preservation and failure rate. Each needs a licensed calibrated
evaluator or adjudicated human review. They are not approximated.

The boundary metric is a change magnitude. It is not a seam-quality or realism score, and the
report says so next to the number.

## Human review

Automatic metrics cannot answer "which looks more like this child". `scripts/human_review.py`
builds blind packets: A and B order randomized per trial, images re-encoded to strip metadata,
no method names or original paths anywhere in the voter directory, and a private assignment key
kept separately. Voters can answer `cannot_judge`, and the summary reports raw preference counts
rather than a score.

## Synthetic fixtures

`synthetic: true` requires `--allow-synthetic`, and every report and comparison grid that touches
one is labelled as an integration fixture rather than a quality benchmark. Keep fixture cases out
of this directory's real case manifests.

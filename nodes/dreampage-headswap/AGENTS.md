# User requirements — 2026-09-12

**Updated 2026-09-21:** the user explicitly selected **Klein 9B** for training.
4B is retired as a training target. Do not train, select, download or silently fall
back to 4B. The configured default is the existing standard/distilled Klein 9B;
BASE 9B is a distinct explicit variant, not an automatic substitution. The rules
below about photorealism and explicit dataset approval remain unchanged.

Read `docs/WORKLOG.md` and inspect current files before continuing another agent's work.

The user explicitly requires **only photorealistic images in the training dataset**.
Stylized/CGI/cartoon/procedural images must not enter training, including identity-encoder
pretraining or refinement. Existing procedural checkpoints are test artifacts, not initialization
for the realistic model. The downloaded Syn-Vis candidate is rejected and must not be enrolled.

The user explicitly requires **notification and their approval of the dataset before any
training of any kind starts**. This applies to pretraining, fine-tuning, refiner training,
optimizer smoke runs and tests that execute training. Earlier general instructions to continue
training do not override this later requirement. Do not fabricate or infer approval from elapsed
time. First prepare a concrete dataset review with example images, sources/rights, quality
findings, identity splits and an exact manifest hash; then ask for approval and wait.

Read-only investigation, downloading licensed model weights, preparing candidate data,
inference without optimization, code edits and checks that do not train remain authorized.
Do not automatically enroll customer inference images. Do not stop or interrupt active ComfyUI
jobs to obtain GPU memory.

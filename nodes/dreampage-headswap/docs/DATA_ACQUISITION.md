# Getting training data

Researched 2026-09-11; updated with binding user requirements 2026-09-12. This is the plan for obtaining identities we are actually allowed to
train on, and the reasoning behind each route. `DATASET.md` describes the format once data
exists; this document is about how it gets here.

The familiar datasets audited below do not meet this project's rights requirements. Other
sources must be evaluated individually; this is not a claim that every public face dataset is
unusable. Commissioned captures, explicitly licensed data and carefully reviewed photorealistic
synthetic images remain possible routes. Customer photos require explicit training enrollment.

**User requirements:** only photorealistic images may enter training, including encoder
pretraining. Show the exact dataset, example images, provenance and quality findings to the user
and obtain their approval before any training. The Syn-Vis-v0 candidate was rejected for CGI style;
no image from it has been trained on. Existing procedural runs are historical software tests.

## What this repository will not do

No scraping. No downloading a research dataset into a commercial product. No inferring consent
from the fact that a customer uploaded a photo. Enrolment refuses a corpus whose rights record
is incomplete, and that refusal is the point rather than an obstacle to work around.

## The public datasets are closed to us

| Dataset | Licence | Usable here |
| --- | --- | --- |
| FFHQ | CC BY-NC-SA 4.0, and NVIDIA states it should not be used to develop facial recognition | No |
| CelebA / CelebA-HQ | Academic research only | No |
| CelebAMask-HQ | Non-commercial research; explicitly forbids commercial exploitation of derived data | No |
| VGGFace2 | CC BY-NC-SA 4.0 | No |
| MS-Celeb-1M, MegaFace | Retracted by their publishers | No, on ethics as well as rights |

All of them are also adult-dominated web imagery, which is the wrong domain for a children's
product even where the licence would have allowed it.

**The trap to watch for:** a permissively licensed repository whose weights were trained on one
of these. Several BiSeNet face-parsing projects carry an MIT licence on the code while the
checkpoint was trained on CelebAMask-HQ, whose terms forbid commercial use of derived data. MIT
on a repository does not launder the provenance of the weights inside it. `headmasks.py` makes
every provider state its weights' licence for exactly this reason, and
`docs/LICENSE_AUDIT.md` is where the decision gets recorded.

## Routes that are open

### 1. Consented customer captures, opt-in

A source of real, in-domain child identities at the resolution and framing the product
actually sees. It needs work outside this repository; commissioned or licensed captures are
other potential sources.

What the code already enforces: `customer_data: true` requires `explicit_training_enrollment:
true`, plus a consent record whose `training_permitted` is explicitly true and which carries an
auditable reference. Inference permission is not training permission, and the rights gate treats
them as different things.

What the product would need to add:

- A separate, unbundled opt-in at order time. Not a term buried in the purchase conditions,
  since consent that is a condition of the service is not freely given.
- Parental consent, verifiable. Norway's digital consent age is 13, with a proposal to raise it
  to 15 that was intended to enter into force in summer 2026; confirm the current status before
  building the flow. For a children's book product the realistic answer is parental consent in
  every case.
- A face is special-category biometric data once it is processed to identify a person, which
  puts training on it under explicit-consent terms and heightened protection for children.
  Datatilsynet has treated children's data as an aggravating factor in recent enforcement.
- Withdrawal that actually works: a record linking each enrolled capture back to the consent that
  permits it, so a withdrawal can remove the capture, retire the checkpoints trained on it, or
  both. Decide which before collecting, not after.
- Several captures per child, because one photo cannot make a training pair. The opt-in should
  ask for three or more.

Treat this as a legal decision with an engineering consequence, not the other way round. Get it
reviewed before the first enrolment.

### 2. Commissioned captures with signed releases

A photo session with model releases that explicitly permit AI training and commercial use. Slow
and expensive per identity, and for children it means guardian releases, but the rights story is
clean and the capture conditions can be designed: several angles, several expressions, several
lighting setups per child, which is exactly what the benchmark needs and what web imagery never
provides.

This is the realistic way to build the first honest benchmark, where a few dozen well-covered
identities are worth more than thousands of scraped ones.

### 3. Licensed vendor data

Vendors now sell rights-cleared, consent-collected face data for AI training, including sets
with multiple captures per subject spanning years, and stock libraries have begun offering
explicitly AI-training-licensed collections. Useful for adult identities and for pretraining the
encoder on general facial structure.

Before buying, check four things, because they are where these deals fail: does the licence
cover model training and commercial deployment rather than just viewing; does it include minors
and on what basis; are there several captures per subject; and does the vendor pass on
withdrawal obligations from their subjects to you.

### 4. Synthetic identities from a permissively licensed generator

The stack already targets FLUX.2 Klein BASE 4B, whose weights are Apache-2.0. Generating
consistent synthetic identities from text avoids enrolling actual customer references. It may
provide photorealistic candidate images, but the output still needs visual review for artifacts,
identity drift and appearance; the model's license alone is not a quality guarantee.

Generated images remain correlated with the generator's distribution and may preserve its errors.
Use only photorealistic examples reviewed and approved by the user. Synthetic validation cannot
demonstrate generalization to real child references; the real-data benchmark remains separate.
`scripts/prepare_photoreal_candidates.py` performs inference only and leaves every candidate
unapproved. It must not start a training loop or automatically enroll its output.

### 5. Templates we already own

The identity side is the hard part; the template side is not. DreamPage owns its book
illustrations and their prepared headmasks, across twenty-plus books. Those are in-domain, rights
clean, and already carry the exact masks the pipeline treats as authoritative. They are what the
benchmark's template column should be built from, paired with consented child references.

## What "a good dataset" means here, concretely

`scripts/dataset_report.py` measures a corpus against these and names each gap. The thresholds
are arguments, not beliefs; the defaults are a starting position.

| Criterion | Default target | Why this and not something else |
| --- | --- | --- |
| Distinct identities | 200 or more | Held-out identities and in-batch contrastive negatives both come out of this number |
| Captures per identity | 3 or more | Two makes a pair; three lets the source view vary independently of the target |
| Head resolution | 256 px on the shorter side of the masked head | The model crops around the head, so this is the resolution that actually reaches it, not the image size |
| Sharpness | Laplacian variance 40 or more | A blurred reference cannot carry identity |
| Reviewed masks | 90 percent or more | Box-derived masks cut hair, ears and chin at the boundary |
| Mask coverage | 60 percent of the frame or less | A mask over most of the frame leaves no protected context to preserve |
| Head inside the frame | every capture | A head at the edge leaves no context for the padded crop |
| Duplicates | none | A repeated capture across splits invalidates every held-out number |
| Splits | at least two identities in each | Anything less cannot be evaluated |
| Ages | recorded for every identity | Age preservation cannot be measured for a child whose age nobody wrote down |
| Pose, expression, lighting | recorded for every capture | Nothing here estimates them, and the benchmark's coverage list depends on them |

Beyond the counts, the corpus needs the coverage the benchmark asks for: frontal and
three-quarter views, opposite angles, up and down, gaze changes, happy, sad and neutral, closed
mouth, warm, cold and difficult lighting, small and large heads, several hairstyles, and hair
crossing the mask boundary. That is a capture plan, which is why route 2 keeps coming back.

## Getting from photos to an enrolled corpus

```powershell
python scripts/ingest_dataset.py --root data/raw --output-dir data/enrolled --rights data/rights.json --mask-provider sidecar --ages data/ages.json
python scripts/dataset_report.py --identities data/enrolled/identities.jsonl --report data/enrolled/quality.json
python scripts/preprocess_dataset.py --identities data/enrolled/identities.jsonl --output-dir data/clean
python scripts/generate_training_pairs.py --identities data/clean/identities.clean.jsonl --output-dir data/pairs
```

Ingest expects one directory per person. It validates the rights record before writing anything,
normalizes each capture's orientation into a lossless copy, obtains a headmask through an
explicit provider, drops duplicates by decoded pixels, and writes a report naming every accepted
and rejected capture. A capture it could not mask is rejected rather than enrolled with an
invented mask.

Where reviewed masks do not exist yet, `--mask-provider sidecar-then-box` with a `--boxes` file
will draw an ellipse from a head box you supply. Those masks are recorded as
`derived_geometric`, the quality report counts them separately, and they should not be what a
printed page is masked with. A box measured before a capture needed rotation is refused rather
than silently misaligned.

For a model-backed provider, wire it in code with `CallableMaskProvider` and state the weights'
licence there. SAM 2's code and weights are Apache-2.0, which makes a promptable segmenter with a
supplied box the most defensible automated route. Record whatever you choose in
`docs/LICENSE_AUDIT.md` before it produces a single enrolled mask.

## The order I would do this in

1. Get the consent flow reviewed, because it gates the only in-domain source and takes the
   longest.
2. Commission or collect a small, well-covered benchmark set, identity-disjoint from everything
   else, and pair it with owned templates. The first honest comparison against the current
   workflow needs nothing more than this.
3. Review only photorealistic candidate images, with multiple consistent captures per identity,
   and obtain explicit approval of the complete manifest before considering training.
4. Enrol consented customer captures as they arrive, and re-run the quality report each time to
   see which coverage gaps are still open.

Sources:

- [FFHQ licence, NVlabs](https://github.com/NVlabs/ffhq-dataset/blob/master/LICENSE.txt)
- [FFHQ dataset terms and intended use](https://github.com/NVlabs/ffhq-dataset)
- [CelebAMask-HQ non-commercial terms](https://github.com/switchablenorms/CelebAMask-HQ)
- [Can I use this publicly available dataset to build commercial AI software?](https://arxiv.org/pdf/2111.02374)
- [MegaFace retraction, Exposing.ai](https://exposing.ai/megaface/)
- [Segment Anything 2, Meta AI](https://ai.meta.com/blog/segment-anything-2/)
- [Data protection law in Norway, CMS Expert Guide](https://cms.law/en/int/expert-guides/cms-expert-guide-to-data-protection-and-cyber-security-laws/norway)
- [AI regulation in Norway, CMS Expert Guide](https://cms.law/en/int/expert-guides/ai-regulation-scanner/norway)
- [Norway data privacy law and Datatilsynet](https://www.recordinglaw.com/world-laws/world-data-privacy-laws/norway-data-privacy-laws/)
- [Rights-cleared AI data licensing](https://blog.depositphotos.com/rights-cleared-ai-data-licensing.html)
- [Defined.ai and Getty Images commercially safe training datasets](https://www.barchart.com/story/news/30355803/definedai-announces-strategic-engagement-with-getty-images-to-deliver-high-quality-commercially-safe-image-datasets-for-ai-training)
- [Commercial face dataset listings](https://axonlab.ai/face-recognition-datasets/)

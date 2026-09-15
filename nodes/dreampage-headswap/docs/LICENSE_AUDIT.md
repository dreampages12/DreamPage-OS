# License and provenance register

Audit date: **2026-09-11**. This is a technical inventory and release gate, not a legal opinion or a completed software bill of materials. Code licenses, weight licenses, training-data rights, and a customer's inference permission are separate records. Missing evidence means **unapproved**, not commercially cleared. No external weights or datasets are redistributed by this project.

## Backbone decision

Use **`black-forest-labs/FLUX.2-klein-base-4B`** as the initial optional pretrained training target. BFL identifies the Base variants as undistilled and suitable for adaptation. The **4B family is Apache-2.0; the 9B family is under the FLUX Non-Commercial License**. Commercial local 9B use requires separate rights. The existing file named `flux-2-klein-9b.safetensors` is not evidence of those rights. [BFL family overview](https://bfl.ai/models/flux-2-klein), [BFL local training and licensing](https://help.bfl.ai/articles/7108141705-can-i-run-or-fine-tune-flux-2-klein-locally).

| Asset | Evidence / status | Decision |
| --- | --- | --- |
| FLUX.2 Klein BASE 4B | Official model card: Apache-2.0, undistilled; external weights not included | Preferred optional backbone; retain license/notices and record exact revision/hash before use. [Model card](https://huggingface.co/black-forest-labs/FLUX.2-klein-base-4B) |
| FLUX.2 Klein 4B distilled | Same Apache-2.0 family; four-step variant | Possible later speed comparison, not the selected fine-tuning baseline. [Official model inventory](https://github.com/black-forest-labs/flux2) |
| FLUX.2 Klein 9B and BASE 9B | Non-commercial public weights; commercial contract not inspected | Not a default dependency; existing production grant must be documented separately. [BASE 9B card and license link](https://huggingface.co/black-forest-labs/FLUX.2-klein-base-9B) |
| Installed `flux-2-klein-9b.safetensors` | Existing active graph, approximately 18.16 GB; provenance not authenticated | Record source URL, commit, SHA-256, variant and commercial grant before importing into this stack |
| FLUX.2 VAE | Existing `flux2-vae.safetensors`; optional new adapter uses the VAE from the approved BASE 4B snapshot | Use snapshot component provenance; do not infer that a similarly named local file has the same rights/hash. [BASE 4B files](https://huggingface.co/black-forest-labs/FLUX.2-klein-base-4B/tree/main) |
| Qwen3-4B text weights | BASE 4B uses Qwen3 text conditioning; official Qwen card Apache-2.0 | Optional approved-snapshot component, not an identity encoder. [Qwen3-4B card](https://huggingface.co/Qwen/Qwen3-4B) |
| Qwen3-8B text weights / installed Q8 GGUF | Official original weights Apache-2.0; local GGUF quantizer/source/hash unrecorded | Record derivative provenance and notices before reuse. [Qwen3-8B card](https://huggingface.co/Qwen/Qwen3-8B) |
| Existing BFS headswap LoRA | Name references Klein 9B; disconnected in inspected graph; author/data/license not recorded | Unapproved for the new stack; base-weight obligations remain relevant |
| `4x-UltraSharp.pth` | Active whole-image legacy upscaler; download source, training provenance and applicable terms not verified | Not imported; do not infer rights from permissively licensed ESRGAN implementations |
| `bbox/face_yolov8m.pt` | Active legacy child detector; actual checkpoint publisher/data not verified | Not imported; review exact weight provenance and Ultralytics terms |
| DreamFace / native DreamSwap / DreamRefine | New project-owned implementation; no pretrained face weights bundled | Project code ownership does not imply the randomly initialized model is trained or rights to future training data |

## Existing face software that must not silently become a dependency

The filesystem contains `models/insightface/inswapper_128.onnx`, `buffalo_l` detection/recognition files, and `models/insightface/models/antelopev2/` files including `glintr100.onnx` and `genderage.onnx`. AdvancedLivePortrait imports InsightFace. These are **not on the active inspected Klein graph**. `uniface_256.onnx` is also present, with unverified provenance.

InsightFace's code is MIT, but its supplied pretrained models and annotated training data are restricted to non-commercial research without a separate license. That applies to manual and automatic downloads. The new identity encoder and evaluator must not auto-load these local weights or present their embeddings as commercially approved. A separate commercial grant must cover the exact asset and usage; otherwise train an encoder on approved data or select a separately audited alternative. [InsightFace upstream licensing](https://github.com/deepinsight/insightface#license), [Python package model policy](https://github.com/deepinsight/insightface/tree/master/python-package#license).

Ultralytics publishes AGPL-3.0 and Enterprise licensing paths. Its own guidance calls for Enterprise terms for proprietary commercial integration that cannot meet AGPL obligations; the legacy face checkpoint's separate provenance still needs review. No YOLO implementation or weights are added to the new core. [Ultralytics licensing](https://www.ultralytics.com/license).

## Libraries

The following is the direct implementation/optional dependency register. `pyproject.toml` is the install authority; optional availability is not proof that its integration ran. A versioned transitive dependency and CUDA-runtime SBOM remains a release task.

| Library | License / source | Use and obligation |
| --- | --- | --- |
| PyTorch | BSD-3-Clause; installed legacy environment `2.5.1+cu121`. [License](https://github.com/pytorch/pytorch/blob/main/LICENSE) | Tensors/training; retain notices, inventory bundled third-party/runtime licenses |
| NumPy | BSD-3-Clause. [License](https://github.com/numpy/numpy/blob/main/LICENSE.txt) | Array/image plumbing; retain notices |
| SciPy | BSD-3-Clause and bundled component notices. [License](https://github.com/scipy/scipy/blob/main/LICENSE.txt) | Mask morphology/distance transforms |
| Pillow | MIT-CMU and bundled component notices. [License](https://github.com/python-pillow/Pillow/blob/main/LICENSE) | Image I/O; preserve relevant notices |
| PyYAML | MIT. [License](https://github.com/yaml/pyyaml/blob/main/LICENSE) | Safe configuration parsing |
| Diffusers | Apache-2.0. [License](https://github.com/huggingface/diffusers/blob/main/LICENSE) | Optional FLUX implementation only; code license does not license every model |
| Transformers | Apache-2.0. [License](https://github.com/huggingface/transformers/blob/main/LICENSE) | Optional local Qwen text encoder |
| Accelerate | Apache-2.0. [License](https://github.com/huggingface/accelerate/blob/main/LICENSE) | Optional offload/distributed ecosystem; validate actual training support separately |
| Safetensors | Apache-2.0. [License](https://github.com/huggingface/safetensors/blob/main/LICENSE) | Optional external model serialization |
| Hugging Face Hub | Apache-2.0. [License](https://github.com/huggingface/huggingface_hub/blob/main/LICENSE) | Optional model snapshot tooling; no automatic child-data upload |
| TensorBoard | Apache-2.0. [License](https://github.com/tensorflow/tensorboard/blob/master/LICENSE) | Optional local experiment logging; no child image logging by default |
| pytest | MIT. [License](https://github.com/pytest-dev/pytest/blob/main/LICENSE) | Development tests only |
| setuptools | MIT. [License](https://github.com/pypa/setuptools/blob/main/LICENSE) | Build backend |
| Python standard library | PSF and bundled notices. [License](https://docs.python.org/3/license.html) | Runtime and local CLI/reporting |

PEFT, bitsandbytes, LPIPS, face recognizers, image segmentation models, external datasets, remote W&B logging and external refinement weights are **not implicitly approved by being named in a design**. Add asset-level records before introducing them. A metric without an approved trained evaluator must remain unavailable; substituting a random encoder would manufacture evidence.

The old host contains ComfyUI (GPLv3), LanPaint (GPLv3), CropAndStitch (GPLv3), Impact Pack (GPLv3), Impact Subpack (AGPLv3), and ComfyUI-GGUF (Apache-2.0), as verified from each installed `LICENSE`/`LICENSE.txt`. The new package does not copy their code. The independently executable ML core and thin optional ComfyUI layer are separated for maintainability; that separation alone is **not** a legal determination about combined distribution or derivative works. Resolve applicable obligations before proprietary redistribution. [GPLv3 text](https://www.gnu.org/licenses/gpl-3.0.html), [AGPLv3 text](https://www.gnu.org/licenses/agpl-3.0.html).

## Dataset and experiment admission

No customer/order images are an automatic training source. An inference request is not training consent. No face dataset was downloaded for this implementation. Procedurally generated synthetic test fixtures are engineering tests, not evidence of realistic human identity transfer.

Every future source needs: source owner and URL, license text/version, explicit commercial ML training permission, consent/permitted-use evidence, retention/deletion conditions, intended split and identity identifier, acquisition date, and asset digest. Track synthetic data generator weights and their terms as well. Evaluation/research-only permission cannot be silently upgraded to commercial training permission. Approval metadata is an admission control, not independent proof that a declaration is true.

Before model release, archive exact upstream license texts and notices; pin code/model revisions and hashes; export the dependency SBOM; confirm training/evaluation provenance; and document any commercial grants. Unknown legacy assets remain outside the default stack while implementation and synthetic tests continue.

## Headmask providers

Added 2026-09-11. Every capture needs a headmask before it can be enrolled, so the question of where masks come from is now a rights question with a code path. `src/dreampage_headswap/data/headmasks.py` requires each provider to state the licence of whatever produced the mask, and records it per capture in the manifest.

| Provider | Rights position | Decision |
| --- | --- | --- |
| Reviewed masks prepared by the enrolling organization | Owned with the capture | Preferred. The only source that claims `reviewed_external` authority |
| Geometry from an operator-supplied head box | Project-owned geometry; no third-party weights and no detector | Approved for bootstrapping enrolment. Marked `derived_geometric`, counted separately in the corpus report, and not suitable as a production page mask |
| Face-parsing checkpoints trained on CelebAMask-HQ | Repository licence is often MIT while the weights derive from a dataset that forbids commercial use of derived data | **Not approved.** An MIT repository does not launder the provenance of the weights inside it |
| Segment Anything 2 | Meta releases SAM 2 code and weights under Apache-2.0; the SA-1B dataset has its own separate terms | Most defensible automated route, prompted with a supplied box. Pin the exact checkpoint, revision and hash, and record it here before it produces an enrolled mask. [SAM 2 release](https://ai.meta.com/blog/segment-anything-2/) |
| Any other segmentation model | Unassessed | Wire it through `CallableMaskProvider` with its weights' licence stated in code, and add a row here first |

No segmentation weights are bundled, downloaded or selected automatically by this project. The default provider produces nothing and explains why.

## Public face datasets

Assessed 2026-09-11 for commercial training use. None of the commonly cited datasets is usable here, and the reasoning, the open routes and the consent requirements are in `docs/DATA_ACQUISITION.md`.

| Dataset | Terms | Decision |
| --- | --- | --- |
| FFHQ | CC BY-NC-SA 4.0; publisher states it should not be used to develop facial recognition | Not approved. [Licence](https://github.com/NVlabs/ffhq-dataset/blob/master/LICENSE.txt) |
| CelebA, CelebA-HQ | Academic research only | Not approved |
| CelebAMask-HQ | Non-commercial research; forbids commercial exploitation of derived data | Not approved, and see the headmask table above. [Terms](https://github.com/switchablenorms/CelebAMask-HQ) |
| VGGFace2 | CC BY-NC-SA 4.0 | Not approved |
| MS-Celeb-1M, MegaFace | Retracted by their publishers | Not approved on ethics as well as rights. [MegaFace](https://exposing.ai/megaface/) |

Consented customer captures remain a separate admission decision that requires an unbundled opt-in, verifiable parental consent, and a withdrawal path, not a code change.

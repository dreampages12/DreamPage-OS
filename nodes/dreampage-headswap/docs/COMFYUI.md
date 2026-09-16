# ComfyUI integration

ComfyUI is an integration layer. The stack in `src/dreampage_headswap/` runs, trains and is
tested without it, and no model logic lives in the node package.

Nothing in this document has been applied to the running ComfyUI installation. The production
workflow is untouched.

## Installing

The nodes need `dreampage_headswap` importable by the same interpreter ComfyUI runs on.

```powershell
C:\DreamPage-OS\DreamPage-image\venv\Scripts\python.exe -m pip install -e C:\DreamPage-OS\nodes\dreampage-headswap
New-Item -ItemType Junction -Path C:\DreamPage-OS\DreamPage-image\custom_nodes\dreampage_headswap -Target C:\DreamPage-OS\nodes\dreampage-headswap\comfyui_dreampage_headswap
```

The junction means the nodes ComfyUI loads and the nodes the tests import are the same files.
Restart ComfyUI and the seven nodes appear under **DreamPage/HeadSwap**.

## Conventions

ComfyUI passes images as `B,H,W,C` floats in `[0,1]` and masks as `B,H,W`. The core uses RGB
`H,W,C` arrays and `B,C,H,W` tensors. All of that translation lives in `conversion.py`, and it is
strict on purpose:

- an image batch handed to a single-image input raises instead of silently using the first frame
- a mask outside `[0,1]`, or a non-finite image, raises
- alpha is dropped explicitly, never blended
- masks are never inverted and never resized to fit; a mask that does not match the template is a
  mistake worth surfacing

White means editable, which is ComfyUI's own convention for `MASK` and the opposite of nothing.

## Nodes

| Node | In | Out |
| --- | --- | --- |
| `DP_LoadHeadSwapModel` | config path, device, optional checkpoint | `DP_PIPELINE`, checkpoint metadata |
| `DP_UseHeadMask` | mask, expand, feather | original, generation and blend masks, report |
| `DP_PrepareTemplateCrop` | template, mask, resolution, context | `DP_CROP`, crop image, crop mask, transform |
| `DP_CompositeToTemplate` | template, generated crop, `DP_CROP` | final image, preservation report |
| `DP_EncodeChildIdentity` | pipeline, child images | `DP_IDENTITY`, summary |
| `DP_QualityCheck` | template, result, mask, threshold | report, status, preservation score |
| `DP_HeadSwapPipeline` | everything, in one node | image, quality, debug, preservation score |

### DP_HeadSwapPipeline

The production node. Child references, template and headmask in; the finished page out. It runs
identity encoding, the crop, geometry, generation, optional refinement, compositing and the
quality gate internally.

Settings are `identity_strength`, `refine_strength`, `mask_expand`, `mask_feather`, `steps`,
`seed`, `quality_threshold`, and optionally `crop_resolution`, `crop_context`, `degradation`,
`age`, `debug` and `debug_dir`. A `crop_resolution` or `crop_context` of zero means "keep what the
config says", so the node does not quietly override a configured pipeline.

Age is a float where `-1` means unknown. Unknown is not zero, and the model is told which it is.

`refine_strength` above zero without a loaded DreamRefine checkpoint raises rather than silently
skipping refinement.

The inference YAML can set `refiner.checkpoint` to a checkpoint produced by
`training/train_refiner.py`. It includes its own frozen identity encoder, so the node uses the
same identity representation as refiner training. See `REFINEMENT.md` for the artifact and
teacher requirements. No retraining or separate refinement node is needed to load that bundle.

Setting `debug_dir` writes every intermediate stage as a file: the processed masks, the head
crop, the identity-suppressed template the model actually saw, the raw generation, the refined
generation, the final composite and the outside-mask difference image. Those files contain child
references, so the node writes them only where it is told to.

### DP_UseHeadMask

Expansion widens the region the model may *look at*. It never widens the region the model may
*write to*: the blend mask is clamped to the supplied mask, and the node's report states whether
that held. The current production graph expands by 35 pixels, which does change the effective
edited region; that is a deliberate difference from this package's default of zero, not an
oversight to copy.

### DP_PrepareTemplateCrop and DP_CompositeToTemplate

These two are usable on their own, and that is the point. Any generator that can produce an image
at the crop's exact model resolution can be composited back with the hard preservation guarantee:
protected pixels are copied from the original template after all arithmetic, so the result is
byte-identical outside the supplied mask. The existing Klein workflow can be routed through them
without waiting for a trained DreamSwap checkpoint.

The composite node refuses a crop of the wrong resolution rather than resampling it into place.

### DP_QualityCheck

Returns the full quality report, a status and the preservation score. `PASS` requires calibrated
providers that do not exist yet, so today the honest outcomes are `RETRY`, which means measured
preservation with unavailable identity and realism metrics, and `FAIL`, which means protected
pixels moved.

## Nodes that were deliberately not built

`DP_DreamSwap` and `DP_DreamRefine` as separate graph nodes would require exposing the pipeline's
internal stages as public API, or duplicating the sampling loop inside the node package. The
second is how integration layers start owning model logic, which is the thing this package is
supposed to avoid. Splitting them is worth doing behind a proper stage API. It is a decision for
the project lead, not a side effect of writing nodes.

## Testing

`tests/test_pipeline_nodes.py` covers the node contract, the conversion boundary and a real run
through the loader, the encoder and the pipeline node on the tiny backbone, including that the
template outside the mask comes back unchanged. The tests import the package directly and need no
ComfyUI installation, which is the whole reason the boundary is drawn where it is.

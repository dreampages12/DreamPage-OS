# ComfyUI integration

ComfyUI is an integration layer. The stack in `src/dreampage_headswap/` runs, trains and is
tested without it, and no model logic lives in the node package.

The integration is installed in DreamPage OS. The separate Studio workflow uses normal
Klein 9B; book production workflows remain separate.

## Test workflow: ordinary Klein 9B

Open **LAB-DreamPage-HeadSwap** in DreamPage Image's workflow list. Refresh the browser
after updating the extension. Select the three inputs in group 02:

1. **Person**: a sharp portrait showing the full head and hair.
2. **Original scene**: the image in which the head should be replaced.
3. **Headmask**: a matching image of exactly the scene's dimensions. White permits edits;
   black protects the original. Keep `mask_channel = red` for a grayscale mask.

Click **Run**. Group 06 shows the final image and a before/after review board. Files go to
the configured ComfyUI output directory under `DreamPage/Studio/`. Start with the supplied
4 steps, fixed seed, native sampler and zero color correction. Inspect hair, likeness,
pose and the neck seam; the protected-pixel check does not certify visual quality.

Mobile JPEG/MPO containers are supported: `mpo_frame = 0` selects the primary photo.
The report records the container, embedded frame count and selected frame. Additional
frames may be alternate views or HDR gain maps; leave this at zero for normal photos.
Actual animations are still rejected. Source files are never modified by the loader.

The graph includes all nine **DreamPage/Studio** nodes: LoadPhoto, ReferenceStudio,
IdentityEncoder, SceneStudio, SwapPrompt, KleinConditioning, DreamSwap, SeamFinish and
ReviewBoard. Optional `view_2` and `view_3` on ReferenceStudio accept additional photos
of the same person. Optional source masks isolate the head in wider reference photos.

IdentityEncoder uses the pretrained FLUX.2 VAE; it is not a newly trained face encoder.
SeamFinish performs deterministic blending. No LoRA, custom trained checkpoint,
training execution or automatic dataset enrollment is involved.

Rebuild and install from the OS root with `python tools/headswap.py studio`.
The builder checks live node schemas and available model/image selections before writing.
Previous installed workflow revisions are backed up under `state/headswap/workflow-backups`.

## Installing

The nodes need `dreampage_headswap` importable by the same interpreter ComfyUI runs on.

```powershell
C:\Users\tobia\AppData\Local\Programs\Python\Python310\python.exe -m pip install -e C:\DreamPage-OS\nodes\dreampage-headswap
New-Item -ItemType Junction -Path C:\DreamPage-OS\DreamPage-image\custom_nodes\dreampage_headswap -Target C:\DreamPage-OS\nodes\dreampage-headswap\comfyui_dreampage_headswap
```

The junction means the nodes ComfyUI loads and the nodes the tests import are the same files.
On a new installation, restart ComfyUI when idle. Seven checkpoint-based nodes appear
under **DreamPage/HeadSwap** and nine native inference nodes under **DreamPage/Studio**.

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

## Native and checkpoint-based paths

`DP_DreamSwap` now exists in the native Studio path and delegates sampling to ComfyUI.
The older checkpoint-based pipeline described above is a separate integration; it requires
appropriate trained weights and is not part of the ordinary Klein 9B Studio workflow.
There is no trained standalone `DP_DreamRefine` node in this workflow.

## Testing

`tests/test_pipeline_nodes.py` covers the node contract, the conversion boundary and a real run
through the loader, the encoder and the pipeline node on the tiny backbone, including that the
template outside the mask comes back unchanged. The tests import the package directly and need no
ComfyUI installation, which is the whole reason the boundary is drawn where it is.

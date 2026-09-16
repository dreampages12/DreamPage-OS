# Current DreamPage workflow

Inspected 2026-09-11, read-only. No customer images were opened, executed, copied, or admitted to training. The representative graph is `C:/DreamPage-OS/books/fotballstjernen/workflow_api.json`; a loader/settings scan of all 23 `books/*/workflow_api.json` files found the same Klein 9B, Qwen GGUF, four-step LanPaint, and crop-mask settings. This records wiring, not a quality benchmark.

## Three production inputs

| Input | Actual graph entry and route | Role |
| --- | --- | --- |
| Child reference | `LoadImage` **194** → face YOLO **174/175** → head/hair segment crop **177** → batch **180** → resize **188** (1.3 MP) → `VAEEncode` **119** | Source identity, supplied as an image latent reference |
| Template | `LoadImage` **192** → `InpaintCropImproved` **184** → `VAEEncode` **150** | Existing illustration, target placement and context; also initial inpaint latent |
| External headmask | `LoadImageMask` **165**, **red** channel → crop **184**, crop mask → `SetLatentNoiseMask` **152** | White/nonzero pixels are editable; supplied per page, not detected from the child |

`books/fotballstjernen/config.json` associates `page_key`, `template_image`, `mask_image`, and optional `face_expression`. Its configured template/face IDs (151/121) are stale for the actual graph. `script/regen_page.py:detect_nodes` discovers valid nodes; `render_variants` patches the actual template, child, mask, output prefix and seed before queueing. Consequently the filenames embedded in the static JSON are examples, not authoritative customer/page selection. The same three inputs must be recorded in every future comparison case.

## What FLUX sees

The active model loader **126** names `flux-2-klein-9b.safetensors`, located under `models/diffusion_models/`. Its name and four-step use match the distilled 9B variant; the file's original download revision/license grant have not been authenticated. The workflow does **not** load a BASE checkpoint. The VAE loader **102** names `flux2-vae.safetensors`.

The prompt encoder is **193**, `CLIPLoaderGGUF`, loading **Qwen3-8B-Q8_0.gguf**. Despite the generic CLIP node label and `type: stable_diffusion`, the referenced weights are Qwen3 text weights. The child is encoded by the image VAE, not by Qwen and not by a dedicated learned identity encoder. The node title mentioning IPAdapter at **180** is stale; no active IPAdapter is wired.

Prompt **196** describes identity transfer, template pose/expression, and matched lighting. `ReferenceLatent` **112** appends the template crop latent; **118** appends the child head latent. **100** adds Flux guidance 6. `comfy_extras/nodes_edit_model.py:ReferenceLatent.execute` appends `reference_latents`; `comfy/model_base.py` routes these to FLUX, and `comfy/ldm/flux/model.py:_forward` concatenates reference image tokens with the generated image tokens using separate position IDs. The original template face remains visible in its reference latent. Source/template identity separation is requested largely through the prompt.

The sampled model connects directly to loader **126**. LoRA **161** names `bfs_head_v1_flux-klein_9b_step3500_rank128.safetensors` but is **disconnected**; prompt **195** and zero-conditioning **136** are also outside the active output dependency chain. Their presence is not evidence of active training or conditioning.

## Crop, generation and composite

Crop **184** uses Lanczos, no pre-resize, hole filling, mask expansion **35 pixels**, blend **32 pixels**, high-pass **0.1**, context factor **1.5**, output **1024×1024**, and padding multiple **32**. These are existing settings, not defaults adopted by the replacement. In particular expansion changes the effective allowed region relative to the supplied mask.

Sampler **156**, `LanPaint_KSampler`, receives the masked template latent and both-reference positive conditioning. It runs **4 Euler/simple steps**, CFG **1**, denoise **1**, two LanPaint inner steps, and **Image First**. The negative text **107** is connected, but ordinary negative-CFG influence should not be assumed with CFG 1. LanPaint's implementation overrides sampling and supplies its own inpainting settings.

`VAEDecode` **104** → `InpaintStitchImproved` **183** restores the crop to the saved canvas using crop offsets and a blend mask → **4x-UltraSharp.pth**, **300/301**, upscales the **whole page** → `SaveImage` **9**. The stitcher preserves pixels outside its blend support by design; the final whole-page neural upscale changes resolution and image pixels, so the saved output is not an exact-pixel copy of the original outside the supplied headmask.

## Useful conventions and unknown quality

Preserve the three explicit inputs, authoritative template background, page-specific prepared masks, crop/stitch coordinate metadata, seeds, and independent per-page outputs. Replace prompt-only identity control, uncontrolled target-face leakage, default mask enlargement, and page-wide enhancement in the strict preservation path.

The graph provides useful production mechanisms for context, inpainting, and local stitching. Without consented paired outputs and human ratings, it is not possible to say which cases look good or measure identity/realism failures. Target-identity leakage, source-pose transfer, age drift, plastic texture and boundary mismatch are **hypotheses to test**, not measured findings. Benchmark the current pre-upscale stitch as well as its actual delivered output, recording resolution handling explicitly; do not quietly resize one system and call the metrics directly comparable.

Implementation evidence: `script/regen_page.py`, `nodes.py:LoadImageMask`, `custom_nodes/ComfyUI-GGUF/nodes.py:CLIPLoaderGGUF`, `custom_nodes/LanPaint/src/LanPaint/nodes.py:LanPaint_KSampler`, and `custom_nodes/ComfyUI-Inpaint-CropAndStitch/inpaint_cropandstitch.py:InpaintStitchImproved`. None of this production code was modified or copied into the new ML package.

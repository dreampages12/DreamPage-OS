# nodes/ — og hvilke custom nodes systemet faktisk trenger

## DreamPage sine egne noder

Disse er våre. De ligger her, i git, og junctes inn i
`DreamPage-image/custom_nodes/` av `tools/migrate/phase1_build_image.ps1`.
Det er slik vi utvider ComfyUI uten å redigere den.

| Mappe | Nodeklasser | Brukt av |
|---|---|---|
| `dreampage-headswap/` | `DP_LoadHeadSwapModel`, `DP_EncodeChildIdentity`, `DP_PrepareTemplateCrop`, `DP_UseHeadMask`, `DP_HeadSwapPipeline`, `DP_CompositeToTemplate`, `DP_QualityCheck` | **ingen produksjons­workflow** |
| `comfyui_head_hair_mask_guard/` | `HumanHeadHairMaskGuard` | `user/default/workflows/Head_Hair_Mask_FullSize_Fast.json` (operatørverktøy for headmasker) |

### `dreampage-headswap` er ikke i produksjonsveien

Dette er verdt å vite, for det er lett å tro noe annet. Jeg søkte gjennom 200
workflow-filer på maskinen: **ingen av de 24 bokworkflowene refererer en
enkelt `DP_*`-klasse.** Headswappen i produksjon gjøres med hyllevare —
FLUX.2 Klein + LoRA + LanPaint + InpaintCropAndStitch + Ultralytics
ansiktsdeteksjon + den håndtegnede headmasken.

Oppdatert kontroll 20.09.2026: ComfyUI på konfigurert port 8189 registrerer
**alle 16 DreamPage-noder**: de sju kjernenodene over og ni Studio-noder
(`DP_LoadPhoto`, `DP_ReferenceStudio`, `DP_IdentityEncoder`, `DP_SceneStudio`,
`DP_SwapPrompt`, `DP_KleinConditioning`, `DP_DreamSwap`, `DP_SeamFinish`,
`DP_ReviewBoard`). Den tidligere påstanden om at Studio-nodene manglet var feil.

`python tools/headswap.py studio` bygger fra serverens faktiske kontrakter og
installerer `LAB-DreamPage-HeadSwap.json` i GUI-lista. Workflow-verktøyet bevarer
denne eksplisitte LAB-fila ved synkronisering. Bokworkflowene bruker fortsatt
sin eksisterende pipeline. Å bygge LAB-grafen sender ingen GPU-jobb.

Treningsprosjektet, modellkvitteringen og lokale data er bevart under
`nodes/dreampage-headswap/`. Eget miljø, datasettreview og versjonerte
fresh/resume/finetune-kjøringer beskrives i [MODEL-TRAINING.md](../docs/MODEL-TRAINING.md).
Ingen trening starter før Tobias har godkjent det konkrete fotorealistiske datasettet.

## Custom nodes som MÅ være installert for at bøkene skal bygges

Utledet, ikke gjettet: `tools/node_requirements.py` leser hver `class_type` i
alle 24 `books/*/workflow_api.json` og sporer den til noden som registrerer
den. Maskinlesbar utgave i `nodes/required.json`.

Alle 24 bøkene bruker **samme 26 nodeklasser**. 18 av dem er ComfyUI-kjerne.
De 8 øvrige kommer fra fem pakker:

| Pakke | Klasser | Rolle |
|---|---|---|
| `ComfyUI-GGUF` | `CLIPLoaderGGUF` | laster Qwen3-8B-Q8_0 som tekstkoder |
| `comfyui-impact-pack` | `BboxDetectorSEGS`, `SEGSToImageList`, `ImageListToImageBatch` | finner ansiktet i malen |
| `comfyui-impact-subpack` | `UltralyticsDetectorProvider` | `bbox/face_yolov8m.pt` |
| `ComfyUI-Inpaint-CropAndStitch` | `InpaintCropImproved`, `InpaintStitchImproved` | beskjærer til hodet og syr tilbake |
| `LanPaint` | `LanPaint_KSampler` | selve inpaintingen, 4 steg |

Mangler én av dem, får du ikke en oppstartsfeil. Du får en prompt som avvises
med *«Cannot execute because node X does not exist»* — midt i en betalt ordre.

### De 41 andre

41 av de 44 installerte pakkene brukes ikke av bokproduksjonen:
IPAdapter, InstantID, ReActor, PuLID, ControlNet-aux, WanVideo, LivePortrait,
KJNodes, RMBG, segment-anything og resten. De er rester etter tidligere
generasjoner av pipelinen og eksperimenter i GUI-et.

De kopieres likevel **verbatim** inn i `DreamPage-image`, og det er et bevisst
valg:

- Flere av dem har ingen egen `.git`, så lokale endringer kan ikke oppdages.
  Notatet om at PuLID/ControlNet/Kontext-hooken må patches manuelt og mistes
  ved node-oppdatering peker nettopp på en slik node. En reinstallasjon via
  Manager ville stille mistet patchen.
- De brukes av operatørens GUI-workflows, som ikke er versjonert noe sted.
- 2,46 GB er ikke verdt risikoen ved å rydde.

To tredjeparts-noder har lokale endringer som *kan* ses (de har git):
`ComfyUI-WanAnimatePreprocess` (`models/onnx_models.py` endret) og
`Comfyui_Redux_Advanced` (en eksempelfil slettet). Ingen av dem er i
bokveien.

## Modellstier

`config/extra_model_paths.yaml` genereres av `python tools/models.py paths`
fra de faktiske undermappene i `models/`, pluss aliasene custom nodes ber om
under andre navn.

Det siste er ikke pedanteri. Første utgave listet ComfyUI sine standard­nøkler,
og da så `UltralyticsDetectorProvider` **null** modeller:
`models/ultralytics/` er ikke en standardnøkkel — Impact Subpack registrerer
den selv og ber om `ultralytics`, `ultralytics_bbox` og `ultralytics_segm`.
Hver eneste bokside ville feilet på

```
model_name: 'bbox/face_yolov8m.pt' not in []
```

Det ble fanget av å faktisk kjøre en side gjennom det nye imaget, ikke av å
sammenligne nodelister — de var identiske (2067 mot 2067) mens modellene
fortsatt var usynlige.

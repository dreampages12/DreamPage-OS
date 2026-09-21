# DreamPage OS — migreringsplan

> **HISTORISK DOKUMENT. Migreringen er gjennomført.** Fasene 0–7 er ferdige
> (se «Status» i `README.md`), `C:\ComfyUI` finnes ikke lenger, og n8n eier
> ingen del av ordreveien. Denne fila beskriver hvordan systemet kom hit, og
> beholdes fordi den forklarer *hvorfor* mappestrukturen ser ut som den gjør
> — ikke fordi noe her skal utføres. Vil du vite hvordan systemet er i dag:
> `README.md`, `CLAUDE.md` og `docs/ARCHITECTURE.md`.

Generert 2026-09-15. Kilde: DREAMPAGE-OS-BUILD-PROMPT.md + kartlegging av
`C:\ComfyUI` (untracked produksjonskode inne i en ComfyUI-klone).

## 0. Situasjonsbilde (verifisert 2026-09-15 22:45)

| Ting | Status |
|---|---|
| ComfyUI | kjører, pid 21040, port 8188, **system-Python** 3.10.11 (ikke `venv/`), base `C:\ComfyUI`, v0.21.0 |
| n8n | kjører, pid 7556, port 5678, db 14,4 GB |
| Worker-workflow | `xy8qiRUzcBpH52CI` «Dreampage Worker v2 (med fremdrift)», **active=1**, 82 noder |
| Inntak-workflow | `G0skxlQwcLhDH3NT` «My workflow 3», **active=1**, 11 noder: Webhook → RabbitMQ. Dette er produsenten (WooCommerce → kø) og er *utenfor* migreringen |
| dp_bot | kjører, pid 18504, scheduled task «DreamPage dp_bot» → `ensure_dp_bot.ps1` hvert 5. min |
| Mockup-server | kjører, pid 6720, port 8790 |
| cloudflared | Windows-tjeneste «Cloudflared», **Running**, `--token` (fjernstyrt ingress) for tunnel `d9b1ec20…` = `admin.dreampage.store → localhost:3000` |
| `.dreampage-comfy.lock` | finnes ikke nå → ingen ordre i arbeid |
| Diskplass | `C:\ComfyUI` = ~335 GB, ledig på C: = **185 GB** |

### Konsekvens av diskplassen

Det er **ikke plass til å kopiere** `C:\ComfyUI`. Navnebyttet må være en
`Move-Item` på samme volum (metadataoperasjon, umiddelbar). All kopiering
begrenses til vår egen kode (< 1 GB).

## 1. Mappe-mapping

`books/orders/` er 72,4 GB av `books/` sine 73 GB — kundeartefakter, ikke git.
Selve bokdefinisjonene er ~0,6 GB.

| Fra (`C:\ComfyUI\…`) | Til (`C:\DreamPage-OS\…`) | Merknad |
|---|---|---|
| *hele treet* | `DreamPage-image\` | `Move-Item`, samme volum |
| `books\<slug>\{config.json,workflow_api.json,base\,script\,*.png}` | `books\<slug>\` | i git |
| `books\<slug>\orders\` | blir liggende under `books\<slug>\orders\` | **ikke** i git |
| `script\<locale>\` (nb, nn, sv, en-US, en-GB) | `flow\text\<locale>\` | **flyttes som hele mapper** — se §3 |
| `script\` ekte pipeline (se §4) | `flow\` | i git |
| `script\patch_*`, `fix_*`, `rewrite_*`, `tune_*`, `update_*` | `archive\` | etter gjennomgang, §4 |
| `script\*.ttf`, `DreamPage_logo.png`, `blank-back.png`, `dreampage-first.png`, `bakside\`, `logo\`, `lastpages\`, `ryggrad\` | `assets\` | §3 |
| `config\` | `config\` | `dp_bot.json` → `.gitignore` (token) |
| `server\dp-mockup-server\` | `server\dp-mockup-server\` | beholdes, egen prosess |
| `dreampage-headswap\` (uten `.venv-flux-test`, `runs`, `build`) | `nodes\dreampage-headswap\` | junction inn i `DreamPage-image\custom_nodes` |
| `state\` | `state\` | **ikke** i git |
| `output\` | `output\` | **ikke** i git, `--output-directory` |
| `input\` (1,94 GB maler + headmasker) | `input\` | **ikke** i git, `--input-directory` |
| `models\` (159 GB) | `models\` | **ikke** i git, `--extra-model-paths-config` + manifest |
| `tmp\` | `tmp\` | **ikke** i git |
| `venv\` (4,9 GB, ubrukt av ComfyUI) | blir i `DreamPage-image\venv` | brukes bare av headswap-pakka |

### Hvordan ComfyUI får stier utenfor seg selv

`comfy/cli_args.py` har `--output-directory`, `--input-directory`,
`--temp-directory`, `--user-directory`, `--extra-model-paths-config`.
Alle settes på kommandolinja fra `dreampage.ps1`, så **ingen fil inne i
`DreamPage-image\` endres** — regelen fra §4 i oppdraget holder.

## 2. Sti-inventar (fullt i `docs/path-inventory.txt`)

175 hardkodede `C:\ComfyUI`-treff i 75 `.py`-filer under `script\`, pluss:

**Vår kode**

- `books\*\config.json` × 24: `textScript`, `textScripts` (17 språknøkler hver), `prepareScript`, `orderBasePath`
- `books\*\script\prepare_order_*.py` × 14: `BOOK_ROOT`, `COMFY_OUTPUT_ROOT`, `SHARED_SCRIPT_DIR`
- `script\dp_order.py`: `DB`, `CACHE_DIR`, `BOOKS_DIR`, `INPUT_DIR`, og `C:\ComfyUI\output` i `resolve()`
- `script\ensure_dp_bot.ps1`, `script\start_dp_bot.ps1`: bot-sti + 3 loggstier
- `server\dp-mockup-server\data\templates.json`: `mapsDir`, `psdPath` × 3

**Ikke vår kode — lett å glemme**

- `custom_nodes\comfyui-impact-pack\impact-pack.ini` → `custom_wildcards`
- `custom_nodes\was-ns\was_suite_config.json` → `wildcards_path`
- `custom_nodes\dreampage_headswap` = **JUNCTION** → `C:\ComfyUI\dreampage-headswap\comfyui_dreampage_headswap` (må lages på nytt)
- `dreampage-headswap\.venv-flux-test\…\comfyui_readonly_dependencies.pth` → `C:\ComfyUI\venv\Lib\site-packages` (+ `activate`, `activate.bat`, pip-shims)
- `venv\Lib\site-packages\dreampage_headswap-0.1.0.dist-info\direct_url.json` (editable install)
- Scheduled task «DreamPage dp_bot» → `ensure_dp_bot.ps1`
- `user\comfyui*.log`, `user\default\ComfyUI-Manager\` (regenereres)
- Ingen `extra_model_paths.yaml` finnes (bare `.example`) → modellene ligger in-tree

**n8n-databasen** — 24 av 82 noder har hardkodet sti:
`Edit Fields`, `Setup Order Dirs`, `Pages Config`, `Get History`,
`Read Cover PDF`, `Read Innersider PDF`, `Read Template`, `Read Config File`,
`Save Child Image`, `Build Gelato PDF`, `Cleanup Comfy Folder`,
`Cleanup Book Input Folder (READY)`, `Check Page Output`,
`Acquire/Release/Release(Error) Comfy Lock`, `Claim Post-Comfy Order`,
`Build Next Cover Title`, `Upload Continue Cover`, `Build Last Page`,
`Stamp QR On Innersider`, `Record Gelato Draft`, `Build Face Variants`,
`Auto Merge Multibook`.

### Sikkerhetsnett

`mklink /J C:\ComfyUI C:\DreamPage-OS\DreamPage-image` rett etter flytting.
n8n-nodene rettes deretter i ro. Junctionen fjernes **helt til slutt**, og så
kjøres en ordre til — så lenge den finnes er inventaret uverifisert.

## 3. To funn som endrer planen

**(a) Lokalemappene er selvstendige bunter, ikke bare tekstfiler.**
`script\nb\` inneholder 69 filer: 16 `<bok>-text-nb.py` **pluss egne kopier**
av `build_gelato_pdf.py`, `gelato_cover.py`, `dream_pdf_guard.py`,
`dream_text_layout.py`, fontene, `DreamPage_logo.png` og `blank-back.png`.
Tekstscriptene gjør bare `from gelato_cover import …` og stoler på at
scriptets egen mappe er på `sys.path`. Derfor flyttes hver lokalemappe som
**én udelt enhet** til `flow\text\<locale>\`; da følger søskenfilene med og
importene virker uendret. Tekstscriptene blir *ikke* spredt inn i
`books\<slug>\` — det ville brutt alle importene.

**(b) `dp_order.py` leser payloads fra n8n sin SQLite.**
`resolve()` → `find_execution()` → `republish_job.load_payload(execution_id)`.
Cachen `state\orders\<job_key>.json` er redningen: den har allerede formatet
`{order_id, execution_id, payload, overrides}`. **Fra fase 2 skriver `flow` den
cachefila selv ved inntak**, med `execution_id: null`. Da fungerer boten,
`reprint_order.py` og `finish_order.py` uendret etter at n8n er borte — og
`continue_code` overlever, som er hele poenget.

## 4. Klassifisering av `script\` (68 `.py` + 53 `.backup*`)

**Ekte pipeline → `flow\`** (14)
`build_gelato_pdf.py`, `build_last_page.py`, `gelato_cover.py`,
`dream_pdf_guard.py`, `dream_text_layout.py`, `drive_upload.py`,
`dp_order.py`, `dp_bot.py`, `dp_merge.py`, `dp_testbook.py`,
`auto_merge_multibook.py`, `gelato_merge.py`, `regen_page.py`,
`reprint_order.py`

**Operativt verktøy → `flow\tools\`** (12)
`finish_order.py`, `finish_merged_order.py`, `refresh_merged_draft.py`,
`republish_job.py`, `rerun_order_comfy.py`, `render_next_cover.py`,
`make_headmask.py`, `make_shorthair_templates.py`, `make_darkskin_templates.py`,
`upscale_2x_ultrasharp.py`, `sync_title_params.py`, `n8n_credential.py`

**Engangs-patcher → `archive\`** (≈30)
`patch_worker_*` (14), `patch_title_tester_*` (6), øvrige `patch_*`,
`fix_*` (7), `rewrite_*` (2), `tune_*` (2), `update_title_tester_params.py`,
`motet_story.py`, `worker-continue-qr.patched.json`,
`build_gelato_pdf_without_explicit_blank_back.py`

**Før arkivering (§7 i oppdraget):** hver `patch_worker_*.py` leses for logikk
som ikke finnes i noden den patcher. Funnene skrives i `archive\README.md`.
Kandidatene som må migreres til `flow` uansett, fordi de ER dagens oppførsel:
`patch_worker_page_output_scope.py` (sidesjekk kun i egen mappe),
`patch_worker_comfy_restart_resilience.py`, `patch_worker_job_key.py`,
`patch_worker_continue_qr.py`, `patch_worker_next_cover_persist.py`,
`patch_worker_gelato_url.py` (100 MB / `drive.usercontent`).

**`*.backup-before-*`** (53 filer): tas med i første commit som historikk,
deretter slettes de i en egen commit. Git er versjonskontrollen etterpå.

## 5. Faser og porter

| Fase | Innhold | Port |
|---|---|---|
| 0 | `git init` + **første commit av all egen kode**, kopiert (ikke flyttet) til `C:\DreamPage-OS\`. Ingen produksjonsfil røres. | koden finnes i git |
| 1 | `Move-Item` av treet, junction som nett, sti-rewrite i vår kode + n8n + custom_nodes, `flow\paths.py` med én `ROOT` | ekte ordre gjennom n8n fra ny sti |
| 1b | fjern junction, kjør én ordre til | `C:\ComfyUI` finnes ikke |
| 2 | `flow` worker: RabbitMQ prefetch=1 + manuell ack, intern kø, side-løkke, deklarative steg. n8n kaller den som én node. Lås slettes. | to ordre samtidig kjører etter hverandre |
| 3 | SQLite jobb-DB + strukturert logging | «hvor stoppet ordre X» uten n8n |
| 4 | FastAPI i worker-prosessen, bearer-auth på alt, CORS mot dashbordets origin | alle endepunkt lokalt med auth |
| 5 | tekst → prepare → PDF → Drive → Gelato → Telegram → confirm. n8n **deaktiveres** | full ordre uten n8n |
| 6 | cloudflared: rute for API-et | `/api/health` utenfra, 8188/5678 ikke nåbare |
| 7 | panel, `dreampage.ps1`, modellmanifest | `up`/`down`/`status` |

## 6. Ett punkt som må avklares før fase 6

Tjenesten «Cloudflared» kjører i dag med `--token`, altså **fjernstyrt ingress
fra Cloudflare-dashbordet**, for tunnel `d9b1ec20…` som eksponerer
`admin.dreampage.store → localhost:3000`. En lokal `tunnel\config.yml` blir
ignorert av en token-tunnel. To veier:

1. Legg `desktop-tif6h5b.dreampage.store` til som public hostname på den
   eksisterende tunnelen i Cloudflare-dashbordet (eller via API-token).
   Rører ikke den kjørende tjenesten.
2. Konverter tjenesten til named tunnel med `tunnel\config.yml` som oppdraget
   beskriver. Da må ingressen for `admin.dreampage.store` skrives inn i samme
   fil, og tjenesten startes på nytt — kort avbrudd for admin-domenet.

Vei 2 er det oppdraget ber om og gir konfigurasjonen i git. Den krever
`cloudflared`-innlogging/API-tilgang. Dette avklares når fase 6 nås; fasene
1–5 er uavhengige av det.

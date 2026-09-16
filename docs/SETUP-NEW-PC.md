# Sette opp DreamPage OS på en ny PC

---

## ⚠️ Les dette før du kjører noe

**En ny maskin som starter `flow` med køen påslått begynner umiddelbart å ta
ekte kundeordre.**

`dreampage-jobs` er én kø med én konsument. Kobler maskin nummer to seg på,
fordeler RabbitMQ ordrene mellom dem — og halvparten av kundene får boka si
bygget på en maskin som kanskje mangler modeller, kunst eller riktig
`config/`. Ordren feiler, eller verre: den blir bygget feil.

Bestem derfor **først** hva denne maskinen er:

| | Hva den gjør | Hvordan |
|---|---|---|
| **Utvikling** | kode, tester, ingen ekte ordre | start flow med `--no-mq` |
| **Produksjon** | tar ekte ordre fra køen | bare **én** slik maskin om gangen |

Resten av guiden gjelder begge. Forskjellen er ett flagg i steg 8.

---

## 1. Krav

| | Versjon | Merknad |
|---|---|---|
| Python | **3.10** | ikke 3.11+ (se under) |
| Git | | |
| NVIDIA GPU | 24 GB VRAM | RTX 3090 i produksjon |
| Diskplass | ~40 GB | 28 GB modeller + repo + output |
| Tailscale | | RabbitMQ-brokeren nås bare over tailnettet |

**Hvorfor 3.10 og ikke nyere:** `flow/drive_upload.py` håndterer HTTP 308 fra
Googles resumable-opplasting selv. Python 3.11+ sin `HTTPRedirectHandler`
følger 308 automatisk, og da forsvinner `Range`-headeren som sier hvor
opplastingen skal gjenopptas. Koden har en `_NoRedirect`-opener for nettopp
det, men resten av stacken er bare kjørt på 3.10.

---

## 2. Klon repoet

```powershell
git clone <remote> C:\DreamPage-OS
cd C:\DreamPage-OS
```

Bruk **`C:\DreamPage-OS`** hvis du kan. Stiene utledes riktignok fra
`flow/paths.py`, men det ligger fortsatt rundt 60 hardkodede `C:\DreamPage-OS`
igjen i gammel kode. De skal bort, men de er der nå.

Trenger du et annet sted, sett `DP_ROOT` i miljøet — `paths.py` respekterer den.

---

## 3. Python-avhengigheter

```powershell
python -m pip install -r requirements.txt

# torch med CUDA installeres separat, ikke fra requirements.txt:
python -m pip install torch==2.5.1+cu121 torchvision==0.20.1+cu121 `
    --index-url https://download.pytorch.org/whl/cu121
```

---

## 4. ComfyUI (`DreamPage-image/`)

**Følger ikke med i git** — mappa er gitignorert med vilje. Den er upstream
ComfyUI, og vi forker den ikke.

```powershell
git clone https://github.com/comfyanonymous/ComfyUI C:\DreamPage-OS\DreamPage-image
cd C:\DreamPage-OS\DreamPage-image
git checkout v0.21.0            # samme som produksjon
python -m pip install -r requirements.txt
```

Så custom nodes. Vår egen kode ligger i `nodes/` og **symlinkes** inn — den
kopieres ikke, slik at det bare finnes én kopi å redigere:

```powershell
# som administrator
New-Item -ItemType SymbolicLink `
  -Path C:\DreamPage-OS\DreamPage-image\custom_nodes\dreampage-headswap `
  -Target C:\DreamPage-OS\nodes\dreampage-headswap
```

De øvrige tredjeparts-nodene produksjonen bruker er listet av:

```powershell
python tools\node_requirements.py
```

> **Pass på:** `dreampage_headswap` var en periode pip-installert *editable* mot
> den gamle `C:\ComfyUI`. Da kjørte den nye ComfyUI-en gammel kode uten at noe
> sa fra. Sjekk med `python -m pip show dreampage-headswap` at `Location` peker
> dit du tror.

---

## 5. Modeller (~28 GB)

Ikke i git. Manifestet er:

```powershell
python tools\models.py check        # hva mangler, og er størrelsene riktige
python tools\models.py check --verify   # også sha256 (tregt)
```

`models/manifest.json` er generert fra `books/*/workflow_api.json`, så den
lister nøyaktig de modellene bøkene faktisk bruker. Hent dem fra den maskinen
som har dem, eller fra kildene i manifestet.

---

## 6. Hemmeligheter og konfigurasjon

Tre filer er gitignorerte og **må lages for hånd**. Kopier dem fra en maskin som
virker — de finnes ikke noe annet sted.

| Fil | Eksempel | Inneholder |
|---|---|---|
| `config/secrets.json` | `secrets.example.json` | Gelato-nøkkel, worker-bot-token + chat-id, RabbitMQ-legitimasjon, `continue_callback_secret`, `wp_progress_secret` |
| `config/api.json` | `api.example.json` | bearer-tokens med scope |
| `config/dp_bot.json` | — | operatørbotens **egen** token og allowlist |

```jsonc
// config/api.json
{ "<langt-tilfeldig-token>": { "name": "panel",  "scope": "full"   },
  "<annet-token>":           { "name": "flaate", "scope": "status" } }
```

Lag **nye** tokens på en ny maskin. Ikke gjenbruk produksjonens.

> **`config/dp_bot.json` må ha en annen `bot_token` enn worker-boten.**
> `gelato_merge.py` long-poller `getUpdates` på worker-boten under hver ordre,
> og bare én prosess kan eie `getUpdates` per token. Deler de token, spiser de
> hverandres svar — og det som ryker er godkjenningen av et Gelato-utkast på en
> betalt ordre.
>
> Sett `allowed_chat_ids`, ikke `allow_all: true`. Boten kan bygge om betalte
> ordre.

### n8n-filene

n8n-**prosessen** trengs ikke. Men to filer gjør det, fordi produksjonskode
leser SQLite-fila direkte:

```
C:\Users\<bruker>\.n8n\database.sqlite   → gamle ordre-payloads (flow/dp_order.py)
C:\Users\<bruker>\.n8n\config            → encryptionKey for Google Drive-legitimasjonen
```

Uten dem virker ikke `drive_upload.py`. Kopier dem med.

### Tailscale

RabbitMQ-brokeren er `100.118.194.49` — en tailnet-adresse. Maskinen må være på
tailnettet. Uten det får `flow` aldri ordre.

---

## 7. Egne stier til ComfyUI

`input/`, `output/` og `models/` ligger på rota, ikke inne i `DreamPage-image/`.
Det er sånn vi slipper å røre ComfyUI. `dreampage.ps1 up` setter dem på
kommandolinja (`--input-directory`, `--output-directory`,
`--extra-model-paths-config`), så du trenger ikke gjøre noe — men det er verdt å
vite at det er derfor ComfyUI kan oppdateres uten frykt.

Porten er **8189**, ikke ComfyUIs standard 8188. Den står ett sted:
`config/flow.json` → `comfy.url`, og fire steder leser den derfra.

---

## 8. Start

### Utviklingsmaskin — tar ingen ekte ordre

```powershell
python flow\worker\main.py --no-mq
```

API-et, panelet og runneren lever; køen røres ikke. Du kan legge jobber inn
selv med `POST /api/jobs`.

### Produksjonsmaskin

```powershell
.\dreampage.ps1 up
.\dreampage.ps1 status
```

Bekreft at du ikke har to konsumenter:

```python
import sys; sys.path.insert(0, "flow")
import dp_secrets, pika
c = dp_secrets.get("rabbitmq")
con = pika.BlockingConnection(pika.ConnectionParameters(
    host=c["hostname"], port=int(c.get("port") or 5672),
    virtual_host=c.get("vhost") or "/",
    credentials=pika.PlainCredentials(c["username"], c["password"])))
r = con.channel().queue_declare(queue="dreampage-jobs", passive=True)
print(r.method.message_count, "meldinger,", r.method.consumer_count, "konsumenter")
```

**Forventet: `1 konsumenter`.** Står det `2`, tar to maskiner ordre samtidig og
du må stoppe den ene nå.

---

## 9. Verifiser

```powershell
.\dreampage.ps1 test          # alle testene + check_assets
python tools\check_assets.py  # all delt kunst og alle fonter finnes
python tools\models.py check  # modellene er der og har riktig størrelse
```

Alle tre skal gi exit 0. `check_assets` er den som fanger den farligste
feilklassen — se `CLAUDE.md`.

Så en ekte gjennomkjøring **uten** å røre en kundeordre:

```powershell
python flow\dp_testbook.py --help
```

---

## 10. Vaktmester og faste oppgaver (kun produksjon)

To scheduled tasks:

| Navn | Kjører | Hva |
|---|---|---|
| «DreamPage OS» | hvert 5. min + ved innlogging | `dreampage.ps1 ensure` |
| «DreamPage cleanup» | daglig 04:30 | `tools/cleanup_variants.py` |

Uten den første kommer ComfyUI og flow **ikke** tilbake etter en omstart, og
ordrene hoper seg opp i køen uten at noe sier fra.

---

## 11. Identiteten til maskinen

`config/flow.json`:

```jsonc
"server": { "label": "tobias-pc", "role": "production", "region": "no-hjemme" },
"api":    { "tailnet": false }
```

Sett `label` til noe eget. `server.id` står **ikke** her — den er en UUID i
`state/server_id.json` som følger maskinen, ikke vertsnavnet, slik at et
navnebytte ikke gjør serveren til en ny server i overvåkingen.

`api.tailnet: true` lar det **fulle** API-et (8765) svare på tailnet-adressen.
Standarden er `false`, og den skal den være på en ny maskin — `/api/jobs`
inneholder barnenavn. Skru den bare på hvis et kontrollpanel på en annen maskin
faktisk trenger det.

---

## Sjekkliste

- [ ] Python 3.10, `requirements.txt`, torch+cu121
- [ ] `DreamPage-image/` klonet på v0.21.0, custom nodes på plass
- [ ] `nodes/` symlinket, ikke kopiert
- [ ] `python tools\models.py check` → exit 0
- [ ] `config/secrets.json`, `api.json`, `dp_bot.json` lagt inn
- [ ] `dp_bot.json` har **annen** bot-token enn worker-boten
- [ ] `.n8n\database.sqlite` og `.n8n\config` kopiert
- [ ] Tailscale oppe
- [ ] `.\dreampage.ps1 test` → exit 0
- [ ] `python tools\check_assets.py` → exit 0
- [ ] **`consumer_count` på `dreampage-jobs` er fortsatt 1**
- [ ] scheduled tasks lagt inn (kun produksjon)

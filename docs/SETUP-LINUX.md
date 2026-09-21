# Sette opp DreamPage OS på Linux

Nye maskiner settes opp på Linux. Produksjonsmaskinen kjører Windows enda, og
skal fortsette med det — `docs/SETUP-NEW-PC.md` er guiden for den.

Koden er **den samme**. Det finnes ingen Linux-gren og ingen Windows-gren;
forskjellene ligger på tre steder og bare der:

| | |
|---|---|
| `flow/dp_platform.py` | oppetid, `~/.n8n`, hvor kjørbare filer er, hvilken vaktmester |
| `tools/dreampage.py` + `dreampage.sh` | supervisoren, motstykket til `dreampage.ps1` |
| `deploy/systemd/` | vaktmesteren, motstykket til Task Scheduler |

En `if windows:` i produksjonskoden er en feil. Er noe forskjellig, hører det
hjemme i `dp_platform.py`.

---

## ⚠️ Les dette før du kjører noe

**En ny maskin som starter `flow` i BOOK-modus begynner umiddelbart å ta ekte
kundeordre.**

`dreampage-jobs` er én kø med én konsument. Kobler maskin nummer to seg på,
fordeler RabbitMQ ordrene mellom dem — og halvparten av kundene får boka si
bygget på en maskin som kanskje mangler modeller eller kunst.

Bestem derfor **først** hva denne maskinen er:

| Modus | Kø | Hva den gjør |
|---|---|---|
| `book` | `dreampage-jobs` | hele bokproduksjonen. **Bare én slik maskin om gangen.** |
| `preview` | `preview-jobs` | forhåndsvisninger til nettbutikken. Koster ingenting, trykker ingenting. |
| utvikling | ingen | start flow med `--no-mq` |

Se `docs/preview-modus.md`. En ny Linux-maskin bør som regel settes til
`preview` først.

---

## 1. Krav

| | Versjon | Merknad |
|---|---|---|
| Python | **3.10** | ikke 3.11+ — se `docs/SETUP-NEW-PC.md` §1 for hvorfor |
| Git | | |
| NVIDIA GPU + driver | 24 GB VRAM | `nvidia-smi` må svare |
| Diskplass | ~40 GB | 28 GB modeller + repo + output |
| Tailscale | | RabbitMQ-brokeren nås bare over tailnettet |
| Node.js | 18+ | bare BOOK-modus (mockup-serveren) |

```bash
sudo apt update
sudo apt install -y python3.10 python3.10-venv python3.10-dev git \
                    build-essential libgl1 libglib2.0-0 fontconfig
```

`libgl1` og `libglib2.0-0` er Pillow/OpenCV sine; uten dem feiler første
bilde med en `ImportError` som ikke nevner bilder med ett ord.

---

## 2. Klon repoet

```bash
git clone <remote> ~/DreamPage-OS
cd ~/DreamPage-OS
chmod +x dreampage.sh deploy/systemd/install.sh
```

**Bruk `~/DreamPage-OS`.** Stiene utledes riktignok fra `flow/paths.py` og
tåler hva som helst, men `deploy/systemd/*.service` bruker
`%h/DreamPage-OS`. Ligger repoet et annet sted, må de rettes — `install.sh`
nekter og sier fra.

`chmod +x` er nødvendig fordi filene er laget på Windows, der det ikke finnes
noen kjørbar-bit å ta vare på.

Trenger du et helt annet sted: sett `DP_ROOT` i miljøet.

---

## 3. Python-miljø

```bash
python3.10 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

Torch installeres **med CUDA-hjul fra pytorch.org**, ikke fra
`requirements.txt`:

```bash
.venv/bin/python -m pip install torch==2.5.1+cu121 torchvision==0.20.1+cu121 \
    --index-url https://download.pytorch.org/whl/cu121
.venv/bin/python -c "import torch; print(torch.cuda.is_available())"
```

Sier den `False`, stopp her. En ComfyUI uten CUDA bygger sider på CPU i
timevis i stedet for i minutter, og det ser ut som at den henger.

`dreampage.sh` finner `.venv/bin/python` av seg selv. `DP_PYTHON` i miljøet
overstyrer.

---

## 4. ComfyUI, modeller, hemmeligheter

Identisk med Windows — følg `docs/SETUP-NEW-PC.md` §4–6. Kort:

* `DreamPage-image/` er ComfyUI. **Innholdet redigeres aldri.** Vi endrer den
  ved å gi den andre stier på kommandolinja, ikke ved å endre filene dens.
* Modellene (~28 GB) hentes med `tools/models.py`.
* `config/secrets.json`, `config/api.json` og `config/dp_bot.json` ligger
  **ikke** i git. Kopier fra `*.example.json` og fyll inn.
* `config/extra_model_paths.yaml` peker på `models/`.

En ting er annerledes: `flow/n8n_credential.py` og `flow/dp_order.py` leser
n8n sin SQLite for å hente gamle ordre-payloads og dekryptere
Drive-legitimasjonen. På Linux ligger den i `~/.n8n/`. Har maskinen ingen
n8n-installasjon, kopier de to filene dit:

```bash
mkdir -p ~/.n8n
# database.sqlite og config (encryptionKey) fra den gamle maskinen
```

`DP_N8N_HOME` overstyrer stien.

---

## 5. Velg modus

```bash
./dreampage.sh mode            # hva står den til nå
./dreampage.sh mode preview    # eller book
```

---

## 6. Start

```bash
./dreampage.sh up
./dreampage.sh status
```

`up` starter ComfyUI, flow, og — bare i BOOK-modus — mockup-serveren og
operatørboten. Tjenestene startes med `start_new_session`, så de overlever at
SSH-økta lukkes.

Vil du prøve uten å ta imot ordre:

```bash
.venv/bin/python flow/worker/main.py --no-mq
```

---

## 7. Vaktmesteren

```bash
./deploy/systemd/install.sh
```

Den legger `dreampage-ensure.timer` under `systemctl --user`, som kjører
`./dreampage.sh ensure` hvert 5. minutt og ved oppstart — nøyaktig det
scheduled task «DreamPage ensure» gjør på Windows.

**`loginctl enable-linger`** er den ene tingen som er lett å glemme, og
`install.sh` gjør den for deg: uten den stopper brukerens systemd når siste
SSH-økt lukkes, og da dør hele DreamPage når du logger av.

```bash
systemctl --user list-timers dreampage-ensure.timer
journalctl --user -u dreampage-ensure -f
tail -f state/watchdog.log
```

Bruker-enheter og ikke system-enheter, med vilje: ComfyUI trenger
GPU-tilgang og brukerens miljø, og en system-enhet ville kjørt som root med
et annet `HOME` — da finner koden verken `~/.n8n` eller `.venv`.

---

## 8. Verifiser

```bash
./dreampage.sh test
```

Kjører alle testfilene, `check_assets`, `comfy_workflows --check` og
`check_portability`. Den siste er spesielt verdt å lese på en ny maskin: den
finner hardkodede stier, filnavn med feil bokstav og Windows-bare API-er.

Deretter:

```bash
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8765/api/health | head
```

Sjekk i svaret:

| Felt | Skal være |
|---|---|
| `mode.name` / `mode.queue` | den modusen du valgte |
| `comfy.from_image` | `true` — altså **vår** ComfyUI |
| `comfy.unet_models` | > 0 — den ser modellene |
| `rabbitmq.connected` | `true` (eller `false` hvis du kjører `--no-mq`) |

`/api/status` viser i tillegg `server.platform`, så en flåtevisning kan se
hvilke maskiner som kjører hva.

---

## 9. Hva som er annerledes fra Windows

| | Windows | Linux |
|---|---|---|
| Supervisor | `.\dreampage.ps1` | `./dreampage.sh` |
| Vaktmester | Task Scheduler, hvert 5. min | `dreampage-ensure.timer` |
| Stopp av tjeneste | `Stop-Process -Force` | `SIGTERM`, så flow rekker å legge fra seg køen |
| Prosessoppslag | `Win32_Process` | `/proc/<pid>/cmdline` |
| Oppetid | `GetTickCount64` | `/proc/uptime` |
| cloudflared | fil i `Downloads` | på `PATH` |
| Store/små bokstaver i filnavn | spiller ingen rolle | **spiller all rolle** |

Den siste er den farligste, fordi den er usynlig fra Windows:
`Georgia.TTF` åpner `Georgia.ttf` der, og finnes ikke her.
`tools/check_portability.py` sjekker hvert eneste filnavn konfigurasjonen
peker på mot det disken faktisk heter — og den kjøres av
`.\dreampage.ps1 test` **på Windows**, slik at feilen fanges på maskinen der
den ikke gjør noe.

---

## Sjekkliste

- [ ] `nvidia-smi` svarer, `torch.cuda.is_available()` er `True`
- [ ] `chmod +x dreampage.sh deploy/systemd/install.sh`
- [ ] `config/secrets.json` og `config/api.json` er fylt ut
- [ ] `~/.n8n/database.sqlite` og `~/.n8n/config` finnes
- [ ] `./dreampage.sh mode` sier riktig modus
- [ ] `./dreampage.sh test` er grønn
- [ ] `/api/health` sier `from_image: true` og `unet_models > 0`
- [ ] `systemctl --user list-timers` viser `dreampage-ensure.timer`
- [ ] `loginctl show-user $USER` sier `Linger=yes`
- [ ] **bare én maskin i BOOK-modus**

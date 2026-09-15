# DreamPage Klein 9B Studio

En ny, redigerbar ComfyUI-workflow for den eksisterende `flux-2-klein-9b.safetensors` på denne PC-en. Ni nye DreamPage-noder leser bilder, forbereder personreferanser, bygger scenen og instruksjonen, kjører Klein og setter hodet tilbake i originalbildet. Ingen trening eller LoRA kjøres av workflowen.

## Åpne og test

1. Åpne `workflows/DreamPage_Klein9B_Studio.json` i ComfyUI. Filen med `_api.json` er for API-klienter og er ikke den redigerbare UI-workflowen.
2. I gruppe **02 / YOUR THREE INPUTS**, velg personbildet, originalscenen og masken som hører til scenen. Behold **red** som maskekanal. Hvitt angir hodet/håret som kan erstattes; svart er beskyttet.
3. Behold først standardinnstillingene og kjør workflowen. Se på de forberedte referansene, scenereferansen og maskens turkise overlay.
4. Vurder siden og review-bildet i gruppe **06 / FINISH & REVIEW**. Sjekk gjenkjennelighet, hodeform, hår, uttrykk, lys og overgangen til halsen.

Eksempelvalgene er eksisterende inputfiler: `26063001.jpg`, `forside(dyreparken).jpg` og `forside-headmask(dyreparken).png`. De er testinnganger for inferens; de blir ikke automatisk treningsdata. Velg gjerne ditt eget testtilfelle.

Sluttbildet lagres under `ComfyUI/output/DreamPage/Studio/final_*.png`. Sammenligningsbildet lagres under `ComfyUI/output/DreamPage/Studio/review_*.png`. Standard Save Image-noder legger til løpenummer og workflow-metadata. Det endelige sidebildet beholder originalens dimensjoner.

## De ni nye nodene

| Node | Hva den gjør nå |
| --- | --- |
| **DP Load Photo** | Leser foto og masker med samme Pillow-bildeavkoding, korrigerer EXIF-orientering og returnerer RGB-bilde, valgt maskekanal og leserapport. Brukes separat for person, scene og sidemaske. |
| **DP Reference Studio** | Forbereder opptil tre ulike bilder av samme person. Beholder sideforhold og kan bruke en separat hodemaske for hvert bilde. Viser bildene som faktisk sendes videre. |
| **DP Identity Encoder · Klein** | VAE-enkoder hver personreferanse separat med den ferdigtrente FLUX.2-VAE-en. Dette er fungerende visuell referansekondisjonering; den spesialiserte DreamFace-enkoderen er ennå ikke trent. |
| **DP Scene & Mask Studio** | Lager utsnitt, genereringsmaske, blandemaske og en trygg latent start. Den opprinnelige sidemasken bestemmer alltid hvilke sluttpiksler som kan endres. |
| **DP Swap Direction** | Bygger en instruksjon som følger faktisk bilderekkefølge: scene først, deretter personreferanser. Feltet for ekstra instruksjoner er valgfritt. |
| **DP Klein Conditioning** | Enkoder tekst og scene og kobler sammen referansene. Det opprinnelige hodet fjernes fra latentstarten før skalering og VAE-enkoding. |
| **DP DreamSwap · Klein 9B** | Kjører den lokale Klein-modellen med vanlig Comfy-sampling eller den installerte LanPaint-sampleren. Har fast seed som utgangspunkt. |
| **DP Seam Finish** | Setter resultatet tilbake i originaloppløsning med begrenset fargekorreksjon og innvendig kantblanding. Kopierer beskyttede piksler direkte fra originalen. Dette er deterministisk etterbehandling, ikke en trent DreamRefine-modell. |
| **DP Review Board** | Viser person, før/etter, skrivemaske og forsterket differanse utenfor masken. Måler pikselbevaring, mens identitet og fotorealisme vurderes av et menneske. |

Alle ni er tilkoblet i workflowen; DP Load Photo brukes tre ganger. Standardnoder håndterer modellinnlasting, VAE-dekoding, forhåndsvisning og lagring. De tidligere sju DreamPage-nodene for den separate trenbare pakken finnes fortsatt, men trengs ikke i denne Klein-workflowen.

## Innstillingene du kan sammenligne

Startoppsettet bruker personreferanse **768**, sceneutsnitt **1024**, context **1.5**, mask expansion **0**, feather **8**, edge protection **0.65**, **4 Euler/simple-steg**, native sampler og seed **19347 / fixed**. CFG er **1** og denoise er **1**. Fargekorreksjon starter på **0**, slik at den kan vurderes som et separat tiltak. Dette er et praktisk startoppsett, ikke et løfte om optimalt resultat på alle ansikter.

- **Flere personbilder:** Koble andre bilder av samme person til `view_2` og eventuelt `view_3`. Bildene holdes separate. De blir ikke blandet eller gjennomsnittsberegnet til én latent.
- **Bilde med mye bakgrunn:** Bruk en tydelig portrettbeskjæring eller koble til en hodemaske for kilden. Masken må følge det aktuelle bildet. `background_strength` undertrykker bakgrunnen bare når den tilhørende kildemasken finnes.
- **Scene mode:** `original` beholder posering og uttrykk, men viser også modellens opprinnelige ansikt. `blur` svekker detaljene. `neutral` fjerner hodeinformasjonen, inkludert posering og uttrykk inne i masken. Sammenlign disse ved samme seed.
- **LanPaint:** Sett `engine` til `lanpaint` for å bruke den eksisterende installasjonen. `lanpaint_steps` gjelder bare denne motoren. LanPaint bruker en binær latentmaske, mens vanlig Comfy-sampling kan bevare myke maskeverdier; resultatene kan derfor bli forskjellige.
- **Hårkant og hals:** Juster først den faktiske hodemasken hvis den avgrenser feil. Feather ligger på innsiden av masken. Expansion gir genereringen mer rom, men tillater aldri endringer utenfor den originale masken i det ferdige bildet.
- **Fargekorreksjon:** Øk `color_strength` forsiktig hvis du vil sammenligne korrigering fra den urørte konteksten rundt hodet. `max_shift` begrenser endringen. Resultatet må fortsatt vurderes visuelt.

Behold samme seed når du sammenligner én innstilling. Det finnes ingen kunstig «identity strength»-kontroll som bare skalerer VAE-latenter, og ingen ekstra FluxGuidance-node: de lokale 9B-vektene har ikke en slik guidance-embedding.

Modellkontrollen validerer 9B-arkitekturen og tilkoblingenes størrelser. Arkitekturen alene skiller ikke en BASE 9B-modell fra en destillert 9B-modell. Workflowen velger derfor den konkrete eksisterende filen `flux-2-klein-9b.safetensors`; en annen modellfil krever egne validerte samplerinnstillinger.

## Hva REVIEW betyr

**REVIEW** betyr at den målte pikselbevaringen utenfor masken er nøyaktig. Det betyr ikke at ansiktet automatisk er riktig eller fotorealistisk. **FAIL** betyr at denne pikseltesten feilet. Identity score og realism score forblir ukjente; det tildeles ingen oppdiktet kvalitetsscore.

Review-bildets differansepanel forsterker endringer utenfor masken 20 ganger. Beskyttede områder skal være svarte. Den ferdige siden går ikke gjennom en oppskalering av hele bildet, siden det ville endre de beskyttede pikslene.

Sammenligningen gjelder de orienterte RGB-pikslene fra **DP Load Photo**. Bildeleseren bruker Pillow konsekvent: ulike JPEG-dekodere kan gi litt forskjellige piksler fra samme fil. Dette gjør det mulig å kontrollere den lagrede PNG-filen mot originalen med samme avkoding, i tillegg til den interne pikseltesten.

## Legg til LoRA senere

Når en kompatibel LoRA for akkurat Klein **9B** er klar, sett inn Comfy-noden **Load LoRA (Model Only)** mellom **Load Diffusion Model** og **DP DreamSwap**. Alle andre forbindelser beholdes. Start fra styrken som anbefales og valideres for den aktuelle LoRA-en.

En LoRA eller identitetsadapter trent for BASE **4B** kan ikke uten videre kobles inn i 9B-modellen. Arkitektur, størrelser og treningsoppsett må stemme. Ingen av de eksisterende LoRA-filene på PC-en lastes av det leverte startoppsettet.

## Filer og vedlikehold

- `comfyui_dreampage_headswap/native_nodes.py`: de ni adapterne.
- `comfyui_dreampage_headswap/web/dreampage.js`: avgrenset teal-styling og en skrivebeskyttet rapportvisning. Rapportwidgeten lagres ikke som en input eller parameter i workflowen.
- `scripts/build_klein_workflow.py`: bygger UI- og API-filene fra faktiske nodeskjemaer og kontrollerer tilkoblinger og overlapp. Skriptet køer ingen jobber.
- `workflows/DreamPage_Klein9B_Studio.json`: redigerbar UI-workflow.
- `workflows/DreamPage_Klein9B_Studio_api.json`: tilsvarende API-graf.

For å generere workflowfilene på nytt fra prosjektmappen mens ComfyUI kjører:

```powershell
C:\ComfyUI\venv\Scripts\python.exe scripts/build_klein_workflow.py
```

Frontend-stylingen krever at ComfyUI har lastet pakken og at nettleseren er oppdatert. Hvis nodene mangler, kontroller at pakken lastes fra `custom_nodes/dreampage_headswap` og at DreamPage-pakken er installert i Python-miljøet som faktisk starter ComfyUI. En restart må vente til aktive jobber er ferdige.

## Verifikasjonsstatus

Builderen og JavaScript-syntaksen er kontrollert. Endelig UI- og inferensverifikasjon med den nye DP Load Photo-varianten pågår; resultater fra en tidligere graf uten denne bildeleseren dokumenterer ikke denne siste varianten.

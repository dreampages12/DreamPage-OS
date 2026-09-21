# DreamPage-modellen: datasett og gjenbrukbar trening

Oppdatert 21.09.2026. Koden bor i `nodes/dreampage-headswap/`. Den gamle
`ComfyUI/dreampage-headswap`-kopien er historisk. Ingen fotorealistisk modell
er trent ennå, og ingen datasettgodkjenning er gitt.

## Det som er klargjort

- Eget Python-miljø i `nodes/dreampage-headswap/.venv`, med egne avhengigheter.
  ComfyUIs produksjonsmiljø oppgraderes ikke av dette oppsettet.
- Versjonerte kjøringer med konfigurasjon, kodehash, datasettets innholdshash,
  godkjenningskvittering, foreldrecheckpoint, forsøkshistorikk og checkpoint-hasher.
- `fresh`: ny modellkjøring; `resume`: samme data, optimizer, scheduler, RNG og
  dataposisjon; `finetune`: ny kjøring som bare arver modellvektene.
- Godkjenning kontrolleres på nytt ved hver start. Endrede bilder eller manifester
  ugyldiggjør den. Planlegging lager bare en **ikke godkjent** forespørsel.
- Identiteter brukt til trening følger modellens avstamning. De kan ikke senere
  brukes som uavhengig validering/test av en etterkommer. Behold samme person-ID
  for samme person på tvers av alle datasettversjoner.

**Treningsmålet er FLUX.2 Klein 9B**, slik Tobias har valgt. Standardoppsettet
peker på vanlig/distilled 9B og den eksisterende lokale transformeren i
`models/diffusion_models/flux-2-klein-9b.safetensors`. 4B-konfigurasjonene og
anskaffelsesverktøyene er arkivert og avvises som aktivt treningsmål.

Vanlig [Klein 9B](https://huggingface.co/black-forest-labs/FLUX.2-klein-9B)
er distilled og bruker tekstguidance 1.0. BASE 9B er en egen eksplisitt variant;
programmet velger den aldri automatisk. Loaderen kontrollerer 12288 tekstkanaler,
128 latentkanaler og 9B-transformerens blokk-/attention-konfigurasjon.

Den eksisterende traineren lærer DreamFace og egne DreamSwap-adaptere rundt
9B-backbonen (backbonens vekter er fryst i pilotkonfigurasjonen). Dette er
fortsatt en egen checkpoint-pakke, ikke en ferdig vanlig ComfyUI-LoRA. LoRA-eksport
og innkobling av den trente pakken i native Studio må implementeres og valideres
separat. Ingen kvalitets- eller VRAM-påstand følger av arkitekturstøtten.

## Oppsett og kontroll

Fra DreamPage OS-roten, med Python 3.10 og NVIDIA-driver som støtter CUDA 12.1:

```text
python tools/headswap.py setup-env
python tools/headswap.py doctor --report state/headswap/readiness.json
python tools/headswap.py init-data
python tools/headswap.py studio
```

`setup-env` installerer biblioteker; det laster ikke modeller på GPU og trener
ingenting. Installasjonen er verifisert på denne Windows-maskinen. Linux-stier
støttes, men Linux-installasjon og GPU-trening er ikke kjørt her. Miljøet skal
opprettes på hver maskin; ikke kopier `.venv` mellom maskiner.

`doctor` kontrollerer miljø, kildekopi, 9B-transformerens header, komponentkvittering,
mottaksmappe og registrerte ComfyUI-noder. Headeren viser arkitektur; en full SHA256
kreves for å fastslå nøyaktig kilde/variant. Modellinnlasteren verifiserer alle filer
og den eksterne transformeren før lasting. Datasettgodkjenning er en kontroll per kjøring.

`studio` bygger og installerer `LAB-DreamPage-HeadSwap.json` fra den aktive
ComfyUI-serverens nodekontrakter. Det sender ingen jobb og endrer ingen
bokworkflow. Workflowen bruker de nye nodene og vanlig Klein 9B uten trent LoRA.

## Gjenstående 9B-komponenter

Den lokale transformerfilen er fullstendig SHA256-verifisert mot utgiverens vanlige
Klein 9B: `0975d6b77b5f510b99547d6724a208e36527df654e8f6134f59ece3f9f30da58`.
Kvittering: `state/headswap/klein-9b-transformer.json`. Dette var en strømmet filkontroll
med liten minnebruk, uten modellinnlasting eller trening.

Transformerfilen er ikke alene et komplett Diffusers-treningsoppsett.
Treneren trenger også 9B-kompatibel Qwen3-8B-tekstkoder, tokenizer, VAE,
scheduler og konfigurasjon. Studio bruker allerede ComfyUIs egne komponenter;
produksjonen endres ikke av denne klargjøringen.

Offisiell revisjon kontrollert via metadata:
`92196c8e11f7b6cf2b7493e037d8c5345c559216`.
Tilgangsforsøket til den offisielle `transformer/config.json` ble avvist med
`GatedRepoError` 21.09.2026. Kontoen må ha tilgang til modellrepoet før de
manglende komponentene kan hentes (22 støttefiler, cirka 16,6 GB; eksisterende
transformer gjenbrukes). Ingen vilkår aksepteres automatisk.

Fra treningsprosjektet med eget miljø; kommandoen under viser bare inventar:

```text
PY scripts/prepare_klein_9b.py --revision 92196c8e11f7b6cf2b7493e037d8c5345c559216 --transformer ../../models/diffusion_models/flux-2-klein-9b.safetensors
```

Legg til `--download` etter at kontoens tilgang er i orden. Det verktøyet
sammenligner den eksisterende transformeren mot offisiell SHA256 og henter bare
støttekomponentene; det trener ingenting. 9B-rettigheter registreres separat i
kildekvitteringen. Den gamle 4B-modellens Apache-kvittering gjelder ikke 9B.
Se [utgiverens modellkort](https://huggingface.co/black-forest-labs/FLUX.2-klein-9B).

Aktiv swap-konfigurasjon: `configs/training/flux_klein_9b_photoreal_pilot.yaml`.
Den krever både komplett 9B-oppsett og det senere godkjente datasettet.

## Bilder fra Tobias

Legg originalene i `nodes/dreampage-headswap/local_data/fra_tobias/`:

```text
person_001/    ca. åtte forskjellige bilder av samme person
person_002/    neste person
...
person_020/
swaps/swap_001/person.heic
swaps/swap_001/for.png
swaps/swap_001/etter.png
swaps/swap_001/maske.png     hvis tilgjengelig
```

Filendelsen skal stemme med originalformatet; HEIC er støttet. Et manglende
maskebilde stopper ikke levering, men vi må klargjøre en korrekt maske før
paret kan brukes til trening. `for`, `etter` og masken må ha samme geometri.
Det trengs ikke en egen tekstfil i hver swap-mappe: Tobias har oppgitt at
swapene kommer fra DreamPage-pipelinen. Samtykke/rettigheter og visuell
fotorealisme gjennomgås før innrømming. Ingen kundebilder hentes automatisk.

Fra treningsprosjektet, med `.venv/Scripts/python.exe` på Windows eller
`.venv/bin/python` på Linux som `PY`:

```text
PY scripts/review_intake.py --input local_data/fra_tobias --output local_data/reviews/intake-v1
```

Dette lager lokal HTML-katalog og JSON-rapport: orienterte forhåndsvisninger,
bildehasher, dimensjoner, duplikater, lesefeil og mangler i swap-mappene.
Originalene bevares. Rapporten er **ikke** et treningsmanifest eller en
godkjenning. Bruk et nytt review-navn når nye bilder kommer.

Deretter klargjør vi masker, eksplisitte person-ID-er, rettighetsmetadata og
separate train/validation/test-personer. De eksisterende verktøyene
`ingest_dataset.py`, `preprocess_dataset.py`, `generate_training_pairs.py`
og `dataset_report.py` dekker denne delen. HEIC normaliseres til PNG ved
innrømming. Par-generatoren skriver relative stier og korpusregister.
Eksakte swap-par må registreres med riktig kildeperson; de blandes ikke inn
automatisk fra mappeplassering alene.

## Planlegg uten å trene

Når et konkret, gjennomgått korpus finnes, kan vi planlegge:

```text
PY training/manage.py plan --config configs/training/identity_photoreal_pilot.yaml --component identity --run-id identity-v1
PY training/manage.py list
```

Run-mappen får `config.json`, `run.json` og `approval.request.json`. Det siste
har `approved: false`. Brukeren skal se bildene, kilder/rettigheter, kvalitet,
personsplitter og hash før godkjenning. **Ingen skal endre dette til true uten
brukerens eksplisitte godkjenning av akkurat det datasettet og treningsfasen.**

Pilotkonfigurasjonene er utgangspunkt som må tilpasses faktisk datasett og
VRAM. Identity-piloten trenger minst fire treningspersoner og to
valideringspersoner. Et lite datasett kan teste retningen; mange steg gjør
ikke automatisk modellen god eller generaliserbar.

## Start, fortsett og videreutvikle — etter godkjenning

Følgende kommandoer er dokumentasjon; de er **ikke kjørt**:

```text
PY training/manage.py start --run runs/managed/identity-v1 --approval local_data/reviews/approved-v1.json
PY training/manage.py resume --run runs/managed/identity-v1 --approval local_data/reviews/approved-v1.json
PY training/manage.py resume --run runs/managed/identity-v1 --approval local_data/reviews/approved-v1.json --max-steps 1500
PY training/manage.py plan --config configs/training/identity_photoreal_pilot.yaml --component identity --mode finetune --parent runs/managed/identity-v1/model/checkpoint.best.pt --run-id identity-v2
```

For nye data: lag en ny datasettversjon og konfigurasjon, planlegg `finetune`,
og innhent ny godkjenning. For trening helt på nytt: planlegg `fresh` med
et nytt run-navn. Tidligere runs overskrives ikke. Fortsatt optimalisering
krever samme modellarkitektur. Refiner krever i tillegg samme uavhengig
gjennomgåtte, frosne identity-lærermodell.

`resume` krever uendret treningskode, konfigurasjon, data og registrerte
biblioteksversjoner. Checkpoint lagres atomisk; gjenopptakelsen begynner ved
siste lagrede steg. En annen GPU/driver kan gi numeriske forskjeller selv
om RNG og dataposisisjon gjenopprettes. Gamle prosedyretest-checkpoints
bruker eldre datafingeravtrykk og er ikke initialisering for denne modellen.

Ved strømbrudd kan en lås bli liggende. Kontroller at prosessen faktisk er
stoppet på den opprinnelige maskinen før:

```text
PY training/manage.py recover --run runs/managed/identity-v1 --reason "Strømbrudd, prosessen er bekreftet stoppet" --confirmed-stopped
```

Recovery registrerer checkpoint-hasher og begrunnelsen, men starter ingenting.
Hvis krasjet skjedde før første checkpoint, planlegg et nytt run.

## Flere servere og produksjon

Trening er sperret når OS-konfigurasjonen har `server.role: production`.
Bruk en dedikert treningsmaskin uten bokworker/supervisor aktiv. Ikke endre
rollen på denne produksjonsmaskinen bare for å omgå kontrollen. Det er ikke
nok at ComfyUI-køen er tom et øyeblikk: workeren kan motta nye ordre.

Kopier datasett, godkjenningskvitteringer, modellvekter og ønskede runs med
samme relative katalogstruktur til den nye maskinen. Koden ligger i Git;
private bilder, vekter, `.venv` og runs er ignorert og må flyttes/sikkerhetskopieres
separat. Behold originalfilene og deres hasher. Planlegging, mottakskontroll
og metadata bruker ikke GPU. FLUX-trening støtter én prosess foreløpig;
flerkortstrening/FSDP er ikke ferdig integrert eller validert.

## Verifisering og kvalitet

Kun tester som ikke trener er kjørt i denne økten. Miljøkontroll, godkjennings-
og lineage-kontroller, filintegritet og workflowstruktur er verifisert.
De faktiske nye treningsløpene, VRAM-behovet og modellkvaliteten må valideres
etter datasettgodkjenning. Ingen run merkes kvalitetsgodkjent automatisk.
Hold utvalgte personer helt utenfor trening, sammenlign mot baseline med
identiske innganger, og bruk blind menneskelig vurdering sammen med målbare
maskebevarings-/rekonstruksjonskontroller før en modell tas i produksjon.

# `config/preview/` — konfigurasjon for PREVIEW-modus

Dette leses bare av en server som står i **preview**-modus
(`config/flow.json` → `"mode": "preview"`). En bok-PC rører ikke disse
filene.

## Hvorfor det er så lite her

Forhåndsvisnings-PC-en holdt en fullstendig `preview-config/` med omslag,
masker, workflow, logo, fonter og tittelparametre per bok per marked. Alt
det finnes allerede i DreamPage OS, fordi det er det boka **trykkes** fra:

| Hva | Hvor det leses fra |
|---|---|
| Omslag (`page00`) og innersider, med headmask | `books/<slug>/config.json` |
| ComfyUI-workflow og `patchNodes` | `books/<slug>/config.json` |
| `line1`/`line2`/logo/font/gull per språk | `config/next_book_titles.json` |
| Selve rendringen av tittel og logo | `flow/pre/render-title*.py` |
| **Historieteksten på innersider** | `flow/text/<lokale>/<bok>-text-<lokale>.py` |

**Side 7 i forhåndsvisningen er side 7 i boka.** Alt annet ville vært en løgn
mot kunden — de kjøper boka de ser. `flow/pre/render-innerpage.py` importerer
bokas eget tekstscript, kaller `build_pages(child_name)` og lar bokas egen
`render_page()` tegne sida. Navnebytte, automatisk uthevede ord, delingen i
to balanserte blokker, den mørke puta bak teksten, venstre/høyre kolonne og
den automatiske krympingen av skriften følger med gratis — det er den samme
koden. Endrer noen teksten på side 7, endrer forhåndsvisningen seg i samme
øyeblikk.

`config/next_book_titles.json` sier selv `"source": "preview-worker"` — den
er ikke en etterligning av forhåndsvisningen, den **er** den, flyttet hit.

En kopi av de samme verdiene ville vært en kopi som gikk ut av synk, og da
ville forhåndsvisningen og den trykte boka sagt to forskjellige ting. Derfor
inneholder denne mappa bare det som ikke finnes noe annet sted.

## `markets/<marked>.json` — påkrevd

Ett per språkmarked: `nb`, `en`, `sv`, `uk`. Mangler fila for markedet en
jobb hører til, **feiler jobben**. Det er med vilje: en svensk
forhåndsvisning rendret med norsk tittel ser riktig nok ut til at ingen
oppdager det før kunden gjør det.

```json
{
  "title_lang": "sv",          // hvilken nøkkel i next_book_titles.json
  "logo_locale": "sv",         // hvilken flow/text/logo/<lokale>/-mappe
  "script_language": "sv",     // hvilket av bokas textScripts historien tas fra
  "aliases": { "regnbuens-skatt": "regnbuen" },
  "defaults": { "workflow_api": "" }   // tom = bokas egen workflow_api.json
}
```

`uk` gjenbruker `en` sine maler og `en-GB`-logomappa — det er den samme
regelen forhåndsvisnings-PC-en har hatt hele tiden.

## `books/<marked>/<slug>.json` — valgfri

En bok som skal se ut som den trykte boka trenger **ingen fil her**. Filen
finnes for de tre tilfellene som ikke kan utledes:

1. **Hvilken innerside som skal vises.** Hvilken scene som selger boka er en
   redaksjonell avgjørelse. *Hva som står på den* er det ikke — det er bokas
   tekst. Uten en `innerpage`-seksjon feiler en innerside-jobb med en setning
   som sier hvor sidevalget skal legges inn.
2. **En annen ComfyUI-workflow** enn den boka trykkes med.
3. **En tittel som skal stå annerledes** i forhåndsvisningen enn i boka.

Feltnavnene er forhåndsvisnings-PC-ens egne, slik at en fil derfra kan
legges rett inn:

```json
{
  "title_lang": "nb",
  "logo_locale": "nb",
  "script_language": "nb",

  "line1": "{child_name} og",
  "line2": "",
  "line2_image": "C:/DreamPage-OS/flow/text/logo/nb/dyreparken-logo.png",
  "logo_scale": 0.78,

  "cover_image": "forside(dyreparken).jpg",
  "hair_mask": "forside-headmask(dyreparken).png",
  "workflow_api": "",

  "innerpage": {
    "page_key": "page07",
    "image": "",
    "hair_mask": ""
  }
}
```

* `{child_name}` og `{child_name_s}` (eieform: «Emmas», «Mats'») byttes ut
  med barnets navn i **tittelen**.
* `page_key` slås opp i **bokas egen** `config.json`, så malen og masken er de
  samme filene som trykkes. `image`/`hair_mask` overstyrer bare hvis en
  forhåndsvisning skal bruke noe annet.
* **Det finnes ingen `text`, `side`, `font_size` eller `highlights` her.**
  Alt det kommer fra bokas tekstscript, via malfilnavnet
  (`template_image` i bokas config = `filename` i tekstscriptet). En tekst
  her ville vært en kopi som gikk ut av synk — og da ville kunden sett én
  historie på nettsiden og fått en annen i posten.

Skal en annen side vises, bytt `page_key`. Skal teksten endres, endre den i
tekstscriptet — da endres boka og forhåndsvisningen sammen.

## Hva som IKKE kan stå her

Hemmeligheter. Supabase-URL og nøkkel ligger i `config/secrets.json` under
`"supabase"`, lest via `flow/dp_secrets.py`.

## Sjekk stiene

`tools/check_assets.py` leser kunst- og fontstier ut av JSON-filene her, på
samme måte som den gjør for `config/next_book_titles.json`. Legger du inn en
`line2_image` eller en fontsti, blir den sjekket automatisk — kjør

```powershell
python tools\check_assets.py
```

En manglende tittellogo er ikke en detalj: for de fleste bøker **er** logoen
hele andre tittellinje, og render-title skriver «ADVARSEL» og avslutter med
0. Det ga ordre 1510 en trykkeklar forside som bare sa «Henry og det» — og i
en forhåndsvisning er det kunden som ser det.

# Gamle maler — arkivert 17.09.2026

Her ligger malsettet som lå i `C:\DreamPage-OS\input\` fram til 17.09.2026,
da boka fikk 14 helt nye innersider og en ny historie.

## Hva som ligger her

| Filer | Hva |
|---|---|
| `01..14(magiske-bursdag-jente).png` | de gamle innersidemalene |
| `01..14-headmask(...).png` | headmaskene til dem |
| `01..14(...)kort.png` + `01..14-hairmask(...)` | korthårsvariantene til dem |
| `forside(...)kort.png` + `forside-hairmask(...)` | korthårsvarianten av forsiden |

Forsiden og baksiden selv ble **ikke** byttet — de ligger fortsatt i `input/`
og i `base/`.

## Hvorfor korthårsvariantene ble tatt ut av `input/`

Korthårsmalene viser de GAMLE illustrasjonene. Hadde de blitt liggende, ville
en ordre med kort hår fått gammel kunst med ny tekst — uten at noe stoppet
den. Det er nøyaktig feilklassen «stille fallback» i CLAUDE.md: koden finner
en fil, velger den, og sier ingenting.

`hair_variant_filename` gir `None` når fila ikke finnes, så boka faller
tilbake på standardmalen. `available_hair_variants` returnerer nå bare
`['langt']`, og botten viser ingen 💇-knapp for denne boka.

Forsidens korthårsvariant er fortsatt gyldig kunst, men ble tatt ut sammen med
de andre: ett riktig omslag og fjorten sider med langt hår er verre enn ingen
variant i det hele tatt.

## Slik får du korthårsvarianten tilbake

Krever at ComfyUI kjører (port 8189), og bør ikke kjøres mens en ordre går:

```powershell
python flow\make_shorthair_templates.py --book den-magiske-bursdagen-jente --dry-run
python flow\make_shorthair_templates.py --book den-magiske-bursdagen-jente --apply
```

Se over `output\shorthair\den-magiske-bursdagen-jente\` før variantene tas i
bruk — hårmasken segmenteres automatisk og kan bomme.

# tunnel/ — cloudflared

Tunnelen er det eneste som slipper trafikk **inn** til maskinen. Alt utgående
— RabbitMQ over Tailscale, Gelato, Google Drive, Telegram — fungerer uten den
og skal ikke røres.

## Status: ikke satt opp. Dette trenger deg.

`config.yml` er skrevet og klar, men den er **ikke i bruk**, og det er ikke en
forglemmelse. Slik ser det ut på maskinen nå:

```
Windows-tjeneste "Cloudflared"   Running, Automatic
  kommandolinje:  cloudflared.exe tunnel run --token eyJhIjoi…
  tunnel:         d9b1ec20-d7a4-421b-9d56-ba1ce8305aca
  eksponerer:     admin.dreampage.store  ->  localhost:3000
```

`--token` betyr **fjernstyrt ingress**: rutene ligger i Cloudflare-dashbordet,
ikke i en lokal fil. En `config.yml` på disk blir fullstendig ignorert av en
slik tunnel. Å bare legge filen her og starte tjenesten på nytt ville derfor
ikke gjort noe — eller, verre, ville tatt ned `admin.dreampage.store`.

Det finnes også en *annen*, ubrukt named tunnel i
`~/.cloudflared/1506ea11-9ebb-4037-956e-b8a664b70379.json` med en `config.yml`
som peker på `remote.hageai.com` — et annet prosjekt. Ikke rør den.

## To veier videre

### Vei 1 — legg hostnavnet til på den eksisterende tunnelen (minst risiko)

Rører ikke den kjørende tjenesten. I Cloudflare-dashbordet:

1. Zero Trust → Networks → Tunnels → tunnelen `d9b1ec20…`
2. Public Hostnames → Add a public hostname
   - Subdomain: `desktop-tif6h5b`
   - Domain: `dreampage.store`
   - Path: `api` *(og en egen oppføring for `panel`)*
   - Service: `HTTP` → `127.0.0.1:8765`
3. Sørg for at det finnes en catch-all som gir 404 for alt annet på det
   hostnavnet.

Ulempen: konfigurasjonen er ikke i git, som er hele grunnen til at vi
migrerer bort fra n8n. Den er da ett klikk fra å bli borte uten spor.

### Vei 2 — konverter til named tunnel med `config.yml` (det oppdraget ber om)

Gir konfigurasjonen i git og diffbar historikk. Krever et kort avbrudd for
`admin.dreampage.store`, så gjør det når ingen ordre kjører
(`.\dreampage.ps1 status`).

```powershell
# 1. logg inn (åpner nettleser, velger sone)
cloudflared tunnel login

# 2. lag tunnelen. Skriver credentials til ~\.cloudflared\<id>.json
cloudflared tunnel create desktop-tif6h5b

# 3. flytt legitimasjonen hit og skriv id-en inn i config.yml.
#    credentials.json står i .gitignore - den er en nøkkel, ikke konfigurasjon.
Move-Item "$env:USERPROFILE\.cloudflared\<ID>.json" C:\DreamPage-OS\tunnel\credentials.json
#    ... og bytt REPLACE_WITH_TUNNEL_ID i config.yml med <ID>

# 4. DNS-ruten
cloudflared tunnel route dns desktop-tif6h5b desktop-tif6h5b.dreampage.store

# 5. prøv den i forgrunnen FØRST, uten å røre tjenesten
cloudflared --config C:\DreamPage-OS\tunnel\config.yml tunnel run

# 6. virker den, bytt tjenesten over
Stop-Service Cloudflared
sc.exe delete Cloudflared
cloudflared --config C:\DreamPage-OS\tunnel\config.yml service install
Start-Service Cloudflared
```

**`admin.dreampage.store` må være med i `config.yml` før steg 6.** Den ligger
allerede inne i filen, men verifiser at porten (3000) stemmer — ingenting
lytter på 3000 på denne maskinen i dag, så dashbordet kjører et annet sted,
eller er ikke startet.

## Verifiser fra utsiden

Kjør dette fra en annen maskin, ikke herfra — en lokal test går ikke gjennom
tunnelen og beviser ingenting.

```bash
# skal gi 401: tunnelen er transport, tokenet er autentisering
curl -si https://desktop-tif6h5b.dreampage.store/api/health | head -1

# skal gi 200
curl -si -H "Authorization: Bearer <token>" \
     https://desktop-tif6h5b.dreampage.store/api/health | head -1

# skal gi 404 - ingenting annet enn API-stien er rutet
curl -si https://desktop-tif6h5b.dreampage.store/ | head -1

# ComfyUI og n8n skal IKKE være nåbare noe sted via domenet
curl -si https://desktop-tif6h5b.dreampage.store/system_stats | head -1
curl -si https://desktop-tif6h5b.dreampage.store/rest/login | head -1
```

Og fra maskinen selv, for å bekrefte at portene ikke er åpnet i ruteren:

```powershell
# 8188 lytter på 0.0.0.0 fordi ComfyUI startes med --listen. Det er greit på
# LAN/Tailscale, men skal aldri komme ut gjennom tunnelen.
Get-NetTCPConnection -LocalPort 8188,5678,8765,8790 -State Listen |
  Select-Object LocalAddress, LocalPort
```

## Cloudflare Access

Verdt å vurdere foran API-et: da må en forespørsel både passere Access og ha
bearer-tokenet. Det gjør at et lekket token alene ikke er nok. Merk at Access
sender en interaktiv innloggingsflyt, så dashbordet må bruke en service token
(`CF-Access-Client-Id` / `CF-Access-Client-Secret`) og ikke en nettleserøkt.

## Filer her

| Fil | I git | Merknad |
|---|---|---|
| `config.yml` | ja | ingress. `REPLACE_WITH_TUNNEL_ID` må byttes |
| `credentials.json` | **nei** | tunnelnøkkel. `.gitignore` |
| `README.md` | ja | denne |

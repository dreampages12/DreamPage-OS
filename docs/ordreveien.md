# Hvordan en ordre faktisk kommer inn

Skrevet 2026-09-16 etter å ha verifisert det mot broker og n8n-API, fordi
antakelsen vi jobbet etter var **feil** og det er en farlig ting å ta feil om.

## Veien, verifisert

```
WordPress / WooCommerce
      |
      |  publiserer SELV til RabbitMQ.
      |  payload: source = "dreampage_woocommerce"
      |           checkout_source = "store_api_checkout"
      v
RabbitMQ  100.118.194.49:5672  vhost dreampages
      |
      |  kø: dreampage-jobs    (1 konsument = flow-workeren)
      v
flow/worker  ->  DreamPage-image (ComfyUI)  ->  output/ -> PDF -> Drive -> Gelato-utkast
```

**n8n er ikke i denne veien.** Verifisert tre uavhengige veier:

1. Ingen aktiv n8n-workflow publiserer til `dreampage-jobs`. De to som gjør
   det — `67s2WDaxTqGGDNpj` «Main-Dreampage» og `xy8qiRUzcBpH52CI` «Dreampage
   Worker v2» — er **begge deaktivert**.
2. Payloaden sier `source: dreampage_woocommerce`, altså ikke formet av en
   n8n-node.
3. `dreampage-jobs` har **1 konsument**: vår worker. Ingen produsent på denne
   maskinen.

### Hva den ENE aktive n8n-workflowen faktisk gjør

`G0skxlQwcLhDH3NT` «My workflow 3» er `POST /webhook/dp-preview-001` →
RabbitMQ **`preview-jobs`**. Det er nettsidens forhåndsvisning, ikke en
bokordre. Tidligere notater kalte den «WooCommerce → RabbitMQ-produsenten som
må leve» — det stemmer ikke, og forvekslingen kommer av at begge ender i
RabbitMQ.

`preview-jobs` har i dag **0 konsumenter**: alle `DP Preview Worker`-workflows
er deaktiverte. Forhåndsvisningen på nettsiden håndteres altså et annet sted,
eller ikke i det hele tatt. Det er ikke en regresjon fra migreringen, men det
er verdt å vite.

## Hva n8n likevel brukes til — og hvorfor prosessen ikke må leve

To steder i produksjonskoden rører n8n, og **begge leser SQLite-filen
direkte**, ikke HTTP-API-et:

| Fil | Bruk |
|---|---|
| `flow/dp_order.py` | slår opp payloaden for GAMLE ordre som ikke finnes i `state/orders/` |
| `flow/n8n_credential.py` → `flow/drive_upload.py` | dekrypterer Google Drive-legitimasjonen fra `credentials_entity` |

```
C:\Users\tobia\.n8n\database.sqlite      <- filen MÅ bevares
C:\Users\tobia\.n8n\config               <- encryptionKey, MÅ bevares
```

Et søk på `5678` i all produksjonskode gir null treff. **n8n-prosessen kan
altså være nede uten at en bokordre stopper.** Det som ikke må forsvinne er
de to filene over.

### Konsekvens for drift

n8n kjører i dag elevert (pid 7556 per 16.09.2026), startet for hånd, med
**ingen** scheduled task, tjeneste eller Startup-snarvei. Etter en omstart
kommer den ikke tilbake.

Det er bevisst ikke lagt inn i `dreampage.ps1 ensure`:

* bokordrene trenger den ikke,
* den ene aktive workflowen har ingen konsument på andre siden likevel,
* og en autostart som kommer opp med andre miljøvariabler enn den kjørende
  (f.eks. `WEBHOOK_URL`) er en ny feilkilde, ikke en fjernet.

Skal den startes igjen: `C:\Users\tobia\AppData\Roaming\npm\n8n.cmd start`
(global npm-installasjon, `n8n@1.115.3`). Trenger **ikke** elevering.

## Hva som ville skjedd ved en omstart FØR 2026-09-16

* dp_bot: kom tilbake (egen scheduled task siden 12.08.2026)
* **DreamPage-image: kom IKKE tilbake**
* **flow-workeren: kom IKKE tilbake**
* mockup-serveren: kom ikke tilbake
* n8n: kom ikke tilbake

Ordrene ville ligget og hopet seg opp i `dreampage-jobs` uten at noe sa fra —
RabbitMQ tar vare på dem, så ingenting ville gått tapt, men ingenting ville
blitt bygget heller. Det er nå dekket av scheduled task **«DreamPage OS»**
(`dreampage.ps1 ensure`, hvert 5. minutt + ved innlogging).

## Slik sjekker du veien selv

```powershell
# 1. konsumerer vi køen?
curl -H "Authorization: Bearer <status-token>" http://127.0.0.1:8765/api/status
#    -> queue.connected = true, workload.accepting_jobs = true

# 2. hvilke n8n-workflows er aktive?
python tools\migrate\n8n_workflow.py list
```

```python
# 3. hvem står på køene, direkte mot broker
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

Forventet: `0 meldinger, 1 konsumenter` når det er stille. Er
`consumer_count` **0**, er workeren nede og ordrene stopper — det er den ene
linjen som betyr mest.

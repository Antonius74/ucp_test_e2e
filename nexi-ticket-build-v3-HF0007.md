# Ticket Nexi – XPay Build v3: HF0007 su PAY_WITH_CARD al confirmData

**Prodotto:** XPay Build, versione 3 (Hosted Fields)
**Ambiente:** TEST / sandbox – `https://xpaysandbox.nexigroup.com`
**API key:** chiave di test sandbox `ee6a41f2-…` (la TEST key pubblica Nexi)
**Origine merchant (sviluppo):** `http://localhost:3000` (parametro `merchantUrl` allineato a questo valore)

---

## Oggetto

Build v3: il `confirmData()` fallisce con **HF0007 – Validation error** segnalando l'azione
`PAY_WITH_CARD` come `valid:false`, mentre **tutti** i campi carta (`CARD_FIELD`) risultano
`valid:true`. Chiediamo la sequenza di conferma corretta per il flusso in cui la carta è
esposta come azione `PAY_WITH_CARD`.

## Descrizione del flusso osservato

1. `POST /api/phoenix-0.0/psp/api/v1/orders/build` con `"version":"3"` → risposta **200**.
   I `fields` tornano **tutti** con `type:"ACTION"`: 14 APM + un campo carta
   `{ "class":"CARD", "type":"ACTION", "id":"PAY_WITH_CARD", "src":".../phoenix-0.0/v3/?id=PAY_WITH_CARD&…" }`.
   (Nessun `CARD_FIELD` inline restituito a questo passo.)

2. Montiamo l'iframe `PAY_WITH_CARD` e l'utente lo clicca →
   `POST /fe/build/action/PAY_WITH_CARD` → **200** con
   `{"event":"BUILD_FLOW_STATE_CHANGE","state":"CARD_DATA_COLLECTION","fieldSet":{ "fields":[ … ] }}`.
   Il `fieldSet` contiene 5 campi, tutti `class:"CARD_FIELD"`, `type:"TEXT"`:
   `CARD_NUMBER`, `EXPIRATION_DATE`, `SECURITY_CODE`, `CARDHOLDER_NAME`, `CARDHOLDER_EMAIL`.
   **Non** viene restituito alcun campo `PRIVACY_CONDITIONS`.

3. Renderizziamo dinamicamente i 5 iframe del `fieldSet`, l'utente compila con una carta di test.
   Gli eventi `BUILD_SUCCESS` per i singoli campi arrivano correttamente (campi validi).

4. Sul nostro pulsante di conferma chiamiamo `build.confirmData(loader)` →
   evento **`CONFIRM_ERROR`**:

   ```json
   {
     "event": "CONFIRM_ERROR",
     "id": "confirmData",
     "errorCode": "HF0007",
     "errorMessage": "Validation error",
     "validationStatus": [
       { "id": "CARD_NUMBER",      "valid": true  },
       { "id": "PAY_WITH_CARD",    "valid": false },
       { "id": "EXPIRATION_DATE",  "valid": true  },
       { "id": "SECURITY_CODE",    "valid": true  },
       { "id": "CARDHOLDER_NAME",  "valid": true  },
       { "id": "CARDHOLDER_EMAIL", "valid": true  }
     ]
   }
   ```

   Tutti i `CARD_FIELD` sono `valid:true`; **solo l'azione `PAY_WITH_CARD` è `valid:false`**.

## Tentativi già effettuati (e relativi esiti)

- **Ri-eseguire l'azione** dopo la compilazione: `build.clickAction("PAY_WITH_CARD")` →
  `POST /fe/build/action/PAY_WITH_CARD` → **400 Bad Request** → evento
  `BUILD_ERROR errorCode:"HF0002" "Service temporarily unavailable"`.
- **Riordinare/rimuovere il frame azione** lato client prima del `confirmData`: nessun effetto
  sul `validationStatus` (la validazione di `PAY_WITH_CARD` resta `valid:false`), il che indica
  che la valutazione è **lato server/terminale**, non lato frame client.
- **Rimuovere dal DOM l'iframe `PAY_WITH_CARD`** dopo `CARD_DATA_COLLECTION`: la sessione
  scade → `BUILD_ERROR errorCode:"HF0003" "Session expired"`.
- Si osservano inoltre `BUILD_ERROR HF0002 "Service temporarily unavailable"` intermittenti.

## Domande a Nexi

1. Qual è la **sequenza di conferma corretta** in Build v3 quando il metodo carta è esposto
   come **azione `PAY_WITH_CARD`** (e non come `CARD_FIELD` inline diretti)? È previsto
   `confirmData()`, oppure una `clickAction` finale, oppure una chiamata API
   (`/build/finalize_payment`) senza `confirmData`?

2. Perché l'azione `PAY_WITH_CARD` resta **`valid:false`** al `confirmData()` quando **tutti**
   i `CARD_FIELD` sono `valid:true`? Cosa deve essere soddisfatto perché l'azione risulti valida?

3. È richiesto un campo **`PRIVACY_CONDITIONS`** che il nostro terminale **non** restituisce nel
   `fieldSet`? In tal caso, come va abilitato sul terminale?

4. Il terminale sandbox associato alla API key in oggetto è **configurato per completare un
   pagamento carta** tramite Build v3 Hosted Fields? Se no, quali credenziali/terminale di test
   dobbiamo usare?

## Dati utili per la ricerca lato Nexi

> (Sostituire/integrare con i valori della propria sessione; allegare l'HAR completo.)

- `sessionId` esempio: `28a00084-635a-4e28-bbe9-aee4c8f4dda7`
- `correlationid` esempio: `4eacc130-e773-49ad-b91f-75209caa2da8`
- `transactionId` (da `/fe/build/field_settings/PAY_WITH_CARD`): `324126478022861609`
- `cid` upstream build esempio: `49b64e50-af5a-4dea-b5ea-2c11191da823`
- Data/ora dei test, fuso `Europe/Rome`.

## Allegati consigliati

- HAR del browser dell'intero flusso (build → action → confirmData).
- Screenshot del form con i campi carta renderizzati.
- Log console con gli eventi SDK (`BUILD_FLOW_STATE_CHANGE`, `CONFIRM_ERROR`, `BUILD_ERROR`).

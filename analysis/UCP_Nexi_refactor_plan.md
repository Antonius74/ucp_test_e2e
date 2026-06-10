# Piano di refactor — Due payment handler Nexi dentro il perimetro UCP

**Ottica del piano:** l'unità primaria del design è il **payment handler UCP**, non il gateway. Si dichiarano due handler reali (`nexi_card`, `nexi_googlepay`) nel contratto `payment.handlers` di `ucp.json`; dietro ciascun handler vive un gateway server-side che parla con Nexi. La differenziazione tra metodi vive nel **contratto dichiarato** (`id`, `spec`, `config`, `instrument_schemas`), non in branching ad-hoc.

**Obiettivo invariato:** l'autorizzazione Nexi reale (incluso il 3DS) avviene *dentro* la cascata A2A `MockPaymentProcessor → MerchantAgentA2A → gateway`, e finisce nel `a2a.protocol_trace`. Niente più token sintetici né autorizzazione sul canale laterale `/nexi/*`.

**Vincolo libreria:** `nexi_xpay.py` resta una libreria; si aggiunge solo un wrapper (`get_order`). Cambia *chi* la invoca: dai route chiamati dal frontend → dal gateway dietro l'handler.

---

## 1. Modello target (handler-centric)

I tre handler dichiarati in `data/ucp.json → payment.handlers[]`:

| Handler `id` | Metodo | `instrument` (credential) | Config rilevante | Gateway dietro | Endpoint Nexi | 3DS |
|---|---|---|---|---|---|---|
| `example_payment_provider` | Apple Pay (demo) | token mock | `business_id` | `MockUcpPaymentGateway` | — (mock) | n/a |
| `nexi_card` | Carta (hosted fields) | token build session (`sessionId`) | merchant_url, terminal carta | `NexiCardGateway` | `/orders/build` → `/build/finalize_payment` → `/build/state` | sì |
| `nexi_googlepay` | Google Pay | token wallet di rete (`googlePayPaymentData`) | `NEXI_GOOGLEPAY_MERCHANT_ID`/`_TERMINAL_ID`/`_GATEWAY` | `NexiGooglePayGateway` | `/orders/googlepay` → `GET /orders/{orderId}` | sì |

Perché due handler Nexi distinti e non uno solo: carta e Google Pay divergono in **endpoint**, **config** (merchant/terminal ID dedicati per GP, `nexi_xpay.py:243-256`) e **forma dell'instrument** (token da PAN su hosted-fields vs token wallet). Essendo questi esattamente i campi che definiscono un handler UCP, la granularità "un handler per metodo" è quella aderente. Apple Pay resta sul mock per la demo; se reso reale via Nexi diventerebbe un quarto handler `nexi_applepay` (distinguibile da `wallet_provider` nell'instrument).

### Negoziazione (come il client sceglie l'handler)

Il flusso credential-provider esistente è già per-handler: `getSupportedPaymentMethods(email, handler.config)`. Con più handler, il client mappa ciascun bottone UI (Carta / Google Pay / Apple Pay) all'handler corrispondente trovato in `checkout.payment.handlers`, e produce un `PaymentInstrument` con il `handler_id` giusto. Niente più ricerca hard-coded di `example_payment_provider` (`App.tsx:502`).

### Flusso end-to-end (target)

```
Client → seleziona handler → costruisce PaymentInstrument(handler_id, token reale)
       → complete_checkout (cascata A2A)
MerchantAgentA2A → risolve handler_id → gateway corrispondente
Gateway → Nexi (authorize)
   ├─ frictionless → approved → place_order
   └─ 3DS → requires_action + url → client apre challenge → complete_checkout #2 → poll esito → approved/declined
```

Il 3DS adotta l'**Opzione C** (cascata in due fasi con `TaskState.auth-required`), già discussa: la pausa per l'azione utente è modellata nativamente dal protocollo A2A.

---

## 2. Fasi di implementazione

### Fase 0 — Rete di sicurezza
1. Test di non-regressione sul flusso mock (`example_payment_provider` + Apple Pay) in `tests/test_a2a_e2e.py`: deve continuare a passare a fine refactor.
2. Test: `handler_id` non registrato → `unsupported_handler`.
3. Fissare il **contratto di output del gateway** (shape di `MockUcpPaymentGateway.authorize_token`): `status`, `message`, `reason`, `provider`, `transaction_id`, `gateway_request_id`, `processed_at`, `network`, `risk_signals`. Aggiungere il nuovo stato `requires_action` con `redirect_url`. Tutti i gateway rispettano questo shape.

### Fase 1 — Contratto handler (UCP-facing, l'unità primaria)
1. `data/ucp.json`: aggiungere gli handler `nexi_card` e `nexi_googlepay` accanto a `example_payment_provider`, ciascuno con `spec`, `config_schema`, `config` e `instrument_schemas` propri.
2. Definire/riusare gli schema instrument: carta (`card_payment_instrument`) e Google Pay (card con `wallet_provider="google_pay"`).
3. Definire il **contratto del `credential`** per ciascun handler: `nexi_card` → `credential.token = sessionId` reale; `nexi_googlepay` → `credential.token`/blob = `googlePayPaymentData` reale. Niente più token finti (`nexi_build_<id>`, `nexi_googlepay_<id>`).
4. **Checkpoint:** il client vede tre handler; selezione per `id` funziona; nessun comportamento di pagamento ancora cambiato.

### Fase 2 — Realizzazione server-side: gateway dietro l'handler
1. Definire il protocollo `PaymentGateway`: `authorize_token(payment_data, risk_signals) -> dict` (sync, shape Fase 0.3). `MockUcpPaymentGateway` lo soddisfa già.
2. In `MerchantAgentA2A.__init__` sostituire il gateway singolo con un registry `handler_id → gateway`:
   ```python
   self._gateways = {
       "example_payment_provider": MockUcpPaymentGateway(),
       "nexi_card":      NexiCardGateway(),
       "nexi_googlepay": NexiGooglePayGateway(),
   }
   ```
3. In `_process_payment_token` (`a2a_subagents.py:597-611`) sostituire la guardia hard-coded `handler_id != "example_payment_provider"` con `gateway = self._gateways.get(handler_id)` → se `None`, `unsupported_handler`.
4. **Riconciliare il guard `credential.type` (fix del bug #1, vedi §4).** Oggi `_process_payment_token` declina ogni `credential.type != "token"` (`a2a_subagents.py:590`), ma gli instrument reali Nexi usano `nexi_build_operation`/`nexi_googlepay_operation` → verrebbero respinti come `invalid_token_format`. Rendere il guard **per-handler**: ciascun gateway dichiara i `credential.type` che accetta (mock→`token`, `nexi_card`→`nexi_build_operation`, `nexi_googlepay`→`nexi_googlepay_operation`), e il Merchant valida contro quel set invece che contro il letterale `"token"`.
5. **Checkpoint:** comportamento invariato finché i nuovi gateway non sono raggiungibili (il frontend non manda ancora i nuovi `handler_id`); il mock continua a passare. Mergeable da solo.

### Fase 3 — Bridge async→sync
Vincolo: `process_payment` è sync (`payment_processor.py:83`), Nexi è async.
- **Strategia consigliata (A):** i `Nexi*Gateway.authorize_token` restano sync e usano un helper che esegue la coroutine Nexi in modo sicuro anche dentro un event loop attivo (thread executor / `anyio.from_thread`). Zero modifiche alla firma di `process_payment`.
- Alternativa (B): rendere async la catena `process_payment` + i due call site (`agent.py:457`, `agent_executor.py:1096`). Più pulito, tocca più file.
- **Checkpoint:** unit test del bridge con coroutine fittizia.

### Fase 4 — `NexiCardGateway`
1. `authorize_token`: dal `credential.token` (= `sessionId`) chiama `finalize_build_payment(session_id)`.
   - `PAYMENT_COMPLETE` → `approved` (mappa `operation` → `transaction_id`, `provider="nexi.xpay.build.v3"`).
   - `REDIRECTED_TO_EXTERNAL_DOMAIN` → `requires_action` + `redirect_url`.
2. FASE 2 (resume): al `complete_checkout #2`, `get_build_state(session_id)` finché `PAYMENT_COMPLETE`/declino; mappa l'esito.
3. Errori `NexiUpstreamError`/`NexiConfigurationError` → `declined` con `reason` tipizzato (mai eccezioni grezze nella cascata).
4. **Checkpoint:** test contro Nexi TEST (usa il fallback chiave TEST già in `nexi_xpay.py`): approvazione, declino, `requires_action`.

### Fase 5 — `NexiGooglePayGateway`
1. Nuovo wrapper in `nexi_xpay.py`: `get_order(order_id) -> dict` su **`GET /orders/{orderId}`** (verificato in doc Nexi). L'`orderId` è deterministico da `_sanitize_order_id(checkout_id)` (`nexi_xpay.py:100`), quindi il gateway lo ricalcola senza nuovi parametri dal client.
2. `authorize_token`: dal token wallet chiama `process_googlepay_order(...)`.
   - `state=PAYMENT_COMPLETE`/`operation` → `approved`.
   - `state=REDIRECTED_TO_EXTERNAL_DOMAIN` + `redirectUrl` → `requires_action` + `redirect_url`.
3. FASE 2 (resume): al `complete_checkout #2`, `get_order(order_id)` e mappa `operation.operationResult`:
   - `THREEDS_VALIDATED` → `approved`;
   - `THREEDS_FAILED` / `DENIED_BY_RISK` → `declined`.
4. **Checkpoint:** test contro Nexi TEST: frictionless + ramo 3DS con resume.

### Fase 6 — Macchina a stati `requires_action`
Propagare il nuovo esito lungo la catena, oltre `incomplete → ready_for_complete → completed`:

| Stato checkout | Impostato da | Significato | Transizione |
|---|---|---|---|
| `ready_for_complete` | `start_payment` | buyer + fulfillment ok | → `requires_action` o `completed` |
| `requires_action` | gateway via cascata (3DS) | serve azione utente (challenge) | → `completed` (resume ok) / `failed` (resume ko) |
| `completed` | `place_order` | ordine confermato | terminale |

- L'executor mappa `gateway.status="requires_action"` → `TaskState.auth-required` + espone `redirect_url` nel `DataPart` di risposta; non chiama `place_order`.
- `place_order` solo su `approved`.
- La sessione resta agganciata a `contextId`/`taskId` → il resume (`complete_checkout #2`) ritrova checkout e handler.

### Fase 7 — Frontend (per-handler)
1. Mappare ciascun bottone UI all'handler: Carta → `nexi_card`, Google Pay → `nexi_googlepay`, Apple Pay → `example_payment_provider`. Rimuovere la ricerca hard-coded di `example_payment_provider` (`App.tsx:502`) e lo spoofing dell'`handler_id` (`App.tsx:301`, `NexiCardPaymentForm.tsx:362`).
2. **Carta:** mantenere build-session + hosted fields per la *raccolta* del dato sul dominio merchant; **non** finalizzare lato client. Costruire `PaymentInstrument(handler_id="nexi_card", credential.token=sessionId)` → `complete_checkout`. Rimuovere `finalizeSessionPayment` client.
3. **Google Pay:** mantenere il foglio nativo Google Pay (produce il token wallet, client-side per necessità). Non chiamare più `/api/nexi/googlepay-order` per autorizzare. Costruire `PaymentInstrument(handler_id="nexi_googlepay", credential=googlePayPaymentData)` → `complete_checkout`.
4. **Resume 3DS:** su risposta `auth_required` + `redirect_url`, aprire la tab ACS, poi a challenge completato inviare `complete_checkout #2` sullo stesso `taskId`/`contextId`. Sostituisce il dead-end attuale (`App.tsx:758-771`).
5. **Apple Pay:** nessuna modifica.

### Fase 8 — Pulizia route `/nexi/*`
- Mantenere `/nexi/build-session` e `/nexi/hfsdk.js` (servono alla raccolta hosted-fields sul dominio merchant) e i callback `resultUrl`/`notificationUrl`.
- `/nexi/finalize-payment`, `/nexi/build-state`, `/nexi/googlepay-order`: la logica di **autorizzazione** migra nei gateway. Le route possono restare come thin proxy temporaneo o essere rimosse quando il frontend non le usa più per autorizzare.

### Fase 9 — Verifica end-to-end
1. e2e per i tre handler: `example_payment_provider` (Apple Pay mock), `nexi_card`, `nexi_googlepay` (Nexi TEST) — tutti passano da `complete_checkout` → Merchant → gateway corretto.
2. Asserire che il `a2a.protocol_trace` (`mpp.last_exchange`) per carta/GP contenga ora l'autorizzazione **Nexi reale** (`provider="nexi.xpay.build.v3"`, `transaction_id` Nexi), non quella mock.
3. Percorsi: declino (ordine non piazzato), `requires_action` → resume ok, resume ko (`THREEDS_FAILED`).
4. Non-regressione mock + `unsupported_handler` per handler ignoti.

---

## 3. Sequenza, rischio, e cosa cambia rispetto alla versione precedente

| Fase | Tocca | Rischio | Note |
|---|---|---|---|
| 0 Test | tests | nullo | — |
| 1 Contratto handler | `ucp.json`, schemi | basso | **ora è la prima fase**: il contratto guida il design |
| 2 Gateway registry | `a2a_subagents.py` | basso | realizzazione server-side degli handler |
| 3 Bridge async | helper | medio | event loop |
| 4 NexiCardGateway | nuovo + Nexi | medio | 3DS via build/state |
| 5 NexiGooglePayGateway | nuovo + `get_order` | medio | 3DS via GET /orders/{orderId} |
| 6 Stato requires_action | executor, store, status | medio | unico vero stato nuovo |
| 7 Frontend | `App.tsx`, `NexiCardPaymentForm.tsx` | medio | per-handler + resume |
| 8 Route cleanup | `main.py` | basso | — |
| 9 Verifica e2e | tests | — | trace = auth reale |

**Differenze rispetto al piano precedente (gateway-centric):**
- Il **contratto handler** (Fase 1) diventa il punto di partenza, non un passaggio finale: prima si dichiarano i due handler con i loro `instrument_schemas`/`config`, poi si implementa il gateway dietro ciascuno.
- I gateway sono divisi **per handler** (`NexiCardGateway`, `NexiGooglePayGateway`) invece di un unico `NexiPaymentGateway` parametrizzato per metodo: ciascuno incapsula config ed endpoint propri, coerentemente con la divergenza reale tra i due flussi Nexi.
- Aggiunta la Fase 6 esplicita per lo stato `requires_action`, che resta il nodo architetturale principale.

**Rollout incrementale:** le Fasi 1-2 sono indipendenti dal frontend e non cambiano il comportamento osservabile (i nuovi handler non sono raggiungibili finché il client non li seleziona). Mergeabili da sole, a rischio quasi nullo.

---

## 4. Rischi, gap e prerequisiti

Verificati sul codice al commit corrente (`51d38db`). I fix recenti hanno irrobustito il canale laterale Nexi Build v3 / Google Pay staging, ma **non toccano la cascata** (`a2a_subagents.py`, `agent_executor.py`): i gap sotto sono tutti aperti.

### Bloccanti — da risolvere prima/durante i gateway

**#1 — Disallineamento `credential.type` tra frontend e Merchant guard (confermato, decline reale).**
`TokenCredentialResponse.type` è `str` (non un `Literal`), quindi `PaymentInstrument.model_validate` (`agent_executor.py:438`) accetta `nexi_build_operation`/`nexi_googlepay_operation`. Ma il Merchant declina ogni `credential.type != "token"` (`a2a_subagents.py:590`) → gli instrument reali carta/GP costruiti dal frontend (`App.tsx:304`, `NexiCardPaymentForm.tsx:385`) verrebbero respinti come `invalid_token_format`. I test e2e coprono solo `type:"token"`, quindi il ramo reale non è testato.
→ *Mitigazione:* guard `credential.type` per-handler (Fase 2.4). È anche il primo fix concreto del refactor.

**#4 — Stato in-memory vs pausa 3DS multi-minuto.**
Tra `complete_checkout #1` e `#2` l'utente è sull'ACS per minuti; il checkout vive in `RetailStore` + `InMemorySessionService`/`InMemoryTaskStore`. Riavvio o deploy multi-worker → il `#2` colpisce un processo senza quel checkout → ordine perso. Limite più serio oltre la demo a processo singolo.
→ *Mitigazione:* persistenza (store + session) o sticky-session per `contextId` prima di promettere il 3DS in produzione.

**#6 — Capture EXPLICIT: ordine piazzato ma fondi non catturati.**
Default `NEXI_XPAY_CAPTURE_TYPE=EXPLICIT` (`nexi_xpay.py:190`) = sola autorizzazione. Il piano fa `approved → place_order` senza capture (`/operations/{operationId}/captures`). Manca il lifecycle di settlement.
→ *Mitigazione:* decidere IMPLICIT (cattura immediata) oppure aggiungere uno step di capture al fulfillment.

### Architetturali — incidono sul design dei gateway

**#2 — L'executor emette `Message`, non `Task` con stato.**
Usa `new_agent_parts_message`/`enqueue_event` (`agent_executor.py:228+`), nessun `TaskUpdater`. Quindi l'`auth-required` "nativo A2A" dell'Opzione C non è cablato: il two-phase funziona a livello di `checkout.status=requires_action` nel `DataPart`, ma non come lifecycle di Task.
→ *Mitigazione:* accettare il modello message-based (funziona) **oppure** adottare `TaskUpdater`/Task — cambiamento più grosso, da valutare in Fase 6.

**#3 — Bridge async dentro event loop attivo.**
`complete_checkout` (tool ADK) e il fast-path girano in contesto async; un `asyncio.run()` nel gateway sync solleverebbe `RuntimeError`. Obbligatorio thread executor / `anyio.from_thread` (Fase 3).

**#5 — Due porte d'ingresso da tenere coerenti.**
Fast-path deterministico e tool ADK chiamano entrambi `process_payment`: il nuovo `requires_action`/resume va gestito identico in entrambi.

### Dominio pagamento — robustezza Nexi

**#7 — Idempotenza e `orderId`.**
Nessuna idempotency key nella cascata: un retry o un `#2` mal sincronizzato può ri-autorizzare. `_sanitize_order_id` tronca a 18 char (`nexi_xpay.py:104`) → tensione tra **orderId deterministico** (serve per rileggere l'esito GP via `GET /orders/{orderId}`) e **unicità Nexi su retry** (Nexi rifiuta orderId duplicati), più rischio collisione.

**#8 — 3DS non automatizzabile in CI + nessuna riconciliazione.**
Il challenge ACS richiede interazione manuale → in CI testi solo il ramo frictionless. Se l'utente non torna dopo l'ACS, l'ordine resta autorizzato a Nexi ma mai piazzato.
→ *Mitigazione:* job di riconciliazione o webhook `notificationUrl`; mock del ramo 3DS nei test.

### Residui / minori

**#9 — Apple Pay resta mock** → l'asimmetria da dichiarare al cliente si riduce a un metodo, non sparisce.
**#10 — Drift versione UCP:** client `?v=2026-01-11`, `ucp.json` `2026-01-11`, doc precedenti `2026-01-23`. Allineare i nuovi handler o scatta `VERSION_UNSUPPORTED` in `prepare_ucp_metadata`.
**#11 — `risk_signals` non consumati da Nexi** (fa il suo rischio via `exemptions`/3DS): beneficio "risk nel gateway" in parte cosmetico.

### Priorità d'attacco
Prima di scrivere i gateway: **#1** (sblocca il ramo reale), poi **#4** e **#6** (altrimenti il 3DS e l'incasso non reggono oltre la demo). **#2/#3** si affrontano contestualmente alle Fasi 3 e 6.

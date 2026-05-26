<!--
   Copyright 2026 UCP Authors

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
-->

# Cymbal Retail Agent (A2A + UCP + Ollama + Nexi)

This service is the backend of the A2A/UCP shopping demo. It exposes:
- A2A JSON-RPC `message/send` endpoint for the chat client
- UCP discovery endpoints
- Nexi proxy endpoints for Build v3 card flow and Google Pay server-side forwarding

## What This Backend Does

1. Negotiates UCP capabilities using `X-A2A-Extensions` and `UCP-Agent` headers.
2. Executes shopping actions (catalog, cart, checkout, orders) through deterministic paths and ADK/Ollama paths.
3. Handles payment completion in two modes:
- UCP token completion (`complete_checkout`) through merchant mock authorization
- Real Nexi proxy flows for card collection (Build v3) and Google Pay order forwarding.

## Prerequisites

1. Python 3.10+
2. [Ollama](https://ollama.com/) running locally
3. Pulled model (default): `gpt-oss:120b-cloud`

## Quick Start

1. Start Ollama:

```bash
/usr/local/bin/ollama serve
```

2. Install dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

3. Configure environment:

```bash
cp env.example .env
```

4. Run backend:

```bash
.venv/bin/python -m business_agent.main --host 127.0.0.1 --port 10999
```

5. Verify endpoints:
- Agent Card: http://127.0.0.1:10999/.well-known/agent-card.json
- UCP Profile: http://127.0.0.1:10999/.well-known/ucp

## HTTP Endpoints

### Discovery + A2A
- `POST /` -> A2A JSON-RPC `message/send`
- `GET /.well-known/agent-card.json`
- `GET /.well-known/ucp`

### Observability/Debug Pages
- `GET /orders`
- `GET /orders/{order_id}`
- `GET /checkouts/{checkout_id}`
- `GET /reservations`

### Nexi Proxy Endpoints
- `POST /nexi/build-session` -> Nexi `POST /orders/build`
- `POST /nexi/finalize-payment` -> Nexi `POST /build/finalize_payment`
- `GET /nexi/build-state?sessionId=...` -> Nexi `GET /build/state`
- `GET /nexi/hfsdk.js` -> same-origin proxy for Nexi hosted fields SDK
- `POST /nexi/googlepay-order` -> Nexi `POST /orders/googlepay`
- `GET /googlepay/pay.js` -> same-origin proxy for Google Pay web SDK script

## Nexi Build v3 + Google Pay Configuration

Current default behavior in this branch:
- Card flow base: sandbox/prod based on `NEXI_XPAY_ENV`
- Google Pay endpoint: staging `stg-ta.nexigroup.com` (explicit URL)
- Google Pay fallback: disabled by default
- Google Pay header key is sent as `x-api-key` (header)

### Environment Variables

- `BUSINESS_AGENT_MODEL=ollama/gpt-oss:120b-cloud`
- `OLLAMA_API_BASE=http://127.0.0.1:11434`

- `NEXI_XPAY_ENV=TEST|PROD`
- `NEXI_XPAY_API_KEY=<build-api-key>`
- `NEXI_XPAY_API_BASE=<optional override>`
- `NEXI_XPAY_MERCHANT_URL=https://your-domain.tld`
- `NEXI_XPAY_RESULT_URL=https://your-domain.tld/ucp-order/{orderId}`
- `NEXI_XPAY_CANCEL_URL=https://your-domain.tld/ucp-cancel`
- `NEXI_XPAY_NOTIFICATION_URL=<optional>`
- `NEXI_XPAY_LANGUAGE=ita`
- `NEXI_XPAY_CAPTURE_TYPE=EXPLICIT|IMPLICIT`
- `NEXI_XPAY_ENABLE_TEST_KEY_FALLBACK=true|false`
- `NEXI_XPAY_TEST_FALLBACK_API_KEY=<optional>`

- `NEXI_GOOGLEPAY_ENDPOINT=https://stg-ta.nexigroup.com/api/phoenix-0.0/psp/api/v1/orders/googlepay`
- `NEXI_GOOGLEPAY_API_KEY=<googlepay-api-key>`
- `NEXI_GOOGLEPAY_MERCHANT_ID=999999990`
- `NEXI_GOOGLEPAY_TERMINAL_ID=0000999`
- `NEXI_GOOGLEPAY_GATEWAY=nexigtw`
- `NEXI_GOOGLEPAY_ENABLE_FALLBACK=false`
- `NEXI_GOOGLEPAY_CAPTURE_TYPE=IMPLICIT|EXPLICIT`

## Payment Flow Details

### Card (Nexi Build v3)

1. Frontend requests `POST /nexi/build-session`.
2. Backend calls Nexi `orders/build` with `version: "3"` and returns `sessionId` + `fields`.
3. Frontend loads hfsdk through `GET /api/nexi/hfsdk.js` (same-origin proxy).
4. User confirms with `Build.confirmData(...)`.
5. On `READY_FOR_PAYMENT`, frontend triggers `POST /nexi/finalize-payment`.
6. If event callbacks are delayed/missing, frontend polls `GET /nexi/build-state` as fallback.
7. Final state:
- `PAYMENT_COMPLETE` + `operation` -> mapped to UCP payment instrument and checkout completion
- `REDIRECTED_TO_EXTERNAL_DOMAIN` -> 3DS redirect.

### Google Pay

1. Frontend loads Google Pay SDK from `GET /api/googlepay/pay.js` (same-origin proxy, direct fallback available).
2. On `loadPaymentData(...)`, tokenized `googlePayPaymentData` is forwarded to `POST /nexi/googlepay-order`.
3. Backend posts payload to configured Nexi staging endpoint using `x-api-key` header and runtime `correlation-id`.
4. Backend returns raw upstream details (`errors`, `upstreamCid`, `endpointUsed`) for clear troubleshooting.

## Current Known Behaviors

- If Nexi returns `401 UNAUTHORIZED Authorization Missing` on staging, request is reaching Nexi but credentials/authorization are not accepted upstream.
- If Nexi returns `PS0167`, request passed auth checks but Google Pay upstream service rejected token/session payload.
- Backend surfaces error details and correlation IDs to help support troubleshooting.

## Testing

Run E2E suite:

```bash
cd a2a/business_agent
.venv/bin/python -m unittest -v tests/test_a2a_e2e.py
```

The current suite includes:
- A2A/UCP discovery and checkout lifecycle
- Nexi build session endpoint
- Nexi hosted SDK proxy endpoint
- Nexi build state endpoint
- Google Pay script proxy endpoint
- order history and protocol trace checks

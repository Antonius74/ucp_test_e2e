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

# Universal Commerce Protocol (UCP) Samples

This repository contains multiple reference implementations of the Universal
Commerce Protocol (UCP), including a complete Agent-to-Agent (A2A) shopping
demo with a React chat UI and an Ollama-backed model.

## Repository Layout

| Area | Path | Purpose |
| --- | --- | --- |
| A2A demo (recommended) | `a2a/` | End-to-end shopping assistant with A2A JSON-RPC + UCP extension |
| Python REST sample | `rest/python/server/` | FastAPI merchant server reference |
| Python REST client | `rest/python/client/flower_shop/` | Happy-path buyer script |
| Node.js REST sample | `rest/nodejs/` | Hono + Zod merchant server reference |

## Featured Demo: A2A + UCP Shopping Agent

The `a2a/` demo is the most complete example in this repo. It shows:
- UCP capability negotiation through A2A request headers.
- Product discovery and checkout lifecycle with typed UCP payloads.
- Multi-agent orchestration with Shop Agent + Merchant Agent over A2A-style
  `message/send` interactions.
- Nexi XPay Build v3 card hosted-fields flow via backend proxy endpoints.
- Google Pay Web API integration with server-side forwarding to Nexi staging.
- UCP checkout completion using payment operation/token payloads.
- Protocol observability from the frontend dashboard (JSON-RPC payloads, A2A
  traces, token metadata).

Architecture diagram:

![A2A UCP Architecture](a2a/assets/architecture_diagram.webp)

### Core Components

| Component | Location | Responsibility |
| --- | --- | --- |
| React Chat Client | `a2a/chat-client/` | Sends JSON-RPC `message/send`, renders products/checkout/payment flows |
| A2A Server | `a2a/business_agent/src/business_agent/main.py` | Exposes `/api`, `/.well-known/agent-card.json`, `/.well-known/ucp` |
| ADK Executor | `a2a/business_agent/src/business_agent/agent_executor.py` | Routes between direct actions, fast paths, and full ADK/LLM execution |
| Shop Agent (A2A) | `a2a/business_agent/src/business_agent/a2a_subagents.py` | Handles catalog and checkout actions |
| Merchant Agent (A2A) | `a2a/business_agent/src/business_agent/a2a_subagents.py` | Simulates payment authorization/gateway response |
| Commerce Store | `a2a/business_agent/src/business_agent/store.py` | In-memory products, cart, checkout, orders |

### How Model Interaction Works

The backend does not always call the model. It uses a hybrid strategy:

1. Deterministic path for structured actions.
   `{"action":"add_to_checkout"}`, `{"action":"complete_checkout"}`, and similar
   payloads are executed directly for speed and predictability.
2. Fast-path for common catalog intents.
   Queries like "show products" can bypass full reasoning and return typed
   results quickly.
3. Full ADK + Ollama path for open natural language requests.
   Complex requests are executed through Google ADK tooling with Ollama model
   backend (default: `ollama/gpt-oss:120b-cloud`).

This design keeps the UX responsive while preserving model flexibility where it
matters.

### Protocol Exchange (A2A + UCP)

Each chat request is a JSON-RPC 2.0 call to `/api`:
- Method: `message/send`
- Header `X-A2A-Extensions` declares the UCP extension URI.
- Header `UCP-Agent` points to the buyer profile used for capability
  negotiation.
- Response parts return mixed content:
  - `text` for conversational output.
  - `data` for typed UCP payloads such as:
    - `a2a.product_results`
    - `a2a.ucp.checkout`
    - `a2a.orders`
    - `a2a.protocol_trace`

### Payment in the Demo

The payment flow includes both real PSP proxy integrations and UCP completion:
- Card payment form with Nexi Build v3 hosted fields (`orders/build` + `build/finalize_payment`).
- Google Pay Web SDK flow, with tokenized payload forwarded by backend to Nexi `orders/googlepay`.
- Build-state fallback polling (`/build/state`) to recover from delayed/missing SDK transitions.
- Optional saved-card UX and wallet selections in chat UI.
- Merchant-side checkout finalization through UCP payment data and protocol trace.

## Quick Start (A2A Demo)

### 1) Start backend

```bash
cd a2a/business_agent
python3 -m venv .venv
.venv/bin/python -m pip install -e .
cp env.example .env
BUSINESS_AGENT_MODEL=ollama/gpt-oss:120b-cloud \
OLLAMA_API_BASE=http://127.0.0.1:11434 \
.venv/bin/python -m business_agent.main --host 127.0.0.1 --port 10999
```

### 2) Start frontend

```bash
cd a2a/chat-client
npm install
npm run dev -- --host 127.0.0.1 --port 3000
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000).

## Testing

- A2A E2E test suite:
  `cd a2a/business_agent && .venv/bin/python -m unittest -v tests/test_a2a_e2e.py`
- Frontend production build check:
  `cd a2a/chat-client && npm run build`

## Additional Documentation

- A2A demo deep dive: [a2a/README.md](a2a/README.md)
- Backend quickstart: [a2a/business_agent/README.md](a2a/business_agent/README.md)
- Architecture docs set: `a2a/docs/`
- Python REST sample: [rest/python/server/README.md](rest/python/server/README.md)
- Node.js REST sample: [rest/nodejs/README.md](rest/nodejs/README.md)

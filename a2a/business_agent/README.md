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

# Cymbal Retail Agent

Example agent implementing A2A Extension for UCP

### Pre-requisites:

1. Python 3.10+
2. [Ollama](https://ollama.com/) running locally
3. Pulled model (default): `gpt-oss:120b-cloud`

## Quick Start

1. Start Ollama:

   ```bash
   /usr/local/bin/ollama serve
   ```

2. In a new terminal, set up Python env and install dependencies:

   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install -e .
   ```

3. Copy env file and keep defaults (Ollama):

   ```bash
   cp env.example .env
   ```

4. Run the server:

   ```bash
   .venv/bin/python -m business_agent.main
   ```

5. Verify endpoints:
   - Agent Card: http://localhost:10999/.well-known/agent-card.json
   - UCP Profile: http://localhost:10999/.well-known/ucp

## Nexi XPay Build v3 (Card Payment)

The chat client card checkout now uses Nexi XPay Build v3 via backend proxy endpoints:
- `POST /nexi/build-session` -> calls Nexi `POST /orders/build`
- `POST /nexi/finalize-payment` -> calls Nexi `POST /build/finalize_payment`
- `POST /nexi/googlepay-order` -> calls Nexi `POST /orders/googlepay`

Environment variables:

- `NEXI_XPAY_ENV=TEST|PROD`
- `NEXI_XPAY_API_KEY=<your-api-key>`
- `NEXI_XPAY_MERCHANT_URL=https://your-domain.tld`
- `NEXI_XPAY_RESULT_URL=https://your-domain.tld/nexi/result`
- `NEXI_XPAY_CANCEL_URL=https://your-domain.tld/nexi/cancel`
- `NEXI_XPAY_NOTIFICATION_URL=https://your-domain.tld/nexi/notify` (optional)
- `NEXI_XPAY_LANGUAGE=ita`
- `NEXI_GOOGLEPAY_ENDPOINT=https://stg-ta.nexigroup.com/phoenix-0.0/psp/api/v1/orders/googlepay`
- `NEXI_GOOGLEPAY_MERCHANT_ID=999999990`
- `NEXI_GOOGLEPAY_TERMINAL_ID=0000999`
- `NEXI_GOOGLEPAY_GATEWAY=nexigtw`

Note: Nexi Build requires a valid merchant URL domain (HTTP/HTTPS with host only, no path for `merchantUrl`).

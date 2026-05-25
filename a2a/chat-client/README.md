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

## Run Locally

**Prerequisites:** Node.js

1. Install dependencies:
   `npm install`
2. Run the app:
   `npm run dev`

## Google Pay Web API

The checkout uses the real Google Pay Web SDK (`https://pay.google.com/gp/p/js/pay.js`).
On click, it calls `PaymentsClient.loadPaymentData(...)` and forwards the returned
tokenized payload into the existing UCP checkout `complete_checkout` action.

Optional environment variables:

- `VITE_GOOGLE_PAY_ENV=TEST|PRODUCTION` (default: `TEST`)
- `VITE_GOOGLE_PAY_MERCHANT_ID` (required in production)
- `VITE_GOOGLE_PAY_MERCHANT_NAME` (default: `UCP Demo Merchant`)
- `VITE_GOOGLE_PAY_GATEWAY` (default: `example`)
- `VITE_GOOGLE_PAY_GATEWAY_MERCHANT_ID` (default: `exampleGatewayMerchantId`)
- `VITE_GOOGLE_PAY_ALLOWED_AUTH_METHODS` (csv, default: `PAN_ONLY,CRYPTOGRAM_3DS`)
- `VITE_GOOGLE_PAY_ALLOWED_CARD_NETWORKS` (csv, default: `VISA,MASTERCARD`)

In production, use HTTPS and your real PSP gateway configuration.

## Protocol Dashboard

The UI includes a built-in protocol dashboard that logs:
- Outbound JSON-RPC `message/send` requests
- Inbound JSON-RPC responses
- A2A/UCP internal trace events (`a2a.protocol_trace`)
- Payment token fields carried in the exchange
- Visual call-flow timeline for each exchange, including ADK Runner usage (`Yes/No`)

Use the `Trace` toggle in the right panel to open/close it and `Clear` to reset logs.

For demo convenience, clicking `Start Payment` auto-sends a UCP `update_customer_details` action with sample fulfillment data and the current user email, so the checkout can move to `ready_for_complete` without manual JSON input.

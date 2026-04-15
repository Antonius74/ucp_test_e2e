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

## Protocol Dashboard

The UI includes a built-in protocol dashboard that logs:
- Outbound JSON-RPC `message/send` requests
- Inbound JSON-RPC responses
- A2A/UCP internal trace events (`a2a.protocol_trace`)
- Payment token fields carried in the exchange
- Visual call-flow timeline for each exchange, including ADK Runner usage (`Yes/No`)

Use the `Trace` toggle in the right panel to open/close it and `Clear` to reset logs.

For demo convenience, clicking `Start Payment` auto-sends a UCP `update_customer_details` action with sample fulfillment data and the current user email, so the checkout can move to `ready_for_complete` without manual JSON input.

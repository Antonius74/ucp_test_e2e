# Copyright 2026 UCP Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""UCP."""

from typing import Any
from uuid import uuid4
from a2a.types import Task, TaskState, TaskStatus
from a2a.utils import new_agent_text_message
from ucp_sdk.models.schemas.shopping.types.payment_instrument import (
    PaymentInstrument,
)
from .a2a_subagents import MERCHANT_PAYMENT_RESULT_KEY, MerchantAgentA2A


class MockPaymentProcessor:
    """Mock Payment Processor simulating Merchant Agent to MPP Agent calls."""

    def __init__(self, merchant_agent: MerchantAgentA2A | None = None):
        self._merchant_agent = merchant_agent or MerchantAgentA2A()
        self.last_exchange: dict[str, Any] | None = None

    def _build_merchant_request(
        self, payment_data: PaymentInstrument, risk_data: Any | None
    ) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": str(uuid4()),
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "kind": "message",
                    "messageId": str(uuid4()),
                    "contextId": str(uuid4()),
                    "parts": [
                        {
                            "type": "data",
                            "data": {
                                "action": "process_payment_token",
                                "payment_data": payment_data.model_dump(mode="json"),
                                "risk_signals": risk_data,
                            },
                        }
                    ],
                }
            },
        }

    def _extract_merchant_result(self, response: dict[str, Any]) -> dict[str, Any]:
        result = response.get("result")
        if not isinstance(result, dict):
            return {}

        parts = result.get("parts")
        if not isinstance(parts, list):
            return {}

        for part in parts:
            if not isinstance(part, dict):
                continue
            if part.get("type") != "data":
                continue
            data = part.get("data")
            if not isinstance(data, dict):
                continue
            merchant_result = data.get(MERCHANT_PAYMENT_RESULT_KEY)
            if isinstance(merchant_result, dict):
                return merchant_result
        return {}

    def process_payment(
        self, payment_data: PaymentInstrument, risk_data: Any | None = None
    ) -> Task:
        """Process the payment.

        Args:
            payment_data: The payment instrument to process.
            risk_data: Optional risk data for validation.

        Returns:
            Task: A task representing the completed payment process.

        """
        merchant_request = self._build_merchant_request(payment_data, risk_data)
        merchant_response = self._merchant_agent.handle_jsonrpc(merchant_request)
        merchant_result = self._extract_merchant_result(merchant_response)
        self.last_exchange = {
            "merchant_request": merchant_request,
            "merchant_response": merchant_response,
            "merchant_result": merchant_result,
        }

        status_value = merchant_result.get("status")
        message = str(merchant_result.get("message", "Payment failed."))
        is_approved = status_value == "approved"

        return Task(
            context_id=str(uuid4()),
            id=str(uuid4()),
            status=TaskStatus(
                state=TaskState.completed if is_approved else TaskState.failed,
                message=new_agent_text_message(message),
            ),
        )

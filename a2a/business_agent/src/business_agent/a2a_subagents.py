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

"""In-process A2A sub-agents for shopping and merchant flows."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ucp_sdk.models.schemas.shopping.types.buyer import Buyer
from ucp_sdk.models.schemas.shopping.types.payment_instrument import (
    PaymentInstrument,
)
from ucp_sdk.models.schemas.shopping.types.postal_address import PostalAddress
from ucp_sdk.models.schemas.ucp import ResponseCheckout as UcpMetadata

from .constants import (
    UCP_CHECKOUT_KEY,
    UCP_PURCHASE_RESERVATION_KEY,
    UCP_PURCHASE_RESERVATIONS_KEY,
)
from .store import RetailStore

MERCHANT_PAYMENT_RESULT_KEY = "a2a.merchant.payment_result"
A2A_ORDERS_KEY = "a2a.orders"


def _new_text_part(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _new_data_part(data: dict[str, Any]) -> dict[str, Any]:
    return {"type": "data", "data": data}


def _new_message_result(parts: list[dict[str, Any]], context_id: str) -> dict[str, Any]:
    return {
        "kind": "message",
        "messageId": str(uuid4()),
        "role": "agent",
        "contextId": context_id,
        "parts": parts,
    }


def _new_jsonrpc_response(
    request_id: str | int | None, result: dict[str, Any]
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id if request_id is not None else str(uuid4()),
        "result": result,
    }


def _parse_text_action_payload(text: str) -> tuple[str, dict[str, Any]] | None:
    cleaned = text.strip()
    if not cleaned.startswith("{"):
        return None
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    action = payload.get("action")
    if not isinstance(action, str) or not action.strip():
        return None
    params = {key: value for key, value in payload.items() if key != "action"}
    return action.strip(), params


def _extract_message_and_parts(
    payload: dict[str, Any]
) -> tuple[str, str, list[dict[str, Any]], dict[str, Any]]:
    params = payload.get("params")
    if not isinstance(params, dict):
        params = {}

    message = params.get("message")
    if not isinstance(message, dict):
        message = {}

    context_id = str(message.get("contextId") or uuid4())
    request_id = str(payload.get("id") or uuid4())
    parts_raw = message.get("parts")
    parts: list[dict[str, Any]] = []
    if isinstance(parts_raw, list):
        for part in parts_raw:
            if isinstance(part, dict):
                parts.append(part)

    metadata = params.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    return request_id, context_id, parts, metadata


def _extract_action_and_query(
    parts: list[dict[str, Any]],
) -> tuple[tuple[str, dict[str, Any]] | None, str]:
    query_lines: list[str] = []
    action: tuple[str, dict[str, Any]] | None = None

    for part in parts:
        part_type = part.get("type")
        if part_type == "data":
            data = part.get("data")
            if isinstance(data, dict):
                action_name = data.get("action")
                if isinstance(action_name, str) and action_name.strip():
                    action_params = {
                        key: value for key, value in data.items() if key != "action"
                    }
                    action = (action_name.strip(), action_params)
        elif part_type == "text":
            text = part.get("text")
            if isinstance(text, str):
                query_lines.append(text)
                parsed_text_action = _parse_text_action_payload(text)
                if parsed_text_action:
                    action = parsed_text_action

    return action, "\n".join(query_lines).strip()


class ShopAgentA2A:
    """A2A Shop Agent handling catalog and checkout operations."""

    def __init__(self, store: RetailStore):
        self.store = store
        self._checkout_ids_by_context: dict[str, str] = {}
        self._order_ids_by_context: dict[str, list[str]] = {}

    def handle_jsonrpc(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_id, context_id, parts, metadata = _extract_message_and_parts(payload)
        action, query = _extract_action_and_query(parts)

        if action:
            result = self._handle_action(context_id, action, metadata)
        else:
            result = self._handle_search(query)

        message_parts: list[dict[str, Any]] = []
        message = result.get("message")
        if isinstance(message, str) and message.strip():
            message_parts.append(_new_text_part(message))

        data_payload = {
            key: value
            for key, value in result.items()
            if key
            in {
                UCP_CHECKOUT_KEY,
                "a2a.product_results",
                A2A_ORDERS_KEY,
                UCP_PURCHASE_RESERVATION_KEY,
                UCP_PURCHASE_RESERVATIONS_KEY,
                "status",
            }
        }
        if data_payload:
            message_parts.append(_new_data_part(data_payload))

        if not message_parts:
            message_parts.append(_new_text_part("Shop agent completed the request."))

        return _new_jsonrpc_response(
            request_id,
            _new_message_result(message_parts, context_id),
        )

    def get_checkout_id_for_context(self, context_id: str) -> str | None:
        """Return the active checkout ID for an A2A context."""
        return self._checkout_ids_by_context.get(context_id)

    def _get_orders_for_context(self, context_id: str) -> list[Any]:
        order_ids = self._order_ids_by_context.get(context_id, [])
        orders: list[Any] = []
        for order_id in reversed(order_ids):
            order = self.store.get_order(order_id)
            if order is not None:
                orders.append(order)
        return orders

    def _serialize_orders(self, orders: list[Any]) -> list[dict[str, Any]]:
        return [order.model_dump(mode="json") for order in orders]

    def _remember_order_for_context(self, context_id: str, order_id: str) -> None:
        order_ids = self._order_ids_by_context.setdefault(context_id, [])
        if order_id not in order_ids:
            order_ids.append(order_id)

    def _resolve_ucp_metadata(self, metadata: dict[str, Any]) -> UcpMetadata | None:
        ucp_metadata = metadata.get("ucp_metadata")
        if isinstance(ucp_metadata, UcpMetadata):
            return ucp_metadata
        if isinstance(ucp_metadata, dict):
            return UcpMetadata.model_validate(ucp_metadata)
        return None

    def _handle_search(self, query: str) -> dict[str, Any]:
        results = self.store.search_products(query)
        return {
            "message": f"I found {len(results.results)} products for you.",
            "a2a.product_results": results.model_dump(mode="json"),
            "status": "success",
        }

    def _handle_action(
        self,
        context_id: str,
        action_payload: tuple[str, dict[str, Any]],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        action, params = action_payload
        checkout_id = self.get_checkout_id_for_context(context_id)

        if action == "add_to_checkout":
            metadata_value = self._resolve_ucp_metadata(metadata)
            if metadata_value is None:
                return {
                    "message": "Missing UCP metadata for checkout creation.",
                    "status": "error",
                }

            product_id = str(params.get("product_id", "")).strip()
            quantity = int(params.get("quantity", 1))
            checkout = self.store.add_to_checkout(
                metadata_value, product_id, quantity, checkout_id
            )
            self._checkout_ids_by_context[context_id] = checkout.id
            return {
                UCP_CHECKOUT_KEY: checkout.model_dump(mode="json"),
                "status": "success",
            }

        if action == "get_order":
            order_id = str(params.get("order_id", "")).strip()
            if not order_id:
                return {"message": "Order ID is required.", "status": "error"}

            order = self.store.get_order(order_id)
            if order is None:
                return {
                    "message": f"Order '{order_id}' not found.",
                    "status": "not_found",
                }

            self._remember_order_for_context(context_id, order_id)
            return {
                "message": f"Here are the details for order {order_id}.",
                UCP_CHECKOUT_KEY: order.model_dump(mode="json"),
                "status": "success",
            }

        if action == "get_latest_order":
            context_orders = self._get_orders_for_context(context_id)
            order = context_orders[0] if context_orders else self.store.get_latest_order()
            if order is None:
                return {
                    "message": (
                        "I could not find completed orders yet. "
                        "Complete a checkout first, then ask for your orders."
                    ),
                    "status": "not_found",
                }

            order_id = order.order.id if order.order and order.order.id else "latest"
            if order.order and order.order.id:
                self._remember_order_for_context(context_id, order.order.id)
            return {
                "message": f"Here is your latest completed order ({order_id}).",
                UCP_CHECKOUT_KEY: order.model_dump(mode="json"),
                "status": "success",
            }

        if action == "list_orders":
            buyer_email = (
                str(params.get("buyer_email")).strip()
                if params.get("buyer_email") is not None
                else None
            )
            try:
                limit = int(params.get("limit", 10))
            except (TypeError, ValueError):
                limit = 10
            limit = max(1, min(limit, 50))

            context_orders = self._get_orders_for_context(context_id)
            if context_orders:
                orders = context_orders[:limit]
            else:
                orders = self.store.list_orders(buyer_email=buyer_email, limit=limit)

            if not orders:
                return {
                    "message": "I could not find completed orders for this session yet.",
                    "status": "not_found",
                    A2A_ORDERS_KEY: [],
                }

            order_ids = [
                order.order.id
                for order in orders
                if order.order is not None and order.order.id
            ]
            summary = ", ".join(order_ids[:3])
            if len(order_ids) > 3:
                summary = f"{summary}, +{len(order_ids) - 3} more"
            return {
                "message": f"I found {len(orders)} completed order(s): {summary}.",
                A2A_ORDERS_KEY: self._serialize_orders(orders),
                "status": "success",
            }

        if action == "reserve_on_price_drop":
            product_id = str(params.get("product_id", "")).strip()
            if not product_id:
                return {"message": "Product ID is required.", "status": "error"}

            try:
                reservation = self.store.create_purchase_reservation(
                    product_id=product_id,
                    condition_type="price_drop",
                    buyer_email=(
                        str(params.get("buyer_email")).strip()
                        if params.get("buyer_email") is not None
                        else None
                    ),
                    target_price=params.get("target_price"),
                )
            except ValueError as exc:
                return {"message": str(exc), "status": "error"}
            return {
                "message": (
                    f"Price-drop reservation created for {reservation.product_name}. "
                    f"Status: {reservation.status}."
                ),
                UCP_PURCHASE_RESERVATION_KEY: reservation.model_dump(mode="json"),
                "status": "success",
            }

        if action == "reserve_on_restock":
            product_id = str(params.get("product_id", "")).strip()
            if not product_id:
                return {"message": "Product ID is required.", "status": "error"}

            try:
                reservation = self.store.create_purchase_reservation(
                    product_id=product_id,
                    condition_type="back_in_stock",
                    buyer_email=(
                        str(params.get("buyer_email")).strip()
                        if params.get("buyer_email") is not None
                        else None
                    ),
                )
            except ValueError as exc:
                return {"message": str(exc), "status": "error"}
            return {
                "message": (
                    f"Back-in-stock reservation created for {reservation.product_name}. "
                    f"Status: {reservation.status}."
                ),
                UCP_PURCHASE_RESERVATION_KEY: reservation.model_dump(mode="json"),
                "status": "success",
            }

        if action == "list_purchase_reservations":
            buyer_email = (
                str(params.get("buyer_email")).strip()
                if params.get("buyer_email") is not None
                else None
            )
            status = (
                str(params.get("status")).strip().lower()
                if params.get("status") is not None
                else None
            )
            if status not in {None, "active", "triggered"}:
                return {
                    "message": "status must be either 'active' or 'triggered'.",
                    "status": "error",
                }
            try:
                limit = int(params.get("limit", 20))
            except (TypeError, ValueError):
                limit = 20
            limit = max(1, min(limit, 100))

            reservations = self.store.list_purchase_reservations(
                buyer_email=buyer_email,
                status=status,  # type: ignore[arg-type]
                limit=limit,
            )
            return {
                "message": f"I found {len(reservations)} reservation(s).",
                UCP_PURCHASE_RESERVATIONS_KEY: [
                    reservation.model_dump(mode="json")
                    for reservation in reservations
                ],
                "status": "success",
            }

        if not checkout_id:
            return {"message": "A checkout has not been created yet.", "status": "error"}

        if action == "remove_from_checkout":
            product_id = str(params.get("product_id", "")).strip()
            checkout = self.store.remove_from_checkout(checkout_id, product_id)
            return {
                UCP_CHECKOUT_KEY: checkout.model_dump(mode="json"),
                "status": "success",
            }

        if action == "update_checkout":
            product_id = str(params.get("product_id", "")).strip()
            quantity = int(params.get("quantity", 1))
            checkout = self.store.update_checkout(checkout_id, product_id, quantity)
            return {
                UCP_CHECKOUT_KEY: checkout.model_dump(mode="json"),
                "status": "success",
            }

        if action == "get_checkout":
            checkout = self.store.get_checkout(checkout_id)
            if checkout is None:
                return {"message": "Checkout not found.", "status": "error"}
            return {
                UCP_CHECKOUT_KEY: checkout.model_dump(mode="json"),
                "status": "success",
            }

        if action == "start_payment":
            checkout_or_message = self.store.start_payment(checkout_id)
            if isinstance(checkout_or_message, str):
                return {"message": checkout_or_message, "status": "requires_more_info"}
            return {
                UCP_CHECKOUT_KEY: checkout_or_message.model_dump(mode="json"),
                "status": "success",
            }

        if action == "update_customer_details":
            address_country = params.get("address_country") or "US"
            address = PostalAddress(
                street_address=str(params["street_address"]),
                extended_address=(
                    str(params["extended_address"])
                    if "extended_address" in params
                    and params.get("extended_address") is not None
                    else None
                ),
                address_locality=str(params["address_locality"]),
                address_region=str(params["address_region"]),
                address_country=str(address_country),
                postal_code=str(params["postal_code"]),
                first_name=str(params["first_name"]),
                last_name=str(params["last_name"]),
            )
            checkout = self.store.add_delivery_address(checkout_id, address)

            email = params.get("email")
            if email:
                checkout.buyer = Buyer(email=str(email))

            checkout_or_message = self.store.start_payment(checkout_id)
            if isinstance(checkout_or_message, str):
                return {"message": checkout_or_message, "status": "requires_more_info"}
            return {
                UCP_CHECKOUT_KEY: checkout_or_message.model_dump(mode="json"),
                "status": "success",
            }

        if action == "complete_checkout":
            checkout = self.store.get_checkout(checkout_id)
            if checkout is None:
                return {"message": "Checkout not found.", "status": "error"}
            if checkout.status != "ready_for_complete":
                return {
                    "message": (
                        "Checkout is not ready. Please provide buyer details "
                        "and start payment first."
                    ),
                    "status": "requires_more_info",
                }

            payment_instrument_data = params.get("payment_instrument")
            if isinstance(payment_instrument_data, PaymentInstrument):
                payment_instrument = payment_instrument_data
            elif isinstance(payment_instrument_data, dict):
                payment_instrument = PaymentInstrument.model_validate(
                    payment_instrument_data
                )
            else:
                payment_instrument = None

            if payment_instrument is not None:
                checkout.payment.selected_instrument_id = payment_instrument.root.id
                checkout.payment.instruments = [payment_instrument]

            completed_checkout = self.store.place_order(checkout_id)
            if completed_checkout.order and completed_checkout.order.id:
                self._remember_order_for_context(context_id, completed_checkout.order.id)
            self._checkout_ids_by_context.pop(context_id, None)
            return {
                UCP_CHECKOUT_KEY: completed_checkout.model_dump(mode="json"),
                "status": "success",
            }

        return {"message": f"Unsupported shop action: {action}", "status": "error"}


class MerchantAgentA2A:
    """A2A Merchant Agent that validates and authorizes token payments."""

    def __init__(self):
        self._gateway = MockUcpPaymentGateway()

    def handle_jsonrpc(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_id, context_id, parts, _ = _extract_message_and_parts(payload)
        action, _query = _extract_action_and_query(parts)
        if not action:
            return _new_jsonrpc_response(
                request_id,
                _new_message_result(
                    [_new_text_part("Merchant action is required.")],
                    context_id,
                ),
            )

        action_name, params = action
        if action_name != "process_payment_token":
            return _new_jsonrpc_response(
                request_id,
                _new_message_result(
                    [_new_text_part(f"Unsupported merchant action: {action_name}")],
                    context_id,
                ),
            )

        result = self._process_payment_token(params)
        parts_out = [_new_text_part(result["message"])]
        parts_out.append(
            _new_data_part({MERCHANT_PAYMENT_RESULT_KEY: result, "status": result["status"]})
        )
        return _new_jsonrpc_response(
            request_id,
            _new_message_result(parts_out, context_id),
        )

    def _process_payment_token(self, params: dict[str, Any]) -> dict[str, Any]:
        payment_data = params.get("payment_data")
        if isinstance(payment_data, PaymentInstrument):
            payment_data_dict = payment_data.model_dump(mode="json")
        elif isinstance(payment_data, dict):
            payment_data_dict = payment_data
        else:
            return {
                "status": "declined",
                "message": "Payment token data is missing.",
                "reason": "missing_payment_data",
            }

        credential = payment_data_dict.get("credential")
        if not isinstance(credential, dict):
            return {
                "status": "declined",
                "message": "Payment credential is missing.",
                "reason": "missing_credential",
            }

        token_type = credential.get("type")
        token_value = credential.get("token")
        if token_type != "token" or not isinstance(token_value, str) or not token_value:
            return {
                "status": "declined",
                "message": "Invalid payment token format.",
                "reason": "invalid_token_format",
            }

        handler_id = payment_data_dict.get("handler_id")
        if not isinstance(handler_id, str) or not handler_id:
            return {
                "status": "declined",
                "message": "Payment handler id is missing.",
                "reason": "missing_handler_id",
            }

        if handler_id != "example_payment_provider":
            return {
                "status": "declined",
                "message": "Unsupported payment handler for this merchant.",
                "reason": "unsupported_handler",
                "handler_id": handler_id,
            }

        risk_signals = params.get("risk_signals")
        gateway_result = self._gateway.authorize_token(
            payment_data_dict, risk_signals
        )

        if gateway_result["status"] != "approved":
            return {
                "status": "declined",
                "message": gateway_result["message"],
                "reason": gateway_result["reason"],
                "handler_id": handler_id,
                "gateway": gateway_result,
                "ucp_integration": {
                    "protocol": "UCP",
                    "merchant_agent": "mock.ucp.merchant.agent",
                    "payment_gateway": gateway_result["provider"],
                },
            }

        auth_code = f"AUTH-{token_value[-6:]}".upper()
        return {
            "status": "approved",
            "message": "Payment token authorized by UCP merchant + gateway simulation.",
            "authorization_code": auth_code,
            "handler_id": handler_id,
            "gateway": gateway_result,
            "merchant_reference": f"mref_{uuid4().hex[:10]}",
            "ucp_integration": {
                "protocol": "UCP",
                "merchant_agent": "mock.ucp.merchant.agent",
                "payment_gateway": gateway_result["provider"],
                "gateway_transaction_id": gateway_result["transaction_id"],
            },
        }


class MockUcpPaymentGateway:
    """Mock UCP-compatible payment gateway used by MerchantAgentA2A."""

    provider = "mock.ucp.gateway"

    def authorize_token(
        self,
        payment_data: dict[str, Any],
        risk_signals: Any | None,
    ) -> dict[str, Any]:
        credential = payment_data.get("credential")
        token_value = (
            credential.get("token")
            if isinstance(credential, dict)
            else None
        )
        if not isinstance(token_value, str) or not token_value:
            return {
                "status": "declined",
                "message": "Gateway rejected request: token is missing.",
                "reason": "missing_token",
                "provider": self.provider,
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }

        lowered = token_value.lower()
        if lowered.startswith("tok_declined") or "invalid" in lowered:
            return {
                "status": "declined",
                "message": "Gateway declined the token.",
                "reason": "token_declined",
                "provider": self.provider,
                "transaction_id": f"gw_{uuid4().hex[:12]}",
                "gateway_request_id": f"gwreq_{uuid4().hex[:12]}",
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "network": str(payment_data.get("brand", "unknown")).lower(),
                "risk_signals": risk_signals,
            }

        return {
            "status": "approved",
            "message": "Gateway authorization approved.",
            "provider": self.provider,
            "transaction_id": f"gw_{uuid4().hex[:12]}",
            "gateway_request_id": f"gwreq_{uuid4().hex[:12]}",
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "network": str(payment_data.get("brand", "unknown")).lower(),
            "risk_signals": risk_signals,
        }

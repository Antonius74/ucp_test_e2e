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

"""Real Nexi XPay Build v3 gateways behind the UCP Merchant Agent.

Each gateway realises a UCP payment handler declared in ``data/ucp.json``:

* ``nexi_card``      -> :class:`NexiCardGateway`      (hosted-fields build flow)
* ``nexi_googlepay`` -> :class:`NexiGooglePayGateway` (Google Pay orders flow)

They expose the same ``authorize_token(payment_data, risk_signals) -> dict``
contract as ``MockUcpPaymentGateway`` and normalise the Nexi outcome to the
shared gateway result shape, including the ``requires_action`` status used by
the two-phase 3D Secure flow (Option C).

NOTE (Fase 6/7): the ``requires_action`` result and the resume call (#2) are
consumed by the executor/frontend wiring, which is implemented in a later
increment. These gateways already emit/accept them so that wiring is additive.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from . import nexi_xpay

PROVIDER = "nexi.xpay.build.v3"


def run_async(coro: Any) -> Any:
    """Run a coroutine to completion from sync code.

    Safe whether or not an event loop is already running: if one is (the ADK
    tool path and the deterministic fast-path both run inside a loop), the
    coroutine is executed on a dedicated worker thread with its own loop to
    avoid ``asyncio.run()`` raising inside a running loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro)).result()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _approved(operation: dict[str, Any], risk_signals: Any | None) -> dict[str, Any]:
    transaction_id = (
        str(operation.get("operationId"))
        if operation.get("operationId")
        else f"nexi_{uuid4().hex[:12]}"
    )
    return {
        "status": "approved",
        "message": "Payment authorized by Nexi XPay Build v3.",
        "provider": PROVIDER,
        "transaction_id": transaction_id,
        "gateway_request_id": str(operation.get("orderId") or uuid4().hex[:12]),
        "processed_at": _now(),
        "operation": operation,
        "risk_signals": risk_signals,
    }


def _declined(reason: str, message: str, *, extra: dict[str, Any] | None = None,
              risk_signals: Any | None = None) -> dict[str, Any]:
    result = {
        "status": "declined",
        "message": message,
        "reason": reason,
        "provider": PROVIDER,
        "processed_at": _now(),
        "risk_signals": risk_signals,
    }
    if extra:
        result.update(extra)
    return result


def _requires_action(redirect_url: str | None, risk_signals: Any | None,
                     *, session_id: str | None = None,
                     order_id: str | None = None) -> dict[str, Any]:
    return {
        "status": "requires_action",
        "message": "3D Secure authentication required.",
        "reason": "auth_required",
        "provider": PROVIDER,
        "processed_at": _now(),
        "redirect_url": redirect_url,
        "session_id": session_id,
        "order_id": order_id,
        "risk_signals": risk_signals,
    }


def _operation_result_to_status(operation: dict[str, Any], risk_signals: Any | None) -> dict[str, Any]:
    """Map a Nexi 'operation' to approved/declined via operationResult."""
    result = str(operation.get("operationResult") or "").upper()
    if result in {"THREEDS_VALIDATED", "AUTHORIZED", "EXECUTED", "PENDING"}:
        return _approved(operation, risk_signals)
    if result in {"THREEDS_FAILED", "DECLINED", "DENIED_BY_RISK", "CANCELED", "FAILED"}:
        return _declined("nexi_declined", f"Nexi declined: {result}",
                         extra={"operation": operation}, risk_signals=risk_signals)
    # Unknown -> conservatively declined so no order is placed on ambiguity.
    return _declined("nexi_unexpected_result",
                     f"Unexpected Nexi operationResult: {result or 'none'}",
                     extra={"operation": operation}, risk_signals=risk_signals)


class NexiCardGateway:
    """Authorize a hosted-fields card payment via Nexi build finalize/state."""

    provider = PROVIDER
    accepted_credential_types = frozenset({"nexi_build_operation"})

    def authorize_token(self, payment_data: dict[str, Any],
                        risk_signals: Any | None) -> dict[str, Any]:
        credential = payment_data.get("credential") or {}
        # Fase 7: the frontend carries the Nexi build sessionId in the credential.
        session_id = credential.get("session_id") or credential.get("token")
        if not isinstance(session_id, str) or not session_id:
            return _declined("missing_session", "Nexi build session id is missing.",
                             risk_signals=risk_signals)

        resume = bool(credential.get("resume"))
        try:
            if resume:
                state = run_async(nexi_xpay.get_build_state(session_id=session_id))
            else:
                state = run_async(nexi_xpay.finalize_build_payment(session_id=session_id))
        except nexi_xpay.NexiUpstreamError as exc:
            return _declined("nexi_upstream_error",
                             f"Nexi upstream error {exc.status_code}.",
                             extra={"details": exc.payload}, risk_signals=risk_signals)
        except nexi_xpay.NexiConfigurationError as exc:
            return _declined("nexi_config_error", str(exc), risk_signals=risk_signals)

        return self._map_state(state, session_id, risk_signals)

    def _map_state(self, state: dict[str, Any], session_id: str,
                   risk_signals: Any | None) -> dict[str, Any]:
        s = str(state.get("state") or "").upper()
        if s == "PAYMENT_COMPLETE":
            return _approved(state.get("operation") or {}, risk_signals)
        if s == "REDIRECTED_TO_EXTERNAL_DOMAIN":
            return _requires_action(state.get("url"), risk_signals, session_id=session_id)
        return _declined("nexi_unexpected_state",
                         f"Unexpected Nexi build state: {s or 'none'}",
                         extra={"state": state}, risk_signals=risk_signals)


class NexiGooglePayGateway:
    """Authorize a Google Pay payment via Nexi /orders/googlepay + order status."""

    provider = PROVIDER
    accepted_credential_types = frozenset({"nexi_googlepay_operation"})

    def authorize_token(self, payment_data: dict[str, Any],
                        risk_signals: Any | None) -> dict[str, Any]:
        credential = payment_data.get("credential") or {}
        resume = bool(credential.get("resume"))

        try:
            if resume:
                # L'orderId Nexi e' deterministico dal checkout_id: lo si
                # ricava server-side, cosi' il client non deve conoscerlo.
                order_id = credential.get("order_id")
                if not (isinstance(order_id, str) and order_id):
                    ctx = credential.get("order_context") or {}
                    checkout_id = ctx.get("checkout_id")
                    if not checkout_id:
                        return _declined("missing_order_id",
                                         "Nexi order id/context missing for resume.",
                                         risk_signals=risk_signals)
                    order_id = nexi_xpay._sanitize_order_id(str(checkout_id))
                order = run_async(nexi_xpay.get_order(order_id=order_id))
                operation = order.get("operation") if isinstance(order, dict) else None
                return _operation_result_to_status(operation or {}, risk_signals)

            # First call: order context populated by the frontend (Fase 7).
            ctx = credential.get("order_context") or {}
            gp = credential.get("googlepay_payment_data")
            missing = [k for k in ("checkout_id", "amount_cents", "currency", "buyer_email")
                       if not ctx.get(k)]
            if missing or not gp:
                return _declined("missing_order_context",
                                 f"Google Pay order context incomplete: {missing or 'googlepay_payment_data'}.",
                                 risk_signals=risk_signals)

            result = run_async(nexi_xpay.process_googlepay_order(
                checkout_id=str(ctx["checkout_id"]),
                amount_cents=int(ctx["amount_cents"]),
                currency=str(ctx["currency"]),
                buyer_email=str(ctx["buyer_email"]),
                googlepay_payment_data=gp,
                description=ctx.get("description"),
            ))
        except nexi_xpay.NexiUpstreamError as exc:
            return _declined("nexi_upstream_error",
                             f"Nexi upstream error {exc.status_code}.",
                             extra={"details": exc.payload}, risk_signals=risk_signals)
        except nexi_xpay.NexiConfigurationError as exc:
            return _declined("nexi_config_error", str(exc), risk_signals=risk_signals)

        return self._map_googlepay_result(result, risk_signals)

    def _map_googlepay_result(self, result: dict[str, Any],
                              risk_signals: Any | None) -> dict[str, Any]:
        s = str(result.get("state") or "").upper()
        if s == "REDIRECTED_TO_EXTERNAL_DOMAIN":
            order_id = None
            operation = result.get("operation")
            if isinstance(operation, dict):
                order_id = operation.get("orderId")
            return _requires_action(result.get("url") or result.get("redirectUrl"),
                                    risk_signals, order_id=order_id)
        operation = result.get("operation")
        if isinstance(operation, dict) and operation:
            return _operation_result_to_status(operation, risk_signals)
        return _declined("nexi_unexpected_state",
                         f"Unexpected Nexi Google Pay state: {s or 'none'}",
                         extra={"result": result}, risk_signals=risk_signals)

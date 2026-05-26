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

"""Nexi XPay Build v3 integration helpers."""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx


class NexiConfigurationError(Exception):
    """Raised when Nexi integration environment is missing/invalid."""


class NexiUpstreamError(Exception):
    """Raised when Nexi upstream API responds with an error."""

    def __init__(self, status_code: int, payload: object):
        self.status_code = status_code
        self.payload = payload
        super().__init__(f"Nexi upstream error {status_code}")


@dataclass(slots=True)
class NexiConfig:
    environment: str
    api_key: str
    api_base: str
    merchant_url: str
    result_url: str
    cancel_url: str
    notification_url: str | None
    language: str
    timeout_seconds: float
    explicit_capture: bool
    build_fallback_enabled: bool
    build_fallback_api_key: str | None
    googlepay_endpoint: str
    googlepay_api_key: str
    googlepay_merchant_id: str
    googlepay_terminal_id: str
    googlepay_gateway: str
    googlepay_enable_fallback: bool
    googlepay_capture_type: str


def _normalize_environment(value: str | None) -> str:
    normalized = (value or "TEST").strip().upper()
    if normalized not in {"TEST", "PROD"}:
        raise NexiConfigurationError(
            "NEXI_XPAY_ENV must be TEST or PROD."
        )
    return normalized


def _base_domain(environment: str) -> str:
    if environment == "PROD":
        return "https://xpay.nexigroup.com"
    return "https://xpaysandbox.nexigroup.com"


def _api_base(environment: str) -> str:
    return f"{_base_domain(environment)}/api/phoenix-0.0/psp/api/v1"


def _validate_merchant_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise NexiConfigurationError(
            "NEXI_XPAY_MERCHANT_URL must start with http:// or https://."
        )
    if not parsed.netloc:
        raise NexiConfigurationError(
            "NEXI_XPAY_MERCHANT_URL must include a valid host."
        )
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise NexiConfigurationError(
            "NEXI_XPAY_MERCHANT_URL must not include path/query/fragment."
        )
    return f"{parsed.scheme}://{parsed.netloc}"


def _sanitize_order_id(checkout_id: str) -> str:
    compact = re.sub(r"[^A-Za-z0-9]", "", checkout_id)
    if not compact:
        compact = uuid.uuid4().hex
    return f"ucp{compact}"[:18]


def _build_headers(api_key: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "correlation-id": str(uuid.uuid4()),
        "content-type": "application/json",
        "accept": "*/*",
        "accept-language": "en,it;q=0.9",
        "cache-control": "no-cache",
    }


def _nexi_error_code(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    errors = payload.get("errors")
    if not isinstance(errors, list) or not errors:
        return None
    first = errors[0]
    if not isinstance(first, dict):
        return None
    code = first.get("code")
    return str(code).strip() if code is not None else None


def _is_googlepay_auth_error(status_code: int, payload: object) -> bool:
    if status_code in {401, 403}:
        return True
    code = _nexi_error_code(payload)
    return code in {"401 UNAUTHORIZED", "PS0057"}


def _normalize_capture_type(explicit_capture: bool) -> str:
    return "EXPLICIT" if explicit_capture else "IMPLICIT"


def _url_with_order_id(base_url: str, order_id: str) -> str:
    if "{orderId}" in base_url:
        return base_url.replace("{orderId}", order_id)
    if "orderId=" in base_url:
        return base_url
    separator = "&" if "?" in base_url else "/"
    return f"{base_url}{separator}{order_id}" if separator == "/" else f"{base_url}{separator}orderId={order_id}"


def _derive_holder_name(email: str) -> str:
    local = (email.split("@")[0] if "@" in email else email).strip()
    local = re.sub(r"[^A-Za-z0-9._-]", " ", local)
    chunks = [chunk for chunk in re.split(r"[._\-\s]+", local) if chunk]
    if not chunks:
        return "UCP Buyer"
    if len(chunks) == 1:
        return chunks[0].capitalize()
    first = chunks[0].capitalize()
    last = chunks[1].capitalize()
    return f"{first} {last}"


def load_nexi_config() -> NexiConfig:
    environment = _normalize_environment(os.getenv("NEXI_XPAY_ENV"))
    api_key = (os.getenv("NEXI_XPAY_API_KEY") or "").strip()
    if not api_key:
        raise NexiConfigurationError("NEXI_XPAY_API_KEY is required.")

    merchant_url = _validate_merchant_url(
        (os.getenv("NEXI_XPAY_MERCHANT_URL") or "https://example.com").strip()
    )
    result_url = (
        os.getenv("NEXI_XPAY_RESULT_URL") or f"{merchant_url}/nexi/result"
    ).strip()
    cancel_url = (
        os.getenv("NEXI_XPAY_CANCEL_URL") or f"{merchant_url}/nexi/cancel"
    ).strip()
    notification_url = (os.getenv("NEXI_XPAY_NOTIFICATION_URL") or "").strip() or None
    language = (os.getenv("NEXI_XPAY_LANGUAGE") or "ita").strip().lower()

    timeout_raw = (os.getenv("NEXI_XPAY_TIMEOUT_SECONDS") or "30").strip()
    try:
        timeout_seconds = float(timeout_raw)
    except ValueError as exc:
        raise NexiConfigurationError(
            "NEXI_XPAY_TIMEOUT_SECONDS must be numeric."
        ) from exc

    explicit_capture_raw = (os.getenv("NEXI_XPAY_CAPTURE_TYPE") or "EXPLICIT").strip().upper()
    explicit_capture = explicit_capture_raw != "IMPLICIT"

    build_fallback_enabled_raw = (
        os.getenv("NEXI_XPAY_ENABLE_TEST_KEY_FALLBACK") or "true"
    ).strip().lower()
    build_fallback_enabled = build_fallback_enabled_raw in {"1", "true", "yes", "on"}

    build_fallback_api_key = (
        os.getenv("NEXI_XPAY_TEST_FALLBACK_API_KEY")
        or "ee6a41f2-fa09-4b8f-bc05-5dc225bdc270"
    ).strip()
    if not build_fallback_api_key:
        build_fallback_api_key = None

    googlepay_api_key = (
        os.getenv("NEXI_GOOGLEPAY_API_KEY")
        or api_key
    ).strip()
    googlepay_enable_fallback_raw = (
        os.getenv("NEXI_GOOGLEPAY_ENABLE_FALLBACK") or "false"
    ).strip().lower()
    googlepay_enable_fallback = googlepay_enable_fallback_raw in {
        "1",
        "true",
        "yes",
        "on",
    }

    googlepay_capture_type_raw = (
        os.getenv("NEXI_GOOGLEPAY_CAPTURE_TYPE")
        or os.getenv("NEXI_XPAY_CAPTURE_TYPE")
        or "EXPLICIT"
    ).strip().upper()
    googlepay_capture_type = (
        "IMPLICIT" if googlepay_capture_type_raw == "IMPLICIT" else "EXPLICIT"
    )

    return NexiConfig(
        environment=environment,
        api_key=api_key,
        api_base=(
            os.getenv("NEXI_XPAY_API_BASE") or _api_base(environment)
        ).strip(),
        merchant_url=merchant_url,
        result_url=result_url,
        cancel_url=cancel_url,
        notification_url=notification_url,
        language=language,
        timeout_seconds=timeout_seconds,
        explicit_capture=explicit_capture,
        build_fallback_enabled=build_fallback_enabled,
        build_fallback_api_key=build_fallback_api_key,
        googlepay_endpoint=(
            os.getenv("NEXI_GOOGLEPAY_ENDPOINT")
            or f"{_api_base(environment)}/orders/googlepay"
        ).strip(),
        googlepay_api_key=googlepay_api_key,
        googlepay_merchant_id=(
            os.getenv("NEXI_GOOGLEPAY_MERCHANT_ID") or "999999990"
        ).strip(),
        googlepay_terminal_id=(
            os.getenv("NEXI_GOOGLEPAY_TERMINAL_ID") or "0000999"
        ).strip(),
        googlepay_gateway=(os.getenv("NEXI_GOOGLEPAY_GATEWAY") or "nexigtw").strip(),
        googlepay_enable_fallback=googlepay_enable_fallback,
        googlepay_capture_type=googlepay_capture_type,
    )


async def create_build_session(
    *,
    checkout_id: str,
    amount_cents: int,
    currency: str,
) -> dict[str, object]:
    config = load_nexi_config()
    endpoint = f"{config.api_base}/orders/build"
    order_id = _sanitize_order_id(checkout_id)
    result_url = _url_with_order_id(config.result_url, order_id)
    payload: dict[str, object] = {
        "version": "3",
        "merchantUrl": config.merchant_url,
        "order": {
            "orderId": order_id,
            "amount": str(amount_cents),
            "currency": currency.upper(),
        },
        "paymentSession": {
            "actionType": "PAY",
            "amount": str(amount_cents),
            "recurrence": {
                "action": "NO_RECURRING",
                "contractId": None,
                "contractType": None,
                "contractExpiryDate": None,
                "contractFrequency": None,
            },
            "captureType": _normalize_capture_type(config.explicit_capture),
            "exemptions": "NO_PREFERENCE",
            "language": config.language,
            "resultUrl": result_url,
            "cancelUrl": config.cancel_url,
        },
    }
    if config.notification_url:
        payment_session = payload["paymentSession"]
        if isinstance(payment_session, dict):
            payment_session["notificationUrl"] = config.notification_url

    async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
        response = await client.post(
            endpoint,
            headers=_build_headers(config.api_key),
            json=payload,
        )

    try:
        data = response.json()
    except ValueError:
        data = {"raw_response": response.text}

    if response.status_code >= 400:
        error_code = _nexi_error_code(data)
        is_retryable_gateway_error = error_code in {"GW0035", "PS0057", "401 UNAUTHORIZED"}
        if (
            config.environment == "TEST"
            and config.build_fallback_enabled
            and config.build_fallback_api_key
            and is_retryable_gateway_error
        ):
            fallback_endpoint = f"{_api_base('TEST')}/orders/build"
            async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
                fallback_response = await client.post(
                    fallback_endpoint,
                    headers=_build_headers(config.build_fallback_api_key),
                    json=payload,
                )
            try:
                fallback_data = fallback_response.json()
            except ValueError:
                fallback_data = {"raw_response": fallback_response.text}

            if fallback_response.status_code < 400 and isinstance(fallback_data, dict):
                warnings = fallback_data.get("warnings")
                warnings_list = warnings if isinstance(warnings, list) else []
                warnings_list.append(
                    {
                        "code": "UCP_FALLBACK_TEST_KEY",
                        "description": "Primary Nexi key failed in TEST; demo retried with official Nexi TEST key.",
                    }
                )
                fallback_data["warnings"] = warnings_list
                fallback_data["environment"] = "TEST"
                fallback_data["nexiDomain"] = _base_domain("TEST")
                fallback_data["hfsdkUrl"] = f"{_base_domain('TEST')}/monetaweb/resources/hfsdk.js"
                fallback_data["apiBaseUsed"] = _api_base("TEST")
                fallback_data["upstreamCid"] = fallback_response.headers.get("cid")
                return fallback_data

            if isinstance(fallback_data, dict):
                fallback_data["upstreamCid"] = fallback_response.headers.get("cid")
                data = {
                    "primaryAttempt": data,
                    "fallbackAttempt": fallback_data,
                }

    if response.status_code >= 400:
        if isinstance(data, dict):
            data["upstreamCid"] = response.headers.get("cid")
        raise NexiUpstreamError(response.status_code, data)

    if not isinstance(data, dict):
        raise NexiUpstreamError(
            502,
            {"error": "Unexpected Nexi response shape."},
        )

    data["environment"] = config.environment
    data["nexiDomain"] = _base_domain(config.environment)
    data["hfsdkUrl"] = f"{_base_domain(config.environment)}/monetaweb/resources/hfsdk.js"
    data["apiBaseUsed"] = config.api_base
    data["upstreamCid"] = response.headers.get("cid")
    return data


async def finalize_build_payment(*, session_id: str) -> dict[str, object]:
    config = load_nexi_config()
    endpoint = f"{config.api_base}/build/finalize_payment"
    payload = {"sessionId": session_id}

    async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
        response = await client.post(
            endpoint,
            headers=_build_headers(config.api_key),
            json=payload,
        )

    try:
        data = response.json()
    except ValueError:
        data = {"raw_response": response.text}

    if response.status_code >= 400:
        if isinstance(data, dict):
            data["upstreamCid"] = response.headers.get("cid")
        raise NexiUpstreamError(response.status_code, data)

    if not isinstance(data, dict):
        raise NexiUpstreamError(
            502,
            {"error": "Unexpected Nexi response shape."},
        )

    return data


async def get_build_state(*, session_id: str) -> dict[str, object]:
    config = load_nexi_config()
    endpoint = f"{config.api_base}/build/state"

    async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
        response = await client.get(
            endpoint,
            headers=_build_headers(config.api_key),
            params={"sessionId": session_id},
        )

    try:
        data = response.json()
    except ValueError:
        data = {"raw_response": response.text}

    if response.status_code >= 400:
        if isinstance(data, dict):
            data["upstreamCid"] = response.headers.get("cid")
        raise NexiUpstreamError(response.status_code, data)

    if not isinstance(data, dict):
        raise NexiUpstreamError(
            502,
            {"error": "Unexpected Nexi response shape."},
        )

    data["upstreamCid"] = response.headers.get("cid")
    return data


async def process_googlepay_order(
    *,
    checkout_id: str,
    amount_cents: int,
    currency: str,
    buyer_email: str,
    googlepay_payment_data: dict[str, object],
    description: str | None = None,
) -> dict[str, object]:
    config = load_nexi_config()
    endpoint = config.googlepay_endpoint
    email = buyer_email.strip() or "buyer@example.com"
    holder_name = _derive_holder_name(email)
    safe_description = (description or "UCP Demo purchase").strip() or "UCP Demo purchase"

    payload: dict[str, object] = {
        "order": {
            "orderId": _sanitize_order_id(checkout_id),
            "amount": str(amount_cents),
            "currency": currency.upper(),
            "customerId": config.googlepay_terminal_id,
            "description": safe_description,
            "customField": f"terminal:{config.googlepay_terminal_id}",
            "customerInfo": {
                "cardHolderName": holder_name,
                "cardHolderEmail": email,
            },
        },
        "paymentSession": {
            "actionType": "PAY",
            "amount": str(amount_cents),
            "recurrence": {
                "action": "NO_RECURRING",
                "contractId": None,
                "contractType": None,
                "contractExpiryDate": None,
                "contractFrequency": None,
            },
            "captureType": config.googlepay_capture_type,
            "exemptions": "NO_PREFERENCE",
            "language": config.language,
            "resultUrl": config.result_url,
            "cancelUrl": config.cancel_url,
        },
        "googlePayPaymentData": googlepay_payment_data,
    }
    if config.notification_url:
        payment_session = payload["paymentSession"]
        if isinstance(payment_session, dict):
            payment_session["notificationUrl"] = config.notification_url

    async def _post_googlepay(
        *,
        request_endpoint: str,
        request_api_key: str,
    ) -> tuple[int, dict[str, object]]:
        async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
            response = await client.post(
                request_endpoint,
                headers=_build_headers(request_api_key),
                json=payload,
            )

        try:
            response_data = response.json()
        except ValueError:
            response_data = {"raw_response": response.text}

        if not isinstance(response_data, dict):
            response_data = {"raw_response": response.text}
        response_data["upstreamCid"] = response.headers.get("cid")
        response_data["endpointUsed"] = request_endpoint
        return response.status_code, response_data

    status_code, data = await _post_googlepay(
        request_endpoint=endpoint,
        request_api_key=config.googlepay_api_key,
    )

    if (
        status_code >= 400
        and config.googlepay_enable_fallback
        and _is_googlepay_auth_error(status_code, data)
    ):
        fallback_endpoint = f"{config.api_base}/orders/googlepay"
        fallback_key = config.api_key
        should_retry_fallback = not (
            fallback_endpoint == endpoint and fallback_key == config.googlepay_api_key
        )

        if should_retry_fallback:
            fallback_status_code, fallback_data = await _post_googlepay(
                request_endpoint=fallback_endpoint,
                request_api_key=fallback_key,
            )
            if fallback_status_code < 400:
                warnings = fallback_data.get("warnings")
                warning_list = warnings if isinstance(warnings, list) else []
                warning_list.append(
                    {
                        "code": "UCP_GOOGLEPAY_FALLBACK_ENDPOINT",
                        "description": (
                            "Primary Google Pay endpoint/key unauthorized. "
                            "Processed using XPay API base fallback endpoint."
                        ),
                    }
                )
                fallback_data["warnings"] = warning_list
                data = fallback_data
                status_code = fallback_status_code
            else:
                raise NexiUpstreamError(
                    fallback_status_code,
                    {
                        "primaryAttempt": data,
                        "fallbackAttempt": fallback_data,
                    },
                )

    if status_code >= 400:
        raise NexiUpstreamError(status_code, data)

    if not isinstance(data, dict):
        raise NexiUpstreamError(
            502,
            {"error": "Unexpected Nexi response shape."},
        )

    data["gateway"] = config.googlepay_gateway
    data["merchantId"] = config.googlepay_merchant_id
    data["terminalId"] = config.googlepay_terminal_id
    return data

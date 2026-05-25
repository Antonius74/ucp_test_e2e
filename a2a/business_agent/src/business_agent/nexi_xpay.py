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
    merchant_url: str
    result_url: str
    cancel_url: str
    notification_url: str | None
    language: str
    timeout_seconds: float


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
        "X-Api-Key": api_key,
        "Correlation-Id": str(uuid.uuid4()),
        "Content-Type": "application/json",
    }


def load_nexi_config() -> NexiConfig:
    environment = _normalize_environment(os.getenv("NEXI_XPAY_ENV"))
    api_key = (os.getenv("NEXI_XPAY_API_KEY") or "").strip()
    if not api_key:
        raise NexiConfigurationError("NEXI_XPAY_API_KEY is required.")

    merchant_url = _validate_merchant_url(
        (os.getenv("NEXI_XPAY_MERCHANT_URL") or "https://merchant.ucp.demo").strip()
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

    return NexiConfig(
        environment=environment,
        api_key=api_key,
        merchant_url=merchant_url,
        result_url=result_url,
        cancel_url=cancel_url,
        notification_url=notification_url,
        language=language,
        timeout_seconds=timeout_seconds,
    )


async def create_build_session(
    *,
    checkout_id: str,
    amount_cents: int,
    currency: str,
) -> dict[str, object]:
    config = load_nexi_config()
    endpoint = f"{_api_base(config.environment)}/orders/build"
    payload: dict[str, object] = {
        "version": "3",
        "merchantUrl": config.merchant_url,
        "order": {
            "orderId": _sanitize_order_id(checkout_id),
            "amount": str(amount_cents),
            "currency": currency.upper(),
        },
        "language": config.language,
        "resultUrl": config.result_url,
        "cancelUrl": config.cancel_url,
    }
    if config.notification_url:
        payload["notificationUrl"] = config.notification_url

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
        raise NexiUpstreamError(response.status_code, data)

    if not isinstance(data, dict):
        raise NexiUpstreamError(
            502,
            {"error": "Unexpected Nexi response shape."},
        )

    data["environment"] = config.environment
    data["nexiDomain"] = _base_domain(config.environment)
    data["hfsdkUrl"] = f"{_base_domain(config.environment)}/monetaweb/resources/hfsdk.js"
    return data


async def finalize_build_payment(*, session_id: str) -> dict[str, object]:
    config = load_nexi_config()
    endpoint = f"{_api_base(config.environment)}/build/finalize_payment"
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
        raise NexiUpstreamError(response.status_code, data)

    if not isinstance(data, dict):
        raise NexiUpstreamError(
            502,
            {"error": "Unexpected Nexi response shape."},
        )

    return data

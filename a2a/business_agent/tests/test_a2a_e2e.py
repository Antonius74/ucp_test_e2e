"""End-to-end tests for A2A + UCP flow with Ollama."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
import unittest
from pathlib import Path
from typing import Any

import httpx


A2A_UCP_EXTENSION_URL = "https://ucp.dev/specification/reference?v=2026-01-11"
OLLAMA_HEALTH_URL = "http://127.0.0.1:11434/api/tags"
PROFILE_PORT = int(os.environ.get("A2A_PROFILE_TEST_PORT", "13000"))
BACKEND_PORT = int(os.environ.get("A2A_BACKEND_TEST_PORT", "10999"))
BACKEND_BASE_URL = f"http://127.0.0.1:{BACKEND_PORT}"
CLIENT_PROFILE_URL = (
    f"http://127.0.0.1:{PROFILE_PORT}/profile/agent_profile.json"
)
DEFAULT_MODEL = os.environ.get("BUSINESS_AGENT_MODEL", "ollama/gpt-oss:120b-cloud")

MOCK_PAYMENT_INSTRUMENT = {
    "id": "instr_2",
    "type": "card",
    "brand": "visa",
    "last_digits": "8888",
    "expiry_month": 12,
    "expiry_year": 2026,
    "handler_id": "example_payment_provider",
    "handler_name": "example.payment.provider",
    "credential": {"type": "token", "token": "mock_token_e2e"},
}


def _wait_for_url(url: str, timeout_s: int = 120) -> None:
    deadline = time.time() + timeout_s
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(url)
            if response.status_code < 500:
                return
        except Exception as exc:  # pragma: no cover - exercised in CI/runtime.
            last_error = exc
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for {url}. Last error: {last_error}")


def _safe_terminate(process: subprocess.Popen[str] | None) -> None:
    if process is None:
        return
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _extract_parts(result: dict[str, Any]) -> list[dict[str, Any]]:
    parts = result.get("parts")
    if isinstance(parts, list):
        return [p for p in parts if isinstance(p, dict)]

    status_message = result.get("status", {}).get("message")
    if isinstance(status_message, dict):
        nested_parts = status_message.get("parts")
        if isinstance(nested_parts, list):
            return [p for p in nested_parts if isinstance(p, dict)]
    return []


def _part_data(part: dict[str, Any]) -> dict[str, Any] | None:
    data = part.get("data")
    if isinstance(data, dict):
        return data

    root = part.get("root")
    if isinstance(root, dict):
        root_data = root.get("data")
        if isinstance(root_data, dict):
            return root_data
    return None


def _find_data(parts: list[dict[str, Any]], key: str) -> Any | None:
    for part in parts:
        data = _part_data(part)
        if isinstance(data, dict) and key in data:
            return data[key]
    return None


def _collect_text(parts: list[dict[str, Any]]) -> str:
    texts: list[str] = []
    for part in parts:
        text = part.get("text")
        if isinstance(text, str):
            texts.append(text)
            continue

        root = part.get("root")
        if isinstance(root, dict):
            root_text = root.get("text")
            if isinstance(root_text, str):
                texts.append(root_text)
    return "\n".join(texts)


class A2AOllamaE2ETest(unittest.TestCase):
    """Validates the documented A2A/UCP use cases with Ollama."""

    ollama_process: subprocess.Popen[str] | None = None
    profile_server_process: subprocess.Popen[str] | None = None
    backend_process: subprocess.Popen[str] | None = None

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        repo_root = root.parent
        chat_client_dir = repo_root / "chat-client"
        venv_python = root / ".venv" / "bin" / "python"

        # Start Ollama only if it is not already running.
        try:
            _wait_for_url(OLLAMA_HEALTH_URL, timeout_s=3)
        except RuntimeError:
            cls.ollama_process = subprocess.Popen(
                ["/usr/local/bin/ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            _wait_for_url(OLLAMA_HEALTH_URL, timeout_s=30)

        cls.profile_server_process = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(PROFILE_PORT), "--bind", "127.0.0.1"],
            cwd=str(chat_client_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        _wait_for_url(CLIENT_PROFILE_URL, timeout_s=20)

        env = os.environ.copy()
        env["BUSINESS_AGENT_MODEL"] = env.get("BUSINESS_AGENT_MODEL", DEFAULT_MODEL)
        env["OLLAMA_API_BASE"] = env.get("OLLAMA_API_BASE", "http://127.0.0.1:11434")
        env["ORDER_BASE_URL"] = env.get(
            "ORDER_BASE_URL", f"http://127.0.0.1:{BACKEND_PORT}"
        )

        cls.backend_process = subprocess.Popen(
            [
                str(venv_python),
                "-m",
                "business_agent.main",
                "--host",
                "127.0.0.1",
                "--port",
                str(BACKEND_PORT),
            ],
            cwd=str(root),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        _wait_for_url(
            f"{BACKEND_BASE_URL}/.well-known/agent-card.json",
            timeout_s=90,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        _safe_terminate(cls.backend_process)
        _safe_terminate(cls.profile_server_process)
        _safe_terminate(cls.ollama_process)

    def _send_message(
        self,
        message: str | list[dict[str, Any]],
        *,
        context_id: str | None = None,
    ) -> dict[str, Any]:
        parts: list[dict[str, Any]]
        if isinstance(message, str):
            parts = [{"type": "text", "text": message}]
        else:
            parts = message

        params: dict[str, Any] = {
            "message": {
                "role": "user",
                "parts": parts,
                "messageId": str(uuid.uuid4()),
                "kind": "message",
            },
            "configuration": {"historyLength": 0},
        }
        if context_id:
            params["message"]["contextId"] = context_id

        headers = {
            "Content-Type": "application/json",
            "X-A2A-Extensions": A2A_UCP_EXTENSION_URL,
            "UCP-Agent": f'profile="{CLIENT_PROFILE_URL}"',
        }

        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "message/send",
            "params": params,
        }

        response = None
        for attempt in range(2):
            try:
                with httpx.Client(timeout=240.0) as client:
                    response = client.post(
                        BACKEND_BASE_URL + "/",
                        headers=headers,
                        json=payload,
                    )
                break
            except httpx.ReadTimeout:
                if attempt == 1:
                    raise
                time.sleep(1)

        assert response is not None  # for type-checkers

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertNotIn("error", body, body)
        self.assertIn("result", body, body)
        return body["result"]

    def _create_completed_order(self, email: str = "test@example.com") -> tuple[str, dict[str, Any]]:
        add_result = self._send_message(
            json.dumps(
                {
                    "action": "add_to_checkout",
                    "product_id": "BISC-001",
                    "quantity": 1,
                }
            )
        )
        context_id = add_result.get("contextId")
        self.assertTrue(context_id)

        details_result = self._send_message(
            json.dumps(
                {
                    "action": "update_customer_details",
                    "first_name": "Test",
                    "last_name": "User",
                    "street_address": "123 Main St",
                    "address_locality": "San Francisco",
                    "address_region": "CA",
                    "postal_code": "94105",
                    "address_country": "US",
                    "email": email,
                }
            ),
            context_id=context_id,
        )
        details_parts = _extract_parts(details_result)
        checkout = _find_data(details_parts, "a2a.ucp.checkout")
        self.assertIsInstance(checkout, dict)

        if checkout.get("status") != "ready_for_complete":
            payment_start = self._send_message(
                json.dumps({"action": "start_payment"}),
                context_id=context_id,
            )
            payment_parts = _extract_parts(payment_start)
            checkout = _find_data(payment_parts, "a2a.ucp.checkout")
            self.assertIsInstance(checkout, dict)

        completion_result = self._send_message(
            [
                {"type": "data", "data": {"action": "complete_checkout"}},
                {
                    "type": "data",
                    "data": {
                        "a2a.ucp.checkout.payment_data": MOCK_PAYMENT_INSTRUMENT,
                        "a2a.ucp.checkout.risk_signals": {"data": "e2e-test-risk"},
                    },
                },
            ],
            context_id=context_id,
        )
        completion_parts = _extract_parts(completion_result)
        completed_checkout = _find_data(completion_parts, "a2a.ucp.checkout")
        self.assertIsInstance(completed_checkout, dict)
        self.assertEqual(completed_checkout.get("status"), "completed")

        return context_id, completed_checkout

    def test_well_known_endpoints(self) -> None:
        with httpx.Client(timeout=20.0) as client:
            agent_card_res = client.get(f"{BACKEND_BASE_URL}/.well-known/agent-card.json")
            ucp_res = client.get(f"{BACKEND_BASE_URL}/.well-known/ucp")

        self.assertEqual(agent_card_res.status_code, 200)
        self.assertEqual(ucp_res.status_code, 200)

        card = agent_card_res.json()
        ucp_profile = ucp_res.json()

        self.assertEqual(card.get("protocolVersion"), "0.3.0")
        self.assertIn("capabilities", card)
        self.assertIn("ucp", ucp_profile)
        self.assertIn("capabilities", ucp_profile["ucp"])

    def test_checkout_lifecycle_happy_path(self) -> None:
        context_id: str | None = None

        search_result = self._send_message("show me cookies available in stock")
        context_id = search_result.get("contextId")
        self.assertTrue(context_id)

        search_parts = _extract_parts(search_result)
        product_results = _find_data(search_parts, "a2a.product_results")
        self.assertIsInstance(product_results, dict)
        products = product_results.get("results", [])
        self.assertGreater(len(products), 0)
        product_id = products[0]["productID"]

        add_result = self._send_message(
            json.dumps(
                {
                    "action": "add_to_checkout",
                    "product_id": product_id,
                    "quantity": 1,
                }
            ),
            context_id=context_id,
        )
        context_id = add_result.get("contextId", context_id)
        add_parts = _extract_parts(add_result)
        checkout = _find_data(add_parts, "a2a.ucp.checkout")
        self.assertIsInstance(checkout, dict)
        self.assertEqual(checkout.get("status"), "incomplete")

        details_result = self._send_message(
            json.dumps(
                {
                    "action": "update_customer_details",
                    "first_name": "Test",
                    "last_name": "User",
                    "street_address": "123 Main St",
                    "address_locality": "San Francisco",
                    "address_region": "CA",
                    "postal_code": "94105",
                    "address_country": "US",
                    "email": "test@example.com",
                }
            ),
            context_id=context_id,
        )
        context_id = details_result.get("contextId", context_id)
        details_parts = _extract_parts(details_result)
        checkout = _find_data(details_parts, "a2a.ucp.checkout")
        self.assertIsInstance(checkout, dict)

        if checkout.get("status") != "ready_for_complete":
            payment_start = self._send_message(
                json.dumps({"action": "start_payment"}),
                context_id=context_id,
            )
            context_id = payment_start.get("contextId", context_id)
            payment_parts = _extract_parts(payment_start)
            checkout = _find_data(payment_parts, "a2a.ucp.checkout")
            self.assertIsInstance(checkout, dict)

        self.assertEqual(checkout.get("status"), "ready_for_complete")

        checkout = None
        completion_attempts = [
            [
                {
                    "type": "text",
                    "text": (
                        "Complete the checkout now using the provided payment data."
                    ),
                },
                {"type": "data", "data": {"action": "complete_checkout"}},
                {
                    "type": "data",
                    "data": {
                        "a2a.ucp.checkout.payment_data": MOCK_PAYMENT_INSTRUMENT,
                        "a2a.ucp.checkout.risk_signals": {"data": "e2e-test-risk"},
                    },
                },
            ],
            [
                {"type": "text", "text": '{"action":"complete_checkout"}'},
                {
                    "type": "data",
                    "data": {
                        "a2a.ucp.checkout.payment_data": MOCK_PAYMENT_INSTRUMENT,
                        "a2a.ucp.checkout.risk_signals": {"data": "e2e-test-risk"},
                    },
                },
            ],
        ]
        for attempt in completion_attempts:
            completion_result = self._send_message(attempt, context_id=context_id)
            completion_parts = _extract_parts(completion_result)
            checkout = _find_data(completion_parts, "a2a.ucp.checkout")
            if isinstance(checkout, dict):
                break

        self.assertIsInstance(checkout, dict)
        self.assertEqual(checkout.get("status"), "completed")
        self.assertIn("order", checkout)
        self.assertIn("id", checkout["order"])
        order_permalink = checkout["order"].get("permalink_url")
        self.assertIsInstance(order_permalink, str)
        self.assertIn("/orders/", order_permalink)

        with httpx.Client(timeout=20.0) as client:
            order_page = client.get(order_permalink)
        self.assertEqual(order_page.status_code, 200)
        self.assertIn(checkout["order"]["id"], order_page.text)

        protocol_trace = _find_data(completion_parts, "a2a.protocol_trace")
        self.assertIsInstance(protocol_trace, list)
        merchant_events = [
            event
            for event in protocol_trace
            if isinstance(event, dict)
            and event.get("stage")
            == "a2a.fast_path.action.complete_checkout.merchant_result"
        ]
        self.assertGreaterEqual(len(merchant_events), 1)
        last_merchant_event = merchant_events[-1]
        merchant_exchange = last_merchant_event.get("merchant_exchange")
        self.assertIsInstance(merchant_exchange, dict)
        merchant_result = merchant_exchange.get("merchant_result")
        self.assertIsInstance(merchant_result, dict)
        gateway = merchant_result.get("gateway")
        self.assertIsInstance(gateway, dict)
        self.assertEqual(gateway.get("provider"), "mock.ucp.gateway")
        self.assertEqual(gateway.get("status"), "approved")
        self.assertIn("transaction_id", gateway)

    def test_generic_catalog_query_returns_multiple_products(self) -> None:
        search_result = self._send_message("which kind of prod do you have")
        search_parts = _extract_parts(search_result)
        product_results = _find_data(search_parts, "a2a.product_results")
        self.assertIsInstance(product_results, dict)

        products = product_results.get("results", [])
        self.assertGreaterEqual(len(products), 4)

        product_ids = {product.get("productID") for product in products}
        self.assertIn("BISC-001", product_ids)
        self.assertIn("CHIPS-001", product_ids)

    def test_buy_intent_query_returns_catalog(self) -> None:
        search_result = self._send_message("what can i buy?")
        search_parts = _extract_parts(search_result)
        product_results = _find_data(search_parts, "a2a.product_results")
        self.assertIsInstance(product_results, dict)

        products = product_results.get("results", [])
        self.assertGreaterEqual(len(products), 4)

    def test_update_checkout_quantity_zero_removes_item(self) -> None:
        add_result = self._send_message(
            json.dumps(
                {
                    "action": "add_to_checkout",
                    "product_id": "BISC-001",
                    "quantity": 1,
                }
            )
        )
        context_id = add_result.get("contextId")
        self.assertTrue(context_id)

        add_parts = _extract_parts(add_result)
        checkout = _find_data(add_parts, "a2a.ucp.checkout")
        self.assertIsInstance(checkout, dict)
        self.assertGreaterEqual(len(checkout.get("line_items", [])), 1)

        update_result = self._send_message(
            json.dumps(
                {
                    "action": "update_checkout",
                    "product_id": "BISC-001",
                    "quantity": 0,
                }
            ),
            context_id=context_id,
        )
        update_parts = _extract_parts(update_result)
        checkout = _find_data(update_parts, "a2a.ucp.checkout")
        self.assertIsInstance(checkout, dict)
        self.assertEqual(len(checkout.get("line_items", [])), 0)

    def test_protocol_trace_is_included(self) -> None:
        result = self._send_message("show me cookies available in stock")
        parts = _extract_parts(result)
        protocol_trace = _find_data(parts, "a2a.protocol_trace")
        self.assertIsInstance(protocol_trace, list)

        stages = {
            entry.get("stage")
            for entry in protocol_trace
            if isinstance(entry, dict)
        }
        self.assertIn("ucp.negotiation.completed", stages)
        self.assertIn("a2a.fast_path.catalog.request", stages)
        self.assertIn("a2a.fast_path.catalog.response", stages)

    def test_invalid_payment_token_is_rejected(self) -> None:
        add_result = self._send_message(
            json.dumps(
                {
                    "action": "add_to_checkout",
                    "product_id": "BISC-001",
                    "quantity": 1,
                }
            )
        )
        context_id = add_result.get("contextId")
        self.assertTrue(context_id)

        details_result = self._send_message(
            json.dumps(
                {
                    "action": "update_customer_details",
                    "first_name": "Test",
                    "last_name": "User",
                    "street_address": "123 Main St",
                    "address_locality": "San Francisco",
                    "address_region": "CA",
                    "postal_code": "94105",
                    "address_country": "US",
                    "email": "test@example.com",
                }
            ),
            context_id=context_id,
        )
        details_parts = _extract_parts(details_result)
        checkout = _find_data(details_parts, "a2a.ucp.checkout")
        self.assertIsInstance(checkout, dict)
        self.assertEqual(checkout.get("status"), "ready_for_complete")

        invalid_token_parts = [
            {"type": "data", "data": {"action": "complete_checkout"}},
            {
                "type": "data",
                "data": {
                    "a2a.ucp.checkout.payment_data": {
                        **MOCK_PAYMENT_INSTRUMENT,
                        "credential": {"type": "token", "token": "tok_declined_e2e"},
                    },
                    "a2a.ucp.checkout.risk_signals": {"data": "e2e-invalid-token"},
                },
            },
        ]
        completion_result = self._send_message(invalid_token_parts, context_id=context_id)
        completion_parts = _extract_parts(completion_result)
        completed_checkout = _find_data(completion_parts, "a2a.ucp.checkout")
        self.assertIsNone(completed_checkout)

        text_payload = _collect_text(completion_parts).lower()
        self.assertIn("declined", text_payload)

    def test_show_my_orders_returns_order_history(self) -> None:
        context_id, completed_checkout = self._create_completed_order(
            email="orders-e2e@example.com"
        )
        completed_order_id = completed_checkout.get("order", {}).get("id")
        self.assertIsInstance(completed_order_id, str)

        orders_result = self._send_message("show me my orders", context_id=context_id)
        orders_parts = _extract_parts(orders_result)
        orders_payload = _find_data(orders_parts, "a2a.orders")
        self.assertIsInstance(orders_payload, list)
        self.assertGreaterEqual(len(orders_payload), 1)

        order_ids = {
            order.get("order", {}).get("id")
            for order in orders_payload
            if isinstance(order, dict)
        }
        self.assertIn(completed_order_id, order_ids)

        protocol_trace = _find_data(orders_parts, "a2a.protocol_trace")
        self.assertIsInstance(protocol_trace, list)
        trace_stages = {
            event.get("stage")
            for event in protocol_trace
            if isinstance(event, dict)
        }
        self.assertIn("a2a.fast_path.orders.request", trace_stages)
        self.assertIn("a2a.fast_path.orders.response", trace_stages)


if __name__ == "__main__":
    unittest.main(verbosity=2)

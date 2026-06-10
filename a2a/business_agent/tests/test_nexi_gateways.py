"""Unit tests for the Nexi gateways and Merchant handler routing (Fasi 2-6).

These tests do not hit the network: the async Nexi XPay calls are monkeypatched
with canned payloads, so the gateway state-mapping and the Merchant per-handler
routing / requires_action passthrough are verified in isolation.
"""

from __future__ import annotations

import asyncio
import unittest

from business_agent import nexi_gateway
from business_agent.nexi_gateway import (
    NexiCardGateway,
    NexiGooglePayGateway,
    run_async,
)
from business_agent.a2a_subagents import MerchantAgentA2A


def _async_return(value):
    async def _fn(*_args, **_kwargs):
        return value
    return _fn


def _async_raise(exc):
    async def _fn(*_args, **_kwargs):
        raise exc
    return _fn


class TestAsyncBridge(unittest.TestCase):
    def test_run_async_without_loop(self):
        async def _co():
            return 42

        self.assertEqual(run_async(_co()), 42)

    def test_run_async_inside_running_loop(self):
        async def _inside():
            async def _co():
                return 7

            return run_async(_co())

        self.assertEqual(asyncio.run(_inside()), 7)


class TestNexiCardGateway(unittest.TestCase):
    def setUp(self):
        self._orig_finalize = nexi_gateway.nexi_xpay.finalize_build_payment
        self._orig_state = nexi_gateway.nexi_xpay.get_build_state
        self.gw = NexiCardGateway()

    def tearDown(self):
        nexi_gateway.nexi_xpay.finalize_build_payment = self._orig_finalize
        nexi_gateway.nexi_xpay.get_build_state = self._orig_state

    def _cred(self, **extra):
        return {"credential": {"type": "nexi_build_operation", "session_id": "S1", **extra}}

    def test_frictionless_approved(self):
        nexi_gateway.nexi_xpay.finalize_build_payment = _async_return(
            {"state": "PAYMENT_COMPLETE", "operation": {"operationId": "op1"}}
        )
        r = self.gw.authorize_token(self._cred(), None)
        self.assertEqual(r["status"], "approved")
        self.assertEqual(r["transaction_id"], "op1")

    def test_three_ds_requires_action(self):
        nexi_gateway.nexi_xpay.finalize_build_payment = _async_return(
            {"state": "REDIRECTED_TO_EXTERNAL_DOMAIN", "url": "https://acs/x"}
        )
        r = self.gw.authorize_token(self._cred(), None)
        self.assertEqual(r["status"], "requires_action")
        self.assertEqual(r["redirect_url"], "https://acs/x")

    def test_resume_reads_build_state(self):
        nexi_gateway.nexi_xpay.get_build_state = _async_return(
            {"state": "PAYMENT_COMPLETE", "operation": {"operationId": "op2"}}
        )
        r = self.gw.authorize_token(self._cred(resume=True), None)
        self.assertEqual(r["status"], "approved")
        self.assertEqual(r["transaction_id"], "op2")

    def test_upstream_error_declined(self):
        nexi_gateway.nexi_xpay.finalize_build_payment = _async_raise(
            nexi_gateway.nexi_xpay.NexiUpstreamError(402, {"errors": []})
        )
        r = self.gw.authorize_token(self._cred(), None)
        self.assertEqual(r["status"], "declined")
        self.assertEqual(r["reason"], "nexi_upstream_error")

    def test_missing_session_declined(self):
        r = self.gw.authorize_token({"credential": {"type": "nexi_build_operation"}}, None)
        self.assertEqual(r["reason"], "missing_session")


class TestNexiGooglePayGateway(unittest.TestCase):
    def setUp(self):
        self._orig_gp = nexi_gateway.nexi_xpay.process_googlepay_order
        self._orig_order = nexi_gateway.nexi_xpay.get_order
        self.gw = NexiGooglePayGateway()
        self.ctx = {
            "checkout_id": "chk1",
            "amount_cents": 1999,
            "currency": "EUR",
            "buyer_email": "a@b.it",
        }

    def tearDown(self):
        nexi_gateway.nexi_xpay.process_googlepay_order = self._orig_gp
        nexi_gateway.nexi_xpay.get_order = self._orig_order

    def _cred(self, **extra):
        return {
            "credential": {
                "type": "nexi_googlepay_operation",
                "order_context": self.ctx,
                "googlepay_payment_data": {"t": 1},
                **extra,
            }
        }

    def test_frictionless_approved(self):
        nexi_gateway.nexi_xpay.process_googlepay_order = _async_return(
            {"operation": {"operationId": "gop1", "operationResult": "THREEDS_VALIDATED"}}
        )
        r = self.gw.authorize_token(self._cred(), None)
        self.assertEqual(r["status"], "approved")
        self.assertEqual(r["transaction_id"], "gop1")

    def test_three_ds_requires_action(self):
        nexi_gateway.nexi_xpay.process_googlepay_order = _async_return(
            {"state": "REDIRECTED_TO_EXTERNAL_DOMAIN", "url": "https://acs/gp"}
        )
        r = self.gw.authorize_token(self._cred(), None)
        self.assertEqual(r["status"], "requires_action")
        self.assertEqual(r["redirect_url"], "https://acs/gp")

    def test_resume_failed_declined(self):
        nexi_gateway.nexi_xpay.get_order = _async_return(
            {"operation": {"operationResult": "THREEDS_FAILED"}}
        )
        r = self.gw.authorize_token(self._cred(resume=True), None)
        self.assertEqual(r["status"], "declined")
        self.assertEqual(r["reason"], "nexi_declined")

    def test_incomplete_context_declined(self):
        r = self.gw.authorize_token(
            {
                "credential": {
                    "type": "nexi_googlepay_operation",
                    "order_context": {"checkout_id": "x"},
                    "googlepay_payment_data": {"t": 1},
                }
            },
            None,
        )
        self.assertEqual(r["reason"], "missing_order_context")


class TestMerchantRouting(unittest.TestCase):
    def setUp(self):
        self.merchant = MerchantAgentA2A()

    def _params(self, handler_id, cred_type, token):
        return {
            "payment_data": {
                "handler_id": handler_id,
                "credential": {"type": cred_type, "token": token},
            }
        }

    def test_mock_token_approved(self):
        r = self.merchant._process_payment_token(
            self._params("example_payment_provider", "token", "mock_token")
        )
        self.assertEqual(r["status"], "approved")

    def test_mock_declined_token(self):
        r = self.merchant._process_payment_token(
            self._params("example_payment_provider", "token", "tok_declined_x")
        )
        self.assertEqual(r["status"], "declined")
        self.assertEqual(r["reason"], "token_declined")

    def test_unknown_handler(self):
        r = self.merchant._process_payment_token(
            self._params("does_not_exist", "token", "x")
        )
        self.assertEqual(r["reason"], "unsupported_handler")

    def test_mock_rejects_nexi_credential_type(self):
        r = self.merchant._process_payment_token(
            self._params("example_payment_provider", "nexi_build_operation", "x")
        )
        self.assertEqual(r["reason"], "invalid_token_format")

    def test_nexi_card_accepts_its_credential_and_passes_requires_action(self):
        # Monkeypatch the card gateway's Nexi call to a 3DS redirect.
        orig = nexi_gateway.nexi_xpay.finalize_build_payment
        nexi_gateway.nexi_xpay.finalize_build_payment = _async_return(
            {"state": "REDIRECTED_TO_EXTERNAL_DOMAIN", "url": "https://acs/z"}
        )
        try:
            params = {
                "payment_data": {
                    "handler_id": "nexi_card",
                    "credential": {
                        "type": "nexi_build_operation",
                        "token": "S1",
                        "session_id": "S1",
                    },
                }
            }
            r = self.merchant._process_payment_token(params)
        finally:
            nexi_gateway.nexi_xpay.finalize_build_payment = orig
        self.assertEqual(r["status"], "requires_action")
        self.assertEqual(r["redirect_url"], "https://acs/z")


if __name__ == "__main__":
    unittest.main()

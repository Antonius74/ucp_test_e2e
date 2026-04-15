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

import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import AgentExtension, DataPart, Part, TaskState, TextPart
from a2a.utils import (
    get_data_parts,
    get_message_text,
    new_agent_parts_message,
    new_agent_text_message,
)
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from ucp_sdk.models.schemas.shopping.types.payment_instrument import (
    PaymentInstrument,
)
from ucp_sdk.models.schemas.ucp import ResponseCheckout as UcpMetadata
from .agent import mpp
from .agent import shop_agent
from .constants import (
    A2A_UCP_EXTENSION_URL,
    ADK_EXTENSIONS_STATE_KEY,
    ADK_LATEST_TOOL_RESULT,
    ADK_PAYMENT_STATE,
    ADK_UCP_METADATA_STATE,
    UCP_AGENT_HEADER,
    UCP_PAYMENT_DATA_KEY,
    UCP_PROTOCOL_TRACE_KEY,
    UCP_RISK_SIGNALS_KEY,
)
from .ucp_profile_resolver import ProfileResolver


class UcpRequestProcessor:
    """Handle UCP-specific request processing."""

    def __init__(self, profile_resolver: ProfileResolver):
        """Initialize the UCP request processor.

        Args:
            profile_resolver: The profile resolver instance.

        """
        self.profile_resolver = profile_resolver

    def prepare_ucp_metadata(self, context: RequestContext) -> UcpMetadata:
        """Prepare UCP metadata from the request context.

        Args:
            context: The request context.

        Returns:
            UcpMetadata: The prepared UCP metadata.

        Raises:
            ValueError: If required headers or profiles are missing.

        """
        if A2A_UCP_EXTENSION_URL not in context.requested_extensions:
            raise ValueError("UCP Extension is required for this agent")

        headers = context.call_context.state.get("headers")  # type: ignore

        ucp_agent_header_key = next(
            (key for key in headers if key.lower() == UCP_AGENT_HEADER.lower()),
            None,
        )

        if not ucp_agent_header_key:
            raise ValueError("UCP-Agent should be present in request headers")

        ucp_agent_header_value = headers[ucp_agent_header_key]

        match = re.search(r'profile="([^"]*)"', ucp_agent_header_value)
        if not match or not match.group(1):
            raise ValueError(
                "Client profile URL is missing or empty in UCP-Agent header"
            )

        client_profile_url = match.group(1)
        client_profile_metadata = self.profile_resolver.resolve_profile(
            client_profile_url
        )
        return self.profile_resolver.get_ucp_metadata(client_profile_metadata)


class ADKAgentExecutor(AgentExecutor):
    """ADK agent executor implementation."""

    def __init__(self, agent, extensions: list[AgentExtension]):
        """Initialize a generic ADK agent executor.

        Args:
            agent: The ADK agent instance.
            extensions: List of agent extensions to be used.

        """
        self.agent = agent
        self.runner = Runner(
            app_name=agent.name,
            agent=agent,
            session_service=InMemorySessionService(),
        )
        self.extensions = extensions or []
        self.profile_resolver = ProfileResolver()
        self.ucp_processor = UcpRequestProcessor(self.profile_resolver)

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Cancel the execution of a specific task.

        Args:
            context: The request context.
            event_queue: The event queue.

        """
        task_id = getattr(context, "task_id", None)
        message = (
            f"Cancellation acknowledged for task {task_id}."
            if task_id
            else "Cancellation acknowledged."
        )
        await event_queue.enqueue_event(new_agent_text_message(message))

    async def _get_or_create_session(self, context: RequestContext, user_id: str):
        """Get an existing session or create a new one.

        Args:
            context: The request context.
            user_id: The ID of the user.

        Returns:
            The session object.

        """
        session = await self.runner.session_service.get_session(
            app_name=self.agent.name,
            user_id=user_id,
            session_id=context.context_id,  # type: ignore
        )
        if session is None:
            session = await self.runner.session_service.create_session(
                app_name=self.agent.name,
                user_id=user_id,
                session_id=context.context_id,  # type: ignore
            )

        return session

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Execute the agent for the given context.

        Args:
            context: The request context.
            event_queue: The event queue.

        """
        if not context.message:
            raise ValueError("Message should be present in request context")

        trace_events: list[dict[str, Any]] = []
        self._append_trace(
            trace_events,
            "a2a.execute.start",
            context_id=str(context.context_id),
            requested_extensions=context.requested_extensions,
            agent_framework="Google Agent Development Kit (ADK)",
        )

        self._activate_extensions(context)
        self._append_trace(
            trace_events,
            "a2a.extensions.activated",
            activated_extensions=context.requested_extensions,
        )
        ucp_metadata = self.ucp_processor.prepare_ucp_metadata(context)
        self._append_trace(
            trace_events,
            "ucp.negotiation.completed",
            ucp_version=ucp_metadata.version,
            capabilities=[
                capability.name for capability in ucp_metadata.capabilities
            ],
        )

        query, payment_data, explicit_action = self._prepare_input(
            context, trace_events
        )

        direct_action_parts = self._try_execute_direct_action(
            context=context,
            ucp_metadata=ucp_metadata,
            explicit_action=explicit_action,
            payment_data=payment_data,
            trace_events=trace_events,
        )
        if direct_action_parts is not None:
            direct_action_parts = self._attach_protocol_trace_part(
                direct_action_parts, trace_events
            )
            await event_queue.enqueue_event(
                new_agent_parts_message(
                    direct_action_parts, context.context_id, None
                )
            )
            return

        fast_order_parts = self._try_fast_order_lookup(
            context, query, trace_events
        )
        if fast_order_parts is not None:
            fast_order_parts = self._attach_protocol_trace_part(
                fast_order_parts, trace_events
            )
            await event_queue.enqueue_event(
                new_agent_parts_message(
                    fast_order_parts, context.context_id, None
                )
            )
            return

        fast_search_parts = self._try_fast_catalog_search(
            context, query, trace_events
        )
        if fast_search_parts is not None:
            fast_search_parts = self._attach_protocol_trace_part(
                fast_search_parts, trace_events
            )
            await event_queue.enqueue_event(
                new_agent_parts_message(
                    fast_search_parts, context.context_id, None
                )
            )
            return

        if self._is_greeting(query):
            self._append_trace(
                trace_events,
                "a2a.fast_path.greeting",
                query=query,
                execution_mode="fast_path",
                adk_runner_used=False,
            )
            greeting_parts = [
                Part(
                    root=TextPart(
                        text=(
                            "Hi! I can help you find products and complete "
                            "checkout. Try: show me cookies available in stock."
                        )
                    )
                )
            ]
            greeting_parts = self._attach_protocol_trace_part(
                greeting_parts, trace_events
            )
            await event_queue.enqueue_event(
                new_agent_parts_message(
                    greeting_parts,
                    context.context_id,
                    None,
                )
            )
            return

        user_id: str = context.context_id  # random guest id for the session

        try:
            session = await self._get_or_create_session(context, user_id)
            result_parts = await self._run_agent_and_process_response(
                user_id,
                session.id,
                query,
                context,
                ucp_metadata,
                payment_data,
                trace_events,
            )
            result_parts = self._attach_protocol_trace_part(
                result_parts, trace_events
            )
            await event_queue.enqueue_event(
                new_agent_parts_message(result_parts, context.context_id, None)
            )

        except Exception as e:
            self._append_trace(
                trace_events,
                "a2a.execute.error",
                error=str(e),
            )
            await event_queue.enqueue_event(
                new_agent_text_message(
                    f"Error: {context.context_id} - {str(e)}",
                )
            )

    def _activate_extensions(self, context: RequestContext):
        """Activate extensions based on the request context.

        Args:
            context: The request context.

        """
        if context.requested_extensions:
            for ext in self.extensions:
                if ext.uri in context.requested_extensions:
                    context.add_activated_extension(ext.uri)

    def _to_trace_value(self, value: Any) -> Any:
        """Convert runtime values to JSON-friendly trace payloads."""
        if value is None or isinstance(value, (str, int, float, bool)):
            return value

        if isinstance(value, dict):
            return {
                str(key): self._to_trace_value(nested)
                for key, nested in value.items()
            }

        if isinstance(value, (list, tuple, set)):
            return [self._to_trace_value(item) for item in value]

        if hasattr(value, "model_dump"):
            try:
                return self._to_trace_value(value.model_dump(mode="json"))
            except Exception:
                return str(value)

        return str(value)

    def _append_trace(
        self,
        trace_events: list[dict[str, Any]],
        stage: str,
        **details: Any,
    ) -> None:
        """Append a protocol trace event."""
        event: dict[str, Any] = {
            "stage": stage,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        for key, value in details.items():
            event[key] = self._to_trace_value(value)
        trace_events.append(event)

    def _attach_protocol_trace_part(
        self,
        parts: list[Part],
        trace_events: list[dict[str, Any]],
    ) -> list[Part]:
        """Attach protocol trace details as a data part."""
        if not trace_events:
            return parts

        return [
            *parts,
            Part(root=DataPart(data={UCP_PROTOCOL_TRACE_KEY: trace_events})),
        ]

    def _prepare_input(
        self,
        context: RequestContext,
        trace_events: list[dict[str, Any]],
    ) -> tuple[str, dict | None, tuple[str, dict[str, Any]] | None]:
        """Prepare user query and payment mandate from the request context.

        Args:
            context: The request context.

        Returns:
            tuple[str, dict | None]: The query and payment data.

        """
        query = context.get_user_input()
        self._append_trace(
            trace_events,
            "a2a.input.raw",
            user_input=query,
        )
        text_action = self._parse_action_payload(query)
        explicit_action = text_action
        if text_action:
            query = self._action_to_tool_instruction(*text_action)

        data_list = get_data_parts(context.message.parts)  # type: ignore
        payment_payload: dict[str, Any] = {}
        payment_keys = [UCP_PAYMENT_DATA_KEY, UCP_RISK_SIGNALS_KEY]

        # extract payment data related structured inputs
        # for processing by tools from the state
        for data_part in data_list:
            for key in payment_keys:
                if key in data_part:
                    value = data_part.pop(key)
                    if key == UCP_PAYMENT_DATA_KEY:
                        payment_payload[key] = PaymentInstrument.model_validate(value)
                    else:
                        payment_payload[key] = value

            payload_action = self._parse_action_payload(data_part)
            if payload_action:
                explicit_action = payload_action
                query += "\n" + self._action_to_tool_instruction(*payload_action)
                data_part.pop("action", None)

            if data_part:
                query += "\n" + json.dumps(data_part)

        self._append_trace(
            trace_events,
            "a2a.input.prepared",
            query=query,
            explicit_action=explicit_action,
            has_payment_data=bool(payment_payload),
            adk_runner_candidate=explicit_action is None,
        )
        return query, payment_payload or None, explicit_action

    def _parse_action_payload(
        self, payload: str | dict[str, Any]
    ) -> tuple[str, dict[str, Any]] | None:
        """Return action name and params when payload has an action field."""
        data: dict[str, Any] | None = None
        if isinstance(payload, str):
            payload = payload.strip()
            if not payload.startswith("{"):
                return None
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                return None
            if isinstance(parsed, dict):
                data = parsed
        elif isinstance(payload, dict):
            data = payload

        if not data:
            return None

        action = data.get("action")
        if not isinstance(action, str) or not action.strip():
            return None

        params = {key: value for key, value in data.items() if key != "action"}
        return action.strip(), params

    def _action_to_tool_instruction(
        self, action: str, params: dict[str, Any]
    ) -> str:
        """Convert structured action payload into a deterministic tool instruction."""
        if params:
            encoded_params = json.dumps(params)
            return (
                f"Execute the tool action '{action}' with params {encoded_params}. "
                "Call the matching tool and do not echo the JSON."
            )
        return (
            f"Execute the tool action '{action}'. "
            "Call the matching tool and do not echo the JSON."
        )

    def _is_greeting(self, query: str) -> bool:
        """Return True when user message is a plain greeting."""
        cleaned = query.strip().lower()
        if not cleaned:
            return False
        if cleaned.startswith("execute the tool action"):
            return False

        normalized = re.sub(r"[!?.,;:]+", "", cleaned).strip()
        return normalized in {
            "hi",
            "hello",
            "hey",
            "ciao",
            "hola",
            "good morning",
            "good afternoon",
            "good evening",
        }

    def _build_shop_agent_request(
        self,
        context: RequestContext,
        parts: list[dict[str, Any]],
        ucp_metadata: UcpMetadata | None = None,
    ) -> dict[str, Any]:
        """Build an in-process A2A request for the shop agent."""
        params: dict[str, Any] = {
            "message": {
                "role": "user",
                "kind": "message",
                "messageId": str(uuid4()),
                "contextId": str(context.context_id),
                "parts": parts,
            }
        }

        if ucp_metadata is not None:
            params["metadata"] = {
                "ucp_metadata": ucp_metadata.model_dump(mode="json"),
            }

        return {
            "jsonrpc": "2.0",
            "id": str(uuid4()),
            "method": "message/send",
            "params": params,
        }

    def _subagent_response_to_parts(
        self,
        response: dict[str, Any],
    ) -> list[Part]:
        """Convert in-process sub-agent JSON-RPC response to A2A parts."""
        result = response.get("result")
        if not isinstance(result, dict):
            return []
        response_parts = result.get("parts")
        if not isinstance(response_parts, list):
            return []

        parts: list[Part] = []
        for response_part in response_parts:
            if not isinstance(response_part, dict):
                continue
            part_type = response_part.get("type")
            if part_type == "text":
                text = response_part.get("text")
                if isinstance(text, str):
                    parts.append(Part(root=TextPart(text=text)))
            elif part_type == "data":
                data = response_part.get("data")
                if isinstance(data, dict):
                    parts.append(Part(root=DataPart(data=data)))
        return parts

    def _extract_data_from_parts(self, parts: list[Part], key: str) -> Any | None:
        """Return structured data from a list of A2A parts."""
        for part in parts:
            root = getattr(part, "root", None)
            data = getattr(root, "data", None)
            if isinstance(data, dict) and key in data:
                return data[key]
        return None

    def _payment_instrument_to_dict(self, payment_instrument: Any) -> dict[str, Any] | None:
        """Convert payment instrument to a JSON-serializable dictionary."""
        if payment_instrument is None:
            return None
        if isinstance(payment_instrument, dict):
            return payment_instrument
        if hasattr(payment_instrument, "model_dump"):
            return payment_instrument.model_dump(mode="json")
        return None

    def _is_order_lookup_query(self, query: str) -> bool:
        """Return True when the query is asking for existing orders."""
        cleaned = query.strip().lower()
        if not cleaned or cleaned.startswith("execute the tool action"):
            return False

        order_words = {"order", "orders", "ordine", "ordini"}
        if not any(word in cleaned for word in order_words):
            return False
        if cleaned in {"order", "orders", "my order", "my orders"}:
            return True

        intent_hints = {
            "my",
            "show",
            "view",
            "history",
            "status",
            "track",
            "where",
            "last",
            "latest",
            "recent",
            "past",
            "all",
            "list",
        }
        return any(hint in cleaned for hint in intent_hints)

    def _try_fast_order_lookup(
        self,
        context: RequestContext,
        query: str,
        trace_events: list[dict[str, Any]],
    ) -> list[Part] | None:
        """Fast path for order retrieval and order status messages."""
        if not self._is_order_lookup_query(query):
            return None

        cleaned = query.strip().lower()
        order_id_match = re.search(r"\b(ord-[a-z0-9_-]+)\b", query, re.IGNORECASE)

        if order_id_match:
            action_payload: dict[str, Any] = {
                "action": "get_order",
                "order_id": order_id_match.group(1).upper(),
            }
        elif "all orders" in cleaned or "order history" in cleaned or "my orders" in cleaned:
            action_payload = {"action": "list_orders", "limit": 10}
        else:
            action_payload = {"action": "get_latest_order"}

        shop_request = self._build_shop_agent_request(
            context=context,
            parts=[{"type": "data", "data": action_payload}],
        )
        self._append_trace(
            trace_events,
            "a2a.fast_path.orders.request",
            query=query,
            action=action_payload,
            jsonrpc=shop_request,
        )
        shop_response = shop_agent.handle_jsonrpc(shop_request)
        self._append_trace(
            trace_events,
            "a2a.fast_path.orders.response",
            jsonrpc=shop_response,
        )

        parts = self._subagent_response_to_parts(shop_response)
        if not parts:
            return None

        orders = self._extract_data_from_parts(parts, "a2a.orders")
        checkout = self._extract_data_from_parts(parts, "a2a.ucp.checkout")
        self._append_trace(
            trace_events,
            "a2a.fast_path.orders.completed",
            has_checkout=bool(checkout),
            order_count=len(orders) if isinstance(orders, list) else None,
            execution_mode="fast_path_orders",
            adk_runner_used=False,
        )
        return parts

    def _try_fast_catalog_search(
        self,
        context: RequestContext,
        query: str,
        trace_events: list[dict[str, Any]],
    ) -> list[Part] | None:
        """Fast path for straightforward product search requests."""
        cleaned = query.strip().lower()
        if not cleaned or cleaned.startswith("execute the tool action"):
            return None

        product_hint_words = {
            "show",
            "find",
            "search",
            "what",
            "which",
            "kind",
            "kinds",
            "type",
            "types",
            "product",
            "products",
            "prod",
            "catalog",
            "catalogue",
            "have",
            "list",
            "all",
            "available",
            "stock",
            "cookie",
            "cookies",
            "chip",
            "chips",
            "strawberries",
            "strawberry",
            "nutri",
            "bar",
        }
        if not any(word in cleaned for word in product_hint_words):
            return None

        tokens = re.findall(r"[a-z0-9]+", cleaned)
        stopwords = {
            "a",
            "an",
            "and",
            "any",
            "are",
            "can",
            "could",
            "do",
            "for",
            "i",
            "in",
            "is",
            "it",
            "kind",
            "kinds",
            "me",
            "of",
            "show",
            "tell",
            "the",
            "to",
            "what",
            "which",
            "would",
            "you",
            "your",
        }
        generic_catalog_terms = {
            "all",
            "available",
            "catalog",
            "catalogue",
            "have",
            "sell",
            "buy",
            "purchase",
            "something",
            "anything",
            "stuff",
            "item",
            "items",
            "list",
            "prod",
            "product",
            "products",
            "stock",
            "type",
            "types",
        }
        informative_tokens = [token for token in tokens if token not in stopwords]
        is_generic_catalog_request = (
            bool(informative_tokens)
            and all(token in generic_catalog_terms for token in informative_tokens)
        )

        request_query = "" if is_generic_catalog_request else query
        shop_request = self._build_shop_agent_request(
            context=context,
            parts=[{"type": "text", "text": request_query}],
        )
        self._append_trace(
            trace_events,
            "a2a.fast_path.catalog.request",
            query=request_query,
            jsonrpc=shop_request,
        )
        shop_response = shop_agent.handle_jsonrpc(shop_request)
        self._append_trace(
            trace_events,
            "a2a.fast_path.catalog.response",
            jsonrpc=shop_response,
        )

        parts = self._subagent_response_to_parts(shop_response)
        product_results = self._extract_data_from_parts(parts, "a2a.product_results")
        if not isinstance(product_results, dict):
            return None
        self._append_trace(
            trace_events,
            "a2a.fast_path.catalog.completed",
            result_count=len(product_results.get("results", [])),
            execution_mode="fast_path_catalog",
            adk_runner_used=False,
        )
        return parts

    def _try_execute_direct_action(
        self,
        context: RequestContext,
        ucp_metadata: UcpMetadata,
        explicit_action: tuple[str, dict[str, Any]] | None,
        payment_data: dict[str, Any] | None,
        trace_events: list[dict[str, Any]],
    ) -> list[Part] | None:
        """Execute supported JSON action payloads without an LLM roundtrip."""
        if explicit_action is None:
            return None

        action_name, params = explicit_action
        action = action_name.strip()
        self._append_trace(
            trace_events,
            "a2a.fast_path.action.received",
            action=action,
            params=params,
            execution_mode="fast_path_action",
            adk_runner_used=False,
        )
        supported_actions = {
            "add_to_checkout",
            "remove_from_checkout",
            "update_checkout",
            "get_checkout",
            "get_latest_order",
            "get_order",
            "list_orders",
            "start_payment",
            "update_customer_details",
            "complete_checkout",
        }
        if action not in supported_actions:
            return None

        try:
            if action == "complete_checkout":
                if payment_data is None:
                    self._append_trace(
                        trace_events,
                        "a2a.fast_path.action.complete_checkout.missing_payment_data",
                    )
                    return [
                        Part(
                            root=TextPart(
                                text=(
                                    "Payment Data is missing. Click 'Confirm Purchase' "
                                    "to complete the purchase."
                                )
                            )
                        )
                    ]

                payment_instrument = payment_data.get(UCP_PAYMENT_DATA_KEY)
                self._append_trace(
                    trace_events,
                    "a2a.fast_path.action.complete_checkout.payment_request",
                    payment_data=payment_data,
                )
                task = mpp.process_payment(
                    payment_data[UCP_PAYMENT_DATA_KEY],
                    payment_data[UCP_RISK_SIGNALS_KEY],
                )
                self._append_trace(
                    trace_events,
                    "a2a.fast_path.action.complete_checkout.merchant_result",
                    task_state=task.status.state if task.status else None,
                    merchant_exchange=getattr(mpp, "last_exchange", None),
                )
                if task.status is None or task.status.state != TaskState.completed:
                    message = get_message_text(task.status.message)  # type: ignore
                    self._append_trace(
                        trace_events,
                        "a2a.fast_path.action.complete_checkout.failed",
                        message=message,
                    )
                    return [Part(root=TextPart(text=message or "Payment failed."))]

                complete_params: dict[str, Any] = {"action": "complete_checkout"}
                payment_instrument_data = self._payment_instrument_to_dict(
                    payment_instrument
                )
                if payment_instrument_data is not None:
                    complete_params["payment_instrument"] = payment_instrument_data

                complete_request = self._build_shop_agent_request(
                    context=context,
                    parts=[{"type": "data", "data": complete_params}],
                )
                self._append_trace(
                    trace_events,
                    "a2a.fast_path.action.complete_checkout.shop_request",
                    jsonrpc=complete_request,
                )
                response = shop_agent.handle_jsonrpc(complete_request)
                self._append_trace(
                    trace_events,
                    "a2a.fast_path.action.complete_checkout.shop_response",
                    jsonrpc=response,
                )
                result_parts = self._subagent_response_to_parts(response)

                merchant_result = None
                merchant_exchange = getattr(mpp, "last_exchange", None)
                if isinstance(merchant_exchange, dict):
                    candidate = merchant_exchange.get("merchant_result")
                    if isinstance(candidate, dict):
                        merchant_result = candidate

                if isinstance(merchant_result, dict):
                    auth_code = merchant_result.get("authorization_code")
                    gateway = merchant_result.get("gateway")
                    transaction_id = (
                        gateway.get("transaction_id")
                        if isinstance(gateway, dict)
                        else None
                    )
                    if isinstance(auth_code, str) and isinstance(
                        transaction_id, str
                    ):
                        result_parts.insert(
                            0,
                            Part(
                                root=TextPart(
                                    text=(
                                        "Payment authorized via UCP merchant/gateway "
                                        f"simulation. Auth: {auth_code}, "
                                        f"Transaction: {transaction_id}."
                                    )
                                )
                            ),
                        )

                return result_parts

            shop_request = self._build_shop_agent_request(
                context=context,
                parts=[
                    {
                        "type": "data",
                        "data": {"action": action, **params},
                    }
                ],
                ucp_metadata=ucp_metadata if action == "add_to_checkout" else None,
            )
            self._append_trace(
                trace_events,
                "a2a.fast_path.action.shop_request",
                jsonrpc=shop_request,
            )
            response = shop_agent.handle_jsonrpc(shop_request)
            self._append_trace(
                trace_events,
                "a2a.fast_path.action.shop_response",
                jsonrpc=response,
            )
            return self._subagent_response_to_parts(response)

        except KeyError as e:
            self._append_trace(
                trace_events,
                "a2a.fast_path.action.error",
                error=f"Missing required action parameter: {e}",
            )
            return [Part(root=TextPart(text=f"Missing required action parameter: {e}"))]
        except Exception as e:
            self._append_trace(
                trace_events,
                "a2a.fast_path.action.error",
                error=str(e),
            )
            return [Part(root=TextPart(text=f"Error executing action '{action}': {e}"))]

    def _build_initial_state_delta(
        self,
        context: RequestContext,
        ucp_metadata: UcpMetadata,
        payment_data: dict | None,
    ) -> dict:
        """Build the initial state delta for the agent run.

        Args:
            context: The request context.
            ucp_metadata: The UCP metadata.
            payment_data: The payment data.

        Returns:
            dict: The initial state delta.

        """
        return {
            ADK_UCP_METADATA_STATE: ucp_metadata,
            ADK_EXTENSIONS_STATE_KEY: context.requested_extensions,
            ADK_PAYMENT_STATE: payment_data,
            ADK_LATEST_TOOL_RESULT: None,
        }

    async def _run_agent_and_process_response(
        self,
        user_id: str,
        session_id: str,
        query: str,
        context: RequestContext,
        ucp_metadata: UcpMetadata,
        payment_data: dict | None,
        trace_events: list[dict[str, Any]],
    ) -> list[Part]:
        """Run the ADK agent and processes the response.

        Args:
            user_id: The ID of the user.
            session_id: The ID of the session.
            query: The user query.
            context: The request context.
            ucp_metadata: The UCP metadata.
            payment_data: The payment data.

        Returns:
            list[Part]: The response parts.

        """
        content = types.Content(role="user", parts=[types.Part.from_text(text=query)])
        self._append_trace(
            trace_events,
            "a2a.llm_path.start",
            query=query,
            session_id=session_id,
            execution_mode="adk_runner",
            adk_runner_used=True,
            agent_framework="Google Agent Development Kit (ADK)",
        )

        state_delta = self._build_initial_state_delta(
            context, ucp_metadata, payment_data
        )
        result_parts: list[Part] = []

        final_events: list = []

        async for event in self.runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=content,
            state_delta=state_delta,
        ):
            if event.is_final_response() or len(final_events) > 0:
                final_events.append(event)

        for final_event in final_events:
            response_text = ""
            for part in final_event.content.parts:  # type: ignore
                result_part = self._process_event_part(part)
                if isinstance(result_part, DataPart):
                    result_parts.append(Part(root=result_part))
                elif isinstance(result_part, TextPart):
                    response_text += result_part.text

            if response_text and not any(
                isinstance(p.root, DataPart) for p in result_parts
            ):
                result_parts.append(Part(root=TextPart(text=response_text)))

        self._append_trace(
            trace_events,
            "a2a.llm_path.completed",
            final_event_count=len(final_events),
            response_part_count=len(result_parts),
            execution_mode="adk_runner",
            adk_runner_used=True,
        )
        return result_parts

    def _process_event_part(self, part) -> TextPart | DataPart | None:
        """Process a part from a runner event and return a result part.

        Args:
            part: The part to process.

        Returns:
            TextPart | DataPart | None: The result part, or None.

        """
        if part.function_response and part.function_response.response:
            result = part.function_response.response.get("result")
            if isinstance(result, dict):
                return DataPart(data=result)
            if isinstance(result, str):
                return TextPart(text=result)

        if hasattr(part, "text") and part.text:
            return TextPart(text=part.text)

        return None

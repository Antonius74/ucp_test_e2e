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

import logging
import os
from typing import Any
from a2a.types import TaskState
from a2a.utils import get_message_text
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types
from ucp_sdk.models.schemas.shopping.types.buyer import Buyer
from ucp_sdk.models.schemas.shopping.types.postal_address import PostalAddress
from .a2a_subagents import MerchantAgentA2A, ShopAgentA2A
from .a2a_extensions import UcpExtension
from .constants import (
    ADK_EXTENSIONS_STATE_KEY,
    ADK_LAST_ORDER_ID,
    ADK_LATEST_TOOL_RESULT,
    ADK_PAYMENT_STATE,
    ADK_UCP_METADATA_STATE,
    ADK_USER_CHECKOUT_ID,
    UCP_CHECKOUT_KEY,
    UCP_PURCHASE_RESERVATION_KEY,
    UCP_PURCHASE_RESERVATIONS_KEY,
    UCP_PAYMENT_DATA_KEY,
    UCP_RISK_SIGNALS_KEY,
)
from .payment_processor import MockPaymentProcessor
from .store import RetailStore


store = RetailStore()
shop_agent = ShopAgentA2A(store=store)
merchant_agent = MerchantAgentA2A()
mpp = MockPaymentProcessor(merchant_agent=merchant_agent)
load_dotenv()

DEFAULT_AGENT_MODEL = "ollama/gpt-oss:120b-cloud"
AGENT_MODEL_ENV_VAR = "BUSINESS_AGENT_MODEL"


def get_configured_model_name() -> str:
    """Return the configured model name for the shopper agent."""
    model_name = os.getenv(AGENT_MODEL_ENV_VAR, DEFAULT_AGENT_MODEL).strip()
    return model_name or DEFAULT_AGENT_MODEL


def _create_error_response(message: str) -> dict:
    return {"message": message, "status": "error"}


def search_shopping_catalog(tool_context: ToolContext, query: str) -> dict:
    """Search the product catalog for products that match the given query.

    Args:
        tool_context: The tool context for the current request.
        query: Query for performing product search.

    Returns:
        dict: Returns the response from the tool with success or error status.

    """
    try:
        product_results = store.search_products(query)
        return {"a2a.product_results": product_results.model_dump(mode="json")}
    except Exception:
        logging.exception("There was an error searching the product catalog.")
        return _create_error_response(
            "Sorry, there was an error searching the product catalog, "
            "please try again later."
        )


def add_to_checkout(
    tool_context: ToolContext, product_id: str, quantity: int = 1
) -> dict:
    """Add a product to the checkout session.

    Args:
        tool_context: The tool context for the current request.
        product_id: Product ID or SKU.
        quantity: Quantity; defaults to 1 if not specified.

    Returns:
        dict: Returns the response from the tool with success or error status.

    """
    checkout_id = tool_context.state.get(ADK_USER_CHECKOUT_ID)
    ucp_metadata = tool_context.state.get(ADK_UCP_METADATA_STATE)

    if not ucp_metadata:
        return _create_error_response("There was an error creating UCP metadata")

    try:
        checkout = store.add_to_checkout(
            ucp_metadata, product_id, quantity, checkout_id
        )
        if not checkout_id:
            tool_context.state[ADK_USER_CHECKOUT_ID] = checkout.id

        return {
            UCP_CHECKOUT_KEY: checkout.model_dump(mode="json"),
            "status": "success",
        }
    except ValueError:
        logging.exception(
            "There was an error adding item to checkout, please retry later."
        )
        return _create_error_response(
            "There was an error adding item to checkout, please retry later."
        )


def remove_from_checkout(tool_context: ToolContext, product_id: str) -> dict:
    """Remove a product from the checkout session.

    Args:
        tool_context: The tool context for the current request.
        product_id: Product ID or SKU.

    Returns:
        dict: Returns the response from the tool with success or error status.

    """
    checkout_id = _get_current_checkout_id(tool_context)

    if not checkout_id:
        return _create_error_response("A Checkout has not yet been created.")

    try:
        return {
            UCP_CHECKOUT_KEY: (
                store.remove_from_checkout(checkout_id, product_id).model_dump(
                    mode="json"
                )
            ),
            "status": "success",
        }
    except ValueError:
        logging.exception(
            "There was an error removing item from checkout, please retry later."
        )
        return _create_error_response(
            "There was an error removing item from checkout, please retry later."
        )


def update_checkout(tool_context: ToolContext, product_id: str, quantity: int) -> dict:
    """Update the quantity of a product in the checkout session.

    Args:
        tool_context: The tool context for the current request.
        product_id: Product ID or SKU.
        quantity: New quantity for the product.

    Returns:
        dict: Returns the response from the tool with success or error status.

    """
    checkout_id = _get_current_checkout_id(tool_context)
    if not checkout_id:
        return _create_error_response("A Checkout has not yet been created.")

    try:
        return {
            UCP_CHECKOUT_KEY: (
                store.update_checkout(checkout_id, product_id, quantity).model_dump(
                    mode="json"
                )
            ),
            "status": "success",
        }
    except ValueError:
        logging.exception(
            "There was an error updating item in the cart, please retry later."
        )
        return _create_error_response(
            "There was an error updating item in the cart, please retry later."
        )


def get_checkout(tool_context: ToolContext) -> dict:
    """Retrieve a Checkout Session.

    Args:
        tool_context: The tool context for the current request.

    Returns:
        dict: Returns the response from the tool with success or error status.

    """
    checkout_id = _get_current_checkout_id(tool_context)

    if not checkout_id:
        return _create_error_response("A Checkout has not yet been created.")

    checkout = store.get_checkout(checkout_id)
    if checkout is None:
        return _create_error_response("Checkout not found with the given ID.")

    return {
        UCP_CHECKOUT_KEY: checkout.model_dump(mode="json"),
        "status": "success",
    }


def get_latest_order(tool_context: ToolContext) -> dict:
    """Return the latest completed order for the active user session."""
    order_id = tool_context.state.get(ADK_LAST_ORDER_ID)

    order = None
    if isinstance(order_id, str) and order_id.strip():
        order = store.get_order(order_id.strip())

    if order is None:
        order = store.get_latest_order()

    if order is None:
        return {
            "message": (
                "I could not find any completed orders yet. "
                "Complete a checkout first and then ask for your orders."
            ),
            "status": "not_found",
        }

    if order.order and order.order.id:
        tool_context.state[ADK_LAST_ORDER_ID] = order.order.id

    return {
        UCP_CHECKOUT_KEY: order.model_dump(mode="json"),
        "status": "success",
    }


def get_order(tool_context: ToolContext, order_id: str) -> dict:
    """Return a completed order by order ID."""
    order_id = order_id.strip()
    if not order_id:
        return _create_error_response("Order ID is required.")

    order = store.get_order(order_id)
    if order is None:
        return {
            "message": f"Order '{order_id}' was not found.",
            "status": "not_found",
        }

    tool_context.state[ADK_LAST_ORDER_ID] = order_id
    return {
        UCP_CHECKOUT_KEY: order.model_dump(mode="json"),
        "status": "success",
    }


def reserve_on_price_drop(
    tool_context: ToolContext,
    product_id: str,
    target_price: float | int | str | None = None,
    buyer_email: str | None = None,
) -> dict:
    """Create a reservation that triggers when a product reaches a target price."""
    try:
        reservation = store.create_purchase_reservation(
            product_id=product_id,
            condition_type="price_drop",
            buyer_email=buyer_email,
            target_price=target_price,
        )
    except ValueError as exc:
        return _create_error_response(str(exc))

    message = (
        f"Purchase reservation created for {reservation.product_name}. "
        f"Status: {reservation.status}."
    )
    if reservation.target_price:
        message += f" Target price: {reservation.target_price}."

    return {
        "message": message,
        UCP_PURCHASE_RESERVATION_KEY: reservation.model_dump(mode="json"),
        "status": "success",
    }


def reserve_on_restock(
    tool_context: ToolContext,
    product_id: str,
    buyer_email: str | None = None,
) -> dict:
    """Create a reservation that triggers when an out-of-stock item is available again."""
    try:
        reservation = store.create_purchase_reservation(
            product_id=product_id,
            condition_type="back_in_stock",
            buyer_email=buyer_email,
        )
    except ValueError as exc:
        return _create_error_response(str(exc))

    return {
        "message": (
            f"Back-in-stock reservation created for {reservation.product_name}. "
            f"Status: {reservation.status}."
        ),
        UCP_PURCHASE_RESERVATION_KEY: reservation.model_dump(mode="json"),
        "status": "success",
    }


def list_purchase_reservations(
    tool_context: ToolContext,
    buyer_email: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> dict:
    """List reservations that were created for deferred purchases."""
    normalized_status = (
        status.strip().lower()
        if isinstance(status, str) and status.strip()
        else None
    )
    if normalized_status not in {None, "active", "triggered"}:
        return _create_error_response("status must be either 'active' or 'triggered'")

    safe_limit = max(1, min(int(limit), 100))
    reservations = store.list_purchase_reservations(
        buyer_email=buyer_email,
        status=normalized_status,  # type: ignore[arg-type]
        limit=safe_limit,
    )

    if not reservations:
        return {
            "message": "No purchase reservations found yet.",
            UCP_PURCHASE_RESERVATIONS_KEY: [],
            "status": "not_found",
        }

    return {
        "message": f"I found {len(reservations)} purchase reservation(s).",
        UCP_PURCHASE_RESERVATIONS_KEY: [
            reservation.model_dump(mode="json") for reservation in reservations
        ],
        "status": "success",
    }


def update_customer_details(
    tool_context: ToolContext,
    first_name: str,
    last_name: str,
    street_address: str,
    address_locality: str,
    address_region: str,
    postal_code: str,
    address_country: str | None,
    extended_address: str | None = None,
    email: str | None = None,
) -> dict:
    """Add delivery address to the checkout.

    Args:
        tool_context: The tool context for the current request.
        first_name: First name of the recipient.
        last_name: Last name of the recipient.
        street_address: The street address. For example, 1600 Amphitheatre Pkwy.
        address_locality: The locality in which the street address is.
        address_region: The region in which the locality is.
        postal_code: The postal code. For example, 94043.
        address_country: The country.
        extended_address: The extended address of the postal address.
        email: The email address of the recipient.

    Returns:
        dict: Returns the response from the tool with success or error status.

    """
    checkout_id = _get_current_checkout_id(tool_context)

    if not checkout_id:
        return _create_error_response("A Checkout has not yet been created.")

    if not address_country:
        address_country = "US"

    address = PostalAddress(
        street_address=street_address,
        extended_address=extended_address,
        address_locality=address_locality,
        address_region=address_region,
        address_country=address_country,
        postal_code=postal_code,
        first_name=first_name,
        last_name=last_name,
    )

    checkout = store.add_delivery_address(checkout_id, address)

    if email:
        checkout.buyer = Buyer(email=email)

    # invoke start payment tool once the user details are added
    return start_payment(tool_context)


async def complete_checkout(tool_context: ToolContext) -> dict:
    """Process the payment data to complete checkout.

    Args:
        tool_context: The tool context for the current request.

    Returns:
        dict: Returns the response from the tool with success or error status.

    """
    checkout_id = _get_current_checkout_id(tool_context)

    if not checkout_id:
        return _create_error_response("A Checkout has not yet been created.")

    checkout = store.get_checkout(checkout_id)

    if checkout is None:
        return _create_error_response("Checkout not found for the current session.")

    payment_data: dict[str, Any] = tool_context.state.get(ADK_PAYMENT_STATE)

    if payment_data is None:
        return {
            "message": (
                "Payment Data is missing. Click 'Confirm Purchase' "
                "to complete the purchase."
            ),
            "status": "requires_more_info",
        }

    try:
        task = mpp.process_payment(
            payment_data[UCP_PAYMENT_DATA_KEY],
            payment_data[UCP_RISK_SIGNALS_KEY],
        )

        if task is None:
            return _create_error_response("Failed to receive a valid response from MPP")

        if task.status is not None and task.status.state == TaskState.completed:
            payment_instrument = payment_data.get(UCP_PAYMENT_DATA_KEY)
            checkout.payment.selected_instrument_id = payment_instrument.root.id
            checkout.payment.instruments = [payment_instrument]

            response = store.place_order(checkout_id)
            # clear completed checkout from state
            tool_context.state[ADK_USER_CHECKOUT_ID] = None
            if response.order and response.order.id:
                tool_context.state[ADK_LAST_ORDER_ID] = response.order.id
            return {
                UCP_CHECKOUT_KEY: response.model_dump(mode="json"),
                "status": "success",
            }
        else:
            return _create_error_response(
                get_message_text(task.status.message)  # type: ignore
            )
    except Exception:
        logging.exception("There was an error completing the checkout.")
        return _create_error_response(
            "Sorry, there was an error completing the checkout, please try again."
        )


def start_payment(tool_context: ToolContext) -> dict:
    """Ask for required information to proceed with the payment.

    Args:
        tool_context: The tool context for the current request.

    Returns:
        dict: checkout object

    """
    checkout_id = _get_current_checkout_id(tool_context)

    if not checkout_id:
        return _create_error_response("A Checkout has not yet been created.")

    result = store.start_payment(checkout_id)
    if isinstance(result, str):
        return {"message": result, "status": "requires_more_info"}
    else:
        tool_context.actions.skip_summarization = True
        return {
            UCP_CHECKOUT_KEY: result.model_dump(mode="json"),
            "status": "success",
        }


def _get_current_checkout_id(tool_context: ToolContext) -> str | None:
    """Return the current checkout ID from the tool context state.

    Args:
        tool_context: The tool context for the current request.

    Returns:
        str | None: The checkout ID if present, else None.

    """
    return tool_context.state.get(ADK_USER_CHECKOUT_ID)


def after_tool_modifier(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: ToolContext,
    tool_response: dict,
) -> dict | None:
    """Modify the tool response before returning to the agent.

    Args:
        tool: The tool that was executed.
        args: The arguments passed to the tool.
        tool_context: The tool context for the current request.
        tool_response: The response returned by the tool.

    Returns:
        dict | None: The modified tool response, or None.

    """
    extensions = tool_context.state.get(ADK_EXTENSIONS_STATE_KEY, [])
    # add typed data responses to the state
    ucp_response_keys = [
        UCP_CHECKOUT_KEY,
        "a2a.product_results",
        UCP_PURCHASE_RESERVATION_KEY,
        UCP_PURCHASE_RESERVATIONS_KEY,
    ]
    if UcpExtension.URI in extensions and any(
        key in tool_response for key in ucp_response_keys
    ):
        tool_context.state[ADK_LATEST_TOOL_RESULT] = tool_response

    return None


def modify_output_after_agent(
    callback_context: CallbackContext,
) -> types.Content | None:
    """Modify the agent's output before returning to the user.

    Args:
        callback_context: The callback context for the agent run.

    Returns:
        types.Content | None: The modified agent output, or None.

    """
    # add the UCP tool responses as agent output
    latest_result = callback_context.state.get(ADK_LATEST_TOOL_RESULT)
    if latest_result:
        return types.Content(
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        response={"result": latest_result}
                    )
                )
            ],
            role="model",
        )

    return None


root_agent = Agent(
    name="shopper_agent",
    model=get_configured_model_name(),
    description="Agent to help with shopping",
    instruction=(
        "You are a helpful shopping agent. Always complete user requests by"
        " invoking the available tools instead of only replying with text."
        " If the message includes an explicit action payload with an 'action'"
        " field (for example add_to_checkout, update_checkout, start_payment,"
        " update_customer_details, complete_checkout, reserve_on_price_drop,"
        " reserve_on_restock), call the matching tool immediately with the"
        " provided arguments. Never echo the raw JSON action back to the user."
        " If the user asks to add or remove items,"
        " update the checkout accordingly. If they ask to replace items, call"
        " remove_from_checkout and add_to_checkout to apply the change."
        " If the user asks for order status, their latest order, or asks to"
        " view an order by ID, call get_latest_order or get_order."
        " If they ask to buy later when cheaper or when available again, call"
        " reserve_on_price_drop or reserve_on_restock."
        " When payment data is already present in session state and the user"
        " asks to complete checkout, call complete_checkout."
    ),
    tools=[
        search_shopping_catalog,
        add_to_checkout,
        remove_from_checkout,
        update_checkout,
        get_checkout,
        get_latest_order,
        get_order,
        reserve_on_price_drop,
        reserve_on_restock,
        list_purchase_reservations,
        start_payment,
        update_customer_details,
        complete_checkout,
    ],
    after_tool_callback=after_tool_modifier,
    after_agent_callback=modify_output_after_agent,
)

"""Generated routes for UCP server."""

from typing import Annotated, Any

import dependencies
from fastapi import APIRouter
from fastapi import Body
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Path
import models
from routes import ucp_implementation
from services.checkout_service import CheckoutService
import ucp_sdk.models.schemas.shopping.checkout_create_req
import ucp_sdk.models.schemas.shopping.checkout_resp
import ucp_sdk.models.schemas.shopping.checkout_update_req
import ucp_sdk.models.schemas.shopping.order
from ucp_sdk.models.schemas.shopping.ap2_mandate import Ap2CompleteRequest

router = APIRouter()


@router.post(
  "/checkout-sessions",
  response_model=ucp_sdk.models.schemas.shopping.checkout_resp.CheckoutResponse,
  status_code=201,
  operation_id="create_checkout",
  summary="Create Checkout",
)
async def create_checkout(
  body: Annotated[
    ucp_sdk.models.schemas.shopping.checkout_create_req.CheckoutCreateRequest,
    Body(...),
  ],
  common_headers: Annotated[
    dependencies.CommonHeaders, Depends(dependencies.common_headers)
  ],
  idempotency_key: Annotated[str, Depends(dependencies.idempotency_header)],
  checkout_service: Annotated[
    CheckoutService, Depends(dependencies.get_checkout_service)
  ],
):
  """Create Checkout."""
  req_dict = body.model_dump(exclude_unset=True, by_alias=True)
  unified_req = models.UnifiedCheckoutCreateRequest(**req_dict)
  return await ucp_implementation.create_checkout(
    unified_req, common_headers, idempotency_key, checkout_service
  )


@router.get(
  "/checkout-sessions/{id}",
  response_model=ucp_sdk.models.schemas.shopping.checkout_resp.CheckoutResponse,
  status_code=200,
  operation_id="get_checkout",
  summary="Get Checkout",
)
async def get_checkout(
  id: Annotated[str, Path(...)],
  common_headers: Annotated[
    dependencies.CommonHeaders, Depends(dependencies.common_headers)
  ],
  checkout_service: Annotated[
    CheckoutService, Depends(dependencies.get_checkout_service)
  ],
):
  """Get Checkout."""
  return await ucp_implementation.get_checkout(id, common_headers, checkout_service)


@router.put(
  "/checkout-sessions/{id}",
  response_model=ucp_sdk.models.schemas.shopping.checkout_resp.CheckoutResponse,
  status_code=200,
  operation_id="update_checkout",
  summary="Update Checkout",
)
async def update_checkout(
  id: Annotated[str, Path(...)],
  body: Annotated[
    ucp_sdk.models.schemas.shopping.checkout_update_req.CheckoutUpdateRequest,
    Body(...),
  ],
  common_headers: Annotated[
    dependencies.CommonHeaders, Depends(dependencies.common_headers)
  ],
  idempotency_key: Annotated[str, Depends(dependencies.idempotency_header)],
  checkout_service: Annotated[
    CheckoutService, Depends(dependencies.get_checkout_service)
  ],
):
  """Update Checkout."""
  req_dict = body.model_dump(exclude_unset=True, by_alias=True)
  unified_req = models.UnifiedCheckoutUpdateRequest(**req_dict)
  return await ucp_implementation.update_checkout(
    id, unified_req, common_headers, idempotency_key, checkout_service
  )


@router.post(
  "/checkout-sessions/{id}/complete",
  response_model=ucp_sdk.models.schemas.shopping.checkout_resp.CheckoutResponse,
  status_code=200,
  operation_id="complete_checkout",
  summary="Complete Checkout",
)
async def complete_checkout(
  id: Annotated[str, Path(...)],
  body: Annotated[dict[str, Any], Body(...)],
  common_headers: Annotated[
    dependencies.CommonHeaders, Depends(dependencies.common_headers)
  ],
  idempotency_key: Annotated[str, Depends(dependencies.idempotency_header)],
  checkout_service: Annotated[
    CheckoutService, Depends(dependencies.get_checkout_service)
  ],
):
  """Complete Checkout."""
  payment_data = body.get("payment_data") or body.get("paymentData")
  risk_signals = body.get("risk_signals") or body.get("riskSignals") or {}
  ap2_payload = body.get("ap2")

  if payment_data is None:
    raise HTTPException(
      status_code=422,
      detail="Missing required field 'payment_data' in request body.",
    )

  ap2 = (
    Ap2CompleteRequest.model_validate(ap2_payload)
    if isinstance(ap2_payload, dict)
    else None
  )

  return await ucp_implementation.complete_checkout(
    checkout_id=id,
    payment_data=payment_data,
    risk_signals=risk_signals,
    common_headers=common_headers,
    idempotency_key=idempotency_key,
    checkout_service=checkout_service,
    ap2=ap2,
  )


@router.post(
  "/checkout-sessions/{id}/cancel",
  response_model=ucp_sdk.models.schemas.shopping.checkout_resp.CheckoutResponse,
  status_code=200,
  operation_id="cancel_checkout",
  summary="Cancel Checkout",
)
async def cancel_checkout(
  id: Annotated[str, Path(...)],
  common_headers: Annotated[
    dependencies.CommonHeaders, Depends(dependencies.common_headers)
  ],
  idempotency_key: Annotated[str, Depends(dependencies.idempotency_header)],
  checkout_service: Annotated[
    CheckoutService, Depends(dependencies.get_checkout_service)
  ],
):
  """Cancel Checkout."""
  result = await ucp_implementation.cancel_checkout(
    id, common_headers, idempotency_key, checkout_service
  )
  return result.model_dump(mode="json", by_alias=True)


@router.post(
  "/webhooks/partners/{partner_id}/events/order",
  response_model=dict,
  status_code=200,
  operation_id="order_event_webhook",
  summary="Order Event Webhook",
)
async def order_event_webhook(
  partner_id: Annotated[str, Path(...)],
  body: Annotated[ucp_sdk.models.schemas.shopping.order.Order, Body(...)],
  signature: Annotated[None, Depends(dependencies.verify_signature)],
  checkout_service: Annotated[
    CheckoutService, Depends(dependencies.get_checkout_service)
  ],
):
  """Order Event Webhook."""
  return await ucp_implementation.order_event_webhook(
    partner_id, body, signature, checkout_service
  )

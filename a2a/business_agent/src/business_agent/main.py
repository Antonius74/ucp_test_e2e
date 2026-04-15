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

import asyncio
import functools
import html
import json
import logging
import os

from pathlib import Path
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard
import click
from dotenv import load_dotenv
from google.adk.models.registry import LLMRegistry
from starlette.applications import Starlette
from starlette.responses import FileResponse
from starlette.responses import HTMLResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
import uvicorn

from .agent import get_configured_model_name
from .agent import root_agent as business_agent
from .agent import store
from .agent_executor import ADKAgentExecutor

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())


def _requires_google_api_key(model_name: str) -> bool:
    """Return whether this model requires GOOGLE_API_KEY."""
    normalized = model_name.strip().lower()
    return normalized.startswith("gemini") or normalized.startswith("gemma-")


def make_sync(func):
    """Wrap an async function to run synchronously.

    Args:
        func: The async function to wrap.





    Returns:
        The wrapped synchronous function.


    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


@click.command()
@click.option("--host", default="localhost")
@click.option("--port", default=10999)
@make_sync
async def run(host, port):
    """Run the A2A business agent server.

    Args:
        host: The host to bind to.
        port: The port to listen on.

    """
    model_name = get_configured_model_name()
    if model_name.startswith("ollama/") or model_name.startswith("ollama_chat/"):
        os.environ.setdefault("OLLAMA_API_BASE", "http://127.0.0.1:11434")

    if _requires_google_api_key(model_name) and not os.getenv("GOOGLE_API_KEY"):
        logger.error(
            "GOOGLE_API_KEY must be set when BUSINESS_AGENT_MODEL is %s",
            model_name,
        )
        exit(1)

    try:
        LLMRegistry.resolve(model_name)
    except ValueError:
        logger.exception(
            "Invalid BUSINESS_AGENT_MODEL=%s. Check installed dependencies and model name.",
            model_name,
        )
        exit(1)

    base_path = Path(__file__).parent
    card_path = base_path / "data" / "agent_card.json"
    with card_path.open(encoding="utf-8") as f:
        data = json.load(f)
    agent_card = AgentCard.model_validate(data)

    task_store = InMemoryTaskStore()

    request_handler = DefaultRequestHandler(
        agent_executor=ADKAgentExecutor(
            agent=business_agent,
            extensions=agent_card.capabilities.extensions or [],
        ),
        task_store=task_store,
    )

    a2a_app = A2AStarletteApplication(
        agent_card=agent_card, http_handler=request_handler
    )
    routes = a2a_app.routes()

    async def order_page(request):
        order_id = request.path_params.get("order_id")
        if not isinstance(order_id, str):
            return HTMLResponse("<h1>Invalid order ID</h1>", status_code=400)

        order = store.get_order(order_id)
        if order is None:
            return HTMLResponse(
                f"<h1>Order {html.escape(order_id)} not found</h1>",
                status_code=404,
            )

        order_json = json.dumps(order.model_dump(mode="json"), indent=2)
        content = f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Order {html.escape(order_id)}</title>
    <style>
      body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        margin: 0;
        padding: 24px;
        background: #f5f8fc;
        color: #0f172a;
      }}
      .card {{
        max-width: 960px;
        margin: 0 auto;
        background: #fff;
        border: 1px solid #dbe4ef;
        border-radius: 14px;
        padding: 20px;
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
      }}
      h1 {{
        margin-top: 0;
      }}
      pre {{
        overflow: auto;
        background: #f1f5fb;
        border: 1px solid #d8e2f0;
        border-radius: 10px;
        padding: 12px;
      }}
    </style>
  </head>
  <body>
    <div class="card">
      <h1>Order {html.escape(order_id)}</h1>
      <p>This page is served by the A2A business agent backend.</p>
      <pre>{html.escape(order_json)}</pre>
    </div>
  </body>
</html>
"""
        return HTMLResponse(content)

    async def orders_page(request):
        limit_param = request.query_params.get("limit", "20")
        try:
            limit = max(1, min(int(limit_param), 100))
        except ValueError:
            limit = 20

        buyer_email = request.query_params.get("buyer_email")
        orders = store.list_orders(
            buyer_email=buyer_email if buyer_email else None,
            limit=limit,
        )

        order_links: list[str] = []
        for order in orders:
            order_id = order.order.id if order.order and order.order.id else None
            if not order_id:
                continue
            total_amount = next(
                (
                    total.amount
                    for total in order.totals
                    if total.type == "total"
                ),
                0,
            )
            order_links.append(
                (
                    f'<li><a href="/orders/{html.escape(order_id)}">'
                    f"{html.escape(order_id)}</a> - {order.status} - "
                    f"{order.currency} {(total_amount / 100):.2f}</li>"
                )
            )

        links_markup = (
            "<ul>" + "".join(order_links) + "</ul>"
            if order_links
            else "<p>No completed orders found.</p>"
        )
        filters_text = (
            f"Filtered by buyer_email={html.escape(buyer_email)}"
            if buyer_email
            else "Showing all in-memory completed orders"
        )

        content = f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Orders</title>
    <style>
      body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        margin: 0;
        padding: 24px;
        background: #f5f8fc;
        color: #0f172a;
      }}
      .card {{
        max-width: 960px;
        margin: 0 auto;
        background: #fff;
        border: 1px solid #dbe4ef;
        border-radius: 14px;
        padding: 20px;
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
      }}
    </style>
  </head>
  <body>
    <div class="card">
      <h1>Completed Orders</h1>
      <p>{filters_text}</p>
      {links_markup}
    </div>
  </body>
</html>
"""
        return HTMLResponse(content)

    async def checkout_page(request):
        checkout_id = request.path_params.get("checkout_id")
        if not isinstance(checkout_id, str):
            return HTMLResponse("<h1>Invalid checkout ID</h1>", status_code=400)

        checkout = store.get_checkout(checkout_id)
        if checkout is None:
            return HTMLResponse(
                f"<h1>Checkout {html.escape(checkout_id)} not found</h1>",
                status_code=404,
            )

        checkout_json = json.dumps(checkout.model_dump(mode="json"), indent=2)
        content = f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Checkout {html.escape(checkout_id)}</title>
    <style>
      body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        margin: 0;
        padding: 24px;
        background: #f5f8fc;
        color: #0f172a;
      }}
      .card {{
        max-width: 960px;
        margin: 0 auto;
        background: #fff;
        border: 1px solid #dbe4ef;
        border-radius: 14px;
        padding: 20px;
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
      }}
      h1 {{
        margin-top: 0;
      }}
      pre {{
        overflow: auto;
        background: #f1f5fb;
        border: 1px solid #d8e2f0;
        border-radius: 10px;
        padding: 12px;
      }}
    </style>
  </head>
  <body>
    <div class="card">
      <h1>Checkout {html.escape(checkout_id)}</h1>
      <p>This page is served by the A2A business agent backend.</p>
      <pre>{html.escape(checkout_json)}</pre>
    </div>
  </body>
</html>
"""
        return HTMLResponse(content)

    routes.extend(
        [
            Route("/checkouts/{checkout_id}", checkout_page),
            Route("/orders", orders_page),
            Route("/orders/{order_id}", order_page),
            Route(
                "/.well-known/ucp",
                lambda _: FileResponse(base_path / "data" / "ucp.json"),
            ),
            Mount(
                "/images",
                app=StaticFiles(directory=str(base_path / "data" / "images")),
                name="images",
            ),
        ]
    )
    app = Starlette(routes=routes)

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    run()

/*
 * Copyright 2026 UCP Authors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
import type { Checkout } from "../types";

interface OrderHistoryProps {
  orders: Checkout[];
}

function resolveOrderUrl(order: Checkout): string | undefined {
  const orderId = order.order?.id || order.order_id;
  if (!orderId) {
    return undefined;
  }

  const permalink = order.order?.permalink_url || order.order_permalink_url;
  if (!permalink) {
    return `/api/orders/${orderId}`;
  }
  if (permalink.includes("example.com")) {
    return `/api/orders/${orderId}`;
  }
  if (permalink.startsWith("/orders/")) {
    return window.location.port === "3000" ? `/api${permalink}` : permalink;
  }
  return permalink;
}

function formatCurrency(cents: number, currency: string): string {
  const symbol = currency === "EUR" ? "EUR " : "$";
  return `${symbol}${(cents / 100).toFixed(2)}`;
}

function getGrandTotal(order: Checkout): number {
  return order.totals.find((t) => t.type === "total")?.amount || 0;
}

export default function OrderHistory({ orders }: OrderHistoryProps) {
  if (!orders.length) {
    return null;
  }

  return (
    <div className="mt-3 w-full max-w-4xl rounded-xl border border-slate-200 bg-white p-4 shadow-lg">
      <h3 className="mb-3 border-b border-slate-200 pb-2 text-md font-bold text-slate-800">
        Order History
      </h3>
      <div className="space-y-3">
        {orders.map((order) => {
          const orderId = order.order?.id || order.order_id || `checkout-${order.id}`;
          const orderUrl = resolveOrderUrl(order);
          const itemCount = order.line_items.reduce(
            (sum, lineItem) => sum + lineItem.quantity,
            0
          );

          return (
            <div
              key={orderId}
              className="rounded-lg border border-slate-200 bg-slate-50 p-3"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="font-semibold text-slate-800">{orderId}</div>
                <div className="text-sm text-slate-600">
                  {itemCount} item(s) -{" "}
                  <span className="font-semibold text-slate-800">
                    {formatCurrency(getGrandTotal(order), order.currency)}
                  </span>
                </div>
              </div>
              <div className="mt-1 text-sm text-slate-600">
                Status: {order.status}
              </div>
              {orderUrl && (
                <a
                  href={orderUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-2 inline-block rounded bg-blue-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-blue-700"
                >
                  View order
                </a>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

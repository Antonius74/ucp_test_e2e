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
import type React from "react";
import { useState } from "react";
import GooglePayButton from "./GooglePayButton";

import type {
  Checkout,
  CheckoutItem,
  GooglePayTokenizedCard,
  WalletType,
} from "../types";

interface CheckoutProps {
  checkout: Checkout;
  onCheckout?: () => void;
  onCompletePayment?: (checkout: Checkout) => void;
  onOpenCardPayment?: (checkout: Checkout) => void;
  onWalletPayment?: (checkout: Checkout, wallet: WalletType) => void;
  onGooglePayAuthorized?: (
    checkout: Checkout,
    payload: GooglePayTokenizedCard
  ) => Promise<void> | void;
  onGooglePayError?: (message: string) => void;
}

const CheckoutComponent: React.FC<CheckoutProps> = ({
  checkout,
  onCheckout,
  onCompletePayment,
  onOpenCardPayment,
  onWalletPayment,
  onGooglePayAuthorized,
  onGooglePayError,
}) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const itemsToShow = isExpanded
    ? checkout.line_items
    : checkout.line_items.slice(0, 5);

  const formatCurrency = (amount: number, currency: string) => {
    const currencySymbol = currency === "EUR" ? "€" : "$";
    return `${currencySymbol}${(amount / 100).toFixed(2)}`;
  };

  const getTotal = (type: string) => {
    return checkout.totals.find((t) => t.type === type);
  };

  const getItemTotal = (lineItem: CheckoutItem) => {
    return lineItem.totals.find((t) => t.type === "total");
  };

  const grandTotal = getTotal("total");
  const isReadyForPayment = checkout.status === "ready_for_complete";
  const orderPermalink = checkout.order?.permalink_url;
  const legacyExampleDomain = "example.com";
  const orderFallbackPath = checkout.order?.id
    ? `/api/orders/${checkout.order.id}`
    : undefined;
  const orderUrl =
    orderPermalink && orderPermalink.includes(legacyExampleDomain)
      ? orderFallbackPath
      : orderPermalink && orderPermalink.startsWith("/orders/")
        ? (window.location.port === "3000"
            ? `/api${orderPermalink}`
            : orderPermalink)
        : orderPermalink;

  return (
    <div className="flex w-full my-3 justify-start">
      <div className="w-full max-w-3xl rounded-xl border border-slate-200 bg-white p-4 shadow-lg">
        <h3 className="mb-3 flex items-center border-b border-slate-200 pb-2 text-md font-bold text-slate-800">
          <svg
            role="img"
            aria-label="Checkout"
            xmlns="http://www.w3.org/2000/svg"
            className="h-6 w-6 mr-2"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 11-4 0 2 2 0 014 0z"
            />
          </svg>
          {checkout.status === "completed"
            ? "Order Confirmed"
            : "Checkout Summary"}
        </h3>
        {checkout.order?.id && (
          <p className="space-y-2 border-b border-slate-200 pb-3 pt-3 text-sm">
            Order ID: {checkout.order.id}
          </p>
        )}
        {checkout.status === "completed" && (
          <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
            Payment completed and order confirmed through UCP checkout flow.
            Use the button below to view your order details page.
          </div>
        )}
        <div className="pt-3 space-y-3">
          {itemsToShow.map((lineItem: CheckoutItem) => (
            <div key={lineItem.id} className="flex items-center text-sm">
              <img
                src={lineItem.item.image_url}
                alt={lineItem.item.id}
                className="w-16 h-16 object-cover rounded-md mr-4"
              />
              <div className="flex-grow">
                <p className="font-semibold text-slate-700">
                  {lineItem.item.title}
                </p>
                <p className="text-slate-500">Qty: {lineItem.quantity}</p>
              </div>
              <p className="pl-2 font-medium text-slate-800">
                {formatCurrency(
                  getItemTotal(lineItem).amount,
                  checkout.currency
                )}
              </p>
            </div>
          ))}
        </div>
        {checkout.line_items.length > 5 && (
          <div className="mt-3">
            <button
              type="button"
              onClick={() => setIsExpanded(!isExpanded)}
              className="w-full text-center text-sm text-blue-600 hover:underline"
            >
              {isExpanded
                ? "Show less"
                : `Show ${checkout.line_items.length - 5} more items`}
            </button>
          </div>
        )}
        <div className="mt-4 space-y-2 border-t border-slate-200 pt-3 text-sm">
          {checkout.totals
            .filter((t) => t.type !== "total" && t.amount > 0)
            .map((total) => (
              <div
                key={total.type}
                className="flex justify-between items-center"
              >
                <span className="text-slate-600">{total.display_text}</span>
                <span className="font-medium text-slate-800">
                  {formatCurrency(total.amount, checkout.currency)}
                </span>
              </div>
            ))}
        </div>
        {grandTotal && (
          <div className="mt-4 border-t border-slate-200 pt-3">
            <div className="flex justify-between items-center font-bold text-md">
              <span>{grandTotal.display_text}</span>
              <span>
                {formatCurrency(grandTotal.amount, checkout.currency)}
              </span>
            </div>
          </div>
        )}
        <p className="mt-3 text-center text-xs text-slate-400">
          Checkout ID: {checkout.id}
        </p>
        {checkout.status !== "completed" && (
          <div className="mt-4 flex flex-wrap items-center justify-start gap-3 border-t border-slate-200 pt-4">
            {!isReadyForPayment && onCheckout && (
              <button
                type="button"
                onClick={onCheckout}
                className="rounded bg-blue-600 px-4 py-2 text-sm font-bold text-white hover:bg-blue-700"
              >
                Start Payment
              </button>
            )}
            {isReadyForPayment && (
              <>
                {onOpenCardPayment && (
                  <button
                    type="button"
                    onClick={() => onOpenCardPayment?.(checkout)}
                    className="h-10 min-w-[150px] rounded-md bg-blue-700 px-4 text-sm font-semibold text-white transition hover:bg-blue-800"
                  >
                    Paga con Carta
                  </button>
                )}
                {onWalletPayment && (
                  <button
                    type="button"
                    onClick={() => onWalletPayment(checkout, "apple_pay")}
                    className="h-10 min-w-[150px] rounded-md border border-slate-300 bg-white px-4 text-sm font-semibold text-slate-800 transition hover:bg-slate-50"
                  >
                    Paga con Apple
                  </button>
                )}
                {onGooglePayAuthorized ? (
                  <GooglePayButton
                    totalPrice={(
                      (grandTotal?.amount || 0) / 100
                    ).toFixed(2)}
                    currencyCode={checkout.currency || "EUR"}
                    onAuthorized={(payload) =>
                      onGooglePayAuthorized(checkout, payload)
                    }
                    onError={onGooglePayError}
                  />
                ) : (
                  <button
                    type="button"
                    disabled
                    className="h-10 min-w-[150px] rounded-md border border-slate-300 bg-slate-100 px-4 text-sm font-semibold text-slate-500"
                  >
                    Google Pay unavailable
                  </button>
                )}
              </>
            )}
          </div>
        )}
        {orderUrl && (
          <a
            href={orderUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="block mt-4 bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded text-center"
          >
            View Your Order
          </a>
        )}
      </div>
    </div>
  );
};

export default CheckoutComponent;

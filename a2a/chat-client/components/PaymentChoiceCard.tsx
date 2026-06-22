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
import GooglePayButton from "./GooglePayButton";
import type {
  Checkout,
  GooglePayLifecycleEvent,
  GooglePayTokenizedCard,
  WalletType,
} from "../types";

interface PaymentChoiceCardProps {
  checkout: Checkout;
  onOpenCardPayment?: (checkout: Checkout) => Promise<void> | void;
  onWalletPayment?: (checkout: Checkout, wallet: WalletType) => Promise<void> | void;
  onGooglePayAuthorized?: (
    checkout: Checkout,
    payload: GooglePayTokenizedCard
  ) => Promise<void> | void;
  onGooglePayLifecycleEvent?: (
    checkout: Checkout,
    event: GooglePayLifecycleEvent
  ) => void;
  onGooglePayError?: (message: string) => void;
}

function totalAmount(checkout: Checkout): number {
  return checkout.totals.find((total) => total.type === "total")?.amount || 0;
}

const PaymentChoiceCard: React.FC<PaymentChoiceCardProps> = ({
  checkout,
  onOpenCardPayment,
  onWalletPayment,
  onGooglePayAuthorized,
  onGooglePayLifecycleEvent,
  onGooglePayError,
}) => {
  const total = totalAmount(checkout);
  const currency = checkout.currency || "EUR";

  return (
    <div className="mt-4 w-full max-w-3xl rounded-lg border border-slate-200 bg-white p-4 shadow-lg">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-bold uppercase tracking-wide text-slate-500">
            Payment method
          </h3>
          <p className="mt-1 text-lg font-semibold text-slate-900">
            Choose how to pay in this chat
          </p>
        </div>
        <div className="rounded-md bg-slate-100 px-3 py-2 text-sm font-semibold text-slate-700">
          {new Intl.NumberFormat("it-IT", {
            style: "currency",
            currency,
          }).format(total / 100)}
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-3">
        {onOpenCardPayment && (
          <button
            type="button"
            onClick={() => onOpenCardPayment(checkout)}
            className="h-11 rounded-md bg-blue-700 px-4 text-sm font-semibold text-white transition hover:bg-blue-800"
          >
            Carta
          </button>
        )}

        {onWalletPayment && (
          <button
            type="button"
            onClick={() => onWalletPayment(checkout, "apple_pay")}
            className="h-11 rounded-md border border-slate-300 bg-white px-4 text-sm font-semibold text-slate-900 transition hover:bg-slate-50"
          >
            Apple Pay
          </button>
        )}

        {onGooglePayAuthorized && (
          <GooglePayButton
            totalPrice={(total / 100).toFixed(2)}
            currencyCode={currency}
            onAuthorized={(payload) => onGooglePayAuthorized(checkout, payload)}
            onLifecycleEvent={(event) =>
              onGooglePayLifecycleEvent?.(checkout, event)
            }
            onError={onGooglePayError}
          />
        )}
      </div>
    </div>
  );
};

export default PaymentChoiceCard;

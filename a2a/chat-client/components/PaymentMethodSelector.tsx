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
import type { PaymentMethod } from "../types";

interface PaymentMethodSelectorProps {
  paymentMethods: PaymentMethod[];
  onSelect: (selectedMethod: string) => void;
  title?: string;
  onAddNewCard?: () => void;
}

const PaymentMethodSelector: React.FC<PaymentMethodSelectorProps> = ({
  paymentMethods,
  onSelect,
  title,
  onAddNewCard,
}) => {
  const [selectedMethod, setSelectedMethod] = useState<string | null>(null);

  const formatMethodLabel = (method: PaymentMethod): string => {
    if (method.display_label) {
      return method.display_label;
    }
    if (method.wallet_provider === "google_pay") {
      return "Google Pay";
    }
    if (method.wallet_provider === "apple_pay") {
      return "Apple Pay";
    }
    return `${method.brand.toUpperCase()} ending in ${method.last_digits}`;
  };

  const handleContinue = () => {
    if (selectedMethod) {
      onSelect(selectedMethod);
    }
  };

  return (
    <div className="mt-3 w-full max-w-3xl rounded-xl border border-slate-200 bg-white p-4 shadow-lg">
      <h3 className="mb-3 text-lg font-bold text-slate-800">
        {title || "Select a Payment Method"}
      </h3>
      <div className="space-y-2 mb-4">
        {paymentMethods.map((method) => {
          const isSavedCard = method.id.startsWith("saved_");
          return (
          <label
            key={method.id}
            className="flex cursor-pointer items-center rounded-md p-2 hover:bg-slate-100"
          >
            <input
              type="radio"
              name="paymentMethod"
              value={method.id}
              checked={selectedMethod === method.id}
              onChange={() => setSelectedMethod(method.id)}
              className="form-radio h-4 w-4 text-blue-600"
            />
            <span className="ml-3 text-slate-700">
              {formatMethodLabel(method)}
              {isSavedCard && (
                <span className="ml-2 rounded bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
                  Saved
                </span>
              )}
            </span>
          </label>
          );
        })}
      </div>
      <button
        type="button"
        onClick={handleContinue}
        disabled={!selectedMethod}
        className="block w-full rounded-md bg-blue-600 py-2 text-center text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-400"
      >
        Continue
      </button>
      {onAddNewCard && (
        <button
          type="button"
          onClick={onAddNewCard}
          className="mt-2 block w-full rounded-md border border-slate-300 bg-white py-2 text-center text-slate-800 transition-colors hover:bg-slate-50"
        >
          Aggiungi nuova carta
        </button>
      )}
    </div>
  );
};

export default PaymentMethodSelector;

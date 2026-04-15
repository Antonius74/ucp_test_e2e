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
}

const PaymentMethodSelector: React.FC<PaymentMethodSelectorProps> = ({
  paymentMethods,
  onSelect,
}) => {
  const [selectedMethod, setSelectedMethod] = useState<string | null>(null);

  const handleContinue = () => {
    if (selectedMethod) {
      onSelect(selectedMethod);
    }
  };

  return (
    <div className="mt-3 w-full max-w-3xl rounded-xl border border-slate-200 bg-white p-4 shadow-lg">
      <h3 className="mb-3 text-lg font-bold text-slate-800">
        Select a Payment Method
      </h3>
      <div className="space-y-2 mb-4">
        {paymentMethods.map((method) => (
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
              {method.brand.toUpperCase()} ending in {method.last_digits}
            </span>
          </label>
        ))}
      </div>
      <button
        type="button"
        onClick={handleContinue}
        disabled={!selectedMethod}
        className="block w-full rounded-md bg-blue-600 py-2 text-center text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-400"
      >
        Continue
      </button>
    </div>
  );
};

export default PaymentMethodSelector;

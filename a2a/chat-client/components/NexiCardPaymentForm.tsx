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
import { useMemo, useState } from "react";
import type { Checkout, NexiCardPaymentRequest } from "../types";

interface NexiCardPaymentFormProps {
  checkout: Checkout;
  defaultEmail?: string | null;
  onSubmit: (request: NexiCardPaymentRequest) => Promise<void> | void;
}

function formatCardNumber(input: string): string {
  const digits = input.replace(/\D/g, "").slice(0, 19);
  return digits.replace(/(\d{4})(?=\d)/g, "$1 ").trim();
}

function formatExpiry(input: string): string {
  const digits = input.replace(/\D/g, "").slice(0, 4);
  if (digits.length < 3) {
    return digits;
  }
  return `${digits.slice(0, 2)}/${digits.slice(2)}`;
}

function isLuhnValid(cardNumber: string): boolean {
  const digits = cardNumber.replace(/\D/g, "");
  if (digits.length < 13 || digits.length > 19) {
    return false;
  }
  let sum = 0;
  let shouldDouble = false;
  for (let i = digits.length - 1; i >= 0; i -= 1) {
    let digit = Number.parseInt(digits.charAt(i), 10);
    if (shouldDouble) {
      digit *= 2;
      if (digit > 9) {
        digit -= 9;
      }
    }
    sum += digit;
    shouldDouble = !shouldDouble;
  }
  return sum % 10 === 0;
}

function detectBrand(cardNumber: string): string {
  const digits = cardNumber.replace(/\D/g, "");
  if (/^4/.test(digits)) return "visa";
  if (/^5[1-5]/.test(digits) || /^2(2[2-9]|[3-7])/.test(digits))
    return "mastercard";
  if (/^3[47]/.test(digits)) return "amex";
  return "card";
}

function parseExpiry(expiry: string): { month: number; year: number } | null {
  const match = expiry.match(/^(\d{2})\/(\d{2})$/);
  if (!match) {
    return null;
  }
  const month = Number.parseInt(match[1], 10);
  const year2 = Number.parseInt(match[2], 10);
  if (Number.isNaN(month) || Number.isNaN(year2) || month < 1 || month > 12) {
    return null;
  }
  return { month, year: 2000 + year2 };
}

const NexiCardPaymentForm: React.FC<NexiCardPaymentFormProps> = ({
  checkout,
  defaultEmail,
  onSubmit,
}) => {
  const [cardholderName, setCardholderName] = useState("");
  const [email, setEmail] = useState(defaultEmail || "");
  const [cardNumber, setCardNumber] = useState("");
  const [expiry, setExpiry] = useState("");
  const [cvc, setCvc] = useState("");
  const [saveCardForFuture, setSaveCardForFuture] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const totalAmount = checkout.totals.find((t) => t.type === "total")?.amount ?? 0;
  const currency = checkout.currency || "EUR";
  const payLabel = useMemo(
    () =>
      new Intl.NumberFormat("it-IT", {
        style: "currency",
        currency,
      }).format(totalAmount / 100),
    [currency, totalAmount]
  );
  const brand = detectBrand(cardNumber);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isSubmitting) return;

    const trimmedName = cardholderName.trim();
    const trimmedEmail = email.trim();
    const normalizedCard = cardNumber.replace(/\D/g, "");
    const normalizedCvc = cvc.replace(/\D/g, "");
    const parsedExpiry = parseExpiry(expiry);

    if (!trimmedName) {
      setError("Please enter the cardholder name.");
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)) {
      setError("Please enter a valid email.");
      return;
    }
    if (!isLuhnValid(normalizedCard)) {
      setError("Card number is not valid.");
      return;
    }
    if (!parsedExpiry) {
      setError("Expiry must be in MM/YY format.");
      return;
    }
    if (normalizedCvc.length < 3 || normalizedCvc.length > 4) {
      setError("CVC must be 3 or 4 digits.");
      return;
    }

    const now = new Date();
    const currentMonth = now.getMonth() + 1;
    const currentYear = now.getFullYear();
    if (
      parsedExpiry.year < currentYear ||
      (parsedExpiry.year === currentYear && parsedExpiry.month < currentMonth)
    ) {
      setError("Card is expired.");
      return;
    }

    setError(null);
    setIsSubmitting(true);
    try {
      await onSubmit({
        checkoutId: checkout.id,
        cardholderName: trimmedName,
        email: trimmedEmail,
        cardNumber: normalizedCard,
        expiryMonth: parsedExpiry.month,
        expiryYear: parsedExpiry.year,
        cvc: normalizedCvc,
        saveCardForFuture,
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="mt-3 w-full max-w-xl rounded-2xl border border-slate-200 bg-white p-0 shadow-xl">
      <div className="flex items-center justify-between rounded-t-2xl border-b border-slate-200 bg-gradient-to-r from-slate-50 to-blue-50 px-5 py-4">
        <div>
          <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">
            Secure Card Payment
          </p>
          <h3 className="text-lg font-bold text-slate-900">Pay {payLabel}</h3>
        </div>
        <img
          src="/images/nexi-xpay.svg"
          alt="Nexi XPay"
          className="h-10 w-auto"
        />
      </div>

      <form className="space-y-4 p-5" onSubmit={handleSubmit}>
        <div className="space-y-1">
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Cardholder name
          </label>
          <input
            type="text"
            value={cardholderName}
            onChange={(e) => setCardholderName(e.target.value)}
            placeholder="Mario Rossi"
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
            autoComplete="cc-name"
          />
        </div>

        <div className="space-y-1">
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Email
          </label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="name@example.com"
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
            autoComplete="email"
          />
        </div>

        <div className="space-y-1">
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Card number
          </label>
          <div className="relative">
            <input
              type="text"
              inputMode="numeric"
              value={cardNumber}
              onChange={(e) => setCardNumber(formatCardNumber(e.target.value))}
              placeholder="4242 4242 4242 4242"
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 pr-20 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
              autoComplete="cc-number"
            />
            <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              {brand}
            </span>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Expiry
            </label>
            <input
              type="text"
              inputMode="numeric"
              value={expiry}
              onChange={(e) => setExpiry(formatExpiry(e.target.value))}
              placeholder="MM/YY"
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
              autoComplete="cc-exp"
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              CVC
            </label>
            <input
              type="password"
              inputMode="numeric"
              value={cvc}
              onChange={(e) => setCvc(e.target.value.replace(/\D/g, "").slice(0, 4))}
              placeholder="123"
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
              autoComplete="cc-csc"
            />
          </div>
        </div>

        {error && (
          <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
            {error}
          </p>
        )}

        <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={saveCardForFuture}
            onChange={(event) => setSaveCardForFuture(event.target.checked)}
            className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
          />
          Save this card for future payments
        </label>

        <div className="flex items-center justify-between gap-3 border-t border-slate-200 pt-3">
          <p className="text-xs text-slate-500">
            Encrypted checkout powered by Nexi XPay simulation.
          </p>
          <button
            type="submit"
            disabled={isSubmitting}
            className="rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-wait disabled:bg-blue-400"
          >
            {isSubmitting ? "Processing..." : `Pay ${payLabel}`}
          </button>
        </div>
      </form>
    </div>
  );
};

export default NexiCardPaymentForm;

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
import { useEffect, useMemo, useRef, useState } from "react";
import type { Checkout, PaymentInstrument } from "../types";

interface NexiCardPaymentFormProps {
  checkout: Checkout;
  defaultEmail?: string | null;
  onSubmit: (instrument: PaymentInstrument) => Promise<void> | void;
}

interface NexiHostedField {
  type?: string;
  id?: string;
  src?: string;
  class?: string;
}

interface NexiBuildSessionResponse {
  sessionId: string;
  securityToken?: string;
  fields?: NexiHostedField[];
  hfsdkUrl?: string;
  nexiDomain?: string;
}

interface NexiOperation {
  operationId?: string;
  paymentCircuit?: string;
  paymentInstrumentInfo?: string;
}

interface NexiFinalizeResponse {
  state?: string;
  url?: string;
  operation?: NexiOperation;
}

interface NexiBuildFlowEvent {
  sessionId?: string;
  url?: string;
  operation?: NexiOperation;
  fieldSet?: {
    fields?: NexiHostedField[];
  };
  errorCode?: string;
}

interface NexiBuildInstance {
  confirmData: (loader?: () => void) => void;
}

interface NexiBuildOptions {
  onBuildSuccess?: (evtData: NexiBuildFlowEvent) => void;
  onBuildError?: (evtData: NexiBuildFlowEvent) => void;
  onConfirmError?: (evtData: NexiBuildFlowEvent) => void;
  onBuildFlowStateChange?: (
    evtData: NexiBuildFlowEvent,
    state: string
  ) => void;
}

type NexiBuildConstructor = new (options: NexiBuildOptions) => NexiBuildInstance;

declare global {
  interface Window {
    Build?: NexiBuildConstructor;
  }
}

const HFSDK_SCRIPT_ID = "nexi-hfsdk";

function loadScript(scriptId: string, src: string): Promise<void> {
  const existing = document.getElementById(scriptId) as HTMLScriptElement | null;
  if (existing) {
    return Promise.resolve();
  }

  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.id = scriptId;
    script.src = src;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Failed to load script: ${src}`));
    document.head.appendChild(script);
  });
}

function mapNexiOperationToInstrument(operation: NexiOperation): PaymentInstrument {
  const operationId = operation.operationId || crypto.randomUUID();
  const paymentCircuitRaw = (operation.paymentCircuit || "CARD").toLowerCase();
  const paymentCircuit = paymentCircuitRaw.replace(/[^a-z0-9]+/g, "_") || "card";
  const maskedInfo = operation.paymentInstrumentInfo || "****0000";
  const last4Match = maskedInfo.match(/(\d{4})$/);
  const last_digits = last4Match ? last4Match[1] : "0000";

  return {
    id: `nexi_build_${operationId}`,
    type: "card",
    brand: paymentCircuit,
    last_digits,
    expiry_month: 12,
    expiry_year: new Date().getFullYear() + 2,
    handler_id: "example_payment_provider",
    handler_name: "example.payment.provider",
    credential: {
      type: "nexi_build_operation",
      token: `nexi_build_${operationId}`,
    },
  };
}

const NexiCardPaymentForm: React.FC<NexiCardPaymentFormProps> = ({
  checkout,
  defaultEmail,
  onSubmit,
}) => {
  const [error, setError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string>(
    "Initializing Nexi secure payment..."
  );
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [paymentMethodFields, setPaymentMethodFields] = useState<NexiHostedField[]>([]);
  const [cardFields, setCardFields] = useState<NexiHostedField[]>([]);
  const [sessionId, setSessionId] = useState<string>("");
  const [email, setEmail] = useState(defaultEmail || "");
  const [saveCardForFuture, setSaveCardForFuture] = useState(false);

  const buildRef = useRef<NexiBuildInstance | null>(null);
  const hasMountedRef = useRef(false);

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

  useEffect(() => {
    if (hasMountedRef.current) {
      return;
    }
    hasMountedRef.current = true;

    async function initializeNexiBuild() {
      setIsLoading(true);
      setError(null);
      try {
        const createSessionResponse = await fetch("/api/nexi/build-session", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            checkoutId: checkout.id,
            amount: totalAmount,
            currency,
          }),
        });

        const sessionPayload =
          (await createSessionResponse.json()) as NexiBuildSessionResponse & {
            error?: string;
            details?: unknown;
          };

        if (!createSessionResponse.ok) {
          const details =
            sessionPayload.details && typeof sessionPayload.details === "object"
              ? ` ${JSON.stringify(sessionPayload.details)}`
              : "";
          throw new Error(
            (sessionPayload.error || "Unable to initialize Nexi payment session.") +
              details
          );
        }

        if (!sessionPayload.sessionId) {
          throw new Error("Nexi sessionId missing in /orders/build response.");
        }

        const hfsdkUrl =
          sessionPayload.hfsdkUrl ||
          `${sessionPayload.nexiDomain || "https://xpaysandbox.nexigroup.com"}/monetaweb/resources/hfsdk.js`;

        await loadScript(HFSDK_SCRIPT_ID, hfsdkUrl);

        if (!window.Build) {
          throw new Error("Nexi Build SDK is not available after script load.");
        }

        setSessionId(sessionPayload.sessionId);
        setPaymentMethodFields(
          (sessionPayload.fields || []).filter(
            (field) => field.class === "CARD" || field.id === "PAY_WITH_CARD"
          )
        );

        buildRef.current = new window.Build({
          onBuildSuccess: () => {
            setError(null);
          },
          onBuildError: (evtData) => {
            const code = evtData?.errorCode ? ` (${evtData.errorCode})` : "";
            setError(`Nexi validation error${code}.`);
            setIsSubmitting(false);
          },
          onConfirmError: (evtData) => {
            const code = evtData?.errorCode ? ` (${evtData.errorCode})` : "";
            setError(`Nexi confirm error${code}.`);
            setIsSubmitting(false);
          },
          onBuildFlowStateChange: async (evtData, state) => {
            if (state === "CARD_DATA_COLLECTION") {
              setStatusMessage("Insert card details in secure Nexi fields.");
              setCardFields(evtData?.fieldSet?.fields || []);
              setIsSubmitting(false);
              return;
            }

            if (state === "READY_FOR_PAYMENT") {
              setStatusMessage("Card data confirmed. Finalizing payment...");
              try {
                const finalizeResponse = await fetch(
                  "/api/nexi/finalize-payment",
                  {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ sessionId: evtData?.sessionId || sessionPayload.sessionId }),
                  }
                );
                const finalizePayload =
                  (await finalizeResponse.json()) as NexiFinalizeResponse & {
                    error?: string;
                    details?: unknown;
                  };

                if (!finalizeResponse.ok) {
                  throw new Error(
                    finalizePayload.error ||
                      "Nexi finalize_payment request failed."
                  );
                }

                if (
                  finalizePayload.state === "REDIRECTED_TO_EXTERNAL_DOMAIN" &&
                  finalizePayload.url
                ) {
                  setStatusMessage(
                    "3DS authentication required. Opening Nexi challenge..."
                  );
                  window.open(finalizePayload.url, "_blank", "noopener,noreferrer");
                  setIsSubmitting(false);
                  return;
                }

                if (
                  finalizePayload.state === "PAYMENT_COMPLETE" &&
                  finalizePayload.operation
                ) {
                  const instrument = mapNexiOperationToInstrument(
                    finalizePayload.operation
                  );
                  await onSubmit(instrument);
                  setIsSubmitting(false);
                  return;
                }

                throw new Error("Unexpected Nexi finalize state.");
              } catch (finalizeError) {
                setError(
                  finalizeError instanceof Error
                    ? finalizeError.message
                    : "Unable to finalize Nexi payment."
                );
                setIsSubmitting(false);
              }
              return;
            }

            if (state === "PAYMENT_COMPLETE" && evtData?.operation) {
              const instrument = mapNexiOperationToInstrument(evtData.operation);
              await onSubmit(instrument);
              setIsSubmitting(false);
            }
          },
        });

        setStatusMessage("Select card and continue with Nexi secure fields.");
      } catch (setupError) {
        setError(
          setupError instanceof Error
            ? setupError.message
            : "Unable to initialize Nexi payment."
        );
      } finally {
        setIsLoading(false);
      }
    }

    void initializeNexiBuild();
  }, [checkout.id, currency, onSubmit, totalAmount]);

  const handleConfirmPayment = () => {
    setError(null);
    setIsSubmitting(true);
    setStatusMessage("Confirming card data with Nexi...");
    try {
      if (!buildRef.current) {
        throw new Error("Nexi Build SDK not initialized.");
      }
      buildRef.current.confirmData(() => {
        setIsSubmitting(true);
      });
    } catch (confirmError) {
      setError(
        confirmError instanceof Error
          ? confirmError.message
          : "Unable to confirm payment."
      );
      setIsSubmitting(false);
    }
  };

  return (
    <div className="mt-3 w-full max-w-3xl rounded-2xl border border-slate-200 bg-white p-0 shadow-xl">
      <div className="flex items-center justify-between rounded-t-2xl border-b border-slate-200 bg-gradient-to-r from-slate-50 to-blue-50 px-5 py-4">
        <div>
          <p className="text-[11px] uppercase tracking-[0.12em] text-slate-500">
            Nexi XPay Build v3
          </p>
          <h3 className="text-lg font-bold text-slate-900">Pay {payLabel}</h3>
        </div>
        <img
          src="/images/nexi-xpay.svg"
          alt="Nexi XPay"
          className="h-10 w-auto"
        />
      </div>

      <div className="space-y-4 p-5">
        <p className="rounded-md border border-blue-100 bg-blue-50 px-3 py-2 text-sm text-blue-700">
          {statusMessage}
        </p>

        <div className="space-y-1">
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Email for receipt
          </label>
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="name@example.com"
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
            autoComplete="email"
          />
        </div>

        {paymentMethodFields.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Select payment method
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              {paymentMethodFields.map((field, index) => (
                <iframe
                  key={`${field.id || "method"}-${index}`}
                  src={field.src}
                  title={field.id || `Nexi Method ${index + 1}`}
                  className="h-14 w-full rounded-md border border-slate-200"
                />
              ))}
            </div>
          </div>
        )}

        {cardFields.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Card details (secure Nexi iframes)
            </p>
            <div className="grid gap-2 md:grid-cols-2">
              {cardFields.map((field, index) => (
                <iframe
                  key={`${field.id || "card"}-${index}`}
                  src={field.src}
                  title={field.id || `Nexi Card Field ${index + 1}`}
                  className="h-12 w-full rounded-md border border-slate-200"
                />
              ))}
            </div>
          </div>
        )}

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
            Session ID: {sessionId || "pending"}
          </p>
          <button
            type="button"
            onClick={handleConfirmPayment}
            disabled={isLoading || isSubmitting}
            className="rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-blue-700 disabled:cursor-wait disabled:bg-blue-400"
          >
            {isLoading
              ? "Loading Nexi..."
              : isSubmitting
                ? "Processing..."
                : `Pay ${payLabel}`}
          </button>
        </div>
      </div>
    </div>
  );
};

export default NexiCardPaymentForm;

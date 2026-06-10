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
  warnings?: Array<{
    code?: string;
    description?: string;
  }>;
  details?: {
    errors?: Array<{
      code?: string;
      description?: string;
    }>;
  };
  error?: string;
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
  details?: {
    errors?: Array<{
      code?: string;
      description?: string;
    }>;
  };
  error?: string;
}

interface NexiFieldSet {
  fields?: NexiHostedField[];
  sessionId?: string;
}

interface NexiValidationStatus {
  id?: string;
  valid?: boolean;
}

interface NexiBuildFlowEvent {
  event?: string;
  state?: string;
  id?: string;
  errorMessage?: string;
  validationStatus?: NexiValidationStatus[];
  sessionId?: string;
  url?: string;
  operation?: NexiOperation;
  fieldSet?: NexiFieldSet;
  errorCode?: string;
  // Some SDK builds nest the payload one level deeper under `data`.
  data?: {
    state?: string;
    sessionId?: string;
    operation?: NexiOperation;
    fieldSet?: NexiFieldSet;
  };
}

type NexiWorkflowState =
  | "PAYMENT_METHOD_SELECTION"
  | "CARD_DATA_COLLECTION"
  | "READY_FOR_PAYMENT"
  | "REDIRECTED_TO_EXTERNAL_DOMAIN"
  | "GDI_VERIFICATION"
  | "PAYMENT_COMPLETE";

interface NexiBuildInstance {
  confirmData: (loader?: () => void) => void;
  clickAction: (targetId: string) => void;
}

interface NexiBuildOptions {
  onBuildSuccess?: (
    evtData: NexiBuildFlowEvent,
    state?: NexiWorkflowState
  ) => void;
  onBuildError?: (evtData: NexiBuildFlowEvent) => void;
  onConfirmError?: (evtData: NexiBuildFlowEvent) => void;
  onAllFieldsLoaded?: () => void;
  onComponentUnavailable?: (evtData: NexiBuildFlowEvent) => void;
  onBuildFlowStateChange?: (
    evtData: NexiBuildFlowEvent,
    state: NexiWorkflowState
  ) => void;
}

interface NexiBuildStateResponse {
  state?: string;
  url?: string;
  operation?: NexiOperation;
}

type NexiBuildConstructor = new (options: NexiBuildOptions) => NexiBuildInstance;

declare global {
  interface Window {
    Build?: NexiBuildConstructor;
  }
}

const HFSDK_SCRIPT_ID = "nexi-hfsdk";
const BUILD_GLOBAL_WAIT_TIMEOUT_MS = 4000;
const BUILD_GLOBAL_POLL_INTERVAL_MS = 50;
const AUTO_SELECT_CARD_DELAY_MS = 220;
const AUTO_SELECT_CARD_MAX_ATTEMPTS = 10;
const CARD_FIELDS_WAIT_TIMEOUT_MS = 4000;
const CONFIRM_PAYMENT_TIMEOUT_MS = 12000;
const FINALIZE_POLL_RETRY_DELAY_MS = 1200;
const FINALIZE_POLL_MAX_ATTEMPTS = 3;
const SECURE_CARD_INPUT_IDS = new Set([
  "CARD_PAN",
  "PAN",
  "CARD_NUMBER",
  "EXPIRATION_DATE",
  "CARD_EXPIRY",
  "CVV",
  "CVC",
  "SECURITY_CODE",
]);

function resolveBuildConstructor(): NexiBuildConstructor | undefined {
  if (typeof window === "undefined") {
    return undefined;
  }

  const fromWindow = window.Build;
  if (typeof fromWindow === "function") {
    return fromWindow;
  }

  const fromGlobalThis = (globalThis as { Build?: unknown }).Build;
  if (typeof fromGlobalThis === "function") {
    return fromGlobalThis as NexiBuildConstructor;
  }

  try {
    const fromLexicalScope = Function(
      "return typeof Build === 'function' ? Build : undefined;"
    )() as unknown;
    if (typeof fromLexicalScope === "function") {
      return fromLexicalScope as NexiBuildConstructor;
    }
  } catch {
    // Ignore lexical lookup errors and let the caller handle missing constructor.
  }

  return undefined;
}

function formatNexiErrorMessage(
  fallback: string,
  details?: unknown
): string {
  if (!details || typeof details !== "object") {
    return fallback;
  }

  const detailsRecord = details as Record<string, unknown>;
  const errors = detailsRecord.errors;
  const upstreamCid =
    typeof detailsRecord.upstreamCid === "string"
      ? detailsRecord.upstreamCid
      : null;
  if (Array.isArray(errors) && errors.length > 0) {
    const first = errors[0];
    if (first && typeof first === "object") {
      const firstRecord = first as Record<string, unknown>;
      const codeRaw = firstRecord.code;
      const descriptionRaw = firstRecord.description;
      const code =
        typeof codeRaw === "string" && codeRaw.trim()
          ? `[${codeRaw}] `
          : "";
      const desc =
        typeof descriptionRaw === "string" && descriptionRaw.trim()
          ? descriptionRaw
          : "Unknown Nexi error";
      const cidSuffix = upstreamCid ? ` (cid: ${upstreamCid})` : "";
      return `${code}${desc}${cidSuffix}`;
    }
  }

  const primaryAttempt = detailsRecord.primaryAttempt;
  if (primaryAttempt && typeof primaryAttempt === "object") {
    const nested = formatNexiErrorMessage(fallback, primaryAttempt);
    if (nested !== fallback) {
      return nested;
    }
  }

  const fallbackAttempt = detailsRecord.fallbackAttempt;
  if (fallbackAttempt && typeof fallbackAttempt === "object") {
    const nested = formatNexiErrorMessage(fallback, fallbackAttempt);
    if (nested !== fallback) {
      return nested;
    }
  }

  return fallback;
}

function hasSecureCardInputFields(fields: NexiHostedField[]): boolean {
  return fields.some((field) => {
    const id = (field.id || "").toUpperCase().trim();
    const fieldType = (field.type || "").toUpperCase().trim();
    const fieldClass = (field.class || "").toUpperCase().trim();

    if (SECURE_CARD_INPUT_IDS.has(id)) {
      return true;
    }

    return fieldClass === "CARD_FIELD" || fieldType === "INPUT";
  });
}

function isRenderableCardField(field: NexiHostedField): boolean {
  if (!field.src) {
    return false;
  }
  const id = (field.id || "").toUpperCase().trim();
  const fieldType = (field.type || "").toUpperCase().trim();
  const fieldClass = (field.class || "").toUpperCase().trim();
  if (SECURE_CARD_INPUT_IDS.has(id)) {
    return true;
  }
  if (id === "PRIVACY_CONDITIONS") {
    return true;
  }
  return fieldClass === "CARD_FIELD" || fieldType === "INPUT";
}

function normalizeWorkflowState(state?: string): NexiWorkflowState | undefined {
  if (!state) {
    return undefined;
  }
  const normalized = state.trim().toUpperCase();
  if (
    normalized === "PAYMENT_METHOD_SELECTION" ||
    normalized === "CARD_DATA_COLLECTION" ||
    normalized === "READY_FOR_PAYMENT" ||
    normalized === "REDIRECTED_TO_EXTERNAL_DOMAIN" ||
    normalized === "GDI_VERIFICATION" ||
    normalized === "PAYMENT_COMPLETE"
  ) {
    return normalized;
  }
  return undefined;
}

function waitForBuildGlobal(
  timeoutMs = BUILD_GLOBAL_WAIT_TIMEOUT_MS
): Promise<NexiBuildConstructor> {
  const buildCtor = resolveBuildConstructor();
  if (buildCtor) {
    return Promise.resolve(buildCtor);
  }

  return new Promise((resolve, reject) => {
    const startedAt = Date.now();

    const check = () => {
      const resolvedCtor = resolveBuildConstructor();
      if (resolvedCtor) {
        resolve(resolvedCtor);
        return;
      }
      if (Date.now() - startedAt >= timeoutMs) {
        reject(new Error("Nexi Build SDK global `Build` was not initialized."));
        return;
      }
      window.setTimeout(check, BUILD_GLOBAL_POLL_INTERVAL_MS);
    };

    check();
  });
}

async function loadNexiBuildScript(
  scriptId: string,
  sources: string[]
): Promise<NexiBuildConstructor> {
  const availableCtor = resolveBuildConstructor();
  if (availableCtor) {
    return availableCtor;
  }

  const uniqueSources = sources
    .map((value) => value.trim())
    .filter(Boolean)
    .filter((value, index, arr) => arr.indexOf(value) === index);
  if (uniqueSources.length === 0) {
    throw new Error("No Nexi SDK script source available.");
  }

  let lastError: Error | null = null;
  for (const src of uniqueSources) {
    try {
      const existing = document.getElementById(
        scriptId
      ) as HTMLScriptElement | null;
      if (existing) {
        existing.remove();
      }

      await new Promise<void>((resolve, reject) => {
        const script = document.createElement("script");
        script.id = scriptId;
        script.src = src;
        script.async = true;
        script.crossOrigin = "anonymous";
        script.onload = () => resolve();
        script.onerror = () => reject(new Error(`Failed to load script: ${src}`));
        document.head.appendChild(script);
      });

      return await waitForBuildGlobal();
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
    }
  }

  throw lastError || new Error("Unable to load Nexi Build SDK script.");
}

// Fase 7: l'instrument carta porta il sessionId Nexi reale e l'handler
// "nexi_card"; l'autorizzazione (finalize_payment / build/state) avviene poi
// nella cascata, nel NexiCardGateway. Niente finalize lato client.
// `resume=true` quando la confirmData ha gia' restituito PAYMENT_COMPLETE:
// il gateway si limita a rileggere lo stato invece di rilanciare il finalize.
function buildNexiCardInstrument(
  sessionId: string,
  resume: boolean,
  operation?: NexiOperation
): PaymentInstrument {
  const paymentCircuitRaw = (operation?.paymentCircuit || "CARD").toLowerCase();
  const paymentCircuit = paymentCircuitRaw.replace(/[^a-z0-9]+/g, "_") || "card";
  const maskedInfo = operation?.paymentInstrumentInfo || "****0000";
  const last4Match = maskedInfo.match(/(\d{4})$/);
  const last_digits = last4Match ? last4Match[1] : "0000";

  return {
    id: `nexi_card_${sessionId}`,
    type: "card",
    brand: paymentCircuit,
    last_digits,
    expiry_month: 12,
    expiry_year: new Date().getFullYear() + 2,
    handler_id: "nexi_card",
    handler_name: "nexi.xpay.build.card",
    credential: {
      type: "nexi_build_operation",
      // token non vuoto richiesto dal Merchant; il gateway usa session_id.
      token: sessionId,
      session_id: sessionId,
      resume,
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
  const [cardFields, setCardFields] = useState<NexiHostedField[]>([]);
  const [actionFields, setActionFields] = useState<NexiHostedField[]>([]);
  const [sessionId, setSessionId] = useState<string>("");
  const [email, setEmail] = useState(defaultEmail || "");
  const [saveCardForFuture, setSaveCardForFuture] = useState(false);
  const [isCardFieldsReady, setIsCardFieldsReady] = useState(false);

  const buildRef = useRef<NexiBuildInstance | null>(null);
  const hasMountedRef = useRef(false);
  const preferredCardActionIdRef = useRef("PAY_WITH_CARD");
  const autoCardSelectionTriggeredRef = useRef(false);
  const autoCardSelectionAttemptsRef = useRef(0);
  const cardFieldsReadyRef = useRef(false);
  const confirmTimeoutRef = useRef<number | null>(null);
  const finalizeInFlightRef = useRef(false);
  const directFinalizeTriedRef = useRef(false);
  const isMountedRef = useRef(true);

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
  const renderableCardFields = useMemo(
    () => cardFields.filter(isRenderableCardField),
    [cardFields]
  );

  const clearConfirmTimeout = () => {
    if (confirmTimeoutRef.current !== null) {
      window.clearTimeout(confirmTimeoutRef.current);
      confirmTimeoutRef.current = null;
    }
  };

  const applyCardFieldsState = (fields: NexiHostedField[]) => {
    const nextFields = Array.isArray(fields) ? fields : [];
    const ready = hasSecureCardInputFields(nextFields);
    setCardFields(nextFields);
    cardFieldsReadyRef.current = ready;
    setIsCardFieldsReady(ready);
  };

  // Fase 7: niente finalize lato client. Quando la sessione e' pronta
  // (READY_FOR_PAYMENT) si invia l'instrument con il sessionId: il finalize e
  // l'eventuale 3DS sono gestiti dal NexiCardGateway dentro la cascata.
  const finalizeSessionPayment = async (activeSessionId: string) => {
    if (finalizeInFlightRef.current) {
      return;
    }
    finalizeInFlightRef.current = true;
    try {
      clearConfirmTimeout();
      setStatusMessage("Card data confirmed. Completing payment...");
      await onSubmit(buildNexiCardInstrument(activeSessionId, false));
      setIsSubmitting(false);
    } finally {
      finalizeInFlightRef.current = false;
    }
  };

  const pollBuildStateAfterConfirm = async (activeSessionId: string) => {
    for (let attempt = 0; attempt < FINALIZE_POLL_MAX_ATTEMPTS; attempt += 1) {
      try {
        const stateResponse = await fetch(
          `/api/nexi/build-state?sessionId=${encodeURIComponent(activeSessionId)}`
        );
        const statePayload =
          (await stateResponse.json()) as NexiBuildStateResponse & {
            error?: string;
            details?: unknown;
          };

        if (!stateResponse.ok) {
          throw new Error(
            formatNexiErrorMessage(
              statePayload.error || "Nexi /build/state request failed.",
              statePayload.details
            )
          );
        }

        const workflowState = normalizeWorkflowState(statePayload.state);
        if (workflowState === "READY_FOR_PAYMENT") {
          setStatusMessage("Card data confirmed. Finalizing payment...");
          await finalizeSessionPayment(activeSessionId);
          return;
        }
        if (workflowState === "PAYMENT_COMPLETE" && statePayload.operation) {
          clearConfirmTimeout();
          await onSubmit(
            buildNexiCardInstrument(activeSessionId, true, statePayload.operation)
          );
          setIsSubmitting(false);
          return;
        }
      } catch {
        // Keep retrying for a short window, then surface the final timeout error.
      }

      await new Promise((resolve) => {
        window.setTimeout(resolve, FINALIZE_POLL_RETRY_DELAY_MS);
      });
    }

    if (!isMountedRef.current) {
      return;
    }
    setError("Nexi did not respond in time while confirming card data. Please retry.");
    setIsSubmitting(false);
    setStatusMessage("Insert card details in secure Nexi fields.");
  };

  const triggerCardSelection = (resetAttempts = false) => {
    if (resetAttempts) {
      autoCardSelectionAttemptsRef.current = 0;
    }

    const attempt = () => {
      if (cardFieldsReadyRef.current) {
        return;
      }
      const build = buildRef.current;
      if (!build) {
        return;
      }

      const actionId = preferredCardActionIdRef.current || "PAY_WITH_CARD";
      // eslint-disable-next-line no-console
      console.debug("[Nexi] clickAction attempt", {
        actionId,
        attempt: autoCardSelectionAttemptsRef.current + 1,
      });
      try {
        build.clickAction(actionId);
      } catch {
        // We'll retry a few times because Build frames can register asynchronously.
      }

      autoCardSelectionAttemptsRef.current += 1;
      if (
        !cardFieldsReadyRef.current &&
        autoCardSelectionAttemptsRef.current < AUTO_SELECT_CARD_MAX_ATTEMPTS
      ) {
        window.setTimeout(attempt, AUTO_SELECT_CARD_DELAY_MS);
      } else if (!cardFieldsReadyRef.current) {
        window.setTimeout(() => {
          if (!cardFieldsReadyRef.current) {
            setError(
              "Nexi secure card fields are not available in this browser session. Reload the page and retry."
            );
            setStatusMessage("Waiting for Nexi secure card fields...");
          }
        }, CARD_FIELDS_WAIT_TIMEOUT_MS);
      }
    };

    attempt();
  };

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      if (confirmTimeoutRef.current !== null) {
        window.clearTimeout(confirmTimeoutRef.current);
        confirmTimeoutRef.current = null;
      }
    };
  }, []);

  // DIAGNOSTIC: log every postMessage the page receives so we can see exactly
  // what (if anything) the Nexi iframe sends to the parent window, and its
  // origin/shape. Remove once the card flow works.
  useEffect(() => {
    const rawMessageLogger = (evt: MessageEvent) => {
      // eslint-disable-next-line no-console
      console.debug("[Nexi][raw message]", {
        origin: evt.origin,
        dataType: typeof evt.data,
        data: evt.data,
      });
    };
    window.addEventListener("message", rawMessageLogger);
    return () => window.removeEventListener("message", rawMessageLogger);
  }, []);

  useEffect(() => {
    if (hasMountedRef.current) {
      return;
    }
    hasMountedRef.current = true;

    async function initializeNexiBuild() {
      setIsLoading(true);
      setError(null);
      applyCardFieldsState([]);
      setActionFields([]);
      autoCardSelectionTriggeredRef.current = false;
      autoCardSelectionAttemptsRef.current = 0;
      preferredCardActionIdRef.current = "PAY_WITH_CARD";
      finalizeInFlightRef.current = false;
      clearConfirmTimeout();
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
          throw new Error(
            formatNexiErrorMessage(
              sessionPayload.error ||
                "Unable to initialize Nexi payment session.",
              sessionPayload.details
            )
          );
        }

        if (!sessionPayload.sessionId) {
          throw new Error("Nexi sessionId missing in /orders/build response.");
        }

        const hfsdkUrl =
          sessionPayload.hfsdkUrl ||
          `${sessionPayload.nexiDomain || "https://xpaysandbox.nexigroup.com"}/monetaweb/resources/hfsdk.js`;
        const proxyHfsdkUrl = `/api/nexi/hfsdk.js?source=${encodeURIComponent(
          hfsdkUrl
        )}`;

        // Use only same-origin proxy to avoid browser/network blocks on direct third-party script.
        const BuildCtor = await loadNexiBuildScript(HFSDK_SCRIPT_ID, [
          proxyHfsdkUrl,
        ]);

        setSessionId(sessionPayload.sessionId);
        const cardActionFields = (sessionPayload.fields || []).filter(
          (field) =>
            (field.class === "CARD" || field.id === "PAY_WITH_CARD") &&
            typeof field.src === "string" &&
            field.src.trim().length > 0
        );
        const firstCardAction = cardActionFields.find(
          (field) => typeof field.id === "string" && field.id.trim().length > 0
        );
        if (firstCardAction?.id) {
          preferredCardActionIdRef.current = firstCardAction.id;
        }
        // Step 1 of Build v3: the PAY_WITH_CARD action iframe must be mounted in
        // the DOM so the SDK can register it (READY event). Without it,
        // clickAction("PAY_WITH_CARD") has no target frame and the card-data
        // collection step is never reached.
        setActionFields(cardActionFields);
        const fallbackWarning = (sessionPayload.warnings || []).find(
          (warning) => warning.code === "UCP_FALLBACK_TEST_KEY"
        );
        if (fallbackWarning?.description) {
          setStatusMessage(fallbackWarning.description);
        }

        const extractFieldSetFields = (
          evtData: NexiBuildFlowEvent
        ): NexiHostedField[] =>
          evtData?.fieldSet?.fields ||
          evtData?.data?.fieldSet?.fields ||
          [];

        const handleWorkflowStateChange = async (
          evtData: NexiBuildFlowEvent,
          stateRaw?: string
        ) => {
          // The workflow state can arrive as the SDK callback argument, at the
          // top level of the event, or nested under `data` depending on the SDK
          // build. Try all of them before giving up.
          const state =
            normalizeWorkflowState(stateRaw) ||
            normalizeWorkflowState(evtData?.state) ||
            normalizeWorkflowState(evtData?.data?.state);
          // eslint-disable-next-line no-console
          console.debug("[Nexi] workflow state change", {
            stateRaw,
            resolvedState: state,
            evtData,
          });
          if (!state) {
            return;
          }

          const activeSessionId =
            evtData?.sessionId ||
            evtData?.data?.sessionId ||
            evtData?.fieldSet?.sessionId ||
            evtData?.data?.fieldSet?.sessionId ||
            sessionPayload.sessionId;
          if (state === "PAYMENT_METHOD_SELECTION") {
            setStatusMessage("Opening Nexi secure card fields...");
            applyCardFieldsState([]);
            const stateFieldSet = extractFieldSetFields(evtData);
            const preferredField = stateFieldSet.find(
              (field) =>
                field &&
                (field.id === "PAY_WITH_CARD" || field.class === "CARD")
            );
            if (preferredField?.id) {
              preferredCardActionIdRef.current = preferredField.id;
            }
            autoCardSelectionTriggeredRef.current = true;
            triggerCardSelection(true);
            return;
          }

          if (state === "CARD_DATA_COLLECTION") {
            const stateFields = extractFieldSetFields(evtData);
            applyCardFieldsState(stateFields);
            // NOTE: the PAY_WITH_CARD frame is the session/3DS orchestrator and
            // must stay alive in the DOM (removing it expires the session →
            // HF0003). We only reorder the SDK frame map at confirm time so
            // confirmData() targets a real card field instead of the action.
            if (hasSecureCardInputFields(stateFields)) {
              setStatusMessage("Insert card details in secure Nexi fields.");
            } else {
              setStatusMessage("Select card and continue with Nexi secure fields.");
            }
            setIsSubmitting(false);
            return;
          }

          if (state === "READY_FOR_PAYMENT") {
            setStatusMessage("Card data confirmed. Finalizing payment...");
            try {
              await finalizeSessionPayment(activeSessionId);
            } catch (finalizeError) {
              clearConfirmTimeout();
              setError(
                finalizeError instanceof Error
                  ? finalizeError.message
                  : "Unable to finalize Nexi payment."
              );
              setIsSubmitting(false);
            }
            return;
          }

          const operation = evtData?.operation || evtData?.data?.operation;
          if (state === "PAYMENT_COMPLETE" && operation) {
            clearConfirmTimeout();
            // confirmData ha gia' completato in un solo step: resume=true, il
            // gateway si limita a rileggere lo stato della sessione.
            await onSubmit(buildNexiCardInstrument(activeSessionId, true, operation));
            setIsSubmitting(false);
          }
        };

        buildRef.current = new BuildCtor({
          onBuildSuccess: (evtData, state) => {
            setError(null);
            // Always forward to the handler: the workflow state may not be in the
            // callback argument (the handler re-derives it from the event body).
            void handleWorkflowStateChange(evtData, state);
          },
          onBuildError: (evtData) => {
            // eslint-disable-next-line no-console
            console.debug("[Nexi] onBuildError", evtData);
            clearConfirmTimeout();
            const code = evtData?.errorCode ? ` (${evtData.errorCode})` : "";
            setError(`Nexi validation error${code}.`);
            setIsSubmitting(false);
          },
          onConfirmError: (evtData) => {
            // eslint-disable-next-line no-console
            console.debug("[Nexi] onConfirmError", evtData);
            clearConfirmTimeout();
            const status = Array.isArray(evtData?.validationStatus)
              ? evtData.validationStatus
              : [];
            const invalid = status.filter((entry) => entry?.valid === false);
            const onlyActionInvalid =
              invalid.length > 0 &&
              invalid.every(
                (entry) =>
                  (entry.id || "").toUpperCase() === "PAY_WITH_CARD" ||
                  (entry.id || "").toUpperCase() ===
                    (preferredCardActionIdRef.current || "").toUpperCase()
              );
            const code = evtData?.errorCode ? ` (${evtData.errorCode})` : "";
            // EXPERIMENT: every CARD_FIELD is valid and only the PAY_WITH_CARD
            // action is flagged invalid. The card data may already be saved on
            // the Nexi server, so try finalize_payment directly (it only needs
            // the sessionId). One-shot guard to avoid loops.
            if (
              evtData?.errorCode === "HF0007" &&
              onlyActionInvalid &&
              !directFinalizeTriedRef.current
            ) {
              directFinalizeTriedRef.current = true;
              const activeSessionId =
                evtData?.sessionId || sessionPayload.sessionId;
              // eslint-disable-next-line no-console
              console.debug(
                "[Nexi] HF0007 only on action; trying finalize_payment directly",
                activeSessionId
              );
              setStatusMessage("Finalizing payment directly with Nexi...");
              setIsSubmitting(true);
              void finalizeSessionPayment(activeSessionId).catch(
                (finalizeError) => {
                  // eslint-disable-next-line no-console
                  console.debug("[Nexi] direct finalize failed", finalizeError);
                  setError(
                    finalizeError instanceof Error
                      ? `Direct finalize failed: ${finalizeError.message}`
                      : `Nexi confirm error${code}.`
                  );
                  setIsSubmitting(false);
                }
              );
              return;
            }
            setError(`Nexi confirm error${code}.`);
            setIsSubmitting(false);
          },
          onAllFieldsLoaded: () => {
            // eslint-disable-next-line no-console
            console.debug("[Nexi] onAllFieldsLoaded");
            if (autoCardSelectionTriggeredRef.current) {
              return;
            }
            autoCardSelectionTriggeredRef.current = true;
            setStatusMessage("Opening Nexi secure card fields...");
            window.setTimeout(() => {
              triggerCardSelection(true);
            }, AUTO_SELECT_CARD_DELAY_MS);
          },
          onComponentUnavailable: (evtData) => {
            // eslint-disable-next-line no-console
            console.debug("[Nexi] onComponentUnavailable", evtData);
            // The PAY_WITH_CARD action is intentionally removed once we enter
            // card-data collection, so ignore an unavailable event for it.
            const unavailableId = (evtData?.id || "").toUpperCase();
            if (
              unavailableId === "PAY_WITH_CARD" ||
              unavailableId === (preferredCardActionIdRef.current || "").toUpperCase()
            ) {
              return;
            }
            const code = evtData?.errorCode ? ` (${evtData.errorCode})` : "";
            setError(
              `Nexi component temporarily unavailable${code}. Check third-party cookies and retry.`
            );
          },
          onBuildFlowStateChange: (evtData, state) => {
            // eslint-disable-next-line no-console
            console.debug("[Nexi] onBuildFlowStateChange (callback)", {
              state,
              evtData,
            });
            void handleWorkflowStateChange(evtData, state);
          },
        });
        // eslint-disable-next-line no-console
        console.debug("[Nexi] Build instance constructed", {
          actionFields: cardActionFields,
          sessionId: sessionPayload.sessionId,
        });

        setStatusMessage("Opening Nexi secure card fields...");
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
    directFinalizeTriedRef.current = false;
    if (!isCardFieldsReady || !hasSecureCardInputFields(cardFields)) {
      setStatusMessage("Waiting for Nexi secure card fields...");
      setError(
        "Secure card fields are not ready yet. Wait a moment and try again."
      );
      setIsSubmitting(false);
      return;
    }
    setIsSubmitting(true);
    setStatusMessage("Confirming card data with Nexi...");
    try {
      if (!buildRef.current) {
        throw new Error("Nexi Build SDK not initialized.");
      }
      if (!sessionId) {
        throw new Error("Nexi session is not ready yet.");
      }
      clearConfirmTimeout();
      const activeSessionId = sessionId;
      confirmTimeoutRef.current = window.setTimeout(() => {
        confirmTimeoutRef.current = null;
        void pollBuildStateAfterConfirm(activeSessionId);
      }, CONFIRM_PAYMENT_TIMEOUT_MS);
      buildRef.current.confirmData(() => {
        setIsSubmitting(true);
      });
    } catch (confirmError) {
      clearConfirmTimeout();
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

        {/* Step 1 of Build v3: the Nexi action button(s) (incl. PAY_WITH_CARD)
            must be rendered VISIBLY so the Nexi iframe app boots, posts READY and
            can be activated (a zero-size/hidden iframe never initializes, so
            clickAction has no effect). Once the secure card fields are ready we
            collapse the button but keep it mounted so the SDK keeps tracking the
            frame. */}
        {actionFields.length > 0 && (
          <div
            className="space-y-2"
            style={
              isCardFieldsReady
                ? { height: 0, overflow: "hidden", margin: 0 }
                : undefined
            }
            aria-hidden={isCardFieldsReady}
          >
            {!isCardFieldsReady && (
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Pay with card
              </p>
            )}
            {actionFields.map((field, index) => (
              <iframe
                key={`nexi-action-${field.id || "card"}-${index}`}
                src={field.src}
                title={field.id || `Nexi action ${index + 1}`}
                className="h-12 w-full rounded-md border border-slate-200"
              />
            ))}
          </div>
        )}

        {renderableCardFields.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Card details (secure Nexi iframes)
            </p>
            <div className="grid gap-2 md:grid-cols-2">
              {renderableCardFields.map((field, index) => (
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
            disabled={isLoading || isSubmitting || !isCardFieldsReady}
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
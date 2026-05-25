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
import { useEffect, useMemo, useRef, useState } from "react";
import type { GooglePayTokenizedCard } from "../types";

type GooglePayEnvironment = "TEST" | "PRODUCTION";

type GooglePayButtonState = "loading" | "ready" | "unavailable";

interface GooglePayButtonProps {
  totalPrice: string;
  currencyCode: string;
  onAuthorized: (payload: GooglePayTokenizedCard) => Promise<void> | void;
  onError?: (message: string) => void;
}

interface GooglePayPaymentData {
  apiVersion?: number;
  apiVersionMinor?: number;
  email?: string;
  paymentMethodData?: {
    description?: string;
    info?: {
      cardNetwork?: string;
      cardDetails?: string;
      cardFundingSource?: string;
    };
    tokenizationData?: {
      token?: string;
      type?: string;
    };
    type?: string;
  };
}

interface GooglePayPaymentsClient {
  isReadyToPay(request: unknown): Promise<{ result: boolean }>;
  loadPaymentData(request: unknown): Promise<GooglePayPaymentData>;
  createButton(options: {
    onClick: () => void;
    buttonColor?: "black" | "white" | "default";
    buttonType?: "pay" | "buy" | "checkout" | "plain";
    buttonLocale?: string;
    buttonSizeMode?: "fill" | "static";
  }): HTMLElement;
}

interface GooglePayApi {
  PaymentsClient: new (options: {
    environment: GooglePayEnvironment;
  }) => GooglePayPaymentsClient;
}

type GooglePayWindow = Window & {
  google?: {
    payments?: {
      api?: GooglePayApi;
    };
  };
};

const GOOGLE_PAY_SCRIPT_ID = "google-pay-web-js";
const GOOGLE_PAY_SCRIPT_SRC = "https://pay.google.com/gp/p/js/pay.js";
const DEFAULT_ALLOWED_AUTH_METHODS = ["PAN_ONLY", "CRYPTOGRAM_3DS"];
const DEFAULT_ALLOWED_CARD_NETWORKS = ["VISA", "MASTERCARD"];

function parseCsvList(value: string | undefined, fallback: string[]): string[] {
  const normalized = (value || "")
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);
  return normalized.length > 0 ? normalized : fallback;
}

function loadGooglePayScript(): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("Google Pay is only available in browser."));
  }

  const gWindow = window as GooglePayWindow;
  if (gWindow.google?.payments?.api?.PaymentsClient) {
    return Promise.resolve();
  }

  return new Promise((resolve, reject) => {
    const existing = document.getElementById(
      GOOGLE_PAY_SCRIPT_ID
    ) as HTMLScriptElement | null;

    if (existing) {
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener(
        "error",
        () => reject(new Error("Failed to load Google Pay script.")),
        { once: true }
      );
      return;
    }

    const script = document.createElement("script");
    script.id = GOOGLE_PAY_SCRIPT_ID;
    script.src = GOOGLE_PAY_SCRIPT_SRC;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () =>
      reject(new Error("Failed to load Google Pay script."));
    document.head.appendChild(script);
  });
}

const GooglePayButton = ({
  totalPrice,
  currencyCode,
  onAuthorized,
  onError,
}: GooglePayButtonProps) => {
  const [state, setState] = useState<GooglePayButtonState>("loading");
  const [isProcessing, setIsProcessing] = useState(false);
  const buttonContainerRef = useRef<HTMLDivElement>(null);
  const paymentsClientRef = useRef<GooglePayPaymentsClient | null>(null);
  const onAuthorizedRef = useRef(onAuthorized);
  const onErrorRef = useRef(onError);

  useEffect(() => {
    onAuthorizedRef.current = onAuthorized;
  }, [onAuthorized]);

  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  const config = useMemo(() => {
    const envMap = (import.meta as unknown as { env?: Record<string, string> })
      .env || {};
    const environment: GooglePayEnvironment =
      envMap.VITE_GOOGLE_PAY_ENV === "PRODUCTION" ? "PRODUCTION" : "TEST";

    return {
      environment,
      merchantId: envMap.VITE_GOOGLE_PAY_MERCHANT_ID || "999999990",
      merchantName: envMap.VITE_GOOGLE_PAY_MERCHANT_NAME || "UCP Demo Merchant",
      gateway: envMap.VITE_GOOGLE_PAY_GATEWAY || "nexigtw",
      gatewayMerchantId:
        envMap.VITE_GOOGLE_PAY_GATEWAY_MERCHANT_ID || "999999990",
      countryCode: envMap.VITE_GOOGLE_PAY_COUNTRY_CODE || "IT",
      allowedAuthMethods: parseCsvList(
        envMap.VITE_GOOGLE_PAY_ALLOWED_AUTH_METHODS,
        DEFAULT_ALLOWED_AUTH_METHODS
      ),
      allowedCardNetworks: parseCsvList(
        envMap.VITE_GOOGLE_PAY_ALLOWED_CARD_NETWORKS,
        DEFAULT_ALLOWED_CARD_NETWORKS
      ),
    };
  }, []);

  const baseCardMethod = useMemo(
    () => ({
      type: "CARD",
      parameters: {
        allowedAuthMethods: config.allowedAuthMethods,
        allowedCardNetworks: config.allowedCardNetworks,
      },
    }),
    [config.allowedAuthMethods, config.allowedCardNetworks]
  );

  const paymentDataRequest = useMemo(
    () => ({
      apiVersion: 2,
      apiVersionMinor: 0,
      allowedPaymentMethods: [
        {
          ...baseCardMethod,
          tokenizationSpecification: {
            type: "PAYMENT_GATEWAY",
            parameters: {
              gateway: config.gateway,
              gatewayMerchantId: config.gatewayMerchantId,
            },
          },
        },
      ],
      merchantInfo:
        config.environment === "PRODUCTION"
          ? {
              merchantId: config.merchantId,
              merchantName: config.merchantName,
            }
          : {
              merchantId: config.merchantId,
              merchantName: config.merchantName,
            },
      transactionInfo: {
        totalPriceStatus: "FINAL",
        totalPrice,
        currencyCode,
        countryCode: config.countryCode,
        checkoutOption: "COMPLETE_IMMEDIATE_PURCHASE",
      },
      emailRequired: true,
    }),
    [
      baseCardMethod,
      config.gateway,
      config.gatewayMerchantId,
      config.merchantId,
      config.merchantName,
      config.countryCode,
      totalPrice,
      currencyCode,
    ]
  );

  const paymentDataRequestRef = useRef(paymentDataRequest);
  useEffect(() => {
    paymentDataRequestRef.current = paymentDataRequest;
  }, [paymentDataRequest]);

  const isProcessingRef = useRef(false);

  useEffect(() => {
    let cancelled = false;

    async function setupGooglePay() {
      try {
        await loadGooglePayScript();
        if (cancelled) {
          return;
        }

        const gWindow = window as GooglePayWindow;
        const ApiCtor = gWindow.google?.payments?.api?.PaymentsClient;
        if (!ApiCtor) {
          throw new Error("Google Pay API unavailable.");
        }

        const client = new ApiCtor({ environment: config.environment });
        paymentsClientRef.current = client;

        const readyToPay = await client.isReadyToPay({
          apiVersion: 2,
          apiVersionMinor: 0,
          allowedPaymentMethods: [baseCardMethod],
        });

        if (cancelled) {
          return;
        }

        if (!readyToPay?.result) {
          setState("unavailable");
          return;
        }

        const container = buttonContainerRef.current;
        if (!container) {
          return;
        }

        container.innerHTML = "";
        const button = client.createButton({
          onClick: async () => {
            const activeClient = paymentsClientRef.current;
            if (!activeClient || isProcessingRef.current) {
              return;
            }
            isProcessingRef.current = true;
            setIsProcessing(true);

            try {
              const paymentData = await activeClient.loadPaymentData(
                paymentDataRequestRef.current
              );
              const token = paymentData.paymentMethodData?.tokenizationData?.token;
              const paymentMethodType = paymentData.paymentMethodData?.type;

              if (!token || !paymentMethodType) {
                throw new Error("Google Pay token is missing.");
              }

              await onAuthorizedRef.current({
                apiVersion: paymentData.apiVersion ?? 2,
                apiVersionMinor: paymentData.apiVersionMinor ?? 0,
                email: paymentData.email,
                paymentMethodData: {
                  description: paymentData.paymentMethodData?.description,
                  info: {
                    cardDetails: paymentData.paymentMethodData?.info?.cardDetails,
                    cardFundingSource:
                      paymentData.paymentMethodData?.info?.cardFundingSource,
                    cardNetwork: paymentData.paymentMethodData?.info?.cardNetwork,
                  },
                  tokenizationData: {
                    token,
                    type:
                      paymentData.paymentMethodData?.tokenizationData?.type ||
                      "PAYMENT_GATEWAY",
                  },
                  type: paymentMethodType,
                },
              });
            } catch (error) {
              console.error("Google Pay payment failed:", error);
              const errorCode =
                error &&
                typeof error === "object" &&
                "statusCode" in error &&
                typeof (error as { statusCode?: unknown }).statusCode === "string"
                  ? (error as { statusCode: string }).statusCode
                  : "";
              if (errorCode === "CANCELED") {
                onErrorRef.current?.("Google Pay payment cancelled.");
              } else {
                onErrorRef.current?.(
                  "Google Pay payment failed. Please try again."
                );
              }
            } finally {
              isProcessingRef.current = false;
              setIsProcessing(false);
            }
          },
          buttonColor: "black",
          buttonType: "pay",
          buttonSizeMode: "fill",
        });

        container.appendChild(button);
        setState("ready");
      } catch (error) {
        console.error("Google Pay setup failed:", error);
        if (!cancelled) {
          setState("unavailable");
        }
      }
    }

    setupGooglePay();
    return () => {
      cancelled = true;
    };
  }, [baseCardMethod, config.environment]);

  if (state === "unavailable") {
    return (
      <button
        type="button"
        disabled
        className="h-10 min-w-[150px] rounded-md border border-slate-300 bg-slate-100 px-4 text-sm font-semibold text-slate-500"
      >
        Google Pay unavailable
      </button>
    );
  }

  return (
    <div className="relative h-10 min-w-[150px]">
      <div ref={buttonContainerRef} className="h-10 min-w-[150px]" />
      {(state === "loading" || isProcessing) && (
        <div className="absolute inset-0 flex items-center justify-center rounded-md border border-slate-300 bg-slate-100 text-xs font-medium text-slate-500">
          {isProcessing ? "Processing..." : "Loading Google Pay..."}
        </div>
      )}
    </div>
  );
};

export default GooglePayButton;

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
import { useEffect, useRef, useState } from "react";
import ChatInput from "./components/ChatInput";
import ChatMessageComponent from "./components/ChatMessage";
import Header from "./components/Header";
import ProtocolDashboard from "./components/ProtocolDashboard";
import { appConfig } from "./config";
import { CredentialProviderProxy } from "./mocks/credentialProviderProxy";

import {
  type ChatMessage,
  type PaymentInstrument,
  type ProtocolExchangeEvent,
  type Product,
  Sender,
  type Checkout,
  type PaymentHandler,
} from "./types";

type RequestPart =
  | { type: "text"; text: string }
  | { type: "data"; data: Record<string, unknown> };

function isToolCallText(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed.startsWith("{") || !trimmed.endsWith("}")) {
    return false;
  }

  const containsToolCallShape =
    trimmed.includes('"name"') &&
    (trimmed.includes('"parameters"') ||
      trimmed.includes('"action"') ||
      trimmed.includes("get_") ||
      trimmed.includes("add_to_checkout") ||
      trimmed.includes("start_payment") ||
      trimmed.includes("complete_checkout"));

  if (containsToolCallShape) {
    return true;
  }

  try {
    const parsed = JSON.parse(trimmed) as Record<string, unknown>;
    return (
      typeof parsed?.name === "string" &&
      (parsed.parameters === undefined ||
        typeof parsed.parameters === "object")
    );
  } catch {
    return /^{"name"\s*:\s*".+"/.test(trimmed);
  }
}

function createChatMessage(
  sender: Sender,
  text: string,
  props: Partial<ChatMessage> = {}
): ChatMessage {
  return {
    id: crypto.randomUUID(),
    sender,
    text,
    ...props,
  };
}

function normalizeWhitespace(text: string): string {
  return text.replace(/\r/g, "").replace(/\n{3,}/g, "\n\n").trim();
}

function stripMarkdownTableRows(text: string): string {
  const lines = text.split("\n");
  const filtered = lines.filter((line) => {
    const trimmed = line.trim();
    if (!trimmed) {
      return true;
    }

    // Remove markdown table rows and separators.
    if (trimmed.startsWith("|") && trimmed.endsWith("|")) {
      return false;
    }
    if (/^[|:\-\s]+$/.test(trimmed) && trimmed.includes("-")) {
      return false;
    }
    return true;
  });

  return normalizeWhitespace(filtered.join("\n"));
}

function formatCatalogNarrative(
  rawText: string,
  products?: Product[]
): string {
  const normalized = normalizeWhitespace(rawText);
  if (!products || products.length === 0) {
    return normalized;
  }

  const withoutTable = stripMarkdownTableRows(normalized);
  const lower = normalized.toLowerCase();
  const looksVerboseCatalog =
    normalized.length > 520 ||
    lower.includes("| product id |") ||
    lower.includes("quick look at what") ||
    lower.includes("all of these items are in stock") ||
    lower.includes("let me know which ones you'd like");

  if (!withoutTable || looksVerboseCatalog) {
    return `I found ${products.length} products for you. Browse the cards below and tap "Add to Checkout" on any item.`;
  }

  return withoutTable;
}

function extractTokens(value: unknown, collector: Set<string>): void {
  if (!value || typeof value !== "object") {
    return;
  }

  if (Array.isArray(value)) {
    for (const item of value) {
      extractTokens(item, collector);
    }
    return;
  }

  const obj = value as Record<string, unknown>;
  for (const [key, nested] of Object.entries(obj)) {
    if (key === "token" && typeof nested === "string") {
      collector.add(nested);
    } else {
      extractTokens(nested, collector);
    }
  }
}

function getPartData(
  part: Record<string, unknown>
): Record<string, unknown> | undefined {
  if (part.data && typeof part.data === "object") {
    return part.data as Record<string, unknown>;
  }
  if (
    part.root &&
    typeof part.root === "object" &&
    (part.root as Record<string, unknown>).data &&
    typeof (part.root as Record<string, unknown>).data === "object"
  ) {
    return (part.root as Record<string, unknown>).data as Record<string, unknown>;
  }
  return undefined;
}

function extractProtocolTrace(
  parts: Record<string, unknown>[]
): Record<string, unknown>[] {
  const trace: Record<string, unknown>[] = [];
  for (const part of parts) {
    const data = getPartData(part);
    const protocolTrace = data?.["a2a.protocol_trace"];
    if (Array.isArray(protocolTrace)) {
      for (const entry of protocolTrace) {
        if (entry && typeof entry === "object") {
          trace.push(entry as Record<string, unknown>);
        }
      }
    }
  }
  return trace;
}

function toHeadersObject(headers: Headers): Record<string, string> {
  const obj: Record<string, string> = {};
  headers.forEach((value, key) => {
    obj[key] = value;
  });
  return obj;
}

function isEmailLike(text: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(text.trim());
}

function deriveNameFromEmail(email: string): {
  firstName: string;
  lastName: string;
} {
  const localPart = email.split("@")[0] || "guest";
  const normalized = localPart.replace(/[^a-zA-Z0-9._-]/g, " ").trim();
  const chunks = normalized
    .split(/[._\-\s]+/)
    .map((chunk) => chunk.trim())
    .filter(Boolean);
  const firstRaw = chunks[0] || "Guest";
  const lastRaw = chunks[1] || "Buyer";
  const toName = (value: string) =>
    value.charAt(0).toUpperCase() + value.slice(1).toLowerCase();
  return {
    firstName: toName(firstRaw),
    lastName: toName(lastRaw),
  };
}

const initialMessage: ChatMessage = createChatMessage(
  Sender.MODEL,
  appConfig.defaultMessage,
  { id: "initial" }
);

/**
 * An example A2A chat client that demonstrates consuming a business's A2A Agent with UCP Extension.
 * Only for demo purposes, not intended for production use.
 */
function App() {
  const [user_email, _setUserEmail] = useState<string | null>(
    "foo@example.com"
  );
  const [messages, setMessages] = useState<ChatMessage[]>([initialMessage]);
  const [isLoading, setIsLoading] = useState(false);
  const [contextId, setContextId] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [protocolEvents, setProtocolEvents] = useState<ProtocolExchangeEvent[]>(
    []
  );
  const [isProtocolDashboardOpen, setIsProtocolDashboardOpen] = useState(true);
  const credentialProvider = useRef(new CredentialProviderProxy());
  const chatContainerRef = useRef<HTMLDivElement>(null);

  // Scroll to the bottom when new messages are added
  // biome-ignore lint/correctness/useExhaustiveDependencies: Scroll when messages change
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop =
        chatContainerRef.current.scrollHeight;
    }
  }, [messages]);

  const appendProtocolEvent = (
    event: Omit<ProtocolExchangeEvent, "id" | "timestamp">
  ) => {
    const nextEvent: ProtocolExchangeEvent = {
      ...event,
      id: crypto.randomUUID(),
      timestamp: new Date().toISOString(),
    };
    setProtocolEvents((prev) => [...prev, nextEvent]);
  };

  const buildCustomerDetailsAction = (
    emailOverride?: string | null
  ): RequestPart[] => {
    const resolvedEmail = (emailOverride || user_email || "buyer@example.com").trim();
    const { firstName, lastName } = deriveNameFromEmail(resolvedEmail);
    return [
      {
        type: "data",
        data: {
          action: "update_customer_details",
          first_name: firstName,
          last_name: lastName,
          street_address: "1 Market St",
          address_locality: "San Francisco",
          address_region: "CA",
          postal_code: "94105",
          address_country: "US",
          email: resolvedEmail,
        },
      },
    ];
  };

  const handleAddToCheckout = (productToAdd: Product) => {
    const actionPayload = JSON.stringify({
      action: "add_to_checkout",
      product_id: productToAdd.productID,
      quantity: 1,
    });
    handleSendMessage(actionPayload, { isUserAction: true });
  };

  const handleStartPayment = () => {
    const updateDetailsParts = buildCustomerDetailsAction();
    handleSendMessage(updateDetailsParts, {
      isUserAction: true,
    });
  };

  const handlePaymentMethodSelection = async (checkout: Checkout) => {
    if (!checkout || !checkout.payment || !checkout.payment.handlers) {
      const errorMessage = createChatMessage(
        Sender.MODEL,
        "Sorry, I couldn't retrieve payment methods."
      );
      setMessages((prev) => [...prev, errorMessage]);
      return;
    }

    //find the handler with id "example_payment_provider"
    const handler = checkout.payment.handlers.find(
      (handler: PaymentHandler) => handler.id === "example_payment_provider"
    );
    if (!handler) {
      const errorMessage = createChatMessage(
        Sender.MODEL,
        "Sorry, I couldn't find the supported payment handler."
      );
      setMessages((prev) => [...prev, errorMessage]);
      return;
    }

    try {
      const paymentResponse =
        await credentialProvider.current.getSupportedPaymentMethods(
          user_email,
          handler.config
        );
      const paymentMethods = paymentResponse.payment_method_aliases;

      const paymentSelectorMessage = createChatMessage(Sender.MODEL, "", {
        paymentMethods,
      });
      setMessages((prev) => [...prev, paymentSelectorMessage]);
    } catch (error) {
      console.error("Failed to resolve mandate:", error);
      const errorMessage = createChatMessage(
        Sender.MODEL,
        "Sorry, I couldn't retrieve payment methods."
      );
      setMessages((prev) => [...prev, errorMessage]);
    }
  };

  const handlePaymentMethodSelected = async (selectedMethod: string) => {
    // Hide the payment selector by removing it from the messages
    setMessages((prev) => prev.filter((msg) => !msg.paymentMethods));

    // Add a temporary user message
    const userActionMessage = createChatMessage(
      Sender.USER,
      `User selected payment method: ${selectedMethod}`,
      { isUserAction: true }
    );
    setMessages((prev) => [...prev, userActionMessage]);

    try {
      if (!user_email) {
        throw new Error("User email is not set.");
      }

      const paymentInstrument =
        await credentialProvider.current.getPaymentToken(
          user_email,
          selectedMethod
        );

      if (!paymentInstrument || !paymentInstrument.credential) {
        throw new Error("Failed to retrieve payment credential");
      }

      const paymentInstrumentMessage = createChatMessage(Sender.MODEL, "", {
        paymentInstrument,
      });
      setMessages((prev) => [...prev, paymentInstrumentMessage]);
    } catch (error) {
      console.error("Failed to process payment mandate:", error);
      const errorMessage = createChatMessage(
        Sender.MODEL,
        "Sorry, I couldn't process the payment. Please try again."
      );
      setMessages((prev) => [...prev, errorMessage]);
    }
  };

  const handleConfirmPayment = async (paymentInstrument: PaymentInstrument) => {
    // Hide the payment confirmation component
    const userActionMessage = createChatMessage(
      Sender.USER,
      `User confirmed payment.`,
      { isUserAction: true }
    );
    // Let handleSendMessage manage the loading indicator
    setMessages((prev) => [
      ...prev.filter((msg) => !msg.paymentInstrument),
      userActionMessage,
    ]);

    try {
      const parts: RequestPart[] = [
        { type: "data", data: { action: "complete_checkout" } },
        {
          type: "data",
          data: {
            "a2a.ucp.checkout.payment_data": paymentInstrument,
            "a2a.ucp.checkout.risk_signals": {
              merchant_id: "merchant_ucp_demo",
              gateway_hint: "mock.ucp.gateway",
              risk_score: 12,
              session_id: crypto.randomUUID(),
            },
          },
        },
      ];

      await handleSendMessage(parts, {
        isUserAction: true,
      });
    } catch (error) {
      console.error("Error confirming payment:", error);
      const errorMessage = createChatMessage(
        Sender.MODEL,
        "Sorry, there was an issue confirming your payment."
      );
      // If handleSendMessage wasn't called, we might need to manually update state
      // In this case, we remove the loading indicator that handleSendMessage would have added
      setMessages((prev) => [...prev.slice(0, -1), errorMessage]); // This assumes handleSendMessage added a loader
      setIsLoading(false); // Ensure loading is stopped on authorization error
    }
  };

  const handleSendMessage = async (
    messageContent: string | RequestPart[],
    options?: { isUserAction?: boolean; headers?: Record<string, string> }
  ) => {
    if (isLoading) return;

    let normalizedMessageContent: string | RequestPart[] = messageContent;
    let userMessageText =
      options?.isUserAction
        ? ""
        : typeof messageContent === "string"
          ? messageContent
          : "Sent complex data";

    const latestCheckout = messages
      .slice()
      .reverse()
      .find((message) => !!message.checkout)?.checkout;
    const shouldAutofillFromEmail =
      typeof messageContent === "string" &&
      isEmailLike(messageContent) &&
      !!latestCheckout &&
      latestCheckout.status !== "completed";

    if (shouldAutofillFromEmail) {
      normalizedMessageContent = buildCustomerDetailsAction(messageContent);
      userMessageText = messageContent;
    }

    const userMessage = createChatMessage(
      Sender.USER,
      userMessageText
    );
    if (userMessage.text) {
      // Only add if there's text
      setMessages((prev) => [...prev, userMessage]);
    }
    setMessages((prev) => [
      ...prev,
      createChatMessage(Sender.MODEL, "", { isLoading: true }),
    ]);
    setIsLoading(true);

    try {
      const requestParts =
        typeof normalizedMessageContent === "string"
          ? [{ type: "text", text: normalizedMessageContent }]
          : normalizedMessageContent;

      const requestParams: {
        message: {
          role: string;
          parts: RequestPart[];
          messageId: string;
          kind: string;
          contextId?: string;
          taskId?: string;
        };
        configuration: {
          historyLength: number;
        };
      } = {
        message: {
          role: "user",
          parts: requestParts,
          messageId: crypto.randomUUID(),
          kind: "message",
        },
        configuration: {
          historyLength: 0,
        },
      };

      if (contextId) {
        requestParams.message.contextId = contextId;
      }
      if (taskId) {
        requestParams.message.taskId = taskId;
      }

      const defaultHeaders = {
        "Content-Type": "application/json",
        "X-A2A-Extensions":
          "https://ucp.dev/specification/reference?v=2026-01-11",
        "UCP-Agent":
          'profile="http://localhost:3000/profile/agent_profile.json"',
      };
      const mergedHeaders = { ...defaultHeaders, ...options?.headers };
      const jsonRpcPayload = {
        jsonrpc: "2.0",
        id: crypto.randomUUID(),
        method: "message/send",
        params: requestParams,
      };

      const outboundTokens = new Set<string>();
      extractTokens(requestParts, outboundTokens);
      appendProtocolEvent({
        direction: "outbound",
        title: "A2A message/send request",
        endpoint: "/api",
        httpMethod: "POST",
        headers: mergedHeaders,
        jsonrpcPayload: jsonRpcPayload,
        contextId: requestParams.message.contextId || null,
        taskId: requestParams.message.taskId || null,
        tokens: [...outboundTokens],
      });

      const response = await fetch("/api", {
        method: "POST",
        headers: mergedHeaders,
        body: JSON.stringify(jsonRpcPayload),
      });

      if (!response.ok || !response.body) {
        throw new Error(`API request failed with status ${response.status}`);
      }

      const data = await response.json();

      // Update context and task IDs from the response for subsequent requests
      if (data.result?.contextId) {
        setContextId(data.result.contextId);
      }
      //if there is a task and it's in one of the active states
      if (
        data.result?.id &&
        data.result?.status?.state in ["working", "submitted", "input-required"]
      ) {
        setTaskId(data.result.id);
      } else {
        //if not reset taskId
        setTaskId(null);
      }

      const combinedBotMessage = createChatMessage(Sender.MODEL, "");
      const textParts: string[] = [];

      const responsePartsRaw =
        data.result?.parts || data.result?.status?.message?.parts || [];
      const responseParts: Record<string, unknown>[] = Array.isArray(
        responsePartsRaw
      )
        ? responsePartsRaw.filter(
            (part: unknown): part is Record<string, unknown> =>
              !!part && typeof part === "object"
          )
        : [];
      const protocolTrace = extractProtocolTrace(responseParts);
      const inboundTokens = new Set<string>();
      extractTokens(data, inboundTokens);
      extractTokens(protocolTrace, inboundTokens);
      appendProtocolEvent({
        direction: "inbound",
        title: "A2A message/send response",
        endpoint: "/api",
        httpMethod: "POST",
        httpStatus: response.status,
        headers: toHeadersObject(response.headers),
        jsonrpcPayload: data,
        contextId: data.result?.contextId || null,
        taskId: data.result?.id || null,
        tokens: [...inboundTokens],
        protocolTrace: protocolTrace.length > 0 ? protocolTrace : undefined,
      });

      for (const part of responseParts) {
        const textValue = part.text;
        if (typeof textValue === "string") {
          if (isToolCallText(textValue)) {
            continue;
          }
          textParts.push(textValue);
          continue;
        }

        const dataPayload = getPartData(part);
        if (dataPayload?.["a2a.product_results"]) {
          // Product results
          const productResults = dataPayload["a2a.product_results"] as {
            results?: Product[];
          };
          combinedBotMessage.products = productResults.results;
        } else if (dataPayload?.["a2a.orders"]) {
          const orders = dataPayload["a2a.orders"] as Checkout[];
          if (Array.isArray(orders)) {
            combinedBotMessage.orders = orders;
          }
        } else if (dataPayload?.["a2a.ucp.checkout"]) {
          // Checkout
          combinedBotMessage.checkout = dataPayload["a2a.ucp.checkout"] as Checkout;
        }
      }

      const rawText = textParts.join("\n");
      combinedBotMessage.text = formatCatalogNarrative(
        rawText,
        combinedBotMessage.products
      );
      if (!combinedBotMessage.text && combinedBotMessage.products?.length) {
        combinedBotMessage.text = `I found ${combinedBotMessage.products.length} products for you.`;
      }

      const newMessages: ChatMessage[] = [];
      const hasContent =
        combinedBotMessage.text ||
        combinedBotMessage.products ||
        combinedBotMessage.orders ||
        combinedBotMessage.checkout;
      if (hasContent) {
        newMessages.push(combinedBotMessage);
      }

      if (newMessages.length > 0) {
        setMessages((prev) => [...prev.slice(0, -1), ...newMessages]);
      } else {
        const fallbackResponse =
          "Sorry, I received a response I couldn't understand.";
        setMessages((prev) => [
          ...prev.slice(0, -1),
          createChatMessage(Sender.MODEL, fallbackResponse),
        ]);
      }
    } catch (error) {
      console.error("Error sending message:", error);
      appendProtocolEvent({
        direction: "inbound",
        title: "A2A transport error",
        endpoint: "/api",
        httpMethod: "POST",
        headers: {},
        jsonrpcPayload: {
          error: error instanceof Error ? error.message : String(error),
        },
      });
      const errorMessage = createChatMessage(
        Sender.MODEL,
        "Sorry, something went wrong. Please try again."
      );
      // Replace the placeholder with the error message
      setMessages((prev) => [...prev.slice(0, -1), errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const lastCheckoutIndex = messages.map((m) => !!m.checkout).lastIndexOf(true);

  return (
    <div className="app-shell flex flex-col h-screen max-h-screen font-sans">
      <Header />
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <section className="flex min-h-0 min-w-0 flex-1 flex-col">
          <main
            ref={chatContainerRef}
            className="chat-scroll flex-grow overflow-y-auto p-4 md:p-6"
          >
            <div className="mx-auto w-full max-w-7xl space-y-2">
              {messages.map((msg, index) => (
                <ChatMessageComponent
                  key={msg.id}
                  message={msg}
                  onAddToCart={handleAddToCheckout}
                  onCheckout={
                    msg.checkout?.status !== "ready_for_complete"
                      ? handleStartPayment
                      : undefined
                  }
                  onSelectPaymentMethod={handlePaymentMethodSelected}
                  onConfirmPayment={handleConfirmPayment}
                  onCompletePayment={
                    msg.checkout?.status === "ready_for_complete"
                      ? handlePaymentMethodSelection
                      : undefined
                  }
                  isLastCheckout={index === lastCheckoutIndex}
                ></ChatMessageComponent>
              ))}
            </div>
          </main>
          <ChatInput onSendMessage={handleSendMessage} isLoading={isLoading} />
        </section>

        <ProtocolDashboard
          events={protocolEvents}
          isOpen={isProtocolDashboardOpen}
          onToggle={() => setIsProtocolDashboardOpen((prev) => !prev)}
          onClear={() => setProtocolEvents([])}
        />
      </div>
    </div>
  );
}

export default App;

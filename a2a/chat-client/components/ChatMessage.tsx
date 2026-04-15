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
import { appConfig } from "@/config";
import {
  type ChatMessage,
  type Checkout,
  type PaymentInstrument,
  type Product,
  Sender,
} from "../types";
import CheckoutComponent from "./Checkout";
import PaymentConfirmationComponent from "./PaymentConfirmation";
import PaymentMethodSelector from "./PaymentMethodSelector";
import OrderHistory from "./OrderHistory";
import PurchaseReservations from "./PurchaseReservations";
import ProductCard from "./ProductCard";
import UserLogo from "./UserLogo";

interface ChatMessageProps {
  message: ChatMessage;
  onAddToCart?: (product: Product) => Promise<void> | void;
  onReservePriceDrop?: (product: Product) => Promise<void> | void;
  onReserveRestock?: (product: Product) => Promise<void> | void;
  onCheckout?: () => void;
  onSelectPaymentMethod?: (selectedMethod: string) => void;
  onConfirmPayment?: (paymentInstrument: PaymentInstrument) => void;
  onCompletePayment?: (checkout: Checkout) => void;
  isLastCheckout?: boolean;
}

function TypingIndicator() {
  return (
    <div className="w-full my-2 justify-start">
      <div className="flex items-center gap-2 mb-1">
        <div className="flex-shrink-0">
          <img alt="logo" src={appConfig.logoUrl} className="w-8 h-8" />
        </div>
        <span className="font-semibold text-slate-700">{appConfig.name}</span>
      </div>
      <div className="agent-bubble ml-10 px-4 py-3 rounded-2xl self-start inline-block">
        <div className="flex items-center space-x-2 h-5">
          <span className="h-2 w-2 bg-slate-400 rounded-full animate-bounce [animation-delay:-0.3s]"></span>
          <span className="h-2 w-2 bg-slate-400 rounded-full animate-bounce [animation-delay:-0.15s]"></span>
          <span className="h-2 w-2 bg-slate-400 rounded-full animate-bounce"></span>
        </div>
      </div>
    </div>
  );
}

function ChatMessageComponent({
  message,
  onAddToCart,
  onReservePriceDrop,
  onReserveRestock,
  onCheckout,
  onSelectPaymentMethod,
  onConfirmPayment,
  onCompletePayment,
  isLastCheckout,
}: ChatMessageProps) {
  const isUser = message.sender === Sender.USER;

  if (message.isLoading) {
    return <TypingIndicator />;
  }

  // User messages are handled separately
  if (isUser) {
    return (
      <div className="flex w-full my-2 items-start gap-2 justify-end">
        <div className="user-bubble max-w-[78%] md:max-w-2xl px-4 py-2 rounded-2xl shadow-sm self-end">
          <div className="whitespace-pre-wrap break-words">{message.text}</div>
        </div>
        <div className="flex-shrink-0 pt-1">
          <UserLogo className="w-8 h-8 text-slate-400" />
        </div>
      </div>
    );
  }

  return (
    <div className="w-full my-2 justify-start">
      <div className="flex items-center gap-2 mb-1">
        <div className="flex-shrink-0">
          <img
            src={appConfig.logoUrl}
            alt={appConfig.name}
            className="w-8 h-8"
          />
        </div>
        <span className="font-semibold text-slate-700">{appConfig.name}</span>
      </div>
      <div className="ml-10 flex-grow min-w-0">
        {message.text && (
          <div className="agent-bubble max-w-[92%] md:max-w-3xl px-4 py-3 rounded-2xl self-start inline-block">
            <div className="break-words whitespace-pre-wrap leading-relaxed">
              {message.text}
            </div>
          </div>
        )}

        {message.paymentMethods && onSelectPaymentMethod && (
          <PaymentMethodSelector
            paymentMethods={message.paymentMethods}
            onSelect={onSelectPaymentMethod}
          />
        )}

        {message.paymentInstrument && onConfirmPayment && (
          <PaymentConfirmationComponent
            paymentInstrument={message.paymentInstrument}
            onConfirm={() => onConfirmPayment(message.paymentInstrument)}
          />
        )}

        {message.products && message.products.length > 0 && (
          <div className="w-full my-3">
            <div className="catalog-grid p-1">
              {message.products.map((product) => (
                <ProductCard
                  key={product.productID}
                  product={product}
                  onAddToCart={onAddToCart}
                  onReservePriceDrop={onReservePriceDrop}
                  onReserveRestock={onReserveRestock}
                />
              ))}
            </div>
          </div>
        )}

        {message.purchaseReservations && message.purchaseReservations.length > 0 && (
          <PurchaseReservations reservations={message.purchaseReservations} />
        )}

        {message.orders && message.orders.length > 0 && (
          <OrderHistory orders={message.orders} />
        )}

        {message.checkout && (
          <CheckoutComponent
            checkout={message.checkout}
            onCheckout={isLastCheckout ? onCheckout : undefined}
            onCompletePayment={isLastCheckout ? onCompletePayment : undefined}
          />
        )}
      </div>
    </div>
  );
}

export default ChatMessageComponent;

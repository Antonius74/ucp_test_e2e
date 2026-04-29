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
export enum Sender {
  USER = "user",
  MODEL = "model",
}

export interface Product {
  productID: string;
  name: string;
  image: string[];
  brand: { name: string };
  offers: {
    price: string;
    priceCurrency: string;
    availability: string;
  };
  url: string;
  description: string;
  size: {
    name: string;
  };
}

export interface Credential {
  type: string;
  token: string;
}

export interface PaymentMethod {
  id: string;
  type: string;
  brand: string;
  last_digits: string;
  expiry_month: number;
  expiry_year: number;
  display_label?: string;
  wallet_provider?: WalletType;
}

export type WalletType = "google_pay" | "apple_pay";

export interface PaymentInstrument extends PaymentMethod {
  handler_id: string;
  handler_name: string;
  credential: Credential;
}

export interface ChatMessage {
  id: string;
  sender: Sender;
  text: string;
  products?: Product[];
  orders?: Checkout[];
  purchaseReservations?: PurchaseReservation[];
  cardPaymentCheckout?: Checkout;
  isLoading?: boolean;
  paymentMethods?: PaymentMethod[];
  paymentMethodsTitle?: string;
  allowAddNewCard?: boolean;
  isUserAction?: boolean;
  checkout?: Checkout;
  paymentInstrument?: PaymentInstrument;
}

export interface NexiCardPaymentRequest {
  checkoutId: string;
  cardholderName: string;
  email: string;
  cardNumber: string;
  expiryMonth: number;
  expiryYear: number;
  cvc: string;
  saveCardForFuture: boolean;
}

export type ProtocolDirection = "outbound" | "inbound";

export interface ProtocolExchangeEvent {
  id: string;
  timestamp: string;
  direction: ProtocolDirection;
  title: string;
  endpoint: string;
  httpMethod: string;
  httpStatus?: number;
  headers: Record<string, string>;
  jsonrpcPayload: unknown;
  contextId?: string | null;
  taskId?: string | null;
  tokens?: string[];
  protocolTrace?: unknown;
}

export interface CheckoutTotal {
  type: string;
  display_text: string;
  amount: number;
}

export interface PurchaseReservation {
  id: string;
  product_id: string;
  product_name: string;
  condition_type: "price_drop" | "back_in_stock";
  status: "active" | "triggered";
  created_at: string;
  trigger_reason?: string | null;
  triggered_at?: string | null;
  buyer_email?: string | null;
  currency: string;
  current_price: string;
  target_price?: string | null;
  current_availability: string;
}

export interface CheckoutItem {
  id: string;
  item: {
    id: string;
    title: string;
    price: number;
    image_url: string;
  };
  quantity: number;
  totals: CheckoutTotal[];
}

export interface PaymentHandler {
  id: string;
  name: string;
  //...other props
}
export interface Payment {
  handlers: PaymentHandler[];
  selected_instrument_id: string;
  instruments: PaymentInstrument[];
}

export interface Checkout {
  id: string;
  line_items: CheckoutItem[];
  currency: string;
  continue_url?: string | null;
  status: string;
  totals: CheckoutTotal[];
  order?: {
    id?: string;
    permalink_url?: string;
  };
  order_id?: string;
  order_permalink_url?: string;
  payment?: Payment;
}

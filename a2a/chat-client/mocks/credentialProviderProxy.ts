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
import type {
  PaymentInstrument,
  PaymentMethod,
  WalletType,
} from "../types";

interface NexiCardTokenizationRequest {
  cardNumber: string;
  expiryMonth: number;
  expiryYear: number;
  saveCardForFuture?: boolean;
}

interface SavedCardRecord extends PaymentMethod {
  saved_at: string;
}

type SavedCardsByEmail = Record<string, SavedCardRecord[]>;

const SAVED_CARDS_STORAGE_KEY = "ucp_saved_payment_methods_v1";

/**
 * A mock CredentialProvider to simulate calls to a remote service for credentials.
 * In a real application, this would make a network request to a provider's service.
 */
export class CredentialProviderProxy {
  handler_id = "example_payment_provider";
  handler_name = "example.payment.provider";

  _getMockPaymentMethods(): { payment_method_aliases: PaymentMethod[] } {
    return {
      payment_method_aliases: [
        {
          id: "instr_1",
          type: "card",
          brand: "amex",
          last_digits: "1111",
          expiry_month: 12,
          expiry_year: 2026,
        },
        {
          id: "instr_2",
          type: "card",
          brand: "visa",
          last_digits: "8888",
          expiry_month: 12,
          expiry_year: 2026,
        },
        {
          id: "instr_3",
          type: "card",
          brand: "mastercard",
          last_digits: "5555",
          expiry_month: 12,
          expiry_year: 2026,
        },
      ],
    };
  }

  _normalizeEmail(user_email: string | null | undefined): string {
    return (user_email || "").trim().toLowerCase();
  }

  _loadSavedCardsByEmail(): SavedCardsByEmail {
    if (typeof window === "undefined") {
      return {};
    }

    try {
      const raw = window.localStorage.getItem(SAVED_CARDS_STORAGE_KEY);
      if (!raw) {
        return {};
      }
      const parsed = JSON.parse(raw) as SavedCardsByEmail;
      if (!parsed || typeof parsed !== "object") {
        return {};
      }
      return parsed;
    } catch (error) {
      console.warn(
        "CredentialProviderProxy: Unable to read saved cards from localStorage.",
        error
      );
      return {};
    }
  }

  _saveSavedCardsByEmail(cardsByEmail: SavedCardsByEmail): void {
    if (typeof window === "undefined") {
      return;
    }

    try {
      window.localStorage.setItem(
        SAVED_CARDS_STORAGE_KEY,
        JSON.stringify(cardsByEmail)
      );
    } catch (error) {
      console.warn(
        "CredentialProviderProxy: Unable to persist saved cards in localStorage.",
        error
      );
    }
  }

  _getSavedPaymentMethods(user_email: string): PaymentMethod[] {
    const normalizedEmail = this._normalizeEmail(user_email);
    if (!normalizedEmail) {
      return [];
    }

    const cardsByEmail = this._loadSavedCardsByEmail();
    const saved = cardsByEmail[normalizedEmail] || [];
    return saved.map(({ saved_at: _savedAt, ...method }) => method);
  }

  async getRegisteredPaymentMethods(
    user_email: string
  ): Promise<{ payment_method_aliases: PaymentMethod[] }> {
    console.log(
      `CredentialProviderProxy: Simulating fetch of registered cards for ${user_email}`
    );
    await new Promise((resolve) => setTimeout(resolve, 350));
    return {
      payment_method_aliases: this._getSavedPaymentMethods(user_email),
    };
  }

  _savePaymentMethodAlias(user_email: string, method: PaymentMethod): void {
    const normalizedEmail = this._normalizeEmail(user_email);
    if (!normalizedEmail) {
      return;
    }

    const cardsByEmail = this._loadSavedCardsByEmail();
    const existing = cardsByEmail[normalizedEmail] || [];
    const deduped = existing.filter(
      (saved) =>
        !(
          saved.brand === method.brand &&
          saved.last_digits === method.last_digits &&
          saved.expiry_month === method.expiry_month &&
          saved.expiry_year === method.expiry_year
        )
    );

    const updated: SavedCardRecord[] = [
      { ...method, saved_at: new Date().toISOString() },
      ...deduped,
    ].slice(0, 8);

    cardsByEmail[normalizedEmail] = updated;
    this._saveSavedCardsByEmail(cardsByEmail);
  }

  _getAllPaymentMethodsForUser(user_email: string): PaymentMethod[] {
    const saved = this._getSavedPaymentMethods(user_email);
    const defaults = this._getMockPaymentMethods().payment_method_aliases;
    const seen = new Set(saved.map((method) => method.id));
    const merged = [...saved];

    for (const method of defaults) {
      if (!seen.has(method.id)) {
        merged.push(method);
      }
    }
    return merged;
  }

  _getWalletPaymentMethods(wallet: WalletType): PaymentMethod[] {
    const baseYear = new Date().getFullYear() + 2;
    if (wallet === "google_pay") {
      return [
        {
          id: "gpay_wallet_1",
          type: "card",
          brand: "visa",
          last_digits: "9012",
          expiry_month: 10,
          expiry_year: baseYear,
          display_label: "Google Pay •••• 9012",
          wallet_provider: "google_pay",
        },
        {
          id: "gpay_wallet_2",
          type: "card",
          brand: "mastercard",
          last_digits: "3371",
          expiry_month: 6,
          expiry_year: baseYear + 1,
          display_label: "Google Pay •••• 3371",
          wallet_provider: "google_pay",
        },
        {
          id: "gpay_wallet_3",
          type: "card",
          brand: "amex",
          last_digits: "7765",
          expiry_month: 3,
          expiry_year: baseYear + 1,
          display_label: "Google Pay •••• 7765",
          wallet_provider: "google_pay",
        },
      ];
    }

    return [
      {
        id: "apay_wallet_1",
        type: "card",
        brand: "visa",
        last_digits: "4820",
        expiry_month: 9,
        expiry_year: baseYear,
        display_label: "Apple Pay •••• 4820",
        wallet_provider: "apple_pay",
      },
      {
        id: "apay_wallet_2",
        type: "card",
        brand: "mastercard",
        last_digits: "6634",
        expiry_month: 12,
        expiry_year: baseYear + 1,
        display_label: "Apple Pay •••• 6634",
        wallet_provider: "apple_pay",
      },
      {
        id: "apay_wallet_3",
        type: "card",
        brand: "amex",
        last_digits: "2907",
        expiry_month: 5,
        expiry_year: baseYear + 1,
        display_label: "Apple Pay •••• 2907",
        wallet_provider: "apple_pay",
      },
    ];
  }

  async getWalletPaymentMethods(
    wallet: WalletType
  ): Promise<{ payment_method_aliases: PaymentMethod[] }> {
    console.log(
      `CredentialProviderProxy: Simulating fetch of available cards for ${wallet}`
    );
    await new Promise((resolve) => setTimeout(resolve, 450));
    return { payment_method_aliases: this._getWalletPaymentMethods(wallet) };
  }
  /**
   * Simulates fetching supported payment methods based on the cart mandate.
   * @param config The payment handler config defined by the merchant.
   * @returns A promise that resolves to a mock payment methods response.
   */
  async getSupportedPaymentMethods(
    user_email: string,
    // biome-ignore lint/suspicious/noExplicitAny: no specific type for config
    config: any
  ): Promise<{ payment_method_aliases: PaymentMethod[] }> {
    console.log(
      `CredentialProviderProxy: Simulating fetch for ${user_email} supported payment methods with config:`,
      config
    );
    // Simulate network latency
    await new Promise((resolve) => setTimeout(resolve, 500));
    return {
      payment_method_aliases: this._getAllPaymentMethodsForUser(user_email),
    };
  }

  /**
   * Simulates fetching a payment token for a selected payment method.
   * @param user_email The user's email.
   * @param payment_method_id The selected payment method alias.
   * @returns A promise that resolves to a mock payment token response.
   */
  async getPaymentToken(
    user_email: string,
    payment_method_id: string
  ): Promise<PaymentInstrument | undefined> {
    console.log(
      `CredentialProviderProxy: Simulating fetch for payment token for user ${user_email} and method ${payment_method_id}`
    );
    // Simulate network latency
    await new Promise((resolve) => setTimeout(resolve, 500));
    const randomId = crypto.randomUUID();
    const payment_method = this._getAllPaymentMethodsForUser(user_email).find(
      (method) => method.id === payment_method_id
    );

    if (!payment_method) {
      return undefined;
    }

    return {
      ...payment_method,
      handler_id: this.handler_id,
      handler_name: this.handler_name,
      credential: {
        type: "token",
        token: `tok_ucp_${randomId}`,
      },
    };
  }

  _detectCardBrand(cardNumber: string): string {
    if (/^4/.test(cardNumber)) return "visa";
    if (/^5[1-5]/.test(cardNumber) || /^2(2[2-9]|[3-7])/.test(cardNumber))
      return "mastercard";
    if (/^3[47]/.test(cardNumber)) return "amex";
    return "card";
  }

  async tokenizeNexiCardPayment(
    user_email: string,
    payload: NexiCardTokenizationRequest
  ): Promise<PaymentInstrument> {
    console.log(
      `CredentialProviderProxy: Simulating Nexi tokenization for ${user_email}`
    );
    await new Promise((resolve) => setTimeout(resolve, 700));

    const digits = payload.cardNumber.replace(/\D/g, "");
    const randomId = crypto.randomUUID();
    const paymentInstrument: PaymentInstrument = {
      id: `nexi_instr_${randomId.slice(0, 8)}`,
      type: "card",
      brand: this._detectCardBrand(digits),
      last_digits: digits.slice(-4),
      expiry_month: payload.expiryMonth,
      expiry_year: payload.expiryYear,
      handler_id: this.handler_id,
      handler_name: this.handler_name,
      credential: {
        type: "token",
        token: `tok_nexi_${randomId}`,
      },
    };

    if (payload.saveCardForFuture) {
      this._savePaymentMethodAlias(user_email, {
        id: `saved_${randomId.slice(0, 8)}`,
        type: "card",
        brand: paymentInstrument.brand,
        last_digits: paymentInstrument.last_digits,
        expiry_month: paymentInstrument.expiry_month,
        expiry_year: paymentInstrument.expiry_year,
      });
    }

    return paymentInstrument;
  }

  async requestWalletAuthorization(
    wallet: WalletType
  ): Promise<{ approved: boolean; wallet: WalletType }> {
    console.log(
      `CredentialProviderProxy: Simulating ${wallet} authorization sheet`
    );
    await new Promise((resolve) => setTimeout(resolve, 650));
    return { approved: true, wallet };
  }

  async tokenizeWalletPayment(
    user_email: string,
    wallet: WalletType,
    selectedMethodId: string
  ): Promise<PaymentInstrument> {
    console.log(
      `CredentialProviderProxy: Simulating wallet tokenization for ${wallet} (${user_email})`
    );
    await new Promise((resolve) => setTimeout(resolve, 500));
    const selectedMethod = this._getWalletPaymentMethods(wallet).find(
      (method) => method.id === selectedMethodId
    );
    if (!selectedMethod) {
      throw new Error(`Unknown wallet payment method: ${selectedMethodId}`);
    }
    const randomId = crypto.randomUUID();
    return {
      id: `${wallet}_instr_${randomId.slice(0, 8)}`,
      type: "card",
      brand: selectedMethod.brand,
      last_digits: selectedMethod.last_digits,
      expiry_month: selectedMethod.expiry_month,
      expiry_year: selectedMethod.expiry_year,
      display_label: selectedMethod.display_label,
      wallet_provider: wallet,
      handler_id: this.handler_id,
      handler_name: this.handler_name,
      credential: {
        type: "token",
        token: `tok_${wallet}_${randomId}`,
      },
    };
  }
}

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
import type { PurchaseReservation } from "../types";

interface PurchaseReservationsProps {
  reservations: PurchaseReservation[];
}

function describeCondition(reservation: PurchaseReservation): string {
  if (reservation.condition_type === "price_drop") {
    if (reservation.target_price) {
      return `Trigger when price reaches ${reservation.target_price}`;
    }
    return "Trigger when the price drops";
  }
  return "Trigger when product is back in stock";
}

export default function PurchaseReservations({
  reservations,
}: PurchaseReservationsProps) {
  if (!reservations.length) {
    return null;
  }

  return (
    <div className="mt-3 w-full max-w-4xl rounded-xl border border-slate-200 bg-white p-4 shadow-lg">
      <h3 className="mb-3 border-b border-slate-200 pb-2 text-md font-bold text-slate-800">
        Purchase Reservations
      </h3>
      <div className="space-y-3">
        {reservations.map((reservation) => (
          <div
            key={reservation.id}
            className="rounded-lg border border-slate-200 bg-slate-50 p-3"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="font-semibold text-slate-800">
                {reservation.product_name} ({reservation.product_id})
              </div>
              <span
                className={`rounded-full px-2 py-1 text-xs font-semibold ${
                  reservation.status === "triggered"
                    ? "bg-emerald-100 text-emerald-800"
                    : "bg-amber-100 text-amber-800"
                }`}
              >
                {reservation.status}
              </span>
            </div>
            <div className="mt-1 text-sm text-slate-600">
              {describeCondition(reservation)}
            </div>
            <div className="mt-1 text-sm text-slate-600">
              Current: {reservation.current_price} -{" "}
              {reservation.current_availability.includes("InStock")
                ? "In stock"
                : "Not in stock"}
            </div>
            {reservation.trigger_reason && (
              <div className="mt-1 text-xs text-emerald-700">
                Trigger reason: {reservation.trigger_reason}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

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
import type { Product } from "../types";

interface ProductCardProps {
  product: Product;
  onAddToCart: (product: Product) => void;
  onReserveRestock?: (product: Product) => void;
}

const ProductCard: React.FC<ProductCardProps> = ({
  product,
  onAddToCart,
  onReserveRestock,
}) => {
  const isAvailable = product.offers.availability.includes("InStock");
  const handleAddToCartClick = () => onAddToCart?.(product);
  const handleReserveRestockClick = () => onReserveRestock?.(product);

  return (
    <div className="product-card bg-white rounded-xl shadow-md overflow-hidden border border-slate-200">
      <img
        src={product.image[0]}
        alt={product.name}
        className="w-full h-44 object-cover"
      />
      <div className="p-4">
        <h3 className="text-lg font-semibold text-slate-800 truncate" title={product.name}>
          {product.name}
        </h3>
        <p className="text-sm text-slate-600">{product.brand.name}</p>
        <p className="mt-2 min-h-10 text-sm leading-5 text-slate-600">
          {product.description}
        </p>
        <div className="flex justify-between items-center mt-3">
          <p className="text-lg font-bold text-slate-900">
            {product.offers.priceCurrency === "EUR" ? "€" : "$"}
            {product.offers.price}
          </p>
          <span
            className={`px-2 py-1 text-xs font-semibold rounded-full ${isAvailable ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800"}`}
          >
            {isAvailable ? "In Stock" : "Out of Stock"}
          </span>
        </div>
        <button
          type="button"
          onClick={handleAddToCartClick}
          disabled={!isAvailable || !onAddToCart}
          className="mt-4 block w-full rounded-md bg-blue-600 py-2 text-center font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-400"
        >
          Add to Checkout
        </button>
        {!isAvailable && onReserveRestock && (
          <button
            type="button"
            onClick={handleReserveRestockClick}
            className="mt-2 block w-full rounded-md border border-amber-300 bg-amber-50 py-2 text-center text-sm font-medium text-amber-700 transition-colors hover:bg-amber-100"
          >
            Reserve when back in stock
          </button>
        )}
      </div>
    </div>
  );
};

export default ProductCard;

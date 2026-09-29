import React from "react";
import { useSearchParams } from "react-router-dom";
import { XCircle } from "lucide-react";

const TIER_LABELS = { starter: "Starter", growth: "Growth", scale: "Scale" };

// Public page — Stripe Checkout's cancel_url when a customer backs out
// before paying. No account/org is ever created on this path.
export default function CheckoutCancelled() {
  const [searchParams] = useSearchParams();
  const tier = searchParams.get("tier");

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#F8F9FA] px-4" data-testid="checkout-cancelled-page">
      <div className="max-w-sm w-full bg-white border border-gray-100 rounded-2xl shadow-sm p-8 text-center">
        <XCircle className="w-8 h-8 text-gray-400 mx-auto mb-3" />
        <p className="text-sm font-medium text-gray-700">Checkout was cancelled — you have not been charged.</p>
        {tier && TIER_LABELS[tier] && (
          <a href={`/checkout?tier=${tier}`} className="inline-block mt-4 text-sm font-semibold text-[#1E3A8A] hover:underline" data-testid="checkout-cancelled-retry-link">
            Try the {TIER_LABELS[tier]} plan again
          </a>
        )}
      </div>
    </div>
  );
}

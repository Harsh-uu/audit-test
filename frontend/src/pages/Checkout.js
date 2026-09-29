import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import axios from "axios";
import { Loader2, AlertCircle } from "lucide-react";

const API = "/api";
const TIER_LABELS = { starter: "Starter", growth: "Growth", scale: "Scale" };

// Public, unauthenticated page — reached from a full-page navigation off the
// marketing site (supervision2.co.uk/#pricing -> /checkout?tier=starter).
// Immediately kicks off a Stripe Checkout Session and redirects the browser
// there; this page itself has no real UI beyond a loading/error state.
export default function Checkout() {
  const [searchParams] = useSearchParams();
  const tier = searchParams.get("tier");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!tier || !TIER_LABELS[tier]) {
      setError("Unknown plan — please go back and pick a plan again.");
      return;
    }
    let cancelled = false;
    axios.post(`${API}/public/checkout`, { tier })
      .then(({ data }) => {
        if (!cancelled && data.url) window.location.href = data.url;
      })
      .catch(err => {
        if (cancelled) return;
        setError(err.response?.data?.detail || "Could not start checkout — please try again shortly.");
      });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tier]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#F8F9FA] px-4" data-testid="checkout-page">
      <div className="max-w-sm w-full text-center">
        {error ? (
          <div className="bg-white border border-red-100 rounded-2xl shadow-sm p-8" data-testid="checkout-error">
            <AlertCircle className="w-8 h-8 text-red-500 mx-auto mb-3" />
            <p className="text-sm text-gray-700">{error}</p>
          </div>
        ) : (
          <div className="bg-white border border-gray-100 rounded-2xl shadow-sm p-8">
            <Loader2 className="w-8 h-8 text-[#1E3A8A] animate-spin mx-auto mb-3" />
            <p className="text-sm font-medium text-gray-700">Redirecting you to secure checkout…</p>
            <p className="text-xs text-gray-400 mt-1">{tier ? `${TIER_LABELS[tier] || tier} plan` : ""}</p>
          </div>
        )}
      </div>
    </div>
  );
}

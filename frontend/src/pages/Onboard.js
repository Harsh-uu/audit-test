import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import axios from "axios";
import { Loader2, AlertCircle, CheckCircle, ShieldCheck } from "lucide-react";
import { JurisdictionFields } from "@/components/JurisdictionFields";

const API = "/api";
const TIER_LABELS = { starter: "Starter", growth: "Growth", scale: "Scale" };

function formatError(detail) {
  if (!detail) return "Something went wrong. Please try again.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map(e => e?.msg || JSON.stringify(e)).join(" ");
  return String(detail);
}

// Public, unauthenticated page reached after a successful Stripe Checkout
// payment (success_url=/onboard?session_id=...). Verifies the session, then
// collects the org's founding admin details before completing onboarding —
// which ends in the SAME admin-invite email/accept-invite flow the Super
// Admin's manual "Create Org + Invite Admin" already uses.
export default function Onboard() {
  const [searchParams] = useSearchParams();
  const sessionId = searchParams.get("session_id");

  const [state, setState] = useState("loading"); // loading | error | already_used | form | submitting | provisioning | success
  const [errorMsg, setErrorMsg] = useState("");
  const [verified, setVerified] = useState(null); // { tier, founding }
  const [form, setForm] = useState({ name: "", email: "", organisation_name: "", jurisdiction: "england", service_type: "domiciliary" });
  const [resultOrgName, setResultOrgName] = useState("");

  useEffect(() => {
    if (!sessionId) {
      setState("error");
      setErrorMsg("Missing checkout session — please restart checkout from the pricing page.");
      return;
    }
    axios.get(`${API}/public/checkout/verify`, { params: { session_id: sessionId } })
      .then(({ data }) => {
        if (data.status === "already_used") {
          setState("already_used");
          return;
        }
        setVerified({ tier: data.tier, founding: data.founding });
        if (data.prefill_email) setForm(f => ({ ...f, email: data.prefill_email }));
        setState("form");
      })
      .catch(err => {
        setState("error");
        setErrorMsg(formatError(err.response?.data?.detail) || "We couldn't verify your payment — please contact support.");
      });
  }, [sessionId]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setState("submitting");
    setErrorMsg("");
    try {
      const { data, status } = await axios.post(`${API}/public/onboarding/complete`, {
        session_id: sessionId,
        name: form.name.trim(),
        email: form.email.trim(),
        organisation_name: form.organisation_name.trim(),
        jurisdiction: form.jurisdiction,
        service_type: ["northern_ireland", "ofsted"].includes(form.jurisdiction) ? form.service_type : undefined,
      });
      if (status === 202 || data.provisioning) {
        setState("provisioning");
        return;
      }
      setResultOrgName(data.organisation_name || form.organisation_name);
      setState("success");
    } catch (err) {
      setState("form");
      setErrorMsg(formatError(err.response?.data?.detail));
    }
  };

  if (state === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#F8F9FA]" data-testid="onboard-loading">
        <Loader2 className="w-8 h-8 text-[#1E3A8A] animate-spin" />
      </div>
    );
  }

  if (state === "error") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#F8F9FA] px-4" data-testid="onboard-error">
        <div className="max-w-sm w-full bg-white border border-red-100 rounded-2xl shadow-sm p-8 text-center">
          <AlertCircle className="w-8 h-8 text-red-500 mx-auto mb-3" />
          <p className="text-sm text-gray-700">{errorMsg}</p>
        </div>
      </div>
    );
  }

  if (state === "already_used") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#F8F9FA] px-4" data-testid="onboard-already-used">
        <div className="max-w-sm w-full bg-white border border-gray-100 rounded-2xl shadow-sm p-8 text-center">
          <ShieldCheck className="w-8 h-8 text-gray-400 mx-auto mb-3" />
          <p className="text-sm text-gray-700">This checkout link has already been used to set up an account.</p>
          <p className="text-xs text-gray-400 mt-2">Check your inbox for the invite email, or contact support if you can't find it.</p>
        </div>
      </div>
    );
  }

  if (state === "provisioning") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#F8F9FA] px-4" data-testid="onboard-provisioning">
        <div className="max-w-sm w-full bg-white border border-gray-100 rounded-2xl shadow-sm p-8 text-center">
          <Loader2 className="w-8 h-8 text-[#1E3A8A] animate-spin mx-auto mb-3" />
          <p className="text-sm font-medium text-gray-700">We're finishing setting up your account.</p>
          <p className="text-xs text-gray-400 mt-2">You'll receive an email shortly. Contact support if this takes more than a few minutes — your payment has already gone through.</p>
        </div>
      </div>
    );
  }

  if (state === "success") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#F8F9FA] px-4" data-testid="onboard-success">
        <div className="max-w-sm w-full bg-white border border-gray-100 rounded-2xl shadow-sm p-8 text-center">
          <CheckCircle className="w-8 h-8 text-green-600 mx-auto mb-3" />
          <p className="text-sm font-semibold text-gray-800">{resultOrgName} is all set up!</p>
          <p className="text-xs text-gray-500 mt-2">Check your inbox for an invite email to set your password and log in as the organisation admin.</p>
        </div>
      </div>
    );
  }

  const tierLabel = verified?.tier ? (TIER_LABELS[verified.tier] || verified.tier) : "";

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#F8F9FA] px-4 py-10" data-testid="onboard-page">
      <div className="max-w-md w-full">
        <div className="bg-white border border-gray-100 rounded-2xl shadow-sm p-8">
          <div className="mb-6">
            <h1 className="font-bold font-display text-[#1E3A8A] text-xl">Set up your organisation</h1>
            <p className="text-sm text-gray-500 mt-1">
              Payment confirmed — {tierLabel} plan{verified?.founding ? " (founding member price locked for 12 months)" : ""}.
            </p>
          </div>
          {errorMsg && (
            <p className="mb-4 text-sm text-red-600 bg-red-50 p-2 rounded" data-testid="onboard-form-error">{errorMsg}</p>
          )}
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="onboard-org-name" className="block text-sm font-medium text-gray-700 mb-1">Organisation Name</label>
              <input
                id="onboard-org-name"
                data-testid="onboard-org-name-input"
                type="text"
                required
                value={form.organisation_name}
                onChange={e => setForm(f => ({ ...f, organisation_name: e.target.value }))}
                placeholder="e.g. Sunrise Care Ltd"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/30 focus:border-[#1E3A8A]"
              />
            </div>
            <div>
              <label htmlFor="onboard-name" className="block text-sm font-medium text-gray-700 mb-1">Your Name</label>
              <input
                id="onboard-name"
                data-testid="onboard-name-input"
                type="text"
                required
                value={form.name}
                onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/30 focus:border-[#1E3A8A]"
              />
            </div>
            <div>
              <label htmlFor="onboard-email" className="block text-sm font-medium text-gray-700 mb-1">Your Email</label>
              <input
                id="onboard-email"
                data-testid="onboard-email-input"
                type="email"
                required
                value={form.email}
                onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/30 focus:border-[#1E3A8A]"
              />
            </div>
            <JurisdictionFields
              idPrefix="onboard"
              jurisdiction={form.jurisdiction}
              serviceType={form.service_type}
              onJurisdictionChange={v => setForm(f => ({ ...f, jurisdiction: v }))}
              onServiceTypeChange={v => setForm(f => ({ ...f, service_type: v }))}
            />
            <button
              type="submit"
              data-testid="onboard-submit-btn"
              disabled={state === "submitting"}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-[#1E3A8A] text-white rounded-lg text-sm font-semibold hover:bg-[#1e40af] disabled:opacity-60"
            >
              {state === "submitting" ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
              Complete Setup
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

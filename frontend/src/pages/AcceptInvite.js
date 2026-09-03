import React, { useState, useEffect } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import axios from "axios";
import { Eye, EyeOff, CheckCircle, AlertCircle, Loader2, Building2, HelpCircle } from "lucide-react";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";

const PW_REQS = [
  "At least 10 characters",
  "One uppercase letter (A–Z)",
  "One lowercase letter (a–z)",
  "One number (0–9)",
  "One special character (!@#$…)",
];

function PwTooltip() {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <HelpCircle className="w-3.5 h-3.5 text-gray-400 hover:text-gray-600 cursor-help inline-block ml-1 align-middle" />
      </TooltipTrigger>
      <TooltipContent side="right" className="max-w-xs text-left">
        <p className="font-semibold mb-1.5">Password requirements:</p>
        <ul className="space-y-0.5 text-xs">
          {PW_REQS.map(r => <li key={r} className="flex items-center gap-1.5"><span className="w-1 h-1 rounded-full bg-current flex-shrink-0" />{r}</li>)}
        </ul>
      </TooltipContent>
    </Tooltip>
  );
}

const API = "/api";

export default function AcceptInvite() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token");

  const [status, setStatus] = useState("loading"); // loading | valid | invalid | expired | success
  const [inviteData, setInviteData] = useState(null);
  const [form, setForm] = useState({ name: "", password: "", confirm: "" });
  const [showPw, setShowPw] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token) { setStatus("invalid"); return; }
    axios.get(`${API}/auth/invite/${token}`)
      .then(({ data }) => {
        setInviteData(data);
        setForm(f => ({ ...f, name: data.name || "" }));
        setStatus("valid");
      })
      .catch(err => {
        setStatus(err.response?.status === 410 ? "expired" : "invalid");
      });
  }, [token]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    if (form.password.length < 10) { setError("Password must be at least 10 characters"); return; }
    if (form.password !== form.confirm) { setError("Passwords do not match"); return; }
    setSubmitting(true);
    try {
      const { data } = await axios.post(`${API}/auth/accept-invite`, {
        token,
        name: form.name,
        password: form.password,
      });
      // P3b: server sets HttpOnly cookies on accept-invite; no localStorage needed
      setStatus("success");
      // Hard redirect so AuthProvider re-reads the session via cookie on mount
      setTimeout(() => { window.location.href = "/dashboard"; }, 1400);
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to accept invitation. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#F1F5F9] flex items-center justify-center p-4">
      <div className="w-full max-w-md">

        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-2 mb-2">
            <div className="w-9 h-9 bg-[#1E3A8A] rounded-lg flex items-center justify-center">
              <Building2 className="w-5 h-5 text-white" />
            </div>
            <span className="text-xl font-bold text-[#1E3A8A] font-display tracking-tight">1two.one</span>
          </div>
          <p className="text-sm text-gray-400">Care Supervision Platform</p>
        </div>

        <div className="bg-white rounded-2xl shadow-xl overflow-hidden">

          {/* Loading */}
          {status === "loading" && (
            <div className="flex flex-col items-center gap-3 py-16 px-8">
              <Loader2 className="w-8 h-8 text-[#1E3A8A] animate-spin" />
              <p className="text-sm text-gray-500">Validating your invitation…</p>
            </div>
          )}

          {/* Invalid */}
          {status === "invalid" && (
            <div className="flex flex-col items-center gap-4 py-16 px-8 text-center">
              <div className="w-14 h-14 bg-red-100 rounded-full flex items-center justify-center">
                <AlertCircle className="w-7 h-7 text-red-500" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-gray-900 font-display mb-1">Invalid Invitation</h2>
                <p className="text-sm text-gray-500">This invitation link is invalid or has already been used.</p>
              </div>
              <Link to="/login" className="text-sm text-[#1E3A8A] font-semibold hover:underline mt-2">
                Go to Login
              </Link>
            </div>
          )}

          {/* Expired */}
          {status === "expired" && (
            <div className="flex flex-col items-center gap-4 py-16 px-8 text-center">
              <div className="w-14 h-14 bg-amber-100 rounded-full flex items-center justify-center">
                <AlertCircle className="w-7 h-7 text-amber-500" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-gray-900 font-display mb-1">Link Expired</h2>
                <p className="text-sm text-gray-500">
                  This invitation expired after 72 hours. Please ask your administrator to resend it.
                </p>
              </div>
              <Link to="/login" className="text-sm text-[#1E3A8A] font-semibold hover:underline mt-2">
                Go to Login
              </Link>
            </div>
          )}

          {/* Success */}
          {status === "success" && (
            <div className="flex flex-col items-center gap-4 py-16 px-8 text-center">
              <div className="w-14 h-14 bg-emerald-100 rounded-full flex items-center justify-center">
                <CheckCircle className="w-7 h-7 text-emerald-600" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-gray-900 font-display mb-1">You're all set!</h2>
                <p className="text-sm text-gray-500">Your account is ready. Taking you to your dashboard…</p>
              </div>
              <Loader2 className="w-5 h-5 text-[#1E3A8A] animate-spin mt-2" />
            </div>
          )}

          {/* Valid — set password form */}
          {status === "valid" && inviteData && (
            <>
              <div className="bg-[#1E3A8A] px-8 py-6">
                <p className="text-white/60 text-xs font-semibold uppercase tracking-widest mb-1">Invitation</p>
                <h2 className="text-white font-bold font-display text-lg leading-tight">
                  Join {inviteData.org_name}
                </h2>
                <p className="text-blue-200 text-sm mt-1">{inviteData.email}</p>
              </div>

              <form onSubmit={handleSubmit} className="px-8 py-7 space-y-4">
                <p className="text-sm text-gray-500">Set your name and choose a password to activate your account.</p>

                {error && (
                  <div className="flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                    <AlertCircle className="w-4 h-4 flex-shrink-0" />
                    {error}
                  </div>
                )}

                <div>
                  <label htmlFor="invite-name" className="block text-xs font-semibold text-gray-600 mb-1.5">Your name</label>
                  <input
                    id="invite-name"
                    name="name"
                    data-testid="invite-name-input"
                    type="text"
                    required
                    autoComplete="name"
                    value={form.name}
                    onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                    className="w-full border border-gray-300 rounded-lg px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/30 focus:border-[#1E3A8A]"
                    placeholder="Jane Smith"
                  />
                </div>

                <div>
                  <label htmlFor="invite-password" className="block text-xs font-semibold text-gray-600 mb-1.5 flex items-center">Password <PwTooltip /></label>
                  <div className="relative">
                    <input
                      id="invite-password"
                      name="password"
                      data-testid="invite-password-input"
                      type={showPw ? "text" : "password"}
                      required
                      autoComplete="new-password"
                      value={form.password}
                      onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                      className="w-full border border-gray-300 rounded-lg px-3.5 py-2.5 text-sm pr-10 focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/30 focus:border-[#1E3A8A]"
                      placeholder="Min. 10 characters"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPw(v => !v)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                    >
                      {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>

                <div>
                  <label htmlFor="invite-confirm" className="block text-xs font-semibold text-gray-600 mb-1.5">Confirm password</label>
                  <input
                    id="invite-confirm"
                    name="confirm-password"
                    data-testid="invite-confirm-input"
                    type="password"
                    required
                    autoComplete="new-password"
                    value={form.confirm}
                    onChange={e => setForm(f => ({ ...f, confirm: e.target.value }))}
                    className="w-full border border-gray-300 rounded-lg px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/30 focus:border-[#1E3A8A]"
                    placeholder="Repeat password"
                  />
                </div>

                <button
                  data-testid="accept-invite-submit"
                  type="submit"
                  disabled={submitting || !form.name.trim() || !form.password || !form.confirm}
                  className="w-full flex items-center justify-center gap-2 py-2.5 bg-[#1E3A8A] text-white rounded-lg text-sm font-semibold hover:bg-[#1e40af] transition-colors disabled:opacity-50 mt-2"
                >
                  {submitting && <Loader2 className="w-4 h-4 animate-spin" />}
                  {submitting ? "Setting up account…" : "Activate Account"}
                </button>
              </form>
            </>
          )}

        </div>
      </div>
    </div>
  );
}

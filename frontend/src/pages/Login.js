import React, { useState } from "react";
import { useNavigate, Navigate } from "react-router-dom";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import { Eye, EyeOff, AlertCircle, CheckCircle, ShieldCheck, Mail } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

function formatError(detail) {
  if (!detail) return "Something went wrong. Please try again.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map(e => e?.msg || JSON.stringify(e)).join(" ");
  return String(detail);
}

export default function Login() {
  const { user, login, completeLogin } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState("login"); // "login" | "forgot"
  const [form, setForm] = useState({ email: "", password: "" });
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // MFA state
  const [mfaState, setMfaState] = useState(null); // { mfa_session, email }
  const [otpCode, setOtpCode] = useState("");

  if (user) return <Navigate to={user.role === "super_admin" ? "/super-admin" : "/dashboard"} replace />;

  const handle = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    setSuccess("");
    try {
      if (mode === "login") {
        const userData = await login(form.email, form.password);
        if (userData.requires_mfa) {
          setMfaState({ mfa_session: userData.mfa_session, email: userData.email });
          return;
        }
        navigate(userData.role === "super_admin" ? "/super-admin" : "/dashboard");
      } else if (mode === "forgot") {
        const res = await fetch(`${API}/auth/forgot-password`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: form.email }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(formatError(data.detail));
        setSuccess(data.message);
      }
    } catch (err) {
      setError(formatError(err.response?.data?.detail) || err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleMfaVerify = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const { data } = await axios.post(`${API}/auth/verify-mfa`, {
        mfa_session: mfaState.mfa_session,
        code: otpCode.trim(),
      });
      completeLogin(data);
      navigate(data.role === "super_admin" ? "/super-admin" : "/dashboard");
    } catch (err) {
      setError(formatError(err.response?.data?.detail) || err.message);
    } finally {
      setLoading(false);
    }
  };

  // ── MFA OTP screen ────────────────────────────────────────────────────────
  if (mfaState) {
    return (
      <div className="min-h-screen flex bg-[#F8F9FA]">
        <div className="hidden lg:flex lg:w-1/2 bg-[#1E3A8A] flex-col justify-between p-12">
          <div className="flex items-center gap-3">
            <img src="/logo.svg" alt="1two.one" className="w-16 h-16" />
            <span className="text-white text-4xl font-semibold tracking-tight">1two.one</span>
          </div>
          <div>
            <h1 className="text-4xl font-bold text-white mb-4 leading-tight">Two-factor authentication</h1>
            <p className="text-blue-200 text-lg leading-relaxed">
              Your account is protected with an extra layer of security. Enter the code sent to your email to continue.
            </p>
          </div>
          <p className="text-blue-300 text-sm">1two.one &copy; 2025</p>
        </div>

        <div className="flex-1 flex items-center justify-center p-8">
          <div className="w-full max-w-md fade-in">
            <div className="lg:hidden flex items-center gap-2 mb-8">
              <img src="/logo.svg" alt="1two.one" className="w-7 h-7" />
              <span className="text-[#1E3A8A] text-xl font-semibold">1two.one</span>
            </div>

            <div className="w-12 h-12 rounded-xl bg-[#EEF2FF] flex items-center justify-center mb-5">
              <ShieldCheck className="w-6 h-6 text-[#1E3A8A]" />
            </div>

            <h2 className="text-2xl font-semibold text-gray-900 mb-1">Check your email</h2>
            <p className="text-sm text-gray-500 mb-8 flex items-center gap-1.5">
              <Mail className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
              We sent a 6-digit code to <strong className="text-gray-700 ml-1">{mfaState.email}</strong>
            </p>

            {error && (
              <div className="flex items-start gap-3 bg-red-50 border border-red-200 text-red-700 rounded-md p-3 mb-6 text-sm" data-testid="mfa-error">
                <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <form onSubmit={handleMfaVerify} className="space-y-4">
              <div>
                <label htmlFor="mfa-code" className="block text-sm font-medium text-gray-700 mb-1">Verification code</label>
                <input
                  id="mfa-code"
                  name="otp"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  value={otpCode}
                  onChange={e => setOtpCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  placeholder="000000"
                  required
                  maxLength={6}
                  autoFocus
                  className="w-full px-3 py-3 border border-gray-300 rounded-md text-center text-2xl font-mono tracking-[0.5em] focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] focus:border-transparent"
                  data-testid="mfa-code-input"
                />
              </div>

              <button
                type="submit"
                disabled={loading || otpCode.length !== 6}
                className="w-full bg-[#1E3A8A] text-white py-2.5 px-4 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors disabled:opacity-60 flex items-center justify-center gap-2"
                data-testid="mfa-submit-btn"
              >
                {loading && <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full spin"></div>}
                Verify and sign in
              </button>
            </form>

            <p className="mt-6 text-center text-sm text-gray-500">
              <button
                onClick={() => { setMfaState(null); setOtpCode(""); setError(""); }}
                className="text-[#1E3A8A] font-medium hover:underline"
                data-testid="mfa-back-btn"
              >
                Back to sign in
              </button>
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex bg-[#F8F9FA]">
      {/* Left panel */}
      <div className="hidden lg:flex lg:w-1/2 bg-[#1E3A8A] flex-col justify-between p-12">
        <div className="flex items-center gap-3">
          <img src="/logo.svg" alt="1two.one" className="w-16 h-16" />
          <span className="text-white text-4xl font-semibold tracking-tight">1two.one</span>
        </div>
        <div>
          <h1 className="text-4xl font-bold text-white mb-4 leading-tight">
            Turn routine meetings into compliance evidence
          </h1>
          <p className="text-blue-200 text-lg leading-relaxed">
            Record, transcribe, and map your supervision meetings to your regulatory framework and induction standards automatically.
          </p>
          <div className="mt-8 space-y-3">
            {["Regulatory and induction evidence tracking", "Automatic compliance framework mapping", "Full audit trail with timestamps", "GDPR-aligned audio management"].map(f => (
              <div key={f} className="flex items-center gap-3 text-blue-100">
                <div className="w-1.5 h-1.5 bg-[#059669] rounded-full flex-shrink-0"></div>
                <span className="text-sm">{f}</span>
              </div>
            ))}
          </div>
        </div>
        <p className="text-blue-300 text-sm">1two.one &copy; 2025</p>
      </div>

      {/* Right panel */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-md fade-in">
          <div className="lg:hidden flex items-center gap-2 mb-8">
            <img src="/logo.svg" alt="1two.one" className="w-7 h-7" />
            <span className="text-[#1E3A8A] text-xl font-semibold">1two.one</span>
          </div>

          <h2 className="text-2xl font-semibold text-gray-900 mb-1">
            {mode === "login" ? "Sign in to your account" : "Reset your password"}
          </h2>
          <p className="text-gray-500 text-sm mb-8">
            {mode === "forgot" ? "Enter your email and we'll send you a reset link." : ""}
          </p>

          {error && (() => {
            const isForgotHint = error.toLowerCase().includes("forgot password");
            return (
              <div className={`flex items-start gap-3 rounded-md p-3 mb-6 text-sm border ${isForgotHint ? "bg-amber-50 border-amber-200 text-amber-800" : "bg-red-50 border-red-200 text-red-700"}`} data-testid="login-error">
                <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                <span>{error}</span>
              </div>
            );
          })()}
          {success && (
            <div className="flex items-start gap-3 bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-md p-3 mb-6 text-sm" data-testid="forgot-success">
              <CheckCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
              <span>{success}</span>
            </div>
          )}

          <form onSubmit={handle} className="space-y-4">
            <div>
              <label htmlFor="login-email" className="block text-sm font-medium text-gray-700 mb-1">Email address</label>
              <input
                id="login-email"
                name="email"
                type="email"
                value={form.email}
                onChange={e => setForm(f => ({...f, email: e.target.value}))}
                placeholder="you@organisation.com"
                required
                autoComplete="email"
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] focus:border-transparent"
                data-testid="login-email-input"
              />
            </div>

            {mode !== "forgot" && (
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label htmlFor="login-password" className="block text-sm font-medium text-gray-700">Password</label>
                  {mode === "login" && (
                    <button
                      type="button"
                      onClick={() => { setMode("forgot"); setError(""); setSuccess(""); }}
                      className="text-xs text-[#1E3A8A] hover:underline"
                      data-testid="forgot-password-link"
                    >
                      Forgot password?
                    </button>
                  )}
                </div>
                <div className="relative">
                  <input
                    id="login-password"
                    name="password"
                    type={showPassword ? "text" : "password"}
                    value={form.password}
                    onChange={e => setForm(f => ({...f, password: e.target.value}))}
                    placeholder="••••••••"
                    required
                    autoComplete="current-password"
                    className="w-full px-3 py-2 pr-10 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] focus:border-transparent"
                    data-testid="login-password-input"
                  />
                  <button type="button" onClick={() => setShowPassword(!showPassword)} className="absolute right-3 top-2.5 text-gray-400 hover:text-gray-600">
                    {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>
            )}

            <button
              type="submit"
              disabled={loading || (mode === "forgot" && !!success)}
              className="w-full bg-[#1E3A8A] text-white py-2.5 px-4 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors disabled:opacity-60 flex items-center justify-center gap-2"
              data-testid="login-submit-btn"
            >
              {loading && <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full spin"></div>}
              {mode === "login" ? "Sign in" : "Send reset link"}
            </button>
          </form>

          <p className="mt-6 text-center text-sm text-gray-500">
            {mode !== "login" && (
              <button onClick={() => { setMode("login"); setError(""); setSuccess(""); }} className="text-[#1E3A8A] font-medium hover:underline" data-testid="toggle-login-btn">Back to sign in</button>
            )}
          </p>

        </div>
      </div>
      <footer className="absolute bottom-0 left-0 right-0 py-3 px-6 flex items-center justify-between text-xs text-gray-400">
        <span>Supervision2 Ltd &middot; Company no. 16789096 &middot; ICO reg. ZC215901</span>
      </footer>    </div>
  );
}

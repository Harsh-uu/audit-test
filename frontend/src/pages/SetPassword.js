import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import axios from "axios";
import { cachedGet } from "@/utils/apiCache";
import { Eye, EyeOff, CheckCircle, XCircle, Lock } from "lucide-react";

const checks = [
  { label: "At least 10 characters",      test: p => p.length >= 10 },
  { label: "An uppercase letter (A–Z)",   test: p => /[A-Z]/.test(p) },
  { label: "A lowercase letter (a–z)",    test: p => /[a-z]/.test(p) },
  { label: "A number (0–9)",              test: p => /[0-9]/.test(p) },
  { label: "A special character (!@#$…)", test: p => /[^A-Za-z0-9]/.test(p) },
];

export default function SetPassword() {
  const { user, getAuthConfig, API } = useAuth();
  const navigate = useNavigate();

  const [current, setCurrent]   = useState("");
  const [next, setNext]         = useState("");
  const [confirm, setConfirm]   = useState("");
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNext, setShowNext]       = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [error, setError]  = useState("");
  const [saving, setSaving] = useState(false);

  const allPassing = checks.every(c => c.test(next));
  const matching   = next && confirm && next === confirm;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    if (!allPassing) { setError("Please meet all password requirements."); return; }
    if (!matching)   { setError("Passwords do not match."); return; }
    setSaving(true);
    try {
      await axios.post(`${API}/auth/change-password`, { current_password: current, new_password: next }, getAuthConfig());
      // Refresh user data so must_change_password is cleared
      const { data } = await cachedGet(`${API}/auth/me`, getAuthConfig());
      // Update user in context via a page reload (simplest — avoids needing a setUser export)
      if (data?.role === "super_admin") {
        navigate("/super-admin", { replace: true });
      } else {
        navigate("/dashboard", { replace: true });
      }
      window.location.reload();
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to change password");
    }
    setSaving(false);
  };

  return (
    <div className="min-h-screen bg-[#F8F9FA] flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-[#1E3A8A] mb-4">
            <Lock className="w-7 h-7 text-white" />
          </div>
          <h1 className="text-2xl font-semibold text-gray-900">Set your password</h1>
          <p className="text-sm text-gray-500 mt-1">
            Welcome{user?.name ? `, ${user.name}` : ""}. Please choose a secure password before continuing.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6 space-y-4">
          {/* Current password */}
          <div>
            <label htmlFor="set-current-password" className="block text-xs font-medium text-gray-600 mb-1">Current / temporary password</label>
            <div className="relative">
              <input
                id="set-current-password"
                name="current-password"
                type={showCurrent ? "text" : "password"}
                value={current}
                onChange={e => setCurrent(e.target.value)}
                required
                autoComplete="current-password"
                className="w-full border border-gray-200 rounded-lg px-3 py-2.5 text-sm pr-10 focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/20 focus:border-[#1E3A8A]"
                placeholder="Enter current password"
                data-testid="current-password-input"
              />
              <button type="button" onClick={() => setShowCurrent(v => !v)} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                {showCurrent ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          {/* New password */}
          <div>
            <label htmlFor="set-new-password" className="block text-xs font-medium text-gray-600 mb-1">New password</label>
            <div className="relative">
              <input
                id="set-new-password"
                name="new-password"
                type={showNext ? "text" : "password"}
                value={next}
                onChange={e => setNext(e.target.value)}
                required
                autoComplete="new-password"
                className="w-full border border-gray-200 rounded-lg px-3 py-2.5 text-sm pr-10 focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/20 focus:border-[#1E3A8A]"
                placeholder="Choose a strong password"
                data-testid="new-password-input"
              />
              <button type="button" onClick={() => setShowNext(v => !v)} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                {showNext ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
            {/* Strength checklist */}
            {next && (
              <ul className="mt-2 space-y-1">
                {checks.map(c => (
                  <li key={c.label} className={`flex items-center gap-1.5 text-xs ${c.test(next) ? "text-emerald-600" : "text-gray-400"}`}>
                    {c.test(next) ? <CheckCircle className="w-3.5 h-3.5 flex-shrink-0" /> : <XCircle className="w-3.5 h-3.5 flex-shrink-0" />}
                    {c.label}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Confirm */}
          <div>
            <label htmlFor="set-confirm-password" className="block text-xs font-medium text-gray-600 mb-1">Confirm new password</label>
            <div className="relative">
              <input
                id="set-confirm-password"
                name="confirm-password"
                type={showConfirm ? "text" : "password"}
                value={confirm}
                onChange={e => setConfirm(e.target.value)}
                required
                autoComplete="new-password"
                className={`w-full border rounded-lg px-3 py-2.5 text-sm pr-10 focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/20 focus:border-[#1E3A8A] ${
                  confirm && !matching ? "border-red-300" : "border-gray-200"
                }`}
                placeholder="Repeat your new password"
                data-testid="confirm-password-input"
              />
              <button type="button" onClick={() => setShowConfirm(v => !v)} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                {showConfirm ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
            {confirm && !matching && <p className="text-xs text-red-500 mt-1">Passwords do not match</p>}
          </div>

          {error && (
            <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2" data-testid="set-password-error">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={saving || !allPassing || !matching || !current}
            className="w-full bg-[#1E3A8A] text-white py-2.5 rounded-lg text-sm font-medium hover:bg-[#1E40AF] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            data-testid="set-password-submit"
          >
            {saving ? "Saving…" : "Set password and continue"}
          </button>
        </form>
      </div>
    </div>
  );
}

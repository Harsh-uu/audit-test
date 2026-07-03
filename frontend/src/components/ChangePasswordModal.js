import React, { useState } from "react";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import { Eye, EyeOff, CheckCircle, XCircle, X } from "lucide-react";
import { toast } from "sonner";

const checks = [
  { label: "At least 10 characters",      test: p => p.length >= 10 },
  { label: "Uppercase letter (A–Z)",       test: p => /[A-Z]/.test(p) },
  { label: "Lowercase letter (a–z)",       test: p => /[a-z]/.test(p) },
  { label: "Number (0–9)",                 test: p => /[0-9]/.test(p) },
  { label: "Special character (!@#$…)",    test: p => /[^A-Za-z0-9]/.test(p) },
];

export default function ChangePasswordModal({ onClose }) {
  const { getAuthConfig, API } = useAuth();

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
      toast.success("Password changed successfully");
      onClose();
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to change password");
    }
    setSaving(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" data-testid="change-password-modal">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h2 className="text-base font-semibold text-gray-900">Change password</h2>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400" data-testid="change-password-close">
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {/* Current */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Current password</label>
            <div className="relative">
              <input
                type={showCurrent ? "text" : "password"}
                value={current}
                onChange={e => setCurrent(e.target.value)}
                required
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm pr-10 focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/20 focus:border-[#1E3A8A]"
                placeholder="Your current password"
                data-testid="cp-current"
              />
              <button type="button" onClick={() => setShowCurrent(v => !v)} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                {showCurrent ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          {/* New */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">New password</label>
            <div className="relative">
              <input
                type={showNext ? "text" : "password"}
                value={next}
                onChange={e => setNext(e.target.value)}
                required
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm pr-10 focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/20 focus:border-[#1E3A8A]"
                placeholder="Choose a strong password"
                data-testid="cp-new"
              />
              <button type="button" onClick={() => setShowNext(v => !v)} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                {showNext ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
            {next && (
              <ul className="mt-2 space-y-0.5">
                {checks.map(c => (
                  <li key={c.label} className={`flex items-center gap-1.5 text-xs ${c.test(next) ? "text-emerald-600" : "text-gray-400"}`}>
                    {c.test(next) ? <CheckCircle className="w-3 h-3 flex-shrink-0" /> : <XCircle className="w-3 h-3 flex-shrink-0" />}
                    {c.label}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Confirm */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Confirm new password</label>
            <div className="relative">
              <input
                type={showConfirm ? "text" : "password"}
                value={confirm}
                onChange={e => setConfirm(e.target.value)}
                required
                className={`w-full border rounded-lg px-3 py-2 text-sm pr-10 focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/20 focus:border-[#1E3A8A] ${confirm && !matching ? "border-red-300" : "border-gray-200"}`}
                placeholder="Repeat new password"
                data-testid="cp-confirm"
              />
              <button type="button" onClick={() => setShowConfirm(v => !v)} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                {showConfirm ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
            {confirm && !matching && <p className="text-xs text-red-500 mt-1">Passwords do not match</p>}
          </div>

          {error && <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</p>}

          <div className="flex gap-2 pt-1">
            <button type="button" onClick={onClose} className="flex-1 border border-gray-200 text-gray-600 py-2 rounded-lg text-sm hover:bg-gray-50 transition-colors">
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving || !allPassing || !matching || !current}
              className="flex-1 bg-[#1E3A8A] text-white py-2 rounded-lg text-sm font-medium hover:bg-[#1E40AF] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              data-testid="cp-submit"
            >
              {saving ? "Saving…" : "Update password"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

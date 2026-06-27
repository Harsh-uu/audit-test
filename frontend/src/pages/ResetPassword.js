import React, { useState } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { Eye, EyeOff, AlertCircle, CheckCircle } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL;

export default function ResetPassword() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token") || "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#F8F9FA] p-8">
        <div className="text-center">
          <p className="text-red-600 text-sm mb-4">Invalid or missing reset link.</p>
          <Link to="/login" className="text-[#1E3A8A] text-sm hover:underline">Back to sign in</Link>
        </div>
      </div>
    );
  }

  const handle = async (e) => {
    e.preventDefault();
    if (password !== confirm) { setError("Passwords do not match."); return; }
    if (password.length < 8) { setError("Password must be at least 8 characters."); return; }
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API}/api/auth/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, new_password: password }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to reset password.");
      setDone(true);
      setTimeout(() => navigate("/login"), 3000);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex bg-[#F8F9FA]">
      {/* Left panel */}
      <div className="hidden lg:flex lg:w-1/2 bg-[#1E3A8A] flex-col justify-between p-12">
        <div className="flex items-center gap-3">
          <img src="/logo.svg" alt="1two.one" className="w-16 h-16" />
          <span className="text-white text-4xl font-semibold tracking-tight">1two.one</span>
        </div>
        <div>
          <blockquote className="text-blue-200 text-lg font-light leading-relaxed mb-6">
            "Creating a culture of continuous improvement in adult social care."
          </blockquote>
        </div>
        <p className="text-blue-300 text-sm">1two.one &copy; 2025</p>
      </div>

      {/* Right panel */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-md">
          <div className="lg:hidden flex items-center gap-2 mb-8">
            <img src="/logo.svg" alt="1two.one" className="w-7 h-7" />
            <span className="text-[#1E3A8A] text-xl font-semibold">1two.one</span>
          </div>

          <h2 className="text-2xl font-semibold text-gray-900 mb-1">
            Set a new password
          </h2>
          <p className="text-gray-500 text-sm mb-8">Choose a strong password for your account.</p>

          {error && (
            <div className="flex items-start gap-3 bg-red-50 border border-red-200 text-red-700 rounded-md p-3 mb-6 text-sm">
              <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}
          {done && (
            <div className="flex items-start gap-3 bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-md p-3 mb-6 text-sm" data-testid="reset-success">
              <CheckCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
              <span>Password updated! Redirecting you to sign in...</span>
            </div>
          )}

          {!done && (
            <form onSubmit={handle} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">New password</label>
                <div className="relative">
                  <input
                    type={showPassword ? "text" : "password"}
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    placeholder="At least 8 characters"
                    required
                    minLength={8}
                    className="w-full px-3 py-2 pr-10 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
                    data-testid="reset-password-input"
                  />
                  <button type="button" onClick={() => setShowPassword(!showPassword)} className="absolute right-3 top-2.5 text-gray-400 hover:text-gray-600">
                    {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Confirm password</label>
                <input
                  type={showPassword ? "text" : "password"}
                  value={confirm}
                  onChange={e => setConfirm(e.target.value)}
                  placeholder="Repeat your password"
                  required
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
                  data-testid="reset-confirm-input"
                />
              </div>
              <button
                type="submit"
                disabled={loading}
                className="w-full bg-[#1E3A8A] text-white py-2.5 px-4 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors disabled:opacity-60 flex items-center justify-center gap-2"
                data-testid="reset-submit-btn"
              >
                {loading && <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>}
                Update password
              </button>
            </form>
          )}

          <p className="mt-6 text-center text-sm text-gray-500">
            <Link to="/login" className="text-[#1E3A8A] font-medium hover:underline">Back to sign in</Link>
          </p>
        </div>
      </div>
    </div>
  );
}

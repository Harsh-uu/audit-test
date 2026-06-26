import React, { useState } from "react";
import { useNavigate, Navigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { Eye, EyeOff, AlertCircle } from "lucide-react";

function formatError(detail) {
  if (!detail) return "Something went wrong. Please try again.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map(e => e?.msg || JSON.stringify(e)).join(" ");
  return String(detail);
}

export default function Login() {
  const { user, login, register } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({ email: "", password: "", name: "", role: "attendee" });
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  if (user) return <Navigate to="/dashboard" replace />;

  const handle = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      if (mode === "login") {
        await login(form.email, form.password);
      } else {
        await register(form.email, form.password, form.name, form.role);
      }
      navigate("/dashboard");
    } catch (err) {
      setError(formatError(err.response?.data?.detail) || err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex bg-[#F8F9FA]">
      {/* Left panel */}
      <div className="hidden lg:flex lg:w-1/2 bg-[#1E3A8A] flex-col justify-between p-12">
        <div className="flex items-center gap-3">
          <span className="text-white text-2xl font-semibold tracking-tight" style={{fontFamily:'Work Sans,sans-serif'}}>1two.one</span>
        </div>
        <div>
          <h1 className="text-4xl font-bold text-white mb-4 leading-tight" style={{fontFamily:'Work Sans,sans-serif'}}>
            Turn routine meetings into compliance evidence
          </h1>
          <p className="text-blue-200 text-lg leading-relaxed">
            Record, transcribe, and map your supervision meetings to CQC regulations and Care Certificate standards automatically.
          </p>
          <div className="mt-8 space-y-3">
            {["Automatic CQC compliance mapping", "Care Certificate competence evidence", "Full audit trail with timestamps", "GDPR-aligned audio management"].map(f => (
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
            <span className="text-[#1E3A8A] text-xl font-semibold" style={{fontFamily:'Work Sans,sans-serif'}}>1two.one</span>
          </div>

          <h2 className="text-2xl font-semibold text-gray-900 mb-1" style={{fontFamily:'Work Sans,sans-serif'}}>
            {mode === "login" ? "Sign in to your account" : "Create account"}
          </h2>
          <p className="text-gray-500 text-sm mb-8">
            {mode === "login" ? "Welcome back. Enter your credentials to continue." : "Set up your account."}
          </p>

          {error && (
            <div className="flex items-start gap-3 bg-red-50 border border-red-200 text-red-700 rounded-md p-3 mb-6 text-sm" data-testid="login-error">
              <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={handle} className="space-y-4">
            {mode === "register" && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Full name</label>
                <input
                  type="text"
                  value={form.name}
                  onChange={e => setForm(f => ({...f, name: e.target.value}))}
                  placeholder="Jane Smith"
                  required
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] focus:border-transparent"
                  data-testid="register-name-input"
                />
              </div>
            )}

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Email address</label>
              <input
                type="email"
                value={form.email}
                onChange={e => setForm(f => ({...f, email: e.target.value}))}
                placeholder="you@organisation.com"
                required
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] focus:border-transparent"
                data-testid="login-email-input"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  value={form.password}
                  onChange={e => setForm(f => ({...f, password: e.target.value}))}
                  placeholder="••••••••"
                  required
                  className="w-full px-3 py-2 pr-10 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] focus:border-transparent"
                  data-testid="login-password-input"
                />
                <button type="button" onClick={() => setShowPassword(!showPassword)} className="absolute right-3 top-2.5 text-gray-400 hover:text-gray-600">
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {mode === "register" && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Role</label>
                <select
                  value={form.role}
                  onChange={e => setForm(f => ({...f, role: e.target.value}))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
                  data-testid="register-role-select"
                >
                  <option value="attendee">Care Worker / Attendee</option>
                  <option value="manager">Manager / Sign-off Owner</option>
                  <option value="shared_reviewer">Shared Reviewer</option>
                </select>
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-[#1E3A8A] text-white py-2.5 px-4 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors disabled:opacity-60 flex items-center justify-center gap-2"
              data-testid="login-submit-btn"
            >
              {loading && <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full spin"></div>}
              {mode === "login" ? "Sign in" : "Create account"}
            </button>
          </form>

          <p className="mt-6 text-center text-sm text-gray-500">
            {mode === "login" ? (
              <>Don't have an account? <button onClick={() => setMode("register")} className="text-[#1E3A8A] font-medium hover:underline" data-testid="toggle-register-btn">Register</button></>
            ) : (
              <>Already have an account? <button onClick={() => setMode("login")} className="text-[#1E3A8A] font-medium hover:underline" data-testid="toggle-login-btn">Sign in</button></>
            )}
          </p>

          {mode === "login" && (
            <div className="mt-6 bg-blue-50 border border-blue-200 rounded-md p-3 text-xs text-blue-700">
              <strong>Demo credentials:</strong><br/>
              Admin: admin@supervision.com / Admin123!<br/>
              Manager: manager@supervision.com / Manager123!<br/>
              Staff: staff@supervision.com / Staff123!
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

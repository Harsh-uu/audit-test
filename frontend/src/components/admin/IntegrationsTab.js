import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Webhook, Loader2, RefreshCw, Send, CheckCircle2, XCircle, KeyRound, Info } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const FIELDS_SHARED = ["Summary", "Achievements", "Actions", "Learning Needs"];

function StatusPill({ success }) {
  return success ? (
    <span className="flex items-center gap-1 text-[11px] font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-2 py-0.5">
      <CheckCircle2 className="w-3 h-3" />Delivered
    </span>
  ) : (
    <span className="flex items-center gap-1 text-[11px] font-semibold text-red-700 bg-red-50 border border-red-200 rounded-full px-2 py-0.5">
      <XCircle className="w-3 h-3" />Failed
    </span>
  );
}

export function IntegrationsTab() {
  const { API, getAuthConfig } = useAuth();
  const [cfg, setCfg] = useState({ url: "", enabled: false, secret_masked: "", configured: false });
  const [urlInput, setUrlInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [deliveries, setDeliveries] = useState([]);
  const [resendingId, setResendingId] = useState(null);

  const load = useCallback(async () => {
    try {
      const [cfgRes, delRes] = await Promise.all([
        axios.get(`${API}/org/webhook`, getAuthConfig()),
        axios.get(`${API}/org/webhook/deliveries`, getAuthConfig()),
      ]);
      setCfg(cfgRes.data);
      setUrlInput(cfgRes.data.url || "");
      setDeliveries(delRes.data || []);
    } catch {
      toast.error("Failed to load webhook settings");
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleSave = async (enabledOverride) => {
    const enabled = enabledOverride !== undefined ? enabledOverride : cfg.enabled;
    if (enabled && !urlInput.trim()) {
      toast.error("Add a URL before enabling the webhook");
      return;
    }
    setSaving(true);
    try {
      await axios.put(`${API}/org/webhook`, { url: urlInput.trim(), enabled }, getAuthConfig());
      toast.success("Webhook settings saved");
      await load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to save webhook settings");
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    try {
      const { data } = await axios.post(`${API}/org/webhook/test`, {}, getAuthConfig());
      if (data.success) toast.success(`Test ping delivered (HTTP ${data.http_status})`);
      else toast.error(data.error_message || "Test ping failed");
      await load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to send test ping");
    } finally {
      setTesting(false);
    }
  };

  const handleRegenerate = async () => {
    setRegenerating(true);
    try {
      const { data } = await axios.post(`${API}/org/webhook/regenerate-secret`, {}, getAuthConfig());
      toast.success("Signing secret regenerated");
      setCfg(c => ({ ...c, secret_masked: data.secret_masked }));
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to regenerate secret");
    } finally {
      setRegenerating(false);
    }
  };

  const handleResend = async (id) => {
    setResendingId(id);
    try {
      const { data } = await axios.post(`${API}/org/webhook/deliveries/${id}/resend`, {}, getAuthConfig());
      if (data.success) toast.success("Resent successfully");
      else toast.error(data.error_message || "Resend failed");
      await load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to resend");
    } finally {
      setResendingId(null);
    }
  };

  if (loading) {
    return <div className="flex items-center gap-2 text-xs text-gray-400"><Loader2 className="w-3.5 h-3.5 animate-spin" />Loading integration settings…</div>;
  }

  return (
    <div className="max-w-2xl space-y-6" data-testid="integrations-tab">
      <div>
        <h3 className="text-sm font-semibold text-gray-800 mb-0.5 flex items-center gap-1.5">
          <Webhook className="w-4 h-4 text-[#0F766E]" />HR System Webhook
        </h3>
        <p className="text-xs text-gray-500">
          When a meeting is signed off, push a limited summary to your HR system automatically — no polling, no API key sharing beyond this org.
        </p>
      </div>

      <div className="flex items-start gap-2 bg-teal-50 border border-teal-200 rounded-lg p-3">
        <Info className="w-4 h-4 text-teal-600 flex-shrink-0 mt-0.5" />
        <div className="text-xs text-teal-800">
          <p className="font-semibold mb-1">Only these 4 fields are shared — never the transcript, audio, risks, or standards mapping:</p>
          <div className="flex gap-1.5 flex-wrap">
            {FIELDS_SHARED.map(f => (
              <span key={f} className="bg-white border border-teal-200 rounded-full px-2 py-0.5 font-medium">{f}</span>
            ))}
          </div>
        </div>
      </div>

      <div className="space-y-3">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Webhook URL</label>
          <input
            type="text"
            value={urlInput}
            onChange={e => setUrlInput(e.target.value)}
            placeholder="https://your-hr-system.com/webhooks/1two-one"
            className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-500"
            data-testid="webhook-url-input"
          />
        </div>

        <div className="flex items-center justify-between bg-gray-50 border border-gray-200 rounded-lg px-3 py-2.5">
          <div>
            <p className="text-sm font-medium text-gray-800">Push on sign-off</p>
            <p className="text-xs text-gray-400">Fires automatically the moment a meeting is signed off</p>
          </div>
          <button
            role="switch"
            aria-checked={cfg.enabled}
            onClick={() => handleSave(!cfg.enabled)}
            disabled={saving}
            className={`relative w-11 h-6 rounded-full transition-colors flex-shrink-0 ${cfg.enabled ? "bg-[#0F766E]" : "bg-gray-300"} disabled:opacity-50`}
            data-testid="webhook-enabled-toggle"
          >
            <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${cfg.enabled ? "translate-x-5" : ""}`} />
          </button>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => handleSave()}
            disabled={saving}
            className="flex items-center gap-1.5 text-sm px-4 py-2 rounded-lg bg-[#1E3A8A] text-white hover:bg-[#1E40AF] transition-colors disabled:opacity-50"
            data-testid="webhook-save-btn"
          >
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Save URL
          </button>
          <button
            onClick={handleTest}
            disabled={testing || !cfg.configured}
            className="flex items-center gap-1.5 text-sm px-4 py-2 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            data-testid="webhook-test-btn"
          >
            {testing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
            Send Test Ping
          </button>
        </div>

        {cfg.secret_masked && (
          <div className="flex items-center justify-between bg-gray-50 border border-gray-200 rounded-lg px-3 py-2.5">
            <div className="flex items-center gap-2">
              <KeyRound className="w-3.5 h-3.5 text-gray-400" />
              <div>
                <p className="text-xs font-medium text-gray-700">Signing secret</p>
                <p className="text-xs text-gray-400 font-mono" data-testid="webhook-secret-masked">{cfg.secret_masked}</p>
              </div>
            </div>
            <button
              onClick={handleRegenerate}
              disabled={regenerating}
              className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md border border-gray-200 text-gray-600 hover:bg-white transition-colors disabled:opacity-50"
              data-testid="webhook-regenerate-secret-btn"
            >
              <RefreshCw className={`w-3 h-3 ${regenerating ? "animate-spin" : ""}`} />Regenerate
            </button>
          </div>
        )}
        <p className="text-[11px] text-gray-400">
          Every push is signed with HMAC-SHA256 in the <code className="bg-gray-100 px-1 rounded">X-Webhook-Signature</code> header, so your HR system can verify it really came from us.
        </p>
      </div>

      <div>
        <h4 className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2">Recent deliveries</h4>
        {deliveries.length === 0 ? (
          <p className="text-xs text-gray-400" data-testid="webhook-deliveries-empty">No deliveries yet — sign off a meeting or send a test ping.</p>
        ) : (
          <div className="border border-gray-200 rounded-lg divide-y divide-gray-100 max-h-72 overflow-y-auto" data-testid="webhook-deliveries-list">
            {deliveries.map(d => (
              <div key={d.id} className="flex items-center justify-between gap-3 px-3 py-2.5" data-testid={`webhook-delivery-${d.id}`}>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <StatusPill success={d.success} />
                    <span className="text-xs text-gray-500">{d.event}</span>
                  </div>
                  <p className="text-[11px] text-gray-400 mt-0.5 truncate">
                    {new Date(d.attempted_at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
                    {d.http_status ? ` · HTTP ${d.http_status}` : ""}
                    {d.error_message ? ` · ${d.error_message}` : ""}
                  </p>
                </div>
                {!d.success && (
                  <button
                    onClick={() => handleResend(d.id)}
                    disabled={resendingId === d.id}
                    className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 transition-colors disabled:opacity-50 flex-shrink-0"
                    data-testid={`webhook-resend-btn-${d.id}`}
                  >
                    {resendingId === d.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                    Resend
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

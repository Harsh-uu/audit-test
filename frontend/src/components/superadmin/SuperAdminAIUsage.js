import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Cpu, AlertTriangle, Clock, RefreshCw, Loader2, ExternalLink } from "lucide-react";

const API = "/api";

function StatCard({ label, value, sub, warn, testId }) {
  return (
    <div data-testid={testId} className="bg-white border border-gray-200 rounded-lg p-4">
      <p className="text-xs text-gray-500 font-medium">{label}</p>
      <p className={`text-2xl font-bold font-display mt-1 ${warn ? "text-red-600" : "text-[#1E3A8A]"}`}>{value}</p>
      {sub && <p className="text-[11px] text-gray-400 mt-0.5">{sub}</p>}
    </div>
  );
}

function ProviderBadge({ provider, fallback }) {
  const isGemini = (provider || "").startsWith("gemini");
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${
      isGemini ? "bg-indigo-100 text-indigo-700" : "bg-amber-100 text-amber-700"
    }`}>
      <Cpu className="w-3 h-3" />
      {provider || "unknown"}
      {fallback && <span className="ml-0.5">(fallback)</span>}
    </span>
  );
}

export default function SuperAdminAIUsage({ getAuthConfig, orgs }) {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState({ items: [], stats: { total: 0, fallback_count: 0, fallback_rate_pct: 0, avg_latency_ms: null, by_provider: {}, provider_changed_on_rescan_count: 0 } });
  const [orgFilter, setOrgFilter] = useState("");
  const [providerFilter, setProviderFilter] = useState("");
  const [fallbackOnly, setFallbackOnly] = useState(false);
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = {};
      if (orgFilter) params.org_id = orgFilter;
      if (providerFilter) params.provider = providerFilter;
      if (fallbackOnly) params.fallback_only = true;
      if (fromDate) params.from_date = fromDate;
      if (toDate) params.to_date = toDate + "T23:59:59";
      const res = await axios.get(`${API}/super-admin/ai-usage-report`, { ...getAuthConfig(), params });
      setData(res.data);
    } catch (e) {
      setError(e?.response?.data?.detail || "Failed to load AI usage report");
    } finally {
      setLoading(false);
    }
  }, [getAuthConfig, orgFilter, providerFilter, fallbackOnly, fromDate, toDate]);

  useEffect(() => { load(); }, [load]);

  const providers = Object.keys(data.stats.by_provider || {});

  return (
    <div data-testid="ai-usage-report">
      <p className="text-sm text-gray-500 mb-4 max-w-2xl">
        Which AI provider served each meeting's evidence analysis, and whether it fell back —
        for RCA on evidence-scan discrepancies. Not shown to end users on any individual meeting.
      </p>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 mb-5 bg-white border border-gray-200 rounded-lg p-3">
        <select
          value={orgFilter}
          onChange={e => setOrgFilter(e.target.value)}
          data-testid="ai-usage-org-filter"
          className="px-2.5 py-1.5 border border-gray-300 rounded text-xs bg-white focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
        >
          <option value="">All Organisations</option>
          {(orgs || []).map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
        <select
          value={providerFilter}
          onChange={e => setProviderFilter(e.target.value)}
          data-testid="ai-usage-provider-filter"
          className="px-2.5 py-1.5 border border-gray-300 rounded text-xs bg-white focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
        >
          <option value="">All Providers</option>
          {providers.map(p => <option key={p} value={p}>{p}</option>)}
        </select>
        <label className="flex items-center gap-1.5 text-xs text-gray-600 px-1">
          <input type="checkbox" checked={fallbackOnly} onChange={e => setFallbackOnly(e.target.checked)} data-testid="ai-usage-fallback-only-checkbox" />
          Fallback only
        </label>
        <input
          type="date" value={fromDate} onChange={e => setFromDate(e.target.value)}
          data-testid="ai-usage-from-date" className="px-2.5 py-1.5 border border-gray-300 rounded text-xs"
        />
        <span className="text-xs text-gray-400">to</span>
        <input
          type="date" value={toDate} onChange={e => setToDate(e.target.value)}
          data-testid="ai-usage-to-date" className="px-2.5 py-1.5 border border-gray-300 rounded text-xs"
        />
        <button
          onClick={load} data-testid="ai-usage-refresh-btn"
          className="ml-auto flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-semibold border border-gray-200 text-gray-600 hover:bg-gray-50"
        >
          <RefreshCw className="w-3.5 h-3.5" /> Refresh
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700" data-testid="ai-usage-error">{error}</div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16 text-gray-400" data-testid="ai-usage-loading">
          <Loader2 className="w-6 h-6 animate-spin" />
        </div>
      ) : (
        <>
          {/* Stat cards */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-5">
            <StatCard testId="ai-usage-stat-total" label="Total Analyses" value={data.stats.total} />
            <StatCard
              testId="ai-usage-stat-fallback"
              label="Fallback Rate"
              value={`${data.stats.fallback_rate_pct}%`}
              sub={`${data.stats.fallback_count} of ${data.stats.total}`}
              warn={data.stats.fallback_rate_pct > 20}
            />
            <StatCard
              testId="ai-usage-stat-latency"
              label="Avg Latency"
              value={data.stats.avg_latency_ms != null ? `${(data.stats.avg_latency_ms / 1000).toFixed(1)}s` : "—"}
            />
            <StatCard
              testId="ai-usage-stat-provider-changed"
              label="Provider Changed on Rescan"
              value={data.stats.provider_changed_on_rescan_count ?? 0}
              sub="likely explains a different evidence count"
              warn={(data.stats.provider_changed_on_rescan_count ?? 0) > 0}
            />
            <div className="bg-white border border-gray-200 rounded-lg p-4" data-testid="ai-usage-stat-by-provider">
              <p className="text-xs text-gray-500 font-medium mb-1.5">By Provider</p>
              {providers.length === 0 ? (
                <p className="text-sm text-gray-400">No data</p>
              ) : (
                <div className="space-y-1">
                  {providers.map(p => (
                    <div key={p} className="flex items-center justify-between text-xs">
                      <span className="text-gray-600 truncate">{p}</span>
                      <span className="font-semibold text-[#1E3A8A]">{data.stats.by_provider[p]}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Table */}
          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
            {data.items.length === 0 ? (
              <div className="p-8 text-center text-sm text-gray-400" data-testid="ai-usage-empty-state">
                No AI-tracked analyses found for these filters (only analyses run after this tracking shipped are included).
              </div>
            ) : (
              <div className="overflow-x-auto">
              <table className="w-full text-sm min-w-[720px]" data-testid="ai-usage-table">
                <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
                  <tr>
                    <th className="text-left px-4 py-2.5 font-medium">Meeting</th>
                    <th className="text-left px-4 py-2.5 font-medium">Organisation</th>
                    <th className="text-left px-4 py-2.5 font-medium">Initial Scan</th>
                    <th className="text-left px-4 py-2.5 font-medium">Latest Scan</th>
                    <th className="text-left px-4 py-2.5 font-medium">Latency</th>
                    <th className="text-left px-4 py-2.5 font-medium">Date</th>
                    <th className="text-left px-4 py-2.5 font-medium">Fallback Reason</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {data.items.map(item => (
                    <tr key={item.analysis_id} data-testid={`ai-usage-row-${item.analysis_id}`}>
                      <td className="px-4 py-2.5">
                        <a
                          href={`/meetings/${item.meeting_id}/report`}
                          target="_blank" rel="noreferrer"
                          className="flex items-center gap-1 text-[#1E3A8A] hover:underline font-medium"
                          data-testid={`ai-usage-meeting-link-${item.analysis_id}`}
                        >
                          {item.meeting_title || "Untitled meeting"} <ExternalLink className="w-3 h-3" />
                        </a>
                        {item.rescanned_at && <span className="text-[11px] text-gray-400">rescanned</span>}
                      </td>
                      <td className="px-4 py-2.5 text-gray-600">{item.org_name || "—"}</td>
                      <td className="px-4 py-2.5">
                        <ProviderBadge provider={item.initial_ai_provider || item.ai_provider} fallback={item.initial_ai_fallback_used} />
                      </td>
                      <td className="px-4 py-2.5">
                        {item.rescanned_at ? (
                          <span className="flex items-center gap-1.5">
                            <ProviderBadge provider={item.ai_provider} fallback={item.ai_fallback_used} />
                            {item.provider_changed_on_rescan && (
                              <span
                                className="text-[11px] text-red-600 font-semibold flex items-center gap-0.5"
                                title="Provider changed between initial scan and rescan — likely explains a different evidence count"
                                data-testid={`ai-usage-provider-changed-${item.analysis_id}`}
                              >
                                <AlertTriangle className="w-3 h-3" /> changed
                              </span>
                            )}
                          </span>
                        ) : (
                          <span className="text-xs text-gray-400">— not rescanned —</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-gray-600">
                        <span className="inline-flex items-center gap-1">
                          <Clock className="w-3 h-3 text-gray-400" />
                          {item.ai_latency_ms != null ? `${(item.ai_latency_ms / 1000).toFixed(1)}s` : "—"}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-gray-500 text-xs">
                        {item.analyzed_at ? new Date(item.analyzed_at).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"}
                      </td>
                      <td className="px-4 py-2.5 text-xs text-gray-500 max-w-xs">
                        {item.ai_fallback_used && item.ai_fallback_reason ? (
                          <span className="flex items-start gap-1 text-amber-700">
                            <AlertTriangle className="w-3 h-3 mt-0.5 flex-shrink-0" />
                            <span className="truncate" title={item.ai_fallback_reason}>{item.ai_fallback_reason}</span>
                          </span>
                        ) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

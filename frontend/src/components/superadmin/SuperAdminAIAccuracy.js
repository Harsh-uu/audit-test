import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Target, ThumbsUp, ThumbsDown, Flag, RefreshCw, Loader2, ExternalLink } from "lucide-react";

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

const ACTION_STYLE = {
  accepted: "bg-green-100 text-green-700",
  rejected: "bg-red-100 text-red-700",
  needs_followup: "bg-amber-100 text-amber-700",
  edited_summary: "bg-blue-100 text-blue-700",
  viewed: "bg-gray-100 text-gray-500",
  pending: "bg-gray-100 text-gray-400",
};

function ActionBadge({ action }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${ACTION_STYLE[action] || "bg-gray-100 text-gray-500"}`}>
      {(action || "unknown").replace("_", " ")}
    </span>
  );
}

export default function SuperAdminAIAccuracy({ getAuthConfig, orgs }) {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState({ items: [], stats: { total: 0, by_action: {}, acceptance_rate: null, top_rejected_standards: [] }, by_org: [] });
  const [orgFilter, setOrgFilter] = useState("");
  const [actionFilter, setActionFilter] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = {};
      if (orgFilter) params.org_id = orgFilter;
      if (actionFilter) params.action = actionFilter;
      if (fromDate) params.from_date = fromDate;
      if (toDate) params.to_date = toDate + "T23:59:59";
      const res = await axios.get(`${API}/super-admin/ai-accuracy-report`, { ...getAuthConfig(), params });
      setData(res.data);
    } catch (e) {
      setError(e?.response?.data?.detail || "Failed to load AI accuracy report");
    } finally {
      setLoading(false);
    }
  }, [getAuthConfig, orgFilter, actionFilter, fromDate, toDate]);

  useEffect(() => { load(); }, [load]);

  const { stats, by_org } = data;
  const rejected = stats.by_action?.rejected || 0;
  const flagged = stats.by_action?.needs_followup || 0;

  return (
    <div data-testid="ai-accuracy-report">
      <p className="text-sm text-gray-500 mb-4 max-w-2xl">
        Every accept/reject/flag decision a manager makes on AI-mapped evidence, across all organisations —
        the same data behind each org's own AI Accuracy tab, aggregated globally so you can spot an
        organisation (or the whole fleet) with an unusually low acceptance rate.
      </p>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 mb-5 bg-white border border-gray-200 rounded-lg p-3">
        <select
          value={orgFilter}
          onChange={e => setOrgFilter(e.target.value)}
          data-testid="ai-accuracy-org-filter"
          className="px-2.5 py-1.5 border border-gray-300 rounded text-xs bg-white focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
        >
          <option value="">All Organisations</option>
          {(orgs || []).map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
        <select
          value={actionFilter}
          onChange={e => setActionFilter(e.target.value)}
          data-testid="ai-accuracy-action-filter"
          className="px-2.5 py-1.5 border border-gray-300 rounded text-xs bg-white focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
        >
          <option value="">All Actions</option>
          <option value="accepted">Accepted</option>
          <option value="rejected">Rejected</option>
          <option value="needs_followup">Flagged</option>
          <option value="edited_summary">Edited</option>
          <option value="viewed">Viewed</option>
        </select>
        <input
          type="date" value={fromDate} onChange={e => setFromDate(e.target.value)}
          data-testid="ai-accuracy-from-date" className="px-2.5 py-1.5 border border-gray-300 rounded text-xs"
        />
        <span className="text-xs text-gray-400">to</span>
        <input
          type="date" value={toDate} onChange={e => setToDate(e.target.value)}
          data-testid="ai-accuracy-to-date" className="px-2.5 py-1.5 border border-gray-300 rounded text-xs"
        />
        <button
          onClick={load} data-testid="ai-accuracy-refresh-btn"
          className="ml-auto flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-semibold border border-gray-200 text-gray-600 hover:bg-gray-50"
        >
          <RefreshCw className="w-3.5 h-3.5" /> Refresh
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700" data-testid="ai-accuracy-error">{error}</div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16 text-gray-400" data-testid="ai-accuracy-loading">
          <Loader2 className="w-6 h-6 animate-spin" />
        </div>
      ) : (
        <>
          {/* Stat cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
            <StatCard testId="ai-accuracy-stat-total" label="Total Decisions" value={stats.total} />
            <StatCard
              testId="ai-accuracy-stat-rate"
              label="Acceptance Rate"
              value={stats.acceptance_rate != null ? `${stats.acceptance_rate}%` : "—"}
              sub="of accepted + rejected"
              warn={stats.acceptance_rate != null && stats.acceptance_rate < 60}
            />
            <StatCard testId="ai-accuracy-stat-rejected" label="Rejected" value={rejected} icon={ThumbsDown} />
            <StatCard testId="ai-accuracy-stat-flagged" label="Flagged for Follow-up" value={flagged} icon={Flag} />
          </div>

          {/* By Organisation — the global insight the per-org report can't show */}
          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden mb-5" data-testid="ai-accuracy-by-org">
            <div className="px-4 py-2.5 border-b border-gray-100 bg-gray-50">
              <p className="text-xs font-semibold text-gray-600 uppercase">By Organisation</p>
            </div>
            {by_org.length === 0 ? (
              <div className="p-6 text-center text-sm text-gray-400" data-testid="ai-accuracy-by-org-empty">No feedback recorded for these filters</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm min-w-[560px]">
                  <thead className="text-xs text-gray-500">
                    <tr>
                      <th className="text-left px-4 py-2 font-medium">Organisation</th>
                      <th className="text-right px-4 py-2 font-medium">Total</th>
                      <th className="text-right px-4 py-2 font-medium">Accepted</th>
                      <th className="text-right px-4 py-2 font-medium">Rejected</th>
                      <th className="text-right px-4 py-2 font-medium">Flagged</th>
                      <th className="text-right px-4 py-2 font-medium">Acceptance Rate</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {by_org.map(o => (
                      <tr key={o.org_id || "unknown"} data-testid={`ai-accuracy-org-row-${o.org_id}`}>
                        <td className="px-4 py-2 font-medium text-gray-800">{o.org_name}</td>
                        <td className="px-4 py-2 text-right text-gray-600">{o.total}</td>
                        <td className="px-4 py-2 text-right text-green-700">{o.accepted}</td>
                        <td className="px-4 py-2 text-right text-red-600">{o.rejected}</td>
                        <td className="px-4 py-2 text-right text-amber-600">{o.flagged}</td>
                        <td className={`px-4 py-2 text-right font-semibold ${o.acceptance_rate != null && o.acceptance_rate < 60 ? "text-red-600" : "text-[#1E3A8A]"}`}>
                          {o.acceptance_rate != null ? `${o.acceptance_rate}%` : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Top rejected standards */}
          {stats.top_rejected_standards?.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-lg p-4 mb-5" data-testid="ai-accuracy-top-rejected">
              <p className="text-xs font-semibold text-gray-600 uppercase mb-2">Most Rejected Standards</p>
              <div className="space-y-1">
                {stats.top_rejected_standards.map((s, i) => (
                  <div key={i} className="flex items-center justify-between text-xs">
                    <span className="text-gray-600 truncate">{s.standard_ref} {s.standard_name}</span>
                    <span className="font-semibold text-red-600">{s.count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Feedback log */}
          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
            {data.items.length === 0 ? (
              <div className="p-8 text-center text-sm text-gray-400" data-testid="ai-accuracy-empty-state">
                No evidence feedback found for these filters.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm min-w-[820px]" data-testid="ai-accuracy-table">
                  <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
                    <tr>
                      <th className="text-left px-4 py-2.5 font-medium">Meeting</th>
                      <th className="text-left px-4 py-2.5 font-medium">Organisation</th>
                      <th className="text-left px-4 py-2.5 font-medium">Standard</th>
                      <th className="text-left px-4 py-2.5 font-medium">Confidence</th>
                      <th className="text-left px-4 py-2.5 font-medium">Manager</th>
                      <th className="text-left px-4 py-2.5 font-medium">Action</th>
                      <th className="text-left px-4 py-2.5 font-medium">Date</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {data.items.map(item => (
                      <tr key={item.id} data-testid={`ai-accuracy-row-${item.id}`}>
                        <td className="px-4 py-2.5">
                          <a
                            href={`/meetings/${item.meeting_id}/report`}
                            target="_blank" rel="noreferrer"
                            className="flex items-center gap-1 text-[#1E3A8A] hover:underline font-medium"
                            data-testid={`ai-accuracy-meeting-link-${item.id}`}
                          >
                            {item.meeting_title || "Untitled meeting"} <ExternalLink className="w-3 h-3" />
                          </a>
                        </td>
                        <td className="px-4 py-2.5 text-gray-600">{item.org_name || "—"}</td>
                        <td className="px-4 py-2.5 text-gray-600 max-w-xs truncate" title={item.standard_name}>
                          {item.standard_ref || "—"}
                        </td>
                        <td className="px-4 py-2.5 text-gray-500 text-xs">{item.ai_confidence || "—"}</td>
                        <td className="px-4 py-2.5 text-gray-600">{item.manager_name || "—"}</td>
                        <td className="px-4 py-2.5"><ActionBadge action={item.manager_action} /></td>
                        <td className="px-4 py-2.5 text-gray-500 text-xs">
                          {item.timestamp ? new Date(item.timestamp).toLocaleString("en-GB") : "—"}
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

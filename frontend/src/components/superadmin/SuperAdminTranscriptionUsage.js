import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { Mic, AlertTriangle, Clock, RefreshCw, Loader2, ExternalLink } from "lucide-react";

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

function ModelBadge({ model }) {
  const isPrimary = (model || "").includes("3") || (model || "").includes("pro");
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${
      isPrimary ? "bg-indigo-100 text-indigo-700" : "bg-amber-100 text-amber-700"
    }`}>
      <Mic className="w-3 h-3" />
      {model || "unknown"}
    </span>
  );
}

export default function SuperAdminTranscriptionUsage({ getAuthConfig, orgs }) {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState({ items: [], stats: { total: 0, failed_count: 0, failure_rate_pct: 0, avg_latency_ms: null, avg_audio_duration_seconds: null, warnings_count: 0, by_speech_model: {} } });
  const [orgFilter, setOrgFilter] = useState("");
  const [modelFilter, setModelFilter] = useState("");
  const [failedOnly, setFailedOnly] = useState(false);
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = {};
      if (orgFilter) params.org_id = orgFilter;
      if (modelFilter) params.speech_model = modelFilter;
      if (failedOnly) params.failed_only = true;
      if (fromDate) params.from_date = fromDate;
      if (toDate) params.to_date = toDate + "T23:59:59";
      const res = await axios.get(`${API}/super-admin/transcription-usage-report`, { ...getAuthConfig(), params });
      setData(res.data);
    } catch (e) {
      setError(e?.response?.data?.detail || "Failed to load transcription usage report");
    } finally {
      setLoading(false);
    }
  }, [getAuthConfig, orgFilter, modelFilter, failedOnly, fromDate, toDate]);

  useEffect(() => { load(); }, [load]);

  const models = Object.keys(data.stats.by_speech_model || {});

  return (
    <div data-testid="transcription-usage-report">
      <p className="text-sm text-gray-500 mb-4 max-w-2xl">
        Which AssemblyAI speech model actually transcribed each meeting, how long it took, and whether it
        failed — track the transcription pipeline's health separately from the evidence-analysis step above.
      </p>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 mb-5 bg-white border border-gray-200 rounded-lg p-3">
        <select
          value={orgFilter}
          onChange={e => setOrgFilter(e.target.value)}
          data-testid="transcription-usage-org-filter"
          className="px-2.5 py-1.5 border border-gray-300 rounded text-xs bg-white focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
        >
          <option value="">All Organisations</option>
          {(orgs || []).map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
        <select
          value={modelFilter}
          onChange={e => setModelFilter(e.target.value)}
          data-testid="transcription-usage-model-filter"
          className="px-2.5 py-1.5 border border-gray-300 rounded text-xs bg-white focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
        >
          <option value="">All Speech Models</option>
          {models.map(m => <option key={m} value={m}>{m}</option>)}
        </select>
        <label className="flex items-center gap-1.5 text-xs text-gray-600 px-1">
          <input type="checkbox" checked={failedOnly} onChange={e => setFailedOnly(e.target.checked)} data-testid="transcription-usage-failed-only-checkbox" />
          Failed only
        </label>
        <input
          type="date" value={fromDate} onChange={e => setFromDate(e.target.value)}
          data-testid="transcription-usage-from-date" className="px-2.5 py-1.5 border border-gray-300 rounded text-xs"
        />
        <span className="text-xs text-gray-400">to</span>
        <input
          type="date" value={toDate} onChange={e => setToDate(e.target.value)}
          data-testid="transcription-usage-to-date" className="px-2.5 py-1.5 border border-gray-300 rounded text-xs"
        />
        <button
          onClick={load} data-testid="transcription-usage-refresh-btn"
          className="ml-auto flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-semibold border border-gray-200 text-gray-600 hover:bg-gray-50"
        >
          <RefreshCw className="w-3.5 h-3.5" /> Refresh
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700" data-testid="transcription-usage-error">{error}</div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16 text-gray-400" data-testid="transcription-usage-loading">
          <Loader2 className="w-6 h-6 animate-spin" />
        </div>
      ) : (
        <>
          {/* Stat cards */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-5">
            <StatCard testId="transcription-usage-stat-total" label="Total Transcriptions" value={data.stats.total} />
            <StatCard
              testId="transcription-usage-stat-failed"
              label="Failure Rate"
              value={`${data.stats.failure_rate_pct}%`}
              sub={`${data.stats.failed_count} of ${data.stats.total}`}
              warn={data.stats.failure_rate_pct > 5}
            />
            <StatCard
              testId="transcription-usage-stat-latency"
              label="Avg Latency"
              value={data.stats.avg_latency_ms != null ? `${(data.stats.avg_latency_ms / 1000).toFixed(1)}s` : "—"}
            />
            <StatCard
              testId="transcription-usage-stat-duration"
              label="Avg Audio Length"
              value={data.stats.avg_audio_duration_seconds != null ? `${Math.round(data.stats.avg_audio_duration_seconds / 60)}min` : "—"}
              sub={`${data.stats.warnings_count} with safety warnings`}
            />
            <div className="bg-white border border-gray-200 rounded-lg p-4" data-testid="transcription-usage-stat-by-model">
              <p className="text-xs text-gray-500 font-medium mb-1.5">By Speech Model</p>
              {models.length === 0 ? (
                <p className="text-sm text-gray-400">No data</p>
              ) : (
                <div className="space-y-1">
                  {models.map(m => (
                    <div key={m} className="flex items-center justify-between text-xs">
                      <span className="text-gray-600 truncate">{m}</span>
                      <span className="font-semibold text-[#1E3A8A]">{data.stats.by_speech_model[m]}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Table */}
          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
            {data.items.length === 0 ? (
              <div className="p-8 text-center text-sm text-gray-400" data-testid="transcription-usage-empty-state">
                No tracked transcriptions found for these filters (only meetings processed after this tracking shipped are included).
              </div>
            ) : (
              <div className="overflow-x-auto">
              <table className="w-full text-sm min-w-[720px]" data-testid="transcription-usage-table">
                <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
                  <tr>
                    <th className="text-left px-4 py-2.5 font-medium">Meeting</th>
                    <th className="text-left px-4 py-2.5 font-medium">Organisation</th>
                    <th className="text-left px-4 py-2.5 font-medium">Speech Model</th>
                    <th className="text-left px-4 py-2.5 font-medium">Latency</th>
                    <th className="text-left px-4 py-2.5 font-medium">Audio Length</th>
                    <th className="text-left px-4 py-2.5 font-medium">Date</th>
                    <th className="text-left px-4 py-2.5 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {data.items.map(item => (
                    <tr key={item.meeting_id} data-testid={`transcription-usage-row-${item.meeting_id}`}>
                      <td className="px-4 py-2.5">
                        <a
                          href={`/meetings/${item.meeting_id}/report`}
                          target="_blank" rel="noreferrer"
                          className="flex items-center gap-1 text-[#1E3A8A] hover:underline font-medium"
                          data-testid={`transcription-usage-meeting-link-${item.meeting_id}`}
                        >
                          {item.meeting_title || "Untitled meeting"} <ExternalLink className="w-3 h-3" />
                        </a>
                      </td>
                      <td className="px-4 py-2.5 text-gray-600">{item.org_name || "—"}</td>
                      <td className="px-4 py-2.5">
                        {item.speech_model_used ? <ModelBadge model={item.speech_model_used} /> : <span className="text-xs text-gray-400">—</span>}
                      </td>
                      <td className="px-4 py-2.5 text-gray-600">
                        <span className="inline-flex items-center gap-1">
                          <Clock className="w-3 h-3 text-gray-400" />
                          {item.latency_ms != null ? `${(item.latency_ms / 1000).toFixed(1)}s` : "—"}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-gray-600">
                        {item.audio_duration_seconds != null ? `${Math.round(item.audio_duration_seconds / 60)}min` : "—"}
                      </td>
                      <td className="px-4 py-2.5 text-gray-500 text-xs">
                        {item.transcribed_at ? new Date(item.transcribed_at).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"}
                      </td>
                      <td className="px-4 py-2.5 text-xs max-w-xs">
                        {item.failed ? (
                          <span className="flex items-start gap-1 text-red-600 font-medium" data-testid={`transcription-usage-failed-${item.meeting_id}`}>
                            <AlertTriangle className="w-3 h-3 mt-0.5 flex-shrink-0" />
                            <span className="truncate" title={item.processing_error}>Failed{item.processing_error ? `: ${item.processing_error}` : ""}</span>
                          </span>
                        ) : item.transcript_has_warnings ? (
                          <span className="flex items-center gap-1 text-amber-700">
                            <AlertTriangle className="w-3 h-3 flex-shrink-0" /> Warnings
                          </span>
                        ) : (
                          <span className="text-emerald-600 font-medium">OK</span>
                        )}
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

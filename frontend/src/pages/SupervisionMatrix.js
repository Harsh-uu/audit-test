import React, { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { cachedGet } from "@/utils/apiCache";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import { CheckCircle, Loader2, AlertCircle, LayoutGrid } from "lucide-react";

function fmt(dateStr) {
  if (!dateStr) return "—";
  try { return new Date(dateStr).toLocaleDateString("en-GB", { day: "numeric", month: "short" }); }
  catch { return dateStr; }
}

function cardTheme(s) {
  if (s.is_overdue) return {
    bg: "bg-red-50 border-red-200",
    statusColor: "text-red-600",
    btnCls: "bg-red-600 hover:bg-red-700 text-white",
    statusText: `${Math.abs(s.days_until_due)}d overdue`,
    key: "overdue",
  };
  if (s.days_until_due <= 10) return {
    bg: "bg-amber-50 border-amber-200",
    statusColor: "text-amber-700",
    btnCls: "bg-amber-500 hover:bg-amber-600 text-white",
    statusText: s.days_until_due === 0 ? "Due today" : `Due in ${s.days_until_due}d`,
    key: "due_soon",
  };
  return {
    bg: "bg-emerald-50 border-emerald-200",
    statusColor: "text-emerald-700",
    btnCls: null,
    statusText: `Due ${fmt(s.next_due)}`,
    key: "on_track",
  };
}

function MatrixCard({ s, navigate }) {
  const theme = cardTheme(s);
  const showStart = theme.key !== "on_track";

  return (
    <div
      className={`rounded-lg border p-2.5 flex flex-col gap-2 shadow-sm ${theme.bg}`}
      data-testid={`matrix-card-${s.id}`}
    >
      {/* Type + name */}
      <div className="flex items-start gap-1.5">
        <div
          className="w-2 h-2 rounded-full mt-0.5 flex-shrink-0"
          style={{ backgroundColor: s.meeting_type_color }}
        />
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold text-gray-900 leading-tight truncate">
            {s.meeting_type_name}
          </p>
          <p className="text-[11px] text-gray-500 truncate mt-0.5">{s.staff_name}</p>
        </div>
      </div>

      {/* Status row */}
      <div className="flex items-center justify-between gap-1 mt-auto">
        <span className={`text-[11px] font-medium leading-tight ${theme.statusColor}`}>
          {theme.statusText}
        </span>
        {showStart ? (
          <button
            onClick={() => navigate(
              `/meetings/new?schedule_id=${s.id}` +
              `&title=${encodeURIComponent(s.meeting_type_name + " — " + s.staff_name)}` +
              `&attendee_id=${s.staff_user_id}`
            )}
            className={`text-[10px] font-semibold px-2 py-0.5 rounded flex-shrink-0 transition-colors ${theme.btnCls}`}
            data-testid={`matrix-start-${s.id}`}
          >
            Start
          </button>
        ) : (
          <CheckCircle className="w-3 h-3 text-emerald-500 flex-shrink-0" />
        )}
      </div>
    </div>
  );
}

const FILTERS = [
  { key: "all",      label: "All",       activeCls: "bg-gray-900 text-white",    inactiveCls: "bg-white text-gray-600 border-gray-200" },
  { key: "overdue",  label: "Overdue",   activeCls: "bg-red-600 text-white",     inactiveCls: "bg-white text-red-600 border-red-200" },
  { key: "due_soon", label: "Due Soon",  activeCls: "bg-amber-500 text-white",   inactiveCls: "bg-white text-amber-700 border-amber-200" },
  { key: "on_track", label: "On Track",  activeCls: "bg-emerald-600 text-white", inactiveCls: "bg-white text-emerald-700 border-emerald-200" },
];

export default function SupervisionMatrix() {
  const { getAuthConfig, API } = useAuth();
  const navigate = useNavigate();

  const [schedules, setSchedules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");

  const fetchSchedules = useCallback(async () => {
    try {
      const { data } = await cachedGet(`${API}/schedules/`, getAuthConfig());
      setSchedules(data);
    } catch {
      // silently fail — schedules may not exist yet
    }
    setLoading(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API]);

  useEffect(() => { fetchSchedules(); }, [fetchSchedules]);

  // Counts
  const overdueList  = schedules.filter(s => s.is_overdue);
  const dueSoonList  = schedules.filter(s => !s.is_overdue && s.days_until_due <= 10);
  const onTrackList  = schedules.filter(s => !s.is_overdue && s.days_until_due > 10);

  const counts = { overdue: overdueList.length, due_soon: dueSoonList.length, on_track: onTrackList.length };

  const filtered = filter === "overdue"  ? overdueList
                 : filter === "due_soon" ? dueSoonList
                 : filter === "on_track" ? onTrackList
                 : schedules;

  if (loading) {
    return (
      <Layout>
        <div className="flex items-center justify-center py-24 text-gray-400">
          <Loader2 className="w-5 h-5 animate-spin mr-2" />
          <span className="text-sm">Loading matrix…</span>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="p-6 md:p-8 fade-in">

        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <div className="w-8 h-8 rounded-lg bg-[#1E3A8A]/10 flex items-center justify-center">
            <LayoutGrid className="w-4 h-4 text-[#1E3A8A]" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold text-gray-900 font-display">Supervision Matrix</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              {schedules.length} schedule{schedules.length !== 1 ? "s" : ""} across all staff
            </p>
          </div>

          {/* Summary chips */}
          <div className="ml-auto flex items-center gap-2">
            {overdueList.length > 0 && (
              <span className="text-xs font-semibold bg-red-100 text-red-700 border border-red-200 px-2.5 py-1 rounded-full">
                {overdueList.length} overdue
              </span>
            )}
            {dueSoonList.length > 0 && (
              <span className="text-xs font-semibold bg-amber-100 text-amber-700 border border-amber-200 px-2.5 py-1 rounded-full">
                {dueSoonList.length} due soon
              </span>
            )}
            {onTrackList.length > 0 && (
              <span className="text-xs font-semibold bg-emerald-100 text-emerald-700 border border-emerald-200 px-2.5 py-1 rounded-full">
                {onTrackList.length} on track
              </span>
            )}
          </div>
        </div>

        {/* Filter bar */}
        <div className="flex items-center gap-2 mb-5 flex-wrap">
          {FILTERS.map(f => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`text-xs font-medium px-3 py-1.5 rounded-full border transition-colors ${
                filter === f.key ? f.activeCls : f.inactiveCls
              }`}
              data-testid={`matrix-filter-${f.key}`}
            >
              {f.label}
              {f.key !== "all" && ` (${counts[f.key]})`}
              {f.key === "all" && ` (${schedules.length})`}
            </button>
          ))}
        </div>

        {/* Grid */}
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-gray-400">
            <AlertCircle className="w-8 h-8 mb-3 opacity-30" />
            <p className="text-sm font-medium text-gray-500">
              {schedules.length === 0 ? "No schedules set up yet" : "No schedules in this category"}
            </p>
            {schedules.length === 0 && (
              <button
                onClick={() => navigate("/admin/schedules")}
                className="mt-3 text-xs text-[#1E3A8A] font-medium hover:underline"
              >
                Go to Meeting Schedules →
              </button>
            )}
          </div>
        ) : (
          <div
            className="grid gap-2.5"
            style={{ gridTemplateColumns: "repeat(auto-fill, minmax(148px, 1fr))" }}
            data-testid="supervision-matrix-grid"
          >
            {filtered.map(s => (
              <MatrixCard key={s.id} s={s} navigate={navigate} />
            ))}
          </div>
        )}

      </div>
    </Layout>
  );
}

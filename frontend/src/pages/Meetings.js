import React, { useState, useEffect, useMemo, useRef } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { cachedGet, invalidateCache } from "@/utils/apiCache";
import { useAuth } from "@/context/AuthContext";
import { Skeleton } from "@/components/ui/skeleton";
import { UkDatePicker } from "@/components/ui/uk-date-picker";
import Layout from "@/components/Layout";
import { Plus, Search, Clock, CheckCircle, Mic, FileText, AlertCircle, Users, ChevronRight, ChevronDown, Loader2, ArrowUpDown, X, Calendar, Building2, Trash2, ShieldCheck, Sparkles, Archive } from "lucide-react";

const STATUS_CONFIG = {
  draft:             { label: "Draft",        color: "bg-gray-100 text-gray-700 border-gray-200",       icon: FileText },
  recording:         { label: "Recording",    color: "bg-red-100 text-red-700 border-red-200",           icon: Mic },
  stopped:           { label: "Stopped",      color: "bg-orange-100 text-orange-700 border-orange-200",  icon: Mic },
  processing:        { label: "Processing",   color: "bg-blue-100 text-blue-700 border-blue-200",        icon: Loader2 },
  transcribing:      { label: "Transcribing", color: "bg-blue-100 text-blue-700 border-blue-200",        icon: Loader2 },
  analyzing:         { label: "Analysing",    color: "bg-purple-100 text-purple-700 border-purple-200",  icon: Loader2 },
  in_review:         { label: "In Review",    color: "bg-amber-100 text-amber-700 border-amber-200",     icon: Clock },
  reviewed:          { label: "Reviewed",     color: "bg-teal-100 text-teal-700 border-teal-200",        icon: CheckCircle },
  signed_off:        { label: "Signed Off",   color: "bg-emerald-100 text-emerald-800 border-emerald-200", icon: CheckCircle },
  shared:            { label: "Shared",       color: "bg-emerald-100 text-emerald-800 border-emerald-200", icon: CheckCircle },
  processing_failed: { label: "Failed",       color: "bg-red-100 text-red-700 border-red-200",           icon: AlertCircle },
};

// Order status-breakdown text on collapsed month rows in a sensible reading order.
const STATUS_BREAKDOWN_ORDER = ["draft", "processing", "transcribing", "analyzing", "in_review", "reviewed", "signed_off", "shared", "processing_failed"];

// Filled (active-state) version of each status's badge color, for the quick-filter chips.
const FILLED_STATUS_COLORS = {
  draft:      "bg-gray-600 text-white border-gray-600",
  in_review:  "bg-amber-500 text-white border-amber-500",
  reviewed:   "bg-teal-600 text-white border-teal-600",
  signed_off: "bg-emerald-600 text-white border-emerald-600",
};

const QUICK_FILTERS = [
  { value: "all",       label: "All" },
  { value: "draft",     label: "Draft" },
  { value: "in_review", label: "In Review" },
  { value: "reviewed",  label: "Reviewed" },
  { value: "signed_off",label: "Signed Off" },
];

function StatusBadge({ status }) {
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.draft;
  const Icon = cfg.icon;
  const isSignedOff = status === "signed_off" || status === "shared";
  return (
    <>
      {/* Mobile: shield-tick icon for signed_off, icon-only pill for everything else */}
      {isSignedOff ? (
        <ShieldCheck className="sm:hidden w-6 h-6 text-emerald-600 flex-shrink-0" title="Signed Off" />
      ) : (
        <span className={`sm:hidden inline-flex items-center px-2 py-0.5 text-xs font-medium border rounded-full ${cfg.color}`}>
          <Icon className="w-3 h-3" />
        </span>
      )}
      {/* Desktop: full label pill */}
      <span className={`hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium border rounded-full ${cfg.color}`}>
        <Icon className="w-3 h-3" />
        {cfg.label}
      </span>
    </>
  );
}

function formatDate(dateStr) {
  if (!dateStr) return "—";
  try {
    return new Date(dateStr).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  } catch { return dateStr; }
}

function formatStatusBreakdown(statusCounts) {
  const known = STATUS_BREAKDOWN_ORDER.filter(s => statusCounts[s] > 0);
  const unknown = Object.keys(statusCounts).filter(s => !STATUS_BREAKDOWN_ORDER.includes(s) && statusCounts[s] > 0);
  const titleCase = (s) => s.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  return [...known, ...unknown]
    .map(s => `${statusCounts[s]} ${(STATUS_CONFIG[s] || {}).label || titleCase(s)}`)
    .join(" · ");
}

function currentMonthKeyParts() {
  const d = new Date();
  return { year: d.getFullYear(), month: d.getMonth() + 1, key: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}` };
}

export default function Meetings() {
  const { getAuthConfig, API, user } = useAuth();
  const navigate = useNavigate();
  const { key: currentMonthKey, year: currentYear, month: currentMonth } = useMemo(currentMonthKeyParts, []);

  const [loading, setLoading] = useState(true);
  // month_key -> meeting[] ; current month is always loaded in full up front
  const [monthCache, setMonthCache] = useState({});
  // [{ month_key, year, month, label, count, status_counts }] — every OTHER month, newest first
  const [monthSummaries, setMonthSummaries] = useState([]);
  const [expandedKeys, setExpandedKeys] = useState(() => new Set());
  const [expandingKey, setExpandingKey] = useState(null);

  // Full flat list — only fetched once the user searches/filters, so filtering
  // can cover the whole history instead of just what's currently expanded.
  const [allMeetings, setAllMeetings] = useState(null);
  const [loadingAll, setLoadingAll] = useState(false);

  const [deletingId, setDeletingId] = useState(null);   // meeting id currently pending confirm
  const [deleteLoadingId, setDeleteLoadingId] = useState(null); // in-flight delete
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [sortOrder, setSortOrder] = useState("desc"); // "desc" = newest first
  const [showDateFilter, setShowDateFilter] = useState(false);
  const [orgFilter, setOrgFilter] = useState({ setting_id: "", team_id: "" });
  const [orgStructure, setOrgStructure] = useState({ settings: [], unassigned_users: [] });
  const [showHistorical, setShowHistorical] = useState(false);
  const pollRef = useRef(null);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    Promise.all([
      cachedGet(`${API}/dashboard/`, getAuthConfig()),
      axios.get(`${API}/meetings/?year=${currentYear}&month=${currentMonth}`, getAuthConfig()),
      axios.get(`${API}/meetings/month-summary`, getAuthConfig()),
    ])
      .then(([dashRes, curRes, sumRes]) => {
        if (dashRes.data.org_structure) setOrgStructure(dashRes.data.org_structure);
        setMonthCache({ [currentMonthKey]: curRes.data });
        setMonthSummaries(sumRes.data);
      })
      .catch(err => console.error("Meetings load failed", err.message))
      .finally(() => setLoading(false));

    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Expand/collapse a previous month's divider row — lazy-fetches on first expand only.
  const toggleMonth = async (monthKey, year, month) => {
    if (expandedKeys.has(monthKey)) {
      setExpandedKeys(prev => { const n = new Set(prev); n.delete(monthKey); return n; });
      return;
    }
    setExpandedKeys(prev => new Set(prev).add(monthKey));
    if (monthCache[monthKey]) return; // already fetched earlier this session
    setExpandingKey(monthKey);
    try {
      const { data } = await axios.get(`${API}/meetings/?year=${year}&month=${month}`, getAuthConfig());
      setMonthCache(prev => ({ ...prev, [monthKey]: data }));
    } catch (err) {
      console.error("Failed to load month", monthKey, err.message);
      setExpandedKeys(prev => { const n = new Set(prev); n.delete(monthKey); return n; });
    } finally {
      setExpandingKey(null);
    }
  };

  // PERF-002: only poll while at least one *currently loaded* month has a
  // meeting still mid-pipeline — re-fetches just those loaded months, never
  // the whole history, so this stays cheap however big the org gets.
  useEffect(() => {
    const hasProcessing = Object.values(monthCache).some(list =>
      list.some(m => ["processing", "transcribing", "analyzing"].includes(m.status))
    );
    if (hasProcessing && !pollRef.current) {
      pollRef.current = setInterval(async () => {
        const keys = Object.keys(monthCache);
        await Promise.all(keys.map(async k => {
          const [y, m] = k.split("-").map(Number);
          try {
            const { data } = await axios.get(`${API}/meetings/?year=${y}&month=${m}`, getAuthConfig());
            setMonthCache(prev => ({ ...prev, [k]: data }));
          } catch (err) { /* keep stale data on transient poll failure */ }
        }));
      }, 15000);
    } else if (!hasProcessing && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [monthCache]);

  const allLoadedMeetings = useMemo(() => Object.values(monthCache).flat(), [monthCache]);
  const activeMeetingsLoaded = useMemo(() => allLoadedMeetings.filter(m => !m.is_historical), [allLoadedMeetings]);
  const historicalMeetings = useMemo(() => allLoadedMeetings.filter(m => m.is_historical === true), [allLoadedMeetings]);

  const hasActiveFilters = search || statusFilter !== "all" || dateFrom || dateTo || orgFilter.setting_id || orgFilter.team_id;

  // Chip counts reflect whatever is currently loaded — once a filter triggers
  // the full-history fetch, switch the counts to that complete set too so
  // they don't visibly change again once the filter is cleared.
  const chipCountSource = (hasActiveFilters && allMeetings) ? allMeetings.filter(m => !m.is_historical) : activeMeetingsLoaded;

  // The moment any search/filter is applied, fetch the complete history once
  // (like the old "Load all meetings" button) so filtering isn't limited to
  // whatever months happen to be expanded — this is the one place the page
  // deliberately trades speed for completeness.
  useEffect(() => {
    if (hasActiveFilters && allMeetings === null && !loadingAll) {
      setLoadingAll(true);
      axios.get(`${API}/meetings/`, getAuthConfig())
        .then(({ data }) => setAllMeetings(data))
        .catch(err => console.error("Failed to load full meeting history", err.message))
        .finally(() => setLoadingAll(false));
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasActiveFilters]);

  const searchSource = useMemo(() => {
    const list = hasActiveFilters ? (allMeetings || []) : activeMeetingsLoaded;
    return list.filter(m => !m.is_historical);
  }, [hasActiveFilters, allMeetings, activeMeetingsLoaded]);

  const filteredMeetings = useMemo(() => {
    const q = search.toLowerCase();
    return searchSource
      .filter(m => {
        if (q) {
          const titleMatch = m.title?.toLowerCase().includes(q);
          const attendeeMatch = (m.attendees || []).some(a =>
            (typeof a === "string" ? a : a?.name || "").toLowerCase().includes(q)
          );
          if (!titleMatch && !attendeeMatch) return false;
        }
        if (statusFilter !== "all" && m.status !== statusFilter) return false;
        if (dateFrom) {
          const mDate = new Date(m.date || m.created_at || 0);
          if (mDate < new Date(dateFrom)) return false;
        }
        if (dateTo) {
          const mDate = new Date(m.date || m.created_at || 0);
          if (mDate > new Date(dateTo + "T23:59:59")) return false;
        }
        if (orgFilter.team_id && m.team_id !== orgFilter.team_id) return false;
        if (!orgFilter.team_id && orgFilter.setting_id && m.setting_id !== orgFilter.setting_id) return false;
        return true;
      })
      .sort((a, b) => {
        const da = new Date(a.date || a.created_at || 0).getTime();
        const db = new Date(b.date || b.created_at || 0).getTime();
        return sortOrder === "desc" ? db - da : da - db;
      });
  }, [searchSource, search, statusFilter, dateFrom, dateTo, sortOrder, orgFilter]);

  const clearFilters = () => {
    setSearch("");
    setStatusFilter("all");
    setDateFrom("");
    setDateTo("");
    setOrgFilter({ setting_id: "", team_id: "" });
  };

  const getMeetingAction = (meeting) => {
    if (["draft", "stopped", "recording"].includes(meeting.status)) return () => navigate(`/meetings/${meeting.id}/record`);
    return () => navigate(`/meetings/${meeting.id}/report`);
  };

  const canDelete = user?.role === "admin";

  const handleDelete = async (e, meetingId) => {
    e.stopPropagation();
    if (deletingId !== meetingId) { setDeletingId(meetingId); return; }
    setDeleteLoadingId(meetingId);
    try {
      await axios.delete(`${API}/meetings/${meetingId}`, getAuthConfig());
      setMonthCache(prev => {
        const next = {};
        for (const [k, list] of Object.entries(prev)) next[k] = list.filter(m => m.id !== meetingId);
        return next;
      });
      if (allMeetings !== null) setAllMeetings(prev => prev.filter(m => m.id !== meetingId));
      // Bust the dashboard cache so navigating back re-fetches a fresh list
      invalidateCache("/dashboard");
    } catch (err) {
      alert(err.response?.data?.detail || "Delete failed");
    } finally {
      setDeleteLoadingId(null);
      setDeletingId(null);
    }
  };

  const renderMeetingCard = (meeting) => (
    <div
      key={meeting.id}
      onClick={deletingId === meeting.id ? undefined : getMeetingAction(meeting)}
      className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm hover:shadow-md hover:-translate-y-0.5 transition-all duration-200 cursor-pointer"
      data-testid={`meeting-item-${meeting.id}`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 mb-1">
            <h3 className="font-medium text-gray-900 truncate">{meeting.title}</h3>
          </div>
          <div className="flex items-center gap-4 text-xs text-gray-500">
            <span>{formatDate(meeting.date || meeting.created_at)}</span>
            {meeting.location && <span>{meeting.location}</span>}
            {meeting.attendees?.length > 0 && (
              <span className="flex items-center gap-1">
                <Users className="w-3 h-3" />
                {meeting.attendees.length} attendee{meeting.attendees.length !== 1 ? "s" : ""}
              </span>
            )}
            {meeting.sign_off_manager_name && (
              <span>Manager: {meeting.sign_off_manager_name}</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {/* Dynamic Prep shortcut — only for draft/stopped meetings, manager/admin */}
          {(user?.role === "manager" || user?.role === "admin") && ["draft", "stopped"].includes(meeting.status) && (
            <button
              onClick={e => { e.stopPropagation(); navigate(`/meetings/${meeting.id}/prepare`); }}
              className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-indigo-700 bg-indigo-50 border border-indigo-200 rounded-md hover:bg-indigo-100 transition-colors"
              title="Dynamic Supervision Prep"
              data-testid={`prepare-btn-${meeting.id}`}
            >
              <Sparkles className="w-3 h-3" /> Prepare
            </button>
          )}
          <StatusBadge status={meeting.status} />
          {canDelete && (
            deletingId === meeting.id ? (
              <div className="flex items-center gap-1.5" onClick={e => e.stopPropagation()}>
                <span className="text-xs text-red-600 font-medium">Delete?</span>
                <button
                  onClick={e => handleDelete(e, meeting.id)}
                  disabled={deleteLoadingId === meeting.id}
                  className="text-xs px-2 py-1 rounded bg-red-600 text-white hover:bg-red-700 transition-colors disabled:opacity-60"
                  data-testid={`delete-confirm-btn-${meeting.id}`}
                >
                  {deleteLoadingId === meeting.id ? "..." : "Yes"}
                </button>
                <button
                  onClick={e => { e.stopPropagation(); setDeletingId(null); }}
                  className="text-xs px-2 py-1 rounded border border-gray-300 text-gray-600 hover:bg-gray-50 transition-colors"
                  data-testid={`delete-cancel-btn-${meeting.id}`}
                >
                  No
                </button>
              </div>
            ) : (
              <button
                onClick={e => handleDelete(e, meeting.id)}
                className="p-1.5 text-gray-300 hover:text-red-500 hover:bg-red-50 rounded transition-colors"
                title="Delete meeting"
                data-testid={`delete-meeting-btn-${meeting.id}`}
              >
                <Trash2 className="w-4 h-4" />
              </button>
            )
          )}
          <ChevronRight className="w-4 h-4 text-gray-400 mt-0.5" />
        </div>
      </div>
    </div>
  );

  const currentMonthMeetings = (monthCache[currentMonthKey] || []).filter(m => !m.is_historical);
  const hasAnyMeetingsAtAll = currentMonthMeetings.length > 0 || monthSummaries.length > 0;

  return (
    <Layout>
      <div className="p-6 md:p-8 fade-in">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">Meetings</h1>
            <p className="text-sm text-gray-500 mt-0.5">Manage your supervision meetings and compliance evidence</p>
          </div>
          <button
            onClick={() => navigate("/meetings/new")}
            data-testid="new-meeting-btn"
            className="inline-flex items-center gap-2 bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors"
          >
            <Plus className="w-4 h-4" />
            New Meeting
          </button>
        </div>

        {/* Search & filter bar */}
        <div className="space-y-3 mb-5">
          <div className="flex flex-col sm:flex-row gap-2">
            {/* Search */}
            <div className="relative flex-1">
              <Search className="absolute left-3 top-2.5 w-4 h-4 text-gray-400" />
              <input
                type="text"
                placeholder="Search by title or attendee name..."
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="w-full pl-9 pr-4 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
                data-testid="search-input"
              />
              {search && (
                <button onClick={() => setSearch("")} className="absolute right-2.5 top-2.5 text-gray-400 hover:text-gray-600">
                  <X className="w-4 h-4" />
                </button>
              )}
            </div>

            {/* Date filter toggle */}
            <button
              onClick={() => setShowDateFilter(!showDateFilter)}
              data-testid="date-filter-toggle"
              className={`flex items-center gap-2 px-3 py-2 border rounded-md text-sm transition-colors ${
                (dateFrom || dateTo) ? "border-[#1E3A8A] bg-blue-50 text-[#1E3A8A]" : "border-gray-300 text-gray-600 hover:bg-gray-50"
              }`}
            >
              <Calendar className="w-4 h-4" />
              Date
            </button>

            {/* Sort toggle */}
            <button
              onClick={() => setSortOrder(o => o === "desc" ? "asc" : "desc")}
              data-testid="sort-toggle"
              className="flex items-center gap-2 px-3 py-2 border border-gray-300 rounded-md text-sm text-gray-600 hover:bg-gray-50 transition-colors"
              title={sortOrder === "desc" ? "Newest first" : "Oldest first"}
            >
              <ArrowUpDown className="w-4 h-4" />
              {sortOrder === "desc" ? "Newest" : "Oldest"}
            </button>

            {/* Clear all */}
            {hasActiveFilters && (
              <button
                onClick={clearFilters}
                data-testid="clear-filters-btn"
                className="flex items-center gap-1.5 px-3 py-2 text-sm text-red-600 hover:text-red-700 hover:bg-red-50 border border-red-200 rounded-md transition-colors"
              >
                <X className="w-3.5 h-3.5" />
                Clear
              </button>
            )}
          </div>

          {/* Date range picker */}
          {showDateFilter && (
            <div className="flex flex-wrap gap-2 items-center p-3 bg-gray-50 border border-gray-200 rounded-md" data-testid="date-range-picker">
              <label className="text-xs font-medium text-gray-500 whitespace-nowrap">From</label>
              <UkDatePicker
                value={dateFrom}
                onChange={setDateFrom}
                className="flex-1 min-w-0 max-w-full px-2 py-1.5 text-sm"
                testId="date-from-input"
              />
              <label className="text-xs font-medium text-gray-500">To</label>
              <UkDatePicker
                value={dateTo}
                onChange={setDateTo}
                minDate={dateFrom ? new Date(dateFrom) : undefined}
                className="flex-1 min-w-0 max-w-full px-2 py-1.5 text-sm"
                testId="date-to-input"
              />
              {(dateFrom || dateTo) && (
                <button onClick={() => { setDateFrom(""); setDateTo(""); }} className="text-xs text-gray-400 hover:text-gray-600">
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          )}

          {/* Quick status chips + org filter (same row, filter pushed right) */}
          <div className="flex items-center gap-2 flex-wrap">
            {QUICK_FILTERS.map(f => (
              <button
                key={f.value}
                onClick={() => setStatusFilter(f.value)}
                data-testid={`filter-chip-${f.value}`}
                className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                  f.value === "all"
                    ? (statusFilter === "all"
                        ? "bg-[#1E3A8A] text-white border-[#1E3A8A]"
                        : "bg-white text-gray-600 border-gray-200 hover:border-[#1E3A8A] hover:text-[#1E3A8A]")
                    : (statusFilter === f.value
                        ? FILLED_STATUS_COLORS[f.value]
                        : `${STATUS_CONFIG[f.value].color} hover:opacity-80`)
                }`}
              >
                {f.label}
                {f.value !== "all" && (
                  <span className="ml-1.5 opacity-70">
                    {chipCountSource.filter(m => m.status === f.value).length}
                  </span>
                )}
              </button>
            ))}

            {/* Org filter (admin/manager only, when org has settings) — pushed to the right */}
            {orgStructure.settings?.length > 0 && (
              <div className="flex items-center gap-2 flex-wrap ml-auto" data-testid="org-filter-bar">
                <Building2 className="w-3.5 h-3.5 text-gray-400" />
                <span className="text-xs text-gray-500 font-medium">Filter:</span>
                <select
                  value={orgFilter.setting_id}
                  onChange={e => setOrgFilter({ setting_id: e.target.value, team_id: "" })}
                  className="px-2 py-1 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#1E3A8A] bg-white"
                  data-testid="setting-filter-select"
                >
                  <option value="">All Settings</option>
                  {orgStructure.settings.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
                {orgFilter.setting_id && (
                  <select
                    value={orgFilter.team_id}
                    onChange={e => setOrgFilter(f => ({ ...f, team_id: e.target.value }))}
                    className="px-2 py-1 border border-gray-300 rounded text-xs focus:outline-none focus:ring-1 focus:ring-[#1E3A8A] bg-white"
                    data-testid="team-filter-select"
                  >
                    <option value="">All Teams</option>
                    {(orgStructure.settings.find(s => s.id === orgFilter.setting_id)?.teams || []).map(t => (
                      <option key={t.id} value={t.id}>{t.name}</option>
                    ))}
                  </select>
                )}
              </div>
            )}

            {/* Result count */}
            {hasActiveFilters && !loadingAll && (
              <span className={orgStructure.settings?.length > 0 ? "w-full text-xs text-gray-400" : "ml-auto text-xs text-gray-400"} data-testid="filtered-count">
                {filteredMeetings.length} matching meeting{filteredMeetings.length !== 1 ? "s" : ""} (searched full history)
              </span>
            )}
          </div>
        </div>

        {/* Meetings list */}
        {loading ? (
          <div className="space-y-2" aria-busy="true" aria-label="Loading meetings">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0 space-y-2">
                    <Skeleton className="h-4 w-2/3" />
                    <div className="flex items-center gap-4">
                      <Skeleton className="h-3 w-24" />
                      <Skeleton className="h-3 w-16" />
                      <Skeleton className="h-3 w-20" />
                    </div>
                  </div>
                  <Skeleton className="h-5 w-20 rounded-full flex-shrink-0" />
                </div>
              </div>
            ))}
          </div>
        ) : hasActiveFilters ? (
          // ── Filtered/search mode — flat list over the FULL meeting history ──
          loadingAll ? (
            <div className="space-y-2" aria-busy="true" aria-label="Searching full meeting history">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
                  <Skeleton className="h-4 w-2/3 mb-2" />
                  <Skeleton className="h-3 w-40" />
                </div>
              ))}
            </div>
          ) : filteredMeetings.length === 0 ? (
            <div className="text-center py-16 bg-white border border-gray-200 rounded-lg shadow-sm" data-testid="empty-meetings">
              <FileText className="w-10 h-10 text-gray-300 mx-auto mb-3" />
              <p className="text-gray-500 font-medium">No meetings found</p>
              <p className="text-gray-400 text-sm mt-1">Try adjusting your search or filters</p>
              <button onClick={clearFilters} className="mt-4 inline-flex items-center gap-2 text-[#1E3A8A] px-4 py-2 rounded-md text-sm font-medium border border-[#1E3A8A] hover:bg-blue-50 transition-colors">
                <X className="w-4 h-4" />
                Clear filters
              </button>
            </div>
          ) : (
            <div className="space-y-2" data-testid="meetings-list">
              {filteredMeetings.map(renderMeetingCard)}
            </div>
          )
        ) : !hasAnyMeetingsAtAll ? (
          <div className="text-center py-16 bg-white border border-gray-200 rounded-lg shadow-sm" data-testid="empty-meetings">
            <FileText className="w-10 h-10 text-gray-300 mx-auto mb-3" />
            <p className="text-gray-500 font-medium">No meetings found</p>
            <p className="text-gray-400 text-sm mt-1">Create your first supervision meeting</p>
            <button onClick={() => navigate("/meetings/new")} className="mt-4 inline-flex items-center gap-2 bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors">
              <Plus className="w-4 h-4" />
              New Meeting
            </button>
          </div>
        ) : (
          // ── Default grouped view — current month in full, past months collapsed ──
          <div className="space-y-2" data-testid="meetings-list">
            {currentMonthMeetings.length > 0 ? (
              currentMonthMeetings
                .slice()
                .sort((a, b) => {
                  const da = new Date(a.date || a.created_at || 0).getTime();
                  const db = new Date(b.date || b.created_at || 0).getTime();
                  return sortOrder === "desc" ? db - da : da - db;
                })
                .map(renderMeetingCard)
            ) : (
              <p className="text-sm text-gray-400 py-3">No meetings yet this month.</p>
            )}

            {monthSummaries.map(ms => {
              const isExpanded = expandedKeys.has(ms.month_key);
              const isExpanding = expandingKey === ms.month_key;
              return (
                <div key={ms.month_key} data-testid={`month-group-${ms.month_key}`}>
                  <button
                    onClick={() => toggleMonth(ms.month_key, ms.year, ms.month)}
                    data-testid={`month-toggle-${ms.month_key}`}
                    className="w-full flex items-center gap-3 py-3 group"
                  >
                    <span className="text-sm font-medium text-gray-600 group-hover:text-[#1E3A8A] whitespace-nowrap transition-colors">
                      {ms.label}
                    </span>
                    <span className="flex-1 h-px bg-gray-200 group-hover:bg-[#1E3A8A]/30 transition-colors" />
                    <span className="text-xs text-gray-400 whitespace-nowrap">
                      {ms.count} meeting{ms.count !== 1 ? "s" : ""}
                      {formatStatusBreakdown(ms.status_counts) && (
                        <span className="hidden sm:inline"> · {formatStatusBreakdown(ms.status_counts)}</span>
                      )}
                    </span>
                    <ChevronDown className={`w-4 h-4 text-gray-400 group-hover:text-[#1E3A8A] transition-transform duration-200 ${isExpanded ? "rotate-180" : ""}`} />
                  </button>
                  {isExpanded && (
                    <div className="space-y-2 pb-2" data-testid={`month-meetings-${ms.month_key}`}>
                      {isExpanding ? (
                        [...Array(Math.min(ms.count, 3))].map((_, i) => (
                          <div key={i} className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
                            <Skeleton className="h-4 w-2/3 mb-2" />
                            <Skeleton className="h-3 w-40" />
                          </div>
                        ))
                      ) : (
                        (monthCache[ms.month_key] || [])
                          .filter(m => !m.is_historical)
                          .slice()
                          .sort((a, b) => {
                            const da = new Date(a.date || a.created_at || 0).getTime();
                            const db = new Date(b.date || b.created_at || 0).getTime();
                            return sortOrder === "desc" ? db - da : da - db;
                          })
                          .map(renderMeetingCard)
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Historical meetings — staff who have since moved teams (from currently loaded months) */}
        {historicalMeetings.length > 0 && (
          <div className="mt-8" data-testid="historical-section">
            <button
              onClick={() => setShowHistorical(v => !v)}
              className="flex items-center gap-2 text-sm text-gray-400 hover:text-gray-600 transition-colors mb-1 group"
              data-testid="historical-toggle-btn"
            >
              <Archive className="w-4 h-4" />
              <span className="font-medium">Historical Meetings</span>
              <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">
                {historicalMeetings.length}
              </span>
              <ChevronDown className={`w-4 h-4 transition-transform duration-200 ${showHistorical ? "rotate-180" : ""}`} />
            </button>
            <p className="text-xs text-gray-400 mb-3">
              Staff in these meetings have since moved to a different team.
            </p>
            {showHistorical && (
              <div className="space-y-2 opacity-50" data-testid="historical-meetings-list">
                {historicalMeetings.map(meeting => (
                  <div
                    key={meeting.id}
                    onClick={getMeetingAction(meeting)}
                    className="bg-gray-50 border border-gray-200 rounded-lg p-4 shadow-sm cursor-pointer hover:opacity-75 transition-opacity"
                    data-testid={`historical-meeting-item-${meeting.id}`}
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <Archive className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                          <h3 className="font-medium text-gray-600 truncate">{meeting.title}</h3>
                        </div>
                        <div className="flex items-center gap-4 text-xs text-gray-400">
                          <span>{formatDate(meeting.date || meeting.created_at)}</span>
                          {meeting.attendees?.length > 0 && (
                            <span className="flex items-center gap-1">
                              <Users className="w-3 h-3" />
                              {meeting.attendees.length} attendee{meeting.attendees.length !== 1 ? "s" : ""}
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        <StatusBadge status={meeting.status} />
                        <ChevronRight className="w-4 h-4 text-gray-300 mt-0.5" />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </Layout>
  );
}

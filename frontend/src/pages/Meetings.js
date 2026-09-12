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

export default function Meetings() {
  const { getAuthConfig, API, user } = useAuth();
  const navigate = useNavigate();
  const [meetings, setMeetings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [hasMoreMeetings, setHasMoreMeetings] = useState(false);
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
    // Initial load: single combined endpoint (1 round-trip instead of several)
    cachedGet(`${API}/dashboard/`, getAuthConfig())
      .then(r => {
        const d = r.data;
        setMeetings(d.meetings || []);
        setHasMoreMeetings(d.has_more_meetings || false);
        if (d.org_structure) setOrgStructure(d.org_structure);
      })
      .catch(err => console.error("Meetings load failed", err.message))
      .finally(() => setLoading(false));

    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Lightweight poll — keeps meeting statuses live without re-fetching everything
  const fetchMeetingsOnly = async () => {
    try {
      const { data } = await axios.get(`${API}/meetings/`, getAuthConfig());
      setMeetings(data);
      // Full list is now loaded — no more "Load all" needed
      setHasMoreMeetings(false);
    } catch (err) {
      console.error("Failed to refresh meetings", err.message);
    }
  };

  // PERF-002: only poll while at least one meeting is still mid-pipeline
  // (processing/transcribing/analyzing) — same pattern as UploadSupervision.js,
  // rather than an unconditional 15s interval regardless of activity.
  useEffect(() => {
    const hasProcessing = meetings.some(m => ["processing", "transcribing", "analyzing"].includes(m.status));
    if (hasProcessing && !pollRef.current) {
      pollRef.current = setInterval(fetchMeetingsOnly, 15000);
    } else if (!hasProcessing && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meetings]);

  // Called when user clicks "Load all meetings" — fetches full untruncated list
  const loadAllMeetings = async () => {
    setLoadingAll(true);
    try {
      const { data } = await axios.get(`${API}/meetings/`, getAuthConfig());
      setMeetings(data);
      setHasMoreMeetings(false);
    } catch (err) {
      console.error("Failed to load all meetings", err.message);
    } finally {
      setLoadingAll(false);
    }
  };

  // Legacy alias so delete handler can call fetchMeetings after delete
  const fetchMeetings = fetchMeetingsOnly;

  const activeMeetings = useMemo(() => meetings.filter(m => !m.is_historical), [meetings]);
  const historicalMeetings = useMemo(() => meetings.filter(m => m.is_historical === true), [meetings]);

  const filteredMeetings = useMemo(() => {
    const q = search.toLowerCase();
    return activeMeetings
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
  }, [activeMeetings, search, statusFilter, dateFrom, dateTo, sortOrder, orgFilter]);

  const hasActiveFilters = search || statusFilter !== "all" || dateFrom || dateTo || orgFilter.setting_id || orgFilter.team_id;

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
      setMeetings(prev => prev.filter(m => m.id !== meetingId));
      // Bust the dashboard cache so navigating back re-fetches a fresh list
      invalidateCache("/dashboard");
    } catch (err) {
      alert(err.response?.data?.detail || "Delete failed");
    } finally {
      setDeleteLoadingId(null);
      setDeletingId(null);
    }
  };

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

          {/* Org filter (admin/manager only, when org has settings) */}
          {orgStructure.settings?.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap" data-testid="org-filter-bar">
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

          {/* Quick status chips */}
          <div className="flex items-center gap-2 flex-wrap">
            {QUICK_FILTERS.map(f => (
              <button
                key={f.value}
                onClick={() => setStatusFilter(f.value)}
                data-testid={`filter-chip-${f.value}`}
                className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                  statusFilter === f.value
                    ? "bg-[#1E3A8A] text-white border-[#1E3A8A]"
                    : "bg-white text-gray-600 border-gray-200 hover:border-[#1E3A8A] hover:text-[#1E3A8A]"
                }`}
              >
                {f.label}
                {f.value !== "all" && (
                  <span className="ml-1.5 opacity-70">
                    {activeMeetings.filter(m => m.status === f.value).length}
                  </span>
                )}
              </button>
            ))}
            {/* Result count */}
            {hasActiveFilters && (
              <span className="ml-auto text-xs text-gray-400">
                {filteredMeetings.length} of {meetings.length} meetings
              </span>
            )}
            {/* Pagination hint */}
            {hasMoreMeetings && !hasActiveFilters && (
              <span className="ml-auto text-xs text-gray-400">
                Showing first 50 meetings
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
        ) : filteredMeetings.length === 0 ? (
          <div className="text-center py-16 bg-white border border-gray-200 rounded-lg shadow-sm" data-testid="empty-meetings">
            <FileText className="w-10 h-10 text-gray-300 mx-auto mb-3" />
            <p className="text-gray-500 font-medium">No meetings found</p>
            <p className="text-gray-400 text-sm mt-1">
              {hasActiveFilters ? "Try adjusting your search or filters" : "Create your first supervision meeting"}
            </p>
            {hasActiveFilters ? (
              <button onClick={clearFilters} className="mt-4 inline-flex items-center gap-2 text-[#1E3A8A] px-4 py-2 rounded-md text-sm font-medium border border-[#1E3A8A] hover:bg-blue-50 transition-colors">
                <X className="w-4 h-4" />
                Clear filters
              </button>
            ) : (
              <button onClick={() => navigate("/meetings/new")} className="mt-4 inline-flex items-center gap-2 bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors">
                <Plus className="w-4 h-4" />
                New Meeting
              </button>
            )}
          </div>
        ) : (
          <div className="space-y-2" data-testid="meetings-list">
            {filteredMeetings.map(meeting => (
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
            ))}
          </div>
        )}

        {/* Load all meetings button — shown when initial 50-meeting batch may be truncated */}
        {hasMoreMeetings && (
          <div className="flex justify-center mt-4">
            <button
              onClick={loadAllMeetings}
              disabled={loadingAll}
              data-testid="load-all-meetings-btn"
              className="flex items-center gap-2 text-sm text-blue-600 hover:text-blue-700 font-medium transition-colors disabled:opacity-50"
            >
              {loadingAll ? (
                <>
                  <span className="w-4 h-4 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
                  Loading all meetings…
                </>
              ) : (
                "Load all meetings"
              )}
            </button>
          </div>
        )}

        {/* Historical meetings — staff who have since moved teams */}
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

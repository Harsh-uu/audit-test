import React, { useState, useEffect, useMemo } from "react";
import { useNavigate, Link } from "react-router-dom";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import { Plus, Search, Clock, CheckCircle, Mic, FileText, AlertCircle, Users, ChevronRight, Loader, ArrowUpDown, X, Calendar, Building2, Trash2, ShieldCheck } from "lucide-react";

const STATUS_CONFIG = {
  draft:             { label: "Draft",        color: "bg-gray-100 text-gray-700 border-gray-200",       icon: FileText },
  recording:         { label: "Recording",    color: "bg-red-100 text-red-700 border-red-200",           icon: Mic },
  stopped:           { label: "Stopped",      color: "bg-orange-100 text-orange-700 border-orange-200",  icon: Mic },
  processing:        { label: "Processing",   color: "bg-blue-100 text-blue-700 border-blue-200",        icon: Loader },
  transcribing:      { label: "Transcribing", color: "bg-blue-100 text-blue-700 border-blue-200",        icon: Loader },
  analyzing:         { label: "Analysing",    color: "bg-purple-100 text-purple-700 border-purple-200",  icon: Loader },
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

function DueCard({ s, navigate }) {
  const isOverdue = s.is_overdue;
  const daysAbs = Math.abs(s.days_until_due);
  return (
    <div
      className={`flex-shrink-0 w-52 rounded-lg border p-3.5 shadow-sm flex flex-col gap-2 ${
        isOverdue ? "bg-red-50 border-red-200" : "bg-blue-50 border-blue-200"
      }`}
      data-testid={`due-card-${s.id}`}
    >
      <div className="flex items-start gap-2">
        <div className="w-2 h-2 rounded-full mt-1 flex-shrink-0" style={{ backgroundColor: s.meeting_type_color }} />
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold text-gray-900 truncate">{s.meeting_type_name}</p>
          <p className="text-xs text-gray-500 truncate">{s.staff_name}</p>
        </div>
      </div>
      <div className="flex items-center justify-between mt-auto gap-2">
        <span className={`text-xs font-medium ${isOverdue ? "text-red-600" : "text-blue-700"}`}>
          {isOverdue ? `${daysAbs}d overdue` : `Due ${formatDate(s.next_due)}`}
        </span>
        <button
          onClick={() => navigate(
            `/meetings/new?schedule_id=${s.id}` +
            `&title=${encodeURIComponent(s.meeting_type_name + " — " + s.staff_name)}` +
            `&attendee_id=${s.staff_user_id}`
          )}
          className={`text-xs font-medium px-2 py-1 rounded flex-shrink-0 transition-colors ${
            isOverdue
              ? "bg-red-600 text-white hover:bg-red-700"
              : "bg-[#1E3A8A] text-white hover:bg-[#1E40AF]"
          }`}
          data-testid={`due-card-start-${s.id}`}
        >
          Start
        </button>
      </div>
    </div>
  );
}

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

export default function Dashboard() {
  const { getAuthConfig, API, user } = useAuth();
  const navigate = useNavigate();
  const [meetings, setMeetings] = useState([]);
  const [loading, setLoading] = useState(true);
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
  const [dueMeetings, setDueMeetings] = useState([]);
  const [dueLoading, setDueLoading] = useState(false);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    fetchMeetings();
    if (user?.role === "admin" || user?.role === "manager") {
      axios.get(`${API}/org/structure`, getAuthConfig()).then(r => setOrgStructure(r.data)).catch(() => {});
      setDueLoading(true);
      axios.get(`${API}/schedules/due`, getAuthConfig())
        .then(r => setDueMeetings(r.data))
        .catch(() => {})
        .finally(() => setDueLoading(false));
    }
    const interval = setInterval(fetchMeetings, 15000);
    return () => clearInterval(interval);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const fetchMeetings = async () => {
    try {
      const { data } = await axios.get(`${API}/meetings/`, getAuthConfig());
      setMeetings(data);
    } catch (err) {
      console.error("Failed to load meetings", err);
    } finally {
      setLoading(false);
    }
  };

  const filteredMeetings = useMemo(() => {
    const q = search.toLowerCase();
    return meetings
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
  }, [meetings, search, statusFilter, dateFrom, dateTo, sortOrder, orgFilter]);

  const hasActiveFilters = search || statusFilter !== "all" || dateFrom || dateTo || orgFilter.setting_id || orgFilter.team_id;

  const clearFilters = () => {
    setSearch("");
    setStatusFilter("all");
    setDateFrom("");
    setDateTo("");
    setOrgFilter({ setting_id: "", team_id: "" });
  };

  const stats = {
    total: meetings.length,
    inReview: meetings.filter(m => ["in_review", "reviewed"].includes(m.status)).length,
    signedOff: meetings.filter(m => ["signed_off", "shared"].includes(m.status)).length,
  };

  const getMeetingAction = (meeting) => {
    if (["draft", "stopped", "recording"].includes(meeting.status)) return () => navigate(`/meetings/${meeting.id}/record`);
    return () => navigate(`/meetings/${meeting.id}/report`);
  };

  const canDelete = user?.role === "admin" || user?.role === "manager";

  const handleDelete = async (e, meetingId) => {
    e.stopPropagation();
    if (deletingId !== meetingId) { setDeletingId(meetingId); return; }
    setDeleteLoadingId(meetingId);
    try {
      await axios.delete(`${API}/meetings/${meetingId}`, getAuthConfig());
      setMeetings(prev => prev.filter(m => m.id !== meetingId));
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
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
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

        {/* Stats */}
        <div className="grid grid-cols-3 gap-4 mb-6">
          {[
            { label: "Total Meetings", value: stats.total, icon: FileText, color: "text-[#1E3A8A]" },
            { label: "In Review",      value: stats.inReview, icon: Clock, color: "text-amber-600" },
            { label: "Signed Off",     value: stats.signedOff, icon: CheckCircle, color: "text-emerald-600" },
          ].map(({ label, value, icon: Icon, color }) => (
            <div key={label} className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</span>
                <Icon className={`w-4 h-4 ${color}`} />
              </div>
              <p className={`text-2xl font-bold ${color}`}>{value}</p>
            </div>
          ))}
        </div>

        {/* Due This Month Widget — admin/manager only */}
        {(user?.role === "admin" || user?.role === "manager") && (dueMeetings.length > 0 || dueLoading) && (
          <div className="mb-6" data-testid="due-this-month-widget">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2 flex-wrap">
                <Calendar className="w-4 h-4 text-[#1E3A8A]" />
                <h2 className="text-sm font-semibold text-gray-700">Due This Month</h2>
                {!dueLoading && dueMeetings.filter(s => s.is_overdue).length > 0 && (
                  <span className="text-xs font-medium text-red-600 bg-red-50 border border-red-200 px-2 py-0.5 rounded-full">
                    {dueMeetings.filter(s => s.is_overdue).length} overdue
                  </span>
                )}
                {!dueLoading && dueMeetings.filter(s => !s.is_overdue).length > 0 && (
                  <span className="text-xs text-gray-400">
                    {dueMeetings.filter(s => !s.is_overdue).length} upcoming
                  </span>
                )}
              </div>
              <Link
                to="/admin/schedules"
                className="text-xs text-[#1E3A8A] hover:underline flex items-center gap-0.5"
                data-testid="due-view-all-link"
              >
                View all <ChevronRight className="w-3 h-3" />
              </Link>
            </div>
            {dueLoading ? (
              <div className="flex gap-3 overflow-x-auto pb-1">
                {[1, 2, 3].map(i => (
                  <div key={i} className="flex-shrink-0 w-52 h-20 bg-gray-100 rounded-lg animate-pulse" />
                ))}
              </div>
            ) : (
              <div className="flex gap-3 overflow-x-auto pb-2">
                {dueMeetings.map(s => (
                  <DueCard key={s.id} s={s} navigate={navigate} />
                ))}
              </div>
            )}
          </div>
        )}

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
              <input
                type="date"
                value={dateFrom}
                onChange={e => setDateFrom(e.target.value)}
                className="flex-1 min-w-0 max-w-full px-2 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
                data-testid="date-from-input"
              />
              <label className="text-xs font-medium text-gray-500">To</label>
              <input
                type="date"
                value={dateTo}
                onChange={e => setDateTo(e.target.value)}
                min={dateFrom}
                className="flex-1 min-w-0 max-w-full px-2 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
                data-testid="date-to-input"
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
                    {meetings.filter(m => m.status === f.value).length}
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
          </div>
        </div>

        {/* Meetings list */}
        {loading ? (
          <div className="flex items-center justify-center py-16 text-gray-400">
            <div className="flex items-center gap-3">
              <div className="w-5 h-5 border-2 border-[#1E3A8A] border-t-transparent rounded-full spin"></div>
              <span className="text-sm">Loading meetings...</span>
            </div>
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
                      <StatusBadge status={meeting.status} />
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
      </div>
    </Layout>
  );
}

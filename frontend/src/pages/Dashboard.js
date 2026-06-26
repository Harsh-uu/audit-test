import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import { Plus, Search, Clock, CheckCircle, Mic, FileText, AlertCircle, Users, ChevronRight, Loader } from "lucide-react";

const STATUS_CONFIG = {
  draft: { label: "Draft", color: "bg-gray-100 text-gray-700 border-gray-200", icon: FileText },
  recording: { label: "Recording", color: "bg-red-100 text-red-700 border-red-200", icon: Mic },
  stopped: { label: "Stopped", color: "bg-orange-100 text-orange-700 border-orange-200", icon: Mic },
  processing: { label: "Processing", color: "bg-blue-100 text-blue-700 border-blue-200", icon: Loader },
  transcribing: { label: "Transcribing", color: "bg-blue-100 text-blue-700 border-blue-200", icon: Loader },
  analyzing: { label: "Analysing", color: "bg-purple-100 text-purple-700 border-purple-200", icon: Loader },
  in_review: { label: "In Review", color: "bg-amber-100 text-amber-700 border-amber-200", icon: Clock },
  reviewed: { label: "Reviewed", color: "bg-teal-100 text-teal-700 border-teal-200", icon: CheckCircle },
  signed_off: { label: "Signed Off", color: "bg-emerald-100 text-emerald-800 border-emerald-200", icon: CheckCircle },
  shared: { label: "Shared", color: "bg-emerald-100 text-emerald-800 border-emerald-200", icon: CheckCircle },
  processing_failed: { label: "Failed", color: "bg-red-100 text-red-700 border-red-200", icon: AlertCircle },
};

function StatusBadge({ status }) {
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.draft;
  const Icon = cfg.icon;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium border rounded-full ${cfg.color}`}>
      <Icon className="w-3 h-3" />
      {cfg.label}
    </span>
  );
}

function formatDate(dateStr) {
  if (!dateStr) return "—";
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  } catch { return dateStr; }
}

export default function Dashboard() {
  const { getAuthConfig, API } = useAuth();
  const navigate = useNavigate();
  const [meetings, setMeetings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");

  useEffect(() => {
    fetchMeetings();
    const interval = setInterval(fetchMeetings, 15000); // poll for status updates
    return () => clearInterval(interval);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  const filteredMeetings = meetings.filter(m => {
    const matchSearch = m.title?.toLowerCase().includes(search.toLowerCase());
    const matchFilter = filter === "all" || m.status === filter;
    return matchSearch && matchFilter;
  });

  const stats = {
    total: meetings.length,
    inReview: meetings.filter(m => ["in_review", "reviewed"].includes(m.status)).length,
    signedOff: meetings.filter(m => ["signed_off", "shared"].includes(m.status)).length,
  };

  const getMeetingAction = (meeting) => {
    if (meeting.status === "draft" || meeting.status === "stopped") {
      return () => navigate(`/meetings/${meeting.id}/record`);
    }
    if (["processing", "transcribing", "analyzing"].includes(meeting.status)) {
      return () => navigate(`/meetings/${meeting.id}/report`);
    }
    return () => navigate(`/meetings/${meeting.id}/report`);
  };

  return (
    <Layout>
      <div className="p-6 md:p-8 fade-in">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900" style={{fontFamily:'Work Sans,sans-serif'}}>Meetings</h1>
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
            { label: "In Review", value: stats.inReview, icon: Clock, color: "text-amber-600" },
            { label: "Signed Off", value: stats.signedOff, icon: CheckCircle, color: "text-emerald-600" },
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

        {/* Filters */}
        <div className="flex flex-col sm:flex-row gap-3 mb-5">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-2.5 w-4 h-4 text-gray-400" />
            <input
              type="text"
              placeholder="Search meetings..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full pl-9 pr-4 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
              data-testid="search-input"
            />
          </div>
          <select
            value={filter}
            onChange={e => setFilter(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] bg-white"
            data-testid="status-filter"
          >
            <option value="all">All statuses</option>
            <option value="draft">Draft</option>
            <option value="in_review">In Review</option>
            <option value="reviewed">Reviewed</option>
            <option value="signed_off">Signed Off</option>
            <option value="shared">Shared</option>
          </select>
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
              {search ? "Try adjusting your search" : "Create your first supervision meeting"}
            </p>
            {!search && (
              <button
                onClick={() => navigate("/meetings/new")}
                className="mt-4 inline-flex items-center gap-2 bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors"
              >
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
                onClick={getMeetingAction(meeting)}
                className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm hover:shadow-md hover:-translate-y-0.5 transition-all duration-200 cursor-pointer"
                data-testid={`meeting-item-${meeting.id}`}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3 mb-1">
                      <h3 className="font-medium text-gray-900 truncate" style={{fontFamily:'Work Sans,sans-serif'}}>{meeting.title}</h3>
                      <StatusBadge status={meeting.status} />
                    </div>
                    <div className="flex items-center gap-4 text-xs text-gray-500">
                      <span>{formatDate(meeting.date)}</span>
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
                  <ChevronRight className="w-4 h-4 text-gray-400 flex-shrink-0 mt-0.5" />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}

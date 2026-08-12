import React, { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import { ArrowLeft, Users, UserCheck, Calendar, MapPin, AlertCircle, Sparkles, ChevronRight } from "lucide-react";

// Return current local time in datetime-local format (YYYY-MM-DDTHH:mm)
function localNow() {
  const now = new Date();
  const pad = n => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

const TYPE_LABELS = {
  supervision: "Supervision",
  appraisal: "Appraisal",
  observation: "Observation",
  team_meeting: "Team Meeting",
  competency_review: "Competency Review",
  other: "Meeting",
};

function buildTitle(meetingType, selectedUsers) {
  const label = TYPE_LABELS[meetingType] || "Meeting";
  if (selectedUsers.length === 0) return label;
  if (selectedUsers.length === 1) return `${label} with ${selectedUsers[0].name}`;
  if (selectedUsers.length === 2) return `${label} with ${selectedUsers[0].name} & ${selectedUsers[1].name}`;
  return `${label} with ${selectedUsers[0].name} & ${selectedUsers.length - 1} others`;
}

export default function NewMeeting() {
  const { getAuthConfig, API } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const prefillAttendeeId = searchParams.get("attendee_id") || "";
  const prefillScheduleId = searchParams.get("schedule_id") || "";

  const [form, setForm] = useState({
    date: localNow(),
    location: "",
    meeting_type: "supervision",
    attendee_ids: prefillAttendeeId ? [prefillAttendeeId] : [],
    sign_off_manager_id: "",
    schedule_id: prefillScheduleId || undefined,
  });

  useEffect(() => {
    axios.get(`${API}/admin/users?ignore_scope=true`, getAuthConfig())
      .then(r => setUsers(r.data))
      .catch(console.error);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const attendees = users.filter(u => u.role !== "shared_reviewer");
  const managers = users.filter(
    u => ["manager", "admin"].includes(u.role) && form.attendee_ids.includes(u.id)
  );

  // Supervisees = selected non-manager attendees (for title + prep scoping)
  const selectedAttendees = users.filter(u => form.attendee_ids.includes(u.id));
  const supervisees = selectedAttendees.filter(u => !["manager", "admin"].includes(u.role));
  const titlePreview = buildTitle(form.meeting_type, supervisees.length > 0 ? supervisees : selectedAttendees);

  const toggleAttendee = (userId) => {
    setForm(f => {
      const newIds = f.attendee_ids.includes(userId)
        ? f.attendee_ids.filter(id => id !== userId)
        : [...f.attendee_ids, userId];
      const newManagerId = newIds.includes(f.sign_off_manager_id) ? f.sign_off_manager_id : "";
      return { ...f, attendee_ids: newIds, sign_off_manager_id: newManagerId };
    });
  };

  const submit = async () => {
    if (form.attendee_ids.length === 0) return setError("Please select at least one attendee");
    setLoading(true);
    setError("");
    try {
      const { data } = await axios.post(`${API}/meetings/`, {
        ...form,
        title: titlePreview,
      }, getAuthConfig());
      navigate(`/meetings/${data.id}/prepare?from=new`);
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to create meeting");
      setLoading(false);
    }
  };

  return (
    <Layout>
      <div className="h-full flex flex-col fade-in" style={{ minHeight: "calc(100vh - 56px)" }}>

        {/* ── Top bar: title + step indicator ──────────────────────────────── */}
        <div className="px-6 pt-6 pb-4 border-b border-gray-100 bg-white">
          <div className="flex items-center justify-between mb-3">
            <h1 className="text-2xl font-semibold text-gray-900 font-display">New Meeting</h1>
            <button onClick={() => navigate("/dashboard")} className="flex items-center gap-1.5 text-gray-400 hover:text-gray-600 text-xs flex-shrink-0">
              <ArrowLeft className="w-3.5 h-3.5" />Back to Dashboard
            </button>
          </div>

          <div className="flex items-center gap-4">
            {/* Step indicator */}
            <div className="flex items-center gap-2 text-sm font-medium text-[#1E3A8A]">
              <div className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold bg-[#1E3A8A] text-white">1</div>
              <span>Setup</span>
            </div>
            <ChevronRight className="w-4 h-4 text-gray-300" />
            <div className="flex items-center gap-2 text-sm font-medium text-gray-400">
              <div className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold bg-gray-200 text-gray-500">2</div>
              <span className="flex items-center gap-1"><Sparkles className="w-3 h-3" />Prepare</span>
            </div>

            {/* Title preview — grows to fill space */}
            <div className="ml-4 flex items-center gap-2 bg-blue-50 border border-blue-100 rounded-lg px-3 py-1.5 flex-1 min-w-0">
              <span className="text-xs text-blue-400 font-medium whitespace-nowrap">Meeting title:</span>
              <span className="text-sm font-semibold text-blue-900 truncate" data-testid="meeting-title-preview">{titlePreview}</span>
            </div>
          </div>

          {error && (
            <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-md p-3 mt-3 text-sm" data-testid="form-error">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />{error}
            </div>
          )}
        </div>

        {/* ── Two-panel body ─────────────────────────────────────────────────── */}
        <div className="flex flex-col md:flex-row flex-1 overflow-auto md:overflow-hidden">

          {/* LEFT PANEL — config fields + action button */}
          <div className="w-full md:w-80 flex-shrink-0 border-b md:border-b-0 md:border-r border-gray-100 bg-gray-50 flex flex-col p-5 gap-5 md:overflow-y-auto">

            <div>
              <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Meeting Type</label>
              <select
                value={form.meeting_type}
                onChange={e => setForm(f => ({ ...f, meeting_type: e.target.value }))}
                className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] bg-white"
                data-testid="meeting-type-select"
              >
                <option value="supervision">Supervision</option>
                <option value="appraisal">Appraisal</option>
                <option value="observation">Observation</option>
                <option value="team_meeting">Team Meeting</option>
                <option value="competency_review">Competency Review</option>
                <option value="other">Other</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">
                <Calendar className="inline w-3 h-3 mr-1 text-gray-400" />Date &amp; Time
              </label>
              <input
                type="datetime-local"
                value={form.date}
                onChange={e => setForm(f => ({ ...f, date: e.target.value }))}
                className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] bg-white"
                data-testid="meeting-date-input"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">
                <MapPin className="inline w-3 h-3 mr-1 text-gray-400" />Location <span className="font-normal normal-case">(optional)</span>
              </label>
              <input
                type="text"
                value={form.location}
                onChange={e => setForm(f => ({ ...f, location: e.target.value }))}
                placeholder="e.g. Meeting Room A"
                className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] bg-white"
                data-testid="meeting-location-input"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">
                <UserCheck className="inline w-3 h-3 mr-1 text-gray-400" />Sign-off Manager
              </label>
              <select
                value={form.sign_off_manager_id}
                onChange={e => setForm(f => ({ ...f, sign_off_manager_id: e.target.value }))}
                className="w-full px-3 py-2 border border-gray-200 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] bg-white disabled:text-gray-400"
                data-testid="manager-select"
                disabled={managers.length === 0}
              >
                <option value="">{managers.length === 0 ? "Select a manager as attendee first" : "Select responsible manager…"}</option>
                {managers.map(m => <option key={m.id} value={m.id}>{m.name} ({m.role})</option>)}
              </select>
              {managers.length === 0 && (
                <p className="text-xs text-amber-600 mt-1.5">Tick a manager in the attendees list to enable this.</p>
              )}
            </div>

            {/* Spacer pushes button to bottom */}
            <div className="flex-1" />

            <div className="pt-3 border-t border-gray-200">
              {form.attendee_ids.length > 0 && (
                <p className="text-xs text-gray-400 text-center mb-2">{form.attendee_ids.length} attendee{form.attendee_ids.length !== 1 ? "s" : ""} selected</p>
              )}
              <button
                onClick={submit}
                disabled={loading || form.attendee_ids.length === 0}
                className="w-full bg-[#1E3A8A] text-white py-3 rounded-md text-sm font-semibold hover:bg-[#1E40AF] transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
                data-testid="create-meeting-btn"
              >
                {loading
                  ? <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  : <Sparkles className="w-4 h-4" />
                }
                Create &amp; Prepare
              </button>
            </div>
          </div>

          {/* RIGHT PANEL — attendees (scrolls independently) */}
          <div className="flex-1 overflow-y-auto p-5">
            <div className="flex items-center gap-2 mb-4">
              <Users className="w-4 h-4 text-[#1E3A8A]" />
              <h3 className="font-semibold text-gray-800 text-sm font-display">Attendees</h3>
              {form.attendee_ids.length > 0 && (
                <span className="ml-auto text-xs bg-[#1E3A8A] text-white px-2.5 py-0.5 rounded-full font-medium">
                  {form.attendee_ids.length} selected
                </span>
              )}
            </div>

            <div className="space-y-2">
              {attendees.map(user => (
                <label
                  key={user.id}
                  className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                    form.attendee_ids.includes(user.id)
                      ? "border-[#1E3A8A] bg-blue-50"
                      : "border-gray-200 bg-white hover:border-blue-200 hover:bg-blue-50/40"
                  }`}
                  data-testid={`attendee-${user.id}`}
                >
                  <input
                    type="checkbox"
                    checked={form.attendee_ids.includes(user.id)}
                    onChange={() => toggleAttendee(user.id)}
                    className="accent-[#1E3A8A] flex-shrink-0"
                  />
                  <div className="w-8 h-8 rounded-full bg-[#1E3A8A] text-white flex items-center justify-center text-xs font-bold flex-shrink-0">
                    {user.name[0].toUpperCase()}
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">{user.name}</p>
                    <p className="text-xs text-gray-400 capitalize truncate">{user.role} &middot; {user.email}</p>
                  </div>
                </label>
              ))}
              {attendees.length === 0 && (
                <p className="text-sm text-gray-400 text-center py-8">No users found. Add users in the Admin panel.</p>
              )}
            </div>
          </div>

        </div>
      </div>
    </Layout>
  );
}

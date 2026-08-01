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
    axios.get(`${API}/admin/users`, getAuthConfig())
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
      <div className="p-6 md:p-8 max-w-2xl mx-auto fade-in">
        <button onClick={() => navigate("/dashboard")} className="flex items-center gap-2 text-gray-500 hover:text-gray-700 text-sm mb-6">
          <ArrowLeft className="w-4 h-4" />Back to Dashboard
        </button>

        <h1 className="text-2xl font-semibold text-gray-900 mb-1 font-display">New Meeting</h1>
        <p className="text-sm text-gray-500 mb-6">Set up your supervision meeting before recording</p>

        {/* Step indicator — now 2 steps */}
        <div className="flex items-center gap-2 mb-8">
          <div className="flex items-center gap-2 text-sm font-medium text-[#1E3A8A]">
            <div className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold bg-[#1E3A8A] text-white">1</div>
            <span>Meeting Setup</span>
          </div>
          <ChevronRight className="w-4 h-4 text-gray-300" />
          <div className="flex items-center gap-2 text-sm font-medium text-gray-400">
            <div className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold bg-gray-200 text-gray-500">2</div>
            <span><Sparkles className="w-3 h-3 inline mr-0.5" />Prepare</span>
          </div>
        </div>

        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-md p-3 mb-4 text-sm" data-testid="form-error">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />{error}
          </div>
        )}

        <div className="space-y-5">
          {/* Title preview + submit — always at the top so the title is visible as fields are filled */}
          <div className="bg-blue-50 border border-blue-200 rounded-lg px-4 py-3 flex items-center gap-2">
            <span className="text-xs text-blue-500 font-medium whitespace-nowrap">Meeting title:</span>
            <span className="text-sm font-semibold text-blue-900 flex-1" data-testid="meeting-title-preview">{titlePreview}</span>
          </div>

          <button
            onClick={submit}
            disabled={loading}
            className="w-full bg-[#1E3A8A] text-white py-2.5 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors disabled:opacity-60 flex items-center justify-center gap-2"
            data-testid="create-meeting-btn"
          >
            {loading && <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full spin"></div>}
            <Sparkles className="w-4 h-4" />
            Create &amp; Prepare
          </button>

          {/* Meeting type first — most likely to change */}
          <div className="bg-white border border-gray-200 rounded-lg p-6 shadow-sm space-y-5">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Meeting type</label>
              <select
                value={form.meeting_type}
                onChange={e => setForm(f => ({ ...f, meeting_type: e.target.value }))}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] bg-white"
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
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                <Calendar className="inline w-3.5 h-3.5 mr-1 text-gray-400" />Date &amp; Time
              </label>
              <input
                type="datetime-local"
                value={form.date}
                onChange={e => setForm(f => ({ ...f, date: e.target.value }))}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
                data-testid="meeting-date-input"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                <MapPin className="inline w-3.5 h-3.5 mr-1 text-gray-400" />Location (optional)
              </label>
              <input
                type="text"
                value={form.location}
                onChange={e => setForm(f => ({ ...f, location: e.target.value }))}
                placeholder="e.g. Meeting Room A"
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
                data-testid="meeting-location-input"
              />
            </div>
          </div>

          {/* Attendees */}
          <div className="bg-white border border-gray-200 rounded-lg p-6 shadow-sm">
            <div className="flex items-center gap-2 mb-4">
              <Users className="w-4 h-4 text-[#1E3A8A]" />
              <h3 className="font-medium text-gray-900 font-display">Attendees</h3>
              {form.attendee_ids.length > 0 && (
                <span className="ml-auto text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-medium">{form.attendee_ids.length} selected</span>
              )}
            </div>
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {attendees.map(user => (
                <label
                  key={user.id}
                  className={`flex items-center gap-3 p-3 rounded-md border cursor-pointer transition-colors ${
                    form.attendee_ids.includes(user.id) ? "border-[#1E3A8A] bg-blue-50" : "border-gray-200 hover:bg-gray-50"
                  }`}
                  data-testid={`attendee-${user.id}`}
                >
                  <input
                    type="checkbox"
                    checked={form.attendee_ids.includes(user.id)}
                    onChange={() => toggleAttendee(user.id)}
                    className="accent-[#1E3A8A]"
                  />
                  <div className="w-8 h-8 rounded-full bg-[#1E3A8A] text-white flex items-center justify-center text-xs font-semibold">
                    {user.name[0].toUpperCase()}
                  </div>
                  <div>
                    <p className="text-sm font-medium text-gray-900">{user.name}</p>
                    <p className="text-xs text-gray-500 capitalize">{user.role} &middot; {user.email}</p>
                  </div>
                </label>
              ))}
              {attendees.length === 0 && (
                <p className="text-sm text-gray-400 text-center py-4">No users found. Add users in the Admin panel.</p>
              )}
            </div>
          </div>

          {/* Sign-off Manager */}
          <div className="bg-white border border-gray-200 rounded-lg p-6 shadow-sm">
            <div className="flex items-center gap-2 mb-4">
              <UserCheck className="w-4 h-4 text-[#1E3A8A]" />
              <h3 className="font-medium text-gray-900 font-display">Sign-off Manager</h3>
            </div>
            <select
              value={form.sign_off_manager_id}
              onChange={e => setForm(f => ({ ...f, sign_off_manager_id: e.target.value }))}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] bg-white"
              data-testid="manager-select"
              disabled={managers.length === 0}
            >
              <option value="">{managers.length === 0 ? "Select a manager as an attendee first..." : "Select responsible manager..."}</option>
              {managers.map(m => <option key={m.id} value={m.id}>{m.name} ({m.role})</option>)}
            </select>
            {managers.length === 0 && (
              <p className="text-xs text-amber-600 mt-1">Tick a manager or admin in the attendees list above to enable this.</p>
            )}
          </div>

        </div>
      </div>
    </Layout>
  );
}

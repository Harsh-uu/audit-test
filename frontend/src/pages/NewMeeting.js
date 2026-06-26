import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import { ArrowLeft, Users, UserCheck, Calendar, MapPin, AlertCircle, ChevronRight } from "lucide-react";

export default function NewMeeting() {
  const { getAuthConfig, API } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState(1); // 1: details, 2: attendees + manager
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState({
    title: "",
    date: new Date().toISOString().slice(0, 16),
    location: "",
    meeting_type: "supervision",
    attendee_ids: [],
    sign_off_manager_id: "",
  });

  useEffect(() => {
    axios.get(`${API}/admin/users`, getAuthConfig())
      .then(r => setUsers(r.data))
      .catch(console.error);
  }, []);

  const managers = users.filter(u => ["manager", "admin"].includes(u.role));
  const attendees = users.filter(u => u.role !== "shared_reviewer");

  const toggleAttendee = (userId) => {
    setForm(f => ({
      ...f,
      attendee_ids: f.attendee_ids.includes(userId)
        ? f.attendee_ids.filter(id => id !== userId)
        : [...f.attendee_ids, userId],
    }));
  };

  const submit = async () => {
    if (!form.title.trim()) return setError("Please enter a meeting title");
    setLoading(true);
    setError("");
    try {
      const { data } = await axios.post(`${API}/meetings/`, form, getAuthConfig());
      navigate(`/meetings/${data.id}/record`);
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to create meeting");
      setLoading(false);
    }
  };

  return (
    <Layout>
      <div className="p-6 md:p-8 max-w-2xl mx-auto fade-in">
        <button onClick={() => navigate("/dashboard")} className="flex items-center gap-2 text-gray-500 hover:text-gray-700 text-sm mb-6">
          <ArrowLeft className="w-4 h-4" />
          Back to Dashboard
        </button>

        <h1 className="text-2xl font-semibold text-gray-900 mb-1" style={{fontFamily:'Work Sans,sans-serif'}}>New Meeting</h1>
        <p className="text-sm text-gray-500 mb-6">Set up your supervision meeting before recording</p>

        {/* Step indicator */}
        <div className="flex items-center gap-3 mb-8">
          {[1, 2].map(s => (
            <React.Fragment key={s}>
              <div className={`flex items-center gap-2 text-sm font-medium ${step >= s ? "text-[#1E3A8A]" : "text-gray-400"}`}>
                <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold ${step >= s ? "bg-[#1E3A8A] text-white" : "bg-gray-200 text-gray-500"}`}>{s}</div>
                <span>{s === 1 ? "Meeting Details" : "Attendees & Manager"}</span>
              </div>
              {s < 2 && <ChevronRight className="w-4 h-4 text-gray-300" />}
            </React.Fragment>
          ))}
        </div>

        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-md p-3 mb-4 text-sm" data-testid="form-error">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            {error}
          </div>
        )}

        {step === 1 && (
          <div className="bg-white border border-gray-200 rounded-lg p-6 shadow-sm space-y-5">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Meeting title <span className="text-red-500">*</span></label>
              <input
                type="text"
                value={form.title}
                onChange={e => setForm(f => ({...f, title: e.target.value}))}
                placeholder="e.g. Monthly supervision with Jane Smith"
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
                data-testid="meeting-title-input"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                <Calendar className="inline w-3.5 h-3.5 mr-1 text-gray-400" />
                Date &amp; Time
              </label>
              <input
                type="datetime-local"
                value={form.date}
                onChange={e => setForm(f => ({...f, date: e.target.value}))}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
                data-testid="meeting-date-input"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                <MapPin className="inline w-3.5 h-3.5 mr-1 text-gray-400" />
                Location (optional)
              </label>
              <input
                type="text"
                value={form.location}
                onChange={e => setForm(f => ({...f, location: e.target.value}))}
                placeholder="e.g. Meeting Room A"
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
                data-testid="meeting-location-input"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Meeting type</label>
              <select
                value={form.meeting_type}
                onChange={e => setForm(f => ({...f, meeting_type: e.target.value}))}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] bg-white"
                data-testid="meeting-type-select"
              >
                <option value="supervision">Supervision</option>
                <option value="appraisal">Appraisal</option>
                <option value="team_meeting">Team Meeting</option>
                <option value="competency_review">Competency Review</option>
                <option value="other">Other</option>
              </select>
            </div>
            <div className="pt-2">
              <button
                onClick={() => {
                  if (!form.title.trim()) return setError("Please enter a meeting title");
                  setError("");
                  setStep(2);
                }}
                className="w-full bg-[#1E3A8A] text-white py-2.5 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors"
                data-testid="step1-next-btn"
              >
                Continue
              </button>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-5">
            {/* Attendees */}
            <div className="bg-white border border-gray-200 rounded-lg p-6 shadow-sm">
              <div className="flex items-center gap-2 mb-4">
                <Users className="w-4 h-4 text-[#1E3A8A]" />
                <h3 className="font-medium text-gray-900" style={{fontFamily:'Work Sans,sans-serif'}}>Meeting Attendees</h3>
                {form.attendee_ids.length > 0 && (
                  <span className="ml-auto text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-medium">{form.attendee_ids.length} selected</span>
                )}
              </div>
              <div className="space-y-2 max-h-64 overflow-y-auto">
                {attendees.map(user => (
                  <label
                    key={user.id}
                    className={`flex items-center gap-3 p-3 rounded-md border cursor-pointer transition-colors ${
                      form.attendee_ids.includes(user.id)
                        ? "border-[#1E3A8A] bg-blue-50"
                        : "border-gray-200 hover:bg-gray-50"
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
                  <p className="text-sm text-gray-400 text-center py-4">No users available. Add users in the Admin panel.</p>
                )}
              </div>
            </div>

            {/* Manager */}
            <div className="bg-white border border-gray-200 rounded-lg p-6 shadow-sm">
              <div className="flex items-center gap-2 mb-4">
                <UserCheck className="w-4 h-4 text-[#1E3A8A]" />
                <h3 className="font-medium text-gray-900" style={{fontFamily:'Work Sans,sans-serif'}}>Sign-off Manager</h3>
              </div>
              <select
                value={form.sign_off_manager_id}
                onChange={e => setForm(f => ({...f, sign_off_manager_id: e.target.value}))}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] bg-white"
                data-testid="manager-select"
              >
                <option value="">Select responsible manager...</option>
                {managers.map(m => (
                  <option key={m.id} value={m.id}>{m.name} ({m.role})</option>
                ))}
              </select>
              <p className="text-xs text-gray-500 mt-2">The assigned manager will be responsible for final sign-off after all attendees have reviewed.</p>
            </div>

            <div className="flex gap-3">
              <button onClick={() => setStep(1)} className="flex-1 border border-gray-300 text-gray-700 py-2.5 rounded-md text-sm font-medium hover:bg-gray-50 transition-colors">
                Back
              </button>
              <button
                onClick={submit}
                disabled={loading}
                className="flex-1 bg-[#1E3A8A] text-white py-2.5 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors disabled:opacity-60 flex items-center justify-center gap-2"
                data-testid="create-meeting-btn"
              >
                {loading && <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full spin"></div>}
                Create Meeting &amp; Record
              </button>
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
}

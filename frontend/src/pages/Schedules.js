import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import {
  Calendar, Plus, Trash2, Edit2, Check, X, Loader, AlertCircle,
  CheckCircle, Users, ChevronDown, ChevronRight, Zap, Clock,
} from "lucide-react";

const FREQ_OPTIONS = [
  { value: "monthly",      label: "Monthly"   },
  { value: "quarterly",    label: "Quarterly" },
  { value: "annual",       label: "Annual"    },
  { value: "custom_weeks", label: "Custom (set weeks)" },
];

function freqLabel(frequency) {
  if (!frequency) return "";
  if (frequency.startsWith("weeks_")) {
    const n = frequency.split("_")[1];
    return `Every ${n} week${n !== "1" ? "s" : ""}`;
  }
  return { monthly: "Monthly", quarterly: "Quarterly", annual: "Annual" }[frequency] || frequency;
}

/** Renders a frequency <select> + optional week-count input for "Custom (set weeks)" */
function FreqSelector({ value, onChange, className, testId }) {
  const isCustom = value && value.startsWith("weeks_");
  const weeks = isCustom ? (parseInt(value.split("_")[1]) || 6) : 6;

  return (
    <div>
      <select
        value={isCustom ? "custom_weeks" : (value || "monthly")}
        onChange={e => {
          if (e.target.value === "custom_weeks") onChange("weeks_6");
          else onChange(e.target.value);
        }}
        className={className}
        data-testid={testId}
      >
        {FREQ_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      {isCustom && (
        <div className="flex items-center gap-2 mt-2">
          <span className="text-xs text-gray-500">Every</span>
          <input
            type="number"
            min="1"
            max="52"
            value={weeks}
            onChange={e => onChange(`weeks_${Math.max(1, parseInt(e.target.value) || 1)}`)}
            className="w-16 px-2 py-1.5 border border-gray-300 rounded-md text-sm text-center focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
            data-testid={testId ? `${testId}-weeks` : undefined}
          />
          <span className="text-xs text-gray-500">weeks</span>
        </div>
      )}
    </div>
  );
}

const FREQ_LABELS = { monthly: "Monthly", quarterly: "Quarterly", annual: "Annual" };

function avatarColor(name = "") {
  const palette = ["#1E3A8A","#7C3AED","#059669","#D97706","#DC2626","#0891B2","#9333EA"];
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) % palette.length;
  return palette[h];
}

const COLOR_OPTIONS = [
  "#3B82F6","#10B981","#F59E0B","#8B5CF6","#EF4444","#EC4899","#06B6D4","#84CC16",
];

function fmt(dateStr) {
  if (!dateStr) return "—";
  try { return new Date(dateStr).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }); }
  catch { return dateStr; }
}

function DueBadge({ nextDue, isOverdue, daysUntil }) {
  if (isOverdue) {
    const days = Math.abs(daysUntil);
    return <span className="text-xs font-medium text-red-600 bg-red-50 px-2 py-0.5 rounded-full">{days}d overdue</span>;
  }
  if (daysUntil <= 7)  return <span className="text-xs font-medium text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full">Due {fmt(nextDue)}</span>;
  if (daysUntil <= 31) return <span className="text-xs font-medium text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full">Due {fmt(nextDue)}</span>;
  return <span className="text-xs text-gray-400">{fmt(nextDue)}</span>;
}

const inputCls = "w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]";
const selectCls = `${inputCls} bg-white`;

export default function Schedules() {
  const { getAuthConfig, API } = useAuth();
  const navigate = useNavigate();

  const [meetingTypes, setMeetingTypes] = useState([]);
  const [schedules, setSchedules] = useState([]);
  const [allUsers, setAllUsers] = useState([]);
  const [orgStructure, setOrgStructure] = useState({ settings: [], unassigned_users: [] });
  const [loading, setLoading] = useState(true);

  // Flash
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  // Expanded staff rows
  const [expandedStaff, setExpandedStaff] = useState(new Set());

  // Meeting type form
  const [showAddType, setShowAddType] = useState(false);
  const [editingType, setEditingType] = useState(null);
  const [typeForm, setTypeForm] = useState({ name: "", default_frequency: "monthly", color: "#3B82F6" });
  const [savingType, setSavingType] = useState(false);

  // Add schedule per-person modal
  const [showAddSchedule, setShowAddSchedule] = useState(null); // staffUserId
  const [scheduleForm, setScheduleForm] = useState({ meeting_type_id: "", frequency: "monthly", start_date: today() });
  const [savingSchedule, setSavingSchedule] = useState(false);
  const [scheduleError, setScheduleError] = useState("");

  // Bulk add modal
  const [showBulk, setShowBulk] = useState(false);
  const [bulkForm, setBulkForm] = useState({ meeting_type_id: "", frequency: "monthly", start_date: today(), scope: "all", team_id: "" });
  const [bulkSaving, setBulkSaving] = useState(false);
  const [bulkPreview, setBulkPreview] = useState(null);
  const [bulkError, setBulkError] = useState("");

  function today() {
    return new Date().toISOString().split("T")[0];
  }

  const flash = (msg, isErr = false) => {
    if (isErr) setError(msg); else setMessage(msg);
    setTimeout(() => { setError(""); setMessage(""); }, 4000);
  };

  const fetchAll = useCallback(async () => {
    try {
      const [typesRes, schedRes, usersRes, structRes] = await Promise.all([
        axios.get(`${API}/schedules/meeting-types`, getAuthConfig()),
        axios.get(`${API}/schedules/`, getAuthConfig()),
        axios.get(`${API}/admin/users`, getAuthConfig()),
        axios.get(`${API}/org/structure`, getAuthConfig()),
      ]);
      setMeetingTypes(typesRes.data);
      setSchedules(schedRes.data);
      setAllUsers(usersRes.data);
      setOrgStructure(structRes.data);
    } catch (err) {
      flash("Failed to load schedules", true);
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // When a meeting type is selected in schedule form, default its frequency
  useEffect(() => {
    if (scheduleForm.meeting_type_id) {
      const mt = meetingTypes.find(t => t.id === scheduleForm.meeting_type_id);
      if (mt) setScheduleForm(f => ({ ...f, frequency: mt.default_frequency }));
    }
  }, [scheduleForm.meeting_type_id, meetingTypes]);

  useEffect(() => {
    if (bulkForm.meeting_type_id) {
      const mt = meetingTypes.find(t => t.id === bulkForm.meeting_type_id);
      if (mt) setBulkForm(f => ({ ...f, frequency: mt.default_frequency }));
    }
  }, [bulkForm.meeting_type_id, meetingTypes]);

  // ── Meeting Types CRUD ────────────────────────────────────────────────────
  const saveType = async () => {
    if (!typeForm.name.trim()) return;
    setSavingType(true);
    try {
      if (editingType) {
        await axios.put(`${API}/schedules/meeting-types/${editingType.id}`, typeForm, getAuthConfig());
        flash("Meeting type updated");
        setEditingType(null);
      } else {
        await axios.post(`${API}/schedules/meeting-types`, typeForm, getAuthConfig());
        flash("Meeting type created");
        setShowAddType(false);
      }
      setTypeForm({ name: "", default_frequency: "monthly", color: "#3B82F6" });
      fetchAll();
    } catch (err) { flash(err.response?.data?.detail || "Failed to save", true); }
    setSavingType(false);
  };

  const deleteType = async (t) => {
    if (!window.confirm(`Delete meeting type "${t.name}"? Existing schedules using it will still run.`)) return;
    try {
      await axios.delete(`${API}/schedules/meeting-types/${t.id}`, getAuthConfig());
      flash("Meeting type deleted");
      fetchAll();
    } catch (err) { flash("Failed to delete", true); }
  };

  // ── Edit schedule inline ─────────────────────────────────────────────────
  const [editingSchedule, setEditingSchedule] = useState(null); // {id, frequency, start_date, meeting_type_id}
  const [savingEdit, setSavingEdit] = useState(false);
  const [editError, setEditError] = useState("");

  const saveEdit = async () => {
    if (!editingSchedule.start_date) return setEditError("Start date is required");
    setSavingEdit(true); setEditError("");
    try {
      await axios.put(`${API}/schedules/${editingSchedule.id}`, {
        frequency: editingSchedule.frequency,
        start_date: editingSchedule.start_date,
        meeting_type_id: editingSchedule.meeting_type_id,
      }, getAuthConfig());
      flash("Schedule updated");
      setEditingSchedule(null);
      fetchAll();
    } catch (err) { setEditError(err.response?.data?.detail || "Failed to save"); }
    setSavingEdit(false);
  };

  // ── Per-staff schedule ────────────────────────────────────────────────────
  const saveSchedule = async (staffUserId) => {
    if (!scheduleForm.meeting_type_id) return setScheduleError("Please select a meeting type");
    if (!scheduleForm.start_date) return setScheduleError("Please set a start date");
    setSavingSchedule(true);
    setScheduleError("");
    try {
      await axios.post(`${API}/schedules/`, { ...scheduleForm, staff_user_id: staffUserId }, getAuthConfig());
      flash("Schedule added");
      setShowAddSchedule(null);
      fetchAll();
    } catch (err) { setScheduleError(err.response?.data?.detail || "Failed to save"); }
    setSavingSchedule(false);
  };

  const deleteSchedule = async (sid) => {
    try {
      await axios.delete(`${API}/schedules/${sid}`, getAuthConfig());
      flash("Schedule removed");
      fetchAll();
    } catch (err) { flash("Failed to remove", true); }
  };

  // ── Bulk add ──────────────────────────────────────────────────────────────
  const getBulkUserIds = () => {
    const staffRoles = ["attendee", "manager", "shared_reviewer"];
    let users = allUsers.filter(u => staffRoles.includes(u.role));
    if (bulkForm.scope === "team" && bulkForm.team_id) {
      const teams = orgStructure.settings.flatMap(s => s.teams || []);
      const team = teams.find(t => t.id === bulkForm.team_id);
      const memberIds = new Set((team?.members || []).map(m => m.id));
      users = users.filter(u => memberIds.has(u.id));
    }
    return users.map(u => u.id);
  };

  const computeBulkPreview = () => {
    const ids = getBulkUserIds();
    const existingForType = new Set(
      schedules.filter(s => s.meeting_type_id === bulkForm.meeting_type_id).map(s => s.staff_user_id)
    );
    const toCreate = ids.filter(id => !existingForType.has(id)).length;
    const toSkip = ids.length - toCreate;
    setBulkPreview({ total: ids.length, toCreate, toSkip });
  };

  useEffect(() => {
    if (showBulk && bulkForm.meeting_type_id) computeBulkPreview();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bulkForm.meeting_type_id, bulkForm.scope, bulkForm.team_id, showBulk]);

  const saveBulk = async () => {
    if (!bulkForm.meeting_type_id) return setBulkError("Please select a meeting type");
    if (!bulkForm.start_date) return setBulkError("Please set a start date");
    const ids = getBulkUserIds();
    if (!ids.length) return setBulkError("No staff members found for the selected scope");
    setBulkSaving(true);
    setBulkError("");
    try {
      const res = await axios.post(`${API}/schedules/bulk`, {
        meeting_type_id: bulkForm.meeting_type_id,
        frequency: bulkForm.frequency,
        start_date: bulkForm.start_date,
        staff_user_ids: ids,
      }, getAuthConfig());
      flash(`Created ${res.data.created} schedule${res.data.created !== 1 ? "s" : ""} · ${res.data.skipped} already existed`);
      setShowBulk(false);
      setBulkPreview(null);
      fetchAll();
    } catch (err) { setBulkError(err.response?.data?.detail || "Failed"); }
    setBulkSaving(false);
  };

  // ── Derived ───────────────────────────────────────────────────────────────
  const staffUsers = allUsers.filter(u => ["attendee", "manager", "shared_reviewer"].includes(u.role));
  const schedulesByStaff = {};
  for (const s of schedules) {
    if (!schedulesByStaff[s.staff_user_id]) schedulesByStaff[s.staff_user_id] = [];
    schedulesByStaff[s.staff_user_id].push(s);
  }

  const allTeams = orgStructure.settings.flatMap(s => (s.teams || []).map(t => ({ ...t, setting_name: s.name })));
  const overdueCount = schedules.filter(s => s.is_overdue).length;
  const dueThisMonthCount = schedules.filter(s => {
    if (s.is_overdue) return false;
    return s.days_until_due <= 31;
  }).length;

  if (loading) {
    return (
      <Layout>
        <div className="flex items-center justify-center py-24 text-gray-400">
          <Loader className="w-5 h-5 animate-spin mr-2" /><span className="text-sm">Loading…</span>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="p-6 md:p-8 fade-in">

        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900 font-display">Meeting Schedules</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              {schedules.length} schedule{schedules.length !== 1 ? "s" : ""} across {staffUsers.length} staff
              {overdueCount > 0 && <span className="ml-2 text-red-600 font-medium">· {overdueCount} overdue</span>}
              {dueThisMonthCount > 0 && <span className="ml-2 text-blue-600">· {dueThisMonthCount} due this month</span>}
            </p>
          </div>
          <button
            onClick={() => { setShowBulk(true); setBulkForm({ meeting_type_id: meetingTypes[0]?.id || "", frequency: "monthly", start_date: today(), scope: "all", team_id: "" }); setBulkPreview(null); setBulkError(""); }}
            className="flex items-center gap-1.5 bg-[#1E3A8A] text-white text-sm font-medium px-4 py-2 rounded-lg hover:bg-[#1E40AF] transition-colors"
            data-testid="bulk-add-btn"
          >
            <Zap className="w-4 h-4" /> Bulk Assign Schedule
          </button>
        </div>

        {/* Flash */}
        {message && <div className="flex items-center gap-2 bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-lg p-3 mb-4 text-sm"><CheckCircle className="w-4 h-4 flex-shrink-0" />{message}</div>}
        {error   && <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg p-3 mb-4 text-sm"><AlertCircle className="w-4 h-4 flex-shrink-0" />{error}<button onClick={() => setError("")} className="ml-auto"><X className="w-3.5 h-3.5" /></button></div>}

        <div className="flex flex-col lg:flex-row gap-6" style={{ alignItems: "flex-start" }}>

          {/* ── LEFT: Meeting Types ── */}
          <div className="w-full lg:w-64 flex-shrink-0">
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-100 bg-gray-50 flex items-center justify-between">
                <span className="text-sm font-semibold text-gray-700">Meeting Types</span>
                <button onClick={() => { setShowAddType(true); setTypeForm({ name: "", default_frequency: "monthly", color: "#3B82F6" }); setEditingType(null); }} className="p-1 rounded hover:bg-gray-200 text-gray-500" data-testid="add-type-btn"><Plus className="w-3.5 h-3.5" /></button>
              </div>

              <div className="p-3 space-y-1">
                {meetingTypes.map(t => (
                  <div key={t.id} className="group flex items-center gap-2 px-2 py-2 rounded-md hover:bg-gray-50" data-testid={`meeting-type-${t.id}`}>
                    <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: t.color }} />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-gray-900 truncate">{t.name}</p>
                      <p className="text-[10px] text-gray-400">{freqLabel(t.default_frequency)}</p>
                    </div>
                    <div className="flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button onClick={() => { setEditingType(t); setTypeForm({ name: t.name, default_frequency: t.default_frequency, color: t.color }); setShowAddType(false); }} className="p-1 text-gray-400 hover:text-[#1E3A8A]" data-testid={`edit-type-${t.id}`}><Edit2 className="w-3 h-3" /></button>
                      <button onClick={() => deleteType(t)} className="p-1 text-gray-400 hover:text-red-500" data-testid={`delete-type-${t.id}`}><Trash2 className="w-3 h-3" /></button>
                    </div>
                  </div>
                ))}

                {/* Inline add/edit form */}
                {(showAddType || editingType) && (
                  <div className="border border-blue-200 rounded-lg p-3 bg-blue-50 mt-2 space-y-2">
                    <p className="text-xs font-semibold text-[#1E3A8A]">{editingType ? "Edit Type" : "New Type"}</p>
                    <input value={typeForm.name} onChange={e => setTypeForm(f => ({ ...f, name: e.target.value }))} placeholder="Type name *" className={inputCls} autoFocus data-testid="type-name-input"
                      onKeyDown={e => { if (e.key === "Enter") saveType(); if (e.key === "Escape") { setShowAddType(false); setEditingType(null); } }} />
                    <FreqSelector value={typeForm.default_frequency} onChange={v => setTypeForm(f => ({ ...f, default_frequency: v }))} className={selectCls} testId="type-freq-select" />
                    <div>
                      <p className="text-[10px] text-gray-500 mb-1">Colour</p>
                      <div className="flex gap-1.5 flex-wrap">
                        {COLOR_OPTIONS.map(c => (
                          <button key={c} onClick={() => setTypeForm(f => ({ ...f, color: c }))} className={`w-5 h-5 rounded-full border-2 transition-transform hover:scale-110 ${typeForm.color === c ? "border-gray-700 scale-110" : "border-transparent"}`} style={{ backgroundColor: c }} />
                        ))}
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <button onClick={saveType} disabled={savingType || !typeForm.name.trim()} className="flex items-center gap-1 bg-[#1E3A8A] text-white text-xs px-3 py-1.5 rounded hover:bg-[#1E40AF] disabled:opacity-60" data-testid="save-type-btn"><Check className="w-3 h-3" />{savingType ? "Saving…" : "Save"}</button>
                      <button onClick={() => { setShowAddType(false); setEditingType(null); }} className="text-xs px-3 py-1.5 border border-gray-300 rounded hover:bg-white">Cancel</button>
                    </div>
                  </div>
                )}

                {meetingTypes.length === 0 && !showAddType && (
                  <p className="text-xs text-gray-400 text-center py-4">No types yet. Click + to add.</p>
                )}
              </div>
            </div>
          </div>

          {/* ── RIGHT: Staff Schedules ── */}
          <div className="flex-1 min-w-0 bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
            <div className="px-5 py-3.5 border-b border-gray-100 bg-gray-50 flex items-center gap-2">
              <Users className="w-4 h-4 text-gray-400" />
              <span className="text-sm font-semibold text-gray-700">Staff Schedules</span>
              <span className="text-xs text-gray-400">({staffUsers.length} staff members)</span>
            </div>

            {staffUsers.length === 0 && (
              <div className="text-center py-16 text-gray-400">
                <Users className="w-10 h-10 mx-auto mb-3 opacity-20" />
                <p className="text-sm">No staff members found</p>
                <p className="text-xs mt-1">Add users in Organisation → Org Structure first</p>
              </div>
            )}

            <div className="divide-y divide-gray-100">
              {staffUsers.map(u => {
                const userSchedules = schedulesByStaff[u.id] || [];
                const hasOverdue = userSchedules.some(s => s.is_overdue);
                const isExpanded = expandedStaff.has(u.id);
                const initials = u.name.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();

                return (
                  <div key={u.id} data-testid={`staff-row-${u.id}`}>
                    {/* Staff header row */}
                    <div
                      className="flex items-center gap-3 px-5 py-3 cursor-pointer hover:bg-gray-50 transition-colors group"
                      onClick={() => setExpandedStaff(prev => {
                        const next = new Set(prev);
                        if (next.has(u.id)) next.delete(u.id); else next.add(u.id);
                        return next;
                      })}
                    >
                      {isExpanded
                        ? <ChevronDown className="w-4 h-4 text-gray-400 flex-shrink-0" />
                        : <ChevronRight className="w-4 h-4 text-gray-400 flex-shrink-0" />}
                      <div className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold text-white flex-shrink-0" style={{ background: avatarColor(u.name) }}>{initials}</div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-medium text-gray-900 truncate">{u.name}</p>
                          {hasOverdue && <span className="text-xs text-red-600 font-medium bg-red-50 px-1.5 py-0.5 rounded-full flex-shrink-0">Overdue</span>}
                        </div>
                        <p className="text-xs text-gray-400 capitalize">{u.role}</p>
                      </div>
                      {/* Schedule pills — right-aligned, fill leftwards */}
                      {!isExpanded && (
                        <div className="flex items-center gap-1.5 flex-wrap justify-end flex-shrink-0 max-w-[55%]">
                          {userSchedules.length === 0
                            ? <span className="text-xs text-gray-300 italic">No schedules</span>
                            : userSchedules.slice(0, 4).map(s => (
                              <span key={s.id} className="text-xs px-2.5 py-0.5 rounded-full text-white font-medium whitespace-nowrap" style={{ backgroundColor: s.meeting_type_color }}>
                                {s.meeting_type_name}
                              </span>
                            ))
                          }
                          {userSchedules.length > 4 && <span className="text-xs text-gray-400 flex-shrink-0">+{userSchedules.length - 4}</span>}
                        </div>
                      )}
                    </div>

                    {/* Expanded schedules */}
                    {isExpanded && (
                      <div className="bg-gray-50 px-5 pb-4 pt-2 space-y-2">
                        {userSchedules.map(s => (
                          <div key={s.id} className="bg-white rounded-lg border border-gray-100 overflow-hidden" data-testid={`schedule-${s.id}`}>
                            {/* ── Normal view row ── */}
                            {editingSchedule?.id !== s.id && (
                              <div className="flex items-center gap-3 px-3 py-2.5">
                                <div className="w-2 h-8 rounded-full flex-shrink-0" style={{ backgroundColor: s.meeting_type_color }} />
                                <div className="flex-1 min-w-0">
                                  <p className="text-sm font-medium text-gray-900">{s.meeting_type_name}</p>
                                  <p className="text-xs text-gray-400">{freqLabel(s.frequency)} · Started {fmt(s.start_date)} · {s.completed_count} completed</p>
                                </div>
                                <DueBadge nextDue={s.next_due} isOverdue={s.is_overdue} daysUntil={s.days_until_due} />
                                {s.is_overdue || s.days_until_due <= 31 ? (
                                  <button
                                    onClick={() => navigate(`/meetings/new?schedule_id=${s.id}&title=${encodeURIComponent(s.meeting_type_name + " — " + s.staff_name)}&attendee_id=${s.staff_user_id}`)}
                                    className="text-xs font-medium text-white bg-[#1E3A8A] px-2.5 py-1 rounded hover:bg-[#1E40AF] transition-colors flex-shrink-0"
                                    data-testid={`start-meeting-${s.id}`}
                                  >Start</button>
                                ) : null}
                                <button
                                  onClick={() => { setEditingSchedule({ id: s.id, frequency: s.frequency, start_date: s.start_date, meeting_type_id: s.meeting_type_id }); setEditError(""); }}
                                  className="p-1 text-gray-300 hover:text-[#1E3A8A] flex-shrink-0 transition-colors"
                                  title="Edit schedule"
                                  data-testid={`edit-schedule-${s.id}`}
                                ><Edit2 className="w-3.5 h-3.5" /></button>
                                <button onClick={() => deleteSchedule(s.id)} className="p-1 text-gray-300 hover:text-red-500 flex-shrink-0" data-testid={`delete-schedule-${s.id}`}><Trash2 className="w-3.5 h-3.5" /></button>
                              </div>
                            )}

                            {/* ── Inline edit form ── */}
                            {editingSchedule?.id === s.id && (
                              <div className="px-3 py-3 bg-blue-50 border-t border-blue-100 space-y-2" data-testid={`edit-schedule-form-${s.id}`}>
                                <div className="flex items-center gap-2 mb-1">
                                  <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: s.meeting_type_color }} />
                                  <p className="text-xs font-semibold text-[#1E3A8A]">Edit — {s.meeting_type_name}</p>
                                </div>
                                <div className="grid grid-cols-2 gap-2">
                                  <div>
                                    <label className="text-[10px] text-gray-500 block mb-1">Frequency</label>
                                    <FreqSelector
                                      value={editingSchedule.frequency}
                                      onChange={v => setEditingSchedule(e => ({ ...e, frequency: v }))}
                                      className={selectCls}
                                      testId={`edit-freq-${s.id}`}
                                    />
                                  </div>
                                  <div>
                                    <label className="text-[10px] text-gray-500 block mb-1">Start date</label>
                                    <input
                                      type="date"
                                      value={editingSchedule.start_date}
                                      onChange={e => setEditingSchedule(es => ({ ...es, start_date: e.target.value }))}
                                      className={inputCls}
                                      data-testid={`edit-start-date-${s.id}`}
                                    />
                                  </div>
                                </div>
                                {editError && <p className="text-xs text-red-600">{editError}</p>}
                                <div className="flex gap-2 pt-1">
                                  <button onClick={saveEdit} disabled={savingEdit} className="flex items-center gap-1 bg-[#1E3A8A] text-white text-xs px-3 py-1.5 rounded hover:bg-[#1E40AF] disabled:opacity-60" data-testid={`save-edit-schedule-${s.id}`}>
                                    <Check className="w-3 h-3" />{savingEdit ? "Saving…" : "Save"}
                                  </button>
                                  <button onClick={() => setEditingSchedule(null)} className="text-xs px-3 py-1.5 border border-gray-300 rounded hover:bg-white">Cancel</button>
                                </div>
                              </div>
                            )}
                          </div>
                        ))}

                        {/* Add schedule for this person */}
                        {showAddSchedule === u.id ? (
                          <div className="border border-blue-200 rounded-lg p-3 bg-blue-50 space-y-2" data-testid="add-schedule-form">
                            <p className="text-xs font-semibold text-[#1E3A8A]">Add schedule for {u.name}</p>
                            <select value={scheduleForm.meeting_type_id} onChange={e => setScheduleForm(f => ({ ...f, meeting_type_id: e.target.value }))} className={selectCls} data-testid="schedule-type-select">
                              <option value="">Select meeting type *</option>
                              {meetingTypes.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                            </select>
                            <FreqSelector value={scheduleForm.frequency} onChange={v => setScheduleForm(f => ({ ...f, frequency: v }))} className={selectCls} testId="schedule-freq-select" />
                            <div>
                              <label className="text-[10px] text-gray-500 block mb-1">Start date</label>
                              <input type="date" value={scheduleForm.start_date} onChange={e => setScheduleForm(f => ({ ...f, start_date: e.target.value }))} className={inputCls} data-testid="schedule-start-date" />
                            </div>
                            {scheduleError && <p className="text-xs text-red-600">{scheduleError}</p>}
                            <div className="flex gap-2">
                              <button onClick={() => saveSchedule(u.id)} disabled={savingSchedule} className="flex items-center gap-1 bg-[#1E3A8A] text-white text-xs px-3 py-1.5 rounded hover:bg-[#1E40AF] disabled:opacity-60" data-testid="save-schedule-btn"><Check className="w-3 h-3" />{savingSchedule ? "Saving…" : "Save"}</button>
                              <button onClick={() => setShowAddSchedule(null)} className="text-xs px-3 py-1.5 border border-gray-300 rounded hover:bg-white">Cancel</button>
                            </div>
                          </div>
                        ) : (
                          <button
                            onClick={() => { setShowAddSchedule(u.id); setScheduleForm({ meeting_type_id: meetingTypes[0]?.id || "", frequency: "monthly", start_date: today() }); setScheduleError(""); }}
                            className="flex items-center gap-1.5 text-xs text-[#1E3A8A] font-medium border border-dashed border-blue-200 rounded-lg px-3 py-2 hover:bg-blue-50 transition-colors w-full justify-center"
                            data-testid={`add-schedule-${u.id}`}
                          ><Plus className="w-3.5 h-3.5" /> Add Schedule</button>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* ── Bulk Add Modal ── */}
        {showBulk && (
          <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-gray-900 flex items-center gap-2"><Zap className="w-4 h-4 text-[#1E3A8A]" /> Bulk Assign Schedule</h3>
                <button onClick={() => setShowBulk(false)}><X className="w-4 h-4 text-gray-400" /></button>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Meeting Type *</label>
                  <select value={bulkForm.meeting_type_id} onChange={e => setBulkForm(f => ({ ...f, meeting_type_id: e.target.value }))} className={selectCls} data-testid="bulk-type-select">
                    <option value="">Select type…</option>
                    {meetingTypes.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Frequency</label>
                  <FreqSelector value={bulkForm.frequency} onChange={v => setBulkForm(f => ({ ...f, frequency: v }))} className={selectCls} testId="bulk-freq-select" />
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Start Date *</label>
                  <input type="date" value={bulkForm.start_date} onChange={e => setBulkForm(f => ({ ...f, start_date: e.target.value }))} className={inputCls} data-testid="bulk-start-date" />
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Apply to</label>
                  <select value={bulkForm.scope} onChange={e => setBulkForm(f => ({ ...f, scope: e.target.value, team_id: "" }))} className={selectCls} data-testid="bulk-scope-select">
                    <option value="all">All staff in organisation</option>
                    <option value="team">Specific team</option>
                  </select>
                  {bulkForm.scope === "team" && (
                    <select value={bulkForm.team_id} onChange={e => setBulkForm(f => ({ ...f, team_id: e.target.value }))} className={`${selectCls} mt-2`} data-testid="bulk-team-select">
                      <option value="">Select team…</option>
                      {allTeams.map(t => <option key={t.id} value={t.id}>{t.name} ({t.setting_name})</option>)}
                    </select>
                  )}
                </div>

                {/* Preview */}
                {bulkPreview && (
                  <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 text-sm">
                    <p className="font-medium text-blue-800">Preview</p>
                    <p className="text-blue-700 text-xs mt-1">
                      <span className="font-semibold">{bulkPreview.toCreate}</span> schedules will be created
                      {bulkPreview.toSkip > 0 && <span className="text-gray-500"> · {bulkPreview.toSkip} already exist (skipped)</span>}
                    </p>
                  </div>
                )}

                {bulkError && <p className="text-xs text-red-600">{bulkError}</p>}

                <div className="flex gap-2 pt-1">
                  <button
                    onClick={saveBulk}
                    disabled={bulkSaving || !bulkForm.meeting_type_id}
                    className="flex items-center gap-1.5 bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF] disabled:opacity-60"
                    data-testid="bulk-confirm-btn"
                  >
                    <Zap className="w-3.5 h-3.5" />{bulkSaving ? "Creating…" : "Confirm & Create"}
                  </button>
                  <button onClick={() => setShowBulk(false)} className="px-4 py-2 border border-gray-300 text-gray-600 rounded-md text-sm hover:bg-gray-50">Cancel</button>
                </div>
              </div>
            </div>
          </div>
        )}

      </div>
    </Layout>
  );
}

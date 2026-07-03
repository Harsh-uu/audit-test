import React, { useState, useEffect, useCallback, useRef } from "react";
import { DragDropContext, Droppable, Draggable } from "@hello-pangea/dnd";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import {
  Building2, Users, ChevronRight, ChevronDown, Plus, Edit2, Trash2, X, Check,
  MapPin, UserCog, Loader, AlertCircle, CheckCircle, Pencil, KeyRound,
  GripVertical, UserPlus, Search, UserCheck, Layers,
} from "lucide-react";
// ── Constants ────────────────────────────────────────────────────────────────

const ROLES = [
  { value: "attendee", label: "Care Worker / Attendee" },
  { value: "manager", label: "Manager" },
  { value: "shared_reviewer", label: "Shared Reviewer" },
  { value: "admin", label: "Admin" },
];

const ROLE_COLORS = {
  admin: "bg-purple-100 text-purple-700",
  manager: "bg-blue-100 text-blue-700",
  shared_reviewer: "bg-indigo-100 text-indigo-700",
  attendee: "bg-gray-100 text-gray-600",
};

const ROLE_LABELS = {
  admin: "Admin",
  manager: "Manager",
  shared_reviewer: "Reviewer",
  attendee: "Care Worker",
};

// ── Pure helpers ─────────────────────────────────────────────────────────────

function findUser(userId, structure) {
  const u = structure.unassigned_users.find(u => u.id === userId);
  if (u) return u;
  for (const s of structure.settings) {
    for (const t of (s.teams || [])) {
      const m = (t.members || []).find(m => m.id === userId);
      if (m) return m;
    }
  }
  return null;
}

function moveUserInStructure(prev, movedUser, fromTeamId, toTeamId) {
  const newSettings = prev.settings.map(s => ({
    ...s,
    teams: (s.teams || []).map(t => {
      if (fromTeamId && t.id === fromTeamId) {
        return { ...t, members: (t.members || []).filter(m => m.id !== movedUser.id) };
      }
      if (toTeamId && t.id === toTeamId) {
        return { ...t, members: [...(t.members || []), movedUser] };
      }
      return t;
    }),
  }));
  let newUnassigned = prev.unassigned_users;
  if (!fromTeamId) newUnassigned = newUnassigned.filter(u => u.id !== movedUser.id);
  if (!toTeamId) newUnassigned = [...newUnassigned, movedUser];
  return { ...prev, settings: newSettings, unassigned_users: newUnassigned };
}

// ── Small UI atoms ─────────────────────────────────────────────────────────

function Avatar({ name, color = "bg-gray-100 text-gray-600" }) {
  const initials = (name || "?").split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
  return (
    <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold flex-shrink-0 ${color}`}>
      {initials}
    </div>
  );
}

function RoleBadge({ role }) {
  return (
    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${ROLE_COLORS[role] || ROLE_COLORS.attendee}`}>
      {ROLE_LABELS[role] || role}
    </span>
  );
}

function Modal({ title, onClose, children }) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-900">{title}</h3>
          <button onClick={onClose}><X className="w-4 h-4 text-gray-400" /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

function FormField({ label, children }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      {children}
    </div>
  );
}

const inputCls = "w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]";
const selectCls = `${inputCls} bg-white`;

// ── Main component ────────────────────────────────────────────────────────────

export default function OrgStructure() {
  const { getAuthConfig, API, user: currentUser, updateOrgName } = useAuth();
  const isAdmin = currentUser?.role === "admin";
  const canManage = ["admin", "manager"].includes(currentUser?.role);

  const [structure, setStructure] = useState({ settings: [], unassigned_users: [] });
  const [allUsers, setAllUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expandedSettings, setExpandedSettings] = useState(new Set());
  const isFirstLoad = useRef(true);

  // Org name inline edit
  // org name editing is now handled in Layout.js

  // Flash
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  // Saving states
  const [saving, setSaving] = useState(false);
  const [savingUser, setSavingUser] = useState(false);
  const [savingInvite, setSavingInvite] = useState(false);

  // People pool search
  const [searchQuery, setSearchQuery] = useState("");

  // Modals
  const [showAddSetting, setShowAddSetting] = useState(false);
  const [editingSetting, setEditingSetting] = useState(null);
  const [showAddTeamFor, setShowAddTeamFor] = useState(null); // settingId
  const [editingTeam, setEditingTeam] = useState(null);
  const [editingUser, setEditingUser] = useState(null);
  const [showInviteUser, setShowInviteUser] = useState(false);
  const [showPwdReset, setShowPwdReset] = useState(false);
  const [newPassword, setNewPassword] = useState("");

  // Forms
  const [settingForm, setSettingForm] = useState({ name: "", description: "", manager_user_id: "" });
  const [teamForm, setTeamForm] = useState({ name: "", description: "", supervisor_user_id: "" });
  const [editUserForm, setEditUserForm] = useState({});
  const [editUserError, setEditUserError] = useState("");
  const [inviteForm, setInviteForm] = useState({ name: "", email: "", password: "", role: "attendee" });
  const [inviteError, setInviteError] = useState("");

  // ── Org name edit ─────────────────────────────────────────────────────────
  // (Handled globally in Layout.js)

  // ── Data fetching ────────────────────────────────────────────────────────
  const fetchData = useCallback(async () => {
    try {
      const [structRes, usersRes] = await Promise.all([
        axios.get(`${API}/org/structure`, getAuthConfig()),
        axios.get(`${API}/admin/users`, getAuthConfig()),
      ]);
      setStructure(structRes.data);
      setAllUsers(usersRes.data);
      if (isFirstLoad.current) {
        setExpandedSettings(new Set(structRes.data.settings.map(s => s.id)));
        isFirstLoad.current = false;
      }
    } catch (err) {
      console.error("Org structure load failed", err);
      flash("Failed to load organisation structure", true);
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const flash = (msg, isError = false) => {
    if (isError) setError(msg); else setMessage(msg);
    setTimeout(() => { setError(""); setMessage(""); }, 3500);
  };

  const managerUsers = allUsers.filter(u => ["admin", "manager"].includes(u.role));

  // ── Drag and drop ─────────────────────────────────────────────────────────
  const onDragEnd = async (result) => {
    const { draggableId: userId, source, destination } = result;
    if (!destination) return;
    if (source.droppableId === destination.droppableId) return;

    const fromTeamId = source.droppableId === "unassigned" ? null : source.droppableId.replace("team-", "");
    const toTeamId = destination.droppableId === "unassigned" ? null : destination.droppableId.replace("team-", "");
    if (fromTeamId === toTeamId) return;

    const movedUser = findUser(userId, structure);
    if (!movedUser) return;

    // Optimistic update — immediate visual response
    setStructure(prev => moveUserInStructure(prev, movedUser, fromTeamId, toTeamId));

    try {
      await axios.patch(`${API}/org/users/${userId}/assign-team`, { team_id: toTeamId }, getAuthConfig());
    } catch (err) {
      // Revert on failure
      setStructure(prev => moveUserInStructure(prev, movedUser, toTeamId, fromTeamId));
      flash(err.response?.data?.detail || "Failed to move user", true);
    }
  };

  // ── Settings CRUD ─────────────────────────────────────────────────────────
  const saveSetting = async () => {
    if (!settingForm.name.trim()) return;
    setSaving(true);
    try {
      if (editingSetting) {
        await axios.put(`${API}/org/settings/${editingSetting.id}`, settingForm, getAuthConfig());
        flash("Setting updated");
        setEditingSetting(null);
      } else {
        const res = await axios.post(`${API}/org/settings`, settingForm, getAuthConfig());
        flash("Setting created");
        setShowAddSetting(false);
        // Auto-expand new setting
        setExpandedSettings(prev => new Set([...prev, res.data?.id].filter(Boolean)));
      }
      setSettingForm({ name: "", description: "", manager_user_id: "" });
      fetchData();
    } catch (err) { flash(err.response?.data?.detail || "Failed to save", true); }
    setSaving(false);
  };

  const deleteSetting = async (s) => {
    if (!window.confirm(`Delete "${s.name}"? All teams will also be removed.`)) return;
    try {
      await axios.delete(`${API}/org/settings/${s.id}`, getAuthConfig());
      flash("Setting deleted");
      fetchData();
    } catch (err) { flash(err.response?.data?.detail || "Delete failed", true); }
  };

  // ── Teams CRUD ─────────────────────────────────────────────────────────────
  const saveTeam = async (settingId) => {
    if (!teamForm.name.trim()) return;
    setSaving(true);
    try {
      if (editingTeam) {
        await axios.put(`${API}/org/teams/${editingTeam.id}`, teamForm, getAuthConfig());
        flash("Team updated");
        setEditingTeam(null);
      } else {
        await axios.post(`${API}/org/settings/${settingId}/teams`, teamForm, getAuthConfig());
        flash("Team created");
        setShowAddTeamFor(null);
      }
      setTeamForm({ name: "", description: "", supervisor_user_id: "" });
      fetchData();
    } catch (err) { flash(err.response?.data?.detail || "Failed to save", true); }
    setSaving(false);
  };

  const deleteTeam = async (t) => {
    if (!window.confirm(`Delete team "${t.name}"? Members will be unassigned.`)) return;
    try {
      await axios.delete(`${API}/org/teams/${t.id}`, getAuthConfig());
      flash("Team deleted");
      fetchData();
    } catch (err) { flash(err.response?.data?.detail || "Delete failed", true); }
  };

  // ── User management ────────────────────────────────────────────────────────
  const openEditUser = (u) => {
    setEditingUser(u);
    setEditUserForm({ name: u.name, email: u.email, role: u.role, is_active: u.is_active !== false });
    setEditUserError("");
    setShowPwdReset(false);
    setNewPassword("");
  };

  const saveEditUser = async () => {
    if (!editUserForm.name?.trim()) return setEditUserError("Name is required");
    if (!editUserForm.email?.trim()) return setEditUserError("Email is required");
    if (showPwdReset && newPassword && newPassword.length < 8) return setEditUserError("Password must be at least 8 characters");
    setSavingUser(true);
    setEditUserError("");
    try {
      await axios.put(`${API}/admin/users/${editingUser.id}`, editUserForm, getAuthConfig());
      if (showPwdReset && newPassword.trim()) {
        await axios.post(`${API}/admin/users/${editingUser.id}/reset-password`, { new_password: newPassword }, getAuthConfig());
      }
      flash("User updated");
      setEditingUser(null);
      fetchData();
    } catch (err) { setEditUserError(err.response?.data?.detail || "Failed to save"); }
    setSavingUser(false);
  };

  const inviteUser = async () => {
    if (!inviteForm.name.trim()) return setInviteError("Name is required");
    if (!inviteForm.email.trim()) return setInviteError("Email is required");
    if (inviteForm.password.length < 8) return setInviteError("Password must be at least 8 characters");
    setSavingInvite(true);
    setInviteError("");
    try {
      await axios.post(`${API}/org/invite-user`, inviteForm, getAuthConfig());
      flash("User added successfully");
      setShowInviteUser(false);
      setInviteForm({ name: "", email: "", password: "", role: "attendee" });
      fetchData();
    } catch (err) { setInviteError(err.response?.data?.detail || "Failed to add user"); }
    setSavingInvite(false);
  };

  // ── Derived values ─────────────────────────────────────────────────────────
  const filteredUnassigned = structure.unassigned_users.filter(u =>
    !searchQuery ||
    u.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    u.email.toLowerCase().includes(searchQuery.toLowerCase())
  );
  const totalUsers = allUsers.length;
  const assignedCount = totalUsers - structure.unassigned_users.length;

  // ── Loading state ──────────────────────────────────────────────────────────
  if (loading) {
    return (
      <Layout>
        <div className="flex items-center justify-center py-24 text-gray-400">
          <Loader className="w-5 h-5 animate-spin mr-2" /><span className="text-sm">Loading…</span>
        </div>
      </Layout>
    );
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <Layout>
      <div>

        {/* ── Main content ── */}
        <div className="p-6 md:p-8 fade-in">

        {/* Page header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900 font-display">Organisation Structure</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              Drag staff between teams to reassign · {assignedCount}/{totalUsers} staff assigned
            </p>
          </div>
          {canManage && (
            <button
              onClick={() => { setShowAddSetting(true); setSettingForm({ name: "", description: "", manager_user_id: "" }); }}
              className="flex items-center gap-1.5 bg-[#1E3A8A] text-white text-sm font-medium px-4 py-2 rounded-lg hover:bg-[#1E40AF] transition-colors"
              data-testid="add-setting-btn"
            >
              <Plus className="w-4 h-4" /> Add Setting
            </button>
          )}
        </div>

        {/* Flash messages */}
        {message && (
          <div className="flex items-center gap-2 bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-lg p-3 mb-4 text-sm" data-testid="org-success">
            <CheckCircle className="w-4 h-4 flex-shrink-0" />{message}
          </div>
        )}
        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg p-3 mb-4 text-sm" data-testid="org-error">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />{error}
            <button onClick={() => setError("")} className="ml-auto"><X className="w-3.5 h-3.5" /></button>
          </div>
        )}

        {/* ── Two-panel DnD layout ── */}
        <DragDropContext onDragEnd={onDragEnd}>
          <div className="flex flex-col lg:flex-row gap-5" style={{ alignItems: "flex-start" }}>

            {/* ══ LEFT: Org Tree ══════════════════════════════════════════ */}
            <div className="flex-1 min-w-0 bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden" data-testid="org-tree">
              <div className="px-5 py-3.5 border-b border-gray-100 bg-gray-50 flex items-center gap-2">
                <Layers className="w-4 h-4 text-gray-400" />
                <span className="text-sm font-semibold text-gray-700">Settings &amp; Teams</span>
                <span className="text-xs text-gray-400">({structure.settings.length})</span>
              </div>

              <div className="p-4 space-y-3">
                {structure.settings.length === 0 && (
                  <div className="text-center py-16 text-gray-400">
                    <Building2 className="w-10 h-10 mx-auto mb-3 opacity-20" />
                    <p className="text-sm font-medium">No settings yet</p>
                    {canManage && <p className="text-xs mt-1">Use "Add Setting" to get started</p>}
                  </div>
                )}

                {structure.settings.map(s => {
                  const isExpanded = expandedSettings.has(s.id);
                  const teams = s.teams || [];
                  const staffCount = teams.reduce((n, t) => n + (t.members?.length || 0), 0);

                  return (
                    <div key={s.id} className="border border-gray-200 rounded-xl overflow-hidden" data-testid={`setting-${s.id}`}>

                      {/* Setting header */}
                      <div
                        className={`flex items-center gap-3 px-4 py-3 cursor-pointer group transition-colors ${isExpanded ? "bg-[#EFF6FF]" : "bg-gray-50 hover:bg-gray-100"}`}
                        onClick={() => setExpandedSettings(prev => {
                          const next = new Set(prev);
                          if (next.has(s.id)) next.delete(s.id); else next.add(s.id);
                          return next;
                        })}
                      >
                        {isExpanded
                          ? <ChevronDown className="w-4 h-4 text-[#1E3A8A] flex-shrink-0" />
                          : <ChevronRight className="w-4 h-4 text-gray-400 flex-shrink-0" />}
                        <MapPin className="w-4 h-4 text-[#1E3A8A] flex-shrink-0" />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-semibold text-gray-900 truncate">{s.name}</p>
                          {s.manager_name && <p className="text-xs text-gray-400">Manager: {s.manager_name}</p>}
                          <p className="text-xs text-gray-400">{teams.length} team{teams.length !== 1 ? "s" : ""} · {staffCount} staff</p>
                        </div>
                        {canManage && (
                          <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity" onClick={e => e.stopPropagation()}>
                            <button
                              onClick={() => { setEditingSetting(s); setSettingForm({ name: s.name, description: s.description || "", manager_user_id: s.manager_user_id || "" }); }}
                              className="p-1.5 text-gray-400 hover:text-[#1E3A8A] hover:bg-white rounded"
                              title="Edit setting"
                              data-testid={`edit-setting-${s.id}`}
                            ><Edit2 className="w-3.5 h-3.5" /></button>
                            {isAdmin && (
                              <button
                                onClick={() => deleteSetting(s)}
                                className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-white rounded"
                                data-testid={`delete-setting-${s.id}`}
                              ><Trash2 className="w-3.5 h-3.5" /></button>
                            )}
                          </div>
                        )}
                      </div>

                      {/* Teams list */}
                      {isExpanded && (
                        <div className="p-3 space-y-2 bg-white">
                          {teams.map(t => (
                            <div key={t.id} className="border border-gray-100 rounded-lg overflow-hidden" data-testid={`team-${t.id}`}>

                              {/* Team header */}
                              <div className="flex items-center gap-2 px-3 py-2.5 bg-gray-50 group border-b border-gray-100">
                                <Users className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                                <div className="flex-1 min-w-0">
                                  <p className="text-xs font-semibold text-gray-800">{t.name}</p>
                                  {t.supervisor_name && <p className="text-[11px] text-gray-400">Supervisor: {t.supervisor_name}</p>}
                                </div>
                                {canManage && (
                                  <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                                    <button
                                      onClick={() => { setEditingTeam(t); setTeamForm({ name: t.name, description: t.description || "", supervisor_user_id: t.supervisor_user_id || "" }); }}
                                      className="p-1 text-gray-400 hover:text-[#1E3A8A]"
                                      data-testid={`edit-team-${t.id}`}
                                    ><Edit2 className="w-3 h-3" /></button>
                                    <button
                                      onClick={() => deleteTeam(t)}
                                      className="p-1 text-gray-400 hover:text-red-500"
                                      data-testid={`delete-team-${t.id}`}
                                    ><Trash2 className="w-3 h-3" /></button>
                                  </div>
                                )}
                              </div>

                              {/* Droppable member list */}
                              <Droppable droppableId={`team-${t.id}`}>
                                {(provided, snapshot) => (
                                  <div
                                    ref={provided.innerRef}
                                    {...provided.droppableProps}
                                    className={`min-h-[56px] px-2 py-1.5 transition-colors ${snapshot.isDraggingOver ? "bg-blue-50" : "bg-white"}`}
                                  >
                                    {(t.members || []).map((m, idx) => (
                                      <Draggable key={m.id} draggableId={m.id} index={idx} isDragDisabled={!canManage}>
                                        {(provided, snapshot) => (
                                          <div
                                            ref={provided.innerRef}
                                            {...provided.draggableProps}
                                            className={`flex items-center gap-2 px-2 py-1.5 rounded-md mb-1 group/member transition-all ${snapshot.isDragging ? "bg-white shadow-lg ring-1 ring-blue-200" : "hover:bg-gray-50"}`}
                                            data-testid={`member-${m.id}`}
                                          >
                                            {canManage && (
                                              <div {...provided.dragHandleProps} className="cursor-grab text-gray-300 hover:text-gray-500 flex-shrink-0 touch-none">
                                                <GripVertical className="w-3.5 h-3.5" />
                                              </div>
                                            )}
                                            <Avatar
                                              name={m.name}
                                              color={m.id === t.supervisor_user_id ? "bg-[#1E3A8A] text-white" : "bg-gray-100 text-gray-600"}
                                            />
                                            <div className="flex-1 min-w-0">
                                              <p className="text-xs font-medium text-gray-900 truncate">{m.name}</p>
                                              <RoleBadge role={m.role} />
                                            </div>
                                            {canManage && (
                                              <button
                                                onClick={() => openEditUser(m)}
                                                className="opacity-0 group-hover/member:opacity-100 p-1 text-gray-300 hover:text-[#1E3A8A] transition-opacity"
                                                data-testid={`edit-member-${m.id}`}
                                              ><Pencil className="w-3 h-3" /></button>
                                            )}
                                          </div>
                                        )}
                                      </Draggable>
                                    ))}
                                    {provided.placeholder}
                                    {(t.members || []).length === 0 && !snapshot.isDraggingOver && (
                                      <div className="flex items-center justify-center h-[40px] text-[11px] text-gray-300 border border-dashed border-gray-200 rounded-md">
                                        Drop staff here to assign
                                      </div>
                                    )}
                                  </div>
                                )}
                              </Droppable>
                            </div>
                          ))}

                          {/* Inline Add Team */}
                          {canManage && (
                            showAddTeamFor === s.id ? (
                              <div className="border border-blue-200 rounded-lg p-3 bg-blue-50" data-testid="add-team-form">
                                <p className="text-xs font-semibold text-[#1E3A8A] mb-2">New team in {s.name}</p>
                                <div className="space-y-2">
                                  <input
                                    value={teamForm.name}
                                    onChange={e => setTeamForm(f => ({ ...f, name: e.target.value }))}
                                    placeholder="Team name *"
                                    className={inputCls}
                                    onKeyDown={e => { if (e.key === "Enter") saveTeam(s.id); if (e.key === "Escape") setShowAddTeamFor(null); }}
                                    autoFocus
                                    data-testid="new-team-name-input"
                                  />
                                  <select
                                    value={teamForm.supervisor_user_id}
                                    onChange={e => setTeamForm(f => ({ ...f, supervisor_user_id: e.target.value }))}
                                    className={selectCls}
                                  >
                                    <option value="">Supervisor — optional</option>
                                    {managerUsers.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}
                                  </select>
                                  <div className="flex gap-2">
                                    <button
                                      onClick={() => saveTeam(s.id)}
                                      disabled={saving || !teamForm.name.trim()}
                                      className="flex items-center gap-1 bg-[#1E3A8A] text-white text-xs px-3 py-1.5 rounded hover:bg-[#1E40AF] disabled:opacity-60"
                                      data-testid="save-new-team-btn"
                                    ><Check className="w-3 h-3" />{saving ? "Saving…" : "Save"}</button>
                                    <button onClick={() => setShowAddTeamFor(null)} className="text-xs px-3 py-1.5 border border-gray-300 rounded hover:bg-white">Cancel</button>
                                  </div>
                                </div>
                              </div>
                            ) : (
                              <button
                                onClick={() => { setShowAddTeamFor(s.id); setTeamForm({ name: "", description: "", supervisor_user_id: "" }); }}
                                className="w-full flex items-center justify-center gap-1.5 text-xs text-[#1E3A8A] font-medium py-2 border border-dashed border-blue-200 rounded-lg hover:bg-blue-50 transition-colors"
                                data-testid={`add-team-btn-${s.id}`}
                              ><Plus className="w-3.5 h-3.5" /> Add Team</button>
                            )
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            {/* ══ RIGHT: Unassigned People Pool ═══════════════════════════ */}
            <div className="w-full lg:w-72 flex-shrink-0 lg:sticky lg:top-4">
              <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden" data-testid="people-pool">

                {/* Panel header */}
                <div className="px-4 py-3 border-b border-gray-100 bg-amber-50">
                  <div className="flex items-center justify-between mb-2.5">
                    <div className="flex items-center gap-2">
                      <UserCog className="w-4 h-4 text-amber-600" />
                      <span className="text-sm font-semibold text-gray-800">Unassigned Staff</span>
                      {structure.unassigned_users.length > 0 && (
                        <span className="bg-amber-200 text-amber-800 text-xs font-bold px-1.5 py-0.5 rounded-full" data-testid="unassigned-count">
                          {structure.unassigned_users.length}
                        </span>
                      )}
                    </div>
                    {canManage && (
                      <button
                        onClick={() => { setShowInviteUser(true); setInviteForm({ name: "", email: "", password: "", role: "attendee" }); setInviteError(""); }}
                        className="flex items-center gap-1 text-xs text-[#1E3A8A] font-medium hover:underline"
                        data-testid="add-user-btn"
                      ><UserPlus className="w-3.5 h-3.5" /> Add User</button>
                    )}
                  </div>
                  {/* Search */}
                  <div className="relative">
                    <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
                    <input
                      value={searchQuery}
                      onChange={e => setSearchQuery(e.target.value)}
                      placeholder="Search staff…"
                      className="w-full pl-7 pr-3 py-1.5 border border-amber-200 rounded-md text-xs bg-white focus:outline-none focus:ring-1 focus:ring-amber-300"
                      data-testid="search-staff-input"
                    />
                  </div>
                </div>

                {/* Droppable unassigned zone */}
                <Droppable droppableId="unassigned">
                  {(provided, snapshot) => (
                    <div
                      ref={provided.innerRef}
                      {...provided.droppableProps}
                      className={`p-3 min-h-[120px] transition-colors ${snapshot.isDraggingOver ? "bg-amber-50" : "bg-white"}`}
                      data-testid="unassigned-drop-zone"
                    >
                      {filteredUnassigned.map((u, i) => (
                        <Draggable key={u.id} draggableId={u.id} index={i} isDragDisabled={!canManage}>
                          {(provided, snapshot) => (
                            <div
                              ref={provided.innerRef}
                              {...provided.draggableProps}
                              className={`flex items-center gap-2 p-2 rounded-lg mb-1.5 border transition-all group/ucard ${snapshot.isDragging ? "bg-white shadow-lg ring-1 ring-amber-200 border-transparent" : "bg-gray-50 border-gray-100 hover:border-gray-200"}`}
                              data-testid={`unassigned-user-${u.id}`}
                            >
                              {canManage && (
                                <div {...provided.dragHandleProps} className="cursor-grab text-gray-300 hover:text-gray-500 flex-shrink-0 touch-none">
                                  <GripVertical className="w-3.5 h-3.5" />
                                </div>
                              )}
                              <Avatar name={u.name} />
                              <div className="flex-1 min-w-0">
                                <p className="text-xs font-medium text-gray-900 truncate">{u.name}</p>
                                <RoleBadge role={u.role} />
                              </div>
                              {canManage && (
                                <button
                                  onClick={() => openEditUser(u)}
                                  className="opacity-0 group-hover/ucard:opacity-100 p-1 text-gray-300 hover:text-[#1E3A8A] transition-opacity"
                                  data-testid={`edit-user-${u.id}`}
                                ><Pencil className="w-3 h-3" /></button>
                              )}
                            </div>
                          )}
                        </Draggable>
                      ))}
                      {provided.placeholder}

                      {filteredUnassigned.length === 0 && !snapshot.isDraggingOver && (
                        <div className="flex flex-col items-center justify-center py-8 text-gray-300">
                          <UserCheck className="w-8 h-8 mb-2 opacity-50" />
                          <p className="text-xs text-center">
                            {searchQuery ? "No matches" : "All staff assigned"}
                          </p>
                          {!searchQuery && (
                            <p className="text-[10px] mt-1 text-gray-300 text-center">
                              Drag a team member here to unassign
                            </p>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </Droppable>

                {/* Stats footer */}
                <div className="px-4 py-2.5 bg-gray-50 border-t border-gray-100 text-[11px] text-gray-400">
                  {assignedCount} of {totalUsers} staff assigned to a team
                </div>
              </div>
            </div>

          </div>
        </DragDropContext>

        {/* ══ MODALS ══════════════════════════════════════════════════════ */}

        {/* Add / Edit Setting */}
        {(showAddSetting || editingSetting) && (
          <Modal
            title={editingSetting ? `Edit — ${editingSetting.name}` : "New Setting"}
            onClose={() => { setShowAddSetting(false); setEditingSetting(null); }}
          >
            <div className="space-y-3">
              <FormField label="Name *">
                <input value={settingForm.name} onChange={e => setSettingForm(f => ({ ...f, name: e.target.value }))} placeholder="e.g. Sunflower House" className={inputCls} data-testid="setting-name-input" />
              </FormField>
              <FormField label="Description">
                <input value={settingForm.description} onChange={e => setSettingForm(f => ({ ...f, description: e.target.value }))} placeholder="Optional" className={inputCls} />
              </FormField>
              <FormField label="Manager">
                <select value={settingForm.manager_user_id} onChange={e => setSettingForm(f => ({ ...f, manager_user_id: e.target.value }))} className={selectCls}>
                  <option value="">None</option>
                  {managerUsers.map(u => <option key={u.id} value={u.id}>{u.name} ({u.role})</option>)}
                </select>
              </FormField>
              <div className="flex gap-2 pt-1">
                <button onClick={saveSetting} disabled={saving} className="flex items-center gap-1.5 bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF] disabled:opacity-60" data-testid="save-setting-btn">
                  <Check className="w-3.5 h-3.5" />{saving ? "Saving…" : "Save"}
                </button>
                <button onClick={() => { setShowAddSetting(false); setEditingSetting(null); }} className="px-4 py-2 border border-gray-300 text-gray-600 rounded-md text-sm hover:bg-gray-50">Cancel</button>
              </div>
            </div>
          </Modal>
        )}

        {/* Edit Team */}
        {editingTeam && (
          <Modal title={`Edit Team — ${editingTeam.name}`} onClose={() => setEditingTeam(null)}>
            <div className="space-y-3">
              <FormField label="Name *">
                <input value={teamForm.name} onChange={e => setTeamForm(f => ({ ...f, name: e.target.value }))} className={inputCls} data-testid="team-name-input" />
              </FormField>
              <FormField label="Supervisor">
                <select value={teamForm.supervisor_user_id} onChange={e => setTeamForm(f => ({ ...f, supervisor_user_id: e.target.value }))} className={selectCls}>
                  <option value="">None</option>
                  {managerUsers.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}
                </select>
              </FormField>
              <div className="flex gap-2 pt-1">
                <button onClick={() => saveTeam(editingTeam.setting_id)} disabled={saving} className="flex items-center gap-1.5 bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF] disabled:opacity-60" data-testid="save-team-btn">
                  <Check className="w-3.5 h-3.5" />{saving ? "Saving…" : "Save"}
                </button>
                <button onClick={() => setEditingTeam(null)} className="px-4 py-2 border border-gray-300 text-gray-600 rounded-md text-sm hover:bg-gray-50">Cancel</button>
              </div>
            </div>
          </Modal>
        )}

        {/* Add User */}
        {showInviteUser && (
          <Modal title="Add New User" onClose={() => setShowInviteUser(false)}>
            <div className="space-y-3">
              <FormField label="Full Name *">
                <input value={inviteForm.name} onChange={e => setInviteForm(f => ({ ...f, name: e.target.value }))} placeholder="e.g. Jane Smith" className={inputCls} data-testid="invite-name-input" />
              </FormField>
              <FormField label="Email Address *">
                <input type="email" value={inviteForm.email} onChange={e => setInviteForm(f => ({ ...f, email: e.target.value }))} placeholder="jane@example.com" className={inputCls} data-testid="invite-email-input" />
              </FormField>
              <FormField label="Role">
                <select value={inviteForm.role} onChange={e => setInviteForm(f => ({ ...f, role: e.target.value }))} className={selectCls} data-testid="invite-role-select">
                  {ROLES.filter(r => !isAdmin ? r.value !== "admin" : true).map(r => (
                    <option key={r.value} value={r.value}>{r.label}</option>
                  ))}
                </select>
              </FormField>
              <FormField label="Temporary Password *">
                <input type="password" value={inviteForm.password} onChange={e => setInviteForm(f => ({ ...f, password: e.target.value }))} placeholder="Min. 8 characters" className={inputCls} data-testid="invite-password-input" />
              </FormField>
              {inviteError && <p className="text-xs text-red-600" data-testid="invite-error">{inviteError}</p>}
              <div className="flex gap-2 pt-1">
                <button onClick={inviteUser} disabled={savingInvite} className="flex items-center gap-1.5 bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF] disabled:opacity-60" data-testid="save-invite-btn">
                  <UserPlus className="w-3.5 h-3.5" />{savingInvite ? "Adding…" : "Add User"}
                </button>
                <button onClick={() => setShowInviteUser(false)} className="px-4 py-2 border border-gray-300 text-gray-600 rounded-md text-sm hover:bg-gray-50">Cancel</button>
              </div>
            </div>
          </Modal>
        )}

        {/* Edit User */}
        {editingUser && (
          <Modal title={`Edit — ${editingUser.name}`} onClose={() => setEditingUser(null)}>
            <div className="space-y-3">
              <FormField label="Full name">
                <input value={editUserForm.name} onChange={e => setEditUserForm(f => ({ ...f, name: e.target.value }))} className={inputCls} data-testid="edit-user-name" />
              </FormField>
              <FormField label="Email address">
                <input type="email" value={editUserForm.email} onChange={e => setEditUserForm(f => ({ ...f, email: e.target.value }))} className={inputCls} data-testid="edit-user-email" />
              </FormField>
              <FormField label="Role">
                <select value={editUserForm.role} onChange={e => setEditUserForm(f => ({ ...f, role: e.target.value }))} className={selectCls} data-testid="edit-user-role">
                  {ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
                </select>
              </FormField>
              <div className="flex items-center gap-2">
                <input type="checkbox" id="edit-user-active" checked={editUserForm.is_active} onChange={e => setEditUserForm(f => ({ ...f, is_active: e.target.checked }))} className="w-4 h-4 accent-[#1E3A8A]" data-testid="edit-user-active" />
                <label htmlFor="edit-user-active" className="text-sm text-gray-700 cursor-pointer">{editUserForm.is_active ? "Active" : "Inactive"}</label>
              </div>
              <div className="pt-2 border-t border-gray-100">
                <button
                  type="button"
                  onClick={() => { setShowPwdReset(p => !p); setNewPassword(""); }}
                  className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-800 transition-colors"
                  data-testid="toggle-reset-password"
                >
                  <KeyRound className="w-3.5 h-3.5" />
                  {showPwdReset ? "Cancel password change" : "Reset password"}
                  <ChevronDown className={`w-3 h-3 transition-transform ${showPwdReset ? "rotate-180" : ""}`} />
                </button>
                {showPwdReset && (
                  <input
                    type="password"
                    value={newPassword}
                    onChange={e => setNewPassword(e.target.value)}
                    placeholder="New password (min. 8 chars)"
                    className={`mt-2 ${inputCls}`}
                    data-testid="new-password-input"
                  />
                )}
              </div>
              {editUserError && <p className="text-xs text-red-600" data-testid="edit-user-error">{editUserError}</p>}
              <div className="flex gap-2 pt-1">
                <button onClick={saveEditUser} disabled={savingUser} className="flex items-center gap-1.5 bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF] disabled:opacity-60" data-testid="save-edit-user-btn">
                  <Check className="w-3.5 h-3.5" />{savingUser ? "Saving…" : "Save"}
                </button>
                <button onClick={() => setEditingUser(null)} className="border border-gray-300 text-gray-600 px-4 py-2 rounded-md text-sm font-medium hover:bg-gray-50">Cancel</button>
              </div>
            </div>
          </Modal>
        )}

      </div>{/* end main content */}
      </div>{/* end outer wrapper */}
    </Layout>
  );
}

import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import {
  Building2, Users, ChevronRight, Plus, Edit2, Trash2, X, Check,
  MapPin, UserCog, Loader, AlertCircle, CheckCircle,
} from "lucide-react";

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

function ColumnHeader({ icon: Icon, label, count, onAdd, addLabel }) {
  return (
    <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-gray-50">
      <div className="flex items-center gap-2">
        <Icon className="w-4 h-4 text-gray-500" />
        <span className="text-sm font-semibold text-gray-700">{label}</span>
        {count !== undefined && <span className="text-xs text-gray-400">({count})</span>}
      </div>
      {onAdd && (
        <button onClick={onAdd} className="flex items-center gap-1 text-xs text-[#1E3A8A] font-medium hover:underline" data-testid={`add-${addLabel?.toLowerCase().replace(/\s/g, "-")}`}>
          <Plus className="w-3.5 h-3.5" /> {addLabel}
        </button>
      )}
    </div>
  );
}

export default function OrgStructure() {
  const { getAuthConfig, API } = useAuth();
  const [structure, setStructure] = useState({ settings: [], unassigned_users: [] });
  const [allUsers, setAllUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedSetting, setSelectedSetting] = useState(null);
  const [selectedTeam, setSelectedTeam] = useState(null);
  const [showEditSetting, setShowEditSetting] = useState(null);
  const [showEditTeam, setShowEditTeam] = useState(null);
  const [showAddSetting, setShowAddSetting] = useState(false);
  const [showAddTeam, setShowAddTeam] = useState(false);
  const [showAddMember, setShowAddMember] = useState(false);
  const [settingForm, setSettingForm] = useState({ name: "", description: "", manager_user_id: "" });
  const [teamForm, setTeamForm] = useState({ name: "", description: "", supervisor_user_id: "" });
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const fetchData = useCallback(async () => {
    try {
      const [structRes, usersRes] = await Promise.all([
        axios.get(`${API}/org/structure`, getAuthConfig()),
        axios.get(`${API}/admin/users`, getAuthConfig()),
      ]);
      setStructure(structRes.data);
      setAllUsers(usersRes.data);
      // Refresh selected objects from new data
      if (selectedSetting) {
        const refreshed = structRes.data.settings.find(s => s.id === selectedSetting.id);
        setSelectedSetting(refreshed || null);
        if (selectedTeam && refreshed) {
          const rTeam = refreshed.teams?.find(t => t.id === selectedTeam.id);
          setSelectedTeam(rTeam || null);
        }
      }
    } catch (err) {
      console.error("Org structure load failed", err);
      setError("Failed to load organisation structure.");
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const flash = (msg, isError = false) => {
    if (isError) setError(msg); else setMessage(msg);
    setTimeout(() => { setError(""); setMessage(""); }, 3000);
  };

  const managerUsers = allUsers.filter(u => ["admin", "manager"].includes(u.role));

  // ── Settings CRUD ─────────────────────────────────────────────────────────
  const saveSetting = async () => {
    if (!settingForm.name.trim()) return;
    setSaving(true);
    try {
      if (showEditSetting) {
        await axios.put(`${API}/org/settings/${showEditSetting.id}`, settingForm, getAuthConfig());
        flash("Setting updated");
        setShowEditSetting(null);
      } else {
        await axios.post(`${API}/org/settings`, settingForm, getAuthConfig());
        flash("Setting created");
        setShowAddSetting(false);
      }
      setSettingForm({ name: "", description: "", manager_user_id: "" });
      fetchData();
    } catch (err) { flash(err.response?.data?.detail || "Failed to save setting", true); }
    setSaving(false);
  };

  const deleteSetting = async (s) => {
    if (!window.confirm(`Delete "${s.name}"? All teams inside will also be removed.`)) return;
    try {
      await axios.delete(`${API}/org/settings/${s.id}`, getAuthConfig());
      flash("Setting deleted");
      if (selectedSetting?.id === s.id) { setSelectedSetting(null); setSelectedTeam(null); }
      fetchData();
    } catch (err) { flash(err.response?.data?.detail || "Delete failed", true); }
  };

  // ── Teams CRUD ─────────────────────────────────────────────────────────────
  const saveTeam = async () => {
    if (!teamForm.name.trim() || !selectedSetting) return;
    setSaving(true);
    try {
      if (showEditTeam) {
        await axios.put(`${API}/org/teams/${showEditTeam.id}`, teamForm, getAuthConfig());
        flash("Team updated");
        setShowEditTeam(null);
      } else {
        await axios.post(`${API}/org/settings/${selectedSetting.id}/teams`, teamForm, getAuthConfig());
        flash("Team created");
        setShowAddTeam(false);
      }
      setTeamForm({ name: "", description: "", supervisor_user_id: "" });
      fetchData();
    } catch (err) { flash(err.response?.data?.detail || "Failed to save team", true); }
    setSaving(false);
  };

  const deleteTeam = async (t) => {
    if (!window.confirm(`Delete team "${t.name}"? Members will be unassigned.`)) return;
    try {
      await axios.delete(`${API}/org/teams/${t.id}`, getAuthConfig());
      flash("Team deleted");
      if (selectedTeam?.id === t.id) setSelectedTeam(null);
      fetchData();
    } catch (err) { flash(err.response?.data?.detail || "Delete failed", true); }
  };

  // ── Member management ─────────────────────────────────────────────────────
  const addMember = async (userId) => {
    if (!selectedTeam) return;
    try {
      await axios.post(`${API}/org/teams/${selectedTeam.id}/members`, { user_id: userId }, getAuthConfig());
      flash("Member added");
      fetchData();
    } catch (err) { flash(err.response?.data?.detail || "Failed to add member", true); }
  };

  const removeMember = async (userId, userName) => {
    if (!window.confirm(`Remove ${userName} from this team?`)) return;
    try {
      await axios.delete(`${API}/org/teams/${selectedTeam.id}/members/${userId}`, getAuthConfig());
      flash("Member removed");
      fetchData();
    } catch (err) { flash(err.response?.data?.detail || "Failed to remove member", true); }
  };

  const formField = (label, value, onChange, extra = {}) => (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      <input
        value={value}
        onChange={e => onChange(e.target.value)}
        className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
        {...extra}
      />
    </div>
  );

  const selectField = (label, value, onChange, opts, placeholder = "None") => (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      <select value={value} onChange={e => onChange(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] bg-white">
        <option value="">{placeholder}</option>
        {opts.map(o => <option key={o.id} value={o.id}>{o.name} ({o.role})</option>)}
      </select>
    </div>
  );

  const SettingTeamForm = ({ form, setForm, managers, onSave, onCancel }) => (
    <div className="space-y-3">
      {formField("Name *", form.name, v => setForm(f => ({ ...f, name: v })), { placeholder: "e.g. Sunflower House" })}
      {formField("Description", form.description, v => setForm(f => ({ ...f, description: v })), { placeholder: "Optional" })}
      {managers && selectField("Manager / Supervisor", form.manager_user_id || form.supervisor_user_id, v => setForm(f => ({ ...f, manager_user_id: v, supervisor_user_id: v })), managers)}
      <div className="flex gap-2 pt-1">
        <button onClick={onSave} disabled={saving} className="flex items-center gap-1.5 bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF] disabled:opacity-60">
          <Check className="w-3.5 h-3.5" />{saving ? "Saving…" : "Save"}
        </button>
        <button onClick={onCancel} className="px-4 py-2 border border-gray-300 text-gray-600 rounded-md text-sm hover:bg-gray-50">Cancel</button>
      </div>
    </div>
  );

  if (loading) {
    return (
      <Layout>
        <div className="flex items-center justify-center py-24 text-gray-400">
          <Loader className="w-5 h-5 animate-spin mr-2" /><span className="text-sm">Loading structure…</span>
        </div>
      </Layout>
    );
  }

  const currentTeamMembers = selectedTeam ? (structure.settings.find(s => s.id === selectedSetting?.id)?.teams?.find(t => t.id === selectedTeam.id)?.members || []) : [];
  const currentSettingTeams = selectedSetting ? (structure.settings.find(s => s.id === selectedSetting?.id)?.teams || []) : [];

  return (
    <Layout>
      <div className="p-6 md:p-8 fade-in">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-2xl font-semibold text-gray-900" style={{ fontFamily: "Work Sans,sans-serif" }}>Organisation Structure</h1>
          <p className="text-sm text-gray-500 mt-0.5">Manage your care settings, teams, and staff hierarchy</p>
        </div>

        {/* Flash messages */}
        {message && (
          <div className="flex items-center gap-2 bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-md p-3 mb-4 text-sm" data-testid="org-success">
            <CheckCircle className="w-4 h-4 flex-shrink-0" />{message}
          </div>
        )}
        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-md p-3 mb-4 text-sm" data-testid="org-error">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />{error}
            <button onClick={() => setError("")} className="ml-auto"><X className="w-3.5 h-3.5" /></button>
          </div>
        )}

        {/* Unassigned users badge */}
        {structure.unassigned_users.length > 0 && (
          <div className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg flex items-center gap-2 text-sm text-amber-700">
            <Users className="w-4 h-4 flex-shrink-0" />
            <span><strong>{structure.unassigned_users.length}</strong> user{structure.unassigned_users.length !== 1 ? "s" : ""} not yet assigned to a team</span>
          </div>
        )}

        {/* Column layout */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-0 border border-gray-200 rounded-xl overflow-hidden shadow-sm bg-white" style={{ minHeight: 480 }}>

          {/* Column 1 — Settings */}
          <div className="border-r border-gray-200 flex flex-col" data-testid="settings-column">
            <ColumnHeader icon={MapPin} label="Settings (Locations)" count={structure.settings.length} onAdd={() => { setShowAddSetting(true); setSettingForm({ name: "", description: "", manager_user_id: "" }); }} addLabel="Add Setting" />

            {showAddSetting && (
              <div className="p-4 border-b border-gray-100 bg-blue-50">
                <p className="text-xs font-semibold text-[#1E3A8A] mb-3">New Setting</p>
                <SettingTeamForm
                  form={settingForm}
                  setForm={setSettingForm}
                  managers={managerUsers}
                  onSave={saveSetting}
                  onCancel={() => setShowAddSetting(false)}
                />
              </div>
            )}

            <div className="flex-1 overflow-y-auto">
              {structure.settings.length === 0 && !showAddSetting && (
                <div className="text-center py-12 text-gray-400">
                  <Building2 className="w-8 h-8 mx-auto mb-2 opacity-30" />
                  <p className="text-xs">No settings yet</p>
                </div>
              )}
              {structure.settings.map(s => (
                <div
                  key={s.id}
                  onClick={() => { setSelectedSetting(s); setSelectedTeam(null); }}
                  className={`flex items-center justify-between px-4 py-3 cursor-pointer border-b border-gray-100 group transition-colors ${selectedSetting?.id === s.id ? "bg-[#EFF6FF] border-l-2 border-l-[#1E3A8A]" : "hover:bg-gray-50"}`}
                  data-testid={`setting-row-${s.id}`}
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-gray-900 truncate">{s.name}</p>
                    {s.manager_name && <p className="text-xs text-gray-400 truncate">Manager: {s.manager_name}</p>}
                    <p className="text-xs text-gray-400">{s.teams?.length || 0} team{(s.teams?.length || 0) !== 1 ? "s" : ""}</p>
                  </div>
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0 ml-2">
                    <button onClick={e => { e.stopPropagation(); setShowEditSetting(s); setSettingForm({ name: s.name, description: s.description || "", manager_user_id: s.manager_user_id || "" }); }} className="p-1 text-gray-400 hover:text-[#1E3A8A]" data-testid={`edit-setting-${s.id}`}><Edit2 className="w-3.5 h-3.5" /></button>
                    <button onClick={e => { e.stopPropagation(); deleteSetting(s); }} className="p-1 text-gray-400 hover:text-red-500" data-testid={`delete-setting-${s.id}`}><Trash2 className="w-3.5 h-3.5" /></button>
                  </div>
                  <ChevronRight className={`w-4 h-4 ml-2 flex-shrink-0 transition-colors ${selectedSetting?.id === s.id ? "text-[#1E3A8A]" : "text-gray-300"}`} />
                </div>
              ))}
            </div>
          </div>

          {/* Column 2 — Teams */}
          <div className="border-r border-gray-200 flex flex-col" data-testid="teams-column">
            {!selectedSetting ? (
              <div className="flex flex-col h-full">
                <ColumnHeader icon={Users} label="Teams" />
                <div className="flex-1 flex items-center justify-center text-gray-300">
                  <div className="text-center"><Users className="w-8 h-8 mx-auto mb-2 opacity-30" /><p className="text-xs">Select a setting</p></div>
                </div>
              </div>
            ) : (
              <div className="flex flex-col h-full">
                <ColumnHeader icon={Users} label={`Teams — ${selectedSetting.name}`} count={currentSettingTeams.length} onAdd={() => { setShowAddTeam(true); setTeamForm({ name: "", description: "", supervisor_user_id: "" }); }} addLabel="Add Team" />

                {showAddTeam && (
                  <div className="p-4 border-b border-gray-100 bg-blue-50">
                    <p className="text-xs font-semibold text-[#1E3A8A] mb-3">New Team</p>
                    <SettingTeamForm
                      form={teamForm}
                      setForm={setTeamForm}
                      managers={managerUsers}
                      onSave={saveTeam}
                      onCancel={() => setShowAddTeam(false)}
                    />
                  </div>
                )}

                <div className="flex-1 overflow-y-auto">
                  {currentSettingTeams.length === 0 && !showAddTeam && (
                    <div className="text-center py-12 text-gray-400">
                      <Users className="w-8 h-8 mx-auto mb-2 opacity-30" /><p className="text-xs">No teams yet</p>
                    </div>
                  )}
                  {currentSettingTeams.map(t => (
                    <div
                      key={t.id}
                      onClick={() => setSelectedTeam(t)}
                      className={`flex items-center justify-between px-4 py-3 cursor-pointer border-b border-gray-100 group transition-colors ${selectedTeam?.id === t.id ? "bg-[#EFF6FF] border-l-2 border-l-[#1E3A8A]" : "hover:bg-gray-50"}`}
                      data-testid={`team-row-${t.id}`}
                    >
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-gray-900 truncate">{t.name}</p>
                        {t.supervisor_name && <p className="text-xs text-gray-400">Supervisor: {t.supervisor_name}</p>}
                        <p className="text-xs text-gray-400">{t.members?.length || 0} member{(t.members?.length || 0) !== 1 ? "s" : ""}</p>
                      </div>
                      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0 ml-2">
                        <button onClick={e => { e.stopPropagation(); setShowEditTeam(t); setTeamForm({ name: t.name, description: t.description || "", supervisor_user_id: t.supervisor_user_id || "" }); }} className="p-1 text-gray-400 hover:text-[#1E3A8A]" data-testid={`edit-team-${t.id}`}><Edit2 className="w-3.5 h-3.5" /></button>
                        <button onClick={e => { e.stopPropagation(); deleteTeam(t); }} className="p-1 text-gray-400 hover:text-red-500" data-testid={`delete-team-${t.id}`}><Trash2 className="w-3.5 h-3.5" /></button>
                      </div>
                      <ChevronRight className={`w-4 h-4 ml-2 flex-shrink-0 transition-colors ${selectedTeam?.id === t.id ? "text-[#1E3A8A]" : "text-gray-300"}`} />
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Column 3 — Members */}
          <div className="flex flex-col" data-testid="members-column">
            {!selectedTeam ? (
              <div className="flex flex-col h-full">
                <ColumnHeader icon={UserCog} label="Team Members" />
                <div className="flex-1 flex items-center justify-center text-gray-300">
                  <div className="text-center"><UserCog className="w-8 h-8 mx-auto mb-2 opacity-30" /><p className="text-xs">Select a team</p></div>
                </div>
              </div>
            ) : (
              <div className="flex flex-col h-full">
                <ColumnHeader icon={UserCog} label={`Members — ${selectedTeam.name}`} count={currentTeamMembers.length} onAdd={() => setShowAddMember(true)} addLabel="Add Person" />

                <div className="flex-1 overflow-y-auto">
                  {/* Supervisor badge */}
                  {selectedTeam.supervisor_name && (
                    <div className="flex items-center gap-2 px-4 py-3 bg-indigo-50 border-b border-indigo-100">
                      <div className="w-7 h-7 rounded-full bg-[#1E3A8A] flex items-center justify-center text-white text-xs font-semibold flex-shrink-0">
                        {selectedTeam.supervisor_name.split(" ").map(w => w[0]).join("").slice(0, 2)}
                      </div>
                      <div>
                        <p className="text-xs font-semibold text-[#1E3A8A]">{selectedTeam.supervisor_name}</p>
                        <p className="text-xs text-indigo-400">Supervisor</p>
                      </div>
                    </div>
                  )}

                  {currentTeamMembers.filter(m => m.id !== selectedTeam.supervisor_user_id).length === 0 && (
                    <div className="text-center py-8 text-gray-400"><p className="text-xs">No members yet — add people using the button above</p></div>
                  )}

                  {currentTeamMembers.filter(m => m.id !== selectedTeam.supervisor_user_id).map(m => (
                    <div key={m.id} className="flex items-center justify-between px-4 py-2.5 border-b border-gray-100 group hover:bg-gray-50">
                      <div className="flex items-center gap-2 min-w-0">
                        <div className="w-7 h-7 rounded-full bg-gray-200 flex items-center justify-center text-gray-600 text-xs font-semibold flex-shrink-0">
                          {m.name.split(" ").map(w => w[0]).join("").slice(0, 2)}
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm text-gray-900 truncate">{m.name}</p>
                          <p className="text-xs text-gray-400 capitalize truncate">{m.role}</p>
                        </div>
                      </div>
                      <button onClick={() => removeMember(m.id, m.name)} className="opacity-0 group-hover:opacity-100 p-1 text-gray-300 hover:text-red-400 transition-all" data-testid={`remove-member-${m.id}`}>
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Edit Setting Modal */}
      {showEditSetting && (
        <Modal title={`Edit — ${showEditSetting.name}`} onClose={() => setShowEditSetting(null)}>
          <SettingTeamForm form={settingForm} setForm={setSettingForm} managers={managerUsers} onSave={saveSetting} onCancel={() => setShowEditSetting(null)} />
        </Modal>
      )}

      {/* Edit Team Modal */}
      {showEditTeam && (
        <Modal title={`Edit — ${showEditTeam.name}`} onClose={() => setShowEditTeam(null)}>
          <SettingTeamForm form={teamForm} setForm={setTeamForm} managers={managerUsers} onSave={saveTeam} onCancel={() => setShowEditTeam(null)} />
        </Modal>
      )}

      {/* Add Member Modal */}
      {showAddMember && selectedTeam && (
        <Modal title={`Add Person to ${selectedTeam.name}`} onClose={() => setShowAddMember(false)}>
          <p className="text-xs text-gray-500 mb-3">Select from users not yet assigned to a team:</p>
          {structure.unassigned_users.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-4">All users are already assigned to a team</p>
          ) : (
            <div className="space-y-1.5 max-h-60 overflow-y-auto" data-testid="unassigned-users-list">
              {structure.unassigned_users.map(u => (
                <div key={u.id} className="flex items-center justify-between p-2.5 bg-gray-50 rounded-md border border-gray-200">
                  <div>
                    <p className="text-sm font-medium text-gray-900">{u.name}</p>
                    <p className="text-xs text-gray-400 capitalize">{u.role} · {u.email}</p>
                  </div>
                  <button onClick={() => { addMember(u.id); setShowAddMember(false); }} className="flex items-center gap-1 text-xs bg-[#1E3A8A] text-white px-3 py-1.5 rounded-md hover:bg-[#1E40AF]" data-testid={`assign-user-${u.id}`}>
                    <Plus className="w-3 h-3" /> Add
                  </button>
                </div>
              ))}
            </div>
          )}
          <p className="text-xs text-gray-400 mt-3">Need to add a new user? Create them first in <strong>Admin → Users</strong>, then assign here.</p>
        </Modal>
      )}
    </Layout>
  );
}

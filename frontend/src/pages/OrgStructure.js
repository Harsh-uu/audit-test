import React, { useState, useEffect, useCallback, useRef, useMemo } from "react";
import axios from "axios";
import { cachedGet, invalidateCache } from "@/utils/apiCache";
import { useAuth } from "@/context/AuthContext";
import { Skeleton } from "@/components/ui/skeleton";
import Layout from "@/components/Layout";
import { EditUserModal } from "@/components/admin/EditUserModal";
import {
  DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuSub, DropdownMenuSubTrigger, DropdownMenuSubContent,
} from "@/components/ui/dropdown-menu";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import {
  Building2, Users, Plus, Edit2, Trash2, X, Check,
  MapPin, AlertCircle, CheckCircle, Pencil,
  MoreVertical, UserPlus, Eye, ArrowRightLeft, Search,
} from "lucide-react";
// ── Constants ────────────────────────────────────────────────────────────────

const ROLES = [
  { value: "attendee", label: "Staff / Supervisee" },
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

function daysSince(dateStr) {
  if (!dateStr) return null;
  const diff = Math.floor((Date.now() - new Date(dateStr)) / 86400000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  if (diff < 7) return `${diff}d ago`;
  if (diff < 30) return `${Math.round(diff / 7)}w ago`;
  return `${Math.round(diff / 30)}mo ago`;
}

// ── Small UI atoms ─────────────────────────────────────────────────────────

function avatarColor(name = "") {
  const palette = ["#1E3A8A","#7C3AED","#059669","#D97706","#DC2626","#0891B2","#9333EA"];
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) % palette.length;
  return palette[h];
}

function Avatar({ name, bg }) {
  const initials = (name || "?").split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
  const background = bg || avatarColor(name);
  return (
    <div className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold text-white flex-shrink-0" style={{ background }}>
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

function Sparkbar({ data }) {
  const safeData = Array.isArray(data) ? data : [];
  const max = Math.max(...safeData, 1);
  return (
    <div className="flex items-end gap-0.5" style={{ height: 20 }}>
      {safeData.map((v, i) => (
        <div
          key={i}
          className="w-1.5 rounded-sm"
          style={{
            height: v === 0 ? 3 : Math.max(4, Math.round((v / max) * 20)),
            background: v === 0 ? "#E5E7EB" : i === safeData.length - 1 ? "#1E3A8A" : "#93C5FD",
          }}
        />
      ))}
    </div>
  );
}

function Modal({ title, onClose, children, wide }) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className={`bg-white rounded-xl shadow-2xl w-full p-6 ${wide ? "max-w-lg" : "max-w-md"}`}>
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

// ── View profile popover content ────────────────────────────────────────────

function ViewProfileCard({ member, stats }) {
  const joined = stats?.created_at
    ? new Date(stats.created_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })
    : "—";
  const teamLabel = stats?.team_name
    ? (stats.setting_name ? `${stats.team_name}, ${stats.setting_name}` : stats.team_name)
    : "Unassigned";
  const lastActive = stats?.last_meeting_date ? daysSince(stats.last_meeting_date) : "No meetings yet";
  return (
    <div data-testid={`view-profile-${member.id}`}>
      <div className="flex items-center gap-3 mb-3">
        <div className="w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold text-white flex-shrink-0" style={{ background: avatarColor(member.name) }}>
          {(member.name || "?").split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase()}
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-900 truncate">{member.name}</p>
          <p className="text-xs text-gray-400 truncate">{member.email}</p>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-y-1.5 text-xs mb-3">
        <span className="text-gray-400">Role</span><span className="text-gray-800 font-medium text-right">{ROLE_LABELS[member.role] || member.role}</span>
        <span className="text-gray-400">Team</span><span className="text-gray-800 font-medium text-right">{teamLabel}</span>
        <span className="text-gray-400">Joined</span><span className="text-gray-800 font-medium text-right">{joined}</span>
        <span className="text-gray-400">Meetings</span><span className="text-gray-800 font-medium text-right">{stats?.meeting_count ?? "—"}</span>
        <span className="text-gray-400">Last active</span><span className="text-emerald-600 font-medium text-right">{lastActive}</span>
      </div>
      {stats?.weekly_activity && (
        <>
          <p className="text-[10px] text-gray-400 mb-1">8-week activity</p>
          <Sparkbar data={stats.weekly_activity} />
        </>
      )}
    </div>
  );
}

// ── Member row (avatar + "…" View / Move to… / Edit menu) ──────────────────

function MemberRow({ m, teamId, teams, canManage, statsByUser, viewing, onView, onCloseView, onMove, onEdit }) {
  const stats = statsByUser[m.id];
  const moveTargets = teams.filter(t => t.id !== teamId);
  return (
    <Popover open={viewing} onOpenChange={(o) => { if (!o) onCloseView(); }}>
      <PopoverAnchor asChild>
        <div className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-gray-50 group/member" data-testid={`member-${m.id}`}>
          <Avatar name={m.name} />
          <div className="flex-1 min-w-0">
            <p className="text-xs font-medium text-gray-900 truncate">{m.name || "Unnamed user"}</p>
            <div className="flex items-center gap-1.5 min-w-0">
              <RoleBadge role={m.role} />
              {m.email && <span className="text-[10px] text-gray-400 truncate">{m.email}</span>}
            </div>
          </div>
          {canManage && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  className="p-1.5 rounded text-gray-400 hover:text-[#1E3A8A] hover:bg-gray-100 opacity-0 group-hover/member:opacity-100 focus:opacity-100 transition-opacity"
                  data-testid={`member-menu-${m.id}`}
                ><MoreVertical className="w-3.5 h-3.5" /></button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-40 text-sm" onCloseAutoFocus={(e) => e.preventDefault()}>
                <DropdownMenuItem onClick={onView} data-testid={`member-view-${m.id}`}>
                  <Eye className="w-3.5 h-3.5" /> View
                </DropdownMenuItem>
                <DropdownMenuSub>
                  <DropdownMenuSubTrigger data-testid={`member-move-${m.id}`}>
                    <ArrowRightLeft className="w-3.5 h-3.5" /> Move to…
                  </DropdownMenuSubTrigger>
                  <DropdownMenuSubContent className="max-h-64 overflow-y-auto">
                    {teamId && (
                      <DropdownMenuItem onClick={() => onMove(null)} data-testid={`move-unassign-${m.id}`}>
                        Unassign
                      </DropdownMenuItem>
                    )}
                    {moveTargets.length === 0 && !teamId && (
                      <div className="px-2 py-1.5 text-xs text-gray-400">No teams available</div>
                    )}
                    {moveTargets.map(t => (
                      <DropdownMenuItem key={t.id} onClick={() => onMove(t.id)} data-testid={`move-to-${t.id}-${m.id}`}>
                        {t.label}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuSubContent>
                </DropdownMenuSub>
                <DropdownMenuItem onClick={onEdit} data-testid={`member-edit-${m.id}`}>
                  <Pencil className="w-3.5 h-3.5" /> Edit
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </PopoverAnchor>
      <PopoverContent side="right" align="start" className="w-72" data-testid={`member-view-popover-${m.id}`}>
        <ViewProfileCard member={m} stats={stats} />
      </PopoverContent>
    </Popover>
  );
}

// ── Team card (header + member rows) ────────────────────────────────────────

function TeamCard({ t, canManage, isAdmin, teamsFlat, statsByUser, viewingUserId, onSetViewingUserId, onMoveUser, onEditTeam, onDeleteTeam, onEditUser }) {
  const memberCount = (t.members || []).length;
  return (
    <div className="border border-gray-200 rounded-xl overflow-hidden mb-3 bg-white" data-testid={`team-${t.id}`}>
      <div className="flex items-center gap-2 px-4 py-2.5 bg-gray-50 border-b border-gray-100 group">
        <Users className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
        <span className="text-xs font-semibold text-gray-800">{t.name}</span>
        <span className="text-[11px] text-gray-400">Supervisor: {t.supervisor_name || "—"}</span>
        {canManage && (
          <div className="flex items-center gap-0.5 ml-auto opacity-0 group-hover:opacity-100 transition-opacity">
            <button onClick={onEditTeam} className="p-1 text-gray-400 hover:text-[#1E3A8A]" data-testid={`edit-team-${t.id}`}><Edit2 className="w-3 h-3" /></button>
            {isAdmin && (
              <button
                onClick={onDeleteTeam}
                disabled={memberCount > 0}
                title={memberCount > 0 ? `Move all ${memberCount} staff out first` : "Delete empty team"}
                className="p-1 text-gray-400 hover:text-red-500 disabled:opacity-30 disabled:hover:text-gray-400 disabled:cursor-not-allowed"
                data-testid={`delete-team-${t.id}`}
              ><Trash2 className="w-3 h-3" /></button>
            )}
          </div>
        )}
      </div>
      <div className="p-2 space-y-0.5">
        {(t.members || []).length === 0 ? (
          <div className="flex items-center justify-center h-10 text-[11px] text-gray-300">No members yet</div>
        ) : t.members.map(m => (
          <MemberRow
            key={m.id}
            m={m}
            teamId={t.id}
            teams={teamsFlat}
            canManage={canManage}
            statsByUser={statsByUser}
            viewing={viewingUserId === m.id}
            onView={() => onSetViewingUserId(m.id)}
            onCloseView={() => onSetViewingUserId(null)}
            onMove={(toTeamId) => onMoveUser(m.id, t.id, toTeamId)}
            onEdit={() => onEditUser(m)}
          />
        ))}
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function OrgStructure({ embedded = false, onUserChanged }) {
  const { getAuthConfig, API, user: currentUser } = useAuth();
  const isAdmin = currentUser?.role === "admin";
  const canManage = ["admin", "manager"].includes(currentUser?.role);

  const [structure, setStructure] = useState({ settings: [], unassigned_users: [] });
  const [allUsers, setAllUsers] = useState([]);
  const [peopleStats, setPeopleStats] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedSettingId, setSelectedSettingId] = useState(null);
  const isFirstLoad = useRef(true);

  // Flash
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  // Saving states
  const [saving, setSaving] = useState(false);
  const [savingInvite, setSavingInvite] = useState(false);

  // "View" popover — one open at a time
  const [viewingUserId, setViewingUserId] = useState(null);

  // Whole-tree staff search (left pane)
  const [staffSearch, setStaffSearch] = useState("");
  const [staffSearchFocused, setStaffSearchFocused] = useState(false);

  // Modals
  const [showAddSetting, setShowAddSetting] = useState(false);
  const [editingSetting, setEditingSetting] = useState(null);
  const [showAddTeamFor, setShowAddTeamFor] = useState(null); // settingId
  const [editingTeam, setEditingTeam] = useState(null);
  const [editingUser, setEditingUser] = useState(null);
  const [showInviteUser, setShowInviteUser] = useState(false);
  const [showUnassignedModal, setShowUnassignedModal] = useState(false);

  // Forms
  const [settingForm, setSettingForm] = useState({ name: "", description: "", manager_user_id: "" });
  const [teamForm, setTeamForm] = useState({ name: "", description: "", supervisor_user_id: "" });
  const [inviteForm, setInviteForm] = useState({ name: "", email: "", password: "", role: "attendee", team_id: "" });
  const [inviteError, setInviteError] = useState("");

  // ── Data fetching ────────────────────────────────────────────────────────
  const fetchData = useCallback(async () => {
    try {
      const [structRes, usersRes, statsRes] = await Promise.all([
        cachedGet(`${API}/org/structure`, getAuthConfig()),
        cachedGet(`${API}/admin/users`, getAuthConfig()),
        cachedGet(`${API}/admin/people-stats`, getAuthConfig()),
      ]);
      setStructure(structRes.data);
      setAllUsers(usersRes.data);
      setPeopleStats(statsRes.data);
      isFirstLoad.current = false;
    } catch (err) {
      console.error("Org structure load failed", err.message);
      flash("Failed to load organisation structure", true);
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API]);

  // Bust org caches then re-fetch — call this after any mutation, and AWAIT it
  // before closing an edit modal. Without the await, a save closed the modal
  // immediately while structure was still stale (~a few hundred ms round trip);
  // reopening "Edit" on that same row during that window prefilled the OLD
  // pre-save values, and clicking Save again silently reverted the change.
  const refreshData = useCallback(async () => {
    invalidateCache("/org/structure", "/admin/users", "/admin/people-stats");
    await fetchData();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchData]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Keep a valid selection: default to the first setting on load, and fall
  // back to it whenever the currently-selected setting disappears (deleted).
  useEffect(() => {
    if (loading) return;
    if (structure.settings.length === 0) {
      if (selectedSettingId !== null) setSelectedSettingId(null);
      return;
    }
    if (!structure.settings.some(s => s.id === selectedSettingId)) {
      setSelectedSettingId(structure.settings[0].id);
    }
  }, [structure, loading, selectedSettingId]);

  const flash = (msg, isError = false) => {
    if (isError) setError(msg); else setMessage(msg);
    setTimeout(() => { setError(""); setMessage(""); }, 3500);
  };

  const managerUsers = allUsers.filter(u => ["admin", "manager"].includes(u.role));

  // Group manager/admin candidates by the Setting they already belong to, so
  // Setting-manager / Team-supervisor pickers don't just show one long flat
  // list — "Unassigned" (safest picks for a brand-new home) always sorts first.
  const groupedManagerOptions = useMemo(() => {
    const settingNameById = {};
    structure.settings.forEach(s => { settingNameById[s.id] = s.name; });
    const groups = {};
    managerUsers.forEach(u => {
      const label = u.setting_id ? (settingNameById[u.setting_id] || "Other setting") : "Unassigned";
      (groups[label] = groups[label] || []).push(u);
    });
    const otherLabels = Object.keys(groups).filter(l => l !== "Unassigned").sort();
    const orderedLabels = [...(groups["Unassigned"] ? ["Unassigned"] : []), ...otherLabels];
    return orderedLabels.map(label => ({ label, users: groups[label] }));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allUsers, structure]);
  const statsByUser = useMemo(() => {
    const map = {};
    peopleStats.forEach(p => { map[p.user_id] = p; });
    return map;
  }, [peopleStats]);

  // All teams org-wide, flattened, for the "Move to…" submenu — prefixed
  // with the setting name only when there's more than one setting to disambiguate.
  const teamsFlat = useMemo(() => {
    const multi = structure.settings.length > 1;
    const flat = [];
    structure.settings.forEach(s => (s.teams || []).forEach(t => {
      flat.push({ id: t.id, label: multi ? `${s.name} — ${t.name}` : t.name });
    }));
    return flat;
  }, [structure]);

  const selectedSetting = structure.settings.find(s => s.id === selectedSettingId) || null;

  // Whole-tree staff index — flattens every member across every Setting/Team
  // plus the unassigned pool, built from data already in `structure` (no
  // extra API call). Filtered client-side as the admin types.
  const allStaffFlat = useMemo(() => {
    const flat = [];
    structure.settings.forEach(s => (s.teams || []).forEach(t => (t.members || []).forEach(m => {
      flat.push({ ...m, settingId: s.id, settingName: s.name, teamName: t.name });
    })));
    structure.unassigned_users.forEach(u => {
      flat.push({ ...u, settingId: null, settingName: null, teamName: null });
    });
    return flat;
  }, [structure]);

  const staffSearchResults = useMemo(() => {
    const q = staffSearch.trim().toLowerCase();
    if (!q) return [];
    return allStaffFlat
      .filter(u => (u.name || "").toLowerCase().includes(q) || (u.email || "").toLowerCase().includes(q))
      .slice(0, 8);
  }, [allStaffFlat, staffSearch]);

  // Jump to a search result: switch the master-detail pane to that person's
  // Setting (or open the Unassigned modal) and pop their View card straight open.
  const jumpToStaff = (u) => {
    setStaffSearch("");
    if (u.settingId) {
      setShowUnassignedModal(false);
      setSelectedSettingId(u.settingId);
    } else {
      setShowUnassignedModal(true);
    }
    setViewingUserId(u.id);
  };

  // ── Move user (used by the "Move to…" menu) ─────────────────────────────
  const moveUser = async (userId, fromTeamId, toTeamId) => {
    if (fromTeamId === toTeamId) return;
    const movedUser = findUser(userId, structure);
    if (!movedUser) return;
    setStructure(prev => moveUserInStructure(prev, movedUser, fromTeamId, toTeamId));
    try {
      await axios.patch(`${API}/org/users/${userId}/assign-team`, { team_id: toTeamId }, getAuthConfig());
      invalidateCache("/admin/people-stats");
      flash(`${movedUser.name} moved`);
    } catch (err) {
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
        await refreshData();
        flash("Setting updated");
        setEditingSetting(null);
      } else {
        const res = await axios.post(`${API}/org/settings`, settingForm, getAuthConfig());
        await refreshData();
        flash("Setting created");
        setShowAddSetting(false);
        if (res.data?.id) setSelectedSettingId(res.data.id);
      }
      setSettingForm({ name: "", description: "", manager_user_id: "" });
    } catch (err) { flash(err.response?.data?.detail || "Failed to save", true); }
    setSaving(false);
  };

  const deleteSetting = async (s) => {
    if (!window.confirm(`Delete "${s.name}"? This cannot be undone.`)) return;
    try {
      await axios.delete(`${API}/org/settings/${s.id}`, getAuthConfig());
      await refreshData();
      flash("Setting deleted");
    } catch (err) { flash(err.response?.data?.detail || "Delete failed", true); }
  };

  // ── Teams CRUD ─────────────────────────────────────────────────────────────
  const saveTeam = async (settingId) => {
    if (!teamForm.name.trim()) return;
    setSaving(true);
    try {
      if (editingTeam) {
        await axios.put(`${API}/org/teams/${editingTeam.id}`, teamForm, getAuthConfig());
        await refreshData();
        flash("Team updated");
        setEditingTeam(null);
      } else {
        await axios.post(`${API}/org/settings/${settingId}/teams`, teamForm, getAuthConfig());
        await refreshData();
        flash("Team created");
        setShowAddTeamFor(null);
      }
      setTeamForm({ name: "", description: "", supervisor_user_id: "" });
    } catch (err) { flash(err.response?.data?.detail || "Failed to save", true); }
    setSaving(false);
  };

  const deleteTeam = async (t) => {
    if (!window.confirm(`Delete team "${t.name}"? This cannot be undone.`)) return;
    try {
      await axios.delete(`${API}/org/teams/${t.id}`, getAuthConfig());
      await refreshData();
      flash("Team deleted");
    } catch (err) { flash(err.response?.data?.detail || "Delete failed", true); }
  };

  // ── User management ────────────────────────────────────────────────────────
  // Structure tree's member/unassigned-user rows are a trimmed subset (id/name/
  // email/role only) — look up the full record (mfa_enabled, team_id, etc.) from
  // allUsers so the shared EditUserModal has everything it needs, same as PeopleHub.
  const openEditUser = (u) => {
    const full = allUsers.find(au => au.id === u.id) || u;
    setEditingUser(full);
  };

  const onUserSaved = async () => {
    await refreshData();
    flash("User updated");
    setEditingUser(null);
    // Structure tab is embedded inside PeopleHub, which keeps its own
    // /admin/people-stats-backed state (People & Usage tab) — that parent
    // state doesn't refetch on its own just because we refreshed here, so
    // notify it explicitly to avoid showing stale team/role data.
    onUserChanged?.();
  };

  const openAddUserForSetting = () => {
    const teams = selectedSetting?.teams || [];
    if (teams.length === 0) return;
    setInviteForm({ name: "", email: "", password: "", role: "attendee", team_id: teams[0].id });
    setInviteError("");
    setShowInviteUser(true);
  };

  const inviteUser = async () => {
    if (!inviteForm.name.trim()) return setInviteError("Name is required");
    if (!inviteForm.email.trim()) return setInviteError("Email is required");
    if (!inviteForm.team_id) return setInviteError("Team is required");
    if (inviteForm.password.length < 10) return setInviteError("Password must be at least 10 characters");
    setSavingInvite(true);
    setInviteError("");
    try {
      const res = await axios.post(`${API}/org/invite-user`, {
        name: inviteForm.name, email: inviteForm.email, password: inviteForm.password, role: inviteForm.role,
      }, getAuthConfig());
      await axios.patch(`${API}/org/users/${res.data.id}/assign-team`, { team_id: inviteForm.team_id }, getAuthConfig());
      await refreshData();
      flash("User added successfully");
      setShowInviteUser(false);
    } catch (err) { setInviteError(err.response?.data?.detail || "Failed to add user"); }
    setSavingInvite(false);
  };

  // ── Derived values ─────────────────────────────────────────────────────────
  const totalUsers = allUsers.length;
  const assignedCount = totalUsers - structure.unassigned_users.length;

  // ── Loading state ──────────────────────────────────────────────────────────
  if (loading) {
    const skeletonEl = (
      <div className="p-6 md:p-8">
        <div className="flex items-center justify-between mb-6">
          <div className="space-y-2">
            <Skeleton className="h-7 w-52" />
            <Skeleton className="h-4 w-72" />
          </div>
        </div>
        <div className="flex flex-col lg:flex-row gap-5">
          <div className="w-full lg:w-72 flex-shrink-0 bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100">
              <Skeleton className="h-4 w-24" />
            </div>
            <div className="p-3 space-y-3">
              {[...Array(3)].map((_, i) => (
                <div key={i} className="space-y-1.5 px-2">
                  <Skeleton className="h-4 w-36" />
                  <Skeleton className="h-3 w-24" />
                </div>
              ))}
            </div>
          </div>
          <div className="flex-1 bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden p-4 space-y-3">
            <Skeleton className="h-6 w-48" />
            {[...Array(2)].map((_, ti) => (
              <div key={ti} className="border border-gray-100 rounded-lg overflow-hidden">
                <div className="flex items-center gap-2 px-3 py-2.5 bg-gray-50 border-b border-gray-100">
                  <Skeleton className="h-3.5 w-3.5 rounded flex-shrink-0" />
                  <Skeleton className="h-3 w-28" />
                </div>
                <div className="flex gap-1.5 p-2">
                  {[...Array(3)].map((_, mi) => (
                    <Skeleton key={mi} className="h-6 w-6 rounded-full" />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
    return embedded ? skeletonEl : <Layout>{skeletonEl}</Layout>;
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  const Wrapper = embedded ? React.Fragment : Layout;
  const selectedTeams = selectedSetting?.teams || [];
  const selectedStaffCount = selectedTeams.reduce((n, t) => n + (t.members?.length || 0), 0);

  return (
    <Wrapper>
      <div>
        <div className="p-6 md:p-8 fade-in">

          {/* Page header */}
          <div className="flex items-center justify-between mb-6">
            <div>
              <h1 className="text-2xl font-semibold text-gray-900 font-display">Organisation Structure</h1>
              <p className="text-sm text-gray-500 mt-0.5">
                {structure.settings.length} setting{structure.settings.length !== 1 ? "s" : ""} · {assignedCount}/{totalUsers} staff assigned
              </p>
            </div>
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

          {/* ── Master–detail layout ── */}
          <div className="flex flex-col lg:flex-row gap-5" style={{ alignItems: "flex-start" }}>

            {/* ══ LEFT: Settings master list ══════════════════════════════ */}
            <div className="w-full lg:w-72 flex-shrink-0 bg-white rounded-xl border border-gray-200 shadow-sm lg:sticky lg:top-4" data-testid="settings-master-list">
              <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
                <span className="text-xs font-bold uppercase tracking-wider text-gray-400">Settings ({structure.settings.length})</span>
                {canManage && (
                  <button
                    onClick={() => { setShowAddSetting(true); setSettingForm({ name: "", description: "", manager_user_id: "" }); }}
                    className="text-xs font-medium text-[#1E3A8A] hover:underline"
                    data-testid="add-setting-btn"
                  >+ Add</button>
                )}
              </div>
              <div className="px-3 py-2.5 border-b border-gray-100 relative">
                <div className="relative">
                  <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input
                    value={staffSearch}
                    onChange={e => setStaffSearch(e.target.value)}
                    onFocus={() => setStaffSearchFocused(true)}
                    onBlur={() => setTimeout(() => setStaffSearchFocused(false), 150)}
                    placeholder="Search staff org-wide…"
                    className="w-full pl-7 pr-3 py-1.5 border border-gray-200 rounded-md text-xs focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
                    data-testid="staff-search-input"
                  />
                </div>
                {staffSearchFocused && staffSearch.trim() && (
                  <div className="absolute left-3 right-3 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-72 overflow-y-auto z-20" data-testid="staff-search-results">
                    {staffSearchResults.length === 0 ? (
                      <div className="px-3 py-3 text-xs text-gray-400 text-center">No staff match "{staffSearch}"</div>
                    ) : staffSearchResults.map(u => (
                      <button
                        key={u.id}
                        onClick={() => jumpToStaff(u)}
                        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-gray-50 text-left border-b border-gray-50 last:border-0"
                        data-testid={`staff-search-result-${u.id}`}
                      >
                        <Avatar name={u.name} />
                        <div className="flex-1 min-w-0">
                          <p className="text-xs font-medium text-gray-900 truncate">{u.name || "Unnamed user"}</p>
                          <p className="text-[11px] text-gray-400 truncate">{u.settingName ? `${u.teamName}, ${u.settingName}` : "Unassigned"}</p>
                        </div>
                        <RoleBadge role={u.role} />
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <div className="max-h-[70vh] overflow-y-auto">
                {structure.settings.length === 0 && (
                  <div className="text-center py-12 px-4 text-gray-400">
                    <Building2 className="w-8 h-8 mx-auto mb-2 opacity-20" />
                    <p className="text-xs font-medium">No settings yet</p>
                    {canManage && <p className="text-[11px] mt-1">Use "+ Add" to get started</p>}
                  </div>
                )}
                {structure.settings.map(s => {
                  const teams = s.teams || [];
                  const staffCount = teams.reduce((n, t) => n + (t.members?.length || 0), 0);
                  const isSelected = selectedSettingId === s.id;
                  return (
                    <div
                      key={s.id}
                      onClick={() => setSelectedSettingId(s.id)}
                      className={`px-4 py-3 border-l-[3px] cursor-pointer transition-colors ${isSelected ? "border-[#1E3A8A] bg-[#EFF6FF]" : "border-transparent hover:bg-gray-50"}`}
                      data-testid={`setting-row-${s.id}`}
                    >
                      <div className="flex items-center gap-2">
                        <MapPin className={`w-4 h-4 flex-shrink-0 ${isSelected ? "text-[#1E3A8A]" : "text-gray-400"}`} />
                        <span className={`text-sm truncate ${isSelected ? "font-semibold text-gray-900" : "font-medium text-gray-700"}`}>{s.name}</span>
                      </div>
                      <p className="text-xs text-gray-500 mt-1 ml-6">{teams.length} team{teams.length !== 1 ? "s" : ""} · {staffCount} staff</p>
                      <p className="text-xs text-gray-400 ml-6">Manager: {s.manager_name || "—"}</p>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* ══ RIGHT: Detail pane ═══════════════════════════════════════ */}
            <div className="flex-1 min-w-0 bg-white rounded-xl border border-gray-200 shadow-sm p-5" data-testid="setting-detail-panel">
              {!selectedSetting ? (
                <div className="text-center py-16 text-gray-400">
                  <Building2 className="w-10 h-10 mx-auto mb-3 opacity-20" />
                  <p className="text-sm font-medium">No setting selected</p>
                  {canManage && <p className="text-xs mt-1">Add a setting on the left to get started</p>}
                </div>
              ) : (
                <>
                  <div className="flex items-center justify-between mb-4 gap-3 flex-wrap">
                    <div className="min-w-0">
                      <h2 className="text-lg font-semibold text-gray-900 truncate">{selectedSetting.name}</h2>
                      <p className="text-xs text-gray-500">{selectedTeams.length} team{selectedTeams.length !== 1 ? "s" : ""} · {selectedStaffCount} staff{selectedSetting.manager_name ? ` · Manager: ${selectedSetting.manager_name}` : ""}</p>
                    </div>
                    {canManage && (
                      <div className="flex items-center gap-2 flex-shrink-0">
                        <button
                          onClick={() => { setEditingSetting(selectedSetting); setSettingForm({ name: selectedSetting.name, description: selectedSetting.description || "", manager_user_id: selectedSetting.manager_user_id || "" }); }}
                          className="p-1.5 text-gray-400 hover:text-[#1E3A8A] hover:bg-gray-50 rounded"
                          title="Edit setting"
                          data-testid={`edit-setting-${selectedSetting.id}`}
                        ><Edit2 className="w-4 h-4" /></button>
                        {isAdmin && (
                          <button
                            onClick={() => deleteSetting(selectedSetting)}
                            disabled={selectedTeams.length > 0}
                            title={selectedTeams.length > 0 ? `Move or delete all ${selectedTeams.length} team(s) out first` : "Delete empty setting"}
                            className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-gray-50 rounded disabled:opacity-30 disabled:hover:text-gray-400 disabled:cursor-not-allowed"
                            data-testid={`delete-setting-${selectedSetting.id}`}
                          ><Trash2 className="w-4 h-4" /></button>
                        )}
                        <button
                          onClick={openAddUserForSetting}
                          disabled={selectedTeams.length === 0}
                          title={selectedTeams.length === 0 ? "Add a team first" : undefined}
                          className="flex items-center gap-1.5 text-sm font-medium px-3 py-1.5 rounded-lg border border-[#1E3A8A] text-[#1E3A8A] hover:bg-[#EFF6FF] disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent transition-colors"
                          data-testid="add-user-btn"
                        ><UserPlus className="w-3.5 h-3.5" /> Add User</button>
                        <button
                          onClick={() => { setShowAddTeamFor(selectedSetting.id); setTeamForm({ name: "", description: "", supervisor_user_id: "" }); }}
                          className="flex items-center gap-1.5 bg-[#1E3A8A] text-white text-sm font-medium px-3 py-1.5 rounded-lg hover:bg-[#1E40AF] transition-colors"
                          data-testid={`add-team-btn-${selectedSetting.id}`}
                        ><Plus className="w-3.5 h-3.5" /> Add Team</button>
                      </div>
                    )}
                  </div>

                  {structure.unassigned_users.length > 0 && (
                    <div className="flex items-center gap-2 bg-amber-50 border border-amber-200 text-amber-800 rounded-lg px-3 py-2 mb-4 text-xs" data-testid="unassigned-banner">
                      <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                      <span className="font-medium">{structure.unassigned_users.length} unassigned staff org-wide</span>
                      <button onClick={() => setShowUnassignedModal(true)} className="ml-auto underline font-medium" data-testid="manage-unassigned-btn">Manage</button>
                    </div>
                  )}

                  {selectedTeams.length === 0 ? (
                    <div className="text-center py-14 text-gray-400">
                      <Users className="w-9 h-9 mx-auto mb-2 opacity-20" />
                      <p className="text-sm font-medium">No teams yet</p>
                      {canManage && <p className="text-xs mt-1">Use "Add Team" to get started</p>}
                    </div>
                  ) : (
                    selectedTeams.map(t => (
                      <TeamCard
                        key={t.id}
                        t={t}
                        canManage={canManage}
                        isAdmin={isAdmin}
                        teamsFlat={teamsFlat}
                        statsByUser={statsByUser}
                        viewingUserId={viewingUserId}
                        onSetViewingUserId={setViewingUserId}
                        onMoveUser={moveUser}
                        onEditTeam={() => { setEditingTeam(t); setTeamForm({ name: t.name, description: t.description || "", supervisor_user_id: t.supervisor_user_id || "" }); }}
                        onDeleteTeam={() => deleteTeam(t)}
                        onEditUser={openEditUser}
                      />
                    ))
                  )}

                  {/* Inline Add Team form */}
                  {canManage && showAddTeamFor === selectedSetting.id && (
                    <div className="border border-blue-200 rounded-lg p-3 bg-blue-50" data-testid="add-team-form">
                      <p className="text-xs font-semibold text-[#1E3A8A] mb-2">New team in {selectedSetting.name}</p>
                      <div className="space-y-2">
                        <input
                          value={teamForm.name}
                          onChange={e => setTeamForm(f => ({ ...f, name: e.target.value }))}
                          placeholder="Team name *"
                          className={inputCls}
                          onKeyDown={e => { if (e.key === "Enter") saveTeam(selectedSetting.id); if (e.key === "Escape") setShowAddTeamFor(null); }}
                          autoFocus
                          data-testid="new-team-name-input"
                        />
                        <select
                          value={teamForm.supervisor_user_id}
                          onChange={e => setTeamForm(f => ({ ...f, supervisor_user_id: e.target.value }))}
                          className={selectCls}
                        >
                          <option value="">Supervisor — optional</option>
                          {groupedManagerOptions.map(g => (
                            <optgroup key={g.label} label={g.label}>
                              {g.users.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}
                            </optgroup>
                          ))}
                        </select>
                        <div className="flex gap-2">
                          <button
                            onClick={() => saveTeam(selectedSetting.id)}
                            disabled={saving || !teamForm.name.trim()}
                            className="flex items-center gap-1 bg-[#1E3A8A] text-white text-xs px-3 py-1.5 rounded hover:bg-[#1E40AF] disabled:opacity-60"
                            data-testid="save-new-team-btn"
                          ><Check className="w-3 h-3" />{saving ? "Saving…" : "Save"}</button>
                          <button onClick={() => setShowAddTeamFor(null)} className="text-xs px-3 py-1.5 border border-gray-300 rounded hover:bg-white">Cancel</button>
                        </div>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>

          </div>

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
                    {groupedManagerOptions.map(g => (
                      <optgroup key={g.label} label={g.label}>
                        {g.users.map(u => <option key={u.id} value={u.id}>{u.name} ({u.role})</option>)}
                      </optgroup>
                    ))}
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
                    {groupedManagerOptions.map(g => (
                      <optgroup key={g.label} label={g.label}>
                        {g.users.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}
                      </optgroup>
                    ))}
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

          {/* Add User — scoped to the selected Setting's teams, team is required */}
          {showInviteUser && selectedSetting && (
            <Modal title={`Add User — ${selectedSetting.name}`} onClose={() => setShowInviteUser(false)}>
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
                <FormField label={`Team * (within ${selectedSetting.name})`}>
                  <select value={inviteForm.team_id} onChange={e => setInviteForm(f => ({ ...f, team_id: e.target.value }))} className={selectCls} data-testid="invite-team-select">
                    {(selectedSetting.teams || []).map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                  </select>
                  <p className="text-[11px] text-gray-400 mt-1">Required — every new user must belong to a team.</p>
                </FormField>
                <FormField label="Temporary Password *">
                  <input type="password" value={inviteForm.password} onChange={e => setInviteForm(f => ({ ...f, password: e.target.value }))} placeholder="Min. 10 characters" className={inputCls} data-testid="invite-password-input" />
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

          {/* Manage unassigned staff (org-wide) */}
          {showUnassignedModal && (
            <Modal title={`Unassigned Staff (${structure.unassigned_users.length})`} onClose={() => setShowUnassignedModal(false)} wide>
              <div className="space-y-0.5 max-h-96 overflow-y-auto" data-testid="unassigned-modal-list">
                {structure.unassigned_users.length === 0 ? (
                  <p className="text-xs text-gray-400 text-center py-6">All staff assigned</p>
                ) : structure.unassigned_users.map(u => (
                  <MemberRow
                    key={u.id}
                    m={u}
                    teamId={null}
                    teams={teamsFlat}
                    canManage={canManage}
                    statsByUser={statsByUser}
                    viewing={viewingUserId === u.id}
                    onView={() => setViewingUserId(u.id)}
                    onCloseView={() => setViewingUserId(null)}
                    onMove={(toTeamId) => moveUser(u.id, null, toTeamId)}
                    onEdit={() => openEditUser(u)}
                  />
                ))}
              </div>
            </Modal>
          )}

          {/* Edit User */}
          {editingUser && (
            <EditUserModal
              person={editingUser}
              onClose={() => setEditingUser(null)}
              onSaved={onUserSaved}
              API={API}
              getAuthConfig={getAuthConfig}
              currentUserRole={currentUser?.role}
            />
          )}

        </div>
      </div>
    </Wrapper>
  );
}

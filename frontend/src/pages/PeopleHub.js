import React, { useState, useEffect, useCallback, useMemo } from "react";
import axios from "axios";
import { cachedGet, invalidateCache } from "@/utils/apiCache";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import OrgStructure from "@/pages/OrgStructure";
import OrgSettings  from "@/pages/OrgSettings";
import { EditUserModal } from "@/components/admin/EditUserModal";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Users, Settings, Building2,
  RefreshCw, Search, AlertTriangle, Check,
  Mail, MoreHorizontal,
} from "lucide-react";

// ── Avatar helper ────────────────────────────────────────────────────────────
function avatarColor(name) {
  const safe = name || "";
  const palette = ["#1E3A8A","#7C3AED","#059669","#D97706","#DC2626","#0891B2","#9333EA"];
  let h = 0;
  for (const c of safe) h = (h * 31 + c.charCodeAt(0)) % palette.length;
  return palette[h];
}

function initials(name) {
  return (name || "").split(" ").map(w => w[0]).join("").toUpperCase().slice(0, 2);
}

// ── Sparkbar ─────────────────────────────────────────────────────────────────
function Sparkbar({ data }) {
  const safeData = Array.isArray(data) ? data : [];
  const max = Math.max(...safeData, 1);
  return (
    <div className="flex items-end gap-0.5" style={{ height: 22 }}>
      {safeData.map((v, i) => (
        <div
          key={i}
          className="w-1.5 rounded-sm"
          style={{
            height: v === 0 ? 3 : Math.max(4, Math.round((v / max) * 22)),
            background: v === 0 ? "#E5E7EB" : i === safeData.length - 1 ? "#1E3A8A" : "#93C5FD",
          }}
        />
      ))}
    </div>
  );
}

// ── People & Usage tab ───────────────────────────────────────────────────────
function PeopleTab({ people, loading, onRefresh, onRevoke, onEdit }) {
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const [teamFilter, setTeamFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");

  const today = new Date().toISOString().slice(0, 10);

  const teams = useMemo(() => {
    const s = new Set();
    people.forEach(p => { if (p.team_name) s.add(p.team_name); });
    return Array.from(s).sort();
  }, [people]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return people.filter(p => {
      if (q && !p.name.toLowerCase().includes(q) && !p.email.toLowerCase().includes(q)) return false;
      if (roleFilter !== "all" && p.role !== roleFilter) return false;
      if (teamFilter !== "all" && p.team_name !== teamFilter) return false;
      if (statusFilter === "active" && (p.pending_invite || !p.is_active)) return false;
      if (statusFilter === "inactive") {
        const inactive = !p.last_meeting_date || p.last_meeting_date < new Date(Date.now() - 30*24*60*60*1000).toISOString().slice(0, 10);
        if (!inactive || p.pending_invite) return false;
      }
      if (statusFilter === "pending" && !p.pending_invite) return false;
      return true;
    });
  }, [people, search, roleFilter, teamFilter, statusFilter]);

  const stats = useMemo(() => {
    const cutoff = new Date(Date.now() - 30*24*60*60*1000).toISOString().slice(0, 10);
    const active  = people.filter(p => !p.pending_invite && p.last_meeting_date && p.last_meeting_date >= cutoff).length;
    const inactive = people.filter(p => !p.pending_invite && (!p.last_meeting_date || p.last_meeting_date < cutoff)).length;
    const pending = people.filter(p => p.pending_invite).length;
    const totalMtgs = people.reduce((s, p) => s + p.meeting_count, 0);
    const activePeople = people.filter(p => !p.pending_invite && p.meeting_count > 0).length;
    const avg = activePeople > 0 ? (totalMtgs / activePeople).toFixed(1) : "—";
    return { total: people.length, active, inactive, pending, avg };
  }, [people]);

  const daysSince = (dateStr) => {
    if (!dateStr) return null;
    const diff = Math.floor((Date.now() - new Date(dateStr)) / 86400000);
    if (diff === 0) return "Today";
    if (diff === 1) return "Yesterday";
    if (diff < 7) return `${diff}d ago`;
    if (diff < 30) return `${Math.round(diff / 7)}w ago`;
    return `${Math.round(diff / 30)}mo ago`;
  };

  const isInactive = (p) => {
    if (p.pending_invite) return false;
    const cutoff = new Date(Date.now() - 30*24*60*60*1000).toISOString().slice(0, 10);
    return !p.last_meeting_date || p.last_meeting_date < cutoff;
  };

  if (loading) return (
    <div className="flex-1 p-6 space-y-4" aria-busy="true" aria-label="Loading staff data">
      {/* Stat strip skeleton */}
      <div className="grid grid-cols-4 gap-3 mb-5">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="bg-white border border-gray-200 rounded-lg p-4 space-y-2">
            <Skeleton className="h-7 w-10" />
            <Skeleton className="h-3 w-24" />
          </div>
        ))}
      </div>
      {/* Search + filter bar skeleton */}
      <div className="flex items-center gap-3 mb-4">
        <Skeleton className="h-9 flex-1 rounded-lg" />
        <Skeleton className="h-9 w-28 rounded-lg" />
        <Skeleton className="h-9 w-28 rounded-lg" />
      </div>
      {/* Staff table rows skeleton */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        {[...Array(8)].map((_, i) => (
          <div key={i} className="flex items-center gap-4 px-4 py-3 border-b border-gray-100 last:border-0">
            <Skeleton className="h-8 w-8 rounded-full flex-shrink-0" />
            <div className="flex-1 space-y-1.5">
              <Skeleton className="h-3.5 w-36" />
              <Skeleton className="h-3 w-48" />
            </div>
            <Skeleton className="h-5 w-16 rounded-full flex-shrink-0" />
            <Skeleton className="h-3 w-24 flex-shrink-0" />
            <Skeleton className="h-7 w-7 rounded flex-shrink-0" />
          </div>
        ))}
      </div>
    </div>
  );

  return (
    <div className="flex gap-0 min-h-0 flex-1">
      {/* Main content */}
      <div className="flex-1 p-6 overflow-y-auto">
        {/* Stat strip */}
        <div className="grid grid-cols-4 gap-3 mb-5">
          <div className="bg-white border border-gray-200 rounded-lg p-4" style={{ borderLeft: "3px solid #1E3A8A" }} data-testid="people-stat-total">
            <div className="text-2xl font-bold text-gray-900">{stats.total}</div>
            <div className="text-xs text-gray-500 mt-0.5">Total staff</div>
          </div>
          <div className="bg-white border border-gray-200 rounded-lg p-4" data-testid="people-stat-active">
            <div className="text-2xl font-bold" style={{ color: "#059669" }}>{stats.active}</div>
            <div className="text-xs text-gray-500 mt-0.5">Active this month</div>
          </div>
          <div className="bg-white border border-gray-200 rounded-lg p-4" data-testid="people-stat-inactive">
            <div className="text-2xl font-bold" style={{ color: stats.inactive > 0 ? "#D97706" : "#111827" }}>{stats.inactive}</div>
            <div className="text-xs text-gray-500 mt-0.5">No meeting in 30+ days</div>
          </div>
          <div className="bg-white border border-gray-200 rounded-lg p-4" data-testid="people-stat-avg">
            <div className="text-2xl font-bold text-gray-900">{stats.avg}</div>
            <div className="text-xs text-gray-500 mt-0.5">Avg meetings / person</div>
          </div>
        </div>

        {/* Filters */}
        <div className="flex gap-2 mb-4">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search by name or email…"
              className="w-full pl-8 pr-3 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
              data-testid="people-search"
            />
          </div>
          <select value={roleFilter} onChange={e => setRoleFilter(e.target.value)} className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm bg-white focus:outline-none" data-testid="people-role-filter">
            <option value="all">All roles</option>
            <option value="attendee">Staff / Supervisee</option>
            <option value="manager">Manager</option>
            <option value="admin">Admin</option>
          </select>
          <select value={teamFilter} onChange={e => setTeamFilter(e.target.value)} className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm bg-white focus:outline-none" data-testid="people-team-filter">
            <option value="all">All teams</option>
            {teams.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm bg-white focus:outline-none" data-testid="people-status-filter">
            <option value="all">All statuses</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive 30d+</option>
            <option value="pending">Pending invite</option>
          </select>
        </div>

        {/* Table */}
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          <table className="w-full" data-testid="people-table">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="text-left px-4 py-2.5 text-[10px] font-bold uppercase tracking-widest text-gray-400">Name</th>
                <th className="text-left px-3 py-2.5 text-[10px] font-bold uppercase tracking-widest text-gray-400">Role</th>
                <th className="text-left px-3 py-2.5 text-[10px] font-bold uppercase tracking-widest text-gray-400">Team</th>
                <th className="text-right px-3 py-2.5 text-[10px] font-bold uppercase tracking-widest text-gray-400">Meetings</th>
                <th className="text-left px-3 py-2.5 text-[10px] font-bold uppercase tracking-widest text-gray-400">8w Activity</th>
                <th className="text-left px-3 py-2.5 text-[10px] font-bold uppercase tracking-widest text-gray-400">Last active</th>
                <th className="px-3 py-2.5"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr><td colSpan={7} className="text-center py-10 text-sm text-gray-400">No staff match your filters</td></tr>
              ) : filtered.map(p => {
                const inactive = isInactive(p);
                const lastStr = p.pending_invite ? "—" : (daysSince(p.last_meeting_date) || "No meetings");
                const lastColor = p.pending_invite ? "#9CA3AF" : inactive ? "#DC2626" : "#059669";
                const ROLE_LABEL = { admin: "Admin", manager: "Manager", attendee: "Care Worker" };
                const ROLE_STYLE = { admin: "bg-purple-100 text-purple-700", manager: "bg-blue-100 text-blue-700", attendee: "bg-gray-100 text-gray-600" };
                return (
                  <tr key={p.user_id} className={`border-b border-gray-50 hover:bg-gray-50 transition-colors ${inactive && !p.pending_invite ? "bg-red-50/30" : ""}`} data-testid={`people-row-${p.user_id}`}>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2.5">
                        <div className="w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold flex-shrink-0" style={{ background: p.pending_invite ? "#9CA3AF" : avatarColor(p.name) }}>
                          {initials(p.name)}
                        </div>
                        <div>
                          <div className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
                            {p.name}
                            {p.pending_invite && <span className="text-[10px] font-semibold bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded-full">Invite pending</span>}
                          </div>
                          <div className="text-xs text-gray-400">{p.email}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${ROLE_STYLE[p.role] || "bg-gray-100 text-gray-600"}`}>
                        {ROLE_LABEL[p.role] || p.role}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-xs text-gray-500">{p.team_name || <span className="text-gray-300">—</span>}</td>
                    <td className="px-3 py-3 text-right">
                      <span className="text-sm font-semibold text-gray-900">{p.meeting_count}</span>
                    </td>
                    <td className="px-3 py-3">
                      <Sparkbar data={p.weekly_activity} />
                    </td>
                    <td className="px-3 py-3">
                      <span className="text-xs font-semibold" style={{ color: lastColor }}>{lastStr}</span>
                    </td>
                    <td className="px-3 py-3 text-right">
                      <button
                        className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
                        onClick={() => onEdit(p)}
                        data-testid={`people-menu-${p.user_id}`}
                        title="Edit user"
                      >
                        <MoreHorizontal className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ── Invites tab ───────────────────────────────────────────────────────────────
function InvitesTab({ people, onRevoke }) {
  const pending = people.filter(p => p.pending_invite);
  return (
    <div className="p-6">
      <p className="text-xs text-gray-500 mb-4">
        Pending invites are staff who have been invited but haven't yet set their password and logged in.
      </p>
      {pending.length === 0 ? (
        <div className="text-center py-16">
          <Check className="w-10 h-10 mx-auto mb-3 text-emerald-400" />
          <p className="text-sm font-medium text-gray-600">All invites accepted</p>
          <p className="text-xs text-gray-400 mt-1">No pending invites — everyone is onboarded</p>
        </div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="text-left px-4 py-2.5 text-[10px] font-bold uppercase tracking-widest text-gray-400">Name</th>
                <th className="text-left px-4 py-2.5 text-[10px] font-bold uppercase tracking-widest text-gray-400">Email</th>
                <th className="text-left px-4 py-2.5 text-[10px] font-bold uppercase tracking-widest text-gray-400">Role</th>
                <th className="text-left px-4 py-2.5 text-[10px] font-bold uppercase tracking-widest text-gray-400">Invited</th>
                <th className="text-left px-4 py-2.5 text-[10px] font-bold uppercase tracking-widest text-gray-400">Status</th>
                <th className="px-4 py-2.5"></th>
              </tr>
            </thead>
            <tbody>
              {pending.map(p => {
                const days = Math.floor((Date.now() - new Date(p.created_at)) / 86400000);
                const expired = days > 7;
                return (
                  <tr key={p.user_id} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2.5">
                        <div className="w-7 h-7 rounded-full bg-gray-200 flex items-center justify-center text-gray-500 text-xs font-bold">{initials(p.name)}</div>
                        <span className="text-sm font-semibold text-gray-900">{p.name}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500">{p.email}</td>
                    <td className="px-4 py-3"><span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full font-semibold">{p.role === "manager" ? "Manager" : "Care Worker"}</span></td>
                    <td className="px-4 py-3 text-xs text-gray-500">{p.created_at}</td>
                    <td className="px-4 py-3">
                      {expired
                        ? <span className="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-semibold">Expired</span>
                        : <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full font-semibold">Pending</span>
                      }
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-1.5 justify-end">
                        <button
                          className="text-xs font-medium border border-gray-200 bg-white rounded px-2.5 py-1 hover:bg-gray-50"
                          onClick={() => alert(`Send ${p.name} their login link:\n${window.location.origin}/login\n\nEmail: ${p.email}`)}
                          data-testid={`invites-resend-${p.user_id}`}
                        >Resend</button>
                        <button
                          className="text-xs font-medium border border-red-200 bg-red-50 text-red-600 rounded px-2.5 py-1 hover:bg-red-100"
                          onClick={() => onRevoke(p)}
                          data-testid={`invites-revoke-${p.user_id}`}
                        >Revoke</button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Main PeopleHub page ───────────────────────────────────────────────────────
export default function PeopleHub() {
  const { getAuthConfig, API, user: currentUser } = useAuth();
  const [tab, setTab]         = useState("people");
  const [people, setPeople]   = useState([]);
  const [loading, setLoading] = useState(true);
  const [editingUser, setEditingUser] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await cachedGet(`${API}/admin/people-stats`, getAuthConfig());
      setPeople(data);
    } catch (err) {
      console.error("People stats error", err.message);
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API]);

  useEffect(() => { load(); }, [load]);

  const handleRefresh = useCallback(() => {
    invalidateCache("/admin/people-stats");
    load();
  }, [load]);

  const revokeInvite = useCallback(async (person) => {
    if (!window.confirm(`Revoke invite for ${person.name}? This will remove their account.`)) return;
    try {
      await axios.delete(`${API}/admin/users/${person.user_id}`, getAuthConfig());
      invalidateCache("/admin/users", "/org/structure", "/admin/people-stats");
      setPeople(prev => prev.filter(p => p.user_id !== person.user_id));
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to revoke invite");
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API]);

  const handleUserSaved = useCallback(() => {
    setEditingUser(null);
    load();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load]);

  const pendingCount = people.filter(p => p.pending_invite).length;

  const TABS = [
    { key: "people",    label: "People & Usage", icon: Users },
    { key: "structure", label: "Structure",      icon: Building2 },
    { key: "invites",   label: "Invites",        icon: Mail,    badge: pendingCount },
    { key: "settings",  label: "Settings",       icon: Settings },
  ];

  return (
    <Layout>
      <div className="flex flex-col h-full">
        {/* Header */}
        <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between sticky top-0 z-20">
          <div>
            <h1 className="text-base font-semibold text-gray-900 font-display">Organisation</h1>
            {!loading && (
              <p className="text-xs text-gray-500 mt-0.5">
                {people.filter(p => !p.pending_invite).length} active staff members
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleRefresh}
              disabled={loading}
              className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 px-3 py-1.5 rounded border border-gray-200 hover:bg-gray-50 disabled:opacity-50"
              data-testid="people-refresh"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>
        </div>

        {/* Tab bar */}
        <div className="bg-white border-b border-gray-100 px-6">
          <div className="flex overflow-x-auto" style={{ scrollbarWidth: "none" }}>
            {TABS.map(({ key, label, icon: Icon, badge }) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap flex-shrink-0 ${
                  tab === key ? "border-[#1E3A8A] text-[#1E3A8A]" : "border-transparent text-gray-500 hover:text-gray-700"
                }`}
                data-testid={`people-tab-${key}`}
              >
                <Icon className="w-4 h-4" />
                {label}
                {badge > 0 && (
                  <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full text-white bg-amber-500">{badge}</span>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Tab content */}
        <div className="flex-1 overflow-hidden flex flex-col">
          {tab === "people" && (
            <PeopleTab people={people} loading={loading} onRefresh={handleRefresh} onRevoke={revokeInvite} onEdit={setEditingUser} />
          )}
          {tab === "structure" && (
            <div className="overflow-y-auto flex-1">
              <OrgStructure embedded />
            </div>
          )}
          {tab === "invites" && (
            <div className="overflow-y-auto flex-1">
              <InvitesTab people={people} onRevoke={revokeInvite} />
            </div>
          )}
          {tab === "settings" && (
            <div className="overflow-y-auto flex-1">
              <OrgSettings embedded />
            </div>
          )}
        </div>
      </div>

      {/* Edit User Modal */}
      {editingUser && (
        <EditUserModal
          person={editingUser}
          onClose={() => setEditingUser(null)}
          onSaved={handleUserSaved}
          API={API}
          getAuthConfig={getAuthConfig}
          currentUserRole={currentUser?.role}
        />
      )}
    </Layout>
  );
}

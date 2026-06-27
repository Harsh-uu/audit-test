import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import { Building2, Users, FileText, Plus, X, ChevronRight, AlertCircle, CheckCircle, Loader2 } from "lucide-react";

const API = process.env.REACT_APP_BACKEND_URL + "/api";

const ROLE_OPTIONS = ["manager", "admin", "attendee", "shared_reviewer"];
const ROLE_LABELS = { manager: "Manager", admin: "Admin", attendee: "Staff", shared_reviewer: "Shared Reviewer" };

function StatusBadge({ status }) {
  const isActive = status === "active";
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${
      isActive ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-600"
    }`}>
      {isActive ? <CheckCircle className="w-3 h-3" /> : <AlertCircle className="w-3 h-3" />}
      {isActive ? "Active" : "Suspended"}
    </span>
  );
}

function RoleBadge({ role }) {
  const colours = {
    admin: "bg-purple-100 text-purple-700",
    manager: "bg-blue-100 text-blue-700",
    attendee: "bg-gray-100 text-gray-600",
    shared_reviewer: "bg-amber-100 text-amber-700",
  };
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${colours[role] || colours.attendee}`}>
      {ROLE_LABELS[role] || role}
    </span>
  );
}

export default function SuperAdminDashboard() {
  const { getAuthConfig } = useAuth();
  const [orgs, setOrgs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedOrg, setSelectedOrg] = useState(null);
  const [orgUsers, setOrgUsers] = useState([]);
  const [usersLoading, setUsersLoading] = useState(false);
  const [showCreateOrg, setShowCreateOrg] = useState(false);
  const [showCreateUser, setShowCreateUser] = useState(false);
  const [orgForm, setOrgForm] = useState({ name: "" });
  const [userForm, setUserForm] = useState({ name: "", email: "", password: "", role: "manager" });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const loadOrgs = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await axios.get(`${API}/super-admin/orgs`, getAuthConfig());
      setOrgs(data);
    } catch {
      setError("Failed to load organisations");
    } finally {
      setLoading(false);
    }
  }, [getAuthConfig]);

  useEffect(() => { loadOrgs(); }, [loadOrgs]);

  const loadOrgUsers = async (org) => {
    setSelectedOrg(org);
    setOrgUsers([]);
    setUsersLoading(true);
    try {
      const { data } = await axios.get(`${API}/super-admin/orgs/${org.id}/users`, getAuthConfig());
      setOrgUsers(data);
    } catch {
      setOrgUsers([]);
    } finally {
      setUsersLoading(false);
    }
  };

  const handleCreateOrg = async (e) => {
    e.preventDefault();
    if (!orgForm.name.trim()) return;
    setSubmitting(true);
    setError("");
    try {
      await axios.post(`${API}/super-admin/orgs`, { name: orgForm.name.trim() }, getAuthConfig());
      setOrgForm({ name: "" });
      setShowCreateOrg(false);
      await loadOrgs();
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to create organisation");
    } finally {
      setSubmitting(false);
    }
  };

  const handleCreateUser = async (e) => {
    e.preventDefault();
    if (!userForm.name.trim() || !userForm.email.trim() || !userForm.password) return;
    setSubmitting(true);
    setError("");
    try {
      await axios.post(`${API}/super-admin/orgs/${selectedOrg.id}/users`, userForm, getAuthConfig());
      setUserForm({ name: "", email: "", password: "", role: "manager" });
      setShowCreateUser(false);
      await loadOrgUsers(selectedOrg);
      // Refresh org stats
      await loadOrgs();
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to create user");
    } finally {
      setSubmitting(false);
    }
  };

  const toggleOrgStatus = async (org) => {
    const newStatus = org.status === "active" ? "suspended" : "active";
    try {
      await axios.patch(`${API}/super-admin/orgs/${org.id}`, { status: newStatus }, getAuthConfig());
      if (selectedOrg?.id === org.id) setSelectedOrg({ ...selectedOrg, status: newStatus });
      await loadOrgs();
    } catch {
      setError("Failed to update status");
    }
  };

  return (
    <Layout>
    <div className="min-h-screen bg-[#F8F9FA] p-6 lg:p-8">
      {/* Page Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold font-display text-[#1E3A8A]">Organisations</h1>
          <p className="text-sm text-gray-500 mt-0.5">{orgs.length} organisation{orgs.length !== 1 ? "s" : ""} registered</p>
        </div>
        <button
          data-testid="create-org-btn"
          onClick={() => { setShowCreateOrg(true); setError(""); }}
          className="flex items-center gap-2 bg-[#1E3A8A] text-white px-4 py-2 rounded-lg text-sm font-semibold hover:bg-[#1e40af] transition-colors"
        >
          <Plus className="w-4 h-4" />
          New Organisation
        </button>
      </div>

      {/* Global error */}
      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          {error}
          <button onClick={() => setError("")} className="ml-auto"><X className="w-4 h-4" /></button>
        </div>
      )}

      {/* Orgs Grid */}
      {loading ? (
        <div className="flex items-center justify-center py-20 text-gray-400 gap-3">
          <Loader2 className="w-5 h-5 animate-spin" />
          <span className="text-sm">Loading organisations...</span>
        </div>
      ) : orgs.length === 0 ? (
        <div className="text-center py-20">
          <Building2 className="w-12 h-12 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-500 font-medium">No organisations yet</p>
          <p className="text-sm text-gray-400 mt-1">Create your first organisation to get started</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {orgs.map(org => (
            <div
              key={org.id}
              data-testid={`org-card-${org.id}`}
              className="bg-white rounded-xl border border-gray-200 p-5 hover:border-[#1E3A8A]/30 hover:shadow-md transition-all"
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex-1 min-w-0 mr-2">
                  <h3 className="font-semibold text-gray-900 truncate font-display">{org.name}</h3>
                  <p className="text-xs text-gray-400 mt-0.5 truncate">{org.slug}</p>
                </div>
                <StatusBadge status={org.status} />
              </div>

              <div className="flex gap-4 mb-4">
                <div className="flex items-center gap-1.5 text-gray-500">
                  <Users className="w-3.5 h-3.5" />
                  <span className="text-sm">{org.user_count} user{org.user_count !== 1 ? "s" : ""}</span>
                </div>
                <div className="flex items-center gap-1.5 text-gray-500">
                  <FileText className="w-3.5 h-3.5" />
                  <span className="text-sm">{org.meeting_count} meeting{org.meeting_count !== 1 ? "s" : ""}</span>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  data-testid={`manage-org-${org.id}`}
                  onClick={() => loadOrgUsers(org)}
                  className="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#1E3A8A] text-white text-xs font-semibold hover:bg-[#1e40af] transition-colors"
                >
                  Manage
                  <ChevronRight className="w-3.5 h-3.5" />
                </button>
                <button
                  data-testid={`toggle-status-${org.id}`}
                  onClick={() => toggleOrgStatus(org)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${
                    org.status === "active"
                      ? "border-red-200 text-red-600 hover:bg-red-50"
                      : "border-emerald-200 text-emerald-600 hover:bg-emerald-50"
                  }`}
                >
                  {org.status === "active" ? "Suspend" : "Activate"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Org Detail Slide-Over ──────────────────────────────────────── */}
      {selectedOrg && (
        <>
          <div className="fixed inset-0 bg-black/30 z-40" onClick={() => setSelectedOrg(null)} />
          <div className="fixed right-0 top-0 h-full w-full max-w-md bg-white shadow-2xl z-50 flex flex-col">
            <div className="flex items-center justify-between p-5 border-b border-gray-200">
              <div>
                <h2 className="font-bold font-display text-[#1E3A8A] text-lg">{selectedOrg.name}</h2>
                <StatusBadge status={selectedOrg.status} />
              </div>
              <button onClick={() => setSelectedOrg(null)} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-5">
              {/* Stats */}
              <div className="grid grid-cols-2 gap-3 mb-5">
                <div className="bg-[#F8F9FA] rounded-lg p-3 text-center">
                  <p className="text-2xl font-bold text-[#1E3A8A] font-display">{selectedOrg.user_count}</p>
                  <p className="text-xs text-gray-500">Users</p>
                </div>
                <div className="bg-[#F8F9FA] rounded-lg p-3 text-center">
                  <p className="text-2xl font-bold text-[#1E3A8A] font-display">{selectedOrg.meeting_count}</p>
                  <p className="text-xs text-gray-500">Meetings</p>
                </div>
              </div>

              {/* Users */}
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-gray-700">Users</h3>
                <button
                  data-testid="add-user-btn"
                  onClick={() => { setShowCreateUser(true); setError(""); }}
                  className="flex items-center gap-1.5 text-xs text-[#1E3A8A] font-semibold hover:underline"
                >
                  <Plus className="w-3.5 h-3.5" />
                  Add User
                </button>
              </div>

              {usersLoading ? (
                <div className="flex items-center gap-2 text-gray-400 text-sm py-4">
                  <Loader2 className="w-4 h-4 animate-spin" /> Loading users...
                </div>
              ) : orgUsers.length === 0 ? (
                <p className="text-sm text-gray-400 py-4 text-center">No users in this organisation</p>
              ) : (
                <div className="space-y-2">
                  {orgUsers.map(u => (
                    <div key={u.id} className="flex items-center gap-3 p-3 bg-[#F8F9FA] rounded-lg">
                      <div className="w-8 h-8 rounded-full bg-[#1E3A8A]/10 flex items-center justify-center flex-shrink-0">
                        <span className="text-xs font-bold text-[#1E3A8A]">
                          {u.name?.charAt(0)?.toUpperCase()}
                        </span>
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-900 truncate">{u.name}</p>
                        <p className="text-xs text-gray-400 truncate">{u.email}</p>
                      </div>
                      <RoleBadge role={u.role} />
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {/* ── Create Organisation Modal ──────────────────────────────────── */}
      {showCreateOrg && (
        <>
          <div className="fixed inset-0 bg-black/40 z-50" onClick={() => setShowCreateOrg(false)} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6">
              <div className="flex items-center justify-between mb-5">
                <h2 className="font-bold font-display text-[#1E3A8A] text-lg">New Organisation</h2>
                <button onClick={() => setShowCreateOrg(false)} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500">
                  <X className="w-5 h-5" />
                </button>
              </div>
              {error && (
                <p className="mb-3 text-sm text-red-600 bg-red-50 p-2 rounded">{error}</p>
              )}
              <form onSubmit={handleCreateOrg} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Organisation Name</label>
                  <input
                    data-testid="org-name-input"
                    type="text"
                    required
                    autoFocus
                    value={orgForm.name}
                    onChange={e => setOrgForm({ name: e.target.value })}
                    placeholder="e.g. Sunrise Care Ltd"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/30 focus:border-[#1E3A8A]"
                  />
                </div>
                <div className="flex gap-2 pt-1">
                  <button
                    type="button"
                    onClick={() => setShowCreateOrg(false)}
                    className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-50"
                  >
                    Cancel
                  </button>
                  <button
                    data-testid="create-org-submit"
                    type="submit"
                    disabled={submitting || !orgForm.name.trim()}
                    className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-[#1E3A8A] text-white rounded-lg text-sm font-semibold hover:bg-[#1e40af] disabled:opacity-50"
                  >
                    {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                    Create
                  </button>
                </div>
              </form>
            </div>
          </div>
        </>
      )}

      {/* ── Create User Modal ─────────────────────────────────────────── */}
      {showCreateUser && selectedOrg && (
        <>
          <div className="fixed inset-0 bg-black/40 z-50" onClick={() => setShowCreateUser(false)} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6">
              <div className="flex items-center justify-between mb-1">
                <h2 className="font-bold font-display text-[#1E3A8A] text-lg">Add User</h2>
                <button onClick={() => setShowCreateUser(false)} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500">
                  <X className="w-5 h-5" />
                </button>
              </div>
              <p className="text-xs text-gray-400 mb-5">Adding to: <span className="font-medium text-gray-600">{selectedOrg.name}</span></p>
              {error && (
                <p className="mb-3 text-sm text-red-600 bg-red-50 p-2 rounded">{error}</p>
              )}
              <form onSubmit={handleCreateUser} className="space-y-3">
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Full Name</label>
                  <input
                    data-testid="user-name-input"
                    type="text"
                    required
                    autoFocus
                    value={userForm.name}
                    onChange={e => setUserForm(f => ({ ...f, name: e.target.value }))}
                    placeholder="Jane Smith"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/30 focus:border-[#1E3A8A]"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Email</label>
                  <input
                    data-testid="user-email-input"
                    type="email"
                    required
                    value={userForm.email}
                    onChange={e => setUserForm(f => ({ ...f, email: e.target.value }))}
                    placeholder="jane@example.com"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/30 focus:border-[#1E3A8A]"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Password</label>
                  <input
                    data-testid="user-password-input"
                    type="password"
                    required
                    value={userForm.password}
                    onChange={e => setUserForm(f => ({ ...f, password: e.target.value }))}
                    placeholder="Min. 8 characters"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/30 focus:border-[#1E3A8A]"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Role</label>
                  <select
                    data-testid="user-role-select"
                    value={userForm.role}
                    onChange={e => setUserForm(f => ({ ...f, role: e.target.value }))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/30 focus:border-[#1E3A8A] bg-white"
                  >
                    {ROLE_OPTIONS.map(r => (
                      <option key={r} value={r}>{ROLE_LABELS[r]}</option>
                    ))}
                  </select>
                </div>
                <div className="flex gap-2 pt-1">
                  <button
                    type="button"
                    onClick={() => setShowCreateUser(false)}
                    className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-50"
                  >
                    Cancel
                  </button>
                  <button
                    data-testid="create-user-submit"
                    type="submit"
                    disabled={submitting || !userForm.name.trim() || !userForm.email.trim() || !userForm.password}
                    className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-[#1E3A8A] text-white rounded-lg text-sm font-semibold hover:bg-[#1e40af] disabled:opacity-50"
                  >
                    {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                    Add User
                  </button>
                </div>
              </form>
            </div>
          </div>
        </>
      )}
    </div>
    </Layout>
  );
}

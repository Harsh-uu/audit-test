import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { Building2, Users, FileText, Plus, X, ChevronRight, AlertCircle, CheckCircle, Loader2, Mail, Copy, Pencil, Trash2, Check, HelpCircle } from "lucide-react";

const ROLE_DESCRIPTIONS = {
  manager:         "Creates meetings, signs off supervision records, views all staff in their team scope.",
  admin:           "Full org access — manage users, standards library, exports, and org settings.",
  attendee:        "Records meetings and marks their own copy as reviewed.",
  shared_reviewer: "View-only access to meetings explicitly shared with them. Cannot edit or sign off.",
};

function RoleInfoTooltip() {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <HelpCircle className="w-3.5 h-3.5 text-gray-400 hover:text-gray-600 cursor-help inline-block ml-1 align-middle" />
      </TooltipTrigger>
      <TooltipContent side="right" className="max-w-xs text-left">
        <p className="font-semibold mb-1.5">Role permissions:</p>
        <ul className="space-y-1.5 text-xs">
          {Object.entries(ROLE_DESCRIPTIONS).map(([role, desc]) => (
            <li key={role}><span className="font-medium">{ROLE_LABELS[role] || role}</span> — {desc}</li>
          ))}
        </ul>
      </TooltipContent>
    </Tooltip>
  );
}

const API = "/api";

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
  const [editingUserId, setEditingUserId] = useState(null);
  const [editUserForm, setEditUserForm] = useState({ name: "", email: "", role: "", password: "" });
  const [showEditOrg, setShowEditOrg] = useState(false);
  const [editOrgForm, setEditOrgForm] = useState({ name: "", jurisdiction: "england", service_type: "domiciliary" });
  const [showInviteAdmin, setShowInviteAdmin] = useState(false);
  const [orgForm, setOrgForm] = useState({ name: "", jurisdiction: "england", service_type: "domiciliary" });
  const [userForm, setUserForm] = useState({ name: "", email: "", password: "", role: "manager" });
  const [inviteForm, setInviteForm] = useState({ name: "", email: "" });
  const [inviteResult, setInviteResult] = useState(null); // { message, invite_link?, email_failed? }
  const [userToDelete, setUserToDelete] = useState(null); // user object pending deletion
  const [deleting, setDeleting] = useState(false);
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
      const payload = { name: orgForm.name.trim(), jurisdiction: orgForm.jurisdiction };
      if (orgForm.jurisdiction === "northern_ireland") {
        payload.service_type = ["residential", "domiciliary"].includes(orgForm.service_type) ? orgForm.service_type : "domiciliary";
      } else if (orgForm.jurisdiction === "ofsted") {
        payload.service_type = ["early_years", "childrens_home", "school"].includes(orgForm.service_type) ? orgForm.service_type : "early_years";
      }
      await axios.post(`${API}/super-admin/orgs`, payload, getAuthConfig());
      setOrgForm({ name: "", jurisdiction: "england", service_type: "domiciliary" });
      setShowCreateOrg(false);
      await loadOrgs();
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to create organisation");
    } finally {
      setSubmitting(false);
    }
  };

  const openEditOrg = (org) => {
    setEditOrgForm({
      name: org.name,
      jurisdiction: org.jurisdiction || "england",
      service_type: org.service_type || (org.jurisdiction === "ofsted" ? "early_years" : "domiciliary"),
    });
    setShowEditOrg(org);
    setError("");
  };

  const handleEditOrg = async (e) => {
    e.preventDefault();
    if (!editOrgForm.name.trim() || !showEditOrg) return;
    setSubmitting(true);
    setError("");
    try {
      const payload = { name: editOrgForm.name.trim(), jurisdiction: editOrgForm.jurisdiction };
      if (editOrgForm.jurisdiction === "northern_ireland") {
        payload.service_type = ["residential", "domiciliary"].includes(editOrgForm.service_type) ? editOrgForm.service_type : "domiciliary";
      } else if (editOrgForm.jurisdiction === "ofsted") {
        payload.service_type = ["early_years", "childrens_home", "school"].includes(editOrgForm.service_type) ? editOrgForm.service_type : "early_years";
      } else {
        payload.service_type = "";  // clear service_type when not NI/Ofsted
      }
      await axios.patch(`${API}/super-admin/orgs/${showEditOrg.id}`, payload, getAuthConfig());
      toast.success("Organisation updated");
      setShowEditOrg(false);
      await loadOrgs();
      // Refresh slide-over if it's the currently selected org
      if (selectedOrg?.id === showEditOrg.id) {
        setSelectedOrg(prev => ({ ...prev, ...payload, service_type: payload.service_type || null }));
      }
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to update organisation");
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

  const handleUpdateUser = async (userId) => {
    setSubmitting(true); setError("");
    try {
      const payload = {};
      if (editUserForm.name.trim()) payload.name = editUserForm.name.trim();
      if (editUserForm.email.trim()) payload.email = editUserForm.email.trim();
      if (editUserForm.role) payload.role = editUserForm.role;
      if (editUserForm.password) payload.password = editUserForm.password;
      await axios.patch(`${API}/super-admin/orgs/${selectedOrg.id}/users/${userId}`, payload, getAuthConfig());
      setEditingUserId(null);
      await loadOrgUsers(selectedOrg);
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to update user");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteUser = async () => {
    if (!userToDelete) return;
    setDeleting(true);
    try {
      const { data } = await axios.delete(
        `${API}/super-admin/orgs/${selectedOrg.id}/users/${userToDelete.id}`,
        getAuthConfig()
      );
      toast.success(data.message || "User deleted successfully");
      setUserToDelete(null);
      await loadOrgUsers(selectedOrg);
      await loadOrgs(); // refresh user count on org cards
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to delete user");
      setUserToDelete(null);
    } finally {
      setDeleting(false);
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

  const handleInviteAdmin = async (e) => {
    e.preventDefault();
    if (!inviteForm.name.trim() || !inviteForm.email.trim()) return;
    setSubmitting(true);
    setError("");
    try {
      const { data } = await axios.post(
        `${API}/super-admin/orgs/${selectedOrg.id}/invite`,
        inviteForm,
        getAuthConfig()
      );
      setInviteResult(data);
      setInviteForm({ name: "", email: "" });
      await loadOrgs();
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to send invitation");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Layout>
    <div className="min-h-full bg-[#F8F9FA] p-6 lg:p-8">
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
                <div className="flex items-center gap-2">
                  {org.jurisdiction && org.jurisdiction !== "england" && (
                    <span
                      data-testid={`org-jurisdiction-badge-${org.id}`}
                      className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                        org.jurisdiction === "wales"
                          ? "bg-green-100 text-green-700"
                          : org.jurisdiction === "scotland"
                          ? "bg-purple-100 text-purple-700"
                          : org.jurisdiction === "ofsted"
                          ? "bg-pink-100 text-pink-700"
                          : "bg-orange-100 text-orange-700"
                      }`}
                    >
                      {org.jurisdiction === "wales" ? "Wales"
                        : org.jurisdiction === "scotland" ? "Scotland"
                        : org.jurisdiction === "northern_ireland"
                          ? `N. Ireland${org.service_type ? ` · ${org.service_type === "domiciliary" ? "Dom" : "Res"}` : ""}`
                          : org.jurisdiction === "ofsted"
                          ? `Ofsted${org.service_type ? ` · ${{ early_years: "Early Years", childrens_home: "Children's Home", school: "School" }[org.service_type] || org.service_type}` : ""}`
                          : org.jurisdiction}
                    </span>
                  )}
                  <StatusBadge status={org.status} />
                </div>
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
                  data-testid={`edit-org-${org.id}`}
                  onClick={() => openEditOrg(org)}
                  className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-gray-200 text-gray-600 hover:bg-gray-50 transition-colors"
                  title="Edit organisation"
                >
                  <Pencil className="w-3.5 h-3.5" />
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
                <div className="flex items-center gap-2">
                  <button
                    data-testid="invite-admin-btn"
                    onClick={() => { setShowInviteAdmin(true); setInviteResult(null); setError(""); }}
                    className="flex items-center gap-1.5 text-xs text-emerald-700 font-semibold hover:underline"
                  >
                    <Mail className="w-3.5 h-3.5" />
                    Invite Admin
                  </button>
                  <span className="text-gray-200 text-xs">|</span>
                  <button
                    data-testid="add-user-btn"
                    onClick={() => { setShowCreateUser(true); setError(""); }}
                    className="flex items-center gap-1.5 text-xs text-[#1E3A8A] font-semibold hover:underline"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    Add User
                  </button>
                </div>
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
                    <div key={u.id} className="border border-gray-100 rounded-lg bg-[#F8F9FA] overflow-hidden">
                      {/* View row */}
                      {editingUserId !== u.id ? (
                        <div className="flex items-center gap-3 p-3">
                          <div className="w-8 h-8 rounded-full bg-[#1E3A8A]/10 flex items-center justify-center flex-shrink-0">
                            <span className="text-xs font-bold text-[#1E3A8A]">{u.name?.charAt(0)?.toUpperCase()}</span>
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-gray-900 truncate">{u.name}</p>
                            <p className="text-xs text-gray-400 truncate">{u.email}</p>
                          </div>
                          <RoleBadge role={u.role} />
                          <button
                            onClick={() => { setEditingUserId(u.id); setEditUserForm({ name: u.name, email: u.email, role: u.role, password: "" }); setError(""); }}
                            className="p-1.5 rounded hover:bg-gray-200 text-gray-400 hover:text-gray-600 transition-colors flex-shrink-0"
                            title="Edit user"
                            data-testid={`edit-user-btn-${u.id}`}
                          >
                            <Pencil className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => setUserToDelete(u)}
                            className="p-1.5 rounded hover:bg-red-100 text-gray-400 hover:text-red-600 transition-colors flex-shrink-0"
                            title="Delete user"
                            data-testid={`delete-user-btn-${u.id}`}
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      ) : (
                        /* Edit row */
                        <div className="p-3 space-y-2">
                          <div className="grid grid-cols-2 gap-2">
                            <input
                              type="text"
                              value={editUserForm.name}
                              onChange={e => setEditUserForm(f => ({ ...f, name: e.target.value }))}
                              placeholder="Full name"
                              className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
                              data-testid="edit-user-name"
                            />
                            <input
                              type="email"
                              value={editUserForm.email}
                              onChange={e => setEditUserForm(f => ({ ...f, email: e.target.value }))}
                              placeholder="Email"
                              className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
                              data-testid="edit-user-email"
                            />
                            <select
                              value={editUserForm.role}
                              onChange={e => setEditUserForm(f => ({ ...f, role: e.target.value }))}
                              className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
                              data-testid="edit-user-role"
                            >
                              <option value="admin">Admin</option>
                              <option value="manager">Manager</option>
                              <option value="attendee">Attendee</option>
                              <option value="shared_reviewer">Shared Reviewer</option>
                            </select>
                            <input
                              type="password"
                              value={editUserForm.password}
                              onChange={e => setEditUserForm(f => ({ ...f, password: e.target.value }))}
                              placeholder="New password (optional)"
                              className="border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
                              data-testid="edit-user-password"
                            />
                          </div>
                          {error && <p className="text-xs text-red-600">{error}</p>}
                          <div className="flex gap-2 pt-1">
                            <button
                              onClick={() => handleUpdateUser(u.id)}
                              disabled={submitting}
                              className="flex items-center gap-1 bg-[#1E3A8A] text-white px-3 py-1.5 rounded text-xs font-medium hover:bg-[#1E40AF] disabled:opacity-60 transition-colors"
                              data-testid="save-user-btn"
                            >
                              <Check className="w-3 h-3" /> Save
                            </button>
                            <button
                              onClick={() => { setEditingUserId(null); setError(""); }}
                              className="px-3 py-1.5 rounded text-xs font-medium border border-gray-300 text-gray-600 hover:bg-gray-50 transition-colors"
                              data-testid="cancel-edit-user-btn"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      )}
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
                  <label htmlFor="create-org-name" className="block text-sm font-medium text-gray-700 mb-1">Organisation Name</label>
                  <input
                    id="create-org-name"
                    name="org_name"
                    data-testid="org-name-input"
                    type="text"
                    required
                    autoFocus
                    value={orgForm.name}
                    onChange={e => setOrgForm(f => ({ ...f, name: e.target.value }))}
                    placeholder="e.g. Sunrise Care Ltd"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/30 focus:border-[#1E3A8A]"
                  />
                </div>
                <div>
                  <label htmlFor="create-org-jurisdiction" className="block text-sm font-medium text-gray-700 mb-1">Jurisdiction</label>
                  <select
                    id="create-org-jurisdiction"
                    name="jurisdiction"
                    data-testid="org-jurisdiction-select"
                    value={orgForm.jurisdiction}
                    onChange={e => setOrgForm(f => ({ ...f, jurisdiction: e.target.value }))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/30 focus:border-[#1E3A8A] bg-white"
                  >
                    <option value="england">England (CQC / Care Certificate)</option>
                    <option value="wales">Wales (CIW / AWIF / SCW)</option>
                    <option value="scotland">Scotland (Care Inspectorate)</option>
                    <option value="northern_ireland">Northern Ireland (RQIA / NISCC)</option>
                    <option value="ofsted">Ofsted (Schools / Early Years / Children's Homes)</option>
                  </select>
                  <p className="mt-1 text-xs text-gray-500">
                    Sets which regulatory framework is used for evidence mapping and compliance reporting.
                  </p>
                </div>
                {orgForm.jurisdiction === "northern_ireland" && (
                  <div>
                    <label htmlFor="create-org-service-type" className="block text-sm font-medium text-gray-700 mb-1">Service Type</label>
                    <select
                      id="create-org-service-type"
                      name="service_type"
                      data-testid="org-service-type-select"
                      value={orgForm.service_type}
                      onChange={e => setOrgForm(f => ({ ...f, service_type: e.target.value }))}
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/30 focus:border-[#1E3A8A] bg-white"
                    >
                      <option value="domiciliary">Domiciliary Care (RQIA Dom Standards 2021)</option>
                      <option value="residential">Residential Care (RQIA Regulations 2005)</option>
                    </select>
                    <p className="mt-1 text-xs text-gray-500">
                      Determines whether RQIA domiciliary or residential regulations are applied. NISCC Code and Induction are shown for both.
                    </p>
                  </div>
                )}
                {orgForm.jurisdiction === "ofsted" && (
                  <div>
                    <label htmlFor="create-org-service-type" className="block text-sm font-medium text-gray-700 mb-1">Setting Type</label>
                    <select
                      id="create-org-service-type"
                      name="service_type"
                      data-testid="org-service-type-select"
                      value={["early_years", "childrens_home", "school"].includes(orgForm.service_type) ? orgForm.service_type : "early_years"}
                      onChange={e => setOrgForm(f => ({ ...f, service_type: e.target.value }))}
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/30 focus:border-[#1E3A8A] bg-white"
                    >
                      <option value="early_years">Early Years (EYFS)</option>
                      <option value="childrens_home">Children's Home (Quality Standards)</option>
                      <option value="school">School (EIF)</option>
                    </select>
                    <p className="mt-1 text-xs text-gray-500">
                      Determines which Ofsted framework is used for evidence mapping and induction tracking.
                    </p>
                  </div>
                )}
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

      {/* ── Edit Organisation Modal ────────────────────────────────────── */}
      {showEditOrg && (
        <>
          <div className="fixed inset-0 bg-black/40 z-50" onClick={() => setShowEditOrg(false)} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6">
              <div className="flex items-center justify-between mb-5">
                <h2 className="font-bold font-display text-[#1E3A8A] text-lg">Edit Organisation</h2>
                <button onClick={() => setShowEditOrg(false)} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500">
                  <X className="w-5 h-5" />
                </button>
              </div>
              {error && <p className="mb-3 text-sm text-red-600 bg-red-50 p-2 rounded">{error}</p>}
              <form onSubmit={handleEditOrg} className="space-y-4">
                <div>
                  <label htmlFor="edit-org-name" className="block text-sm font-medium text-gray-700 mb-1">Organisation Name</label>
                  <input
                    id="edit-org-name"
                    name="org_name"
                    data-testid="edit-org-name-input"
                    type="text"
                    required
                    autoFocus
                    value={editOrgForm.name}
                    onChange={e => setEditOrgForm(f => ({ ...f, name: e.target.value }))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/30 focus:border-[#1E3A8A]"
                  />
                </div>
                <div>
                  <label htmlFor="edit-org-jurisdiction" className="block text-sm font-medium text-gray-700 mb-1">Jurisdiction</label>
                  <select
                    id="edit-org-jurisdiction"
                    name="jurisdiction"
                    data-testid="edit-org-jurisdiction-select"
                    value={editOrgForm.jurisdiction}
                    onChange={e => setEditOrgForm(f => ({ ...f, jurisdiction: e.target.value }))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/30 focus:border-[#1E3A8A] bg-white"
                  >
                    <option value="england">England (CQC / Care Certificate)</option>
                    <option value="wales">Wales (CIW / AWIF / SCW)</option>
                    <option value="scotland">Scotland (Care Inspectorate)</option>
                    <option value="northern_ireland">Northern Ireland (RQIA / NISCC)</option>
                    <option value="ofsted">Ofsted (Schools / Early Years / Children's Homes)</option>
                  </select>
                  <p className="mt-1 text-xs text-gray-500">
                    Changes which regulatory framework is used for all new evidence mappings in this org.
                  </p>
                </div>
                {editOrgForm.jurisdiction === "northern_ireland" && (
                  <div>
                    <label htmlFor="edit-org-service-type" className="block text-sm font-medium text-gray-700 mb-1">Service Type</label>
                    <select
                      id="edit-org-service-type"
                      name="service_type"
                      data-testid="edit-org-service-type-select"
                      value={editOrgForm.service_type}
                      onChange={e => setEditOrgForm(f => ({ ...f, service_type: e.target.value }))}
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/30 focus:border-[#1E3A8A] bg-white"
                    >
                      <option value="domiciliary">Domiciliary Care (RQIA Dom Standards 2021)</option>
                      <option value="residential">Residential Care (RQIA Regulations 2005)</option>
                    </select>
                  </div>
                )}
                {editOrgForm.jurisdiction === "ofsted" && (
                  <div>
                    <label htmlFor="edit-org-service-type" className="block text-sm font-medium text-gray-700 mb-1">Setting Type</label>
                    <select
                      id="edit-org-service-type"
                      name="service_type"
                      data-testid="edit-org-service-type-select"
                      value={["early_years", "childrens_home", "school"].includes(editOrgForm.service_type) ? editOrgForm.service_type : "early_years"}
                      onChange={e => setEditOrgForm(f => ({ ...f, service_type: e.target.value }))}
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/30 focus:border-[#1E3A8A] bg-white"
                    >
                      <option value="early_years">Early Years (EYFS)</option>
                      <option value="childrens_home">Children's Home (Quality Standards)</option>
                      <option value="school">School (EIF)</option>
                    </select>
                  </div>
                )}
                <div className="flex gap-2 pt-1">
                  <button
                    type="button"
                    onClick={() => setShowEditOrg(false)}
                    className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-50"
                  >
                    Cancel
                  </button>
                  <button
                    data-testid="edit-org-submit"
                    type="submit"
                    disabled={submitting || !editOrgForm.name.trim()}
                    className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-[#1E3A8A] text-white rounded-lg text-sm font-semibold hover:bg-[#1e40af] disabled:opacity-50"
                  >
                    {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Pencil className="w-4 h-4" />}
                    Save Changes
                  </button>
                </div>
              </form>
            </div>
          </div>
        </>
      )}

      {/* ── Create User Modal ─────────────────────────────────────────── */}
      {showCreateUser && selectedOrg && (        <>
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
                  <label htmlFor="create-user-name" className="block text-xs font-medium text-gray-700 mb-1">Full Name</label>
                  <input
                    id="create-user-name"
                    name="name"
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
                  <label htmlFor="create-user-email" className="block text-xs font-medium text-gray-700 mb-1">Email</label>
                  <input
                    id="create-user-email"
                    name="email"
                    data-testid="user-email-input"
                    type="email"
                    required
                    autoComplete="email"
                    value={userForm.email}
                    onChange={e => setUserForm(f => ({ ...f, email: e.target.value }))}
                    placeholder="jane@example.com"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/30 focus:border-[#1E3A8A]"
                  />
                </div>
                <div>
                  <label htmlFor="create-user-password" className="block text-xs font-medium text-gray-700 mb-1">Password</label>
                  <input
                    id="create-user-password"
                    name="password"
                    data-testid="user-password-input"
                    type="password"
                    required
                    autoComplete="new-password"
                    value={userForm.password}
                    onChange={e => setUserForm(f => ({ ...f, password: e.target.value }))}
                    placeholder="Min. 8 characters"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/30 focus:border-[#1E3A8A]"
                  />
                </div>
                <div>
                  <label htmlFor="create-user-role" className="block text-xs font-medium text-gray-700 mb-1 flex items-center">Role <RoleInfoTooltip /></label>
                  <select
                    id="create-user-role"
                    name="role"
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

      {/* ── Invite Admin Modal ────────────────────────────────────────── */}
      {showInviteAdmin && selectedOrg && (
        <>
          <div className="fixed inset-0 bg-black/40 z-50" onClick={() => { setShowInviteAdmin(false); setInviteResult(null); }} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6">
              <div className="flex items-center justify-between mb-1">
                <h2 className="font-bold font-display text-[#1E3A8A] text-lg">Invite Admin</h2>
                <button onClick={() => { setShowInviteAdmin(false); setInviteResult(null); }} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500">
                  <X className="w-5 h-5" />
                </button>
              </div>
              <p className="text-xs text-gray-400 mb-5">
                For: <span className="font-medium text-gray-600">{selectedOrg.name}</span>
                <span className="ml-2 text-gray-300">·</span>
                <span className="ml-2">A welcome email with a one-time activation link will be sent</span>
              </p>

              {inviteResult ? (
                <div className="space-y-4">
                  <div className={`flex items-start gap-3 p-4 rounded-lg ${inviteResult.email_failed ? "bg-amber-50 border border-amber-200" : "bg-emerald-50 border border-emerald-200"}`}>
                    {inviteResult.email_failed
                      ? <AlertCircle className="w-5 h-5 text-amber-500 flex-shrink-0 mt-0.5" />
                      : <CheckCircle className="w-5 h-5 text-emerald-600 flex-shrink-0 mt-0.5" />}
                    <div className="flex-1 min-w-0">
                      <p className={`text-sm font-semibold ${inviteResult.email_failed ? "text-amber-700" : "text-emerald-700"}`}>
                        {inviteResult.email_failed ? "User created — email failed to send" : "Invitation sent!"}
                      </p>
                      <p className="text-xs text-gray-500 mt-0.5">{inviteResult.message}</p>
                      {inviteResult.invite_link && (
                        <div className="mt-3">
                          <p className="text-xs font-semibold text-gray-600 mb-1">Share this link manually:</p>
                          <div className="flex items-center gap-2 bg-white border border-gray-200 rounded-lg px-3 py-2">
                            <span className="text-xs text-gray-500 truncate flex-1">{inviteResult.invite_link}</span>
                            <button
                              onClick={() => navigator.clipboard.writeText(inviteResult.invite_link)}
                              className="text-[#1E3A8A] hover:text-[#1e40af] flex-shrink-0"
                              title="Copy link"
                            >
                              <Copy className="w-4 h-4" />
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                  <button
                    onClick={() => { setShowInviteAdmin(false); setInviteResult(null); loadOrgUsers(selectedOrg); }}
                    className="w-full py-2 bg-[#1E3A8A] text-white rounded-lg text-sm font-semibold hover:bg-[#1e40af]"
                  >
                    Done
                  </button>
                </div>
              ) : (
                <form onSubmit={handleInviteAdmin} className="space-y-3">
                  {error && <p className="text-sm text-red-600 bg-red-50 p-2 rounded">{error}</p>}
                  <div>
                    <label htmlFor="invite-admin-name" className="block text-xs font-medium text-gray-700 mb-1">Full Name</label>
                    <input
                      id="invite-admin-name"
                      name="name"
                      data-testid="invite-name-input"
                      type="text"
                      required
                      autoFocus
                      autoComplete="name"
                      value={inviteForm.name}
                      onChange={e => setInviteForm(f => ({ ...f, name: e.target.value }))}
                      placeholder="Jane Smith"
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/30 focus:border-[#1E3A8A]"
                    />
                  </div>
                  <div>
                    <label htmlFor="invite-admin-email" className="block text-xs font-medium text-gray-700 mb-1">Email</label>
                    <input
                      id="invite-admin-email"
                      name="email"
                      data-testid="invite-email-input"
                      type="email"
                      required
                      autoComplete="email"
                      value={inviteForm.email}
                      onChange={e => setInviteForm(f => ({ ...f, email: e.target.value }))}
                      placeholder="admin@organisation.com"
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/30 focus:border-[#1E3A8A]"
                    />
                  </div>
                  <p className="text-xs text-gray-400 flex items-center gap-1.5">
                    <Mail className="w-3.5 h-3.5 flex-shrink-0" />
                    They will receive an email with a link to set their own password
                  </p>
                  <div className="flex gap-2 pt-1">
                    <button type="button" onClick={() => setShowInviteAdmin(false)} className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-50">
                      Cancel
                    </button>
                    <button
                      data-testid="send-invite-submit"
                      type="submit"
                      disabled={submitting || !inviteForm.name.trim() || !inviteForm.email.trim()}
                      className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-emerald-700 text-white rounded-lg text-sm font-semibold hover:bg-emerald-800 disabled:opacity-50"
                    >
                      {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Mail className="w-4 h-4" />}
                      Send Invite
                    </button>
                  </div>
                </form>
              )}
            </div>
          </div>
        </>
      )}
      {/* ── Delete User Confirmation Modal ──────────────────────────── */}
      {userToDelete && (
        <>
          <div className="fixed inset-0 bg-black/50 z-[60]" onClick={() => !deleting && setUserToDelete(null)} />
          <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-sm p-6">
              <div className="flex items-start gap-4 mb-5">
                <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <Trash2 className="w-5 h-5 text-red-600" />
                </div>
                <div>
                  <h3 className="font-bold text-gray-900 text-base">Delete User</h3>
                  <p className="text-sm text-gray-500 mt-1 leading-relaxed">
                    Are you sure you want to delete <strong className="text-gray-800">{userToDelete.name}</strong>?
                    Their schedules and login sessions will also be removed.
                    <span className="block mt-1 text-red-500 font-medium">This cannot be undone.</span>
                  </p>
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => setUserToDelete(null)}
                  disabled={deleting}
                  className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50 transition-colors"
                  data-testid="cancel-delete-user-btn"
                >
                  Cancel
                </button>
                <button
                  onClick={handleDeleteUser}
                  disabled={deleting}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-red-600 text-white rounded-lg text-sm font-semibold hover:bg-red-700 disabled:opacity-60 transition-colors"
                  data-testid="confirm-delete-user-btn"
                >
                  {deleting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                  {deleting ? "Deleting..." : "Delete User"}
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
    </Layout>
  );
}

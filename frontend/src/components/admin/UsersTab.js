import React, { useState } from "react";
import { UserPlus, TrendingUp, Pencil, Check, X, KeyRound, ChevronDown, HelpCircle } from "lucide-react";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";

const ROLE_DESCRIPTIONS = {
  attendee:        "Records meetings and marks their own copy as reviewed.",
  manager:         "Creates meetings, signs off supervision records, views all staff in their team scope.",
  shared_reviewer: "View-only access to meetings explicitly shared with them. Cannot edit or sign off.",
  admin:           "Full org access — manage users, standards library, exports, and org settings.",
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
            <li key={role}><span className="font-medium capitalize">{role === "attendee" ? "Care Worker" : role === "shared_reviewer" ? "Shared Reviewer" : role.charAt(0).toUpperCase() + role.slice(1)}</span> — {desc}</li>
          ))}
        </ul>
      </TooltipContent>
    </Tooltip>
  );
}

const ROLES = [
  { value: "attendee", label: "Care Worker / Attendee" },
  { value: "manager", label: "Manager" },
  { value: "shared_reviewer", label: "Shared Reviewer" },
  { value: "admin", label: "Admin" },
];

export function UsersTab({ users, showNewUser, setShowNewUser, newUser, setNewUser, handleCreateUser, onUpdateUser, onResetPassword, navigate }) {
  const [editingId, setEditingId] = useState(null);
  const [editForm, setEditForm] = useState({});
  const [editError, setEditError] = useState("");
  const [saving, setSaving] = useState(false);
  const [showPwdReset, setShowPwdReset] = useState(false);
  const [newPassword, setNewPassword] = useState("");

  const startEdit = (u) => {
    setEditingId(u.id);
    setEditForm({ name: u.name, email: u.email, role: u.role, is_active: u.is_active });
    setEditError("");
    setShowPwdReset(false);
    setNewPassword("");
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditForm({});
    setEditError("");
    setShowPwdReset(false);
    setNewPassword("");
  };

  const saveEdit = async () => {
    if (!editForm.name?.trim()) return setEditError("Name is required");
    if (!editForm.email?.trim()) return setEditError("Email is required");
    if (showPwdReset && newPassword && newPassword.length < 8) return setEditError("Password must be at least 8 characters");
    setSaving(true);
    setEditError("");
    try {
      await onUpdateUser(editingId, editForm);
      if (showPwdReset && newPassword.trim()) {
        await onResetPassword(editingId, newPassword);
      }
      setEditingId(null);
      setEditForm({});
      setShowPwdReset(false);
      setNewPassword("");
    } catch (err) {
      setEditError(err.message || "Save failed");
    }
    setSaving(false);
  };

  return (
    <div>
      <div className="flex justify-end mb-4">
        <button
          onClick={() => setShowNewUser(true)}
          className="flex items-center gap-2 bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors"
          data-testid="add-user-btn"
        >
          <UserPlus className="w-4 h-4" />
          Add User
        </button>
      </div>

      {showNewUser && (
        <div className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm mb-4">
          <h4 className="font-medium text-gray-900 mb-4">New User</h4>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label htmlFor="new-user-name" className="block text-xs font-medium text-gray-600 mb-1">Full name</label>
              <input id="new-user-name" name="name" value={newUser.name} onChange={e => setNewUser(u => ({ ...u, name: e.target.value }))} className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]" data-testid="new-user-name" />
            </div>
            <div>
              <label htmlFor="new-user-email" className="block text-xs font-medium text-gray-600 mb-1">Email</label>
              <input id="new-user-email" name="email" type="email" value={newUser.email} onChange={e => setNewUser(u => ({ ...u, email: e.target.value }))} className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]" data-testid="new-user-email" autoComplete="email" />
            </div>
            <div>
              <label htmlFor="new-user-role" className="block text-xs font-medium text-gray-600 mb-1 flex items-center">Role <RoleInfoTooltip /></label>
              <select id="new-user-role" name="role" value={newUser.role} onChange={e => setNewUser(u => ({ ...u, role: e.target.value }))} className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] bg-white" data-testid="new-user-role">
                {ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="new-user-password" className="block text-xs font-medium text-gray-600 mb-1">Password</label>
              <input id="new-user-password" name="password" type="password" value={newUser.password} onChange={e => setNewUser(u => ({ ...u, password: e.target.value }))} className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]" data-testid="new-user-password" autoComplete="new-password" />
            </div>
          </div>
          <div className="flex gap-2 mt-4">
            <button onClick={handleCreateUser} className="bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF]" data-testid="save-user-btn">Create</button>
            <button onClick={() => setShowNewUser(false)} className="border border-gray-300 text-gray-600 px-4 py-2 rounded-md text-sm font-medium hover:bg-gray-50">Cancel</button>
          </div>
        </div>
      )}

      <div className="bg-white border border-gray-200 rounded-lg shadow-sm overflow-hidden" data-testid="users-table">
        <table className="w-full">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-600 uppercase tracking-wide">Name</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-600 uppercase tracking-wide hidden sm:table-cell">Email</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-600 uppercase tracking-wide">Role</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-600 uppercase tracking-wide hidden md:table-cell">Status</th>
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-600 uppercase tracking-wide hidden md:table-cell">Portfolio</th>
              <th className="w-10 px-4 py-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {users.map(u => editingId === u.id ? (
              <tr key={u.id} className="bg-blue-50" data-testid={`edit-row-${u.id}`}>
                <td colSpan={6} className="px-4 py-4">
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                    <div>
                      <label htmlFor={`edit-name-${u.id}`} className="block text-xs font-medium text-gray-500 mb-1">Full name</label>
                      <input
                        id={`edit-name-${u.id}`}
                        name="name"
                        value={editForm.name}
                        onChange={e => setEditForm(f => ({ ...f, name: e.target.value }))}
                        className="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
                        data-testid="edit-user-name"
                      />
                    </div>
                    <div>
                      <label htmlFor={`edit-email-${u.id}`} className="block text-xs font-medium text-gray-500 mb-1">Email address</label>
                      <input
                        id={`edit-email-${u.id}`}
                        name="email"
                        type="email"
                        value={editForm.email}
                        onChange={e => setEditForm(f => ({ ...f, email: e.target.value }))}
                        className="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
                        data-testid="edit-user-email"
                      />
                    </div>
                    <div>
                      <label htmlFor={`edit-role-${u.id}`} className="block text-xs font-medium text-gray-500 mb-1 flex items-center">Role <RoleInfoTooltip /></label>
                      <select
                        id={`edit-role-${u.id}`}
                        name="role"
                        value={editForm.role}
                        onChange={e => setEditForm(f => ({ ...f, role: e.target.value }))}
                        className="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] bg-white"
                        data-testid="edit-user-role"
                      >
                        {ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-500 mb-1">Status</label>
                      <label className="flex items-center gap-2 cursor-pointer mt-1.5">
                        <input
                          type="checkbox"
                          checked={editForm.is_active}
                          onChange={e => setEditForm(f => ({ ...f, is_active: e.target.checked }))}
                          className="w-4 h-4 accent-[#1E3A8A]"
                          data-testid="edit-user-active"
                        />
                        <span className="text-sm text-gray-700">{editForm.is_active ? "Active" : "Inactive"}</span>
                      </label>
                    </div>
                  </div>
                  {/* Password reset toggle */}
                  <div className="mt-3 pt-3 border-t border-blue-200">
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
                      <div className="mt-2 max-w-xs">
                        <label htmlFor={`reset-pwd-${u.id}`} className="block text-xs font-medium text-gray-500 mb-1">New password</label>
                        <input
                          id={`reset-pwd-${u.id}`}
                          name="new-password"
                          type="password"
                          value={newPassword}
                          onChange={e => setNewPassword(e.target.value)}
                          placeholder="Min. 8 characters"
                          autoComplete="new-password"
                          className="w-full px-3 py-1.5 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
                          data-testid="new-password-input"
                        />
                      </div>
                    )}
                  </div>

                  {editError && (
                    <p className="text-xs text-red-600 mt-2" data-testid="edit-user-error">{editError}</p>
                  )}
                  <div className="flex gap-2 mt-3">
                    <button
                      onClick={saveEdit}
                      disabled={saving}
                      className="flex items-center gap-1.5 bg-[#1E3A8A] text-white px-3 py-1.5 rounded-md text-sm font-medium hover:bg-[#1E40AF] disabled:opacity-60"
                      data-testid="save-edit-user-btn"
                    >
                      <Check className="w-3.5 h-3.5" />
                      {saving ? "Saving…" : "Save"}
                    </button>
                    <button
                      onClick={cancelEdit}
                      className="flex items-center gap-1.5 border border-gray-300 text-gray-600 px-3 py-1.5 rounded-md text-sm font-medium hover:bg-gray-50"
                      data-testid="cancel-edit-user-btn"
                    >
                      <X className="w-3.5 h-3.5" />
                      Cancel
                    </button>
                  </div>
                </td>
              </tr>
            ) : (
              <tr key={u.id} className="hover:bg-gray-50" data-testid={`user-row-${u.id}`}>
                <td className="px-4 py-3 text-sm font-medium text-gray-900">
                  {u.name}
                  <div className="sm:hidden text-xs text-gray-500 mt-0.5">{u.email}</div>
                </td>
                <td className="px-4 py-3 text-sm text-gray-600 hidden sm:table-cell">{u.email}</td>
                <td className="px-4 py-3">
                  <span className="text-xs px-2 py-0.5 bg-blue-100 text-blue-700 rounded-full capitalize">{u.role}</span>
                </td>
                <td className="px-4 py-3 hidden md:table-cell">
                  <span className={`text-xs ${u.is_active ? "text-emerald-600" : "text-red-500"}`}>
                    {u.is_active ? "Active" : "Inactive"}
                  </span>
                </td>
                <td className="px-4 py-3 hidden md:table-cell">
                  <button
                    onClick={() => navigate(`/portfolio/${u.id}`)}
                    className="flex items-center gap-1 text-xs text-[#1E3A8A] hover:underline"
                    data-testid={`view-portfolio-${u.id}`}
                  >
                    <TrendingUp className="w-3 h-3" /> Portfolio
                  </button>
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => startEdit(u)}
                    className="p-1.5 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-700 transition-colors"
                    title="Edit user"
                    data-testid={`edit-user-${u.id}`}
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

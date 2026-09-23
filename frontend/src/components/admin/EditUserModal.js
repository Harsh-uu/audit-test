import React, { useState, useEffect } from "react";
import axios from "axios";
import { cachedGet, invalidateCache } from "@/utils/apiCache";
import { X, Check, KeyRound, ChevronDown } from "lucide-react";

// ── Shared Edit User modal ──────────────────────────────────────────────────
// Single source of truth for editing name/email/role/active/MFA/team/password.
// Used by both OrgStructure.js (Structure tab) and PeopleHub.js (People tab) —
// previously each page had its own drifted copy of this modal (OrgStructure's
// was missing the Team field, PeopleHub's was missing the MFA toggle).
// Always invalidates all three org caches on save so both tabs stay in sync
// regardless of which page the edit was made from.

const ROLES = [
  { value: "attendee", label: "Staff / Supervisee" },
  { value: "manager", label: "Manager" },
  { value: "shared_reviewer", label: "Shared Reviewer" },
  { value: "admin", label: "Admin" },
];

const inputCls = "w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]";
const selectCls = `${inputCls} bg-white`;

export function EditUserModal({ person, onClose, onSaved, API, getAuthConfig, currentUserRole }) {
  const userId = person.id || person.user_id;
  const [form, setForm] = useState({
    name: person.name,
    email: person.email,
    role: person.role,
    is_active: person.is_active !== false,
    mfa_enabled: Boolean(person.mfa_enabled),
  });
  const [selectedTeam, setSelectedTeam] = useState(person.team_id || "");
  const [teamOptions, setTeamOptions] = useState([]); // [{ id, label }]
  const [showPwd, setShowPwd] = useState(false);
  const [newPwd, setNewPwd] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // Fetch available teams from the org structure
  useEffect(() => {
    cachedGet(`${API}/org/structure`, getAuthConfig())
      .then(res => {
        const opts = [];
        (res.data.settings || []).forEach(s => {
          (s.teams || []).forEach(t => {
            opts.push({
              id: t.id,
              label: (s.teams.length > 0 && res.data.settings.length > 1) ? `${s.name} — ${t.name}` : t.name,
            });
          });
        });
        setTeamOptions(opts);
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async () => {
    if (!form.name.trim()) return setError("Name is required");
    if (!form.email.trim()) return setError("Email is required");
    if (showPwd && newPwd && newPwd.length < 10) return setError("Password must be at least 10 characters");
    setSaving(true);
    setError("");
    try {
      await axios.put(`${API}/admin/users/${userId}`, form, getAuthConfig());
      if (showPwd && newPwd.trim()) {
        await axios.post(`${API}/admin/users/${userId}/reset-password`, { new_password: newPwd }, getAuthConfig());
      }
      if (form.role !== "admin" && selectedTeam !== (person.team_id || "")) {
        await axios.patch(`${API}/org/users/${userId}/assign-team`, { team_id: selectedTeam || null }, getAuthConfig());
      }
      onSaved();
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to save");
    } finally {
      // Always invalidate — even a partial failure (e.g. PUT succeeded but the
      // team PATCH failed) may have changed persisted state, so stale caches
      // must not survive regardless of which step threw.
      invalidateCache("/admin/users", "/org/structure", "/admin/people-stats");
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" data-testid="edit-user-modal">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-5">
          <h3 className="font-semibold text-gray-900">Edit — {person.name}</h3>
          <button onClick={onClose}><X className="w-4 h-4 text-gray-400" /></button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Full name</label>
            <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              className={inputCls} data-testid="edit-user-name" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Email address</label>
            <input type="email" value={form.email} onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
              className={inputCls} data-testid="edit-user-email" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Role</label>
            <select value={form.role} onChange={e => setForm(f => ({ ...f, role: e.target.value }))}
              className={selectCls} data-testid="edit-user-role">
              {ROLES.filter(r => currentUserRole === "admin" ? true : r.value !== "admin").map(r => (
                <option key={r.value} value={r.value}>{r.label}</option>
              ))}
            </select>
          </div>

          {form.role !== "admin" && (
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Team</label>
              <select value={selectedTeam} onChange={e => setSelectedTeam(e.target.value)}
                className={selectCls} data-testid="edit-user-team">
                <option value="">— No team (unassigned)</option>
                {teamOptions.map(t => (
                  <option key={t.id} value={t.id}>{t.label}</option>
                ))}
              </select>
              {teamOptions.length === 0 && (
                <p className="text-xs text-gray-400 mt-1">No teams created yet. Add teams in the Structure tab.</p>
              )}
            </div>
          )}

          <div className="flex items-center gap-2 pt-1">
            <input type="checkbox" id="edit-active" checked={form.is_active}
              onChange={e => setForm(f => ({ ...f, is_active: e.target.checked }))}
              className="w-4 h-4 accent-[#1E3A8A]" data-testid="edit-user-active" />
            <label htmlFor="edit-active" className="text-sm text-gray-700 cursor-pointer">
              {form.is_active ? "Active" : "Inactive (blocked from login)"}
            </label>
          </div>

          {(form.role === "admin" || form.role === "manager") && (
            <div className="flex items-center gap-2">
              <input type="checkbox" id="edit-user-mfa" checked={Boolean(form.mfa_enabled)}
                onChange={e => setForm(f => ({ ...f, mfa_enabled: e.target.checked }))}
                className="w-4 h-4 accent-[#1E3A8A]" data-testid="edit-user-mfa" />
              <label htmlFor="edit-user-mfa" className="text-sm text-gray-700 cursor-pointer">
                Two-Factor Authentication (2FA)
              </label>
              {Boolean(form.mfa_enabled) && (
                <span className="text-xs text-emerald-600 font-medium">Enabled</span>
              )}
            </div>
          )}

          <div className="pt-2 border-t border-gray-100">
            <button type="button" onClick={() => { setShowPwd(p => !p); setNewPwd(""); }}
              className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-800 transition-colors"
              data-testid="toggle-reset-password">
              <KeyRound className="w-3.5 h-3.5" />
              {showPwd ? "Cancel password change" : "Reset password"}
              <ChevronDown className={`w-3 h-3 transition-transform ${showPwd ? "rotate-180" : ""}`} />
            </button>
            {showPwd && (
              <input type="password" value={newPwd} onChange={e => setNewPwd(e.target.value)}
                placeholder="New password (min. 10 chars)"
                className={`mt-2 ${inputCls}`}
                data-testid="new-password-input" />
            )}
          </div>

          {error && <p className="text-xs text-red-600" data-testid="edit-user-error">{error}</p>}

          <div className="flex gap-2 pt-1">
            <button onClick={save} disabled={saving}
              className="flex items-center gap-1.5 bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF] disabled:opacity-60"
              data-testid="save-edit-user-btn">
              <Check className="w-3.5 h-3.5" />{saving ? "Saving…" : "Save"}
            </button>
            <button onClick={onClose} className="px-4 py-2 border border-gray-300 text-gray-600 rounded-md text-sm hover:bg-gray-50">Cancel</button>
          </div>
        </div>
      </div>
    </div>
  );
}

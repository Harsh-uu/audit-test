import React, { useState, useEffect } from "react";
import axios from "axios";
import { toast } from "sonner";
import { cachedGet, invalidateCache } from "@/utils/apiCache";
import { X, UserPlus, KeyRound, Eye, EyeOff, Dices } from "lucide-react";

// ── Quick "Add User" modal ──────────────────────────────────────────────────
// Lets an admin/manager add a single user straight from the People & Usage
// tab, without first having to set up a Setting/Team in Structure. Team stays
// optional here (unlike OrgStructure's "Add User", which is scoped to a
// Setting and requires one) — new users can simply land in "Unassigned" and
// be sorted into a team later once the org has them set up.

const ROLES = [
  { value: "attendee", label: "Staff / Supervisee" },
  { value: "manager", label: "Manager" },
  { value: "shared_reviewer", label: "Shared Reviewer" },
  { value: "admin", label: "Admin" },
];

const inputCls = "w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]";
const selectCls = `${inputCls} bg-white`;

function generatePassword() {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%";
  const bytes = new Uint32Array(14);
  window.crypto.getRandomValues(bytes);
  return Array.from(bytes, b => chars[b % chars.length]).join("");
}

export function AddUserModal({ onClose, onAdded, API, getAuthConfig, currentUserRole }) {
  const [form, setForm] = useState({ name: "", email: "", role: "attendee", team_id: "", password: generatePassword() });
  const [teamOptions, setTeamOptions] = useState([]); // [{ id, label }]
  const [showPwd, setShowPwd] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

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
    if (form.password.length < 10) return setError("Password must be at least 10 characters");
    setSaving(true);
    setError("");
    let createdUserId = null;
    try {
      const res = await axios.post(`${API}/org/invite-user`, {
        name: form.name, email: form.email, password: form.password, role: form.role,
      }, getAuthConfig());
      createdUserId = res.data.id;
      if (form.role !== "admin" && form.team_id) {
        await axios.patch(`${API}/org/users/${createdUserId}/assign-team`, { team_id: form.team_id }, getAuthConfig());
      }
      invalidateCache("/admin/users", "/org/structure", "/admin/people-stats");
      toast.success(`${form.name} added${form.team_id ? "" : " — unassigned, add to a team any time"}`);
      onAdded();
    } catch (err) {
      if (createdUserId) {
        // Account itself was created — only the team assignment failed. Still
        // a success from the user's point of view, so close the modal and
        // refresh rather than leaving them staring at a scary-looking error.
        invalidateCache("/admin/users", "/org/structure", "/admin/people-stats");
        toast.success(`${form.name} added, but couldn't assign a team (${err.response?.data?.detail || "error"}). They're Unassigned — assign one from Structure.`);
        onAdded();
      } else {
        setError(err.response?.data?.detail || "Failed to add user");
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" data-testid="add-user-modal">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-5">
          <h3 className="font-semibold text-gray-900 flex items-center gap-2">
            <UserPlus className="w-4 h-4 text-[#1E3A8A]" /> Add User
          </h3>
          <button onClick={onClose} data-testid="add-user-close-btn"><X className="w-4 h-4 text-gray-400" /></button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Full name *</label>
            <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              placeholder="e.g. Jane Smith" className={inputCls} data-testid="add-user-name" autoFocus />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Email address *</label>
            <input type="email" value={form.email} onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
              placeholder="jane@example.com" className={inputCls} data-testid="add-user-email" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Role</label>
            <select value={form.role} onChange={e => setForm(f => ({ ...f, role: e.target.value }))}
              className={selectCls} data-testid="add-user-role">
              {ROLES.filter(r => currentUserRole === "admin" ? true : r.value !== "admin").map(r => (
                <option key={r.value} value={r.value}>{r.label}</option>
              ))}
            </select>
          </div>

          {form.role !== "admin" && (
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Team</label>
              <select value={form.team_id} onChange={e => setForm(f => ({ ...f, team_id: e.target.value }))}
                className={selectCls} data-testid="add-user-team">
                <option value="">— No team (unassigned for now)</option>
                {teamOptions.map(t => (
                  <option key={t.id} value={t.id}>{t.label}</option>
                ))}
              </select>
              {teamOptions.length === 0 && (
                <p className="text-xs text-gray-400 mt-1">No teams set up yet — that's fine, you can add them any time in the Structure tab.</p>
              )}
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Temporary password *</label>
            <div className="flex gap-1.5">
              <div className="relative flex-1">
                <input type={showPwd ? "text" : "password"} value={form.password}
                  onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                  className={`${inputCls} pr-8`} data-testid="add-user-password" />
                <button type="button" onClick={() => setShowPwd(p => !p)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                  data-testid="add-user-toggle-password-visibility">
                  {showPwd ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
              <button type="button" onClick={() => setForm(f => ({ ...f, password: generatePassword() }))}
                title="Generate a new password"
                className="flex items-center gap-1 px-2.5 border border-gray-300 rounded-md text-xs text-gray-600 hover:bg-gray-50"
                data-testid="add-user-regenerate-password">
                <Dices className="w-3.5 h-3.5" />
              </button>
            </div>
            <p className="text-[11px] text-gray-400 mt-1 flex items-center gap-1">
              <KeyRound className="w-3 h-3" /> Pre-filled with a strong password — share it with {form.name || "the new user"} however you'd like, or write your own.
            </p>
          </div>

          {error && <p className="text-xs text-red-600" data-testid="add-user-error">{error}</p>}

          <div className="flex gap-2 pt-1">
            <button onClick={save} disabled={saving}
              className="flex items-center gap-1.5 bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF] disabled:opacity-60"
              data-testid="add-user-submit-btn">
              <UserPlus className="w-3.5 h-3.5" />{saving ? "Adding…" : "Add User"}
            </button>
            <button onClick={onClose} className="px-4 py-2 border border-gray-300 text-gray-600 rounded-md text-sm hover:bg-gray-50">Cancel</button>
          </div>
        </div>
      </div>
    </div>
  );
}

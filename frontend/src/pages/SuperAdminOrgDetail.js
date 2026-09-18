import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { toast } from "sonner";
import { useNavigate, useParams } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import {
  ArrowLeft, Users, FileText, Plus, X, AlertCircle, CheckCircle, Loader2,
  Mail, Copy, Pencil, Trash2, Check, HelpCircle, Clock, CreditCard, Building2,
} from "lucide-react";

const API = "/api";

const ROLE_OPTIONS = ["manager", "admin", "attendee", "shared_reviewer"];
const ROLE_LABELS = { manager: "Manager", admin: "Admin", attendee: "Staff", shared_reviewer: "Shared Reviewer" };

// Placeholder pricing tiers ahead of the real Stripe connection — mirrors
// supervision2.co.uk/#pricing. Kept in sync with SuperAdminDashboard.js.
const PRICING_TIERS = {
  starter:    { label: "Starter",    included_hours: 10 },
  growth:     { label: "Growth",     included_hours: 30 },
  scale:      { label: "Scale",      included_hours: 70 },
  enterprise: { label: "Enterprise", included_hours: null },
};
const STRIPE_STATUS_LABELS = {
  active: "Active", trialing: "Trialing", past_due: "Past Due",
  canceled: "Canceled", unpaid: "Unpaid", incomplete: "Incomplete",
};
const STRIPE_STATUS_BAD = new Set(["past_due", "canceled", "unpaid", "incomplete"]);

function RoleInfoTooltip() {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <HelpCircle className="w-3.5 h-3.5 text-gray-400 ml-1 cursor-help" />
      </TooltipTrigger>
      <TooltipContent className="max-w-xs text-xs">
        <p><strong>Admin</strong>: full org control incl. billing & users.</p>
        <p><strong>Manager</strong>: runs supervisions, reviews evidence.</p>
        <p><strong>Attendee</strong>: staff member being supervised.</p>
        <p><strong>Shared Reviewer</strong>: read-only evidence review access.</p>
      </TooltipContent>
    </Tooltip>
  );
}

function TierBadge({ tier }) {
  if (!tier || !PRICING_TIERS[tier]) return <span className="text-xs text-gray-400">No tier set</span>;
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-indigo-100 text-indigo-700">
      {PRICING_TIERS[tier].label}
    </span>
  );
}

function StripeStatusBadge({ status }) {
  if (!status) return <span className="text-xs text-gray-400">Not connected</span>;
  const bad = STRIPE_STATUS_BAD.has(status);
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${
      bad ? "bg-red-100 text-red-700" : "bg-emerald-100 text-emerald-700"
    }`}>
      <CreditCard className="w-3 h-3" />
      {STRIPE_STATUS_LABELS[status] || status}
    </span>
  );
}

function UsageBar({ org }) {
  const included = org.included_hours_monthly;
  const used = org.current_period_hours || 0;
  const pct = included ? Math.min(100, Math.round((used / included) * 100)) : null;
  return (
    <div data-testid={`org-usage-${org.id}`}>
      <div className="flex items-baseline justify-between mb-1">
        <span className={`text-xs font-medium ${org.hours_overage ? "text-red-600" : "text-gray-600"}`}>
          {used.toFixed(1)} hrs{included != null ? ` / ${included} hrs this cycle` : " this cycle"}
          {pct != null && ` (${pct}%)`}
        </span>
        {org.hours_overage && (
          <span className="text-xs font-bold text-red-600 flex items-center gap-0.5" data-testid={`org-overage-flag-${org.id}`}>
            <AlertCircle className="w-3 h-3" /> Over
          </span>
        )}
      </div>
      {included != null && (
        <div className="w-full h-1.5 bg-gray-100 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${org.hours_overage ? "bg-red-500" : "bg-[#1E3A8A]"}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
      <p className="text-[11px] text-gray-400 mt-0.5">{org.cumulative_hours.toFixed(1)} hrs all-time</p>
    </div>
  );
}

function StatusBadge({ status }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${
      status === "active" ? "bg-emerald-100 text-emerald-700" : "bg-gray-200 text-gray-600"
    }`}>
      {status === "active" ? "Active" : "Suspended"}
    </span>
  );
}

function RoleBadge({ role }) {
  const colors = {
    admin: "bg-purple-100 text-purple-700",
    manager: "bg-blue-100 text-blue-700",
    attendee: "bg-gray-100 text-gray-600",
    shared_reviewer: "bg-teal-100 text-teal-700",
  };
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-semibold flex-shrink-0 ${colors[role] || "bg-gray-100 text-gray-600"}`}>
      {ROLE_LABELS[role] || role}
    </span>
  );
}

export default function SuperAdminOrgDetail() {
  const { orgId } = useParams();
  const navigate = useNavigate();
  const { getAuthConfig } = useAuth();

  const [org, setOrg] = useState(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [orgUsers, setOrgUsers] = useState([]);
  const [usersLoading, setUsersLoading] = useState(false);
  const [usageHistory, setUsageHistory] = useState([]);
  const [usageHistoryLoading, setUsageHistoryLoading] = useState(false);
  const [billingForm, setBillingForm] = useState({
    pricing_tier: "", included_hours_monthly: "", is_trial: false, trial_ends_at: "",
    stripe_customer_id: "", stripe_subscription_status: "", stripe_current_period_end: "", billing_notes: "",
  });
  const [savingBilling, setSavingBilling] = useState(false);
  const [showCreateUser, setShowCreateUser] = useState(false);
  const [showInviteAdmin, setShowInviteAdmin] = useState(false);
  const [editingUserId, setEditingUserId] = useState(null);
  const [editUserForm, setEditUserForm] = useState({ name: "", email: "", role: "", password: "" });
  const [userForm, setUserForm] = useState({ name: "", email: "", password: "", role: "manager" });
  const [inviteForm, setInviteForm] = useState({ name: "", email: "" });
  const [inviteResult, setInviteResult] = useState(null);
  const [userToDelete, setUserToDelete] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const loadOrg = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/super-admin/orgs/${orgId}`, getAuthConfig());
      setOrg(data);
      setBillingForm({
        pricing_tier: data.pricing_tier || "",
        included_hours_monthly: data.included_hours_monthly ?? "",
        is_trial: data.is_trial || false,
        trial_ends_at: data.trial_ends_at ? data.trial_ends_at.slice(0, 10) : "",
        stripe_customer_id: data.stripe_customer_id || "",
        stripe_subscription_status: data.stripe_subscription_status || "",
        stripe_current_period_end: data.stripe_current_period_end ? data.stripe_current_period_end.slice(0, 10) : "",
        billing_notes: data.billing_notes || "",
      });
    } catch (err) {
      if (err.response?.status === 404) setNotFound(true);
      else setError("Failed to load organisation");
    } finally {
      setLoading(false);
    }
  }, [orgId, getAuthConfig]);

  const loadUsers = useCallback(async () => {
    setUsersLoading(true);
    try {
      const { data } = await axios.get(`${API}/super-admin/orgs/${orgId}/users`, getAuthConfig());
      setOrgUsers(data);
    } catch {
      setOrgUsers([]);
    } finally {
      setUsersLoading(false);
    }
  }, [orgId, getAuthConfig]);

  const loadUsageHistory = useCallback(async () => {
    setUsageHistoryLoading(true);
    try {
      const { data } = await axios.get(`${API}/super-admin/orgs/${orgId}/usage-history`, getAuthConfig());
      setUsageHistory(data);
    } catch {
      setUsageHistory([]);
    } finally {
      setUsageHistoryLoading(false);
    }
  }, [orgId, getAuthConfig]);

  useEffect(() => { loadOrg(); loadUsers(); loadUsageHistory(); }, [loadOrg, loadUsers, loadUsageHistory]);

  const handleTierSelect = (tier) => {
    setBillingForm(f => ({
      ...f,
      pricing_tier: tier,
      included_hours_monthly: tier && PRICING_TIERS[tier]?.included_hours != null
        ? String(PRICING_TIERS[tier].included_hours)
        : f.included_hours_monthly,
    }));
  };

  const handleSaveBilling = async () => {
    setSavingBilling(true);
    setError("");
    try {
      const payload = {
        pricing_tier: billingForm.pricing_tier || "",
        included_hours_monthly: billingForm.included_hours_monthly === "" ? null : parseFloat(billingForm.included_hours_monthly),
        is_trial: billingForm.is_trial,
        trial_ends_at: billingForm.trial_ends_at || "",
        stripe_customer_id: billingForm.stripe_customer_id.trim() || "",
        stripe_subscription_status: billingForm.stripe_subscription_status || "",
        stripe_current_period_end: billingForm.stripe_current_period_end || "",
        billing_notes: billingForm.billing_notes.trim() || "",
      };
      await axios.patch(`${API}/super-admin/orgs/${orgId}/billing`, payload, getAuthConfig());
      toast.success("Billing info updated");
      await loadOrg();
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to update billing info");
    } finally {
      setSavingBilling(false);
    }
  };

  const handleCreateUser = async (e) => {
    e.preventDefault();
    if (!userForm.name.trim() || !userForm.email.trim() || !userForm.password) return;
    setSubmitting(true);
    setError("");
    try {
      await axios.post(`${API}/super-admin/orgs/${orgId}/users`, userForm, getAuthConfig());
      setUserForm({ name: "", email: "", password: "", role: "manager" });
      setShowCreateUser(false);
      await loadUsers();
      await loadOrg();
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
      await axios.patch(`${API}/super-admin/orgs/${orgId}/users/${userId}`, payload, getAuthConfig());
      setEditingUserId(null);
      await loadUsers();
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
      const { data } = await axios.delete(`${API}/super-admin/orgs/${orgId}/users/${userToDelete.id}`, getAuthConfig());
      toast.success(data.message || "User deleted successfully");
      setUserToDelete(null);
      await loadUsers();
      await loadOrg();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to delete user");
      setUserToDelete(null);
    } finally {
      setDeleting(false);
    }
  };

  const toggleOrgStatus = async () => {
    const newStatus = org.status === "active" ? "suspended" : "active";
    try {
      await axios.patch(`${API}/super-admin/orgs/${orgId}`, { status: newStatus }, getAuthConfig());
      setOrg(o => ({ ...o, status: newStatus }));
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
      const { data } = await axios.post(`${API}/super-admin/orgs/${orgId}/invite`, inviteForm, getAuthConfig());
      setInviteResult(data);
      setInviteForm({ name: "", email: "" });
      await loadOrg();
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to send invitation");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <Layout>
        <div className="min-h-full bg-[#F8F9FA] flex items-center justify-center py-20 text-gray-400 gap-3">
          <Loader2 className="w-5 h-5 animate-spin" />
          <span className="text-sm">Loading organisation...</span>
        </div>
      </Layout>
    );
  }

  if (notFound || !org) {
    return (
      <Layout>
        <div className="min-h-full bg-[#F8F9FA] flex flex-col items-center justify-center py-20 text-center">
          <Building2 className="w-12 h-12 text-gray-300 mb-3" />
          <p className="text-gray-500 font-medium">Organisation not found</p>
          <button
            onClick={() => navigate("/super-admin")}
            data-testid="back-to-orgs-btn-notfound"
            className="mt-4 text-sm text-[#1E3A8A] font-semibold hover:underline"
          >
            Back to Organisations
          </button>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="min-h-full bg-[#F8F9FA] p-6 lg:p-8">
        <button
          onClick={() => navigate("/super-admin")}
          data-testid="back-to-orgs-btn"
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-[#1E3A8A] mb-4 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" /> Back to Organisations
        </button>

        <div className="flex items-center justify-between mb-6">
          <div>
            <div className="flex items-center gap-2.5">
              <h1 className="text-2xl font-bold font-display text-[#1E3A8A]">{org.name}</h1>
              <StatusBadge status={org.status} />
            </div>
            <p className="text-sm text-gray-500 mt-0.5">
              {org.jurisdiction?.replace(/_/g, " ")} · Signed up {new Date(org.created_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}
            </p>
          </div>
          <button
            onClick={toggleOrgStatus}
            data-testid="toggle-status-btn"
            className={`px-4 py-2 rounded-lg text-sm font-semibold border transition-colors ${
              org.status === "active" ? "border-red-200 text-red-600 hover:bg-red-50" : "border-emerald-200 text-emerald-600 hover:bg-emerald-50"
            }`}
          >
            {org.status === "active" ? "Suspend" : "Activate"}
          </button>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 flex items-center gap-2">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            {error}
            <button onClick={() => setError("")} className="ml-auto"><X className="w-4 h-4" /></button>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left column: stats + billing & usage */}
          <div className="lg:col-span-1 space-y-6">
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-white border border-gray-200 rounded-lg p-4 text-center">
                <p className="text-2xl font-bold text-[#1E3A8A] font-display">{org.user_count}</p>
                <p className="text-xs text-gray-500">Users</p>
              </div>
              <div className="bg-white border border-gray-200 rounded-lg p-4 text-center">
                <p className="text-2xl font-bold text-[#1E3A8A] font-display">{org.meeting_count}</p>
                <p className="text-xs text-gray-500">Meetings</p>
              </div>
            </div>

            {/* Billing & usage — manual placeholder fields ahead of the real Stripe connection */}
            <div className="bg-white border border-gray-200 rounded-lg p-4">
              <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-1.5">
                <CreditCard className="w-4 h-4 text-gray-400" /> Billing & Usage
              </h3>
              <div className="flex items-center gap-2 mb-3">
                <TierBadge tier={org.pricing_tier} />
                <StripeStatusBadge status={org.stripe_subscription_status} />
                {org.is_trial && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-700">
                    <Clock className="w-3 h-3" /> Trial
                  </span>
                )}
              </div>
              <div className="mb-3 p-2.5 bg-[#F8F9FA] rounded-lg">
                <UsageBar org={org} />
              </div>

              <div className="grid grid-cols-2 gap-2 mb-2">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Pricing tier</label>
                  <select
                    value={billingForm.pricing_tier}
                    onChange={e => handleTierSelect(e.target.value)}
                    data-testid="billing-tier-select"
                    className="w-full border border-gray-300 rounded-lg px-2.5 py-1.5 text-sm bg-white focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
                  >
                    <option value="">No tier set</option>
                    {Object.entries(PRICING_TIERS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Included hrs/month</label>
                  <input
                    type="number"
                    min="0"
                    step="0.5"
                    value={billingForm.included_hours_monthly}
                    onChange={e => setBillingForm(f => ({ ...f, included_hours_monthly: e.target.value }))}
                    placeholder="e.g. custom for Enterprise"
                    data-testid="billing-included-hours-input"
                    className="w-full border border-gray-300 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
                  />
                </div>
              </div>

              <label className="flex items-center gap-1.5 text-xs font-medium text-gray-600 mb-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={billingForm.is_trial}
                  onChange={e => setBillingForm(f => ({ ...f, is_trial: e.target.checked }))}
                  data-testid="billing-is-trial-checkbox"
                  className="rounded border-gray-300 text-amber-600 focus:ring-amber-500"
                />
                On trial
                {billingForm.is_trial && (
                  <input
                    type="date"
                    value={billingForm.trial_ends_at}
                    onChange={e => setBillingForm(f => ({ ...f, trial_ends_at: e.target.value }))}
                    data-testid="billing-trial-ends-input"
                    className="ml-2 border border-gray-300 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
                  />
                )}
              </label>

              <div className="grid grid-cols-2 gap-2 mb-2">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Stripe customer ID</label>
                  <input
                    type="text"
                    value={billingForm.stripe_customer_id}
                    onChange={e => setBillingForm(f => ({ ...f, stripe_customer_id: e.target.value }))}
                    placeholder="cus_..."
                    data-testid="billing-stripe-customer-input"
                    className="w-full border border-gray-300 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Stripe status</label>
                  <select
                    value={billingForm.stripe_subscription_status}
                    onChange={e => setBillingForm(f => ({ ...f, stripe_subscription_status: e.target.value }))}
                    data-testid="billing-stripe-status-select"
                    className="w-full border border-gray-300 rounded-lg px-2.5 py-1.5 text-sm bg-white focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
                  >
                    <option value="">Not connected</option>
                    {Object.entries(STRIPE_STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </div>
              </div>

              <div className="mb-2">
                <label className="block text-xs font-medium text-gray-600 mb-1">Next payment date</label>
                <input
                  type="date"
                  value={billingForm.stripe_current_period_end}
                  onChange={e => setBillingForm(f => ({ ...f, stripe_current_period_end: e.target.value }))}
                  data-testid="billing-next-payment-input"
                  className="w-full border border-gray-300 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
                />
              </div>

              <div className="mb-3">
                <label className="block text-xs font-medium text-gray-600 mb-1">Billing notes</label>
                <textarea
                  value={billingForm.billing_notes}
                  onChange={e => setBillingForm(f => ({ ...f, billing_notes: e.target.value }))}
                  rows={2}
                  placeholder="Any manual notes for this org's billing arrangement"
                  data-testid="billing-notes-textarea"
                  className="w-full border border-gray-300 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-[#1E3A8A] resize-none"
                />
              </div>

              <button
                onClick={handleSaveBilling}
                disabled={savingBilling}
                data-testid="save-billing-btn"
                className="w-full flex items-center justify-center gap-2 py-2 bg-[#1E3A8A] text-white rounded-lg text-sm font-semibold hover:bg-[#1e40af] disabled:opacity-60 transition-colors"
              >
                {savingBilling ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                Save Billing Info
              </button>

              {/* Monthly usage history — last 12 cycles, anchored to signup date */}
              <div className="mt-4 pt-3 border-t border-gray-100">
                <p className="text-xs font-semibold text-gray-600 mb-2">Usage history (last 12 cycles)</p>
                {usageHistoryLoading ? (
                  <div className="flex items-center gap-2 text-gray-400 text-xs py-2">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading...
                  </div>
                ) : usageHistory.length === 0 ? (
                  <p className="text-xs text-gray-400">No usage recorded yet</p>
                ) : (
                  <div className="space-y-1 max-h-40 overflow-y-auto" data-testid="usage-history-list">
                    {usageHistory.slice().reverse().map((c, i) => (
                      <div key={i} className="flex items-center justify-between text-xs py-1 border-b border-gray-50 last:border-0">
                        <span className="text-gray-500">
                          {new Date(c.period_start).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}
                          {" – "}
                          {new Date(c.period_end).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}
                        </span>
                        <span className="font-medium text-gray-700">{c.hours.toFixed(1)} hrs</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Right column: users */}
          <div className="lg:col-span-2">
            <div className="bg-white border border-gray-200 rounded-lg p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold text-gray-700">Users</h3>
                <div className="flex items-center gap-3">
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
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {orgUsers.map(u => (
                    <div key={u.id} className="border border-gray-100 rounded-lg bg-[#F8F9FA] overflow-hidden">
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
        </div>

        {/* ── Create User Modal ─────────────────────────────────────────── */}
        {showCreateUser && (
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
                <p className="text-xs text-gray-400 mb-5">Adding to: <span className="font-medium text-gray-600">{org.name}</span></p>
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
                      placeholder="Min. 10 characters"
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
        {showInviteAdmin && (
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
                  For: <span className="font-medium text-gray-600">{org.name}</span>
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
                      onClick={() => { setShowInviteAdmin(false); setInviteResult(null); loadUsers(); }}
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

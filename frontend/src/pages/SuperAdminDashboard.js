import React, { useState, useEffect, useCallback, useMemo } from "react";
import axios from "axios";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import { Building2, Users, FileText, Plus, X, ChevronRight, AlertCircle, CheckCircle, Loader2, Pencil, Clock, CreditCard, Download, ArrowUpDown, Cpu, Target, Mic } from "lucide-react";
import SuperAdminAIUsage from "@/components/superadmin/SuperAdminAIUsage";
import SuperAdminAIAccuracy from "@/components/superadmin/SuperAdminAIAccuracy";
import SuperAdminTranscriptionUsage from "@/components/superadmin/SuperAdminTranscriptionUsage";
import { JurisdictionFields } from "@/components/JurisdictionFields";

const API = "/api";

// Placeholder pricing tiers ahead of the real Stripe connection — mirrors
// supervision2.co.uk/#pricing. included_hours auto-fills the form but stays
// editable per org (founding-member/custom deals differ from list price).
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

export default function SuperAdminDashboard() {
  const { getAuthConfig } = useAuth();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState("orgs");
  const [orgs, setOrgs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreateOrg, setShowCreateOrg] = useState(false);
  const [showEditOrg, setShowEditOrg] = useState(false);
  const [editOrgForm, setEditOrgForm] = useState({ name: "", jurisdiction: "england", service_type: "domiciliary" });
  const [orgForm, setOrgForm] = useState({ name: "", jurisdiction: "england", service_type: "domiciliary" });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  // Billing/usage filters + sort
  const [tierFilter, setTierFilter] = useState("all");
  const [stripeFilter, setStripeFilter] = useState("all");
  const [overageOnly, setOverageOnly] = useState(false);
  const [sortBy, setSortBy] = useState("name");

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

  const visibleOrgs = useMemo(() => {
    let list = orgs;
    if (tierFilter !== "all") list = list.filter(o => (o.pricing_tier || "none") === tierFilter);
    if (stripeFilter !== "all") list = list.filter(o => (o.stripe_subscription_status || "none") === stripeFilter);
    if (overageOnly) list = list.filter(o => o.hours_overage);
    list = [...list];
    if (sortBy === "usage_desc") list.sort((a, b) => b.current_period_hours - a.current_period_hours);
    else if (sortBy === "overage_first") list.sort((a, b) => (b.hours_overage ? 1 : 0) - (a.hours_overage ? 1 : 0));
    else list.sort((a, b) => a.name.localeCompare(b.name));
    return list;
  }, [orgs, tierFilter, stripeFilter, overageOnly, sortBy]);

  const exportUsageCSV = () => {
    const header = ["Organisation", "Tier", "Included Hours", "Hours This Cycle", "Cumulative Hours", "Overage", "Stripe Status", "Next Payment Date", "Users", "Meetings"];
    const rows = visibleOrgs.map(o => [
      o.name,
      PRICING_TIERS[o.pricing_tier]?.label || "—",
      o.included_hours_monthly ?? "—",
      o.current_period_hours,
      o.cumulative_hours,
      o.hours_overage ? "YES" : "NO",
      STRIPE_STATUS_LABELS[o.stripe_subscription_status] || "—",
      o.stripe_current_period_end ? new Date(o.stripe_current_period_end).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "—",
      o.user_count,
      o.meeting_count,
    ]);
    const csv = [header, ...rows].map(r => r.map(v => `"${String(v ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `org-usage-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
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
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to update organisation");
    } finally {
      setSubmitting(false);
    }
  };

  const toggleOrgStatus = async (org) => {
    const newStatus = org.status === "active" ? "suspended" : "active";
    try {
      await axios.patch(`${API}/super-admin/orgs/${org.id}`, { status: newStatus }, getAuthConfig());
      await loadOrgs();
    } catch {
      setError("Failed to update status");
    }
  };

  return (
    <Layout>
    <div className="min-h-full bg-[#F8F9FA] p-6 lg:p-8">
      {/* Page Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold font-display text-[#1E3A8A]">Organisations</h1>
          <p className="text-sm text-gray-500 mt-0.5">{orgs.length} organisation{orgs.length !== 1 ? "s" : ""} registered</p>
        </div>
        {activeTab === "orgs" && (
          <button
            data-testid="create-org-btn"
            onClick={() => { setShowCreateOrg(true); setError(""); }}
            className="flex items-center gap-2 bg-[#1E3A8A] text-white px-4 py-2 rounded-lg text-sm font-semibold hover:bg-[#1e40af] transition-colors"
          >
            <Plus className="w-4 h-4" />
            New Organisation
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 mb-6 border-b border-gray-200" data-testid="super-admin-tabs">
        <button
          data-testid="tab-orgs"
          onClick={() => setActiveTab("orgs")}
          className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-semibold border-b-2 transition-colors ${
            activeTab === "orgs" ? "border-[#1E3A8A] text-[#1E3A8A]" : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          <Building2 className="w-4 h-4" /> Organisations
        </button>
        <button
          data-testid="tab-ai-usage"
          onClick={() => setActiveTab("ai_usage")}
          className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-semibold border-b-2 transition-colors ${
            activeTab === "ai_usage" ? "border-[#1E3A8A] text-[#1E3A8A]" : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          <Cpu className="w-4 h-4" /> AI Usage
        </button>
        <button
          data-testid="tab-ai-accuracy"
          onClick={() => setActiveTab("ai_accuracy")}
          className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-semibold border-b-2 transition-colors ${
            activeTab === "ai_accuracy" ? "border-[#1E3A8A] text-[#1E3A8A]" : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          <Target className="w-4 h-4" /> AI Accuracy
        </button>
        <button
          data-testid="tab-transcription-usage"
          onClick={() => setActiveTab("transcription_usage")}
          className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-semibold border-b-2 transition-colors ${
            activeTab === "transcription_usage" ? "border-[#1E3A8A] text-[#1E3A8A]" : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          <Mic className="w-4 h-4" /> Transcription Usage
        </button>
      </div>

      {activeTab === "ai_usage" ? (
        <SuperAdminAIUsage getAuthConfig={getAuthConfig} orgs={orgs} />
      ) : activeTab === "ai_accuracy" ? (
        <SuperAdminAIAccuracy getAuthConfig={getAuthConfig} orgs={orgs} />
      ) : activeTab === "transcription_usage" ? (
        <SuperAdminTranscriptionUsage getAuthConfig={getAuthConfig} orgs={orgs} />
      ) : (
      <>
      {/* Global error */}
      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700 flex items-center gap-2">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          {error}
          <button onClick={() => setError("")} className="ml-auto"><X className="w-4 h-4" /></button>
        </div>
      )}

      {/* Billing/usage filter toolbar */}
      {!loading && orgs.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 mb-5 bg-white border border-gray-200 rounded-lg p-3">
          <select
            value={tierFilter}
            onChange={e => setTierFilter(e.target.value)}
            data-testid="filter-tier-select"
            className="border border-gray-300 rounded-lg px-2.5 py-1.5 text-xs font-medium text-gray-600 bg-white focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
          >
            <option value="all">All tiers</option>
            {Object.entries(PRICING_TIERS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            <option value="none">No tier set</option>
          </select>
          <select
            value={stripeFilter}
            onChange={e => setStripeFilter(e.target.value)}
            data-testid="filter-stripe-select"
            className="border border-gray-300 rounded-lg px-2.5 py-1.5 text-xs font-medium text-gray-600 bg-white focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
          >
            <option value="all">All Stripe statuses</option>
            {Object.entries(STRIPE_STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            <option value="none">Not connected</option>
          </select>
          <label className="flex items-center gap-1.5 text-xs font-medium text-gray-600 px-1 cursor-pointer">
            <input
              type="checkbox"
              checked={overageOnly}
              onChange={e => setOverageOnly(e.target.checked)}
              data-testid="filter-overage-only-checkbox"
              className="rounded border-gray-300 text-red-600 focus:ring-red-500"
            />
            Overage only
          </label>
          <button
            onClick={() => setSortBy(sortBy === "usage_desc" ? "name" : "usage_desc")}
            data-testid="sort-usage-btn"
            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
              sortBy === "usage_desc" ? "bg-[#1E3A8A] text-white border-[#1E3A8A]" : "border-gray-300 text-gray-600 hover:bg-gray-50"
            }`}
          >
            <ArrowUpDown className="w-3.5 h-3.5" /> Sort by usage
          </button>
          <button
            onClick={exportUsageCSV}
            data-testid="export-usage-csv-btn"
            className="flex items-center gap-1.5 ml-auto px-2.5 py-1.5 rounded-lg text-xs font-semibold border border-gray-300 text-gray-600 hover:bg-gray-50 transition-colors"
          >
            <Download className="w-3.5 h-3.5" /> Export usage CSV
          </button>
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
          {visibleOrgs.map(org => (
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

              <div className="flex gap-4 mb-3">
                <div className="flex items-center gap-1.5 text-gray-500">
                  <Users className="w-3.5 h-3.5" />
                  <span className="text-sm">{org.user_count} user{org.user_count !== 1 ? "s" : ""}</span>
                </div>
                <div className="flex items-center gap-1.5 text-gray-500">
                  <FileText className="w-3.5 h-3.5" />
                  <span className="text-sm">{org.meeting_count} meeting{org.meeting_count !== 1 ? "s" : ""}</span>
                </div>
              </div>

              {/* Billing & usage snapshot — placeholder ahead of the real Stripe connection */}
              <div className="flex items-center gap-2 mb-2">
                <TierBadge tier={org.pricing_tier} />
                <StripeStatusBadge status={org.stripe_subscription_status} />
                {org.is_trial && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-700">
                    <Clock className="w-3 h-3" /> Trial
                  </span>
                )}
              </div>
              <div className="mb-4 p-2.5 bg-[#F8F9FA] rounded-lg">
                <UsageBar org={org} />
                {org.stripe_current_period_end && (
                  <p className={`text-[11px] mt-1.5 ${STRIPE_STATUS_BAD.has(org.stripe_subscription_status) ? "text-red-600 font-semibold" : "text-gray-400"}`}>
                    Next payment: {new Date(org.stripe_current_period_end).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}
                  </p>
                )}
              </div>

              <div className="flex items-center gap-2">
                <button
                  data-testid={`manage-org-${org.id}`}
                  onClick={() => navigate(`/super-admin/orgs/${org.id}`)}
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
                <JurisdictionFields
                  idPrefix="org"
                  jurisdiction={orgForm.jurisdiction}
                  serviceType={orgForm.service_type}
                  onJurisdictionChange={v => setOrgForm(f => ({ ...f, jurisdiction: v }))}
                  onServiceTypeChange={v => setOrgForm(f => ({ ...f, service_type: v }))}
                />
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
                <JurisdictionFields
                  idPrefix="edit-org"
                  jurisdiction={editOrgForm.jurisdiction}
                  serviceType={editOrgForm.service_type}
                  onJurisdictionChange={v => setEditOrgForm(f => ({ ...f, jurisdiction: v }))}
                  onServiceTypeChange={v => setEditOrgForm(f => ({ ...f, service_type: v }))}
                />
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

    </div>
    </Layout>
  );
}

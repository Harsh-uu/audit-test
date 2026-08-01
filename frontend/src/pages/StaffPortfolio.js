import React, { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import {
  ArrowLeft, Shield, Award, FileText, Download, Loader,
  CheckCircle, Clock, ChevronRight, ChevronDown, TrendingUp, User, Check, FileUp, ExternalLink
} from "lucide-react";

const CONF_CONFIG = {
  likely_evidence: { label: "Likely", dot: "bg-emerald-500", bar: "bg-emerald-500" },
  needs_review: { label: "Needs Review", dot: "bg-amber-400", bar: "bg-amber-400" },
  not_enough_evidence: { label: "Insufficient", dot: "bg-gray-300", bar: "bg-gray-300" },
};

function ConfidenceDots({ likely, review }) {
  const total = likely + review;
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {likely > 0 && (
        <span className="inline-flex items-center gap-1 text-xs bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-full px-2 py-0.5">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
          {likely} likely
        </span>
      )}
      {review > 0 && (
        <span className="inline-flex items-center gap-1 text-xs bg-amber-50 text-amber-700 border border-amber-200 rounded-full px-2 py-0.5">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-400"></span>
          {review} needs review
        </span>
      )}
    </div>
  );
}

function MeetingChips({ refs }) {
  if (!refs?.length) return null;
  const sorted = [...refs].sort((a, b) => (b.date || "").localeCompare(a.date || ""));
  return (
    <div className="flex flex-wrap gap-1 mt-1.5">
      {sorted.map((r, i) => (
        <span key={i} className="text-xs bg-gray-100 text-gray-500 rounded px-1.5 py-0.5">
          {r.date ? r.date.slice(0, 10) : "—"}
        </span>
      ))}
    </div>
  );
}

function EvidenceStandardCard({ item, typeColor }) {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const ref = item.regulation_ref || item.standard_ref || item.criterion_ref || "";
  const name = item.regulation_name || item.standard_name || item.criterion_name || "";
  const sub = item.key_questions?.length
    ? item.key_questions.join(" · ")
    : item.outcome_ref
    ? `Outcome ${item.outcome_ref}: ${item.outcome_name || ""}`
    : item.document_name || "";

  return (
    <div className={`border rounded-lg overflow-hidden mb-2.5 ${typeColor.border}`} data-testid={`standard-card-${ref}`}>
      <button
        className={`w-full flex items-start justify-between p-3 text-left ${typeColor.bg} hover:opacity-90 transition-opacity`}
        onClick={() => setOpen(o => !o)}
      >
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold text-gray-800 truncate">
            <span className={`font-bold ${typeColor.text}`}>{ref}</span>
            {name && <span className="font-normal text-gray-700"> — {name}</span>}
          </p>
          {sub && <p className="text-xs text-gray-500 mt-0.5 truncate">{sub}</p>}
          <div className="mt-1.5">
            <ConfidenceDots likely={item.likely_count} review={item.needs_review_count} />
          </div>
        </div>
        <span className={`ml-3 flex-shrink-0 text-xs font-bold rounded-full w-6 h-6 flex items-center justify-center ${typeColor.badge}`}>
          {item.evidence_count}
        </span>
      </button>
      {open && (
        <div className="px-3 pb-3 pt-2 bg-white border-t border-gray-100">
          <MeetingChips refs={item.meeting_refs} />
          {item.latest_excerpt && (
            <div className="mt-2">
              <blockquote className="border-l-2 border-gray-200 pl-2.5 text-xs text-gray-500 italic leading-relaxed">
                "{item.latest_excerpt}"
              </blockquote>
              {item.source_meeting_id && (
                <button
                  onClick={() => navigate(`/meetings/${item.source_meeting_id}/report`, {
                    state: { highlightExcerpt: item.latest_excerpt, initialTab: "transcript" }
                  })}
                  className="mt-1.5 flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 transition-colors"
                  data-testid={`view-in-transcript-btn-${ref}`}
                >
                  <ExternalLink className="w-3 h-3" />
                  View in transcript
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const TYPE_COLORS = {
  cqc: {
    bg: "bg-purple-50", border: "border-purple-100", text: "text-purple-700",
    badge: "bg-purple-100 text-purple-700",
  },
  care_cert: {
    bg: "bg-blue-50", border: "border-blue-100", text: "text-blue-700",
    badge: "bg-blue-100 text-blue-700",
  },
  custom: {
    bg: "bg-teal-50", border: "border-teal-100", text: "text-teal-700",
    badge: "bg-teal-100 text-teal-700",
  },
};

// ── Care Certificate grouped view with sub-outcome expansion ─────────────────
function CareCertGroupedView({ items, ccStandards }) {
  const [openStds, setOpenStds] = useState({});
  const [showGaps, setShowGaps] = useState({});

  // Group items by standard_ref, preserve numeric order
  const grouped = {};
  for (const item of items) {
    const sr = item.standard_ref;
    if (!grouped[sr]) grouped[sr] = { standardRef: sr, standardName: item.standard_name, items: [] };
    grouped[sr].items.push(item);
  }

  const sortedRefs = Object.keys(grouped).sort((a, b) => {
    const numA = parseInt((a.match(/\d+/) || [0])[0]);
    const numB = parseInt((b.match(/\d+/) || [0])[0]);
    return numA - numB;
  });

  return (
    <div data-testid="care-cert-grouped-view">
      {sortedRefs.map(stdRef => {
        const group = grouped[stdRef];
        const stdDef = ccStandards.find(s => s.reference === stdRef);
        const allSubs = stdDef?.sub_outcomes || [];
        const evidencedRefs = new Set(group.items.map(i => i.outcome_ref).filter(Boolean));
        const gapSubs = allSubs.filter(s => !evidencedRefs.has(s.ref));
        const coveredCount = allSubs.length > 0 ? allSubs.filter(s => evidencedRefs.has(s.ref)).length : evidencedRefs.size;
        const totalSubs = allSubs.length;
        const isOpen = openStds[stdRef] !== false; // default open
        const isShowingGaps = showGaps[stdRef];

        return (
          <div
            key={stdRef}
            className="border border-blue-100 rounded-lg overflow-hidden mb-3"
            data-testid={`cc-group-${stdRef.replace(/\s/g, '-')}`}
          >
            {/* Standard header */}
            <button
              className="w-full flex items-center justify-between p-3 bg-blue-50 hover:bg-blue-100 transition-colors text-left"
              onClick={() => setOpenStds(s => ({ ...s, [stdRef]: !isOpen }))}
            >
              <div className="flex items-center gap-2 min-w-0">
                {isOpen
                  ? <ChevronDown className="w-3.5 h-3.5 text-blue-600 flex-shrink-0" />
                  : <ChevronRight className="w-3.5 h-3.5 text-blue-600 flex-shrink-0" />}
                <span className="text-xs font-semibold text-blue-800 flex-shrink-0">{stdRef}</span>
                <span className="text-xs text-gray-600 truncate">{group.standardName}</span>
              </div>
              <div className="flex-shrink-0 ml-2">
                {totalSubs > 0 ? (
                  <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                    coveredCount === totalSubs ? "bg-emerald-100 text-emerald-700"
                    : coveredCount > 0 ? "bg-amber-100 text-amber-700"
                    : "bg-gray-100 text-gray-500"
                  }`}>
                    {coveredCount}/{totalSubs}
                  </span>
                ) : (
                  <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">
                    {group.items.reduce((s, i) => s + i.evidence_count, 0)} items
                  </span>
                )}
              </div>
            </button>

            {isOpen && (
              <div className="bg-white px-3 py-2">
                {/* Evidenced sub-outcomes */}
                {group.items.map(item => (
                  <div
                    key={item.outcome_ref || item.standard_ref}
                    className="flex items-start gap-2 py-2 border-b border-gray-50 last:border-0"
                    data-testid={`cc-sub-${(item.outcome_ref || item.standard_ref).replace(/\./g, '-')}`}
                  >
                    <span className="w-4 h-4 rounded-full bg-emerald-100 flex items-center justify-center flex-shrink-0 mt-0.5">
                      <Check className="w-2.5 h-2.5 text-emerald-600" />
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-gray-800">
                        {item.outcome_ref && (
                          <span className="text-emerald-700 font-semibold mr-1">{item.outcome_ref}</span>
                        )}
                        {item.outcome_name}
                      </p>
                      <div className="mt-1 flex items-center gap-2 flex-wrap">
                        <ConfidenceDots likely={item.likely_count} review={item.needs_review_count} />
                        <span className="text-xs text-gray-400">
                          {item.evidence_count} evidence item{item.evidence_count !== 1 ? "s" : ""}
                        </span>
                      </div>
                      {item.meeting_refs?.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-1">
                          {item.meeting_refs.slice(0, 4).map((r, i) => (
                            <span key={i} className="text-xs bg-gray-100 text-gray-500 rounded px-1.5 py-0.5">
                              {r.date ? r.date.slice(0, 10) : "—"}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ))}

                {/* Gap sub-outcomes (collapsible) */}
                {gapSubs.length > 0 && (
                  <div className="mt-1">
                    <button
                      className="w-full text-left text-xs text-gray-400 hover:text-gray-600 py-1.5 flex items-center gap-1"
                      onClick={() => setShowGaps(s => ({ ...s, [stdRef]: !s[stdRef] }))}
                    >
                      {isShowingGaps
                        ? <ChevronDown className="w-3 h-3" />
                        : <ChevronRight className="w-3 h-3" />}
                      {gapSubs.length} outcome{gapSubs.length !== 1 ? "s" : ""} not yet evidenced
                    </button>
                    {isShowingGaps && gapSubs.map(sub => (
                      <div key={sub.ref} className="flex items-start gap-2 py-1.5 opacity-50">
                        <span className="w-4 h-4 rounded-full bg-gray-100 flex items-center justify-center flex-shrink-0 mt-0.5">
                          <span className="w-1.5 h-1.5 rounded-full bg-gray-300" />
                        </span>
                        <p className="text-xs text-gray-500 leading-relaxed">
                          <span className="font-medium mr-1">{sub.ref}</span>{sub.desc}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default function StaffPortfolio() {
  const { userId } = useParams();
  const { getAuthConfig, API, user: me } = useAuth();
  const navigate = useNavigate();
  const [portfolio, setPortfolio] = useState(null);
  const [loading, setLoading] = useState(true);
  const [evidenceTab, setEvidenceTab] = useState("cqc");
  const [exporting, setExporting] = useState(false);
  const [ccStandards, setCcStandards] = useState([]);
  const [docUploads, setDocUploads] = useState([]);

  const effectiveUserId = userId || me?.id;
  const canViewUploads = me?.role === "admin" || me?.role === "manager";

  const fetchPortfolio = useCallback(async () => {
    if (!effectiveUserId) return;
    try {
      const { data } = await axios.get(`${API}/portfolio/${effectiveUserId}`, getAuthConfig());
      setPortfolio(data);
      // Auto-select first tab with data
      if (!data.cqc_summary?.length && data.care_cert_summary?.length) setEvidenceTab("care_cert");
      else if (!data.cqc_summary?.length && !data.care_cert_summary?.length && data.custom_summary?.length) setEvidenceTab("custom");
    } catch (err) {
      console.error("Portfolio load failed", err);
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveUserId, API]);

  useEffect(() => { fetchPortfolio(); }, [fetchPortfolio]);

  useEffect(() => {
    axios.get(`${API}/admin/standards`, { ...getAuthConfig(), params: { type: "care_cert" } })
      .then(r => setCcStandards(r.data))
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!canViewUploads || !effectiveUserId) return;
    axios.get(`${API}/doc-uploads/?staff_id=${effectiveUserId}`, getAuthConfig())
      .then(r => setDocUploads(r.data))
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveUserId, canViewUploads]);

  const exportPdf = async () => {
    setExporting(true);
    try {
      const token = localStorage.getItem("supervision_token");
      const resp = await fetch(`${API}/portfolio/${effectiveUserId}/export-pdf`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) throw new Error(await resp.text());
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `portfolio_${portfolio?.user?.name?.replace(/\s/g, "_") || "staff"}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert("Export failed: " + err.message);
    } finally {
      setExporting(false);
    }
  };

  if (loading) {
    return (
      <Layout>
        <div className="flex items-center justify-center h-full py-24">
          <div className="flex items-center gap-3 text-gray-500">
            <div className="w-5 h-5 border-2 border-[#1E3A8A] border-t-transparent rounded-full spin"></div>
            <span className="text-sm">Loading portfolio…</span>
          </div>
        </div>
      </Layout>
    );
  }

  if (!portfolio) {
    return <Layout><div className="p-8 text-center text-gray-500">Portfolio not found</div></Layout>;
  }

  const { user, stats, cqc_summary, care_cert_summary, custom_summary, meetings } = portfolio;
  const initials = user.name.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
  const totalEvidence = (cqc_summary?.length ? cqc_summary.reduce((s, x) => s + x.evidence_count, 0) : 0)
                      + (care_cert_summary?.length ? care_cert_summary.reduce((s, x) => s + x.evidence_count, 0) : 0)
                      + (custom_summary?.length ? custom_summary.reduce((s, x) => s + x.evidence_count, 0) : 0);

  const evidenceItems = { cqc: cqc_summary, care_cert: care_cert_summary, custom: custom_summary };
  const tabCfg = [
    { key: "cqc", label: "CQC", count: cqc_summary?.length, icon: Shield, color: "text-purple-600" },
    { key: "care_cert", label: "Care Cert", count: care_cert_summary?.length, icon: Award, color: "text-blue-600" },
    { key: "custom", label: "Organisational", count: custom_summary?.length, icon: FileText, color: "text-teal-600" },
  ];

  return (
    <Layout>
      <div className="flex flex-col h-full">
        {/* Top bar */}
        <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between sticky top-0 z-20">
          <div className="flex items-center gap-4">
            <button onClick={() => navigate(-1)} className="text-gray-500 hover:text-gray-700">
              <ArrowLeft className="w-4 h-4" />
            </button>
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-full bg-[#1E3A8A] flex items-center justify-center text-white text-sm font-semibold flex-shrink-0">
                {initials}
              </div>
              <div>
                <h1 className="text-base font-semibold text-gray-900 font-display">
                  {user.name}
                </h1>
                <p className="text-xs text-gray-500 capitalize">{user.role} · {user.email}</p>
                {(user.setting_name || user.team_name) && (
                  <div className="flex items-center gap-2 mt-1">
                    {user.setting_name && (
                      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 bg-blue-50 border border-blue-200 text-blue-700 rounded-full" data-testid="setting-badge">
                        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" /><path strokeLinecap="round" strokeLinejoin="round" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
                        {user.setting_name}
                      </span>
                    )}
                    {user.team_name && (
                      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 bg-indigo-50 border border-indigo-200 text-indigo-700 rounded-full" data-testid="team-badge">
                        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
                        {user.team_name}
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
          <button
            onClick={exportPdf}
            disabled={exporting || stats.total_meetings === 0}
            className="flex items-center gap-2 bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors disabled:opacity-50"
            data-testid="export-portfolio-btn"
          >
            <Download className="w-4 h-4" />
            {exporting ? "Generating…" : "Export Portfolio PDF"}
          </button>
        </div>

        {/* Stats bar */}
        <div className="bg-white border-b border-gray-100 px-6 py-3">
          <div className="flex items-center gap-6">
            {[
              { label: "Supervision Sessions", value: stats.total_meetings, color: "text-[#1E3A8A]" },
              { label: "CQC Regulations", value: stats.cqc_count, color: "text-purple-600" },
              { label: "Care Cert Standards", value: stats.care_cert_count, color: "text-blue-600" },
              { label: "Organisational Criteria", value: stats.custom_count, color: "text-teal-600" },
              { label: "Total Evidence Items", value: totalEvidence, color: "text-gray-700" },
            ].map(({ label, value, color }) => (
              <div key={label} className="flex flex-col" data-testid={`stat-${label.toLowerCase().replace(/\s/g, '-')}`}>
                <span className={`text-xl font-bold ${color}`}>{value}</span>
                <span className="text-xs text-gray-400">{label}</span>
              </div>
            ))}
            {stats.last_meeting_date && (
              <div className="ml-auto flex flex-col items-end">
                <span className="text-xs text-gray-400">Last supervision</span>
                <span className="text-xs font-medium text-gray-600">
                  {new Date(stats.last_meeting_date).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}
                </span>
              </div>
            )}
          </div>
        </div>

        {/* Always-visible two-column grid */}
        <div className="flex-1 grid grid-cols-1 lg:grid-cols-12 gap-0 overflow-hidden">

          {/* Left: Evidence Standards (or empty state) */}
          <div className="lg:col-span-7 border-r border-gray-200 flex flex-col overflow-hidden">
            {stats.total_meetings === 0 ? (
              <div className="flex-1 flex items-center justify-center text-center py-24 text-gray-400">
                <div>
                  <TrendingUp className="w-10 h-10 mx-auto mb-3 opacity-30" />
                  <p className="font-medium text-gray-500">No signed-off supervision records yet</p>
                  <p className="text-sm mt-1">Evidence will appear here once meetings are signed off</p>
                </div>
              </div>
            ) : (
              <>
            {/* Tab row */}
            <div className="border-b border-gray-200 px-6 py-3 flex items-center gap-1">
              {tabCfg.map(({ key, label, count, icon: Icon, color }) => (
                <button
                  key={key}
                  onClick={() => setEvidenceTab(key)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                    evidenceTab === key
                      ? "bg-gray-100 text-gray-900"
                      : "text-gray-500 hover:text-gray-700"
                  }`}
                  data-testid={`evidence-tab-${key}`}
                >
                  <Icon className={`w-3.5 h-3.5 ${color}`} />
                  {label}
                  {count > 0 && (
                    <span className={`text-xs rounded-full px-1.5 ${evidenceTab === key ? "bg-[#1E3A8A] text-white" : "bg-gray-200 text-gray-600"}`}>
                        {count}
                      </span>
                    )}
                  </button>
                ))}
              </div>

              <div className="flex-1 overflow-y-auto p-5">
                {evidenceItems[evidenceTab]?.length === 0 ? (
                  <div className="text-center py-12 text-gray-400">
                    <p className="text-sm">No {tabCfg.find(t => t.key === evidenceTab)?.label} evidence recorded yet</p>
                  </div>
                ) : evidenceTab === "care_cert" ? (
                  <CareCertGroupedView items={care_cert_summary} ccStandards={ccStandards} />
                ) : (
                  <div data-testid="evidence-standards-list">
                    {evidenceItems[evidenceTab].map((item, i) => (
                      <EvidenceStandardCard
                        key={item.regulation_ref || item.standard_ref || item.criterion_ref || i}
                        item={item}
                        typeColor={TYPE_COLORS[evidenceTab]}
                      />
                    ))}
                  </div>
                )}
              </div>
            </>
            )}
          </div>

            {/* Right: Meeting History + Imported Documents */}
            <div className="lg:col-span-5 bg-[#F8F9FA] overflow-y-auto" style={{ maxHeight: "calc(100vh - 160px)" }}>
              <div className="p-4">
                <h2 className="text-sm font-semibold text-gray-900 mb-3 font-display">
                  Supervision History
                </h2>
                <div className="space-y-2" data-testid="meeting-history-list">
                  {meetings.map(m => (
                    <div
                      key={m.id}
                      onClick={() => navigate(`/meetings/${m.id}/report`)}
                      className="bg-white border border-gray-200 rounded-lg p-3.5 cursor-pointer hover:shadow-md hover:-translate-y-0.5 transition-all duration-150"
                      data-testid={`portfolio-meeting-${m.id}`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-gray-900 truncate">{m.title}</p>
                          <p className="text-xs text-gray-400 mt-0.5">
                            {m.date ? new Date(m.date).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "—"}
                            {m.sign_off_manager_name && ` · ${m.sign_off_manager_name}`}
                          </p>
                          <div className="flex items-center gap-2 mt-1.5">
                            {m.cqc_count > 0 && (
                              <span className="text-xs bg-purple-50 text-purple-700 border border-purple-100 rounded-full px-2 py-0.5">
                                {m.cqc_count} CQC
                              </span>
                            )}
                            {m.care_cert_count > 0 && (
                              <span className="text-xs bg-blue-50 text-blue-700 border border-blue-100 rounded-full px-2 py-0.5">
                                {m.care_cert_count} Care Cert
                              </span>
                            )}
                            {m.custom_count > 0 && (
                              <span className="text-xs bg-teal-50 text-teal-700 border border-teal-100 rounded-full px-2 py-0.5">
                                {m.custom_count} Custom
                              </span>
                            )}
                          </div>
                        </div>
                        <ChevronRight className="w-4 h-4 text-gray-400 flex-shrink-0 mt-0.5" />
                      </div>
                    </div>
                  ))}
                </div>

                {/* Imported Documents */}
                {canViewUploads && docUploads.length > 0 && (
                  <div className="mt-5">
                    <div className="flex items-center justify-between mb-3">
                      <h2 className="text-sm font-semibold text-gray-900 font-display flex items-center gap-2">
                        <FileUp className="w-3.5 h-3.5 text-indigo-600" />
                        Imported Documents
                      </h2>
                      <button
                        onClick={() => navigate("/upload-supervision")}
                        className="text-xs text-indigo-600 hover:underline font-medium"
                        data-testid="add-import-btn"
                      >
                        + Import
                      </button>
                    </div>
                    <div className="space-y-2" data-testid="imported-docs-list">
                      {docUploads.map(u => (
                        <div
                          key={u.id}
                          onClick={() => u.status === "done" && navigate(`/doc-uploads/${u.id}`)}
                          className={`bg-white border border-indigo-100 rounded-lg p-3 flex items-start gap-3 transition-all duration-150 ${u.status === "done" ? "cursor-pointer hover:shadow-md hover:-translate-y-0.5" : "opacity-70"}`}
                          data-testid={`portfolio-upload-${u.id}`}
                        >
                          <FileText className="w-4 h-4 text-indigo-500 flex-shrink-0 mt-0.5" />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-gray-900 truncate">{u.label || u.filename}</p>
                            <p className="text-xs text-gray-400 mt-0.5">
                              {u.meeting_date}
                              {u.uploader_name && ` · ${u.uploader_name}`}
                            </p>
                            {u.status === "done" && (
                              <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                                {(u.cqc_mappings?.length || 0) > 0 && (
                                  <span className="text-xs bg-purple-50 text-purple-700 border border-purple-100 rounded-full px-2 py-0.5">
                                    {u.cqc_mappings.length} CQC
                                  </span>
                                )}
                                {(u.care_cert_mappings?.length || 0) > 0 && (
                                  <span className="text-xs bg-blue-50 text-blue-700 border border-blue-100 rounded-full px-2 py-0.5">
                                    {u.care_cert_mappings.length} Care Cert
                                  </span>
                                )}
                                <span className="text-xs bg-indigo-50 text-indigo-600 border border-indigo-100 rounded-full px-2 py-0.5 font-medium">
                                  Document Import
                                </span>
                              </div>
                            )}
                            {u.status === "processing" && (
                              <span className="text-xs text-amber-600 flex items-center gap-1 mt-1">
                                <Clock className="w-3 h-3 animate-pulse" /> Scanning…
                              </span>
                            )}
                          </div>
                          {u.status === "done" && <ChevronRight className="w-4 h-4 text-gray-400 flex-shrink-0 mt-0.5" />}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {canViewUploads && docUploads.length === 0 && (
                  <div className="mt-5">
                    <div className="flex items-center justify-between mb-2">
                      <h2 className="text-sm font-semibold text-gray-900 font-display flex items-center gap-2">
                        <FileUp className="w-3.5 h-3.5 text-indigo-600" />
                        Imported Documents
                      </h2>
                    </div>
                    <button
                      onClick={() => navigate("/upload-supervision")}
                      className="w-full border border-dashed border-indigo-200 bg-indigo-50/40 hover:bg-indigo-50 text-indigo-600 text-xs font-medium rounded-lg p-3 flex items-center justify-center gap-2 transition-colors"
                      data-testid="import-supervision-prompt"
                    >
                      <FileUp className="w-3.5 h-3.5" /> Import a previous supervision document
                    </button>
                  </div>
                )}
              </div>
            </div>

          </div>
      </div>
    </Layout>
  );
}

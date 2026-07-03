import React, { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import {
  Grid3x3, TrendingUp, AlertTriangle, ClipboardList, Shield, Award,
  FileText, Users, RefreshCw, ChevronRight, Building2, Check, X, Download
} from "lucide-react";

// ── Cell rendering ──────────────────────────────────────────────────────────
const CELL_CFG = {
  evidenced:    { bg: "bg-emerald-100", border: "border-emerald-300", label: "All outcomes evidenced" },
  partial:      { bg: "bg-amber-50",    border: "border-amber-200",   label: "Partially evidenced" },
  needs_review: { bg: "bg-amber-50",    border: "border-amber-200",   label: "Needs review" },
  gap:          { bg: "bg-gray-50",     border: "border-gray-100",    label: "Gap — no evidence" },
};

function MatrixCell({ cell }) {
  const status = cell?.status || "gap";

  if (status === "evidenced") {
    return (
      <div
        title={cell?.total_sub ? `All ${cell.total_sub} outcomes evidenced` : "All outcomes evidenced"}
        className="w-10 h-10 flex items-center justify-center rounded border bg-emerald-100 border-emerald-300 transition-opacity hover:opacity-80 cursor-default"
      >
        <svg className="w-4 h-4 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      </div>
    );
  }

  if (status === "partial") {
    const covered = cell?.covered_sub ?? 0;
    const total = cell?.total_sub ?? 0;
    return (
      <div
        title={`${covered}/${total} outcomes evidenced (${cell?.pct ?? 0}%)`}
        className="w-10 h-10 flex items-center justify-center rounded border bg-amber-50 border-amber-200 transition-opacity hover:opacity-80 cursor-default"
      >
        <span className="text-[9px] font-bold text-amber-600 leading-none">{covered}/{total}</span>
      </div>
    );
  }

  if (status === "needs_review") {
    return (
      <div
        title={`${cell?.review || 0} item(s) need review`}
        className="w-10 h-10 flex items-center justify-center rounded border bg-amber-50 border-amber-200 transition-opacity hover:opacity-80 cursor-default"
      >
        <span className="w-2.5 h-2.5 rounded-full bg-amber-400" />
      </div>
    );
  }

  // gap
  return (
    <div
      title="No evidence"
      className="w-10 h-10 flex items-center justify-center rounded border bg-gray-50 border-gray-100 cursor-default"
    >
      <span className="w-2 h-2 rounded-full bg-gray-200" />
    </div>
  );
}

// ── Shorten a standard ref for the column header ─────────────────────────────
function shortRef(ref) {
  if (!ref) return ref;
  return ref
    .replace(/CQC\s+Reg\s*/i, "Reg ")   // "CQC Reg 12" → "Reg 12"
    .replace(/Regulation\s+/i, "Reg ")   // "Regulation 9" → "Reg 9"
    .replace(/Standard\s+/i, "Std ")     // "Standard 2" → "Std 2"
    .replace(/:.*$/, "")                  // Strip ": name" suffix
    .trim();
}

// ── Evidence Matrix ─────────────────────────────────────────────────────────
function MatrixView({ matrix, ccStandards = [], onCellClick }) {
  const [matrixTab, setMatrixTab] = useState("cqc");

  const tabs = [
    { key: "cqc",      label: "CQC",             icon: Shield, color: "text-purple-600" },
    { key: "care_cert",label: "Care Certificate", icon: Award,  color: "text-blue-600"  },
    { key: "custom",   label: "Organisational",   icon: FileText, color: "text-teal-600" },
  ];

  const data = matrix[matrixTab] || { standards: [], rows: [] };

  const tabCounts = {
    cqc:       matrix.cqc?.standards?.length ?? 0,
    care_cert: matrix.care_cert?.standards?.length ?? 0,
    custom:    matrix.custom?.standards?.length ?? 0,
  };

  return (
    <div>
      {/* Sub-tabs */}
      <div className="flex items-center gap-1 mb-4">
        {tabs.map(({ key, label, icon: Icon, color }) => (
          <button
            key={key}
            onClick={() => setMatrixTab(key)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
              matrixTab === key ? "bg-[#1E3A8A] text-white" : "text-gray-600 hover:bg-gray-100"
            }`}
            data-testid={`matrix-tab-${key}`}
          >
            <Icon className={`w-3.5 h-3.5 ${matrixTab === key ? "text-white" : color}`} />
            {label}
            <span className={`text-xs rounded-full px-1.5 ${matrixTab === key ? "bg-white/20 text-white" : "bg-gray-100 text-gray-500"}`}>
              {tabCounts[key]}
            </span>
          </button>
        ))}
      </div>

      {data.standards.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          <Grid3x3 className="w-10 h-10 mx-auto mb-2 opacity-30" />
          <p className="text-sm">No evidence mapped yet for these standards</p>
        </div>
      ) : (
        <>
          {/* Scrollable matrix table */}
          <div className="overflow-x-auto rounded-lg border border-gray-200">
            <table className="border-collapse" style={{ minWidth: "max-content" }}>
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  {/* Frozen staff column */}
                  <th className="sticky left-0 z-10 bg-gray-50 border-r border-gray-200 px-4 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide min-w-[160px]">
                    Staff Member
                  </th>
                  {data.standards.map(std => (
                    <th key={std.ref} className="px-2 py-2 text-center min-w-[44px]">
                      <div
                        title={`${std.ref} — ${std.name}`}
                        style={{
                          writingMode: "vertical-rl",
                          transform: "rotate(180deg)",
                          height: 76,
                          lineHeight: "1.3",
                          overflow: "hidden",
                          whiteSpace: "nowrap",
                        }}
                        className="text-xs font-semibold text-gray-500 uppercase tracking-wide mx-auto"
                      >
                        {shortRef(std.ref)}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row, ri) => (
                  <tr key={row.staff_id} className={ri % 2 === 0 ? "bg-white" : "bg-gray-50/50"} data-testid={`matrix-row-${row.staff_id}`}>
                    <td className={`sticky left-0 z-10 border-r border-gray-200 px-4 py-2 ${ri % 2 === 0 ? "bg-white" : "bg-gray-50"}`}>
                      <p className="text-sm font-medium text-gray-800 whitespace-nowrap">{row.staff_name}</p>
                    </td>
                    {data.standards.map(std => (
                      <td key={std.ref} className="px-2 py-2 text-center">
                        {matrixTab === "care_cert" ? (
                          <button
                            className="hover:opacity-75 transition-opacity"
                            onClick={() => onCellClick && onCellClick(row, std)}
                            title={`${row.staff_name} — ${std.ref}: click to see outcomes`}
                            data-testid={`cc-cell-${row.staff_id}-${std.ref.replace(/\s/g, '-')}`}
                          >
                            <MatrixCell cell={row.cells[std.ref]} />
                          </button>
                        ) : (
                          <MatrixCell cell={row.cells[std.ref]} />
                        )}
                      </td>
                    ))}
                  </tr>
                ))}

                {/* Coverage summary row */}
                <tr className="border-t-2 border-gray-200 bg-gray-100">
                  <td className="sticky left-0 z-10 bg-gray-100 border-r border-gray-200 px-4 py-2 text-xs font-semibold text-gray-500 uppercase tracking-wide whitespace-nowrap">
                    Team coverage
                  </td>
                  {data.standards.map(std => {
                    const rows = data.rows;
                    // For Care Cert: green only when 100% sub-outcomes covered
                    const fullyEvidenced = rows.filter(r => r.cells[std.ref]?.status === "evidenced").length;
                    const pct = rows.length ? Math.round((fullyEvidenced / rows.length) * 100) : 0;
                    return (
                      <td key={std.ref} className="px-2 py-2 text-center">
                        <span
                          className={`text-xs font-bold ${
                            pct === 100 ? "text-emerald-600" : pct >= 50 ? "text-amber-500" : "text-red-400"
                          }`}
                          title={`${fullyEvidenced}/${rows.length} staff fully evidenced`}
                        >
                          {pct}%
                        </span>
                      </td>
                    );
                  })}
                </tr>
              </tbody>
            </table>
          </div>

          {/* Legend */}
          <div className="flex items-center gap-5 mt-3 px-1 flex-wrap">
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <div className="w-7 h-7 rounded border bg-emerald-100 border-emerald-300 flex items-center justify-center">
                <svg className="w-3.5 h-3.5 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" /></svg>
              </div>
              All outcomes evidenced
            </div>
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <div className="w-7 h-7 rounded border bg-amber-50 border-amber-200 flex items-center justify-center">
                <span className="text-[8px] font-bold text-amber-600">3/8</span>
              </div>
              Partial (shows covered/total)
            </div>
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <div className="w-7 h-7 rounded border bg-gray-50 border-gray-100 flex items-center justify-center">
                <span className="w-2 h-2 rounded-full bg-gray-200" />
              </div>
              No evidence yet
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ── Care Cert Sub-outcome Drill-down Modal ───────────────────────────────────
function CcDrillDownModal({ staffName, stdRef, stdName, cell, ccStandards, onClose }) {
  const std = ccStandards.find(s => s.reference === stdRef);
  const allSubs = std?.sub_outcomes || [];
  const evidencedSet = new Set(cell?.evidenced_refs || []);
  const covered = allSubs.filter(s => evidencedSet.has(s.ref));
  const gaps = allSubs.filter(s => !evidencedSet.has(s.ref));
  const pct = allSubs.length ? Math.round((covered.length / allSubs.length) * 100) : 0;

  return (
    <div
      className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4"
      onClick={onClose}
      data-testid="cc-drilldown-modal"
    >
      <div
        className="bg-white rounded-xl shadow-2xl w-full max-w-lg max-h-[80vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between p-4 border-b border-gray-200">
          <div>
            <p className="text-xs text-blue-600 font-medium">{staffName}</p>
            <h2 className="text-sm font-semibold text-gray-900 mt-0.5">{stdRef} — {stdName}</h2>
          </div>
          <div className="flex items-center gap-3 ml-4 flex-shrink-0">
            <span className={`text-xs font-bold px-2 py-1 rounded-full ${
              covered.length === allSubs.length && allSubs.length > 0
                ? "bg-emerald-100 text-emerald-700"
                : covered.length > 0
                ? "bg-amber-100 text-amber-700"
                : "bg-gray-100 text-gray-500"
            }`}>
              {covered.length}/{allSubs.length} covered
            </span>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600"
              data-testid="close-drilldown-btn"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Progress bar */}
        {allSubs.length > 0 && (
          <div className="px-4 py-2.5 bg-gray-50 border-b border-gray-100">
            <div className="flex items-center gap-2">
              <div className="flex-1 bg-gray-200 rounded-full h-1.5">
                <div
                  className={`h-1.5 rounded-full transition-all ${pct === 100 ? "bg-emerald-500" : "bg-amber-400"}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="text-xs text-gray-500 flex-shrink-0">{pct}%</span>
            </div>
          </div>
        )}

        {/* Sub-outcomes list */}
        <div className="flex-1 overflow-y-auto p-4">
          {allSubs.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-8">No outcomes defined for this standard</p>
          ) : (
            <>
              {covered.length > 0 && (
                <div className="mb-4">
                  <p className="text-xs font-semibold text-emerald-700 uppercase tracking-wide mb-2">
                    Evidenced ({covered.length})
                  </p>
                  <div className="space-y-1.5">
                    {covered.map(sub => (
                      <div key={sub.ref} className="flex items-start gap-2 py-1">
                        <span className="w-4 h-4 rounded-full bg-emerald-100 flex items-center justify-center flex-shrink-0 mt-0.5">
                          <Check className="w-2.5 h-2.5 text-emerald-600" />
                        </span>
                        <p className="text-xs text-gray-800 leading-relaxed">
                          <span className="font-semibold text-emerald-700 mr-1">{sub.ref}</span>
                          {sub.desc}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {gaps.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
                    Not yet evidenced ({gaps.length})
                  </p>
                  <div className="space-y-1.5">
                    {gaps.map(sub => (
                      <div key={sub.ref} className="flex items-start gap-2 py-1 opacity-60">
                        <span className="w-4 h-4 rounded-full bg-gray-100 flex items-center justify-center flex-shrink-0 mt-0.5">
                          <span className="w-1.5 h-1.5 rounded-full bg-gray-300" />
                        </span>
                        <p className="text-xs text-gray-500 leading-relaxed">
                          <span className="font-medium mr-1">{sub.ref}</span>
                          {sub.desc}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Coverage Gap Bar ────────────────────────────────────────────────────────
function GapBar({ gap }) {
  // For Care Cert: show sub-outcome coverage; for CQC/custom: show staff coverage
  const isCc = gap.type === "care_cert" && (gap.total_sub ?? 0) > 0;
  const numerator = isCc ? (gap.covered_sub ?? 0) : gap.covered;
  const denominator = isCc ? gap.total_sub : gap.total;
  const pct = denominator > 0 ? Math.round((numerator / denominator) * 100) : 0;
  const label = isCc
    ? `${numerator}/${denominator} outcomes`
    : `${numerator}/${denominator} staff`;
  const TYPE_COLOR = {
    cqc:       { badge: "bg-purple-100 text-purple-700", bar: "bg-purple-500" },
    care_cert: { badge: "bg-blue-100 text-blue-700",     bar: "bg-blue-500"   },
    custom:    { badge: "bg-teal-100 text-teal-700",     bar: "bg-teal-500"   },
  };
  const c = TYPE_COLOR[gap.type] || TYPE_COLOR.cqc;

  return (
    <div className="mb-3" data-testid={`gap-bar-${gap.ref}`}>
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className={`text-xs px-1.5 py-0.5 rounded font-medium flex-shrink-0 ${c.badge}`}>{gap.ref}</span>
          <span className="text-sm text-gray-700 truncate">{gap.name}</span>
        </div>
        <span className="text-xs text-gray-500 ml-2 flex-shrink-0">{label}</span>
      </div>
      <div className="w-full bg-gray-100 rounded-full h-1.5">
        <div
          className={`h-1.5 rounded-full transition-all duration-500 ${c.bar}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ── Team Themes ─────────────────────────────────────────────────────────────
function ThemesView({ themes }) {
  const { coverage_gaps, common_risks, outstanding_actions } = themes;

  const gapsByType = {
    cqc: coverage_gaps.filter(g => g.type === "cqc"),
    care_cert: coverage_gaps.filter(g => g.type === "care_cert"),
    custom: coverage_gaps.filter(g => g.type === "custom"),
  };

  return (
    <div className="space-y-8">
      {/* Coverage Gaps */}
      <div>
        <div className="flex items-center gap-2 mb-4">
          <TrendingUp className="w-4 h-4 text-[#1E3A8A]" />
          <h3 className="text-sm font-semibold text-gray-900">Standards Coverage Gaps</h3>
          <span className="text-xs text-gray-400">(numerical order)</span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {[
            { key: "cqc",       label: "CQC Regulations",      icon: Shield, color: "text-purple-600" },
            { key: "care_cert", label: "Care Certificate",      icon: Award,  color: "text-blue-600"  },
            { key: "custom",    label: "Organisational",        icon: FileText, color: "text-teal-600" },
          ].map(({ key, label, icon: Icon, color }) => (
            <div key={key} className="bg-white border border-gray-200 rounded-lg p-4" data-testid={`gap-section-${key}`}>
              <div className={`flex items-center gap-1.5 mb-3 text-sm font-semibold ${color}`}>
                <Icon className="w-3.5 h-3.5" />
                {label}
                <span className="ml-auto text-xs font-normal text-gray-400">{gapsByType[key].length} standards</span>
              </div>
              {gapsByType[key].length === 0 ? (
                <p className="text-xs text-gray-400 italic">No standards mapped yet</p>
              ) : (
                <div className="max-h-80 overflow-y-auto pr-1">
                  {gapsByType[key].map(gap => <GapBar key={gap.ref} gap={gap} />)}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Risks + Actions */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Common Risks */}
        <div className="bg-white border border-gray-200 rounded-lg p-4" data-testid="common-risks-panel">
          <div className="flex items-center gap-2 mb-4">
            <AlertTriangle className="w-4 h-4 text-amber-500" />
            <h3 className="text-sm font-semibold text-gray-900">Recurring Risks Across Team</h3>
          </div>
          {common_risks.length === 0 ? (
            <p className="text-sm text-gray-400 italic py-4 text-center">No risks recorded yet</p>
          ) : (
            <ul className="space-y-2.5">
              {common_risks.map((r, i) => (
                <li key={r.text.slice(0, 40)} className="flex items-start gap-3" data-testid={`risk-item-${i}`}>
                  <div className="flex-shrink-0 w-5 h-5 rounded-full bg-amber-100 flex items-center justify-center mt-0.5">
                    <span className="text-xs font-bold text-amber-700">{r.count}</span>
                  </div>
                  <p className="text-sm text-gray-700 leading-snug">{r.text}</p>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Outstanding Actions */}
        <div className="bg-white border border-gray-200 rounded-lg p-4" data-testid="outstanding-actions-panel">
          <div className="flex items-center gap-2 mb-4">
            <ClipboardList className="w-4 h-4 text-rose-500" />
            <h3 className="text-sm font-semibold text-gray-900">Outstanding Actions Across Team</h3>
          </div>
          {outstanding_actions.length === 0 ? (
            <p className="text-sm text-gray-400 italic py-4 text-center">No outstanding actions — great!</p>
          ) : (
            <ul className="space-y-2.5">
              {outstanding_actions.map((a, i) => (
                <li key={a.text.slice(0, 40)} className="flex items-start gap-3" data-testid={`action-item-${i}`}>
                  <div className="flex-shrink-0 w-5 h-5 rounded-full bg-rose-100 flex items-center justify-center mt-0.5">
                    <span className="text-xs font-bold text-rose-700">{a.count}</span>
                  </div>
                  <p className="text-sm text-gray-700 leading-snug">{a.text}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────
export default function TeamInsights() {
  const { getAuthConfig, API, user } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("matrix");
  const [orgStructure, setOrgStructure] = useState({ settings: [] });
  const [orgFilter, setOrgFilter] = useState({ setting_id: "", team_id: "" });
  const [ccStandards, setCcStandards] = useState([]);
  const [drillDown, setDrillDown] = useState(null);

  const load = useCallback(async (filter = {}) => {
    setLoading(true);
    try {
      const params = {};
      if (filter.team_id) params.team_id = filter.team_id;
      else if (filter.setting_id) params.setting_id = filter.setting_id;
      const { data: d } = await axios.get(`${API}/admin/team-insights`, { ...getAuthConfig(), params });
      setData(d);
    } catch (err) {
      console.error("Team insights error", err);
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API]);

  useEffect(() => {
    load(orgFilter);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgFilter]);

  useEffect(() => {
    if (user?.role === "admin" || user?.role === "manager") {
      axios.get(`${API}/org/structure`, getAuthConfig()).then(r => setOrgStructure(r.data)).catch(() => {});
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    axios.get(`${API}/admin/standards`, { ...getAuthConfig(), params: { type: "care_cert" } })
      .then(r => setCcStandards(r.data))
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleCellClick = (row, std) => {
    setDrillDown({
      staffName: row.staff_name,
      stdRef: std.ref,
      stdName: std.name,
      cell: row.cells[std.ref],
    });
  };

  const exportMatrixCSV = () => {
    if (!data?.matrix) return;
    const lines = ["Staff Member,Framework,Standard Ref,Standard Name,Status,Coverage"];
    const frameworkLabel = { cqc: "CQC", care_cert: "Care Certificate", custom: "Organisational" };

    ["cqc", "care_cert", "custom"].forEach(key => {
      const section = data.matrix[key];
      if (!section?.standards?.length) return;
      section.rows.forEach(row => {
        section.standards.forEach(std => {
          const cell = row.cells?.[std.ref];
          const status = cell?.status || "gap";
          let coverage = "0%";
          if (status === "evidenced") coverage = "100%";
          else if (status === "partial") {
            const pct = cell?.pct ?? 0;
            coverage = `${pct}% (${cell?.covered_sub ?? 0}/${cell?.total_sub ?? 0})`;
          } else if (status === "needs_review") coverage = "needs review";
          const esc = s => `"${String(s).replace(/"/g, '""')}"`;
          lines.push([esc(row.staff_name), esc(frameworkLabel[key] || key), esc(std.ref), esc(std.name), esc(status.replace("_", " ")), esc(coverage)].join(","));
        });
      });
    });

    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "team_intelligence.csv"; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Layout>
      <div className="flex flex-col h-full">
        {/* Header */}
        <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between sticky top-0 z-20">
          <div>
            <h1 className="text-base font-semibold text-gray-900 font-display">
              Team Intelligence
            </h1>
            {data && (
              <p className="text-xs text-gray-500 mt-0.5">
                {data.staff_count} staff · {data.meeting_count} signed-off sessions
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            {orgStructure.settings?.length > 0 && (
              <div className="flex items-center gap-2" data-testid="org-filter">
                <Building2 className="w-3.5 h-3.5 text-gray-400" />
                <select
                  value={orgFilter.setting_id}
                  onChange={e => setOrgFilter({ setting_id: e.target.value, team_id: "" })}
                  className="px-2 py-1 border border-gray-300 rounded text-xs bg-white focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
                  data-testid="insights-setting-filter"
                >
                  <option value="">All Settings</option>
                  {orgStructure.settings.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
                {orgFilter.setting_id && (
                  <select
                    value={orgFilter.team_id}
                    onChange={e => setOrgFilter(f => ({ ...f, team_id: e.target.value }))}
                    className="px-2 py-1 border border-gray-300 rounded text-xs bg-white focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
                    data-testid="insights-team-filter"
                  >
                    <option value="">All Teams</option>
                    {(orgStructure.settings.find(s => s.id === orgFilter.setting_id)?.teams || []).map(t => (
                      <option key={t.id} value={t.id}>{t.name}</option>
                    ))}
                  </select>
                )}
              </div>
            )}
            <button
              onClick={exportMatrixCSV}
              disabled={!data || loading}
              className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 px-3 py-1.5 rounded border border-gray-200 hover:bg-gray-50 disabled:opacity-50"
              data-testid="export-csv-btn"
              title="Export matrix as CSV spreadsheet"
            >
              <Download className="w-3.5 h-3.5" />
              Export CSV
            </button>
            <button
              onClick={() => load(orgFilter)}
              disabled={loading}
              className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 px-3 py-1.5 rounded border border-gray-200 hover:bg-gray-50 disabled:opacity-50"
              data-testid="refresh-insights-btn"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>
        </div>

        {/* Main tabs */}
        <div className="bg-white border-b border-gray-100 px-6">
          <div className="flex gap-1 pt-1">
            {[
              { key: "matrix", label: "Evidence Matrix", icon: Grid3x3 },
              { key: "themes", label: "Team Themes",     icon: TrendingUp },
            ].map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                  tab === key
                    ? "border-[#1E3A8A] text-[#1E3A8A]"
                    : "border-transparent text-gray-500 hover:text-gray-700"
                }`}
                data-testid={`main-tab-${key}`}
              >
                <Icon className="w-4 h-4" />
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="flex items-center justify-center h-48">
              <div className="flex items-center gap-3 text-gray-400">
                <div className="w-5 h-5 border-2 border-[#1E3A8A] border-t-transparent rounded-full animate-spin" />
                <span className="text-sm">Aggregating team data…</span>
              </div>
            </div>
          ) : !data ? (
            <div className="text-center py-16 text-gray-400 text-sm">Failed to load insights</div>
          ) : data.staff_count === 0 ? (
            <div className="text-center py-16">
              <Users className="w-10 h-10 mx-auto mb-3 text-gray-300" />
              <p className="text-gray-500 font-medium">No staff members found</p>
              <p className="text-sm text-gray-400 mt-1">Add staff in the Admin panel to see team insights</p>
            </div>
          ) : (
            <>
              {tab === "matrix" && (
                <MatrixView
                  matrix={data.matrix}
                  ccStandards={ccStandards}
                  onCellClick={handleCellClick}
                />
              )}
              {tab === "themes" && <ThemesView themes={data.themes} />}
            </>
          )}
        </div>
      </div>
      {drillDown && (
        <CcDrillDownModal
          {...drillDown}
          ccStandards={ccStandards}
          onClose={() => setDrillDown(null)}
        />
      )}
    </Layout>
  );
}

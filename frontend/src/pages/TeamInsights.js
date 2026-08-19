import React, { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import axios from "axios";
import { cachedGet } from "@/utils/apiCache";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import { Skeleton } from "@/components/ui/skeleton";
import { UkDatePicker } from "@/components/ui/uk-date-picker";
import {
  Grid3x3, TrendingUp, AlertTriangle, ClipboardList, Shield, Award,
  FileText, Users, RefreshCw, ChevronRight, Building2, Check, X, Download,
  BookOpen, Square, CheckSquare, Search, ExternalLink,
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
    { key: "care_cert",label: "Induction", icon: Award,  color: "text-blue-600"  },
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
            { key: "care_cert", label: "Induction",             icon: Award,  color: "text-blue-600"  },
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

    </div>
  );
}

// ── AchievementsTimeline ─────────────────────────────────────────────────────
// "New" = recorded within 7 days AND meeting not yet signed off
function isNew(item) {
  const sevenDaysAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
  const notSignedOff = !["signed_off", "shared"].includes(item.meeting_status || "");
  return notSignedOff && (item.meeting_date || "") >= sevenDaysAgo;
}

const SHOW_LIMIT = 3;

function AchievementsTimeline({ items, search, staffFilter, onSearchChange, onStaffFilterChange, staffList = [] }) {
  const navigate = useNavigate();
  const [expandedPersons, setExpandedPersons] = useState(() => new Set());
  const [expandedItems, setExpandedItems] = useState(() => new Set());
  const [showAllFor, setShowAllFor] = useState(() => new Set());

  // Filter
  const filtered = items.filter(item => {
    if (staffFilter !== "all" && !(item.staff_names || "").includes(staffFilter)) return false;
    if (search) {
      const q = search.toLowerCase();
      if (!item.text.toLowerCase().includes(q) && !(item.staff_names || "").toLowerCase().includes(q)) return false;
    }
    return true;
  });

  // Group by individual staff name (one achievement may cover multiple people)
  const groupMap = new Map();
  filtered.forEach(item => {
    const names = (item.staff_names || "Unknown").split(/,\s*/);
    names.forEach(name => {
      const key = name.trim() || "Unknown";
      if (!groupMap.has(key)) groupMap.set(key, []);
      // avoid duplicate if name appears twice
      if (!groupMap.get(key).find(e => e.id === item.id && e.meeting_id === item.meeting_id)) {
        groupMap.get(key).push(item);
      }
    });
  });

  // Sort groups: most recent first; within group newest first
  const groups = [...groupMap.entries()].sort((a, b) => {
    const aDate = (a[1][0]?.meeting_date || "");
    const bDate = (b[1][0]?.meeting_date || "");
    return bDate.localeCompare(aDate);
  });

  // Auto-expand first person on load
  useEffect(() => {
    if (groups.length > 0) setExpandedPersons(new Set([groups[0][0]]));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items.length]);

  const togglePerson = name => setExpandedPersons(prev => {
    const next = new Set(prev);
    next.has(name) ? next.delete(name) : next.add(name);
    return next;
  });

  const toggleItem = id => setExpandedItems(prev => {
    const next = new Set(prev);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });

  const newCount = items.filter(isNew).length;
  const thisMonth = (() => {
    const ym = new Date().toISOString().slice(0, 7);
    return items.filter(i => (i.meeting_date || "").startsWith(ym)).length;
  })();

  if (filtered.length === 0 && !search && staffFilter === "all") {
    return (
      <div className="text-center py-16">
        <Award className="w-10 h-10 mx-auto mb-3 text-gray-200" />
        <p className="text-gray-500 font-medium text-sm">No achievements recorded yet</p>
        <p className="text-xs text-gray-400 mt-1">Achievements are captured automatically during meeting analysis</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Search + staff filter bar */}
      <div className="flex gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            placeholder="Search achievements…"
            value={search}
            onChange={e => onSearchChange(e.target.value)}
            className="w-full pl-9 pr-4 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#059669]/30"
          />
        </div>
        {staffList.length > 1 && (
          <select
            value={staffFilter}
            onChange={e => onStaffFilterChange(e.target.value)}
            className="text-sm border border-gray-200 rounded-lg bg-white px-3 py-2 text-gray-600 focus:outline-none focus:ring-2 focus:ring-[#059669]/30"
          >
            <option value="all">All staff</option>
            {staffList.map(n => <option key={n} value={n}>{n}</option>)}
          </select>
        )}
      </div>
      {/* Stats strip */}
      <div className="grid grid-cols-4 gap-3 mb-2">
        {[
          { label: "Total recorded", value: items.length, green: true },
          { label: "This month", value: thisMonth },
          { label: "Staff celebrated", value: groupMap.size },
          { label: "New (last 7 days)", value: newCount, green: newCount > 0 },
        ].map(({ label, value, green }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-200 p-3 shadow-sm">
            <p className={`text-xl font-bold ${green ? "text-[#059669]" : "text-gray-800"}`}>{value}</p>
            <p className="text-xs text-gray-400 mt-0.5">{label}</p>
          </div>
        ))}
      </div>

      {/* Person groups */}
      {groups.map(([personName, personItems]) => {
        const open = expandedPersons.has(personName);
        const hasNew = personItems.some(isNew);
        const visible = showAllFor.has(personName) ? personItems : personItems.slice(0, SHOW_LIMIT);
        const hiddenCount = personItems.length - SHOW_LIMIT;

        return (
          <div key={personName} className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
            {/* Person header — always visible */}
            <button
              className="w-full flex items-center gap-3 px-5 py-3.5 text-left hover:bg-gray-50 transition-colors"
              onClick={() => togglePerson(personName)}
              data-testid={`ach-person-${personName.replace(/\s/g, "-")}`}
            >
              <div
                className="w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold text-white flex-shrink-0"
                style={{ background: avatarColor(personName) }}
              >
                {personName[0].toUpperCase()}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-gray-900">{personName}</p>
                {!open && (
                  <p className="text-xs text-gray-400 truncate italic mt-0.5">
                    "{personItems[0]?.text?.slice(0, 70)}…"
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                {hasNew && (
                  <span className="text-[10px] font-semibold text-amber-600 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded-full">
                    New
                  </span>
                )}
                <span className="text-xs font-semibold text-[#059669] bg-emerald-50 border border-emerald-100 px-2.5 py-1 rounded-full">
                  {personItems.length} {personItems.length === 1 ? "achievement" : "achievements"}
                </span>
                <ChevronRight className={`w-4 h-4 text-gray-400 transition-transform ${open ? "rotate-90" : ""}`} />
              </div>
            </button>

            {/* Timeline body */}
            {open && (
              <div className="px-5 pb-4 border-t border-gray-100">
                <div className="relative pl-7 pt-4 space-y-5">
                  {/* Vertical connector line */}
                  <div className="absolute left-[11px] top-4 bottom-4 w-0.5 bg-gray-100" />

                  {visible.map((item, idx) => {
                    const _new = isNew(item);
                    const expandKey = `${item.meeting_id}-${item.id}-${idx}`;
                    const expanded = expandedItems.has(expandKey);
                    const faded = idx >= SHOW_LIMIT && !showAllFor.has(personName);

                    return (
                      <div key={expandKey} className={`relative transition-opacity ${faded ? "opacity-50" : "opacity-100"}`}>
                        {/* Timeline dot */}
                        <div className={`absolute left-[-28px] top-1 w-5 h-5 rounded-full border-2 border-white shadow-sm flex items-center justify-center flex-shrink-0 ${_new ? "bg-amber-400" : "bg-[#059669]"}`}>
                          <Award className="w-2.5 h-2.5 text-white" />
                        </div>

                        {/* Entry */}
                        <button
                          className="w-full text-left group"
                          onClick={() => toggleItem(expandKey)}
                          data-testid={`ach-item-${item.id}`}
                        >
                          <div className="flex items-start gap-2">
                            <p className={`text-sm font-medium leading-snug flex-1 text-gray-900 group-hover:text-[#059669] transition-colors ${expanded ? "text-[#059669]" : ""}`}>
                              {item.text}
                            </p>
                            {_new && (
                              <span className="text-[10px] font-semibold text-amber-600 bg-amber-50 border border-amber-200 px-1.5 py-0.5 rounded-full flex-shrink-0 mt-0.5">
                                New
                              </span>
                            )}
                            <ChevronRight className={`w-3.5 h-3.5 text-gray-300 flex-shrink-0 mt-1 transition-transform ${expanded ? "rotate-90" : ""}`} />
                          </div>
                          <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                            <span className="text-xs text-gray-400">{item.meeting_title}</span>
                            <span className="text-gray-200 text-xs">·</span>
                            <span className="text-xs font-medium text-gray-500">{item.meeting_date}</span>
                          </div>
                        </button>

                        {/* Inline expansion */}
                        {expanded && (
                          <div className="mt-2.5 ml-0 bg-gray-50 border border-gray-200 rounded-lg p-3">
                            <p className="text-sm text-gray-700 leading-relaxed mb-3">{item.text}</p>
                            <button
                              onClick={() => navigate(`/meetings/${item.meeting_id}/report`)}
                              className="inline-flex items-center gap-1.5 text-xs font-medium text-[#1E3A8A] hover:text-[#1E3A8A]/80 hover:underline"
                              data-testid={`ach-view-meeting-${item.id}`}
                            >
                              <ExternalLink className="w-3.5 h-3.5" />
                              View in meeting report
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}

                  {/* Show more / collapse */}
                  {hiddenCount > 0 && (
                    <button
                      onClick={() => setShowAllFor(prev => {
                        const next = new Set(prev);
                        next.has(personName) ? next.delete(personName) : next.add(personName);
                        return next;
                      })}
                      className="text-xs font-medium text-[#059669] hover:text-[#059669]/80 pl-0 flex items-center gap-1"
                    >
                      {showAllFor.has(personName)
                        ? <><ChevronRight className="w-3 h-3 rotate-90" /> Show fewer</>
                        : <><ChevronRight className="w-3 h-3 -rotate-90" /> Show {hiddenCount} earlier {hiddenCount === 1 ? "achievement" : "achievements"}</>
                      }
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Register helpers ─────────────────────────────────────────────────────────
const SEV_CFG = {
  high:   { badge: "bg-red-100 text-red-700",    bar: "#DC2626" },
  medium: { badge: "bg-amber-100 text-amber-700", bar: "#F59E0B" },
  low:    { badge: "bg-gray-100 text-gray-600",   bar: "#9CA3AF" },
};

function avatarColor(name) {
  const palette = ["#1E3A8A","#7C3AED","#059669","#D97706","#DC2626","#0891B2","#9333EA"];
  let h = 0;
  for (const c of (name || "")) h = (h * 31 + c.charCodeAt(0)) % palette.length;
  return palette[h];
}

// ── RegisterView ─────────────────────────────────────────────────────────────
function RegisterView({ type, items = [], loading, onToggle }) {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [staffFilter, setStaffFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const ACCENT = { actions: "#D97706", risks: "#DC2626", learning_needs: "#0D9488", achievements: "#059669" };
  const accent = ACCENT[type];

  // Unique staff names for filter dropdown
  const staffList = useMemo(() => {
    const names = new Set();
    items.forEach(item => {
      (item.staff_names || "").split(", ").forEach(n => { if (n.trim()) names.add(n.trim()); });
    });
    return Array.from(names).sort();
  }, [items]);

  // Filter items
  const filtered = useMemo(() => {
    return items.filter(item => {
      const q = search.toLowerCase();
      if (q && !item.text.toLowerCase().includes(q) && !(item.staff_names || "").toLowerCase().includes(q)) return false;
      if (staffFilter !== "all" && !(item.staff_names || "").includes(staffFilter)) return false;
      if (type === "actions") {
        if (statusFilter === "outstanding" && item.completed) return false;
        if (statusFilter === "completed" && !item.completed) return false;
      } else if (type === "risks") {
        if (statusFilter === "open" && item.is_resolved) return false;
        if (statusFilter === "resolved" && !item.is_resolved) return false;
        if (statusFilter === "high" && item.severity !== "high") return false;
        if (statusFilter === "medium" && item.severity !== "medium") return false;
      } else if (type === "learning_needs") {
        if (statusFilter === "outstanding" && item.completed) return false;
        if (statusFilter === "addressed" && !item.completed) return false;
      } else if (type === "achievements") {
        // achievements handled by AchievementsTimeline — no status filter here
      }
      return true;
    });
  }, [items, search, staffFilter, statusFilter, type]);

  const today = new Date().toISOString().slice(0, 10);

  // Stat strip data
  const stats = useMemo(() => {
    if (type === "actions") {
      const outstanding = items.filter(i => !i.completed).length;
      const completed   = items.filter(i => i.completed).length;
      const overdue     = items.filter(i => !i.completed && i.due_date && i.due_date < today).length;
      return [
        { value: items.length,  label: "Total actions",  accentColor: accent },
        { value: outstanding,   label: "Outstanding",    accentColor: null },
        { value: completed,     label: "Completed",      accentColor: "#059669" },
        { value: overdue,       label: "Overdue",        accentColor: overdue > 0 ? "#DC2626" : null },
      ];
    }
    if (type === "risks") {
      const open   = items.filter(i => !i.is_resolved).length;
      const high   = items.filter(i => !i.is_resolved && i.severity === "high").length;
      const medium = items.filter(i => !i.is_resolved && i.severity === "medium").length;
      return [
        { value: items.length, label: "Total identified", accentColor: accent },
        { value: high,         label: "High severity",    accentColor: high > 0 ? "#DC2626" : null },
        { value: medium,       label: "Medium severity",  accentColor: medium > 0 ? "#F59E0B" : null },
        { value: open,         label: "Open",             accentColor: null },
      ];
    }
    // achievements — stats rendered inside AchievementsTimeline
    if (type === "achievements") return [];
    // learning_needs
    const outstanding   = items.filter(i => !i.completed).length;
    const addressed     = items.filter(i => i.completed).length;
    const staffAffected = new Set(items.filter(i => !i.completed).flatMap(i => i.staff_ids || [])).size;
    return [
      { value: items.length,  label: "Total identified", accentColor: accent },
      { value: outstanding,   label: "Outstanding",      accentColor: null },
      { value: addressed,     label: "Addressed",        accentColor: "#059669" },
      { value: staffAffected, label: "Staff affected",   accentColor: null },
    ];
  }, [items, type, accent, today]);

  const exportCSV = () => {
    const esc = v => `"${String(v ?? "").replace(/"/g, '""')}"`;
    let headers, rows;
    if (type === "actions") {
      headers = ["Staff","Meeting","Date","Action","Due Date","Status"];
      rows = filtered.map(i => [i.staff_names, i.meeting_title, i.meeting_date, i.text, i.due_date || "", i.completed ? "Completed" : (i.due_date && i.due_date < today ? "Overdue" : "Outstanding")]);
    } else if (type === "risks") {
      headers = ["Staff","Meeting","Date","Risk","Severity","Status"];
      rows = filtered.map(i => [i.staff_names, i.meeting_title, i.meeting_date, i.text, i.severity, i.is_resolved ? "Resolved" : "Open"]);
    } else if (type === "learning_needs") {
      headers = ["Staff","Meeting","Date","Learning Need","Assigned To","Due Date","Status"];
      rows = filtered.map(i => [i.staff_names, i.meeting_title, i.meeting_date, i.text, i.assigned_to || "", i.due_date || "", i.completed ? "Addressed" : "Outstanding"]);
    } else {
      headers = ["Staff","Meeting","Date","Achievement"];
      rows = filtered.map(i => [i.staff_names, i.meeting_title, i.meeting_date, i.text]);
    }
    const csv = [headers.map(esc).join(","), ...rows.map(r => r.map(esc).join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${type.replace("_", "-")}-register.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const renderItem = (item, idx) => {
    if (type === "actions") {
      const overdue  = !item.completed && item.due_date && item.due_date < today;
      const barColor = item.completed ? "#D1FAE5" : overdue ? "#DC2626" : accent;
      return (
        <div
          key={item.id || idx}
          className={`bg-white border border-gray-200 rounded-lg p-3 flex items-start gap-3 hover:shadow-sm hover:border-gray-300 transition-all cursor-pointer ${item.completed ? "opacity-65" : ""}`}
          onClick={() => navigate(`/meetings/${item.meeting_id}/report`)}
          data-testid={`register-action-${item.id}`}
        >
          <div style={{ width: 3, background: barColor, borderRadius: 2, alignSelf: "stretch", flexShrink: 0 }} />
          <button
            onClick={e => { e.stopPropagation(); onToggle("actions", item.meeting_id, item.id, !item.completed); }}
            className={`flex-shrink-0 mt-0.5 w-5 h-5 rounded border-2 flex items-center justify-center transition-colors ${item.completed ? "bg-emerald-500 border-emerald-500" : "border-gray-300 hover:border-emerald-400"}`}
            title={item.completed ? "Mark as outstanding" : "Mark as complete"}
            data-testid={`register-action-toggle-${item.id}`}
          >
            {item.completed && <Check className="w-3 h-3 text-white" />}
          </button>
          <div className="flex-1 min-w-0">
            <p className={`text-sm font-medium leading-snug ${item.completed ? "line-through text-gray-400" : "text-gray-800"}`}>{item.text}</p>
            <div className="flex items-center gap-1.5 mt-1 flex-wrap">
              <div className="w-5 h-5 rounded-full flex items-center justify-center text-white text-[10px] font-bold flex-shrink-0" style={{ background: avatarColor(item.staff_names) }}>
                {(item.staff_names || "?")[0].toUpperCase()}
              </div>
              <span className="text-xs font-semibold text-gray-600">{item.staff_names}</span>
              <span className="text-xs text-gray-300">·</span>
              <span className="text-xs text-gray-400">{item.meeting_title} · {item.meeting_date}</span>
              {item.due_date && (
                <>
                  <span className="text-xs text-gray-300">·</span>
                  <span className={`text-xs ${overdue ? "text-red-500 font-medium" : "text-gray-400"}`}>
                    Due: {item.due_date}{overdue ? " (overdue)" : ""}
                  </span>
                </>
              )}
            </div>
          </div>
          <div className="flex-shrink-0 ml-2">
            {item.completed
              ? <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-700">Completed</span>
              : overdue
              ? <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-red-100 text-red-700">Overdue</span>
              : <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-700">Outstanding</span>
            }
          </div>
          <ChevronRight className="w-4 h-4 text-gray-300 flex-shrink-0 mt-0.5" />
        </div>
      );
    }

    if (type === "risks") {
      const sev = (item.severity || "low").toLowerCase();
      const sc  = SEV_CFG[sev] || SEV_CFG.low;
      return (
        <div
          key={item.id || idx}
          className={`bg-white border border-gray-200 rounded-lg p-3 flex items-start gap-3 hover:shadow-sm hover:border-gray-300 transition-all cursor-pointer ${item.is_resolved ? "opacity-65" : ""}`}
          onClick={() => navigate(`/meetings/${item.meeting_id}/report`)}
          data-testid={`register-risk-${item.id}`}
        >
          <div style={{ width: 3, background: sc.bar, borderRadius: 2, alignSelf: "stretch", flexShrink: 0 }} />
          <button
            onClick={e => { e.stopPropagation(); onToggle("risks", item.meeting_id, item.id, !item.is_resolved); }}
            className="flex-shrink-0 mt-0.5"
            title={item.is_resolved ? "Mark unresolved" : "Mark resolved"}
            data-testid={`register-risk-toggle-${item.id}`}
          >
            {item.is_resolved
              ? <CheckSquare className="w-4 h-4 text-emerald-600" />
              : <Square className="w-4 h-4 text-gray-400 hover:text-emerald-500 transition-colors" />
            }
          </button>
          <div className="flex-1 min-w-0">
            <p className={`text-sm font-medium leading-snug ${item.is_resolved ? "line-through text-gray-400" : "text-gray-800"}`}>{item.text}</p>
            <div className="flex items-center gap-1.5 mt-1 flex-wrap">
              <div className="w-5 h-5 rounded-full flex items-center justify-center text-white text-[10px] font-bold flex-shrink-0" style={{ background: avatarColor(item.staff_names) }}>
                {(item.staff_names || "?")[0].toUpperCase()}
              </div>
              <span className="text-xs font-semibold text-gray-600">{item.staff_names}</span>
              <span className="text-xs text-gray-300">·</span>
              <span className="text-xs text-gray-400">{item.meeting_title} · {item.meeting_date}</span>
              {item.is_resolved && item.resolved_by && (
                <>
                  <span className="text-xs text-gray-300">·</span>
                  <span className="text-xs text-emerald-600">Resolved by {item.resolved_by}</span>
                </>
              )}
            </div>
          </div>
          <span className={`flex-shrink-0 ml-2 inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${sc.badge}`}>
            {sev.charAt(0).toUpperCase() + sev.slice(1)}
          </span>
          <ChevronRight className="w-4 h-4 text-gray-300 flex-shrink-0 mt-0.5" />
        </div>
      );
    }

    // achievements
    if (type === "achievements") {
      return (
        <div
          key={item.id || idx}
          className={`bg-white border border-gray-200 rounded-lg p-3 flex items-start gap-3 hover:shadow-sm hover:border-gray-300 transition-all cursor-pointer ${item.acknowledged ? "opacity-65" : ""}`}
          onClick={() => navigate(`/meetings/${item.meeting_id}/report`)}
          data-testid={`register-ach-${item.id}`}
        >
          <div style={{ width: 3, background: item.acknowledged ? "#D1FAE5" : accent, borderRadius: 2, alignSelf: "stretch", flexShrink: 0 }} />
          <button
            onClick={e => { e.stopPropagation(); onToggle("achievements", item.meeting_id, item.id, !item.acknowledged); }}
            className={`flex-shrink-0 mt-0.5 w-5 h-5 rounded border-2 flex items-center justify-center transition-colors ${item.acknowledged ? "bg-emerald-500 border-emerald-500" : "border-gray-300 hover:border-emerald-400"}`}
            title={item.acknowledged ? "Mark unacknowledged" : "Acknowledge"}
            data-testid={`register-ach-toggle-${item.id}`}
          >
            {item.acknowledged && <Check className="w-3 h-3 text-white" />}
          </button>
          <div className="flex-1 min-w-0">
            <p className={`text-sm font-medium leading-snug ${item.acknowledged ? "line-through text-gray-400" : "text-gray-800"}`}>{item.text}</p>
            <div className="flex items-center gap-1.5 mt-1 flex-wrap">
              <div className="w-5 h-5 rounded-full flex items-center justify-center text-white text-[10px] font-bold flex-shrink-0" style={{ background: avatarColor(item.staff_names) }}>
                {(item.staff_names || "?")[0].toUpperCase()}
              </div>
              <span className="text-xs font-semibold text-gray-600">{item.staff_names}</span>
              <span className="text-xs text-gray-300">·</span>
              <span className="text-xs text-gray-400">{item.meeting_title} · {item.meeting_date}</span>
            </div>
          </div>
          <div className="flex-shrink-0 ml-2">
            {item.acknowledged
              ? <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-700">Acknowledged</span>
              : <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-600 border border-emerald-200">New</span>
            }
          </div>
          <ChevronRight className="w-4 h-4 text-gray-300 flex-shrink-0 mt-0.5" />
        </div>
      );
    }

    // learning_needs
    return (
      <div
        key={item.id || idx}
        className={`bg-white border border-gray-200 rounded-lg p-3 flex items-start gap-3 hover:shadow-sm hover:border-gray-300 transition-all cursor-pointer ${item.completed ? "opacity-65" : ""}`}
        onClick={() => navigate(`/meetings/${item.meeting_id}/report`)}
        data-testid={`register-ln-${item.id}`}
      >
        <div style={{ width: 3, background: item.completed ? "#D1FAE5" : accent, borderRadius: 2, alignSelf: "stretch", flexShrink: 0 }} />
        <button
          onClick={e => { e.stopPropagation(); onToggle("learning_needs", item.meeting_id, item.id, !item.completed); }}
          className={`flex-shrink-0 mt-0.5 w-5 h-5 rounded border-2 flex items-center justify-center transition-colors ${item.completed ? "bg-teal-500 border-teal-500" : "border-gray-300 hover:border-teal-400"}`}
          title={item.completed ? "Mark as outstanding" : "Mark as addressed"}
          data-testid={`register-ln-toggle-${item.id}`}
        >
          {item.completed && <Check className="w-3 h-3 text-white" />}
        </button>
        <div className="flex-1 min-w-0">
          <p className={`text-sm font-medium leading-snug ${item.completed ? "line-through text-gray-400" : "text-gray-800"}`}>{item.text}</p>
          <div className="flex items-center gap-1.5 mt-1 flex-wrap">
            <div className="w-5 h-5 rounded-full flex items-center justify-center text-white text-[10px] font-bold flex-shrink-0" style={{ background: avatarColor(item.staff_names) }}>
              {(item.staff_names || "?")[0].toUpperCase()}
            </div>
            <span className="text-xs font-semibold text-gray-600">{item.staff_names}</span>
            <span className="text-xs text-gray-300">·</span>
            <span className="text-xs text-gray-400">{item.meeting_title} · {item.meeting_date}</span>
            {item.assigned_to && (
              <>
                <span className="text-xs text-gray-300">·</span>
                <span className="text-xs text-gray-400">Assigned: {item.assigned_to}</span>
              </>
            )}
          </div>
        </div>
        <div className="flex-shrink-0 ml-2">
          {item.completed
            ? <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-teal-100 text-teal-700">Addressed</span>
            : <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-700">Outstanding</span>
          }
        </div>
        <ChevronRight className="w-4 h-4 text-gray-300 flex-shrink-0 mt-0.5" />
      </div>
    );
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48">
        <div className="flex items-center gap-3 text-gray-400">
          <div className="w-5 h-5 border-2 border-[#1E3A8A] border-t-transparent rounded-full animate-spin" />
          <span className="text-sm">Loading register…</span>
        </div>
      </div>
    );
  }

  // Achievements use a dedicated grouped timeline — bypass the generic list
  if (type === "achievements") {
    return (
      <AchievementsTimeline
        items={items}
        search={search}
        staffFilter={staffFilter}
        onSearchChange={setSearch}
        onStaffFilterChange={setStaffFilter}
        staffList={staffList}
      />
    );
  }

  const EMPTY_MSG = {
    actions:        "No outstanding actions — great!",
    risks:          "No attention items recorded yet",
    learning_needs: "No learning needs identified yet",
    achievements:   "No achievements recorded yet",
  };
  const STATUS_OPTS = {
    actions:        [{ v: "all", l: "All statuses" }, { v: "outstanding", l: "Outstanding" }, { v: "completed", l: "Completed" }],
    risks:          [{ v: "all", l: "All statuses" }, { v: "open", l: "Open" }, { v: "resolved", l: "Resolved" }, { v: "high", l: "High severity" }, { v: "medium", l: "Medium severity" }],
    learning_needs: [{ v: "all", l: "All statuses" }, { v: "outstanding", l: "Outstanding" }, { v: "addressed", l: "Addressed" }],
    achievements:   [],
  };
  const SEARCH_PH = { actions: "Search actions…", risks: "Search attention items…", learning_needs: "Search learning needs…", achievements: "Search achievements…" };

  return (
    <div>
      {/* Stat strip */}
      <div className="grid grid-cols-4 gap-3 mb-5">
        {stats.map((s, i) => (
          <div
            key={i}
            className="bg-white border border-gray-200 rounded-lg p-4"
            style={i === 0 ? { borderLeft: `3px solid ${accent}` } : {}}
            data-testid={`register-stat-${type}-${i}`}
          >
            <div className="text-2xl font-bold" style={{ color: s.accentColor || "#111827" }}>{s.value}</div>
            <div className="text-xs text-gray-500 mt-0.5">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Filter bar */}
      <div className="flex gap-2 mb-4">
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder={SEARCH_PH[type]}
          className="flex-1 border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
          data-testid={`register-search-${type}`}
        />
        <select
          value={staffFilter}
          onChange={e => setStaffFilter(e.target.value)}
          className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm bg-white focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
          data-testid={`register-staff-filter-${type}`}
        >
          <option value="all">All staff</option>
          {staffList.map(n => <option key={n} value={n}>{n}</option>)}
        </select>
        <select
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
          className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm bg-white focus:outline-none focus:ring-1 focus:ring-[#1E3A8A]"
          data-testid={`register-status-filter-${type}`}
        >
          {STATUS_OPTS[type].map(o => <option key={o.v} value={o.v}>{o.l}</option>)}
        </select>
        <button
          onClick={exportCSV}
          disabled={filtered.length === 0}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 px-3 py-1.5 rounded-lg border border-gray-300 hover:bg-gray-50 disabled:opacity-40 whitespace-nowrap"
          data-testid={`register-export-${type}`}
          title="Export filtered list as CSV"
        >
          <Download className="w-3.5 h-3.5" />
          Export CSV
        </button>
      </div>

      {/* Item list */}
      {filtered.length === 0 ? (
        <div className="text-center py-12 text-gray-400">
          <p className="text-sm">{(search || staffFilter !== "all" || statusFilter !== "all") ? "No items match your filters" : EMPTY_MSG[type]}</p>
        </div>
      ) : (
        <div className="space-y-2" data-testid={`register-list-${type}`}>
          {filtered.map((item, idx) => renderItem(item, idx))}
        </div>
      )}
    </div>
  );
}


// ── Main page ────────────────────────────────────────────────────────────────
export default function TeamInsights() {
  const { getAuthConfig, API, user } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState(() => {
    const t = searchParams.get("tab");
    const valid = ["matrix","themes","achievements","learning_needs","risks","actions"];
    return valid.includes(t) ? t : "matrix";
  });
  const [orgStructure, setOrgStructure] = useState({ settings: [] });
  const [orgFilter, setOrgFilter] = useState({ setting_id: "", team_id: "" });
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [ccStandards, setCcStandards] = useState([]);
  const [drillDown, setDrillDown] = useState(null);
  const [registers, setRegisters] = useState(null);
  const [registersLoading, setRegistersLoading] = useState(false);
  // Stale-request guards: each filter change bumps the counter; callbacks
  // discard responses that arrive after a newer request was dispatched.
  const loadReqRef = useRef(0);
  const regReqRef  = useRef(0);

  const load = useCallback(async (filter = {}) => {
    loadReqRef.current += 1;
    const req = loadReqRef.current;
    setLoading(true);
    try {
      const params = {};
      if (filter.team_id) params.team_id = filter.team_id;
      else if (filter.setting_id) params.setting_id = filter.setting_id;
      if (filter.date_from) params.date_from = filter.date_from;
      if (filter.date_to) params.date_to = filter.date_to;
      const { data: d } = await cachedGet(`${API}/admin/team-insights`, { ...getAuthConfig(), params });
      if (req !== loadReqRef.current) return;
      setData(d);
    } catch (err) {
      console.error("Team insights error", err.message);
    } finally {
      if (req === loadReqRef.current) setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API]);

  const loadRegisters = useCallback(async (filter = {}) => {
    regReqRef.current += 1;
    const req = regReqRef.current;
    setRegistersLoading(true);
    try {
      const params = {};
      if (filter.team_id) params.team_id = filter.team_id;
      else if (filter.setting_id) params.setting_id = filter.setting_id;
      if (filter.date_from) params.date_from = filter.date_from;
      if (filter.date_to) params.date_to = filter.date_to;
      const { data: d } = await cachedGet(`${API}/admin/team-insights/registers`, { ...getAuthConfig(), params });
      if (req !== regReqRef.current) return;
      setRegisters(d);
    } catch (err) {
      console.error("Registers error", err.message);
    } finally {
      if (req === regReqRef.current) setRegistersLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API]);

  const handleRegisterToggle = useCallback(async (type, meetingId, itemId, newValue) => {
    // Optimistic update
    setRegisters(prev => {
      if (!prev) return prev;
      return {
        ...prev,
        [type]: prev[type].map(item => {
          if (item.id === itemId && item.meeting_id === meetingId) {
            return type === "risks"
              ? { ...item, is_resolved: newValue }
              : type === "achievements"
              ? { ...item, acknowledged: newValue }
              : { ...item, completed: newValue };
          }
          return item;
        }),
      };
    });
    try {
      if (type === "risks") {
        await axios.patch(`${API}/review/${meetingId}/risks/${itemId}`, { is_resolved: newValue }, getAuthConfig());
      } else if (type === "actions") {
        await axios.patch(`${API}/admin/team-insights/actions/${meetingId}/${itemId}`, { completed: newValue }, getAuthConfig());
      } else if (type === "achievements") {
        await axios.patch(`${API}/admin/team-insights/achievements/${meetingId}/${itemId}`, { acknowledged: newValue }, getAuthConfig());
      } else {
        await axios.patch(`${API}/admin/team-insights/learning_needs/${meetingId}/${itemId}`, { completed: newValue }, getAuthConfig());
      }
    } catch (err) {
      console.error("Toggle error", err.message);
      // Revert on failure
      setRegisters(prev => {
        if (!prev) return prev;
        return {
          ...prev,
          [type]: prev[type].map(item => {
            if (item.id === itemId && item.meeting_id === meetingId) {
              return type === "risks"
                ? { ...item, is_resolved: !newValue }
                : type === "achievements"
                ? { ...item, acknowledged: !newValue }
                : { ...item, completed: !newValue };
            }
            return item;
          }),
        };
      });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API]);

  // Load main data whenever filters change
  useEffect(() => {
    load({ ...orgFilter, date_from: dateFrom, date_to: dateTo });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgFilter, dateFrom, dateTo]);

  // Load registers on mount AND whenever filters change — not just when a register tab is active,
  // so the badge counts are always visible even when starting on the matrix tab.
  const REGISTER_TABS = ["achievements", "learning_needs", "risks", "actions"];
  useEffect(() => {
    loadRegisters({ ...orgFilter, date_from: dateFrom, date_to: dateTo });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgFilter, dateFrom, dateTo]);

  useEffect(() => {
    if (user?.role === "admin" || user?.role === "manager") {
      cachedGet(`${API}/org/structure`, getAuthConfig()).then(r => setOrgStructure(r.data)).catch(() => {});
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    cachedGet(`${API}/admin/standards`, { ...getAuthConfig(), params: { type: "care_cert" } })
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
    const frameworkLabel = { cqc: "CQC", care_cert: "Induction", custom: "Organisational" };

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

  // Count badges for register tabs
  const regCounts = {
    achievements:   registers?.achievements?.filter(i => !i.acknowledged).length ?? null,
    learning_needs: registers?.learning_needs?.filter(i => !i.completed).length ?? null,
    risks:          registers?.risks?.filter(i => !i.is_resolved).length ?? null,
    actions:        registers?.actions?.filter(i => !i.completed).length ?? null,
  };

  const MAIN_TABS = [
    { key: "matrix",         label: "Evidence Matrix",    icon: Grid3x3,       accent: null },
    { key: "themes",         label: "Standards Coverage", icon: TrendingUp,    accent: null },
    { key: "achievements",   label: "Achievements",       icon: Award,         accent: "#059669" },
    { key: "learning_needs", label: "Learning Needs",     icon: BookOpen,      accent: "#0D9488" },
    { key: "risks",          label: "Attention",          icon: AlertTriangle, accent: "#DC2626" },
    { key: "actions",        label: "Actions",            icon: ClipboardList, accent: "#D97706" },
  ];

  return (
    <Layout>
      <div className="flex flex-col h-full">
        {/* Header */}
        <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between sticky top-0 z-20">
          <div>
            <h1 className="text-base font-semibold text-gray-900 font-display">
              Team Themes
            </h1>
            {data && (
              <p className="text-xs text-gray-500 mt-0.5">
                {data.staff_count} staff · {data.meeting_count} {data.meeting_count === 1 ? "meeting" : "meetings"}
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
            {/* Date range filters */}
            <div className="flex items-center gap-1.5 border-l border-gray-200 pl-2 ml-1" data-testid="date-range-filter">
              <span className="text-xs text-gray-400 whitespace-nowrap">From</span>
              <UkDatePicker
                value={dateFrom}
                onChange={setDateFrom}
                testId="insights-date-from"
              />
              <span className="text-xs text-gray-400">to</span>
              <UkDatePicker
                value={dateTo}
                onChange={setDateTo}
                minDate={dateFrom ? new Date(dateFrom) : undefined}
                testId="insights-date-to"
              />
              {(dateFrom || dateTo) && (
                <button
                  onClick={() => { setDateFrom(""); setDateTo(""); }}
                  className="text-xs text-gray-400 hover:text-gray-600 px-1"
                  title="Clear date filter"
                  data-testid="insights-date-clear"
                >
                  ✕
                </button>
              )}
            </div>
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
              onClick={() => {
                load({ ...orgFilter, date_from: dateFrom, date_to: dateTo });
                if (REGISTER_TABS.includes(tab)) loadRegisters({ ...orgFilter, date_from: dateFrom, date_to: dateTo });
              }}
              disabled={loading || registersLoading}
              className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 px-3 py-1.5 rounded border border-gray-200 hover:bg-gray-50 disabled:opacity-50"
              data-testid="refresh-insights-btn"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${(loading || registersLoading) ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>
        </div>

        {/* Main tabs */}
        <div className="bg-white border-b border-gray-100 px-6">
          <div className="flex overflow-x-auto pt-1" style={{ scrollbarWidth: "none" }}>
            {MAIN_TABS.map(({ key, label, icon: Icon, accent }) => {
              const isActive = tab === key;
              const count = regCounts[key];
              const tabColor = isActive ? (accent || "#1E3A8A") : undefined;
              return (
                <button
                  key={key}
                  onClick={() => setTab(key)}
                  className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap flex-shrink-0 ${
                    isActive
                      ? "text-[#1E3A8A]"
                      : "border-transparent text-gray-500 hover:text-gray-700"
                  }`}
                  style={isActive ? { borderBottomColor: accent || "#1E3A8A", color: accent || "#1E3A8A" } : {}}
                  data-testid={`main-tab-${key}`}
                >
                  <Icon className="w-4 h-4" />
                  {label}
                  {count !== null && count > 0 && (
                    <span
                      className="text-[10px] font-bold px-1.5 py-0.5 rounded-full text-white"
                      style={{ background: accent || "#6B7280" }}
                    >
                      {count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {/* Matrix / Themes: require main data */}
          {(tab === "matrix" || tab === "themes") && (
            loading ? (
              tab === "themes" ? (
                /* ── Themes skeleton — 3-col GapBar card grid ── */
                <div className="space-y-8 p-6" aria-busy="true" aria-label="Loading standards coverage">
                  {/* Section heading */}
                  <div>
                    <div className="flex items-center gap-2 mb-4">
                      <Skeleton className="w-4 h-4 rounded" />
                      <Skeleton className="h-4 w-48" />
                    </div>
                    {/* 3-column card grid */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                      {[
                        { w: 36, color: "text-purple-600" },
                        { w: 44, color: "text-blue-600" },
                        { w: 32, color: "text-teal-600" },
                      ].map((col, ci) => (
                        <div key={ci} className="bg-white border border-gray-200 rounded-lg p-4">
                          {/* Card header: icon + title + count */}
                          <div className="flex items-center gap-1.5 mb-3">
                            <Skeleton className="w-3.5 h-3.5 rounded" />
                            <Skeleton className={`h-3.5`} style={{ width: col.w + 80 }} />
                            <Skeleton className="ml-auto h-3 w-16" />
                          </div>
                          {/* GapBar rows */}
                          {[...Array(5)].map((_, ri) => (
                            <div key={ri} className="mb-3">
                              <div className="flex items-center justify-between mb-1">
                                <div className="flex items-center gap-1.5 min-w-0 flex-1">
                                  <Skeleton className="h-4 w-10 rounded flex-shrink-0" />
                                  <Skeleton className="h-3.5 flex-1" style={{ maxWidth: `${50 + (ri % 4) * 12}%` }} />
                                </div>
                                <Skeleton className="h-3 w-12 ml-2 flex-shrink-0" />
                              </div>
                              <Skeleton className="h-1.5 w-full rounded-full" />
                            </div>
                          ))}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              ) : (
              /* ── Matrix skeleton ── */
              <div className="p-6 space-y-4" aria-busy="true" aria-label="Loading team insights">
                {/* Filter bar shimmer */}
                <div className="flex items-center gap-3 mb-2">
                  <Skeleton className="h-8 w-40 rounded-md" />
                  <Skeleton className="h-8 w-32 rounded-md" />
                  <Skeleton className="h-8 w-28 rounded-md" />
                </div>
                {/* Table header */}
                <div className="flex items-center gap-3 pb-2 border-b border-gray-100">
                  <Skeleton className="h-3 w-28 flex-shrink-0" />
                  {[...Array(5)].map((_, i) => (
                    <Skeleton key={i} className="h-3 w-16 flex-1" />
                  ))}
                </div>
                {/* Staff rows */}
                {[...Array(6)].map((_, i) => (
                  <div key={i} className="flex items-center gap-3 py-2 border-b border-gray-50">
                    <div className="flex items-center gap-2 w-28 flex-shrink-0">
                      <Skeleton className="h-7 w-7 rounded-full flex-shrink-0" />
                      <Skeleton className="h-3 w-16" />
                    </div>
                    {[...Array(5)].map((_, j) => (
                      <Skeleton key={j} className="h-7 flex-1 rounded-md" />
                    ))}
                  </div>
                ))}
              </div>
              )
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
            )
          )}

          {/* Register tabs */}
          {REGISTER_TABS.includes(tab) && (
            <RegisterView
              type={tab}
              items={registers?.[tab] || []}
              loading={registersLoading}
              onToggle={handleRegisterToggle}
            />
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

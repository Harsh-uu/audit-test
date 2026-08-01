import React, { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import {
  Award, ChevronDown, ChevronRight,
  Loader, AlertCircle, CheckCircle, TrendingUp, Download, ExternalLink,
  Users, Search, X,
} from "lucide-react";

/* ── helpers ──────────────────────────────────────────────────────────────── */

function coverageTheme(pct) {
  if (pct >= 70) return { key: "green", bar: "bg-emerald-500", badge: "bg-emerald-50 text-emerald-700 border-emerald-200", ring: "border-emerald-200" };
  if (pct >= 30) return { key: "amber", bar: "bg-amber-400",   badge: "bg-amber-50 text-amber-700 border-amber-200",       ring: "border-amber-200" };
  return             { key: "red",   bar: "bg-red-500",     badge: "bg-red-50 text-red-700 border-red-200",             ring: "border-red-200" };
}

function buildCoverage(standards, rows) {
  return standards.map(std => {
    const evidenced = rows.filter(r => {
      const s = r.cells?.[std.ref]?.status;
      return s === "evidenced" || s === "partial";
    }).length;
    const gaps = rows.filter(r => r.cells?.[std.ref]?.status === "gap").map(r => r.staff_name);
    const evidenced_staff = rows
      .filter(r => r.cells?.[std.ref]?.status !== "gap")
      .map(r => ({
        name:              r.staff_name,
        excerpt:           r.cells[std.ref]?.latest_excerpt || "",
        source_meeting_id: r.cells[std.ref]?.source_meeting_id || "",
      }));
    const pct  = rows.length > 0 ? Math.round((evidenced / rows.length) * 100) : 0;
    return { ...std, evidenced, gaps, evidenced_staff, total: rows.length, pct, theme: coverageTheme(pct) };
  });
}

/* ── StandardRow ──────────────────────────────────────────────────────────── */

function StandardRow({ item, open, onToggle }) {
  const navigate = useNavigate();
  const { pct, evidenced, total, gaps, evidenced_staff = [], theme } = item;
  const hasExpandable = gaps.length > 0 || evidenced_staff.length > 0;
  return (
    <div className={`bg-white border rounded-lg overflow-hidden ${theme.ring}`}>
      <div
        className="px-4 py-3 flex items-center gap-3 cursor-pointer hover:bg-gray-50/60 transition-colors"
        onClick={onToggle}
        data-testid={`cc-row-${item.ref}`}
      >
        <div className={`w-11 h-9 rounded-md flex items-center justify-center text-xs font-bold flex-shrink-0 border ${theme.badge}`}>
          {pct}%
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-gray-900 leading-snug">
            <span className="text-gray-500 mr-1">{item.ref}</span>
            {item.name}
          </p>
          <div className="flex items-center gap-2 mt-1.5">
            <div className="flex-1 bg-gray-100 rounded-full h-1.5">
              <div className={`h-1.5 rounded-full ${theme.bar} transition-all duration-500`} style={{ width: `${pct}%` }} />
            </div>
            <span className="text-xs text-gray-400 flex-shrink-0">{evidenced}/{total} staff</span>
          </div>
        </div>
        {hasExpandable
          ? open ? <ChevronDown className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                 : <ChevronRight className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
          : <CheckCircle className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />}
      </div>

      {open && (
        <>
          {/* Gaps */}
          {gaps.length > 0 && (
            <div className="border-t border-red-100 bg-red-50/40 px-4 py-3">
              <p className="text-xs font-semibold text-red-600 mb-2">No evidence recorded for:</p>
              <div className="flex flex-wrap gap-1.5">
                {gaps.map(name => (
                  <span key={name} className="text-xs bg-white border border-red-200 text-red-700 px-2 py-0.5 rounded-full">{name}</span>
                ))}
              </div>
            </div>
          )}

          {/* Evidence with transcript links */}
          {evidenced_staff.length > 0 && (
            <div className="border-t border-emerald-100 bg-emerald-50/20 px-4 py-3 space-y-3">
              <p className="text-xs font-semibold text-emerald-700">Evidence recorded:</p>
              {evidenced_staff.map(s => (
                <div key={s.name}>
                  <p className="text-xs font-medium text-gray-700">{s.name}</p>
                  {s.excerpt && (
                    <blockquote className="mt-0.5 border-l-2 border-emerald-200 pl-2.5 text-xs text-gray-500 italic leading-relaxed">
                      "{s.excerpt}"
                    </blockquote>
                  )}
                  {s.source_meeting_id && s.excerpt && (
                    <button
                      onClick={e => { e.stopPropagation(); navigate(`/meetings/${s.source_meeting_id}/report`, { state: { highlightExcerpt: s.excerpt, initialTab: "transcript" } }); }}
                      className="mt-1 flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 transition-colors"
                      data-testid={`view-transcript-${item.ref}-${s.name.replace(/\s+/g,"-")}`}
                    >
                      <ExternalLink className="w-3 h-3" />
                      View in transcript
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/* ── StatChip ─────────────────────────────────────────────────────────────── */

function StatChip({ label, value, sub, color }) {
  const cls = {
    green:  "bg-emerald-50 border-emerald-200 text-emerald-800",
    amber:  "bg-amber-50 border-amber-200 text-amber-800",
    red:    "bg-red-50 border-red-200 text-red-800",
    blue:   "bg-blue-50 border-blue-200 text-blue-800",
    purple: "bg-purple-50 border-purple-200 text-purple-800",
  }[color] || "bg-gray-50 border-gray-200 text-gray-800";
  return (
    <div className={`border rounded-xl px-4 py-3 min-w-[100px] ${cls}`}>
      <p className="text-2xl font-bold leading-none">{value}</p>
      <p className="text-xs font-medium mt-1 opacity-80">{label}</p>
      {sub && <p className="text-[10px] mt-0.5 opacity-60">{sub}</p>}
    </div>
  );
}

/* ── StaffPicker ──────────────────────────────────────────────────────────── */

function StaffPicker({ users, selected, onChange }) {
  const [open, setOpen]       = useState(false);
  const [search, setSearch]   = useState("");
  const ref                   = useRef(null);

  // Close on outside click
  useEffect(() => {
    function handler(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false); }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const filtered = users.filter(u =>
    u.name.toLowerCase().includes(search.toLowerCase())
  );

  const toggle = id => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id); else next.add(id);
    onChange(next);
  };

  const label = selected.size === 0
    ? "All staff"
    : selected.size === 1
      ? users.find(u => selected.has(u.id))?.name || "1 staff"
      : `${selected.size} staff selected`;

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 bg-white border border-gray-200 text-gray-700 px-3 py-2 rounded-lg text-sm font-medium hover:bg-gray-50 transition-colors"
        data-testid="staff-picker-trigger"
      >
        <Users className="w-3.5 h-3.5 text-gray-400" />
        <span>{label}</span>
        {selected.size > 0 && (
          <span className="ml-0.5 bg-blue-600 text-white text-[10px] font-bold rounded-full w-4 h-4 flex items-center justify-center">
            {selected.size}
          </span>
        )}
        <ChevronDown className="w-3 h-3 text-gray-400 ml-0.5" />
      </button>

      {open && (
        <div className="absolute right-0 mt-1 w-64 bg-white border border-gray-200 rounded-xl shadow-lg z-50 overflow-hidden" data-testid="staff-picker-dropdown">
          {/* Search */}
          <div className="p-2 border-b border-gray-100">
            <div className="flex items-center gap-2 bg-gray-50 rounded-lg px-2 py-1.5">
              <Search className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
              <input
                autoFocus
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Search staff…"
                className="flex-1 text-sm bg-transparent outline-none text-gray-700 placeholder-gray-400"
                data-testid="staff-picker-search"
              />
              {search && <button onClick={() => setSearch("")}><X className="w-3 h-3 text-gray-400" /></button>}
            </div>
          </div>

          {/* All staff option */}
          <div
            className={`flex items-center gap-2.5 px-3 py-2 cursor-pointer hover:bg-gray-50 border-b border-gray-100 ${selected.size === 0 ? "bg-blue-50" : ""}`}
            onClick={() => { onChange(new Set()); setOpen(false); }}
            data-testid="staff-picker-all"
          >
            <div className={`w-4 h-4 rounded border-2 flex items-center justify-center flex-shrink-0 ${selected.size === 0 ? "bg-blue-600 border-blue-600" : "border-gray-300"}`}>
              {selected.size === 0 && <CheckCircle className="w-3 h-3 text-white" />}
            </div>
            <span className="text-sm text-gray-700 font-medium">All staff</span>
          </div>

          {/* Staff list */}
          <div className="max-h-52 overflow-y-auto">
            {filtered.length === 0 ? (
              <p className="text-xs text-gray-400 text-center py-4">No staff found</p>
            ) : filtered.map(u => (
              <div
                key={u.id}
                className="flex items-center gap-2.5 px-3 py-2 cursor-pointer hover:bg-gray-50"
                onClick={() => toggle(u.id)}
                data-testid={`staff-picker-item-${u.id}`}
              >
                <div className={`w-4 h-4 rounded border-2 flex items-center justify-center flex-shrink-0 transition-colors ${selected.has(u.id) ? "bg-blue-600 border-blue-600" : "border-gray-300"}`}>
                  {selected.has(u.id) && <CheckCircle className="w-3 h-3 text-white" />}
                </div>
                <span className="text-sm text-gray-700">{u.name}</span>
              </div>
            ))}
          </div>

          {/* Footer */}
          {selected.size > 0 && (
            <div className="px-3 py-2 border-t border-gray-100 flex justify-between items-center">
              <span className="text-xs text-gray-400">{selected.size} selected</span>
              <button
                onClick={() => onChange(new Set())}
                className="text-xs text-blue-600 hover:underline"
                data-testid="staff-picker-clear"
              >Clear</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Main page ────────────────────────────────────────────────────────────── */

const FILTER_OPTS = [
  { key: "all",       label: "All" },
  { key: "gaps",      label: "Gaps only" },
  { key: "evidenced", label: "Evidenced" },
];

export default function CareCertPrep() {
  const { getAuthConfig, API } = useAuth();
  const navigate = useNavigate();

  const [insights, setInsights]       = useState(null);
  const [loading, setLoading]         = useState(true);
  const [filter, setFilter]           = useState("all");
  const [open, setOpen]               = useState(new Set());
  const [exporting, setExporting]     = useState(false);
  const [users, setUsers]             = useState([]);
  const [selectedStaff, setSelectedStaff] = useState(new Set());

  useEffect(() => {
    axios.get(`${API}/admin/team-insights`, getAuthConfig())
      .then(r => setInsights(r.data))
      .catch(() => {})
      .finally(() => setLoading(false));
    // Fetch org users for the staff picker
    axios.get(`${API}/admin/users`, getAuthConfig())
      .then(r => setUsers((r.data || []).filter(u => u.role === "attendee" || u.role === "manager")))
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API]);

  const toggle = ref => setOpen(prev => {
    const next = new Set(prev);
    if (next.has(ref)) next.delete(ref); else next.add(ref);
    return next;
  });

  const handleExportExcerpts = async () => {
    setExporting(true);
    try {
      const token = localStorage.getItem("supervision_token");
      const params = selectedStaff.size > 0
        ? `?staff_ids=${Array.from(selectedStaff).join(",")}`
        : "";
      const resp = await fetch(`${API}/admin/export-cc-excerpts${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) throw new Error(await resp.text());
      const blob = await resp.blob();
      const disposition = resp.headers.get("Content-Disposition") || "";
      const match = disposition.match(/filename="([^"]+)"/);
      const filename = match ? match[1] : "care_cert_evidence_excerpts.pdf";
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement("a");
      a.href = url; a.download = filename; a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert("Export failed: " + err.message);
    }
    setExporting(false);
  };

  if (loading) {
    return (
      <Layout>
        <div className="flex items-center justify-center py-24 text-gray-400">
          <Loader className="w-5 h-5 animate-spin mr-2" /> Loading…
        </div>
      </Layout>
    );
  }

  if (!insights || !insights.matrix?.care_cert?.rows?.length) {
    return (
      <Layout>
        <div className="p-8 text-center text-gray-400">
          <AlertCircle className="w-8 h-8 mx-auto mb-3 opacity-30" />
          <p className="text-sm font-medium text-gray-500">No Care Certificate evidence yet</p>
          <p className="text-xs text-gray-400 mt-1">Coverage will appear once meetings with Care Certificate evidence are signed off</p>
          <button onClick={() => navigate("/")} className="mt-3 text-xs text-[#1E3A8A] hover:underline">Back to dashboard →</button>
        </div>
      </Layout>
    );
  }

  const ccRows = insights.matrix?.care_cert?.rows      || [];
  const ccStds = insights.matrix?.care_cert?.standards  || [];

  const ccCov     = buildCoverage(ccStds, ccRows);
  const order     = { red: 0, amber: 1, green: 2 };
  const ccSorted  = [...ccCov].sort((a, b) => order[a.theme.key] - order[b.theme.key]);

  const filtered = filter === "gaps"      ? ccSorted.filter(s => s.gaps.length > 0)
                 : filter === "evidenced" ? ccSorted.filter(s => s.evidenced === s.total && s.total > 0)
                 : ccSorted;

  const ccFull    = ccCov.filter(s => s.evidenced === s.total && s.total > 0).length;
  const ccPartial = ccCov.filter(s => s.evidenced > 0 && s.evidenced < s.total).length;
  const ccGaps    = ccCov.filter(s => s.pct < 70).length;
  const totalStaff = ccRows.length;

  return (
    <Layout>
      <div className="p-6 md:p-8 fade-in">

        {/* Page header */}
        <div className="flex items-start gap-3 mb-6">
          <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center flex-shrink-0 mt-0.5">
            <Award className="w-4 h-4 text-blue-600" />
          </div>
          <div className="flex-1">
            <h1 className="text-2xl font-semibold text-gray-900 font-display">Care Certificate</h1>
            <p className="text-sm text-gray-500 mt-0.5">Evidence coverage across {totalStaff} staff member{totalStaff !== 1 ? "s" : ""}</p>
          </div>
          <div className="flex items-center gap-2">
            <StaffPicker users={users} selected={selectedStaff} onChange={setSelectedStaff} />
            <button
              onClick={handleExportExcerpts}
              disabled={exporting}
              className="flex items-center gap-2 bg-[#1E3A8A] text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-[#1E40AF] transition-colors disabled:opacity-60"
              data-testid="export-cc-excerpts-btn"
            >
              <Download className="w-4 h-4" />
              {exporting ? "Generating…" : "Export Excerpts"}
            </button>
          </div>
        </div>

        {/* Stats */}
        <div className="flex gap-3 flex-wrap mb-6">
          <StatChip label="Fully covered" value={ccFull}    sub={`of ${ccStds.length} standards`} color="green" />
          <StatChip label="Partial cover" value={ccPartial} sub="some staff have gaps"             color="amber" />
          <StatChip label="No evidence"   value={ccGaps}    sub="across all staff"                 color="red"   />
          <StatChip label="Staff tracked" value={totalStaff} sub="signed-off meetings"              color="blue"  />
        </div>

        {/* Filter */}
        <div className="flex items-center gap-1 mb-4">
          <div className="ml-auto flex items-center gap-1">
            {FILTER_OPTS.map(f => (
              <button
                key={f.key}
                onClick={() => setFilter(f.key)}
                className={`text-xs px-2.5 py-1.5 rounded-full border transition-colors ${
                  filter === f.key ? "bg-gray-900 text-white border-gray-900" : "bg-white text-gray-600 border-gray-200 hover:bg-gray-50"
                }`}
                data-testid={`cc-filter-${f.key}`}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        {/* Coverage list */}
        {filtered.length === 0 ? (
          <div className="text-center py-16 text-gray-400">
            <TrendingUp className="w-8 h-8 mx-auto mb-3 opacity-30" />
            <p className="text-sm text-gray-500">No standards match this filter</p>
          </div>
        ) : (
          <div className="space-y-2" data-testid="cc-coverage-list">
            {filtered.map(item => (
              <StandardRow key={item.ref} item={item} open={open.has(item.ref)} onToggle={() => toggle(item.ref)} />
            ))}
          </div>
        )}

      </div>
    </Layout>
  );
}

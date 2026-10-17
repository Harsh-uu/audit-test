import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Check, ChevronRight, ExternalLink, Award, BookOpen, ClipboardList } from "lucide-react";

// ── My Portfolio's Actions / Learning Needs / Achievements timeline ────────
// Same visual language as Team Insights' Registers (pages/TeamInsights.js)
// for consistency, but scoped to one person (no per-person grouping) and
// split into Outstanding (top) vs Completed/history (below) per spec.
// Achievements are read-only (no doneField, no toggle dot) — a recognition
// record, not a to-do.

const TYPE_CFG = {
  achievements:   { icon: Award,         accent: "#059669", noun: "achievement" },
  learning_needs: { icon: BookOpen,      accent: "#0D9488", noun: "learning need" },
  actions:        { icon: ClipboardList, accent: "#D97706", noun: "action" },
};

export function PersonalRegisterTimeline({ type, items, canToggle, onToggle }) {
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState(new Set());
  const cfg = TYPE_CFG[type];
  const Icon = cfg.icon;
  const today = new Date().toISOString().slice(0, 10);
  const isReadOnly = type === "achievements";

  const toggleExpand = (key) => setExpanded(prev => {
    const next = new Set(prev);
    next.has(key) ? next.delete(key) : next.add(key);
    return next;
  });

  const fmtDate = (d) => d ? new Date(d).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "";

  if (!items || items.length === 0) {
    return (
      <div className="text-center py-12 text-gray-400" data-testid={`${type}-empty-state`}>
        <Icon className="w-8 h-8 mx-auto mb-2 opacity-30" />
        <p className="text-sm">No {cfg.noun}s recorded yet</p>
      </div>
    );
  }

  const renderRow = (item, idx, listKey, { standing = false, overdue = false, done = false } = {}) => {
    const key = `${listKey}-${item.meeting_id}-${item.id}-${idx}`;
    const isExpanded = expanded.has(key);
    const dotColor = isReadOnly ? cfg.accent : done ? "#059669" : standing ? "#6366F1" : cfg.accent;
    return (
      <div key={key} className="relative">
        {isReadOnly ? (
          <div
            className="absolute left-[-28px] top-1 w-5 h-5 rounded-full border-2 border-white shadow-sm flex items-center justify-center flex-shrink-0"
            style={{ background: dotColor }}
          >
            <Icon className="w-2.5 h-2.5 text-white" />
          </div>
        ) : (
          <button
            onClick={e => { e.stopPropagation(); canToggle && onToggle(item, !done); }}
            disabled={!canToggle}
            className={`absolute left-[-28px] top-1 w-5 h-5 rounded-full border-2 border-white shadow-sm flex items-center justify-center flex-shrink-0 ${canToggle ? "cursor-pointer" : "cursor-default"}`}
            style={{ background: dotColor }}
            title={canToggle ? (done ? "Mark as outstanding" : "Mark as done") : ""}
            data-testid={`${type}-toggle-${key}`}
          >
            {done ? <Check className="w-2.5 h-2.5 text-white" /> : <Icon className="w-2.5 h-2.5 text-white" />}
          </button>
        )}

        <button className="w-full text-left group" onClick={() => toggleExpand(key)} data-testid={`${type}-item-${key}`}>
          <div className="flex items-start gap-2">
            <p className={`text-sm font-medium leading-snug flex-1 transition-colors ${done ? "line-through text-gray-400" : "text-gray-900"}`}>
              {item.text}
            </p>
            {item.is_rolled_over && (
              <span className="text-[10px] font-semibold text-gray-500 bg-gray-100 border border-gray-200 px-1.5 py-0.5 rounded-full flex-shrink-0 mt-0.5">Rolled over</span>
            )}
            {standing && (
              <span className="text-[10px] font-semibold text-indigo-700 bg-indigo-50 border border-indigo-200 px-1.5 py-0.5 rounded-full flex-shrink-0 mt-0.5">Standing</span>
            )}
            {overdue && (
              <span className="text-[10px] font-semibold text-red-600 bg-red-50 border border-red-200 px-1.5 py-0.5 rounded-full flex-shrink-0 mt-0.5">Overdue</span>
            )}
            <ChevronRight className={`w-3.5 h-3.5 text-gray-300 flex-shrink-0 mt-1 transition-transform ${isExpanded ? "rotate-90" : ""}`} />
          </div>
          <div className="flex items-center gap-1.5 mt-1 flex-wrap">
            <span className="text-xs text-gray-400">{item.meeting_title}</span>
            <span className="text-gray-200 text-xs">·</span>
            <span className="text-xs font-medium text-gray-500">{fmtDate(item.meeting_date)}</span>
            {!isReadOnly && !standing && item.due_date && (
              <>
                <span className="text-gray-200 text-xs">·</span>
                <span className={`text-xs ${overdue ? "text-red-500 font-medium" : "text-gray-400"}`}>Due: {item.due_date}</span>
              </>
            )}
            {standing && item.trigger && (
              <>
                <span className="text-gray-200 text-xs">·</span>
                <span className="text-xs text-gray-400">Trigger: {item.trigger}</span>
              </>
            )}
            {done && item.completed_at && (
              <>
                <span className="text-gray-200 text-xs">·</span>
                <span className="text-xs text-emerald-600">Completed {fmtDate(item.completed_at)}</span>
              </>
            )}
          </div>
        </button>

        {isExpanded && (
          <div className="mt-2.5 bg-gray-50 border border-gray-200 rounded-lg p-3">
            <p className="text-sm text-gray-700 leading-relaxed mb-3">{item.text}</p>
            <button
              onClick={() => navigate(`/meetings/${item.meeting_id}/report`)}
              className="inline-flex items-center gap-1.5 text-xs font-medium text-[#1E3A8A] hover:text-[#1E3A8A]/80 hover:underline"
              data-testid={`${type}-view-meeting-${key}`}
            >
              <ExternalLink className="w-3.5 h-3.5" /> View in meeting report
            </button>
          </div>
        )}
      </div>
    );
  };

  if (isReadOnly) {
    return (
      <div className="relative pl-7 space-y-5" data-testid="achievements-timeline">
        <div className="absolute left-[11px] top-1 bottom-1 w-0.5 bg-gray-100" />
        {items.map((item, idx) => renderRow(item, idx, "ach"))}
      </div>
    );
  }

  // Actions / Learning Needs — Outstanding (overdue first) split from Completed (history)
  const isStanding = (item) => type === "actions" && item.action_type === "standing_commitment";
  const isOverdue = (item) => !item.completed && !isStanding(item) && item.due_date && item.due_date < today;

  const outstandingRaw = items.filter(i => !i.completed);
  const outstanding = [
    ...outstandingRaw.filter(isOverdue),
    ...outstandingRaw.filter(i => !isOverdue(i)),
  ];
  const completed = items.filter(i => i.completed)
    .sort((a, b) => (b.completed_at || b.meeting_date || "").localeCompare(a.completed_at || a.meeting_date || ""));

  return (
    <div className="space-y-8">
      <div>
        <h3 className="text-xs font-bold uppercase tracking-widest text-gray-400 mb-4 flex items-center gap-2">
          Outstanding
          {outstanding.length > 0 && <span className="text-[10px] bg-gray-100 text-gray-600 rounded-full px-1.5">{outstanding.length}</span>}
        </h3>
        {outstanding.length === 0 ? (
          <p className="text-sm text-gray-400" data-testid={`${type}-outstanding-empty`}>Nothing outstanding — you're all caught up.</p>
        ) : (
          <div className="relative pl-7 space-y-5">
            <div className="absolute left-[11px] top-1 bottom-1 w-0.5 bg-gray-100" />
            {outstanding.map((item, idx) => renderRow(item, idx, "outstanding", { standing: isStanding(item), overdue: isOverdue(item), done: false }))}
          </div>
        )}
      </div>

      <div>
        <h3 className="text-xs font-bold uppercase tracking-widest text-gray-400 mb-4 flex items-center gap-2">
          Completed
          {completed.length > 0 && <span className="text-[10px] bg-gray-100 text-gray-600 rounded-full px-1.5">{completed.length}</span>}
        </h3>
        {completed.length === 0 ? (
          <p className="text-sm text-gray-400" data-testid={`${type}-completed-empty`}>Nothing completed yet — your progress history will build up here.</p>
        ) : (
          <div className="relative pl-7 space-y-5">
            <div className="absolute left-[11px] top-1 bottom-1 w-0.5 bg-gray-100" />
            {completed.map((item, idx) => renderRow(item, idx, "completed", { standing: isStanding(item), overdue: false, done: true }))}
          </div>
        )}
      </div>
    </div>
  );
}

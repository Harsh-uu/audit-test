import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Check, ChevronRight, ExternalLink, Award, BookOpen, ClipboardList, Repeat } from "lucide-react";

// ── My Portfolio's Actions / Learning Needs / Achievements list ────────────
// Row style mirrors the Meeting Report's EvidenceTab.js exactly (checkbox
// toggle, same badge/colour conventions) rather than a generic timeline, per
// user feedback — so ticking an item off here feels identical to doing it
// from inside a meeting. Split into Outstanding (top) vs Completed/history
// (below) per spec. Achievements are read-only (a static icon, no checkbox).

const TYPE_CFG = {
  achievements:   { icon: Award,         noun: "achievement" },
  learning_needs: { icon: BookOpen,      noun: "learning need" },
  actions:        { icon: ClipboardList, noun: "action" },
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
    if (next.has(key)) next.delete(key);
    else next.add(key);
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
    return (
      <div
        key={key}
        className={`flex items-start gap-3 p-2.5 rounded-md border transition-all ${
          done ? "bg-gray-50 border-gray-100 opacity-70"
            : overdue ? "bg-red-50 border-red-200"
            : item.is_rolled_over ? "bg-amber-50 border-amber-200"
            : "bg-gray-50 border-transparent"
        }`}
      >
        {isReadOnly ? (
          <div className="w-5 h-5 rounded-full bg-emerald-100 flex items-center justify-center flex-shrink-0 mt-0.5">
            <Icon className="w-3 h-3 text-emerald-600" />
          </div>
        ) : (
          <button
            onClick={() => canToggle && onToggle(item, !done)}
            disabled={!canToggle}
            className={`w-5 h-5 rounded border-2 flex items-center justify-center flex-shrink-0 mt-0.5 transition-colors ${
              done ? "bg-emerald-500 border-emerald-500 text-white" : "border-gray-300 hover:border-emerald-400"
            } ${canToggle ? "cursor-pointer" : "cursor-default opacity-60"}`}
            title={canToggle ? (standing ? (done ? "Reopen" : "Close") : (done ? "Mark as outstanding" : "Mark as complete")) : ""}
            data-testid={`${type}-toggle-${key}`}
          >
            {done && <Check className="w-3 h-3" />}
          </button>
        )}

        <div className="flex-1 min-w-0 cursor-pointer" onClick={() => toggleExpand(key)} data-testid={`${type}-item-${key}`}>
          <div className="flex items-center gap-1.5 flex-wrap">
            <p className={`text-sm ${done ? "line-through text-gray-400" : "text-gray-800"}`}>{item.text}</p>
            {standing && (
              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-indigo-100 text-indigo-700 flex-shrink-0">
                <Repeat className="w-2.5 h-2.5" /> Standing
              </span>
            )}
            {overdue && (
              <span className="text-[10px] font-semibold text-red-600 bg-red-100 px-1.5 py-0.5 rounded-full flex-shrink-0">Overdue</span>
            )}
            {item.is_rolled_over && (
              <span className="text-[10px] font-semibold text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded-full flex-shrink-0">Rolled over</span>
            )}
          </div>
          <p className="text-xs text-gray-500 mt-0.5">
            {item.meeting_title} · {fmtDate(item.meeting_date)}
            {!isReadOnly && !standing && item.due_date && ` · Due: ${item.due_date}`}
            {standing && item.trigger && ` · Trigger: ${item.trigger}`}
            {done && item.completed_at && ` · Completed ${fmtDate(item.completed_at)}`}
          </p>
          {isExpanded && (
            <div className="mt-2 pt-2 border-t border-gray-200">
              <button
                onClick={(e) => { e.stopPropagation(); navigate(`/meetings/${item.meeting_id}/report`); }}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-[#1E3A8A] hover:underline"
                data-testid={`${type}-view-meeting-${key}`}
              >
                <ExternalLink className="w-3.5 h-3.5" /> View in meeting report
              </button>
            </div>
          )}
        </div>
        <ChevronRight
          className={`w-3.5 h-3.5 text-gray-300 flex-shrink-0 mt-1 transition-transform cursor-pointer ${isExpanded ? "rotate-90" : ""}`}
          onClick={() => toggleExpand(key)}
        />
      </div>
    );
  };

  if (isReadOnly) {
    return (
      <div className="space-y-2" data-testid="achievements-list">
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
        <h3 className="text-xs font-bold uppercase tracking-widest text-gray-400 mb-3 flex items-center gap-2">
          Outstanding
          {outstanding.length > 0 && <span className="text-[10px] bg-gray-100 text-gray-600 rounded-full px-1.5">{outstanding.length}</span>}
        </h3>
        {outstanding.length === 0 ? (
          <p className="text-sm text-gray-400" data-testid={`${type}-outstanding-empty`}>Nothing outstanding — you're all caught up.</p>
        ) : (
          <div className="space-y-2">
            {outstanding.map((item, idx) => renderRow(item, idx, "outstanding", { standing: isStanding(item), overdue: isOverdue(item), done: false }))}
          </div>
        )}
      </div>

      <div>
        <h3 className="text-xs font-bold uppercase tracking-widest text-gray-400 mb-3 flex items-center gap-2">
          Completed
          {completed.length > 0 && <span className="text-[10px] bg-gray-100 text-gray-600 rounded-full px-1.5">{completed.length}</span>}
        </h3>
        {completed.length === 0 ? (
          <p className="text-sm text-gray-400" data-testid={`${type}-completed-empty`}>Nothing completed yet — your progress history will build up here.</p>
        ) : (
          <div className="space-y-2">
            {completed.map((item, idx) => renderRow(item, idx, "completed", { standing: isStanding(item), overdue: false, done: true }))}
          </div>
        )}
      </div>
    </div>
  );
}

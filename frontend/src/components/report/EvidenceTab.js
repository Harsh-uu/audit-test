import React, { useState, useRef, useEffect } from "react";
import axios from "axios";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import {
  Edit3, CheckCircle, Clock, Pause, AlertTriangle, Plus, Trash2, Check, Shield, RefreshCw,
  ChevronDown, ChevronUp, Loader2, Quote, Lightbulb, CheckSquare, Square, Zap, Lock, Unlock, Star, BookOpen, FileText, ArrowUp,
} from "lucide-react";

// ── Severity config ──────────────────────────────────────────────────────────
const SEV = {
  high:   { bg: "bg-red-50",    border: "border-red-300",   text: "text-red-700",   badge: "bg-red-100 text-red-700",   icon: "text-red-500"   },
  medium: { bg: "bg-amber-50",  border: "border-amber-300", text: "text-amber-800", badge: "bg-amber-100 text-amber-700", icon: "text-amber-500" },
  low:    { bg: "bg-gray-50",   border: "border-gray-200",  text: "text-gray-700",  badge: "bg-gray-100 text-gray-600",  icon: "text-gray-400"  },
};

// ── Single risk card ──────────────────────────────────────────────────────────
function RiskCard({ risk, meetingId, canEdit, canToggle, onToggleResolved, onCreateAction, linkedActionId, onViewAction }) {
  const { getAuthConfig, API } = useAuth();
  const [open, setOpen] = useState(false);
  const [loadingSugg, setLoadingSugg] = useState(false);
  const [excerpt, setExcerpt] = useState(risk.transcript_excerpt || null);
  const [suggestions, setSuggestions] = useState(risk.suggested_resolutions || null);
  const sev = SEV[risk.severity?.toLowerCase()] || SEV.low;

  const handleDrillIn = async () => {
    const willOpen = !open;
    setOpen(willOpen);
    if (!willOpen || (excerpt !== null && suggestions !== null)) return;
    setLoadingSugg(true);
    try {
      const { data } = await axios.post(`${API}/review/${meetingId}/risks/${risk.id}/suggestions`, null, getAuthConfig());
      setExcerpt(data.transcript_excerpt || "");
      setSuggestions(data.suggested_resolutions || []);
    } catch { setSuggestions([]); setExcerpt(""); }
    finally { setLoadingSugg(false); }
  };

  return (
    <div className={`rounded-lg border-2 ${sev.border} ${risk.is_resolved ? "opacity-60" : ""} transition-opacity`} data-testid={`risk-card-${risk.id}`}>
      {/* Header row */}
      <div className={`flex items-start gap-3 p-3 ${sev.bg} rounded-t-lg`}>
        {/* Tick */}
        <button
          onClick={() => canToggle && onToggleResolved(risk.id, !risk.is_resolved)}
          className={`flex-shrink-0 mt-0.5 ${canToggle ? "cursor-pointer" : "cursor-default"}`}
          title={risk.is_resolved ? "Mark unresolved" : "Mark resolved"}
          data-testid={`risk-toggle-${risk.id}`}
        >
          {risk.is_resolved
            ? <CheckSquare className="w-4 h-4 text-emerald-600" />
            : <Square className={`w-4 h-4 ${sev.icon}`} />}
        </button>

        <div className="flex-1 min-w-0">
          <p className={`text-sm font-medium ${risk.is_resolved ? "line-through text-gray-400" : "text-gray-800"}`}>{risk.text}</p>
          {risk.is_resolved && risk.resolved_by && (
            <p className="text-xs text-emerald-600 mt-0.5">Resolved by {risk.resolved_by}</p>
          )}
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${sev.badge}`}>
            {(risk.severity || "low").toUpperCase()}
          </span>
          <button
            onClick={handleDrillIn}
            className="flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-800 font-medium"
            data-testid={`risk-expand-${risk.id}`}
          >
            {open ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            {open ? "Less" : "Detail"}
          </button>
        </div>
      </div>

      {/* Drill-in panel */}
      {open && (
        <div className="p-4 space-y-4 border-t border-gray-200 bg-white rounded-b-lg">
          {loadingSugg ? (
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Loader2 className="w-4 h-4 animate-spin text-indigo-400" />
              Analysing transcript for context…
            </div>
          ) : (
            <>
              {/* Transcript excerpt */}
              {excerpt && (
                <div className="space-y-1">
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-gray-500 uppercase tracking-wide">
                    <Quote className="w-3 h-3" /> From the transcript
                  </div>
                  <blockquote className="text-sm text-gray-700 italic border-l-4 border-indigo-200 pl-3 py-1 bg-indigo-50 rounded-r-md">
                    "{excerpt}"
                  </blockquote>
                </div>
              )}

              {/* Suggested resolutions */}
              {suggestions?.length > 0 && (
                <div className="space-y-2">
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-gray-500 uppercase tracking-wide">
                    <Lightbulb className="w-3 h-3" /> Suggested resolutions
                  </div>
                  <ul className="space-y-1.5">
                    {suggestions.map((s, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                        <span className="mt-1 w-1.5 h-1.5 rounded-full bg-indigo-400 flex-shrink-0" />
                        {s}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {!excerpt && !suggestions?.length && (
                <p className="text-xs text-gray-400 italic">No additional detail available.</p>
              )}

              {/* Create Action button + link to the resulting action, if one has been created */}
              {((canEdit && !risk.is_resolved) || linkedActionId) && (
                <div className="flex items-center justify-between gap-3">
                  {canEdit && !risk.is_resolved && (
                    <button
                      onClick={() => onCreateAction(risk)}
                      className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 font-medium"
                      data-testid={`risk-create-action-${risk.id}`}
                    >
                      <Zap className="w-3 h-3" /> Create Action from this Risk
                    </button>
                  )}
                  {linkedActionId && (
                    <button
                      onClick={() => onViewAction(linkedActionId)}
                      className="ml-auto flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-800 font-medium hover:underline flex-shrink-0"
                      data-testid={`view-linked-action-${risk.id}`}
                    >
                      View Action <ArrowUp className="w-3 h-3" />
                    </button>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── Risks section ─────────────────────────────────────────────────────────────
function RisksSection({ risks, meetingId, onRisksChange, onCreateAction, canEdit, canToggle, riskActionLinks, onViewAction }) {
  const { getAuthConfig, API } = useAuth();

  const handleToggleResolved = async (riskId, resolved) => {
    const { data } = await axios.patch(`${API}/review/${meetingId}/risks/${riskId}`, { is_resolved: resolved }, getAuthConfig());
    onRisksChange?.(data.risks);
  };

  const open = risks.filter(r => !r.is_resolved);
  const resolved = risks.filter(r => r.is_resolved);

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm" id="section-risks">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-gray-900 text-sm font-display flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-500" /> Areas for Attention
        </h3>
        <span className="text-xs text-gray-400">{open.length} open · {resolved.length} resolved</span>
      </div>
      <div className="space-y-2" data-testid="risks-list">
        {open.map(risk => (
          <RiskCard key={risk.id || risk.text} risk={risk} meetingId={meetingId} canEdit={canEdit} canToggle={canToggle || canEdit}
            onToggleResolved={handleToggleResolved} onCreateAction={onCreateAction}
            linkedActionId={riskActionLinks?.[risk.id]} onViewAction={onViewAction} />
        ))}
        {resolved.length > 0 && (
          <details className="mt-2">
            <summary className="text-xs text-gray-400 cursor-pointer hover:text-gray-600 select-none">
              {resolved.length} resolved risk{resolved.length > 1 ? "s" : ""}
            </summary>
            <div className="mt-2 space-y-2">
              {resolved.map(risk => (
                <RiskCard key={risk.id || risk.text} risk={risk} meetingId={meetingId} canEdit={canEdit} canToggle={canToggle || canEdit}
                  onToggleResolved={handleToggleResolved} onCreateAction={onCreateAction}
                  linkedActionId={riskActionLinks?.[risk.id]} onViewAction={onViewAction} />
              ))}
            </div>
          </details>
        )}
      </div>
    </div>
  );
}

/**
 * Renders the AI-generated summary which follows the format:
 *
 *   Intro sentence one. Intro sentence two.
 *
 *   - Bullet one
 *   - Bullet two
 *
 *   Closing sentence one. Closing sentence two.
 *
 * Falls back to a plain paragraph for older single-block summaries.
 */
function SummaryBody({ text }) {
  if (!text) return <p className="text-sm text-gray-400 italic">No summary available.</p>;

  const blocks = text.split(/\n\n+/);
  // If there's only one block (old format), just render it as text
  if (blocks.length <= 1) {
    return <p className="text-sm text-gray-700 leading-relaxed">{text}</p>;
  }

  return (
    <div className="space-y-3">
      {blocks.map((block, i) => {
        const lines = block.split("\n").map(l => l.trim()).filter(Boolean);
        const isBulletBlock = lines.length > 0 && lines.every(l => l.startsWith("- "));
        if (isBulletBlock) {
          return (
            <ul key={i} className="space-y-1.5 pl-1">
              {lines.map((line, j) => (
                <li key={j} className="flex items-start gap-2 text-sm text-gray-700">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[#1E3A8A]/40 flex-shrink-0" />
                  <span className="leading-relaxed">{line.replace(/^-\s*/, "")}</span>
                </li>
              ))}
            </ul>
          );
        }
        return (
          <p key={i} className="text-sm text-gray-700 leading-relaxed">{block}</p>
        );
      })}
    </div>
  );
}

// ── Achievements section ──────────────────────────────────────────────────────
function AchievementsSection({ achievements }) {
  const list = Array.isArray(achievements) ? achievements : [];
  if (!list.length) return null;

  return (
    <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-5 shadow-sm" id="section-achievements" data-testid="achievements-section">
      <div className="flex items-center gap-2 mb-4">
        <div className="w-7 h-7 rounded-full bg-emerald-500 flex items-center justify-center flex-shrink-0">
          <Star className="w-3.5 h-3.5 text-white" fill="currentColor" />
        </div>
        <h3 className="font-semibold text-emerald-900 text-sm font-display">Achievements</h3>
        <span className="text-xs text-emerald-600 ml-auto">{list.length} noted</span>
      </div>
      <ul className="space-y-2.5" data-testid="achievements-list">
        {list.map((ach, i) => (
          <li
            key={ach.id || i}
            className="flex items-start gap-3 bg-white rounded-md px-3.5 py-3 border border-emerald-100"
            data-testid={`achievement-${i}`}
          >
            <span className="mt-0.5 w-5 h-5 rounded-full bg-emerald-100 flex items-center justify-center flex-shrink-0">
              <Star className="w-2.5 h-2.5 text-emerald-600" fill="currentColor" />
            </span>
            <p className="text-sm text-gray-800 leading-relaxed">{ach.text || ach.description}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}


export const EvidenceTab = React.memo(function EvidenceTab({
  meeting,
  analysis,
  canReview,
  editingSummary,
  setEditingSummary,
  summaryText,
  setSummaryText,
  saveSummary,
  addingAction,
  setAddingAction,
  newAction,
  setNewAction,
  addAction,
  removeAction,
  toggleActionComplete,
  actionMessage,
  onSummaryRegenerated,
  onAnalysisChange,
  isLocked = false,
  onReopenRequest,
  onApproveReopen,
}) {
  const canEdit = canReview;
  const { getAuthConfig, API, user } = useAuth();
  const [showReopenForm, setShowReopenForm] = useState(false);
  const [reopenReason, setReopenReason] = useState("");
  const [reopenSubmitting, setReopenSubmitting] = useState(false);

  // ── Learning Needs local state ───────────────────────────────────────────────
  const [learningNeeds, setLearningNeeds] = useState(() => Array.isArray(analysis?.learning_needs) ? analysis.learning_needs : []);
  const [addingLN, setAddingLN] = useState(false);
  const [newLN, setNewLN] = useState({ text: "", assigned_to: "", assigned_to_user_id: "", due_date: "" });
  const [lnMessage, setLnMessage] = useState("");
  const [lnSaving, setLnSaving] = useState(false);

  const saveLearningNeeds = async (updated) => {
    setLnSaving(true);
    try {
      await axios.put(`${API}/review/${meeting.id}/learning_needs`, { learning_needs: updated }, getAuthConfig());
      setLearningNeeds(updated);
      onAnalysisChange?.({ ...analysis, learning_needs: updated });
      setLnMessage("Saved");
      setTimeout(() => setLnMessage(""), 2000);
    } catch (err) {
      const detail = err?.response?.data?.detail || err?.message || "Unknown error";
      console.error("Learning needs save failed:", err?.response?.status, detail);
      setLnMessage(`Error saving — ${detail}`);
      setTimeout(() => setLnMessage(""), 6000);
      return false;
    } finally { setLnSaving(false); }
    return true;
  };

  const addLN = async () => {
    if (!newLN.text.trim()) return;
    const updated = [...learningNeeds, { id: `ln_${Date.now()}`, text: newLN.text.trim(), assigned_to: newLN.assigned_to.trim() || null, assigned_to_user_id: newLN.assigned_to_user_id || null, due_date: newLN.due_date.trim() || null, completed: false }];
    // Save first — only close the form if it succeeds so data isn't lost on failure
    const ok = await saveLearningNeeds(updated);
    if (ok) {
      setAddingLN(false);
      setNewLN({ text: "", assigned_to: "", assigned_to_user_id: "", due_date: "" });
    }
  };

  const removeLN = async (idx) => {
    await saveLearningNeeds(learningNeeds.filter((_, i) => i !== idx));
  };

  const toggleLNComplete = async (idx, completed) => {
    const prev = learningNeeds;
    const updated = learningNeeds.map((ln, i) => i === idx ? { ...ln, completed } : ln);
    // Optimistic: flip the checkbox immediately, sync to the server in the background
    setLearningNeeds(updated);
    onAnalysisChange?.({ ...analysis, learning_needs: updated });
    try {
      await axios.put(`${API}/review/${meeting.id}/learning_needs`, { learning_needs: updated }, getAuthConfig());
    } catch (err) {
      // Roll back on failure
      setLearningNeeds(prev);
      onAnalysisChange?.({ ...analysis, learning_needs: prev });
      const detail = err?.response?.data?.detail || err?.message || "Unknown error";
      toast.error(`Failed to update learning need — ${detail}`);
    }
  };

  // Who can approve a reopen request? Listed attendees who are not the requester
  const isReopenRequester = meeting?.reopen_requested_by === user?.id;
  const isAttendee = meeting?.attendees?.some(a => a.user_id === user?.id);
  const isDifferentManager = (user?.role === "manager" || user?.role === "admin") && !isReopenRequester;
  const canApproveReopen = meeting?.reopen_requested && (isAttendee || isDifferentManager) && !isReopenRequester;
  const canRequestReopen = isLocked && !meeting?.reopen_requested && (user?.role === "manager" || user?.role === "admin");

  const handleReopenSubmit = async () => {
    if (!reopenReason.trim()) return;
    setReopenSubmitting(true);
    try {
      await onReopenRequest?.(reopenReason.trim());
      setShowReopenForm(false);
      setReopenReason("");
    } finally {
      setReopenSubmitting(false);
    }
  };

  const handleCreateActionFromRisk = (risk) => {
    pendingRiskIdRef.current = risk.id;
    setNewAction(a => ({ ...a, text: `[Risk] ${risk.text}` }));
    setAddingAction(true);
    // Scroll to actions section
    setTimeout(() => document.getElementById("section-actions")?.scrollIntoView({ behavior: "smooth", block: "center" }), 100);
  };

  // ── Risk → created-action linking ────────────────────────────────────────
  // "Create Action from this Risk" only opens/pre-fills the Add Action form —
  // the action itself isn't created until the user submits it. Once the
  // actions array grows while a risk-originated draft was pending, link the
  // newly-appended action back to that risk so a "View Action" link can be
  // shown on the risk card (there was previously no confirmation at all).
  const [riskActionLinks, setRiskActionLinks] = useState({});
  const [highlightedActionId, setHighlightedActionId] = useState(null);
  const pendingRiskIdRef = useRef(null);
  const prevActionsLenRef = useRef(analysis?.actions?.length || 0);

  useEffect(() => {
    const actions = analysis?.actions || [];
    if (pendingRiskIdRef.current && actions.length > prevActionsLenRef.current) {
      const created = actions[actions.length - 1];
      if (created?.id) {
        setRiskActionLinks(prev => ({ ...prev, [pendingRiskIdRef.current]: created.id }));
      }
      pendingRiskIdRef.current = null;
    }
    prevActionsLenRef.current = actions.length;
  }, [analysis?.actions]);

  const handleViewAction = (actionId) => {
    const el = document.getElementById(`action-row-${actionId}`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    setHighlightedActionId(actionId);
    setTimeout(() => setHighlightedActionId(null), 2000);
  };

  const [regenerating, setRegenerating] = useState(false);
  const [regenError, setRegenError] = useState("");

  const handleRegenerate = async () => {
    setRegenerating(true);
    setRegenError("");
    try {
      const { data } = await axios.post(
        `${API}/review/${meeting.id}/regenerate-summary`,
        {},
        getAuthConfig(),
      );
      if (onSummaryRegenerated) onSummaryRegenerated(data.summary);
    } catch (err) {
      setRegenError(err.response?.data?.detail || "Regeneration failed — please try again");
    }
    setRegenerating(false);
  };

  const scrollToSection = (id) =>
    setTimeout(() => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);

  const hasAchievements = Array.isArray(analysis?.achievements) && analysis.achievements.length > 0;
  const hasActions = (analysis?.actions?.length > 0) || canReview;
  const hasLearning = (learningNeeds.length > 0) || canEdit;
  const hasRisks = analysis?.risks?.length > 0;

  const jumpLinks = [
    { id: "section-summary",      label: "Summary",      Icon: FileText,     show: true,            cls: "text-gray-600 hover:bg-gray-100 border-gray-200" },
    { id: "section-achievements", label: "Achievements", Icon: Star,         show: hasAchievements, cls: "text-emerald-700 hover:bg-emerald-50 border-emerald-200", count: analysis?.achievements?.length },
    { id: "section-actions",      label: "Actions",      Icon: CheckSquare,  show: hasActions,      cls: "text-[#1E3A8A] hover:bg-blue-50 border-blue-200",    count: analysis?.actions?.length || null },
    { id: "section-learning",     label: "Learning",     Icon: BookOpen,     show: hasLearning,     cls: "text-teal-700 hover:bg-teal-50 border-teal-200",      count: learningNeeds.length || null },
    { id: "section-risks", label: "Areas for Attention", Icon: AlertTriangle, show: hasRisks, cls: "text-amber-700 hover:bg-amber-50 border-amber-200", count: analysis?.risks?.length },
  ].filter(l => l.show);

  return (
    <div className="space-y-6">
      {/* Quick-jump strip */}
      {jumpLinks.length > 1 && (
        <div className="flex items-center gap-2 flex-wrap" data-testid="overview-jump-strip">
          {jumpLinks.map(({ id, label, Icon, cls, count }) => (
            <button
              key={id}
              onClick={() => scrollToSection(id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs font-medium transition-colors bg-white ${cls}`}
              data-testid={`jump-${id}`}
            >
              <Icon className="w-3 h-3" />
              {label}
              {count != null && count > 0 && (
                <span className="ml-0.5 bg-current/10 rounded-full px-1.5 py-0.5 text-[10px] font-semibold leading-none opacity-80">
                  {count}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
      {/* Summary */}
      <div className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm" id="section-summary">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-gray-900 text-sm font-display">Meeting Summary</h3>
          {canReview && !editingSummary && (
            <div className="flex items-center gap-2">
              <button
                onClick={handleRegenerate}
                disabled={regenerating}
                className="text-xs text-gray-500 flex items-center gap-1 hover:text-[#1E3A8A] disabled:opacity-50"
                title="Regenerate summary in structured format"
                data-testid="regenerate-summary-btn"
              >
                <RefreshCw className={`w-3 h-3 ${regenerating ? "animate-spin" : ""}`} />
                {regenerating ? "Regenerating…" : "Regenerate"}
              </button>
              <button onClick={() => setEditingSummary(true)} className="text-xs text-[#1E3A8A] flex items-center gap-1 hover:underline" data-testid="edit-summary-btn">
                <Edit3 className="w-3 h-3" /> Edit
              </button>
            </div>
          )}
        </div>
        {regenError && <p className="text-xs text-red-500 mb-2">{regenError}</p>}
        {editingSummary ? (
          <div>
            <textarea value={summaryText} onChange={e => setSummaryText(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm resize-none focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]" rows={10} data-testid="summary-textarea" />
            <div className="flex gap-2 mt-2">
              <button onClick={saveSummary} className="text-xs bg-[#1E3A8A] text-white px-3 py-1.5 rounded hover:bg-[#1E40AF]" data-testid="save-summary-btn">Save</button>
              <button onClick={() => setEditingSummary(false)} className="text-xs border border-gray-300 text-gray-600 px-3 py-1.5 rounded">Cancel</button>
            </div>
          </div>
        ) : (
          <div data-testid="summary-text">
            <SummaryBody text={analysis.edited_summary || analysis.summary} />
          </div>
        )}
      </div>

      {/* Achievements */}
      <AchievementsSection achievements={analysis.achievements} />

      {/* Pauses */}
      {meeting.paused_periods?.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <Pause className="w-4 h-4 text-amber-600" />
            <h4 className="text-sm font-medium text-amber-800">Recording Paused</h4>
          </div>
          <p className="text-xs text-amber-700 mb-2">The recording was paused during this meeting. Paused sections were not recorded.</p>
          {meeting.paused_periods.map((p, i) => (
            <div key={p.paused_at || i} className="text-xs text-amber-700 font-mono">
              Pause {i + 1}: {new Date(p.paused_at).toLocaleTimeString()} — {p.resumed_at ? new Date(p.resumed_at).toLocaleTimeString() : "ongoing"} ({p.duration_seconds}s)
            </div>
          ))}
        </div>
      )}

      {/* Actions */}      {(analysis.actions?.length > 0 || canReview) && (
        <div id="section-actions" className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold text-gray-900 text-sm font-display">
              Action Items
              {analysis.actions?.length > 0 && (
                <span className="ml-2 text-xs font-normal text-gray-400">({analysis.actions.length})</span>
              )}
            </h3>
            {canReview && !addingAction && (
              <button onClick={() => setAddingAction(true)} className="flex items-center gap-1 text-xs text-[#1E3A8A] hover:underline font-medium" data-testid="add-action-btn">
                <Plus className="w-3 h-3" /> Add Action
              </button>
            )}
          </div>

          <div className="space-y-2" data-testid="actions-list">
            {(analysis.actions || []).map((action, i) => (
              <div key={action.id || action.text?.slice(0, 40) || i} id={action.id ? `action-row-${action.id}` : undefined} className={`flex items-start gap-3 p-2.5 rounded-md group border transition-all ${highlightedActionId === action.id ? "ring-2 ring-indigo-400 bg-indigo-50 border-indigo-200" : action.completed ? "bg-gray-50 border-gray-100 opacity-70" : action.is_rolled_over ? "bg-amber-50 border-amber-200" : "bg-gray-50 border-transparent"}`}>
                <button
                  onClick={() => toggleActionComplete(action.id || i, !action.completed)}
                  className={`w-5 h-5 rounded border-2 flex items-center justify-center flex-shrink-0 mt-0.5 transition-colors ${action.completed ? "bg-emerald-500 border-emerald-500 text-white" : "border-gray-300 hover:border-emerald-400"}`}
                  title={action.completed ? "Mark as outstanding" : "Mark as complete"}
                  data-testid={`complete-action-${i}`}
                >
                  {action.completed && <Check className="w-3 h-3" />}
                </button>
                <div className="flex-1 min-w-0">
                  <p className={`text-sm ${action.completed ? "line-through text-gray-400" : "text-gray-800"}`}>{action.text}</p>
                  {action.is_rolled_over && !action.completed && (
                    <p className="text-xs text-amber-600 font-medium mt-0.5">Carried over from: {action.source_meeting_title}</p>
                  )}
                  {(action.assigned_to || action.due_date) && (
                    <p className="text-xs text-gray-500 mt-0.5">
                      {action.assigned_to && `Assigned: ${action.assigned_to}`}
                      {action.assigned_to && action.due_date && " · "}
                      {action.due_date && `Due: ${action.due_date}`}
                    </p>
                  )}
                </div>
                {canReview && !action.is_rolled_over && (
                  <button onClick={() => removeAction(i)} className="opacity-0 group-hover:opacity-100 p-1 text-gray-400 hover:text-red-500 transition-all rounded flex-shrink-0" data-testid={`remove-action-${i}`} title="Remove action">
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            ))}
            {analysis.actions?.length === 0 && !addingAction && (
              <p className="text-sm text-gray-400 py-2 text-center">No actions yet — add one below</p>
            )}
          </div>

          {addingAction && (
            <div className="mt-3 border border-dashed border-[#1E3A8A] rounded-md p-3 bg-blue-50 fade-in" data-testid="add-action-form">
              <p className="text-xs font-semibold text-[#1E3A8A] mb-2">New Action</p>
              <input
                type="text"
                value={newAction.text}
                onChange={e => setNewAction(a => ({ ...a, text: e.target.value }))}
                placeholder="Describe the action required..."
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] bg-white mb-2"
                data-testid="new-action-text"
                autoFocus
                onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); addAction(); } }}
              />
              <div className="grid grid-cols-2 gap-2 mb-3">
                <select
                  value={newAction.assigned_to_user_id}
                  onChange={e => {
                    const uid = e.target.value;
                    const att = (meeting.attendees || []).find(a => a.user_id === uid);
                    setNewAction(a => ({ ...a, assigned_to_user_id: uid, assigned_to: att ? att.name : "" }));
                  }}
                  className="px-3 py-1.5 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] bg-white"
                  data-testid="new-action-assigned"
                >
                  <option value="">Assigned to — please select</option>
                  {(meeting.attendees || []).map(a => (
                    <option key={a.user_id} value={a.user_id}>{a.name}</option>
                  ))}
                </select>
                <input type="text" value={newAction.due_date} onChange={e => setNewAction(a => ({ ...a, due_date: e.target.value }))} placeholder="Due date (optional)" className="px-3 py-1.5 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] bg-white" data-testid="new-action-due" />
              </div>
              <div className="flex gap-2">
                <button onClick={addAction} disabled={!newAction.text.trim()} className="flex items-center gap-1.5 bg-[#1E3A8A] text-white px-3 py-1.5 rounded-md text-xs font-medium hover:bg-[#1E40AF] disabled:opacity-50 transition-colors" data-testid="save-new-action-btn">
                  <Plus className="w-3 h-3" /> Add Action
                </button>
                <button onClick={() => { setAddingAction(false); setNewAction({ text: "", assigned_to: "", assigned_to_user_id: "", due_date: "" }); }} className="px-3 py-1.5 border border-gray-300 text-gray-600 rounded-md text-xs hover:bg-gray-50 transition-colors" data-testid="cancel-add-action-btn">
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Learning Needs */}
      {(learningNeeds.length > 0 || canEdit) && (
        <div className="bg-white border border-teal-100 rounded-lg p-5 shadow-sm" id="section-learning" data-testid="learning-needs-section">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold text-gray-900 text-sm flex items-center gap-2 font-display" data-testid="learning-needs-heading">
              <BookOpen className="w-4 h-4 text-teal-600" />
              Learning Needs
              {learningNeeds.length > 0 && (
                <span className="ml-1 text-xs font-normal text-gray-400">({learningNeeds.length})</span>
              )}
            </h3>
            {canEdit && !addingLN && !isLocked && (
              <button onClick={() => setAddingLN(true)} className="flex items-center gap-1 text-xs text-teal-700 hover:underline font-medium" data-testid="add-learning-need-btn">
                <Plus className="w-3 h-3" /> Add
              </button>
            )}
          </div>

          <div className="space-y-2" data-testid="learning-needs-list">
            {learningNeeds.map((ln, i) => (
              <div key={ln.id || i} className={`flex items-start gap-3 p-2.5 rounded-md group border transition-colors ${ln.completed ? "bg-gray-50 border-gray-100 opacity-70" : "bg-teal-50 border-teal-100"}`}>
                <button
                  onClick={() => !isLocked && toggleLNComplete(i, !ln.completed)}
                  disabled={isLocked}
                  className={`w-5 h-5 rounded border-2 flex items-center justify-center flex-shrink-0 mt-0.5 transition-colors ${ln.completed ? "bg-teal-600 border-teal-600 text-white" : "border-teal-300 hover:border-teal-500"}`}
                  title={ln.completed ? "Mark as outstanding" : "Mark as addressed"}
                  data-testid={`complete-ln-${i}`}
                >
                  {ln.completed && <Check className="w-3 h-3" />}
                </button>
                <div className="flex-1 min-w-0">
                  <p className={`text-sm ${ln.completed ? "line-through text-gray-400" : "text-gray-800"}`}>{ln.text}</p>
                  {(ln.assigned_to || ln.due_date) && (
                    <p className="text-xs text-gray-500 mt-0.5">
                      {ln.assigned_to && `Assigned: ${ln.assigned_to}`}
                      {ln.assigned_to && ln.due_date && " · "}
                      {ln.due_date && `Due: ${ln.due_date}`}
                    </p>
                  )}
                </div>
                {canEdit && !isLocked && (
                  <button onClick={() => removeLN(i)} className="opacity-0 group-hover:opacity-100 p-1 text-gray-400 hover:text-red-500 transition-all rounded flex-shrink-0" data-testid={`remove-ln-${i}`} title="Remove">
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            ))}
            {learningNeeds.length === 0 && !addingLN && (
              <p className="text-sm text-gray-400 py-2 text-center">No learning needs identified automatically — use + Add to record one manually</p>
            )}
          </div>

          {addingLN && (
            <div className="mt-3 border border-dashed border-teal-400 rounded-md p-3 bg-teal-50" data-testid="add-ln-form">
              <p className="text-xs font-semibold text-teal-800 mb-2">New Learning Need</p>
              <input
                type="text"
                value={newLN.text}
                onChange={e => setNewLN(n => ({ ...n, text: e.target.value }))}
                placeholder="Describe the knowledge or skill gap..."
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 bg-white mb-2"
                data-testid="new-ln-text"
                autoFocus
                onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); addLN(); } }}
              />
              <div className="grid grid-cols-2 gap-2 mb-3">
                <select
                  value={newLN.assigned_to_user_id}
                  onChange={e => {
                    const uid = e.target.value;
                    const att = (meeting.attendees || []).find(a => a.user_id === uid);
                    setNewLN(n => ({ ...n, assigned_to_user_id: uid, assigned_to: att ? att.name : "" }));
                  }}
                  className="px-3 py-1.5 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 bg-white"
                  data-testid="new-ln-assigned"
                >
                  <option value="">Assigned to — please select</option>
                  {(meeting.attendees || []).map(a => (
                    <option key={a.user_id} value={a.user_id}>{a.name}</option>
                  ))}
                </select>
                <input type="text" value={newLN.due_date} onChange={e => setNewLN(n => ({ ...n, due_date: e.target.value }))} placeholder="Due date (optional)" className="px-3 py-1.5 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 bg-white" data-testid="new-ln-due" />
              </div>
              <div className="flex gap-2 items-center">
                <button onClick={addLN} disabled={!newLN.text.trim() || lnSaving} className="flex items-center gap-1.5 bg-teal-700 text-white px-3 py-1.5 rounded-md text-xs font-medium hover:bg-teal-800 disabled:opacity-50 transition-colors" data-testid="save-new-ln-btn">
                  <Plus className="w-3 h-3" /> Add Learning Need
                </button>
                <button onClick={() => { setAddingLN(false); setNewLN({ text: "", assigned_to: "", assigned_to_user_id: "", due_date: "" }); }} className="px-3 py-1.5 border border-gray-300 text-gray-600 rounded-md text-xs hover:bg-gray-50 transition-colors" data-testid="cancel-add-ln-btn">
                  Cancel
                </button>
                {lnMessage && <span className={`text-xs ml-1 ${lnMessage === "Saved" ? "text-teal-600" : "text-red-500"}`}>{lnMessage}</span>}
              </div>
            </div>
          )}
          {lnMessage && !addingLN && <p className={`text-xs mt-2 ${lnMessage === "Saved" ? "text-teal-600" : "text-red-500"}`}>{lnMessage}</p>}
        </div>
      )}

      {/* Risks & Concerns */}
      {analysis.risks?.length > 0 && (
        <RisksSection
          risks={analysis.risks}
          meetingId={meeting.id}
          onRisksChange={updatedRisks => onAnalysisChange?.({ ...analysis, risks: updatedRisks })}
          onCreateAction={handleCreateActionFromRisk}
          canEdit={canEdit}
          canToggle={isLocked}
          riskActionLinks={riskActionLinks}
          onViewAction={handleViewAction}
        />
      )}

      {/* Attendees review status */}
      {meeting.attendees?.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
          <h3 className="font-semibold text-gray-900 text-sm mb-3 font-display">Review Status</h3>
          <div className="space-y-2">
            {meeting.attendees.map(a => (
              <div key={a.user_id} className="flex items-center justify-between">
                <span className="text-sm text-gray-700">{a.name}</span>
                {a.reviewed
                  ? <span className="text-xs text-emerald-600 flex items-center gap-1"><CheckCircle className="w-3 h-3" /> Reviewed</span>
                  : isLocked
                    ? <span className="text-xs text-emerald-600 flex items-center gap-1"><Shield className="w-3 h-3" /> Signed Off</span>
                    : <span className="text-xs text-amber-600 flex items-center gap-1"><Clock className="w-3 h-3" /> Pending</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Sign-off info — only render when actually signed off */}
      {meeting.sign_off_record?.signed_at && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-4">
          <div className="flex items-center gap-2">
            <Shield className="w-4 h-4 text-emerald-600" />
            <p className="text-sm font-medium text-emerald-800">Signed off by {meeting.sign_off_record.signed_by_name}</p>
          </div>
          <p className="text-xs text-emerald-600 mt-1">
            {new Date(meeting.sign_off_record.signed_at).toLocaleString("en-GB", {
              day: "2-digit", month: "short", year: "numeric",
              hour: "2-digit", minute: "2-digit"
            })}
          </p>
        </div>
      )}

      {/* ── Re-open controls (mutual consent unlock) ───────────────────────── */}

      {/* Approve re-open — shown to attendees (or different manager) when request is pending */}
      {meeting?.reopen_requested && canApproveReopen && (
        <div className="border border-amber-300 bg-amber-50 rounded-lg p-4" data-testid="reopen-approve-banner">
          <div className="flex items-start gap-3">
            <Unlock className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-amber-800">Re-open requested by {meeting.reopen_requested_by_name}</p>
              {meeting.reopen_reason && (
                <p className="text-xs text-amber-700 mt-1">Reason: <span className="italic">{meeting.reopen_reason}</span></p>
              )}
              <p className="text-xs text-amber-600 mt-1">Approving will unlock this report for editing. Both actions are recorded in the Audit Trail.</p>
              <button
                onClick={onApproveReopen}
                className="mt-2 flex items-center gap-1.5 text-xs px-3 py-1.5 bg-amber-600 text-white rounded-md hover:bg-amber-700 font-medium transition-colors"
                data-testid="approve-reopen-btn"
              >
                <Unlock className="w-3 h-3" /> Approve Re-open
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Waiting for approval — shown to the manager who requested it */}
      {meeting?.reopen_requested && isReopenRequester && (
        <div className="border border-blue-200 bg-blue-50 rounded-lg p-4" data-testid="reopen-waiting-banner">
          <div className="flex items-center gap-2 text-sm text-blue-700">
            <Lock className="w-4 h-4 flex-shrink-0" />
            <p>Re-open request sent — waiting for an attendee to approve before this report can be edited again.</p>
          </div>
        </div>
      )}

      {/* Request re-open — shown to manager when locked and no request pending */}
      {canRequestReopen && !showReopenForm && (
        <div className="text-center">
          <button
            onClick={() => setShowReopenForm(true)}
            className="flex items-center gap-1.5 mx-auto text-xs text-gray-400 hover:text-gray-700 transition-colors"
            data-testid="request-reopen-link"
          >
            <Unlock className="w-3 h-3" /> Request to re-open for editing
          </button>
        </div>
      )}

      {canRequestReopen && showReopenForm && (
        <div className="border border-gray-200 rounded-lg p-4 bg-gray-50" data-testid="reopen-form">
          <p className="text-xs font-semibold text-gray-700 mb-1.5 flex items-center gap-1.5">
            <Unlock className="w-3.5 h-3.5" /> Request to re-open for editing
          </p>
          <p className="text-xs text-gray-500 mb-2">The other party must approve before any changes can be made. Both consent events are logged to the Audit Trail.</p>
          <textarea
            value={reopenReason}
            onChange={e => setReopenReason(e.target.value)}
            placeholder="Reason for re-opening (e.g. incorrect action item text)…"
            className="w-full text-xs px-2.5 py-2 border border-gray-300 rounded-md bg-white resize-none focus:outline-none focus:ring-2 focus:ring-blue-400 placeholder-gray-400"
            rows={2}
            data-testid="reopen-reason-input"
          />
          <div className="flex items-center gap-2 mt-2">
            <button
              onClick={handleReopenSubmit}
              disabled={!reopenReason.trim() || reopenSubmitting}
              className="text-xs px-3 py-1.5 bg-[#1E3A8A] text-white rounded-md font-medium hover:bg-[#1E40AF] disabled:opacity-40 transition-colors"
              data-testid="submit-reopen-btn"
            >
              {reopenSubmitting ? "Sending…" : "Send Request"}
            </button>
            <button
              onClick={() => { setShowReopenForm(false); setReopenReason(""); }}
              className="text-xs px-3 py-1.5 border border-gray-200 text-gray-600 rounded-md hover:bg-white transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Audio status */}
      {meeting.audio_deletion_status !== "none" && (
        <div className={`border rounded-lg p-3 text-xs ${meeting.audio_deletion_status === "deleted" ? "bg-gray-50 border-gray-200 text-gray-500" : "bg-amber-50 border-amber-200 text-amber-700"}`} data-testid="audio-status">
          <strong>Audio:</strong> {
            meeting.audio_deletion_status === "grace_period" ? "Grace period — will be deleted in ~5 minutes" :
            meeting.audio_deletion_status === "deleted" ? "Deleted (GDPR compliant)" :
            "Pending deletion"
          }
        </div>
      )}

      {actionMessage && (
        <div className="bg-blue-50 border border-blue-200 text-blue-700 rounded-md p-3 text-sm" data-testid="action-message">
          {actionMessage}
        </div>
      )}

      {/* Back to top */}
      <div className="flex justify-end pt-1 pb-2">
        <button
          onClick={() => document.getElementById("section-summary")?.scrollIntoView({ behavior: "smooth", block: "start" })}
          className="flex items-center gap-1.5 text-xs font-medium text-gray-500 hover:text-gray-800 transition-colors"
          data-testid="back-to-top-btn"
        >
          <ArrowUp className="w-3 h-3" />
          Back to top
        </button>
      </div>
    </div>
  );
});

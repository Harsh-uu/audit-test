import React, { useState, useEffect } from "react";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import {
  FileText, Check, X, Flag, ChevronDown, ChevronUp, ChevronRight, Edit3, Shield, Award, RefreshCw, Loader, AlignLeft,
} from "lucide-react";

const CONFIDENCE_CONFIG = {
  likely_evidence: { label: "Likely Evidence", color: "bg-emerald-100 text-emerald-800 border-emerald-200", dot: "bg-emerald-500" },
  needs_review: { label: "Needs Review", color: "bg-amber-100 text-amber-800 border-amber-200", dot: "bg-amber-500" },
  not_enough_evidence: { label: "Not Enough Evidence", color: "bg-gray-100 text-gray-600 border-gray-200", dot: "bg-gray-400" },
};

const EVIDENCE_STATUS_CONFIG = {
  pending: { label: "Pending", color: "text-gray-500" },
  accepted: { label: "Accepted", color: "text-emerald-600" },
  rejected: { label: "Rejected", color: "text-red-500" },
  needs_followup: { label: "Needs Follow-up", color: "text-amber-600" },
};

const CQC_KEY_QUESTION_STYLES = {
  "Safe":       "bg-red-100 text-red-700 border-red-200",
  "Effective":  "bg-blue-100 text-blue-700 border-blue-200",
  "Caring":     "bg-pink-100 text-pink-700 border-pink-200",
  "Responsive": "bg-amber-100 text-amber-700 border-amber-200",
  "Well-led":   "bg-emerald-100 text-emerald-700 border-emerald-200",
};

function ConfidenceBadge({ confidence }) {
  const cfg = CONFIDENCE_CONFIG[confidence] || CONFIDENCE_CONFIG.needs_review;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 text-xs font-medium border rounded-full ${cfg.color}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`}></span>
      {cfg.label}
    </span>
  );
}

function KeyQuestionBadge({ label }) {
  const style = CQC_KEY_QUESTION_STYLES[label] || "bg-gray-100 text-gray-600 border-gray-200";
  return (
    <span className={`inline-flex text-xs font-medium border rounded-full px-2 py-0.5 ${style}`}>
      {label}
    </span>
  );
}

function EvidenceCard({ mapping, isReviewMode, onUpdateEvidence, type, onShowInTranscript }) {
  const [expanded, setExpanded] = useState(true);
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(mapping.edited_evidence_summary || mapping.evidence_summary);

  const refLabel = type === "cqc" ? mapping.regulation_ref : type === "custom" ? mapping.criterion_ref : mapping.standard_ref;
  const refName = type === "cqc" ? mapping.regulation_name : type === "custom" ? mapping.criterion_name : mapping.standard_name;
  const statusCfg = EVIDENCE_STATUS_CONFIG[mapping.status] || EVIDENCE_STATUS_CONFIG.pending;

  const cardBg = type === "cqc" ? "bg-purple-50 border-b border-purple-100" : type === "custom" ? "bg-teal-50 border-b border-teal-100" : "bg-blue-50 border-b border-blue-100";
  const typeLabel = type === "cqc" ? "CQC" : type === "custom" ? "Policy" : "Care Cert";
  const typeIcon = type === "cqc"
    ? <Shield className="w-3.5 h-3.5 text-[#1E3A8A] flex-shrink-0" />
    : type === "custom"
    ? <FileText className="w-3.5 h-3.5 text-teal-600 flex-shrink-0" />
    : <Award className="w-3.5 h-3.5 text-emerald-600 flex-shrink-0" />;

  const handleAction = async (status) => { await onUpdateEvidence(mapping.id, { status }); };
  const handleSaveEdit = async () => { await onUpdateEvidence(mapping.id, { edited_evidence_summary: editText }); setEditing(false); };

  return (
    <div className={`border rounded-lg overflow-hidden mb-3 ${mapping.status === "rejected" ? "opacity-60" : ""}`} data-testid={`evidence-card-${mapping.id}`}>
      <div className={`flex items-center justify-between p-3 cursor-pointer ${cardBg}`} onClick={() => setExpanded(!expanded)}>
        <div className="flex flex-col min-w-0 flex-1">
          <div className="flex items-center gap-2">
            {typeIcon}
            <span className="text-xs font-semibold text-gray-600 uppercase tracking-wide flex-shrink-0">{typeLabel}</span>
            <span className="text-xs font-medium text-gray-900 truncate">{refLabel} — {refName}</span>
          </div>
          {type === "care_cert" && mapping.outcome_ref && (
            <div className="ml-9 mt-0.5">
              <span className="inline-flex items-center gap-1 text-xs text-blue-700 font-medium bg-blue-100 border border-blue-200 rounded px-1.5 py-0.5" data-testid={`outcome-ref-${mapping.id}`}>
                Outcome {mapping.outcome_ref}: {mapping.outcome_name}
              </span>
            </div>
          )}
          {type === "cqc" && mapping.key_questions?.length > 0 && (
            <div className="ml-9 mt-1 flex flex-wrap gap-1" data-testid={`key-questions-${mapping.id}`}>
              {mapping.key_questions.map(q => <KeyQuestionBadge key={q} label={q} />)}
            </div>
          )}
          {type === "custom" && mapping.document_name && (
            <div className="ml-9 mt-0.5">
              <span className="inline-flex items-center gap-1 text-xs text-teal-700 font-medium bg-teal-100 border border-teal-200 rounded px-1.5 py-0.5">
                {mapping.document_name}
              </span>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0 ml-2">
          <ConfidenceBadge confidence={mapping.confidence} />
          {mapping.status !== "pending" && (
            <span className={`text-xs font-medium ${statusCfg.color}`}>{statusCfg.label}</span>
          )}
          {expanded ? <ChevronUp className="w-3.5 h-3.5 text-gray-400" /> : <ChevronDown className="w-3.5 h-3.5 text-gray-400" />}
        </div>
      </div>

      {expanded && (
        <div className="p-4 bg-white">
          {mapping.transcript_excerpt && (
            <>
              <blockquote className="border-l-3 border-l-gray-300 pl-3 py-1 mb-1.5 bg-gray-50 rounded-r text-sm text-gray-700 italic">
                "{mapping.transcript_excerpt}"
              </blockquote>
              {onShowInTranscript && (
                <button
                  onClick={() => onShowInTranscript(mapping.transcript_excerpt)}
                  className="flex items-center gap-1.5 text-xs text-[#1E3A8A] hover:text-[#1E40AF] hover:underline mb-3 font-medium"
                  data-testid={`show-in-transcript-${mapping.id}`}
                >
                  <AlignLeft className="w-3 h-3" /> Show in transcript
                </button>
              )}
            </>
          )}
          {editing ? (
            <div className="mb-3">
              <textarea value={editText} onChange={e => setEditText(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] resize-none" rows={3} data-testid="evidence-edit-textarea" />
              <div className="flex gap-2 mt-2">
                <button onClick={handleSaveEdit} className="text-xs bg-[#1E3A8A] text-white px-3 py-1 rounded hover:bg-[#1E40AF]">Save</button>
                <button onClick={() => setEditing(false)} className="text-xs border border-gray-300 text-gray-600 px-3 py-1 rounded hover:bg-gray-50">Cancel</button>
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-800 mb-3 leading-relaxed">
              {mapping.edited_evidence_summary || mapping.evidence_summary}
              {mapping.edited_evidence_summary && <span className="ml-1 text-xs text-blue-500">(edited)</span>}
            </p>
          )}
          {mapping.notes && (
            <div className="bg-yellow-50 border border-yellow-200 rounded p-2 mb-3 text-xs text-yellow-800">
              <strong>Note:</strong> {mapping.notes}
            </div>
          )}
          {isReviewMode && (
            <div className="flex items-center gap-2 pt-2 border-t border-gray-100">
              <button onClick={() => handleAction("accepted")} className={`flex items-center gap-1 text-xs px-2.5 py-1 rounded border transition-colors ${mapping.status === "accepted" ? "bg-emerald-100 border-emerald-300 text-emerald-700" : "border-gray-200 text-gray-600 hover:bg-emerald-50"}`} data-testid={`accept-evidence-${mapping.id}`}>
                <Check className="w-3 h-3" /> Accept
              </button>
              <button onClick={() => handleAction("rejected")} className={`flex items-center gap-1 text-xs px-2.5 py-1 rounded border transition-colors ${mapping.status === "rejected" ? "bg-red-100 border-red-300 text-red-600" : "border-gray-200 text-gray-600 hover:bg-red-50"}`} data-testid={`reject-evidence-${mapping.id}`}>
                <X className="w-3 h-3" /> Reject
              </button>
              <button onClick={() => handleAction("needs_followup")} className={`flex items-center gap-1 text-xs px-2.5 py-1 rounded border transition-colors ${mapping.status === "needs_followup" ? "bg-amber-100 border-amber-300 text-amber-700" : "border-gray-200 text-gray-600 hover:bg-amber-50"}`} data-testid={`flag-evidence-${mapping.id}`}>
                <Flag className="w-3 h-3" /> Flag
              </button>
              {!editing && (
                <button onClick={() => setEditing(true)} className="flex items-center gap-1 text-xs px-2.5 py-1 rounded border border-gray-200 text-gray-600 hover:bg-gray-50 ml-auto" data-testid={`edit-evidence-${mapping.id}`}>
                  <Edit3 className="w-3 h-3" /> Edit
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Care Certificate sub-outcome drill-down ──────────────────────────────────
function CareCertDrillDown({ mappings }) {
  const { getAuthConfig, API } = useAuth();
  const [standards, setStandards] = useState([]);
  const [openStds, setOpenStds] = useState({});
  const [showGaps, setShowGaps] = useState({});

  useEffect(() => {
    axios.get(`${API}/admin/standards`, getAuthConfig())
      .then(r => setStandards(r.data.filter(s => s.type === "care_cert")))
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Group mappings by standard_ref → outcome_ref
  const byStandard = {};
  for (const m of mappings) {
    const sr = m.standard_ref;
    if (!byStandard[sr]) byStandard[sr] = { name: m.standard_name, items: [] };
    byStandard[sr].items.push(m);
  }

  const relevantStds = standards.filter(s => byStandard[s.reference]);

  if (!relevantStds.length) return null;

  return (
    <div className="mt-4 pt-4 border-t border-blue-100" data-testid="care-cert-drilldown">
      <div className="flex items-center gap-2 mb-3">
        <Award className="w-3.5 h-3.5 text-blue-600" />
        <h3 className="text-xs font-semibold text-gray-600 uppercase tracking-wide">Specific Outcomes</h3>
      </div>
      {relevantStds.map(std => {
        const stData = byStandard[std.reference];
        const evidencedRefs = new Set(stData.items.map(m => m.outcome_ref).filter(Boolean));
        const allSubs = std.sub_outcomes || [];
        const covered = allSubs.filter(s => evidencedRefs.has(s.ref));
        const gaps = allSubs.filter(s => !evidencedRefs.has(s.ref));
        const isOpen = openStds[std.reference];
        const showingGaps = showGaps[std.reference];

        return (
          <div key={std.reference} className="mb-2 border border-blue-100 rounded-lg overflow-hidden" data-testid={`cc-drilldown-${std.reference?.replace(/\s/g,'-')}`}>
            <button
              className="w-full flex items-center justify-between p-3 bg-blue-50 hover:bg-blue-100 transition-colors text-left"
              onClick={() => setOpenStds(s => ({ ...s, [std.reference]: !s[std.reference] }))}
            >
              <div className="flex items-center gap-2 min-w-0">
                {isOpen ? <ChevronDown className="w-3.5 h-3.5 text-blue-600 flex-shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-blue-600 flex-shrink-0" />}
                <span className="text-xs font-semibold text-blue-800">{std.reference}</span>
                <span className="text-xs text-gray-600 truncate">{std.name}</span>
              </div>
              <span className={`flex-shrink-0 ml-2 text-xs font-bold px-2 py-0.5 rounded-full ${covered.length === allSubs.length && allSubs.length > 0 ? "bg-emerald-100 text-emerald-700" : covered.length > 0 ? "bg-amber-100 text-amber-700" : "bg-gray-100 text-gray-500"}`}>
                {covered.length}/{allSubs.length}
              </span>
            </button>

            {isOpen && (
              <div className="bg-white px-3 py-2 space-y-1">
                {covered.map(sub => {
                  const mapping = stData.items.find(m => m.outcome_ref === sub.ref);
                  return (
                    <div key={sub.ref} className="flex items-start gap-2 py-1.5 border-b border-gray-50 last:border-0">
                      <span className="w-4 h-4 rounded-full bg-emerald-100 flex items-center justify-center flex-shrink-0 mt-0.5">
                        <Check className="w-2.5 h-2.5 text-emerald-600" />
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium text-gray-800">
                          <span className="text-emerald-700 font-semibold mr-1">{sub.ref}</span>{sub.desc}
                        </p>
                        {mapping?.transcript_excerpt && (
                          <p className="text-xs text-gray-500 italic mt-0.5 truncate">"{mapping.transcript_excerpt}"</p>
                        )}
                      </div>
                    </div>
                  );
                })}

                {gaps.length > 0 && (
                  <div>
                    <button
                      className="w-full text-left text-xs text-gray-400 hover:text-gray-600 py-1.5 flex items-center gap-1"
                      onClick={() => setShowGaps(s => ({ ...s, [std.reference]: !s[std.reference] }))}
                    >
                      {showingGaps ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                      {gaps.length} outcomes not yet evidenced
                    </button>
                    {showingGaps && gaps.map(sub => (
                      <div key={sub.ref} className="flex items-start gap-2 py-1 opacity-50">
                        <span className="w-4 h-4 rounded-full bg-gray-100 flex items-center justify-center flex-shrink-0 mt-0.5">
                          <span className="w-1.5 h-1.5 rounded-full bg-gray-300" />
                        </span>
                        <p className="text-xs text-gray-500">
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

export function EvidenceSidebar({ analysis, canReview, updateEvidence, className, noMaxHeight = false, canRescan = false, onRescanEvidence, onShowInTranscript }) {
  const totalCount = (analysis.cqc_mappings?.length || 0) + (analysis.care_cert_mappings?.length || 0) + (analysis.custom_mappings?.length || 0);
  const wrapperClass = className !== undefined ? className : "lg:col-span-5 bg-[#F8F9FA] overflow-y-auto";
  const [rescanning, setRescanning] = useState(false);
  const [showRescanDialog, setShowRescanDialog] = useState(false);
  const [rescanPrompt, setRescanPrompt] = useState("");

  const handleRescanWithPrompt = async (prompt) => {
    if (!onRescanEvidence) return;
    setShowRescanDialog(false);
    setRescanning(true);
    try {
      await onRescanEvidence(prompt);
    } finally {
      setRescanning(false);
      setRescanPrompt("");
    }
  };

  return (
    <div className={wrapperClass} style={noMaxHeight ? {} : { maxHeight: "calc(100vh - 80px)" }}>
      <div className="p-4">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-gray-900 font-display">Compliance Evidence</h2>
          <div className="flex items-center gap-2">
            {canRescan && (
              <button
                onClick={() => !rescanning && setShowRescanDialog(v => !v)}
                disabled={rescanning}
                data-testid="rescan-evidence-btn"
                title="Re-scan compliance evidence — optionally with custom guidance"
                className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded border border-gray-200 bg-white text-gray-600 hover:bg-blue-50 hover:border-blue-200 hover:text-blue-700 transition-colors disabled:opacity-60"
              >
                {rescanning
                  ? <Loader className="w-3.5 h-3.5 animate-spin" />
                  : <RefreshCw className="w-3.5 h-3.5" />}
                {rescanning ? "Re-scanning…" : "Re-scan"}
              </button>
            )}
            <span className="text-xs text-gray-500">{totalCount} items</span>
          </div>
        </div>

        {/* Guided re-scan dialog */}
        {showRescanDialog && !rescanning && (
          <div
            className="mb-4 border border-blue-200 rounded-lg bg-blue-50 p-3 shadow-sm"
            data-testid="rescan-dialog"
          >
            <p className="text-xs font-semibold text-blue-800 mb-1.5 flex items-center gap-1.5">
              <RefreshCw className="w-3 h-3" /> Guide the re-scan (optional)
            </p>
            <textarea
              value={rescanPrompt}
              onChange={e => setRescanPrompt(e.target.value)}
              placeholder="e.g. Focus on medication management and manual handling, or look for evidence of Care Certificate Standard 9"
              className="w-full text-xs px-2.5 py-2 border border-blue-200 rounded-md bg-white resize-none focus:outline-none focus:ring-2 focus:ring-blue-400 text-gray-700 placeholder-gray-400"
              rows={3}
              data-testid="rescan-prompt-input"
            />
            <div className="flex items-center gap-2 mt-2">
              <button
                onClick={() => handleRescanWithPrompt(rescanPrompt.trim())}
                disabled={!rescanPrompt.trim()}
                className="text-xs px-3 py-1.5 bg-[#1E3A8A] text-white rounded-md font-medium hover:bg-[#1E40AF] disabled:opacity-40 transition-colors"
                data-testid="rescan-with-guidance-btn"
              >
                Re-scan with guidance
              </button>
              <button
                onClick={() => handleRescanWithPrompt("")}
                className="text-xs px-3 py-1.5 border border-gray-300 text-gray-600 rounded-md hover:bg-white transition-colors"
                data-testid="rescan-without-guidance-btn"
              >
                Re-scan without guidance
              </button>
              <button
                onClick={() => { setShowRescanDialog(false); setRescanPrompt(""); }}
                className="ml-auto text-xs text-gray-400 hover:text-gray-600"
                data-testid="rescan-cancel-btn"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {analysis.cqc_mappings?.length > 0 && (
          <div className="mb-4">
            <div className="flex items-center gap-2 mb-2">
              <Shield className="w-3.5 h-3.5 text-[#1E3A8A]" />
              <h3 className="text-xs font-semibold text-gray-600 uppercase tracking-wide">CQC Regulations</h3>
              <span className="ml-auto text-xs text-gray-400">{analysis.cqc_mappings.length}</span>
            </div>
            {analysis.cqc_mappings.map(m => (
              <EvidenceCard key={m.id} mapping={m} isReviewMode={canReview} onUpdateEvidence={updateEvidence} type="cqc" onShowInTranscript={onShowInTranscript} />
            ))}
          </div>
        )}

        {analysis.care_cert_mappings?.length > 0 && (
          <div className="mb-4">
            <div className="flex items-center gap-2 mb-2">
              <Award className="w-3.5 h-3.5 text-emerald-600" />
              <h3 className="text-xs font-semibold text-gray-600 uppercase tracking-wide">Care Certificate</h3>
              <span className="ml-auto text-xs text-gray-400">{analysis.care_cert_mappings.length}</span>
            </div>
            {analysis.care_cert_mappings.map(m => (
              <EvidenceCard key={m.id} mapping={m} isReviewMode={canReview} onUpdateEvidence={updateEvidence} type="care_cert" onShowInTranscript={onShowInTranscript} />
            ))}
            <CareCertDrillDown mappings={analysis.care_cert_mappings} />
          </div>
        )}

        {analysis.custom_mappings?.length > 0 && (
          <div className="mb-4">
            <div className="flex items-center gap-2 mb-2">
              <FileText className="w-3.5 h-3.5 text-teal-600" />
              <h3 className="text-xs font-semibold text-gray-600 uppercase tracking-wide">Organisational Standards</h3>
              <span className="ml-auto text-xs text-gray-400">{analysis.custom_mappings.length}</span>
            </div>
            {analysis.custom_mappings.map(m => (
              <EvidenceCard key={m.id} mapping={m} isReviewMode={canReview} onUpdateEvidence={updateEvidence} type="custom" onShowInTranscript={onShowInTranscript} />
            ))}
          </div>
        )}

        {!totalCount && (
          <div className="text-center py-12 text-gray-400">
            <Shield className="w-8 h-8 mx-auto mb-2 opacity-40" />
            <p className="text-sm">No evidence mappings generated</p>
          </div>
        )}
      </div>
    </div>
  );
}


import React, { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import {
  FileText, CheckCircle, Clock, Edit3, Check, X, Flag, ChevronDown, ChevronUp,
  Send, MessageSquare, ArrowLeft, AlertTriangle, Loader, Shield, Award, Pause, Plus, Trash2, History
} from "lucide-react";import { anonymiseTranscript } from "@/utils/anonymise";

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

function ConfidenceBadge({ confidence }) {
  const cfg = CONFIDENCE_CONFIG[confidence] || CONFIDENCE_CONFIG.needs_review;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 text-xs font-medium border rounded-full ${cfg.color}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`}></span>
      {cfg.label}
    </span>
  );
}

const CQC_KEY_QUESTION_STYLES = {
  "Safe":      "bg-red-100 text-red-700 border-red-200",
  "Effective": "bg-blue-100 text-blue-700 border-blue-200",
  "Caring":    "bg-pink-100 text-pink-700 border-pink-200",
  "Responsive":"bg-amber-100 text-amber-700 border-amber-200",
  "Well-led":  "bg-emerald-100 text-emerald-700 border-emerald-200",
};

function KeyQuestionBadge({ label }) {
  const style = CQC_KEY_QUESTION_STYLES[label] || "bg-gray-100 text-gray-600 border-gray-200";
  return (
    <span className={`inline-flex text-xs font-medium border rounded-full px-2 py-0.5 ${style}`}>
      {label}
    </span>
  );
}

function EvidenceCard({ mapping, isReviewMode, onUpdateEvidence, type }) {
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

  const handleAction = async (status) => {
    await onUpdateEvidence(mapping.id, { status });
  };

  const handleSaveEdit = async () => {
    await onUpdateEvidence(mapping.id, { edited_evidence_summary: editText });
    setEditing(false);
  };

  return (
    <div className={`border rounded-lg overflow-hidden mb-3 ${mapping.status === "rejected" ? "opacity-60" : ""}`} data-testid={`evidence-card-${mapping.id}`}>
      <div
        className={`flex items-center justify-between p-3 cursor-pointer ${cardBg}`}
        onClick={() => setExpanded(!expanded)}
      >
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
          {/* Transcript excerpt */}
          {mapping.transcript_excerpt && (
            <blockquote className="border-l-3 border-l-gray-300 pl-3 py-1 mb-3 bg-gray-50 rounded-r text-sm text-gray-700 italic">
              "{mapping.transcript_excerpt}"
            </blockquote>
          )}

          {/* Evidence summary */}
          {editing ? (
            <div className="mb-3">
              <textarea
                value={editText}
                onChange={e => setEditText(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] resize-none"
                rows={3}
                data-testid="evidence-edit-textarea"
              />
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

const AUDIT_EVENT_CONFIG = {
  meeting_created:   { color: "bg-blue-100 text-blue-700", dot: "bg-blue-400" },
  recording_started: { color: "bg-red-100 text-red-700", dot: "bg-red-400" },
  recording_paused:  { color: "bg-amber-100 text-amber-700", dot: "bg-amber-400" },
  recording_resumed: { color: "bg-amber-100 text-amber-700", dot: "bg-amber-400" },
  recording_stopped: { color: "bg-gray-100 text-gray-600", dot: "bg-gray-400" },
  recording_notice_acknowledged: { color: "bg-gray-100 text-gray-600", dot: "bg-gray-300" },
  transcribed:       { color: "bg-indigo-100 text-indigo-700", dot: "bg-indigo-400" },
  analyzed:          { color: "bg-purple-100 text-purple-700", dot: "bg-purple-400" },
  edit_summary:      { color: "bg-blue-50 text-blue-600", dot: "bg-blue-300" },
  edit_actions:      { color: "bg-blue-50 text-blue-600", dot: "bg-blue-300" },
  edit_evidence:     { color: "bg-blue-50 text-blue-600", dot: "bg-blue-300" },
  mark_reviewed:     { color: "bg-emerald-100 text-emerald-700", dot: "bg-emerald-400" },
  signed_off:        { color: "bg-emerald-100 text-emerald-800 font-semibold", dot: "bg-emerald-600" },
  comment_added:     { color: "bg-gray-100 text-gray-700", dot: "bg-gray-400" },
  audio_deleted:     { color: "bg-red-50 text-red-600", dot: "bg-red-300" },
};

function AuditEvent({ event }) {
  const cfg = AUDIT_EVENT_CONFIG[event.type] || { color: "bg-gray-100 text-gray-600", dot: "bg-gray-400" };
  return (
    <div className="relative">
      <div className={`absolute -left-5 w-2.5 h-2.5 rounded-full border-2 border-white ${cfg.dot}`} style={{ top: "0.35rem" }} />
      <div className="bg-white border border-gray-200 rounded-lg p-3 shadow-sm">
        <div className="flex items-start justify-between gap-2">
          <span className={`inline-block text-xs px-2 py-0.5 rounded-full ${cfg.color}`}>{event.label}</span>
          <span className="text-xs text-gray-400 whitespace-nowrap flex-shrink-0">
            {event.timestamp ? new Date(event.timestamp).toLocaleString("en-GB") : "—"}
          </span>
        </div>
        <p className="text-xs text-gray-500 mt-1">by <strong className="text-gray-700">{event.actor}</strong></p>
        {event.detail && <p className="text-xs text-gray-500 mt-1 italic">"{event.detail}"</p>}
      </div>
    </div>
  );
}

const PROCESSING_STAGES = {
  processing: { label: "Uploading audio...", pct: 20 },
  transcribing: { label: "Transcribing audio with Whisper...", pct: 50 },
  analyzing: { label: "Mapping compliance evidence with AI...", pct: 80 },
  processing_failed: { label: "Processing failed", pct: 0, error: true },
};

export default function MeetingReport() {
  const { meetingId } = useParams();
  const { getAuthConfig, API, user } = useAuth();
  const navigate = useNavigate();
  const [meeting, setMeeting] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("evidence"); // evidence | transcript | comments | audit
  const [editingSummary, setEditingSummary] = useState(false);
  const [summaryText, setSummaryText] = useState("");
  const [newComment, setNewComment] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [addingAction, setAddingAction] = useState(false);
  const [newAction, setNewAction] = useState({ text: "", assigned_to: "", due_date: "" });
  const [auditTrail, setAuditTrail] = useState(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [exportingPdf, setExportingPdf] = useState(false);
  const [includeTranscript, setIncludeTranscript] = useState(false);
  const [sendingEmail, setSendingEmail] = useState(false);
  const [showEmailModal, setShowEmailModal] = useState(false);
  const [emailMessage, setEmailMessage] = useState("");

  const isProcessing = ["processing", "transcribing", "analyzing"].includes(meeting?.status);
  const isInReview = meeting?.status === "in_review";
  const isReviewed = meeting?.status === "reviewed";
  const isSignedOff = ["signed_off", "shared"].includes(meeting?.status);
  const canReview = isInReview || isReviewed;
  const canSignOff = user?.role === "manager" || user?.role === "admin";
  const canAddComment = isSignedOff || ["admin", "manager"].includes(user?.role);

  const userAttendee = meeting?.attendees?.find(a => a.user_id === user?.id);
  const hasReviewed = userAttendee?.reviewed || false;
  const allReviewed = meeting?.attendees?.length > 0
    ? meeting.attendees.every(a => a.reviewed)
    : true;

  // API and getAuthConfig are stable context references; meetingId is the only meaningful dep
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const fetchMeeting = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/meetings/${meetingId}`, getAuthConfig());
      setMeeting(data);
      if (data.analysis?.edited_summary || data.analysis?.summary) {
        setSummaryText(data.analysis?.edited_summary || data.analysis?.summary || "");
      }
    } catch (err) {
      console.error("Failed to load meeting", err);
    } finally {
      setLoading(false);
    }
  }, [meetingId]);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const fetchAuditTrail = useCallback(async () => {
    setAuditLoading(true);
    try {
      const { data } = await axios.get(`${API}/review/${meetingId}/audit-trail`, getAuthConfig());
      setAuditTrail(data.events || []);
    } catch (err) {
      console.error("Failed to load audit trail", err);
      setAuditTrail([]);
    } finally {
      setAuditLoading(false);
    }
  }, [meetingId]);

  const exportPdf = async () => {
    setExportingPdf(true);
    try {
      const token = localStorage.getItem("supervision_token");
      const resp = await fetch(`${API}/review/${meetingId}/export-pdf?include_transcript=${includeTranscript}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) throw new Error(await resp.text());
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `supervision_report_${meetingId.slice(-6)}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert("PDF export failed: " + err.message);
    } finally {
      setExportingPdf(false);
    }
  };

  const sendReport = async () => {
    const attendeeEmails = (meeting?.attendees || []).map(a => a.email).filter(Boolean);
    if (!attendeeEmails.length) {
      alert("No attendee email addresses found on this meeting.");
      return;
    }
    setSendingEmail(true);
    try {
      await axios.post(`${API}/review/${meetingId}/send-email`, {
        recipients: attendeeEmails,
        message: emailMessage,
      }, getAuthConfig());
      setShowEmailModal(false);
      setEmailMessage("");
      setActionMessage("Report emailed to attendees.");
    } catch (err) {
      alert("Failed to send email: " + (err.response?.data?.detail || err.message));
    } finally {
      setSendingEmail(false);
    }
  };

  useEffect(() => {
    fetchMeeting();
    const interval = setInterval(() => {
      if (isProcessing) fetchMeeting();
    }, 5000);
    return () => clearInterval(interval);
  }, [fetchMeeting, isProcessing]);

  useEffect(() => {
    if (activeTab === "audit" && auditTrail === null) {
      fetchAuditTrail();
    }
  }, [activeTab, auditTrail, fetchAuditTrail]);

  const saveSummary = async () => {
    try {
      await axios.put(`${API}/review/${meetingId}/summary`, { summary: summaryText }, getAuthConfig());
      setEditingSummary(false);
      fetchMeeting();
      setActionMessage("Summary saved");
    } catch (err) {
      setActionMessage(err.response?.data?.detail || "Failed to save");
    }
  };

  const updateEvidence = async (evidenceId, updates) => {
    try {
      await axios.put(`${API}/review/${meetingId}/evidence/${evidenceId}`, updates, getAuthConfig());
      fetchMeeting();
    } catch (err) {
      console.error("Evidence update failed", err);
    }
  };

  const saveActions = async (updatedActions) => {
    try {
      await axios.put(`${API}/review/${meetingId}/actions`, { actions: updatedActions }, getAuthConfig());
      fetchMeeting();
    } catch (err) {
      setActionMessage(err.response?.data?.detail || "Failed to save actions");
    }
  };

  const addAction = async () => {
    if (!newAction.text.trim()) return;
    const current = meeting?.analysis?.actions || [];
    const updated = [
      ...current,
      {
        id: `action_manual_${Date.now()}`,
        text: newAction.text.trim(),
        assigned_to: newAction.assigned_to.trim() || null,
        due_date: newAction.due_date.trim() || null,
      },
    ];
    await saveActions(updated);
    setNewAction({ text: "", assigned_to: "", due_date: "" });
    setAddingAction(false);
  };

  const removeAction = async (idx) => {
    const current = meeting?.analysis?.actions || [];
    const updated = current.filter((_, i) => i !== idx);
    await saveActions(updated);
  };

  const toggleActionComplete = async (actionId, completed) => {
    try {
      await axios.patch(`${API}/review/${meetingId}/actions/${actionId}`, { completed }, getAuthConfig());
      setMeeting(m => ({
        ...m,
        analysis: {
          ...m.analysis,
          actions: (m.analysis?.actions || []).map(a =>
            (a.id === actionId) ? { ...a, completed, completed_at: completed ? new Date().toISOString() : null } : a
          ),
        },
      }));
    } catch (err) {
      console.error("Failed to update action", err);
    }
  };

  const markReviewed = async () => {
    setSubmitting(true);
    try {
      const { data } = await axios.post(`${API}/review/${meetingId}/mark-reviewed`, {}, getAuthConfig());
      setActionMessage(data.message || "Marked as reviewed");
      fetchMeeting();
    } catch (err) {
      setActionMessage(err.response?.data?.detail || "Failed to mark reviewed");
    } finally {
      setSubmitting(false);
    }
  };

  const signOff = async () => {
    if (!window.confirm("Are you sure you want to sign off this meeting? This will start the audio deletion process.")) return;
    setSubmitting(true);
    try {
      await axios.post(`${API}/review/${meetingId}/signoff`, {}, getAuthConfig());
      setActionMessage("Meeting signed off successfully");
      fetchMeeting();
    } catch (err) {
      setActionMessage(err.response?.data?.detail || "Failed to sign off");
    } finally {
      setSubmitting(false);
    }
  };

  const addComment = async () => {
    if (!newComment.trim()) return;
    try {
      await axios.post(`${API}/review/${meetingId}/comments`, { text: newComment }, getAuthConfig());
      setNewComment("");
      fetchMeeting();
    } catch (err) {
      setActionMessage(err.response?.data?.detail || "Failed to add comment");
    }
  };

  if (loading) {
    return (
      <Layout>
        <div className="flex items-center justify-center h-full py-24">
          <div className="flex items-center gap-3 text-gray-500">
            <div className="w-5 h-5 border-2 border-[#1E3A8A] border-t-transparent rounded-full spin"></div>
            <span className="text-sm">Loading meeting report...</span>
          </div>
        </div>
      </Layout>
    );
  }

  if (!meeting) {
    return <Layout><div className="p-8 text-center text-gray-500">Meeting not found</div></Layout>;
  }

  const stageCfg = PROCESSING_STAGES[meeting.status];
  const analysis = meeting.analysis;

  return (
    <Layout>
      <div className="flex flex-col h-full">
        {/* Top bar */}
        <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between sticky top-0 z-20">
          <div className="flex items-center gap-4">
            <button onClick={() => navigate("/dashboard")} className="text-gray-500 hover:text-gray-700 flex items-center gap-1 text-sm">
              <ArrowLeft className="w-4 h-4" />
            </button>
            <div>
              <h1 className="text-base font-semibold text-gray-900 leading-tight" style={{fontFamily:'Work Sans,sans-serif'}}>{meeting.title}</h1>
              <div className="flex items-center gap-3 text-xs text-gray-500 mt-0.5">
                <span>{new Date(meeting.date).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}</span>
                {meeting.location && <span>{meeting.location}</span>}
                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-medium border text-xs ${
                  isSignedOff ? "bg-emerald-100 text-emerald-800 border-emerald-200" :
                  canReview ? "bg-amber-100 text-amber-800 border-amber-200" :
                  "bg-blue-100 text-blue-700 border-blue-200"
                }`}>
                  {meeting.status.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase())}
                </span>
              </div>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2">
            {canReview && !hasReviewed && (
              <button
                onClick={markReviewed}
                disabled={submitting}
                className="flex items-center gap-2 bg-[#059669] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-emerald-700 transition-colors disabled:opacity-60"
                data-testid="mark-reviewed-btn"
              >
                <CheckCircle className="w-4 h-4" />
                Mark Reviewed
              </button>
            )}
            {hasReviewed && canReview && (
              <span className="flex items-center gap-1.5 text-emerald-600 text-sm font-medium">
                <CheckCircle className="w-4 h-4" />
                You reviewed this
              </span>
            )}
            {canSignOff && (isReviewed || (isInReview && allReviewed)) && !isSignedOff && (
              <button
                onClick={signOff}
                disabled={submitting}
                className="flex items-center gap-2 bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors disabled:opacity-60"
                data-testid="sign-off-btn"
              >
                <Shield className="w-4 h-4" />
                Sign Off
              </button>
            )}
            {isSignedOff && canSignOff && (
              <div className="flex items-center gap-2">
                {/* PDF Export */}
                <div className="flex items-center gap-1.5 bg-white border border-gray-200 rounded-md shadow-sm">
                  <button
                    onClick={exportPdf}
                    disabled={exportingPdf}
                    className="flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors disabled:opacity-60 rounded-l-md"
                    data-testid="export-pdf-btn"
                  >
                    <FileText className="w-4 h-4 text-gray-500" />
                    {exportingPdf ? "Generating…" : "Export PDF"}
                  </button>
                  <div className="border-l border-gray-200 px-2 py-2 flex items-center gap-1.5">
                    <input type="checkbox" id="include-transcript" checked={includeTranscript} onChange={e => setIncludeTranscript(e.target.checked)} className="w-3.5 h-3.5 accent-[#1E3A8A]" data-testid="include-transcript-toggle" />
                    <label htmlFor="include-transcript" className="text-xs text-gray-500 cursor-pointer select-none">+ Transcript</label>
                  </div>
                </div>
                {/* Send Report */}
                <button
                  onClick={() => setShowEmailModal(true)}
                  className="flex items-center gap-1.5 bg-emerald-600 text-white px-3 py-2 rounded-md text-sm font-medium hover:bg-emerald-700 transition-colors"
                  data-testid="send-report-btn"
                >
                  <Send className="w-4 h-4" />
                  Send to Attendees
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Processing state */}
        {stageCfg && (
          <div className="p-8 flex flex-col items-center justify-center" data-testid="processing-indicator">
            {stageCfg.error ? (
              <div className="text-center">
                <AlertTriangle className="w-10 h-10 text-red-400 mx-auto mb-3" />
                <h3 className="font-semibold text-gray-900 mb-1">Processing failed</h3>
                <p className="text-sm text-gray-500">Please try re-uploading the recording.</p>
              </div>
            ) : (
              <div className="text-center max-w-md">
                <div className="w-12 h-12 border-3 border-[#1E3A8A] border-t-transparent rounded-full spin mx-auto mb-4"></div>
                <h3 className="font-semibold text-gray-900 mb-2">{stageCfg.label}</h3>
                <div className="w-64 bg-gray-200 rounded-full h-2 mx-auto">
                  <div className="bg-[#1E3A8A] h-2 rounded-full transition-all duration-500" style={{ width: `${stageCfg.pct}%` }}></div>
                </div>
                <p className="text-xs text-gray-400 mt-3">This page will update automatically</p>
              </div>
            )}
          </div>
        )}

        {/* Content */}
        {!stageCfg && analysis && (
          <div className="flex-1 grid grid-cols-1 lg:grid-cols-12 gap-0 overflow-hidden">
            {/* Left: Transcript */}
            <div className="lg:col-span-7 border-r border-gray-200 flex flex-col overflow-hidden">
              <div className="border-b border-gray-200 px-6 py-3 flex items-center gap-4">
                <button onClick={() => setActiveTab("evidence")} className={`text-sm font-medium pb-1 border-b-2 transition-colors ${activeTab === "evidence" ? "border-[#1E3A8A] text-[#1E3A8A]" : "border-transparent text-gray-500 hover:text-gray-700"}`}>
                  Evidence
                </button>
                <button onClick={() => setActiveTab("transcript")} className={`text-sm font-medium pb-1 border-b-2 transition-colors ${activeTab === "transcript" ? "border-[#1E3A8A] text-[#1E3A8A]" : "border-transparent text-gray-500 hover:text-gray-700"}`}>
                  Transcript
                </button>
                <button onClick={() => setActiveTab("comments")} className={`text-sm font-medium pb-1 border-b-2 transition-colors ${activeTab === "comments" ? "border-[#1E3A8A] text-[#1E3A8A]" : "border-transparent text-gray-500 hover:text-gray-700"}`} data-testid="comments-tab">
                  Comments {meeting.comments?.length > 0 && `(${meeting.comments.length})`}
                </button>
                <button onClick={() => setActiveTab("audit")} className={`text-sm font-medium pb-1 border-b-2 transition-colors ${activeTab === "audit" ? "border-[#1E3A8A] text-[#1E3A8A]" : "border-transparent text-gray-500 hover:text-gray-700"}`} data-testid="audit-trail-tab">
                  Audit Trail
                </button>
              </div>

              <div className="flex-1 overflow-y-auto p-6">
                {activeTab === "evidence" && (
                  <div className="space-y-6">
                    {/* Summary */}
                    <div className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
                      <div className="flex items-center justify-between mb-3">
                        <h3 className="font-semibold text-gray-900 text-sm" style={{fontFamily:'Work Sans,sans-serif'}}>Meeting Summary</h3>
                        {canReview && !editingSummary && (
                          <button onClick={() => setEditingSummary(true)} className="text-xs text-[#1E3A8A] flex items-center gap-1 hover:underline" data-testid="edit-summary-btn">
                            <Edit3 className="w-3 h-3" /> Edit
                          </button>
                        )}
                      </div>
                      {editingSummary ? (
                        <div>
                          <textarea value={summaryText} onChange={e => setSummaryText(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm resize-none focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]" rows={5} data-testid="summary-textarea" />
                          <div className="flex gap-2 mt-2">
                            <button onClick={saveSummary} className="text-xs bg-[#1E3A8A] text-white px-3 py-1.5 rounded hover:bg-[#1E40AF]" data-testid="save-summary-btn">Save</button>
                            <button onClick={() => setEditingSummary(false)} className="text-xs border border-gray-300 text-gray-600 px-3 py-1.5 rounded">Cancel</button>
                          </div>
                        </div>
                      ) : (
                        <p className="text-sm text-gray-700 leading-relaxed" data-testid="summary-text">
                          {analysis.edited_summary || analysis.summary || "No summary available."}
                        </p>
                      )}
                    </div>

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

                    {/* Actions */}
                    {(analysis.actions?.length > 0 || canReview) && (
                      <div className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
                        <div className="flex items-center justify-between mb-3">
                          <h3 className="font-semibold text-gray-900 text-sm" style={{fontFamily:'Work Sans,sans-serif'}}>
                            Action Items
                            {analysis.actions?.length > 0 && (
                              <span className="ml-2 text-xs font-normal text-gray-400">({analysis.actions.length})</span>
                            )}
                          </h3>
                          {canReview && !addingAction && (
                            <button
                              onClick={() => setAddingAction(true)}
                              className="flex items-center gap-1 text-xs text-[#1E3A8A] hover:underline font-medium"
                              data-testid="add-action-btn"
                            >
                              <Plus className="w-3 h-3" /> Add Action
                            </button>
                          )}
                        </div>

                        <div className="space-y-2" data-testid="actions-list">
                          {(analysis.actions || []).map((action, i) => (
                            <div key={action.id || action.text?.slice(0, 40) || i} className={`flex items-start gap-3 p-2.5 rounded-md group border transition-colors ${action.completed ? "bg-gray-50 border-gray-100 opacity-70" : action.is_rolled_over ? "bg-amber-50 border-amber-200" : "bg-gray-50 border-transparent"}`}>
                              {/* Completion checkbox */}
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
                                <button
                                  onClick={() => removeAction(i)}
                                  className="opacity-0 group-hover:opacity-100 p-1 text-gray-400 hover:text-red-500 transition-all rounded flex-shrink-0"
                                  data-testid={`remove-action-${i}`}
                                  title="Remove action"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              )}
                            </div>
                          ))}

                          {analysis.actions?.length === 0 && !addingAction && (
                            <p className="text-sm text-gray-400 py-2 text-center">No actions yet — add one below</p>
                          )}
                        </div>

                        {/* Add action form */}
                        {addingAction && (
                          <div className="mt-3 border border-dashed border-[#1E3A8A] rounded-md p-3 bg-blue-50 fade-in" data-testid="add-action-form">
                            <p className="text-xs font-semibold text-[#1E3A8A] mb-2">New Action</p>
                            <input
                              type="text"
                              value={newAction.text}
                              onChange={e => setNewAction(a => ({...a, text: e.target.value}))}
                              placeholder="Describe the action required..."
                              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] bg-white mb-2"
                              data-testid="new-action-text"
                              autoFocus
                              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); addAction(); } }}
                            />
                            <div className="grid grid-cols-2 gap-2 mb-3">
                              <input
                                type="text"
                                value={newAction.assigned_to}
                                onChange={e => setNewAction(a => ({...a, assigned_to: e.target.value}))}
                                placeholder="Assigned to (optional)"
                                className="px-3 py-1.5 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] bg-white"
                                data-testid="new-action-assigned"
                              />
                              <input
                                type="text"
                                value={newAction.due_date}
                                onChange={e => setNewAction(a => ({...a, due_date: e.target.value}))}
                                placeholder="Due date (optional)"
                                className="px-3 py-1.5 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] bg-white"
                                data-testid="new-action-due"
                              />
                            </div>
                            <div className="flex gap-2">
                              <button
                                onClick={addAction}
                                disabled={!newAction.text.trim()}
                                className="flex items-center gap-1.5 bg-[#1E3A8A] text-white px-3 py-1.5 rounded-md text-xs font-medium hover:bg-[#1E40AF] disabled:opacity-50 transition-colors"
                                data-testid="save-new-action-btn"
                              >
                                <Plus className="w-3 h-3" /> Add Action
                              </button>
                              <button
                                onClick={() => { setAddingAction(false); setNewAction({ text: "", assigned_to: "", due_date: "" }); }}
                                className="px-3 py-1.5 border border-gray-300 text-gray-600 rounded-md text-xs hover:bg-gray-50 transition-colors"
                                data-testid="cancel-add-action-btn"
                              >
                                Cancel
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Risks */}
                    {analysis.risks?.length > 0 && (
                      <div className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
                        <h3 className="font-semibold text-gray-900 text-sm mb-3" style={{fontFamily:'Work Sans,sans-serif'}}>Risks &amp; Concerns</h3>
                        <div className="space-y-2" data-testid="risks-list">
                          {analysis.risks.map((risk, i) => (
                            <div key={risk.text?.slice(0, 40) || i} className={`flex items-start gap-2 p-2.5 rounded-md border ${risk.severity === "high" ? "bg-red-50 border-red-200" : risk.severity === "medium" ? "bg-amber-50 border-amber-200" : "bg-gray-50 border-gray-200"}`}>
                              <AlertTriangle className={`w-3.5 h-3.5 mt-0.5 flex-shrink-0 ${risk.severity === "high" ? "text-red-500" : risk.severity === "medium" ? "text-amber-500" : "text-gray-400"}`} />
                              <p className="text-sm text-gray-800">{risk.text}</p>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Attendees review status */}
                    {meeting.attendees?.length > 0 && (
                      <div className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
                        <h3 className="font-semibold text-gray-900 text-sm mb-3" style={{fontFamily:'Work Sans,sans-serif'}}>Review Status</h3>
                        <div className="space-y-2">
                          {meeting.attendees.map(a => (
                            <div key={a.user_id} className="flex items-center justify-between">
                              <span className="text-sm text-gray-700">{a.name}</span>
                              {a.reviewed
                                ? <span className="text-xs text-emerald-600 flex items-center gap-1"><CheckCircle className="w-3 h-3" /> Reviewed</span>
                                : <span className="text-xs text-amber-600 flex items-center gap-1"><Clock className="w-3 h-3" /> Pending</span>}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Sign-off info */}
                    {meeting.sign_off_record && (
                      <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-4">
                        <div className="flex items-center gap-2">
                          <Shield className="w-4 h-4 text-emerald-600" />
                          <p className="text-sm font-medium text-emerald-800">Signed off by {meeting.sign_off_record.signed_by_name}</p>
                        </div>
                        <p className="text-xs text-emerald-600 mt-1">{new Date(meeting.sign_off_record.signed_at).toLocaleString("en-GB")}</p>
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
                  </div>
                )}

                {activeTab === "transcript" && (
                  <div data-testid="transcript-view">
                    <div className="bg-amber-50 border border-amber-200 rounded-md p-3 mb-4 flex items-center gap-2">
                      <FileText className="w-4 h-4 text-amber-600 flex-shrink-0" />
                      <p className="text-xs text-amber-700">Transcript is read-only. Use the Evidence tab to edit summaries and evidence wording.</p>
                    </div>
                    <div className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
                      <pre className="text-sm text-gray-700 whitespace-pre-wrap font-[inherit] leading-relaxed" data-testid="transcript-text">
                        {anonymiseTranscript(meeting.transcript?.text, meeting.attendees || []) || "Transcript not available."}
                      </pre>
                    </div>
                  </div>
                )}

                {activeTab === "comments" && (
                  <div data-testid="comments-view">
                    <div className="space-y-3 mb-6">
                      {meeting.comments?.length === 0 && (
                        <p className="text-sm text-gray-400 text-center py-6">No comments yet</p>
                      )}
                      {meeting.comments?.map(c => (
                        <div key={c.id} className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
                          <div className="flex items-center justify-between mb-2">
                            <span className="text-sm font-medium text-gray-900">{c.user_name}</span>
                            <span className="text-xs text-gray-400">{new Date(c.created_at).toLocaleString("en-GB")}</span>
                          </div>
                          <p className="text-sm text-gray-700">{c.text}</p>
                        </div>
                      ))}
                    </div>
                    {canAddComment && (
                      <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
                        <textarea
                          value={newComment}
                          onChange={e => setNewComment(e.target.value)}
                          placeholder="Add a comment (read-only viewers only — cannot alter the approved record)..."
                          rows={3}
                          className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] resize-none"
                          data-testid="comment-input"
                        />
                        <div className="flex justify-end mt-2">
                          <button onClick={addComment} disabled={!newComment.trim()} className="flex items-center gap-2 bg-[#1E3A8A] text-white px-4 py-1.5 rounded-md text-sm font-medium hover:bg-[#1E40AF] disabled:opacity-50 transition-colors" data-testid="submit-comment-btn">
                            <Send className="w-3.5 h-3.5" />
                            Add Comment
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {activeTab === "audit" && (
                  <div data-testid="audit-trail-view">
                    <div className="flex items-center justify-between mb-4">
                      <div className="flex items-center gap-2">
                        <History className="w-4 h-4 text-gray-500" />
                        <h3 className="text-sm font-semibold text-gray-700" style={{fontFamily:'Work Sans,sans-serif'}}>Audit Trail</h3>
                      </div>
                      <button onClick={fetchAuditTrail} className="text-xs text-[#1E3A8A] hover:underline" data-testid="refresh-audit-btn">Refresh</button>
                    </div>
                    {auditLoading && (
                      <div className="flex items-center justify-center py-10 text-gray-400">
                        <Loader className="w-5 h-5 animate-spin mr-2" />
                        <span className="text-sm">Loading audit trail…</span>
                      </div>
                    )}
                    {!auditLoading && auditTrail?.length === 0 && (
                      <p className="text-sm text-gray-400 text-center py-8">No audit events yet</p>
                    )}
                    {!auditLoading && auditTrail && auditTrail.length > 0 && (
                      <div className="relative" data-testid="audit-trail-list">
                        <div className="absolute left-3 top-0 bottom-0 w-px bg-gray-200" />
                        <div className="space-y-4 pl-8">
                          {auditTrail.map((ev, idx) => (
                            <AuditEvent key={idx} event={ev} />
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* Right: Evidence cards */}
            <div className="lg:col-span-5 bg-[#F8F9FA] overflow-y-auto" style={{ maxHeight: "calc(100vh - 80px)" }}>
              <div className="p-4">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-sm font-semibold text-gray-900" style={{fontFamily:'Work Sans,sans-serif'}}>Compliance Evidence</h2>
                  <div className="flex items-center gap-2 text-xs text-gray-500">
                    <span>{(analysis.cqc_mappings?.length || 0) + (analysis.care_cert_mappings?.length || 0) + (analysis.custom_mappings?.length || 0)} items</span>
                  </div>
                </div>

                {/* CQC */}
                {analysis.cqc_mappings?.length > 0 && (
                  <div className="mb-4">
                    <div className="flex items-center gap-2 mb-2">
                      <Shield className="w-3.5 h-3.5 text-[#1E3A8A]" />
                      <h3 className="text-xs font-semibold text-gray-600 uppercase tracking-wide">CQC Regulations</h3>
                      <span className="ml-auto text-xs text-gray-400">{analysis.cqc_mappings.length}</span>
                    </div>
                    {analysis.cqc_mappings.map(m => (
                      <EvidenceCard key={m.id} mapping={m} isReviewMode={canReview} onUpdateEvidence={updateEvidence} type="cqc" />
                    ))}
                  </div>
                )}

                {/* Care Cert */}
                {analysis.care_cert_mappings?.length > 0 && (
                  <div className="mb-4">
                    <div className="flex items-center gap-2 mb-2">
                      <Award className="w-3.5 h-3.5 text-emerald-600" />
                      <h3 className="text-xs font-semibold text-gray-600 uppercase tracking-wide">Care Certificate</h3>
                      <span className="ml-auto text-xs text-gray-400">{analysis.care_cert_mappings.length}</span>
                    </div>
                    {analysis.care_cert_mappings.map(m => (
                      <EvidenceCard key={m.id} mapping={m} isReviewMode={canReview} onUpdateEvidence={updateEvidence} type="care_cert" />
                    ))}
                  </div>
                )}

                {/* Custom / Organisational */}
                {analysis.custom_mappings?.length > 0 && (
                  <div className="mb-4">
                    <div className="flex items-center gap-2 mb-2">
                      <FileText className="w-3.5 h-3.5 text-teal-600" />
                      <h3 className="text-xs font-semibold text-gray-600 uppercase tracking-wide">Organisational Standards</h3>
                      <span className="ml-auto text-xs text-gray-400">{analysis.custom_mappings.length}</span>
                    </div>
                    {analysis.custom_mappings.map(m => (
                      <EvidenceCard key={m.id} mapping={m} isReviewMode={canReview} onUpdateEvidence={updateEvidence} type="custom" />
                    ))}
                  </div>
                )}

                {(!analysis.cqc_mappings?.length && !analysis.care_cert_mappings?.length && !analysis.custom_mappings?.length) && (
                  <div className="text-center py-12 text-gray-400">
                    <Shield className="w-8 h-8 mx-auto mb-2 opacity-40" />
                    <p className="text-sm">No evidence mappings generated</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Email modal */}
        {showEmailModal && (
          <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
            <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-gray-900">Send Report to Attendees</h3>
                <button onClick={() => setShowEmailModal(false)}><X className="w-4 h-4 text-gray-400" /></button>
              </div>
              <p className="text-sm text-gray-600 mb-3">
                This will email a link to the signed-off report to all attendees who have an email address on record.
              </p>
              <div className="mb-3 p-3 bg-gray-50 rounded-md text-xs text-gray-500">
                <strong>Recipients:</strong> {(meeting?.attendees || []).map(a => a.name).join(", ") || "No attendees"}
              </div>
              <textarea
                value={emailMessage}
                onChange={e => setEmailMessage(e.target.value)}
                placeholder="Optional personal message to include in the email…"
                rows={3}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 resize-none mb-4"
                data-testid="email-message-input"
              />
              <div className="flex gap-2 justify-end">
                <button onClick={() => setShowEmailModal(false)} className="px-4 py-2 text-sm border border-gray-300 text-gray-600 rounded-md hover:bg-gray-50">Cancel</button>
                <button
                  onClick={sendReport}
                  disabled={sendingEmail}
                  className="flex items-center gap-2 px-4 py-2 text-sm bg-emerald-600 text-white rounded-md font-medium hover:bg-emerald-700 disabled:opacity-60"
                  data-testid="confirm-send-email-btn"
                >
                  <Send className="w-3.5 h-3.5" />
                  {sendingEmail ? "Sending…" : "Send Email"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
}

import React, { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import {
  FileText, CheckCircle, ArrowLeft, AlertTriangle, Loader, Shield, Send, RefreshCw, Lock, Info,
} from "lucide-react";
import { toast } from "sonner";
import { EvidenceTab } from "@/components/report/EvidenceTab";
import { TranscriptTab } from "@/components/report/TranscriptTab";
import { CommentsTab } from "@/components/report/CommentsTab";
import { AuditTrailTab } from "@/components/report/AuditTrailTab";
import { EvidenceSidebar } from "@/components/report/EvidenceSidebar";
import { EmailModal } from "@/components/report/EmailModal";
import { PIIReviewGate } from "@/components/PIIReviewGate";

function RetryButton({ meetingId, onRetry, API, getAuthConfig }) {
  const [retrying, setRetrying] = useState(false);
  const [msg, setMsg] = useState("");
  const handleRetry = async () => {
    setRetrying(true);
    setMsg("");
    try {
      await axios.post(`${API}/processing/${meetingId}/retry`, {}, getAuthConfig());
      setMsg("Retry started — the page will update automatically.");
      setTimeout(onRetry, 3000);
    } catch (err) {
      setMsg(err.response?.data?.detail || "Retry failed");
    } finally {
      setRetrying(false);
    }
  };
  return (
    <div>
      <button
        onClick={handleRetry}
        disabled={retrying}
        data-testid="retry-processing-btn"
        className="inline-flex items-center gap-2 bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors disabled:opacity-50"
      >
        <RefreshCw className={`w-4 h-4 ${retrying ? "animate-spin" : ""}`} />
        {retrying ? "Retrying…" : "Retry Processing"}
      </button>
      {msg && <p className="text-xs text-gray-500 mt-2">{msg}</p>}
    </div>
  );
}

const PROCESSING_STAGES = {
  processing:        { label: "Uploading audio...", pct: 20 },
  transcribing:      { label: "Transcribing Audio...", pct: 50 },
  analyzing:         { label: "Mapping compliance evidence with AI...", pct: 80 },
  processing_failed: { label: "Processing failed", pct: 0, error: true },
};

export default function MeetingReport() {
  const { meetingId } = useParams();
  const { getAuthConfig, API, user } = useAuth();
  const navigate = useNavigate();
  const [meeting, setMeeting] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("evidence");
  const [editingSummary, setEditingSummary] = useState(false);
  const [summaryText, setSummaryText] = useState("");
  const [newComment, setNewComment] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [highlightExcerpt, setHighlightExcerpt] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [addingAction, setAddingAction] = useState(false);
  const [newAction, setNewAction] = useState({ text: "", assigned_to: "", due_date: "" });
  const [auditTrail, setAuditTrail] = useState(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [exportingPdf, setExportingPdf] = useState(false);
  const [exportingTranscript, setExportingTranscript] = useState(false);
  const [includeTranscript, setIncludeTranscript] = useState(false);
  const [retranscribing, setRetranscribing] = useState(false);
  const [sendingEmail, setSendingEmail] = useState(false);
  const [showEmailModal, setShowEmailModal] = useState(false);
  const [emailMessage, setEmailMessage] = useState("");
  const [showSignOffConfirm, setShowSignOffConfirm] = useState(false);
  const [speakersDirty, setSpeakersDirty] = useState(false);
  const [piiGateDone, setPiiGateDone] = useState(false);
  const rescanInitiated = useRef(false);

  const isProcessing = ["processing", "transcribing", "analyzing"].includes(meeting?.status);
  const isRescanning = meeting?.rescan_status === "processing";
  const isInReview = meeting?.status === "in_review";
  const isReviewed = meeting?.status === "reviewed";
  const isSignedOff = ["signed_off", "shared"].includes(meeting?.status);
  const canReview = isInReview || isReviewed;
  const canSignOff = user?.role === "manager" || user?.role === "admin";
  const canEditSpeakers = user?.role === "manager" || user?.role === "admin";
  const canAddComment = isSignedOff || ["admin", "manager"].includes(user?.role);
  const canAnonymise = ["manager", "admin"].includes(user?.role) && !!meeting?.transcript?.text;

  const userAttendee = meeting?.attendees?.find(a => a.user_id === user?.id);
  const hasReviewed = userAttendee?.reviewed || false;
  const allReviewed = meeting?.attendees?.length > 0 ? meeting.attendees.every(a => a.reviewed) : true;

  const fetchMeeting = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/meetings/${meetingId}`, getAuthConfig());
      // Guard: never wipe an existing transcript if the API response omitted it
      // (can happen on K8s pod restart when the transcript DB query transiently fails).
      setMeeting(prev => ({
        ...data,
        transcript: data.transcript || prev?.transcript,
      }));
      if (data.analysis?.edited_summary || data.analysis?.summary) {
        setSummaryText(data.analysis?.edited_summary || data.analysis?.summary || "");
      }
    } catch (err) {
      console.error("Failed to load meeting", err);
    } finally {
      setLoading(false);
    }
  }, [meetingId]); // eslint-disable-line react-hooks/exhaustive-deps

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
  }, [meetingId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    fetchMeeting();
    const interval = setInterval(() => { if (isProcessing || isRescanning) fetchMeeting(); }, 5000);
    return () => clearInterval(interval);
  }, [fetchMeeting, isProcessing, isRescanning]);

  // Detect rescan completion and surface result as a toast
  useEffect(() => {
    if (!rescanInitiated.current) return;
    if (meeting?.rescan_status === "done") {
      rescanInitiated.current = false;
      toast.success("Evidence re-scanned — compliance mappings updated.");
    } else if (meeting?.rescan_status === "failed") {
      rescanInitiated.current = false;
      toast.error("Re-scan failed. Please try again or contact support.");
    }
  }, [meeting?.rescan_status]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (activeTab === "audit" && auditTrail === null) fetchAuditTrail();
  }, [activeTab, auditTrail, fetchAuditTrail]);

  const saveSummary = async () => {
    try {
      await axios.put(`${API}/review/${meetingId}/summary`, { summary: summaryText }, getAuthConfig());
      setEditingSummary(false);
      fetchMeeting();
      setActionMessage("Summary saved");
    } catch (err) { setActionMessage(err.response?.data?.detail || "Failed to save"); }
  };

  const updateEvidence = async (evidenceId, updates) => {
    try {
      await axios.put(`${API}/review/${meetingId}/evidence/${evidenceId}`, updates, getAuthConfig());
      fetchMeeting();
    } catch (err) { console.error("Evidence update failed", err); }
  };

  const saveActions = async (updatedActions) => {
    try {
      await axios.put(`${API}/review/${meetingId}/actions`, { actions: updatedActions }, getAuthConfig());
      fetchMeeting();
    } catch (err) { setActionMessage(err.response?.data?.detail || "Failed to save actions"); }
  };

  const addAction = async () => {
    if (!newAction.text.trim()) return;
    const current = meeting?.analysis?.actions || [];
    await saveActions([
      ...current,
      { id: `action_manual_${Date.now()}`, text: newAction.text.trim(), assigned_to: newAction.assigned_to.trim() || null, due_date: newAction.due_date.trim() || null },
    ]);
    setNewAction({ text: "", assigned_to: "", due_date: "" });
    setAddingAction(false);
  };

  const removeAction = async (idx) => {
    const current = meeting?.analysis?.actions || [];
    await saveActions(current.filter((_, i) => i !== idx));
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
      toast.error(err.response?.data?.detail || "Failed to update action");
    }
  };

  const markReviewed = async () => {
    if (speakersDirty) {
      toast.error("You have unsaved speaker label changes. Please save them in the Transcript tab before marking reviewed.");
      return;
    }
    setSubmitting(true);
    try {
      const { data } = await axios.post(`${API}/review/${meetingId}/mark-reviewed`, {}, getAuthConfig());
      toast.success(data.message || "Session marked as reviewed");
      await fetchMeeting();
    } catch (err) { toast.error(err.response?.data?.detail || "Failed to mark reviewed"); }
    finally { setSubmitting(false); }
  };

  const signOff = async () => {
    setShowSignOffConfirm(false);
    if (speakersDirty) {
      toast.error("You have unsaved speaker label changes. Please save them in the Transcript tab first.");
      return;
    }
    setSubmitting(true);
    try {
      await axios.post(`${API}/review/${meetingId}/signoff`, {}, getAuthConfig());
      await fetchMeeting();
      toast.success("Meeting signed off. PDF export is now available.");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to sign off. Please try again.");
    } finally { setSubmitting(false); }
  };

  const addComment = async () => {
    if (!newComment.trim()) return;
    try {
      await axios.post(`${API}/review/${meetingId}/comments`, { text: newComment }, getAuthConfig());
      setNewComment("");
      fetchMeeting();
    } catch (err) { setActionMessage(err.response?.data?.detail || "Failed to add comment"); }
  };

  const handleAnonymise = async (phrase) => {
    try {
      await axios.patch(`${API}/review/${meetingId}/anonymise`, { phrase }, getAuthConfig());
      setActionMessage(`"${phrase}" anonymised successfully`);
      fetchMeeting();
    } catch (err) {
      setActionMessage(err.response?.data?.detail || "Failed to anonymise");
    }
  };

  const handleFindReplace = async (find, replace, count, occurrenceIndex = 0) => {
    try {
      const { data } = await axios.post(
        `${API}/review/${meetingId}/find-replace`,
        { find, replace, replace_one: count === 1, occurrence_index: occurrenceIndex },
        getAuthConfig()
      );
      if (data.replaced_count > 0) {
        await fetchMeeting();
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || "Find & Replace failed");
    }
  };

  const rescanEvidence = async () => {
    if (speakersDirty) {
      toast.error("You have unsaved transcript changes. Save them in the Transcript tab first, then re-scan.");
      return;
    }
    try {
      const { data } = await axios.post(`${API}/review/${meetingId}/rescan-evidence`, {}, getAuthConfig());

      if (data.status === "processing") {
        // Background task started — mark locally so polling and completion toast fire
        rescanInitiated.current = true;
        setMeeting(m => ({ ...m, rescan_status: "processing" }));
        toast.info("Re-scan started — evidence will update automatically in 1–2 minutes.");
        return;
      }

      // Fallback: synchronous response (should not happen in normal flow)
      if (data.analysis) {
        setMeeting(m => ({ ...m, analysis: data.analysis }));
        if (data.analysis?.edited_summary || data.analysis?.summary) {
          setSummaryText(data.analysis?.edited_summary || data.analysis?.summary || "");
        }
      }
      toast.success("Compliance evidence re-scanned successfully");
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Re-scan failed. Please try again.");
    }
  };

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
    } catch (err) { alert("PDF export failed: " + err.message); }
    finally { setExportingPdf(false); }
  };

  const exportTranscript = async () => {
    setExportingTranscript(true);
    try {
      const token = localStorage.getItem("supervision_token");
      const resp = await fetch(`${API}/review/${meetingId}/export-transcript`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) throw new Error(await resp.text());
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `transcript_${meetingId.slice(-6)}.pdf`; a.click();
      URL.revokeObjectURL(url);
    } catch (err) { alert("Transcript export failed: " + err.message); }
    finally { setExportingTranscript(false); }
  };

  const handleRetranscribe = async () => {
    if (!window.confirm(`Re-scan this meeting's audio with AssemblyAI using ${meeting?.attendees?.length || "the"} expected speaker(s)?\n\nThis will update the transcript and speaker view. The meeting status and compliance evidence will not change.`)) return;
    setRetranscribing(true);
    try {
      const token = localStorage.getItem("supervision_token");
      const resp = await fetch(`${API}/processing/${meetingId}/retranscribe`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "Failed");
      toast.success("Re-scan started — refresh this page in 2–3 minutes to see updated speaker diarization.");
    } catch (err) {
      toast.error("Re-scan failed: " + err.message);
    } finally {
      setRetranscribing(false);
    }
  };

  const sendReport = async () => {
    const attendeeEmails = (meeting?.attendees || []).map(a => a.email).filter(Boolean);
    // Fall back to the meeting creator if no attendees have email addresses
    const recipients = attendeeEmails.length
      ? attendeeEmails
      : meeting?.created_by_email
        ? [meeting.created_by_email]
        : [];
    if (!recipients.length) {
      alert("No recipients found — please add attendees or ensure the meeting creator has an email address.");
      return;
    }
    setSendingEmail(true);
    try {
      await axios.post(`${API}/review/${meetingId}/send-email`, { recipients, message: emailMessage }, getAuthConfig());
      setShowEmailModal(false);
      setEmailMessage("");
      toast.success(`Report emailed to ${recipients.length} recipient${recipients.length > 1 ? "s" : ""}.`);
    } catch (err) {
      toast.error("Email failed: " + (err.response?.data?.detail || err.message));
    } finally { setSendingEmail(false); }
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

  if (!meeting) return <Layout><div className="p-8 text-center text-gray-500">Meeting not found</div></Layout>;

  // ── PII confidentiality gate ─────────────────────────────────────────
  // Show for managers/admins on first open of a processed meeting
  const shouldShowPIIGate =
    !piiGateDone &&
    meeting.pii_review_status !== "reviewed" &&
    (user?.role === "manager" || user?.role === "admin") &&
    !!meeting.transcript &&
    !!meeting.analysis &&
    !isProcessing;

  if (shouldShowPIIGate) {
    return (
      <Layout>
        <PIIReviewGate
          meetingId={meetingId}
          onComplete={async () => {
            await fetchMeeting();
            setPiiGateDone(true);
          }}
          API={API}
          getAuthConfig={getAuthConfig}
        />
      </Layout>
    );
  }

  const stageCfg = PROCESSING_STAGES[meeting.status];
  const analysis = meeting.analysis;

  const tabBtnCls = (t) => `flex-shrink-0 text-sm font-medium pb-1 border-b-2 transition-colors ${activeTab === t ? "border-[#1E3A8A] text-[#1E3A8A]" : "border-transparent text-gray-500 hover:text-gray-700"}`;

  return (
    <Layout>
      <div className="flex flex-col h-full">
        {/* Top bar */}
        <div className="bg-white border-b border-gray-200 px-4 sm:px-6 py-3 sm:py-4 flex items-center justify-between sticky top-0 z-20 gap-2">
          <div className="flex items-center gap-4">
            <button onClick={() => navigate("/dashboard")} className="text-gray-500 hover:text-gray-700 flex items-center gap-1 text-sm">
              <ArrowLeft className="w-4 h-4" />
            </button>
            <div>
              <h1 className="text-base font-semibold text-gray-900 leading-tight font-display">{meeting.title}</h1>
              <div className="flex items-center gap-3 text-xs text-gray-500 mt-0.5">
                <span>{new Date(meeting.date).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}</span>
                {meeting.location && <span>{meeting.location}</span>}
                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-medium border text-xs ${isSignedOff ? "bg-emerald-100 text-emerald-800 border-emerald-200" : canReview ? "bg-amber-100 text-amber-800 border-amber-200" : "bg-blue-100 text-blue-700 border-blue-200"}`}>
                  {meeting.status.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase())}
                </span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {canReview && !hasReviewed && (
              <button onClick={markReviewed} disabled={submitting} className="flex items-center gap-2 bg-[#059669] text-white px-3 py-2 rounded-md text-sm font-medium hover:bg-emerald-700 transition-colors disabled:opacity-60" data-testid="mark-reviewed-btn">
                <CheckCircle className="w-4 h-4" />
                <span className="hidden sm:inline">Mark Reviewed</span>
              </button>
            )}
            {hasReviewed && canReview && (
              <span className="hidden sm:flex items-center gap-1.5 text-emerald-600 text-sm font-medium">
                <CheckCircle className="w-4 h-4" /> You reviewed this
              </span>
            )}
            {canSignOff && !isSignedOff && !isProcessing && analysis && (
              <button onClick={() => setShowSignOffConfirm(true)} disabled={submitting} className="flex items-center gap-2 bg-[#1E3A8A] text-white px-3 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors disabled:opacity-60" data-testid="sign-off-btn">
                <Shield className="w-4 h-4" />
                <span className="hidden sm:inline">Sign Off</span>
              </button>
            )}
            {canSignOff && (
              <div className="flex items-center gap-2">
                {isSignedOff ? (
                  <div className="flex items-center gap-2">
                    <div className="flex items-center bg-white border border-gray-200 rounded-md shadow-sm">
                      <button onClick={exportPdf} disabled={exportingPdf} className="flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors disabled:opacity-60 rounded-l-md" data-testid="export-pdf-btn" title="Export PDF">
                        <FileText className="w-4 h-4 text-gray-500" />
                        <span className="hidden sm:inline">{exportingPdf ? "Generating…" : "Export PDF"}</span>
                      </button>
                      <div className="hidden sm:flex border-l border-gray-200 px-2 py-2 items-center gap-1.5">
                        <input type="checkbox" id="include-transcript" checked={includeTranscript} onChange={e => setIncludeTranscript(e.target.checked)} className="w-3.5 h-3.5 accent-[#1E3A8A]" data-testid="include-transcript-toggle" />
                        <label htmlFor="include-transcript" className="text-xs text-gray-500 cursor-pointer select-none">+ Full text</label>
                      </div>
                    </div>
                    <button
                      onClick={exportTranscript}
                      disabled={exportingTranscript}
                      className="flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-md shadow-sm hover:bg-gray-50 transition-colors disabled:opacity-60"
                      data-testid="export-transcript-btn"
                      title="Download transcript only"
                    >
                      <FileText className="w-4 h-4 text-gray-500" />
                      <span className="hidden sm:inline">{exportingTranscript ? "Generating…" : "Transcript"}</span>
                    </button>
                    {meeting?.audio_file_id && canEditSpeakers && (
                      <button
                        onClick={handleRetranscribe}
                        disabled={retranscribing}
                        className="flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded-md shadow-sm hover:bg-amber-100 transition-colors disabled:opacity-60"
                        data-testid="retranscribe-btn"
                        title={`Re-scan audio with ${meeting?.attendees?.length || "?"} expected speakers`}
                      >
                        <RefreshCw className="w-4 h-4" />
                        <span className="hidden sm:inline">{retranscribing ? "Scanning…" : "Re-scan Audio"}</span>
                      </button>
                    )}
                  </div>
                ) : (
                  <button
                    onClick={() => toast.info("Sign off the meeting first to unlock PDF export and email sharing.")}
                    className="flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-gray-400 bg-white border border-gray-200 rounded-md shadow-sm hover:bg-gray-50 transition-colors"
                    data-testid="export-pdf-locked-btn"
                    title="Sign off required to export"
                  >
                    <Lock className="w-4 h-4" />
                    <span className="hidden sm:inline">Export PDF</span>
                  </button>
                )}
                {isSignedOff && (
                  <button onClick={() => setShowEmailModal(true)} className="flex items-center gap-1.5 bg-emerald-600 text-white px-3 py-2 rounded-md text-sm font-medium hover:bg-emerald-700 transition-colors" data-testid="send-report-btn">
                    <Send className="w-4 h-4" />
                    <span className="hidden sm:inline">Send to Attendees</span>
                  </button>
                )}
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
                <p className="text-sm text-gray-500 mb-4">Please try re-uploading the recording.</p>
                <RetryButton meetingId={meetingId} onRetry={fetchMeeting} API={API} getAuthConfig={getAuthConfig} />
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

        {/* Not yet processed — recording/draft/stopped state */}
        {!stageCfg && !analysis && (
          <div className="flex-1 flex items-center justify-center p-12">
            <div className="text-center max-w-sm">
              <div className="w-14 h-14 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <Loader className="w-7 h-7 text-gray-400" />
              </div>
              <h3 className="font-semibold text-gray-900 mb-2">
                {meeting?.status === "recording" ? "Recording in progress" : "No report yet"}
              </h3>
              <p className="text-sm text-gray-500 mb-5">
                {meeting?.status === "recording"
                  ? "This meeting is still being recorded. Go to the recording screen to stop and upload the audio."
                  : "This meeting hasn't been recorded and processed yet. Start a recording to generate a report."}
              </p>
              <button
                onClick={() => navigate(`/meetings/${meetingId}/record`)}
                className="bg-[#1E3A8A] text-white px-5 py-2.5 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors"
              >
                Go to Recording Screen
              </button>
            </div>
          </div>
        )}

        {/* Content */}
        {!stageCfg && analysis && (
          <div className="flex-1 grid grid-cols-1 lg:grid-cols-12 gap-0 overflow-hidden">
            {/* Left: tabs */}
            <div className="lg:col-span-7 border-r border-gray-200 flex flex-col overflow-hidden">
              <div className="border-b border-gray-200 px-6 py-3 flex items-center gap-4 overflow-x-auto scrollbar-hide">
                <button onClick={() => setActiveTab("evidence")} className={tabBtnCls("evidence")}>Evidence</button>
                <button onClick={() => setActiveTab("transcript")} className={tabBtnCls("transcript")}>Transcript</button>
                <button onClick={() => setActiveTab("comments")} className={tabBtnCls("comments")} data-testid="comments-tab">
                  Comments {meeting.comments?.length > 0 && `(${meeting.comments.length})`}
                </button>
                <button onClick={() => setActiveTab("audit")} className={tabBtnCls("audit")} data-testid="audit-trail-tab">Audit Trail</button>
                <button onClick={() => setActiveTab("compliance")} className={`${tabBtnCls("compliance")} lg:hidden`} data-testid="compliance-tab">Compliance</button>
              </div>

              <div className="flex-1 overflow-y-auto p-6">
                {activeTab === "evidence" && (
                  <EvidenceTab
                    meeting={meeting}
                    analysis={analysis}
                    canReview={canReview}
                    editingSummary={editingSummary}
                    setEditingSummary={setEditingSummary}
                    summaryText={summaryText}
                    setSummaryText={setSummaryText}
                    saveSummary={saveSummary}
                    addingAction={addingAction}
                    setAddingAction={setAddingAction}
                    newAction={newAction}
                    setNewAction={setNewAction}
                    addAction={addAction}
                    removeAction={removeAction}
                    toggleActionComplete={toggleActionComplete}
                    actionMessage={actionMessage}
                    onSummaryRegenerated={newSummary => {
                      setMeeting(m => ({ ...m, analysis: { ...m.analysis, summary: newSummary } }));
                      setSummaryText(newSummary);
                    }}
                  />
                )}
                {/* TranscriptTab stays mounted to preserve unsaved speaker edits
                    across tab switches — hidden with CSS rather than unmounted */}
                <div className={activeTab === "transcript" ? "" : "hidden"}>
                  <TranscriptTab
                    meeting={meeting}
                    onAnonymise={handleAnonymise}
                    canAnonymise={canAnonymise}
                    canEditSpeakers={canEditSpeakers}
                    highlightExcerpt={highlightExcerpt}
                    onDirtyChange={(dirty) => setSpeakersDirty(dirty)}
                    onFindReplace={handleFindReplace}
                    onSpeakerTextGenerated={(spText, editedByName, editedAt, speakerColors) => setMeeting(m => ({
                      ...m,
                      transcript: {
                        ...m.transcript,
                        speaker_text: spText,
                        speaker_text_edited_by_name: editedByName || null,
                        speaker_text_edited_at: editedAt || null,
                        ...(speakerColors !== undefined ? { speaker_colors: speakerColors } : {}),
                      }
                    }))}
                  />
                </div>
                {activeTab === "comments" && (
                  <CommentsTab
                    meeting={meeting}
                    canAddComment={canAddComment}
                    newComment={newComment}
                    setNewComment={setNewComment}
                    addComment={addComment}
                  />
                )}
                {activeTab === "audit" && (
                  <AuditTrailTab
                    auditLoading={auditLoading}
                    auditTrail={auditTrail}
                    fetchAuditTrail={fetchAuditTrail}
                  />
                )}
                {activeTab === "compliance" && (
                  <div className="-m-6">
                    <EvidenceSidebar
                      analysis={analysis}
                      canReview={canReview}
                      updateEvidence={updateEvidence}
                      canRescan={canEditSpeakers && !!meeting?.transcript_id}
                      onRescanEvidence={rescanEvidence}
                      onShowInTranscript={(excerpt) => { setHighlightExcerpt(excerpt); setActiveTab("transcript"); }}
                      className="bg-[#F8F9FA]"
                      noMaxHeight
                    />
                  </div>
                )}
              </div>
            </div>

            <EvidenceSidebar
              analysis={analysis}
              canReview={canReview}
              updateEvidence={updateEvidence}
              canRescan={canEditSpeakers && !!meeting?.transcript_id}
              onRescanEvidence={rescanEvidence}
              onShowInTranscript={(excerpt) => { setHighlightExcerpt(excerpt); setActiveTab("transcript"); }}
              className="hidden lg:block lg:col-span-5 bg-[#F8F9FA] overflow-y-auto"
            />
          </div>
        )}

        <EmailModal
          show={showEmailModal}
          onClose={() => setShowEmailModal(false)}
          meeting={meeting}
          sendingEmail={sendingEmail}
          emailMessage={emailMessage}
          setEmailMessage={setEmailMessage}
          sendReport={sendReport}
        />

        {/* Sign-off confirmation modal */}
        {showSignOffConfirm && (() => {
          const outstanding = (meeting?.analysis?.actions || []).filter(a => !a.completed);
          const unreviewed = (meeting?.attendees || []).filter(a => !a.reviewed);
          return (
            <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40" data-testid="signoff-confirm-modal">
              <div className="bg-white rounded-xl shadow-2xl w-full max-w-sm p-6">
                <h3 className="text-base font-semibold text-gray-900 mb-2">Sign off this session?</h3>
                <p className="text-sm text-gray-500 mb-4">This will start the audio deletion process and mark the meeting as complete.</p>
                {unreviewed.length > 0 && (
                  <div className="flex items-start gap-2.5 bg-blue-50 border border-blue-200 rounded-lg p-3 mb-3" data-testid="unreviewed-attendees-warning">
                    <Info className="w-4 h-4 text-blue-600 flex-shrink-0 mt-0.5" />
                    <p className="text-sm text-blue-800">
                      <span className="font-medium">{unreviewed.length} {unreviewed.length === 1 ? "attendee has" : "attendees have"} not yet reviewed:</span>{" "}
                      {unreviewed.map(a => a.name).join(", ")}.
                    </p>
                  </div>
                )}
                {outstanding.length > 0 && (
                  <div className="flex items-start gap-2.5 bg-amber-50 border border-amber-200 rounded-lg p-3 mb-4" data-testid="outstanding-actions-warning">
                    <AlertTriangle className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
                    <p className="text-sm text-amber-800">
                      <span className="font-medium">{outstanding.length} outstanding {outstanding.length === 1 ? "action" : "actions"}.</span>{" "}
                      These will automatically be carried over to the next session.
                    </p>
                  </div>
                )}
                <div className="flex gap-2 justify-end">
                  <button
                    onClick={() => setShowSignOffConfirm(false)}
                    className="px-4 py-2 text-sm font-medium text-gray-700 border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
                    data-testid="signoff-cancel-btn"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={signOff}
                    disabled={submitting}
                    className="flex items-center gap-2 px-4 py-2 text-sm font-medium bg-[#1E3A8A] text-white rounded-md hover:bg-[#1E40AF] transition-colors disabled:opacity-60"
                    data-testid="signoff-confirm-btn"
                  >
                    <Shield className="w-4 h-4" />
                    {submitting ? "Signing off…" : "Sign Off"}
                  </button>
                </div>
              </div>
            </div>
          );
        })()}
      </div>
    </Layout>
  );
}

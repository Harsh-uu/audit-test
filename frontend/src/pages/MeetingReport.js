import React, { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import { Skeleton } from "@/components/ui/skeleton";
import {
  FileText, CheckCircle, ArrowLeft, AlertTriangle, Loader2, Shield, Send, RefreshCw, Lock, Info, Share2,
} from "lucide-react";
import { toast } from "sonner";
import { EvidenceTab } from "@/components/report/EvidenceTab";
import { TranscriptTab } from "@/components/report/TranscriptTab";
import { CommentsTab } from "@/components/report/CommentsTab";
import { AuditTrailTab } from "@/components/report/AuditTrailTab";
import { EvidenceSidebar } from "@/components/report/EvidenceSidebar";
import { EmailModal } from "@/components/report/EmailModal";
import { ShareModal } from "@/components/report/ShareModal";
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
  const navigate = useNavigate();
  const location = useLocation();
  const { getAuthConfig, API, user } = useAuth();
  const [meeting, setMeeting] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("evidence");
  const [editingSummary, setEditingSummary] = useState(false);
  const [summaryText, setSummaryText] = useState("");
  const [newComment, setNewComment] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [highlightExcerpt, setHighlightExcerpt] = useState("");
  const [highlightKey, setHighlightKey] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [addingAction, setAddingAction] = useState(false);
  const [newAction, setNewAction] = useState({ text: "", assigned_to: "", due_date: "" });
  const [auditTrail, setAuditTrail] = useState(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [exportingPdf, setExportingPdf] = useState(false);
  const [exportingTranscript, setExportingTranscript] = useState(false);
  const [includeTranscript, setIncludeTranscript] = useState(false);
  const [sendingEmail, setSendingEmail] = useState(false);
  const [showEmailModal, setShowEmailModal] = useState(false);
  const [showShareModal, setShowShareModal] = useState(false);
  const [emailMessage, setEmailMessage] = useState("");
  const [showSignOffConfirm, setShowSignOffConfirm] = useState(false);
  const [speakersDirty, setSpeakersDirty] = useState(false);
  const [piiGateDone, setPiiGateDone] = useState(false);
  const rescanInitiated = useRef(false);
  const [warningDismissed, setWarningDismissed] = useState(
    () => !!localStorage.getItem(`tw_dismissed_${meetingId}`)
  );

  const isProcessing = ["processing", "transcribing", "analyzing"].includes(meeting?.status);
  const isRescanning = meeting?.rescan_status === "processing";
  const isInReview = meeting?.status === "in_review";
  const isReviewed = meeting?.status === "reviewed";
  const isSignedOff = ["signed_off", "shared"].includes(meeting?.status);
  const isLocked = isSignedOff;
  const canReview = isInReview || isReviewed;
  const canSignOff = user?.role === "manager" || user?.role === "admin";
  const canEditSpeakers = (user?.role === "manager" || user?.role === "admin") && !isLocked;
  const canAddComment = isSignedOff || ["admin", "manager"].includes(user?.role);
  const canAnonymise = ["manager", "admin"].includes(user?.role) && !!meeting?.transcript?.text && !isLocked;

  const userAttendee = meeting?.attendees?.find(a => a.user_id === user?.id);
  const hasReviewed = userAttendee?.reviewed || false;
  const allReviewed = meeting?.attendees?.length > 0 ? meeting.attendees.every(a => a.reviewed) : true;

  const fetchMeeting = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/meetings/${meetingId}`, getAuthConfig());
      setMeeting(prev => ({
        ...data,
        transcript: data.transcript || prev?.transcript,
      }));
      if (data.analysis?.edited_summary || data.analysis?.summary) {
        setSummaryText(data.analysis?.edited_summary || data.analysis?.summary || "");
      }
    } catch (err) {
      console.error("Failed to load meeting", err.message);
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
      console.error("Failed to load audit trail", err.message);
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

  // Auto-open transcript tab with highlight when navigated from portfolio "View in transcript"
  useEffect(() => {
    if (location.state?.highlightExcerpt) {
      setHighlightExcerpt(location.state.highlightExcerpt);
      setActiveTab("transcript");
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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
    const prev = meeting;
    // Optimistic: close editing immediately with the new text
    setMeeting(m => ({ ...m, analysis: { ...m.analysis, edited_summary: summaryText } }));
    setEditingSummary(false);
    try {
      await axios.put(`${API}/review/${meetingId}/summary`, { summary: summaryText }, getAuthConfig());
      setActionMessage("Summary saved");
    } catch (err) {
      setMeeting(prev);         // revert content
      setEditingSummary(true);  // re-open edit mode so the user doesn't lose their work
      setActionMessage(err.response?.data?.detail || "Failed to save");
    }
  };

  const updateEvidence = useCallback(async (evidenceId, updates) => {
    const prev = meeting;
    // Optimistic: patch the matching item across all three mapping arrays
    const patchMappings = arr => (arr || []).map(e => e.id === evidenceId ? { ...e, ...updates } : e);
    setMeeting(m => ({
      ...m,
      analysis: {
        ...m.analysis,
        cqc_mappings:       patchMappings(m.analysis?.cqc_mappings),
        care_cert_mappings: patchMappings(m.analysis?.care_cert_mappings),
        custom_mappings:    patchMappings(m.analysis?.custom_mappings),
      },
    }));
    try {
      await axios.put(`${API}/review/${meetingId}/evidence/${evidenceId}`, updates, getAuthConfig());
    } catch (err) {
      setMeeting(prev); // revert on failure
      console.error("Evidence update failed", err.message);
      toast.error("Failed to update evidence — changes reverted.");
    }
  }, [meetingId, meeting]); // eslint-disable-line react-hooks/exhaustive-deps

  const onShowInTranscript = useCallback((excerpt) => {
    setHighlightExcerpt(excerpt);
    setHighlightKey(k => k + 1);
    setActiveTab("transcript");
  }, []);

  const onDirtyChange = useCallback((dirty) => setSpeakersDirty(dirty), []);

  const onAnalysisChange = useCallback(
    (updatedAnalysis) => setMeeting(m => ({ ...m, analysis: updatedAnalysis })),
    []
  );

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
      console.error("Failed to update action", err.message);
      toast.error(err.response?.data?.detail || "Failed to update action");
    }
  };

  const markReviewed = async () => {
    if (speakersDirty) {
      toast.error("You have unsaved speaker label changes. Please save them in the Transcript tab before marking reviewed.");
      return;
    }
    const prev = meeting;
    setSubmitting(true);
    // Optimistic: flip the badge immediately
    setMeeting(m => ({ ...m, status: "reviewed" }));
    try {
      const { data } = await axios.post(`${API}/review/${meetingId}/mark-reviewed`, {}, getAuthConfig());
      toast.success(data.message || "Session marked as reviewed");
      // Server decides between 'reviewed' and 'in_review' based on all-attendees state
      setMeeting(m => ({ ...m, status: data.status }));
    } catch (err) {
      setMeeting(prev); // revert
      toast.error(err.response?.data?.detail || "Failed to mark reviewed");
    } finally { setSubmitting(false); }
  };

  const signOff = async () => {
    setShowSignOffConfirm(false);
    if (speakersDirty) {
      toast.error("You have unsaved speaker label changes. Please save them in the Transcript tab first.");
      return;
    }
    const prev = meeting;
    setSubmitting(true);
    // Optimistic: flip badge immediately so the UI feels instant
    setMeeting(m => ({ ...m, status: "signed_off" }));
    try {
      await axios.post(`${API}/review/${meetingId}/signoff`, {}, getAuthConfig());
      toast.success("Meeting signed off. PDF export is now available.");
      await fetchMeeting(); // pull sign_off_record + audio_deletion_status from server
    } catch (err) {
      setMeeting(prev); // revert
      toast.error(err.response?.data?.detail || "Failed to sign off. Please try again.");
    } finally { setSubmitting(false); }
  };

  const addComment = async () => {
    if (!newComment.trim()) return;
    const text = newComment.trim();
    const tempId = `temp_${Date.now()}`;
    const tempComment = {
      id: tempId,
      text,
      author_name: user?.name || "You",
      created_at: new Date().toISOString(),
    };
    // Optimistic: show comment immediately and clear input
    setMeeting(m => ({ ...m, comments: [...(m.comments || []), tempComment] }));
    setNewComment("");
    try {
      await axios.post(`${API}/review/${meetingId}/comments`, { text }, getAuthConfig());
      fetchMeeting(); // replace temp comment with server record (gets proper id/timestamp)
    } catch (err) {
      // Revert: remove temp comment and restore the typed text
      setMeeting(m => ({ ...m, comments: (m.comments || []).filter(c => c.id !== tempId) }));
      setNewComment(text);
      setActionMessage(err.response?.data?.detail || "Failed to add comment");
    }
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

  const rescanEvidence = async (customPrompt = "") => {
    if (speakersDirty) {
      toast.error("You have unsaved transcript changes. Save them in the Transcript tab first, then re-scan.");
      return;
    }
    try {
      const { data } = await axios.post(
        `${API}/review/${meetingId}/rescan-evidence`,
        { custom_prompt: customPrompt || null },
        getAuthConfig()
      );

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

  const handleReopenRequest = async (reason) => {
    const prev = meeting;
    setMeeting(m => ({ ...m, reopen_requested: true }));
    try {
      await axios.post(`${API}/review/${meetingId}/request-reopen`, { reason }, getAuthConfig());
      toast.success("Re-open requested — the other party will see an approval prompt.");
    } catch (err) {
      setMeeting(prev);
      toast.error(err?.response?.data?.detail || "Failed to request re-open.");
    }
  };

  const handleApproveReopen = async () => {
    const prev = meeting;
    setMeeting(m => ({ ...m, status: "reviewed", reopen_requested: false }));
    try {
      await axios.post(`${API}/review/${meetingId}/approve-reopen`, {}, getAuthConfig());
      toast.success("Re-open approved — report is now unlocked for editing.");
    } catch (err) {
      setMeeting(prev);
      toast.error(err?.response?.data?.detail || "Failed to approve re-open.");
      await fetchMeeting();
    }
  };

  const exportPdf = async () => {
    setExportingPdf(true);
    try {
      // P3b: use credentials:'include' so HttpOnly cookie is sent by fetch()
      const resp = await fetch(`${API}/review/${meetingId}/export-pdf?include_transcript=${includeTranscript}`, {
        credentials: 'include',
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
      // P3b: use credentials:'include' so HttpOnly cookie is sent by fetch()
      const resp = await fetch(`${API}/review/${meetingId}/export-transcript`, {
        credentials: 'include',
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

  const sendReport = async (recipients) => {
    if (!recipients || recipients.length === 0) {
      toast.error("No recipient email addresses found. Please add an email address in the recipients list.");
      return;
    }
    setSendingEmail(true);
    try {
      await axios.post(`${API}/review/${meetingId}/send-email`, { recipients, message: emailMessage }, getAuthConfig());
      setShowEmailModal(false);
      setEmailMessage("");
      toast.success(`Report emailed to ${recipients.length} recipient${recipients.length > 1 ? "s" : ""}: ${recipients.join(", ")}`);
    } catch (err) {
      toast.error("Email failed: " + (err.response?.data?.detail || err.message));
    } finally { setSendingEmail(false); }
  };

  if (loading) {
    return (
      <Layout>
        <div className="flex flex-col h-full">
          {/* Top bar skeleton — mirrors the sticky header */}
          <div className="bg-white border-b border-gray-200 px-4 sm:px-6 py-3 sm:py-4 flex items-center justify-between sticky top-0 z-20 gap-2">
            <div className="flex items-center gap-4">
              <Skeleton className="h-4 w-4 rounded" />
              <div className="space-y-1.5">
                <Skeleton className="h-4 w-48" />
                <div className="flex items-center gap-3">
                  <Skeleton className="h-3 w-24" />
                  <Skeleton className="h-5 w-20 rounded-full" />
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Skeleton className="h-8 w-28 rounded-md" />
              <Skeleton className="h-8 w-24 rounded-md" />
            </div>
          </div>
          {/* Two-panel skeleton — mirrors the 7/5 column layout */}
          <div className="flex-1 grid grid-cols-1 lg:grid-cols-12 gap-0 overflow-hidden">
            {/* Left: tab row + content */}
            <div className="lg:col-span-7 border-r border-gray-200 flex flex-col">
              <div className="border-b border-gray-200 px-6 py-3 flex items-center gap-6">
                <Skeleton className="h-4 w-16" />
                <Skeleton className="h-4 w-20" />
                <Skeleton className="h-4 w-16" />
                <Skeleton className="h-4 w-14" />
                <Skeleton className="h-4 w-16" />
              </div>
              <div className="p-6 space-y-5">
                <Skeleton className="h-5 w-40" />
                <Skeleton className="h-24 w-full rounded-lg" />
                <Skeleton className="h-5 w-32" />
                {[...Array(4)].map((_, i) => (
                  <div key={i} className="flex items-start gap-3">
                    <Skeleton className="h-4 w-4 rounded-full flex-shrink-0 mt-0.5" />
                    <Skeleton className="h-4 flex-1" />
                  </div>
                ))}
                <Skeleton className="h-5 w-28 mt-2" />
                {[...Array(3)].map((_, i) => (
                  <div key={i} className="flex items-start gap-3">
                    <Skeleton className="h-4 w-4 rounded-full flex-shrink-0 mt-0.5" />
                    <Skeleton className="h-4" style={{ width: `${55 + i * 12}%` }} />
                  </div>
                ))}
              </div>
            </div>
            {/* Right: compliance panel */}
            <div className="hidden lg:flex lg:col-span-5 flex-col p-6 gap-4">
              <Skeleton className="h-5 w-36" />
              {[...Array(5)].map((_, i) => (
                <div key={i} className="border border-gray-100 rounded-lg p-3 space-y-2">
                  <Skeleton className="h-3 w-20" />
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-3 w-3/4" />
                </div>
              ))}
            </div>
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
        {/* Safety warning banner — shown when transcript has AI hallucination or content flags */}
        {meeting.transcript_has_warnings && !warningDismissed && (
          <div className="bg-red-600 text-white px-4 py-3 flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 flex-shrink-0 mt-0.5" />
            <div className="flex-1 text-sm">
              <span className="font-semibold">Transcript Safety Warning: </span>
              This transcript was automatically flagged for potentially hallucinated or inappropriate content.
              Review carefully before sharing. Use the <strong>Find &amp; Replace</strong> tool in the Transcript tab to remove any incorrect text.
            </div>
            <button
              onClick={() => {
                localStorage.setItem(`tw_dismissed_${meetingId}`, "1");
                setWarningDismissed(true);
              }}
              title="Dismiss warning"
              className="flex-shrink-0 ml-2 text-white/70 hover:text-white transition-colors"
              data-testid="dismiss-transcript-warning-btn"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>
        )}
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
              <button
                onClick={() => setShowSignOffConfirm(true)}
                disabled={submitting || isInReview}
                title={isInReview ? "All attendees must mark the session as reviewed before sign-off can be triggered" : "Sign off this session"}
                className="flex items-center gap-2 bg-[#1E3A8A] text-white px-3 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
                data-testid="sign-off-btn"
              >
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
                {isSignedOff && canSignOff && (
                  <button
                    onClick={() => setShowShareModal(true)}
                    className="flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-indigo-700 bg-white border border-indigo-200 rounded-md shadow-sm hover:bg-indigo-50 transition-colors"
                    data-testid="share-report-btn"
                    title="Share with other team members"
                  >
                    <Share2 className="w-4 h-4" />
                    <span className="hidden sm:inline">
                      {meeting?.shared_with?.length ? `Shared (${meeting.shared_with.length})` : "Share"}
                    </span>
                  </button>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Processing state — three-stage stepper */}
        {stageCfg && !stageCfg.error && (
          <div className="flex-1 flex items-center justify-center p-8" data-testid="processing-indicator">
            <div className="w-full max-w-lg">
              <div className="text-center mb-8">
                <div className="w-12 h-12 border-[3px] border-[#1E3A8A] border-t-transparent rounded-full spin mx-auto mb-4"></div>
                <h3 className="font-semibold text-gray-900 text-lg">Processing your recording</h3>
                <p className="text-sm text-gray-500 mt-1">Do not close or refresh this page whilst processing the meeting</p>
              </div>

              <div className="space-y-5">
                {[
                  {
                    key: "processing",
                    icon: "1",
                    title: "Uploading & Compressing Audio",
                    desc: "Audio is compressed to 16 kHz mono MP3 for optimal transcription",
                    eta: "~10–30 seconds",
                  },
                  {
                    key: "transcribing",
                    icon: "2",
                    title: "Transcribing Recording",
                    desc: "AssemblyAI converts the audio to a speaker-labelled transcript",
                    eta: "~1–5 minutes",
                  },
                  {
                    key: "analyzing",
                    icon: "3",
                    title: "Mapping Compliance Evidence",
                    desc: "AI reviews the transcript and maps discussion points to regulatory standards",
                    eta: "~30–90 seconds",
                  },
                ].map((stage, idx) => {
                  const ORDER = ["processing", "transcribing", "analyzing"];
                  const currentIdx = ORDER.indexOf(meeting.status);
                  const stageIdx   = ORDER.indexOf(stage.key);
                  const isDone     = stageIdx < currentIdx;
                  const isActive   = stageIdx === currentIdx;
                  const isPending  = stageIdx > currentIdx;
                  return (
                    <div key={stage.key} className={`rounded-xl border p-4 transition-all ${
                      isActive  ? "border-[#1E3A8A] bg-blue-50/60 shadow-sm" :
                      isDone    ? "border-emerald-200 bg-emerald-50/40" :
                                  "border-gray-100 bg-gray-50/60 opacity-60"
                    }`}>
                      <div className="flex items-start gap-3 mb-3">
                        <div className={`w-7 h-7 rounded-full flex-shrink-0 flex items-center justify-center text-xs font-bold mt-0.5 ${
                          isDone   ? "bg-emerald-500 text-white" :
                          isActive ? "bg-[#1E3A8A] text-white" :
                                     "bg-gray-200 text-gray-400"
                        }`}>
                          {isDone ? "✓" : stage.icon}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between gap-2">
                            <span className={`text-sm font-semibold ${
                              isActive ? "text-[#1E3A8A]" : isDone ? "text-emerald-700" : "text-gray-400"
                            }`}>{stage.title}</span>
                            <span className={`text-xs flex-shrink-0 ${
                              isActive ? "text-[#1E3A8A]" : isDone ? "text-emerald-600" : "text-gray-300"
                            }`}>
                              {isDone ? "Complete" : isActive ? stage.eta : "Waiting"}
                            </span>
                          </div>

                        </div>
                      </div>
                      <div className="h-1.5 rounded-full bg-gray-200 overflow-hidden ml-10">
                        <div className={`h-full rounded-full transition-all duration-700 ${
                          isDone   ? "w-full bg-emerald-500" :
                          isActive ? "bg-[#1E3A8A] animate-pulse" :
                                     "w-0"
                        } ${isActive ? "w-3/4" : ""}`}></div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* Processing failed state */}
        {stageCfg && stageCfg.error && (
          <div className="p-8 flex flex-col items-center justify-center" data-testid="processing-indicator">
            <div className="text-center">
              <AlertTriangle className="w-10 h-10 text-red-400 mx-auto mb-3" />
              <h3 className="font-semibold text-gray-900 mb-1">Processing failed</h3>
              {meeting?.processing_error && (
                <p className="text-xs text-red-600 font-mono bg-red-50 border border-red-200 rounded px-3 py-2 mb-3 max-w-md text-left break-words">
                  {meeting.processing_error}
                </p>
              )}
              <p className="text-sm text-gray-500 mb-4">Please try re-uploading the recording.</p>
              <RetryButton meetingId={meetingId} onRetry={fetchMeeting} API={API} getAuthConfig={getAuthConfig} />
            </div>
          </div>
        )}

        {/* Not yet processed — recording/draft/stopped state */}
        {!stageCfg && !analysis && (
          <div className="flex-1 flex items-center justify-center p-12">
            <div className="text-center max-w-sm">
              <div className="w-14 h-14 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <Loader2 className="w-7 h-7 text-gray-400" />
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
          <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-12 gap-0 overflow-hidden">
            {/* Left: tabs */}
            <div className="lg:col-span-7 border-r border-gray-200 flex flex-col overflow-hidden min-h-0">
              <div className="sticky top-0 z-10 bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-4 overflow-x-auto scrollbar-hide flex-shrink-0">
                <button onClick={() => setActiveTab("evidence")} className={tabBtnCls("evidence")} data-testid="overview-tab">Overview</button>
                <button onClick={() => setActiveTab("transcript")} className={tabBtnCls("transcript")}>Transcript</button>
                <button onClick={() => setActiveTab("comments")} className={tabBtnCls("comments")} data-testid="comments-tab">
                  Comments {meeting.comments?.length > 0 && `(${meeting.comments.length})`}
                </button>
                <button onClick={() => setActiveTab("audit")} className={tabBtnCls("audit")} data-testid="audit-trail-tab">Audit Trail</button>
                <button onClick={() => setActiveTab("compliance")} className={`${tabBtnCls("compliance")} lg:hidden`} data-testid="compliance-tab">Compliance</button>
                <button onClick={() => setActiveTab("prep")} className={tabBtnCls("prep")} data-testid="prep-tab">Prep Agenda</button>
              </div>

              <div className="flex-1 min-h-0 overflow-y-auto p-6">
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
                    onAnalysisChange={onAnalysisChange}
                    isLocked={isLocked}
                    onReopenRequest={handleReopenRequest}
                    onApproveReopen={handleApproveReopen}
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
                    highlightKey={highlightKey}
                    onDirtyChange={onDirtyChange}
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
                      isLocked={isLocked}
                      canRescan={canEditSpeakers && !!meeting?.transcript_id && !isLocked}
                      onRescanEvidence={rescanEvidence}
                      onShowInTranscript={onShowInTranscript}
                      className="bg-[#F8F9FA]"
                      noMaxHeight
                    />
                  </div>
                )}
                {activeTab === "prep" && (
                  <PrepAgendaTab meetingId={meetingId} API={API} getAuthConfig={getAuthConfig} role={user?.role} navigate={navigate} />
                )}
              </div>
            </div>

            <EvidenceSidebar
              analysis={analysis}
              canReview={canReview}
              updateEvidence={updateEvidence}
              isLocked={isLocked}
              canRescan={canEditSpeakers && !!meeting?.transcript_id && !isLocked}
              onRescanEvidence={rescanEvidence}
              onShowInTranscript={(excerpt) => { setHighlightExcerpt(excerpt); setHighlightKey(k => k + 1); setActiveTab("transcript"); }}
              className="hidden lg:block lg:col-span-5 bg-[#F8F9FA] overflow-y-auto min-h-0"
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

        <ShareModal
          show={showShareModal}
          onClose={() => setShowShareModal(false)}
          meeting={meeting}
          onShared={(sharedWith) => setMeeting(m => ({ ...m, status: "shared", shared_with: sharedWith }))}
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
                  <div className="flex items-start gap-2.5 bg-red-50 border border-red-200 rounded-lg p-3 mb-3" data-testid="unreviewed-attendees-warning">
                    <AlertTriangle className="w-4 h-4 text-red-600 flex-shrink-0 mt-0.5" />
                    <p className="text-sm text-red-800">
                      <span className="font-medium">{unreviewed.length} {unreviewed.length === 1 ? "attendee has" : "attendees have"} not reviewed:</span>{" "}
                      {unreviewed.map(a => a.name).join(", ")}. Sign-off is blocked until all attendees have reviewed.
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
                    disabled={submitting || unreviewed.length > 0}
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


// ── Prep Agenda Tab (inline view for report page) ───────────────────────────
const SECTION_COLORS = {
  wellbeing:            "text-sky-600 bg-sky-50",
  working_well:         "text-emerald-600 bg-emerald-50",
  needs_attention:      "text-amber-600 bg-amber-50",
  learning_development: "text-purple-600 bg-purple-50",
  achievements:         "text-rose-600 bg-rose-50",
  aob:                  "text-gray-600 bg-gray-50",
};

const COVERAGE_CONFIG = {
  covered: { label: "Covered",  cls: "bg-emerald-100 text-emerald-700", dot: "bg-emerald-500" },
  partial: { label: "Partial",  cls: "bg-amber-100 text-amber-700",    dot: "bg-amber-400" },
  missed:  { label: "Missed",   cls: "bg-red-100 text-red-600",        dot: "bg-red-500" },
};

function PrepAgendaTab({ meetingId, API, getAuthConfig, role, navigate }) {
  const [prep, setPrep] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [carryingForward, setCarryingForward] = React.useState(false);

  React.useEffect(() => {
    axios.get(`${API}/prep/${meetingId}`, getAuthConfig())
      .then(r => setPrep(r.data))
      .catch(() => setPrep(null))
      .finally(() => setLoading(false));
  }, [meetingId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) return <div className="flex justify-center py-12"><div className="w-6 h-6 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" /></div>;

  if (!prep?.sections?.length) {
    return (
      <div className="text-center py-12 space-y-3">
        <div className="w-12 h-12 rounded-full bg-indigo-50 flex items-center justify-center mx-auto">
          <span className="text-2xl">✨</span>
        </div>
        <p className="text-sm text-gray-500">No prep agenda for this meeting yet.</p>
        {(role === "manager" || role === "admin") && (
          <button
            onClick={() => navigate(`/meetings/${meetingId}/prepare`)}
            className="inline-flex items-center gap-1.5 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 transition-colors"
          >
            Create prep agenda
          </button>
        )}
      </div>
    );
  }

  const coverage = prep.coverage_results || {};
  const hasCoverage = Object.keys(coverage).length > 0;
  const missedQuestions = [];

  if (hasCoverage) {
    prep.sections?.forEach(section => {
      section.questions?.forEach(q => {
        if (q.included !== false && coverage[q.id]?.status === "missed") {
          missedQuestions.push({ ...q, section_label: section.label });
        }
      });
    });
  }

  const handleCarryForward = async () => {
    if (!missedQuestions.length) return;
    setCarryingForward(true);
    try {
      // Convert each missed question to an action via the review endpoint
      await axios.post(`${API}/prep/${meetingId}/carry-forward-missed`, {}, getAuthConfig());
      toast.success(`${missedQuestions.length} missed question${missedQuestions.length > 1 ? "s" : ""} added as actions.`);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to carry forward");
    } finally { setCarryingForward(false); }
  };

  return (
    <div className="space-y-4">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {prep.focus_topic && (
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-indigo-50 border border-indigo-200">
              <span className="text-xs font-semibold text-indigo-700">Focus:</span>
              <span className="text-sm text-indigo-800">{prep.focus_topic}</span>
            </div>
          )}
          {hasCoverage && (
            <div className="flex items-center gap-2 text-xs">
              {["covered","partial","missed"].map(s => {
                const count = Object.values(coverage).filter(r => r.status === s).length;
                if (!count) return null;
                const cfg = COVERAGE_CONFIG[s];
                return <span key={s} className={`px-2 py-0.5 rounded-full font-medium ${cfg.cls}`}>{count} {cfg.label}</span>;
              })}
            </div>
          )}
        </div>
        {(role === "manager" || role === "admin") && (
          <button onClick={() => navigate(`/meetings/${meetingId}/prepare`)} className="text-xs text-indigo-600 hover:underline">
            Edit prep →
          </button>
        )}
      </div>

      {/* Missed questions carry-forward banner */}
      {hasCoverage && missedQuestions.length > 0 && (
        <div className="flex items-center gap-3 p-3 rounded-lg bg-amber-50 border border-amber-200">
          <span className="text-xs text-amber-800 flex-1">
            <strong>{missedQuestions.length} question{missedQuestions.length > 1 ? "s" : ""}</strong> weren't covered in this session.
          </span>
          <button
            onClick={handleCarryForward}
            disabled={carryingForward}
            className="text-xs px-3 py-1.5 bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-60 transition-colors"
            data-testid="carry-forward-btn"
          >
            {carryingForward ? "Adding…" : "Carry forward as actions"}
          </button>
        </div>
      )}

      {!prep.shared_with_attendees && role === "attendee" && (
        <p className="text-xs text-gray-400 italic">The prep agenda hasn't been shared with you yet.</p>
      )}

      {/* Sections */}
      {prep.sections.map(section => {
        const included = (section.questions || []).filter(q => q.included !== false);
        if (!included.length) return null;
        const colorCls = SECTION_COLORS[section.section_id] || "text-gray-600 bg-gray-50";
        return (
          <div key={section.section_id} className="space-y-2">
            <h3 className={`text-xs font-semibold uppercase tracking-wide px-2 py-1 rounded-md inline-block ${colorCls}`}>{section.label}</h3>
            <ul className="space-y-2 pl-1">
              {included.map(q => {
                const cov = coverage[q.id];
                const cfg = cov ? COVERAGE_CONFIG[cov.status] : null;
                return (
                  <li key={q.id} className="flex items-start gap-2.5">
                    {cfg && (
                      <span className={`mt-1.5 w-2 h-2 rounded-full flex-shrink-0 ${cfg.dot}`} title={cfg.label} />
                    )}
                    {!cfg && <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-gray-300 flex-shrink-0" />}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-gray-700 leading-relaxed">{q.text}</p>
                      {cov?.evidence && (
                        <p className="text-xs text-gray-400 italic mt-0.5">"{cov.evidence}"</p>
                      )}
                    </div>
                    {cfg && (
                      <span className={`flex-shrink-0 text-xs px-2 py-0.5 rounded-full font-medium ${cfg.cls}`}>{cfg.label}</span>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

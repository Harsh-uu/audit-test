import React, { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import {
  FileText, CheckCircle, ArrowLeft, AlertTriangle, Loader2, Shield, Send, MoreHorizontal, Info, Share2, RefreshCw,
} from "lucide-react";
import { toast } from "sonner";
import { EvidenceTab } from "@/components/report/EvidenceTab";
import { TranscriptTab } from "@/components/report/TranscriptTab";
import { CommentsTab } from "@/components/report/CommentsTab";
import { AuditTrailTab } from "@/components/report/AuditTrailTab";
import { EvidenceSidebar } from "@/components/report/EvidenceSidebar";
import { EmailModal } from "@/components/report/EmailModal";
import { ShareModal } from "@/components/report/ShareModal";
import { PostRecordingFlow } from "@/components/report/PostRecordingFlow";
import { RetryButton } from "@/components/report/RetryButton";
import { PrepAgendaTab } from "@/components/report/PrepAgendaTab";

// UK-English overrides for statuses whose US-spelled enum value would
// otherwise leak into the header pill via naive title-casing.
const STATUS_LABELS = {
  analyzing: "Analysing",
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
  const [newAction, setNewAction] = useState({ text: "", assigned_to: "", assigned_to_user_id: "", due_date: "" });
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
  const [showMoreMenu, setShowMoreMenu] = useState(false);
  const moreMenuRef = useRef(null);
  const rescanMenuRef = useRef(null);
  const rescanInitiated = useRef(false);
  const [rescanning, setRescanning] = useState(false);
  const [showRescanDialog, setShowRescanDialog] = useState(false);
  const [rescanPrompt, setRescanPrompt] = useState("");
  const [bulkAccepting, setBulkAccepting] = useState(false);
  const [warningDismissed, setWarningDismissed] = useState(
    () => !!localStorage.getItem(`tw_dismissed_${meetingId}`)
  );

  useEffect(() => {
    if (!showMoreMenu) return;
    const handler = (e) => { if (moreMenuRef.current && !moreMenuRef.current.contains(e.target)) setShowMoreMenu(false); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showMoreMenu]);

  useEffect(() => {
    if (!showRescanDialog) return;
    const handler = (e) => { if (rescanMenuRef.current && !rescanMenuRef.current.contains(e.target)) setShowRescanDialog(false); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showRescanDialog]);

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
    // Refetch every time the tab is switched to Audit Trail (not just once)
    // so edits made elsewhere in the report (speaker labels, evidence, PII
    // review) are reflected without the manager needing to hit Refresh.
    if (activeTab === "audit") fetchAuditTrail();
  }, [activeTab]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    document.getElementById("report-scroll-container")?.scrollTo(0, 0);
    document.getElementById("app-scroll-container")?.scrollTo(0, 0);
  }, [activeTab]);

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

  const bulkAcceptEvidence = async (confidence) => {
    setBulkAccepting(true);
    try {
      const { data } = await axios.post(
        `${API}/review/${meetingId}/evidence/bulk-action`,
        { confidence, status: "accepted" },
        getAuthConfig()
      );
      setMeeting(m => ({
        ...m,
        analysis: {
          ...m.analysis,
          cqc_mappings: data.cqc_mappings ?? m.analysis?.cqc_mappings,
          care_cert_mappings: data.care_cert_mappings ?? m.analysis?.care_cert_mappings,
          custom_mappings: data.custom_mappings ?? m.analysis?.custom_mappings,
        },
      }));
      if (data.updated_count > 0) {
        toast.success(`${data.updated_count} item${data.updated_count !== 1 ? "s" : ""} accepted`);
      } else {
        toast.info("No pending items in that category to accept");
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Bulk accept failed. Please try again.");
    } finally {
      setBulkAccepting(false);
    }
  };

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
    } catch (err) { setActionMessage(err.response?.data?.detail || "Failed to save actions"); }
  };

  const addAction = async () => {
    if (!newAction.text.trim()) return;
    const current = meeting?.analysis?.actions || [];
    const updated = [
      ...current,
      { id: `action_manual_${Date.now()}`, text: newAction.text.trim(), assigned_to: newAction.assigned_to.trim() || null, assigned_to_user_id: newAction.assigned_to_user_id || null, due_date: newAction.due_date.trim() || null },
    ];
    // Optimistic: show the new action immediately, persist in the background
    setMeeting(m => ({ ...m, analysis: { ...m.analysis, actions: updated } }));
    setNewAction({ text: "", assigned_to: "", assigned_to_user_id: "", due_date: "" });
    setAddingAction(false);
    await saveActions(updated);
  };

  const removeAction = async (idx) => {
    const current = meeting?.analysis?.actions || [];
    const updated = current.filter((_, i) => i !== idx);
    setMeeting(m => ({ ...m, analysis: { ...m.analysis, actions: updated } }));
    await saveActions(updated);
  };

  const toggleActionComplete = async (actionId, completed) => {
    const prevActions = meeting?.analysis?.actions || [];
    const nextActions = prevActions.map(a =>
      (a.id === actionId) ? { ...a, completed, completed_at: completed ? new Date().toISOString() : null } : a
    );
    // Optimistic: flip the checkbox immediately, sync to the server in the background
    setMeeting(m => ({ ...m, analysis: { ...m.analysis, actions: nextActions } }));
    try {
      await axios.patch(`${API}/review/${meetingId}/actions/${actionId}`, { completed }, getAuthConfig());
    } catch (err) {
      // Roll back on failure
      setMeeting(m => ({ ...m, analysis: { ...m.analysis, actions: prevActions } }));
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
      // Refetch so attendees[].reviewed is fresh — otherwise the sign-off
      // modal reads stale data and falsely blocks sign-off until a reload.
      await fetchMeeting();
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

  const handleRescanWithPrompt = async (customPrompt) => {
    setShowRescanDialog(false);
    setRescanning(true);
    try {
      await rescanEvidence(customPrompt);
    } finally {
      setRescanning(false);
      setRescanPrompt("");
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
        <div className="min-h-full flex items-center justify-center" data-testid="meeting-report-loading">
          <div className="w-10 h-10 border-[3px] border-[#1E3A8A] border-t-transparent rounded-full spin" />
        </div>
      </Layout>
    );
  }

  if (!meeting) return <Layout><div className="p-8 text-center text-gray-500">Meeting not found</div></Layout>;

  // ── Header-bar title (rendered centred inside Layout's org colour bar) ───
  const meetingHeaderCenter = (
    <div className="min-w-0" data-testid="meeting-header-title">
      <div className="text-white font-semibold text-[15px] leading-tight line-clamp-2 sm:line-clamp-1">{meeting.title}</div>
      <div className="text-white/70 text-[11px] mt-0.5 truncate">
        {new Date(meeting.date).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}
        {meeting.location ? ` · ${meeting.location}` : ""}
      </div>
    </div>
  );

  // ── Post-recording processing flow ────────────────────────────────────
  // Covers upload/transcribe/confidentiality-check/compliance-mapping as
  // ONE cohesive screen — the confidentiality check expands inline as soon
  // as the transcript is ready, while mapping keeps running in the
  // background, instead of jumping between separate progress-bar and
  // gate screens.
  const isProcessingStage = ["processing", "transcribing", "analyzing"].includes(meeting.status);
  const shouldShowPIIGate =
    !piiGateDone &&
    meeting.pii_review_status !== "reviewed" &&
    (user?.role === "manager" || user?.role === "admin") &&
    !!meeting.transcript &&
    !["recording", "processing", "transcribing", "processing_failed"].includes(meeting.status);
  const showPostRecordingFlow = meeting.status !== "processing_failed" && (isProcessingStage || shouldShowPIIGate);

  if (showPostRecordingFlow) {
    return (
      <Layout headerCenter={meetingHeaderCenter}>
        <PostRecordingFlow
          meeting={meeting}
          meetingId={meetingId}
          API={API}
          getAuthConfig={getAuthConfig}
          role={user?.role}
          onPiiComplete={() => {
            // Flip the gate immediately once the PII step reports success —
            // don't block the transition to the tabbed report on a network
            // round-trip. fetchMeeting() still runs to bring in the applied
            // redactions/audit entry, it just no longer gates the switch.
            setPiiGateDone(true);
            fetchMeeting();
          }}
        />
      </Layout>
    );
  }

  const analysis = meeting.analysis;

  const tabBtnCls = (t) => `flex-shrink-0 inline-flex items-center gap-1.5 text-sm font-medium py-3 border-b-2 transition-colors ${activeTab === t ? "border-[#1E3A8A] text-[#1E3A8A]" : "border-transparent text-gray-500 hover:text-gray-700"}`;

  // ── Single contextual primary action — changes as the meeting moves
  // through its lifecycle, so only one call-to-action button is ever shown.
  let primaryAction = null;
  if (canReview && !hasReviewed) {
    primaryAction = (
      <button onClick={markReviewed} disabled={submitting} className="flex items-center gap-2 bg-[#059669] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-emerald-700 transition-colors disabled:opacity-60" data-testid="mark-reviewed-btn">
        <CheckCircle className="w-4 h-4" />
        <span className="hidden sm:inline">Mark Reviewed</span>
      </button>
    );
  } else if (canSignOff && !isSignedOff && !isProcessing && analysis) {
    primaryAction = (
      <button
        onClick={() => setShowSignOffConfirm(true)}
        disabled={submitting || isInReview}
        title={isInReview ? "All attendees must mark the session as reviewed before sign-off can be triggered" : "Sign off this session"}
        className="flex items-center gap-2 bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
        data-testid="sign-off-btn"
      >
        <Shield className="w-4 h-4" />
        <span className="hidden sm:inline">Sign Off</span>
      </button>
    );
  } else if (canSignOff && isSignedOff) {
    primaryAction = (
      <button onClick={() => setShowEmailModal(true)} className="flex items-center gap-2 bg-emerald-600 text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-emerald-700 transition-colors" data-testid="send-report-btn">
        <Send className="w-4 h-4" />
        <span className="hidden sm:inline">Send to Attendees</span>
      </button>
    );
  }

  return (
    <Layout headerCenter={meetingHeaderCenter}>
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
        <div className="bg-white border-b border-gray-200 px-4 sm:px-6 py-3 flex items-center justify-between sticky top-0 z-20 gap-2">
          <div className="flex items-center gap-3 min-w-0 flex-wrap">
            <button onClick={() => navigate("/dashboard")} className="text-gray-500 hover:text-gray-700 flex-shrink-0" data-testid="back-to-dashboard-btn">
              <ArrowLeft className="w-4 h-4" />
            </button>
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-medium border text-xs flex-shrink-0 ${isSignedOff ? "bg-emerald-100 text-emerald-800 border-emerald-200" : canReview ? "bg-amber-100 text-amber-800 border-amber-200" : "bg-blue-100 text-blue-700 border-blue-200"}`} data-testid="meeting-status-pill">
              {STATUS_LABELS[meeting.status] || meeting.status.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase())}
            </span>
            {hasReviewed && canReview && (
              <span className="flex items-center gap-1.5 text-emerald-600 text-xs font-medium flex-shrink-0" data-testid="you-reviewed-this">
                <CheckCircle className="w-3.5 h-3.5" /> You reviewed this
              </span>
            )}
          </div>

          <div className="flex items-center gap-2 flex-shrink-0">
            {canEditSpeakers && !!meeting?.transcript_id && !isLocked && (
              <div className="relative" ref={rescanMenuRef}>
                <button
                  onClick={() => !rescanning && setShowRescanDialog(v => !v)}
                  disabled={rescanning}
                  data-testid="rescan-evidence-btn"
                  title="Re-scan compliance evidence — optionally with custom guidance"
                  className="flex items-center gap-1.5 text-sm px-3 py-2 rounded-md border border-gray-200 bg-white text-gray-600 hover:bg-blue-50 hover:border-blue-200 hover:text-blue-700 transition-colors disabled:opacity-60"
                >
                  {rescanning
                    ? <Loader2 className="w-4 h-4 animate-spin" />
                    : <RefreshCw className="w-4 h-4" />}
                  <span className="hidden sm:inline">{rescanning ? "Re-scanning…" : "Re-scan"}</span>
                </button>
                {showRescanDialog && !rescanning && (
                  <div
                    className="absolute right-0 top-full mt-1.5 w-80 border border-blue-200 rounded-lg bg-blue-50 p-3 shadow-lg z-30"
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
              </div>
            )}
            {primaryAction}
            {canSignOff && isSignedOff && (
              <div className="relative" ref={moreMenuRef}>
                <button
                  onClick={() => setShowMoreMenu(v => !v)}
                  className="w-9 h-9 flex items-center justify-center border border-gray-200 rounded-md text-gray-500 hover:bg-gray-50 transition-colors"
                  data-testid="more-actions-btn"
                  title="More actions"
                >
                  <MoreHorizontal className="w-4 h-4" />
                </button>
                {showMoreMenu && (
                  <div className="absolute right-0 top-full mt-1.5 w-64 bg-white rounded-lg shadow-lg border border-gray-200 z-30 overflow-hidden py-1.5" data-testid="more-actions-menu">
                    <label className="flex items-center gap-2 px-3.5 py-1.5 text-xs text-gray-500 cursor-pointer select-none">
                      <input type="checkbox" checked={includeTranscript} onChange={e => setIncludeTranscript(e.target.checked)} className="w-3.5 h-3.5 accent-[#1E3A8A]" data-testid="include-transcript-toggle" />
                      Include full transcript in PDF
                    </label>
                    <button onClick={() => { exportPdf(); setShowMoreMenu(false); }} disabled={exportingPdf} className="w-full flex items-center gap-2.5 px-3.5 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors disabled:opacity-60" data-testid="export-pdf-btn">
                      <FileText className="w-4 h-4 text-gray-400" />
                      {exportingPdf ? "Generating…" : "Export PDF"}
                    </button>
                    <button onClick={() => { exportTranscript(); setShowMoreMenu(false); }} disabled={exportingTranscript} className="w-full flex items-center gap-2.5 px-3.5 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors disabled:opacity-60" data-testid="export-transcript-btn">
                      <FileText className="w-4 h-4 text-gray-400" />
                      {exportingTranscript ? "Generating…" : "Export Transcript"}
                    </button>
                    <div className="border-t border-gray-100 my-1"></div>
                    <button onClick={() => { setShowMoreMenu(false); setShowShareModal(true); }} className="w-full flex items-center gap-2.5 px-3.5 py-2 text-sm text-indigo-700 hover:bg-indigo-50 transition-colors" data-testid="share-report-btn">
                      <Share2 className="w-4 h-4 text-indigo-400" />
                      {meeting?.shared_with?.length ? `Shared (${meeting.shared_with.length})` : "Share with team"}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Processing failed state */}
        {meeting.status === "processing_failed" && (
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
        {meeting.status !== "processing_failed" && !analysis && (
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

        {/* Content — single column, tabs only (no permanent sidebar) at every viewport width */}
        {meeting.status !== "processing_failed" && analysis && (
          <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
            <div className="sticky top-0 z-10 bg-white border-b border-gray-200 flex-shrink-0">
              <div className="max-w-5xl mx-auto px-6 flex items-center gap-6 overflow-x-auto scrollbar-hide">
                <button onClick={() => setActiveTab("evidence")} className={tabBtnCls("evidence")} data-testid="overview-tab">Overview</button>
                <button onClick={() => setActiveTab("transcript")} className={tabBtnCls("transcript")} data-testid="transcript-tab">Transcript</button>
                <button onClick={() => setActiveTab("compliance")} className={tabBtnCls("compliance")} data-testid="compliance-tab">
                  Compliance
                  {isRescanning && (
                    <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-indigo-100 text-indigo-700">
                      <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-pulse"></span>Processing
                    </span>
                  )}
                </button>
                <button onClick={() => setActiveTab("comments")} className={tabBtnCls("comments")} data-testid="comments-tab">
                  Comments
                  {meeting.comments?.length > 0 && (
                    <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-600">{meeting.comments.length}</span>
                  )}
                </button>
                <button onClick={() => setActiveTab("prep")} className={tabBtnCls("prep")} data-testid="prep-tab">Prep Agenda</button>
                <button onClick={() => setActiveTab("audit")} className={tabBtnCls("audit")} data-testid="audit-trail-tab">Audit Trail</button>
              </div>
            </div>

            <div id="report-scroll-container" className="flex-1 min-h-0 overflow-y-auto">
              <div className="max-w-5xl mx-auto p-6 w-full">
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
                {activeTab === "compliance" && (
                  <div className="-m-6">
                    <EvidenceSidebar
                      analysis={analysis}
                      canReview={canReview && (user?.role === "manager" || user?.role === "admin")}
                      updateEvidence={updateEvidence}
                      isLocked={isLocked}
                      onBulkAccept={bulkAcceptEvidence}
                      bulkAccepting={bulkAccepting}
                      onShowInTranscript={onShowInTranscript}
                      className="bg-[#F8F9FA]"
                      noMaxHeight
                    />
                  </div>
                )}
                {activeTab === "comments" && (
                  <CommentsTab
                    meeting={meeting}
                    canAddComment={canAddComment}
                    newComment={newComment}
                    setNewComment={setNewComment}
                    addComment={addComment}
                  />
                )}
                {activeTab === "prep" && (
                  <PrepAgendaTab meetingId={meetingId} API={API} getAuthConfig={getAuthConfig} role={user?.role} navigate={navigate} />
                )}
                {activeTab === "audit" && (
                  <AuditTrailTab
                    auditLoading={auditLoading}
                    auditTrail={auditTrail}
                    fetchAuditTrail={fetchAuditTrail}
                  />
                )}
              </div>
            </div>
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




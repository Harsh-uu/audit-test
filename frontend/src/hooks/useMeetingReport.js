import { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { invalidateCache } from "@/utils/apiCache";

/**
 * All state, effects and server-communicating handlers for the Meeting Report
 * page. Extracted out of MeetingReport.js so that file stays focused on
 * rendering — this hook owns the data/behaviour, the page owns the JSX.
 */
export function useMeetingReport() {
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
  const [bulkAcceptingTier, setBulkAcceptingTier] = useState(null);
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
      // Team Themes/Insights caches the evidence matrix for 60s — bust it so
      // an accept/reject/flag here shows up immediately rather than looking
      // like it "didn't happen" for up to a minute.
      invalidateCache("/admin/team-insights");
    } catch (err) {
      setMeeting(prev); // revert on failure
      console.error("Evidence update failed", err.message);
      toast.error("Failed to update evidence — changes reverted.");
    }
  }, [meetingId, meeting]); // eslint-disable-line react-hooks/exhaustive-deps

  const BULK_CONFIDENCE_ALIASES = {
    likely_evidence: ["likely_evidence"],
    possible_evidence: ["possible_evidence", "needs_review", "not_enough_evidence"],
  };

  const bulkAcceptEvidence = async (confidence) => {
    const prev = meeting;
    const aliases = BULK_CONFIDENCE_ALIASES[confidence] || [confidence];
    const isPending = (arr) => (arr || []).filter(
      e => aliases.includes(e.confidence) && (e.status || "pending") === "pending"
    ).length;
    const pendingCount =
      isPending(meeting.analysis?.cqc_mappings) +
      isPending(meeting.analysis?.care_cert_mappings) +
      isPending(meeting.analysis?.custom_mappings);

    if (pendingCount === 0) {
      toast.info("No pending items in that category to accept");
      return;
    }

    // Optimistic: flip every matching pending item to accepted immediately,
    // reconcile with the server's authoritative response in the background.
    const patchMappings = arr => (arr || []).map(e =>
      aliases.includes(e.confidence) && (e.status || "pending") === "pending"
        ? { ...e, status: "accepted" }
        : e
    );
    setMeeting(m => ({
      ...m,
      analysis: {
        ...m.analysis,
        cqc_mappings: patchMappings(m.analysis?.cqc_mappings),
        care_cert_mappings: patchMappings(m.analysis?.care_cert_mappings),
        custom_mappings: patchMappings(m.analysis?.custom_mappings),
      },
    }));
    toast.success(`${pendingCount} item${pendingCount !== 1 ? "s" : ""} accepted`);
    invalidateCache("/admin/team-insights");

    setBulkAcceptingTier(confidence);
    try {
      const { data } = await axios.post(
        `${API}/review/${meetingId}/evidence/bulk-action`,
        { confidence, status: "accepted" },
        getAuthConfig()
      );
      // Reconcile with the server's version (e.g. accepted_by/accepted_at fields)
      setMeeting(m => ({
        ...m,
        analysis: {
          ...m.analysis,
          cqc_mappings: data.cqc_mappings ?? m.analysis?.cqc_mappings,
          care_cert_mappings: data.care_cert_mappings ?? m.analysis?.care_cert_mappings,
          custom_mappings: data.custom_mappings ?? m.analysis?.custom_mappings,
        },
      }));
    } catch (err) {
      setMeeting(prev); // revert on failure
      toast.error(err?.response?.data?.detail || "Bulk accept failed. Please try again.");
    } finally {
      setBulkAcceptingTier(null);
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

  const editAction = async (idx, fields) => {
    const current = meeting?.analysis?.actions || [];
    const updated = current.map((a, i) => i === idx ? { ...a, ...fields } : a);
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

  return {
    meetingId, navigate, user, API, getAuthConfig,
    meeting, setMeeting, loading,
    activeTab, setActiveTab,
    editingSummary, setEditingSummary, summaryText, setSummaryText,
    newComment, setNewComment,
    actionMessage,
    highlightExcerpt, highlightKey,
    submitting,
    addingAction, setAddingAction, newAction, setNewAction,
    auditTrail, auditLoading, fetchAuditTrail,
    exportingPdf, exportingTranscript, includeTranscript, setIncludeTranscript,
    sendingEmail, showEmailModal, setShowEmailModal, showShareModal, setShowShareModal,
    emailMessage, setEmailMessage,
    showSignOffConfirm, setShowSignOffConfirm,
    speakersDirty,
    piiGateDone, setPiiGateDone,
    showMoreMenu, setShowMoreMenu, moreMenuRef,
    rescanMenuRef, rescanning, showRescanDialog, setShowRescanDialog, rescanPrompt, setRescanPrompt,
    bulkAcceptingTier,
    warningDismissed, setWarningDismissed,
    isProcessing, isRescanning, isInReview, isReviewed, isSignedOff, isLocked,
    canReview, canSignOff, canEditSpeakers, canAddComment, canAnonymise,
    hasReviewed, allReviewed,
    fetchMeeting,
    saveSummary, updateEvidence, bulkAcceptEvidence,
    onShowInTranscript, onDirtyChange, onAnalysisChange,
    addAction, removeAction, toggleActionComplete, editAction,
    markReviewed, signOff, addComment,
    handleAnonymise, handleFindReplace,
    handleRescanWithPrompt, handleReopenRequest, handleApproveReopen,
    exportPdf, exportTranscript, sendReport,
  };
}

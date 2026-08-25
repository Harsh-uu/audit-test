import React from "react";
import Layout from "@/components/Layout";
import {
  CheckCircle, ArrowLeft, AlertTriangle, Loader2, Shield, Send,
} from "lucide-react";
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
import { SignOffConfirmModal } from "@/components/report/SignOffConfirmModal";
import { RescanDialog } from "@/components/report/RescanDialog";
import { MoreActionsMenu } from "@/components/report/MoreActionsMenu";
import { useMeetingReport } from "@/hooks/useMeetingReport";

// UK-English overrides for statuses whose US-spelled enum value would
// otherwise leak into the header pill via naive title-casing.
const STATUS_LABELS = {
  analyzing: "Analysing",
};

export default function MeetingReport() {
  const {
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
    piiGateDone, setPiiGateDone,
    showMoreMenu, setShowMoreMenu, moreMenuRef,
    rescanMenuRef, rescanning, showRescanDialog, setShowRescanDialog, rescanPrompt, setRescanPrompt,
    bulkAccepting,
    warningDismissed, setWarningDismissed,
    isProcessing, isRescanning, isInReview, isSignedOff, isLocked,
    canReview, canSignOff, canEditSpeakers, canAddComment, canAnonymise,
    hasReviewed,
    fetchMeeting,
    saveSummary, updateEvidence, bulkAcceptEvidence,
    onShowInTranscript, onDirtyChange, onAnalysisChange,
    addAction, removeAction, toggleActionComplete,
    editAction,
    markReviewed, signOff, addComment,
    handleAnonymise, handleFindReplace,
    handleRescanWithPrompt, handleReopenRequest, handleApproveReopen,
    exportPdf, exportTranscript, sendReport,
  } = useMeetingReport();

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
              <RescanDialog
                menuRef={rescanMenuRef}
                rescanning={rescanning}
                show={showRescanDialog}
                onToggle={() => setShowRescanDialog(v => !v)}
                rescanPrompt={rescanPrompt}
                setRescanPrompt={setRescanPrompt}
                onRescanWithGuidance={handleRescanWithPrompt}
                onRescanWithoutGuidance={() => handleRescanWithPrompt("")}
                onCancel={() => { setShowRescanDialog(false); setRescanPrompt(""); }}
              />
            )}
            {primaryAction}
            {canSignOff && isSignedOff && (
              <MoreActionsMenu
                menuRef={moreMenuRef}
                show={showMoreMenu}
                onToggle={() => setShowMoreMenu(v => !v)}
                includeTranscript={includeTranscript}
                setIncludeTranscript={setIncludeTranscript}
                exportingPdf={exportingPdf}
                onExportPdf={() => { exportPdf(); setShowMoreMenu(false); }}
                exportingTranscript={exportingTranscript}
                onExportTranscript={() => { exportTranscript(); setShowMoreMenu(false); }}
                meeting={meeting}
                onShare={() => { setShowMoreMenu(false); setShowShareModal(true); }}
              />
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
                    editAction={editAction}
                    actionMessage={actionMessage}
                    onSummaryRegenerated={newSummary => {
                      onAnalysisChange({ ...analysis, summary: newSummary });
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
        <SignOffConfirmModal
          show={showSignOffConfirm}
          meeting={meeting}
          submitting={submitting}
          onCancel={() => setShowSignOffConfirm(false)}
          onConfirm={signOff}
        />
      </div>
    </Layout>
  );
}

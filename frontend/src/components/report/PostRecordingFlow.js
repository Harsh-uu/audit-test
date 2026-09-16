import React, { useState, useEffect, useRef } from "react";
import axios from "axios";
import { CheckCircle2, Loader2, Shield, ChevronRight, AlertTriangle, Sparkles, Circle } from "lucide-react";

// ── Post-Recording Processing Flow ──────────────────────────────────────
// A single cohesive "Inline Action Stream": Upload + Transcribe collapse
// into compact done-rows as they finish, the Confidentiality Check expands
// inline the moment the transcript is ready (no separate full-screen swap),
// and Mapping Compliance Evidence stays pinned at the bottom with a
// shimmering "still working" background while it runs alongside the
// confidentiality review, instead of blocking behind it.

const TYPE_LABELS = {
  third_party_name: "Third-party Name",
  sensitive_personal_detail: "Personal Detail",
  contact_detail: "Contact Info",
  address: "Address",
  unknown: "Other",
};

const TYPE_COLORS = {
  third_party_name: "bg-red-100 text-red-700 border-red-200",
  sensitive_personal_detail: "bg-orange-100 text-orange-700 border-orange-200",
  contact_detail: "bg-amber-100 text-amber-700 border-amber-200",
  address: "bg-yellow-100 text-yellow-700 border-yellow-200",
  unknown: "bg-gray-100 text-gray-600 border-gray-200",
};

const FULL_ORDER = ["processing", "transcribing", "analyzing", "in_review", "reviewed", "signed_off", "shared"];

function StepShell({ testId, state, icon, title, subtitle, right, children }) {
  // state: "done" | "active" | "waiting"
  const border = state === "done" ? "border-emerald-200" : state === "active" ? "border-[#1E3A8A]" : "border-gray-100";
  const bg = state === "done" ? "bg-emerald-50/50" : state === "active" ? "bg-blue-50/50" : "bg-gray-50/60";
  return (
    <div
      data-testid={testId}
      data-step-state={state}
      className={`rounded-xl border ${border} ${bg} transition-all duration-500 overflow-hidden`}
    >
      <div className={`flex items-start gap-3 px-4 sm:px-5 ${state === "active" && children ? "pt-4" : "py-3.5"} ${state === "active" && children ? "" : ""}`}>
        <div
          className={`w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center mt-0.5 ${
            state === "done" ? "bg-emerald-500 text-white" : state === "active" ? "bg-[#1E3A8A] text-white" : "bg-gray-300 text-gray-500"
          }`}
        >
          {state === "done" ? <CheckCircle2 className="w-4 h-4" /> : icon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span className={`text-sm font-semibold font-display truncate ${state === "done" ? "text-emerald-700" : state === "active" ? "text-[#1E3A8A]" : "text-gray-500"}`}>
              {title}
            </span>
            <span className={`text-xs flex-shrink-0 whitespace-nowrap ${state === "done" ? "text-emerald-600" : state === "active" ? "text-[#1E3A8A]" : "text-gray-500"}`}>
              {right}
            </span>
          </div>
          {subtitle && state !== "done" && <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>}
        </div>
      </div>
      {children && state === "active" && <div className="px-4 sm:px-5 pb-4 sm:pb-5">{children}</div>}
    </div>
  );
}

export function PostRecordingFlow({ meeting, meetingId, API, getAuthConfig, role, onPiiComplete }) {
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState("");
  const [flags, setFlags] = useState([]);
  const [selected, setSelected] = useState({});
  const [replacements, setReplacements] = useState({});
  const [saving, setSaving] = useState(false);
  const [localPiiDone, setLocalPiiDone] = useState(false);
  const scanStartedRef = useRef(false);

  const idx = FULL_ORDER.indexOf(meeting.status);
  const currentIdx = idx === -1 ? 99 : idx; // unknown/later status treated as fully progressed
  const step1Done = currentIdx > 0;
  const step1Active = currentIdx === 0;
  const step2Done = currentIdx > 1; // transcript ready
  const step2Active = currentIdx === 1;
  const step4Done = currentIdx > 2; // compliance mapping finished
  const step4Active = currentIdx === 2;

  const isManagerRole = role === "manager" || role === "admin";
  const piiAlreadyReviewed = meeting.pii_review_status === "reviewed";
  const step3Reviewed = step2Done && (piiAlreadyReviewed || localPiiDone);
  const step3Ready = step2Done;
  const step3Active = step3Ready && isManagerRole && !step3Reviewed;

  useEffect(() => {
    if (!step3Active || scanStartedRef.current) return;
    scanStartedRef.current = true;
    setScanning(true);
    axios.post(`${API}/review/${meetingId}/scan-pii`, {}, getAuthConfig())
      .then(({ data }) => {
        const found = data.flags || [];
        setFlags(found);
        const sel = {}; const reps = {};
        found.forEach(f => { sel[f.id] = true; reps[f.id] = f.replacement || "[Redacted]"; });
        setSelected(sel);
        setReplacements(reps);
      })
      .catch(() => setScanError("Scan could not complete — you can still proceed."))
      .finally(() => setScanning(false));
  }, [step3Active]); // eslint-disable-line react-hooks/exhaustive-deps

  const activeCount = flags.filter(f => selected[f.id]).length;

  const finishPiiReview = async (redactions, skipped) => {
    setSaving(true);
    setScanError("");
    try {
      await axios.post(`${API}/review/${meetingId}/complete-pii-review`, { redactions, skipped }, getAuthConfig());
      setLocalPiiDone(true);
      setSaving(false);
      onPiiComplete();
    } catch (e) {
      setScanError(e.response?.data?.detail || "Failed to save. Please try again.");
      setSaving(false);
    }
  };

  const handleApply = () => {
    const redactions = flags.filter(f => selected[f.id]).map(f => ({
      id: f.id, original: f.original, aliases: f.aliases || [], replacement: replacements[f.id] || "[Redacted]", type: f.type,
    }));
    finishPiiReview(redactions, false);
  };

  const handleSkip = () => finishPiiReview([], true);

  const doneCount = [step1Done, step2Done, step3Reviewed || !isManagerRole, step4Done].filter(Boolean).length;
  const headerTitle = step3Active ? "Confidentiality check required" : "Processing your recording";

  return (
    <div className="min-h-full bg-[#F8F9FA] flex flex-col items-center pt-8 pb-16 px-4" data-testid="processing-indicator">
      <div className="w-full max-w-2xl">
        <div className="text-center mb-6">
          <div className="w-12 h-12 border-[3px] border-[#1E3A8A] border-t-transparent rounded-full spin mx-auto mb-4" />
          <h2 className="text-xl font-bold text-gray-900 font-display" data-testid="prf-title">{headerTitle}</h2>
          <p className="text-sm text-gray-500 mt-1">Do not close or refresh this page whilst processing the meeting</p>
        </div>

        <div className="h-1.5 w-full bg-gray-200 rounded-full overflow-hidden mb-6">
          <div
            style={{ width: `${(doneCount / 4) * 100}%` }}
            className="h-full bg-[#1E3A8A] rounded-full transition-all duration-700"
            data-testid="prf-overall-progress"
          />
        </div>

        <div className="space-y-3">
          {/* Step 1 — Upload */}
          <StepShell
            testId="prf-step-1"
            state={step1Done ? "done" : step1Active ? "active" : "waiting"}
            icon={<span className="text-xs font-bold">1</span>}
            title="Processing Audio"
            subtitle="Audio is compressed to 16 kHz mono MP3 for optimal transcription"
            right={step1Done ? "Complete" : step1Active ? "~10–30 seconds" : "Waiting"}
          >
            <div className="h-1.5 w-full bg-gray-200 rounded-full overflow-hidden relative">
              <div className="absolute inset-y-0 left-0 w-1/3 bg-[#1E3A8A] rounded-full bar-indeterminate" />
            </div>
          </StepShell>

          {/* Step 2 — Transcribe */}
          <StepShell
            testId="prf-step-2"
            state={step2Done ? "done" : step2Active ? "active" : "waiting"}
            icon={<span className="text-xs font-bold">2</span>}
            title="Transcribing Recording"
            subtitle="Converting the audio into a speaker-labelled transcript"
            right={step2Done ? "Complete" : step2Active ? "~1–5 minutes" : "Waiting"}
          >
            <div className="h-1.5 w-full bg-gray-200 rounded-full overflow-hidden relative">
              <div className="absolute inset-y-0 left-0 w-1/3 bg-[#1E3A8A] rounded-full bar-indeterminate" />
            </div>
          </StepShell>

          {/* Step 3 — Confidentiality Check (the merged, expanding step) */}
          <StepShell
            testId="prf-step-3"
            state={step3Reviewed ? "done" : step3Active ? "active" : "waiting"}
            icon={<Shield className="w-4 h-4" />}
            title="Confidentiality Check"
            subtitle={
              isManagerRole
                ? "Review for references to third parties before this meeting is visible to reviewers"
                : "A manager reviews confidentiality before this meeting is fully visible"
            }
            right={
              step3Reviewed ? "Complete"
              : !step3Ready ? "Waiting"
              : isManagerRole ? "Action required"
              : "Pending manager review"
            }
          >
            {!isManagerRole ? null : (
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                {scanning ? (
                  <div className="flex flex-col items-center gap-2.5 py-10 text-center px-6">
                    <Loader2 className="w-6 h-6 text-[#1E3A8A] animate-spin" />
                    <p className="text-sm font-medium text-gray-700">Scanning transcript…</p>
                    <p className="text-xs text-gray-400">Checking for names, contact details and sensitive references</p>
                  </div>
                ) : flags.length === 0 ? (
                  <div className="flex flex-col items-center gap-2.5 py-10 text-center px-6">
                    <div className="w-10 h-10 rounded-full bg-emerald-100 flex items-center justify-center">
                      <CheckCircle2 className="w-5 h-5 text-emerald-600" />
                    </div>
                    <p className="text-sm font-semibold text-gray-900">No issues found</p>
                    <p className="text-xs text-gray-400 max-w-xs">{scanError || "No obvious third-party references were detected in this transcript."}</p>
                  </div>
                ) : (
                  <div className="divide-y divide-gray-100">
                    <div className="px-4 py-3 flex items-center justify-between">
                      <p className="text-sm font-semibold text-gray-900">{flags.length} potential issue{flags.length !== 1 ? "s" : ""} found</p>
                      <p className="text-xs text-gray-400">Check items to apply redactions</p>
                    </div>
                    {flags.map(flag => {
                      const isOn = !!selected[flag.id];
                      return (
                        <div key={flag.id} className={`px-4 py-3.5 transition-colors ${isOn ? "bg-white" : "bg-gray-50 opacity-50"}`} data-testid={`pii-flag-${flag.id}`}>
                          <div className="flex items-start gap-3">
                            <input
                              type="checkbox"
                              checked={isOn}
                              onChange={e => setSelected(s => ({ ...s, [flag.id]: e.target.checked }))}
                              className="mt-1 w-4 h-4 rounded accent-[#1E3A8A] cursor-pointer flex-shrink-0"
                              data-testid={`pii-flag-checkbox-${flag.id}`}
                            />
                            <div className="flex-1 min-w-0 space-y-1.5">
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className={`text-xs font-medium px-2 py-0.5 rounded-full border ${TYPE_COLORS[flag.type] || TYPE_COLORS.unknown}`}>
                                  {TYPE_LABELS[flag.type] || flag.type}
                                </span>
                                {flag.source === "regex" && (
                                  <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">Pattern match</span>
                                )}
                              </div>
                              <div className="flex items-center gap-2 flex-wrap">
                                <code className="text-sm bg-red-50 text-red-700 px-2 py-0.5 rounded border border-red-100 font-mono break-all">{flag.original}</code>
                                <ChevronRight className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                                <input
                                  type="text"
                                  value={replacements[flag.id] || ""}
                                  onChange={e => setReplacements(r => ({ ...r, [flag.id]: e.target.value }))}
                                  disabled={!isOn}
                                  placeholder="[Redacted]"
                                  className="text-sm bg-emerald-50 text-emerald-700 px-2 py-0.5 rounded border border-emerald-200 font-mono w-44 focus:outline-none focus:ring-1 focus:ring-emerald-300 disabled:cursor-not-allowed"
                                  data-testid={`pii-replacement-${flag.id}`}
                                />
                              </div>
                              {flag.reason && <p className="text-xs text-gray-400">{flag.reason}</p>}
                              {flag.aliases && flag.aliases.length > 0 && (
                                <p className="text-xs text-gray-400" data-testid={`pii-aliases-${flag.id}`}>
                                  Also matches: {flag.aliases.join(", ")}
                                </p>
                              )}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}

                {scanError && !scanning && flags.length > 0 && (
                  <div className="px-4 pb-3">
                    <div className="flex items-center gap-2 text-xs text-red-600 bg-red-50 p-2 rounded border border-red-100">
                      <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />{scanError}
                    </div>
                  </div>
                )}

                {!scanning && (
                  <div className="flex flex-col sm:flex-row gap-2.5 p-4 pt-3.5">
                    <button
                      onClick={handleApply}
                      disabled={saving}
                      className="flex-1 flex items-center justify-center gap-2 bg-[#1E3A8A] text-white py-2.5 px-5 rounded-lg text-sm font-semibold hover:bg-[#1e40af] disabled:opacity-60 transition-colors"
                      data-testid="pii-apply-btn"
                    >
                      {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Shield className="w-4 h-4" />}
                      {activeCount > 0 ? `Apply ${activeCount} redaction${activeCount !== 1 ? "s" : ""} & Continue` : "Continue to Review"}
                    </button>
                    <button
                      onClick={handleSkip}
                      disabled={saving}
                      className="sm:w-auto px-5 py-2.5 border border-gray-300 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-60 transition-colors whitespace-nowrap"
                      data-testid="pii-skip-btn"
                    >
                      Skip — no changes needed
                    </button>
                  </div>
                )}
                {!scanning && (
                  <p className="text-center text-xs text-gray-400 pb-3.5">Your decision is recorded in the meeting audit trail with date and time.</p>
                )}
              </div>
            )}
          </StepShell>

          {/* Step 4 — Mapping Compliance Evidence, pinned, shimmers while it runs in the background */}
          <StepShell
            testId="prf-step-4"
            state={step4Done ? "done" : step4Active ? "active" : "waiting"}
            icon={<Sparkles className="w-4 h-4" />}
            title="Mapping Compliance Evidence"
            subtitle="AI reviews the transcript and maps discussion points to regulatory standards"
            right={step4Done ? "Complete" : step4Active ? "~30–90 seconds" : "Waiting"}
          >
            <div className="rounded-lg shimmer-bg border border-blue-100 px-3.5 py-2.5 flex items-center gap-2">
              <Circle className="w-2 h-2 fill-[#1E3A8A] text-[#1E3A8A] animate-pulse flex-shrink-0" />
              <p className="text-xs text-[#1E3A8A]">
                {step3Active
                  ? "Continues in the background — you can complete the confidentiality check above while this finishes."
                  : "Running in the background — the full report will be ready shortly."}
              </p>
            </div>
          </StepShell>
        </div>
      </div>
    </div>
  );
}

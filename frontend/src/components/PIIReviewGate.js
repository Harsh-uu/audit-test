import React, { useState, useEffect } from "react";
import axios from "axios";
import { Shield, Loader2, CheckCircle, ChevronRight, AlertTriangle } from "lucide-react";

const TYPE_LABELS = {
  third_party_name:       "Third-party Name",
  sensitive_personal_detail: "Personal Detail",
  contact_detail:         "Contact Info",
  address:                "Address",
  unknown:                "Other",
};

const TYPE_COLORS = {
  third_party_name:          "bg-red-100 text-red-700 border-red-200",
  sensitive_personal_detail: "bg-orange-100 text-orange-700 border-orange-200",
  contact_detail:            "bg-amber-100 text-amber-700 border-amber-200",
  address:                   "bg-yellow-100 text-yellow-700 border-yellow-200",
  unknown:                   "bg-gray-100 text-gray-600 border-gray-200",
};

export function PIIReviewGate({ meetingId, onComplete, API, getAuthConfig }) {
  const [scanning, setScanning]         = useState(true);
  const [scanError, setScanError]       = useState("");
  const [flags, setFlags]               = useState([]);
  const [selected, setSelected]         = useState({});      // { id: bool }
  const [replacements, setReplacements] = useState({});      // { id: string }
  const [saving, setSaving]             = useState(false);

  useEffect(() => {
    const run = async () => {
      try {
        const { data } = await axios.post(
          `${API}/review/${meetingId}/scan-pii`,
          {},
          getAuthConfig()
        );
        const found = data.flags || [];
        setFlags(found);
        const sel = {};
        const reps = {};
        found.forEach(f => {
          sel[f.id]  = true;
          reps[f.id] = f.replacement || "[Redacted]";
        });
        setSelected(sel);
        setReplacements(reps);
      } catch {
        setScanError("Scan could not complete — you can still proceed.");
      } finally {
        setScanning(false);
      }
    };
    run();
  }, [meetingId]); // eslint-disable-line

  const activeCount = flags.filter(f => selected[f.id]).length;

  const handleApply = async () => {
    setSaving(true);
    setScanError("");
    try {
      const redactions = flags
        .filter(f => selected[f.id])
        .map(f => ({
          id:          f.id,
          original:    f.original,
          replacement: replacements[f.id] || "[Redacted]",
          type:        f.type,
        }));
      await axios.post(
        `${API}/review/${meetingId}/complete-pii-review`,
        { redactions, skipped: false },
        getAuthConfig()
      );
      onComplete();
    } catch (e) {
      setScanError(e.response?.data?.detail || "Failed to save. Please try again.");
      setSaving(false);
    }
  };

  const handleSkip = async () => {
    setSaving(true);
    setScanError("");
    try {
      await axios.post(
        `${API}/review/${meetingId}/complete-pii-review`,
        { redactions: [], skipped: true },
        getAuthConfig()
      );
      onComplete();
    } catch (e) {
      setScanError(e.response?.data?.detail || "Failed to save. Please try again.");
      setSaving(false);
    }
  };

  return (
    <div className="min-h-full bg-[#F8F9FA] flex flex-col">
      {/* Gate header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-2xl mx-auto flex items-center gap-3">
          <div className="w-9 h-9 rounded-full bg-amber-100 flex items-center justify-center flex-shrink-0">
            <Shield className="w-5 h-5 text-amber-600" />
          </div>
          <div>
            <h1 className="text-base font-semibold text-gray-900 font-display">
              Confidentiality Check
            </h1>
            <p className="text-xs text-gray-500">
              Required before this meeting enters review
            </p>
          </div>
        </div>
      </div>

      <div className="flex-1 flex items-start justify-center pt-8 pb-12 px-4">
        <div className="w-full max-w-2xl space-y-5">

          {/* Explanation banner */}
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-4">
            <p className="text-sm text-amber-800 leading-relaxed">
              This transcript may contain references to{" "}
              <strong>third parties</strong> — service users, residents, family
              members, or colleagues not present in the meeting. Please review any
              flagged items and decide whether to replace them before the meeting
              is made available to reviewers.
            </p>
            <p className="text-xs text-amber-600 mt-1.5">
              The original transcript is only visible to meeting participants.
              All other reviewers will see the redacted version.
            </p>
          </div>

          {/* Scan results card */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">

            {scanning ? (
              <div className="flex flex-col items-center gap-3 py-14 text-center px-6">
                <Loader2 className="w-8 h-8 text-[#1E3A8A] animate-spin" />
                <p className="text-sm font-medium text-gray-700">
                  Scanning transcript…
                </p>
                <p className="text-xs text-gray-400">
                  Checking for names, contact details and sensitive references
                </p>
              </div>
            ) : flags.length === 0 ? (
              <div className="flex flex-col items-center gap-3 py-14 text-center px-6">
                <div className="w-12 h-12 rounded-full bg-emerald-100 flex items-center justify-center">
                  <CheckCircle className="w-6 h-6 text-emerald-600" />
                </div>
                <p className="text-sm font-semibold text-gray-900">No issues found</p>
                <p className="text-xs text-gray-400 max-w-xs">
                  {scanError || "No obvious third-party references were detected in this transcript."}
                </p>
              </div>
            ) : (
              <>
                {/* Results header */}
                <div className="px-5 py-3.5 border-b border-gray-100 flex items-center justify-between">
                  <p className="text-sm font-semibold text-gray-900">
                    {flags.length} potential issue{flags.length !== 1 ? "s" : ""} found
                  </p>
                  <p className="text-xs text-gray-400">
                    Check items to apply redactions
                  </p>
                </div>

                {/* Flag list */}
                <div className="divide-y divide-gray-100">
                  {flags.map(flag => {
                    const isOn = !!selected[flag.id];
                    return (
                      <div
                        key={flag.id}
                        className={`px-5 py-4 transition-colors ${isOn ? "bg-white" : "bg-gray-50 opacity-50"}`}
                        data-testid={`pii-flag-${flag.id}`}
                      >
                        <div className="flex items-start gap-3">
                          <input
                            type="checkbox"
                            checked={isOn}
                            onChange={e =>
                              setSelected(s => ({ ...s, [flag.id]: e.target.checked }))
                            }
                            className="mt-1 w-4 h-4 rounded accent-[#1E3A8A] cursor-pointer flex-shrink-0"
                            data-testid={`pii-flag-checkbox-${flag.id}`}
                          />
                          <div className="flex-1 min-w-0 space-y-2">
                            {/* Type badge + source */}
                            <div className="flex items-center gap-2 flex-wrap">
                              <span
                                className={`text-xs font-medium px-2 py-0.5 rounded-full border ${
                                  TYPE_COLORS[flag.type] || TYPE_COLORS.unknown
                                }`}
                              >
                                {TYPE_LABELS[flag.type] || flag.type}
                              </span>
                              {flag.source === "regex" && (
                                <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">
                                  Pattern match
                                </span>
                              )}
                            </div>
                            {/* Original → Replacement row */}
                            <div className="flex items-center gap-2 flex-wrap">
                              <code className="text-sm bg-red-50 text-red-700 px-2 py-0.5 rounded border border-red-100 font-mono break-all">
                                {flag.original}
                              </code>
                              <ChevronRight className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                              <input
                                type="text"
                                value={replacements[flag.id] || ""}
                                onChange={e =>
                                  setReplacements(r => ({ ...r, [flag.id]: e.target.value }))
                                }
                                disabled={!isOn}
                                placeholder="[Redacted]"
                                className="text-sm bg-emerald-50 text-emerald-700 px-2 py-0.5 rounded border border-emerald-200 font-mono w-44 focus:outline-none focus:ring-1 focus:ring-emerald-300 disabled:cursor-not-allowed"
                                data-testid={`pii-replacement-${flag.id}`}
                              />
                            </div>
                            {flag.reason && (
                              <p className="text-xs text-gray-400">{flag.reason}</p>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            )}

            {/* Inline error */}
            {scanError && !scanning && flags.length > 0 && (
              <div className="px-5 pb-4">
                <div className="flex items-center gap-2 text-xs text-red-600 bg-red-50 p-2 rounded border border-red-100">
                  <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
                  {scanError}
                </div>
              </div>
            )}
          </div>

          {/* Error when no flags */}
          {scanError && !scanning && flags.length === 0 && (
            <div className="flex items-center gap-2 text-xs text-amber-700 bg-amber-50 p-3 rounded-lg border border-amber-200">
              <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
              {scanError}
            </div>
          )}

          {/* Action buttons */}
          {!scanning && (
            <div className="flex flex-col sm:flex-row gap-3">
              <button
                onClick={handleApply}
                disabled={saving}
                className="flex-1 flex items-center justify-center gap-2 bg-[#1E3A8A] text-white py-2.5 px-5 rounded-lg text-sm font-semibold hover:bg-[#1e40af] disabled:opacity-60 transition-colors"
                data-testid="pii-apply-btn"
              >
                {saving ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Shield className="w-4 h-4" />
                )}
                {activeCount > 0
                  ? `Apply ${activeCount} redaction${activeCount !== 1 ? "s" : ""} & Continue`
                  : "Continue to Review"}
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

          {/* Audit note */}
          {!scanning && (
            <p className="text-center text-xs text-gray-400">
              Your decision is recorded in the meeting audit trail with date and time.
            </p>
          )}

        </div>
      </div>
    </div>
  );
}

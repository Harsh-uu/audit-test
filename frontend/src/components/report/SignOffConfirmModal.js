import React from "react";
import { Shield, AlertTriangle } from "lucide-react";

export function SignOffConfirmModal({ show, meeting, submitting, onCancel, onConfirm }) {
  if (!show) return null;
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
            onClick={onCancel}
            className="px-4 py-2 text-sm font-medium text-gray-700 border border-gray-300 rounded-md hover:bg-gray-50 transition-colors"
            data-testid="signoff-cancel-btn"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
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
}

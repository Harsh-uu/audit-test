import React from "react";
import { X, Send, UserCircle } from "lucide-react";

export function EmailModal({ show, onClose, meeting, sendingEmail, emailMessage, setEmailMessage, sendReport }) {
  if (!show) return null;

  const attendeeEmails = (meeting?.attendees || []).map(a => a.email).filter(Boolean);
  const usingFallback = attendeeEmails.length === 0 && !!meeting?.created_by_email;

  const recipientLabel = usingFallback
    ? `${meeting.created_by_name || "Meeting Creator"} (${meeting.created_by_email})`
    : (meeting?.attendees || []).map(a => a.name).join(", ") || "No attendees";

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-900">Send Report</h3>
          <button onClick={onClose}><X className="w-4 h-4 text-gray-400" /></button>
        </div>

        <p className="text-sm text-gray-600 mb-3">
          {usingFallback
            ? "No attendees are on record for this session. The report will be sent to the meeting creator instead."
            : "This will email a link to the signed-off report to all attendees who have an email address on record."}
        </p>

        <div className={`mb-4 p-3 rounded-md text-xs ${usingFallback ? "bg-amber-50 border border-amber-200 text-amber-800" : "bg-gray-50 text-gray-500"}`}>
          <div className="flex items-center gap-1.5 font-semibold mb-0.5">
            {usingFallback && <UserCircle className="w-3.5 h-3.5 flex-shrink-0" />}
            {usingFallback ? "Sending to (creator):" : "Recipients:"}
          </div>
          <span>{recipientLabel}</span>
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
          <button onClick={onClose} className="px-4 py-2 text-sm border border-gray-300 text-gray-600 rounded-md hover:bg-gray-50">Cancel</button>
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
  );
}

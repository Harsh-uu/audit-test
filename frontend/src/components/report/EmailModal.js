import React, { useState } from "react";
import { X, Send, AlertTriangle, UserCircle, Plus, Trash2 } from "lucide-react";

export function EmailModal({ show, onClose, meeting, sendingEmail, emailMessage, setEmailMessage, sendReport }) {
  // All hooks must be called unconditionally (before any early returns)
  const [extraEmails, setExtraEmails] = useState([]);
  const [newEmail, setNewEmail] = useState("");

  if (!show) return null;

  // Build the initial recipient list from attendees with emails
  const attendeesWithEmail = (meeting?.attendees || []).filter(a => a.email);
  const attendeesWithoutEmail = (meeting?.attendees || []).filter(a => !a.email);
  const usingCreatorFallback = attendeesWithEmail.length === 0 && !!meeting?.created_by_email;

  const handleAddEmail = () => {
    const trimmed = newEmail.trim().toLowerCase();
    if (!trimmed || !trimmed.includes("@")) return;
    if (extraEmails.includes(trimmed)) return;
    setExtraEmails(prev => [...prev, trimmed]);
    setNewEmail("");
  };

  const handleRemoveExtra = (email) => setExtraEmails(prev => prev.filter(e => e !== email));

  const handleSend = () => {
    // Build final recipient list
    const baseEmails = usingCreatorFallback
      ? [meeting.created_by_email]
      : attendeesWithEmail.map(a => a.email);
    const allRecipients = [...new Set([...baseEmails, ...extraEmails])];
    sendReport(allRecipients);
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-900">Send Report</h3>
          <button onClick={onClose} data-testid="email-modal-close-btn">
            <X className="w-4 h-4 text-gray-400" />
          </button>
        </div>

        {/* Recipients list */}
        <div className="mb-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Recipients</p>
          <div className="border border-gray-200 rounded-lg divide-y divide-gray-100 mb-2">
            {usingCreatorFallback ? (
              <div className="flex items-center gap-2 px-3 py-2 bg-amber-50 rounded-lg">
                <UserCircle className="w-4 h-4 text-amber-500 flex-shrink-0" />
                <div>
                  <p className="text-xs font-medium text-amber-800">{meeting.created_by_name || "Meeting Creator"}</p>
                  <p className="text-xs text-amber-600">{meeting.created_by_email}</p>
                </div>
                <span className="ml-auto text-xs text-amber-600 italic">fallback — no attendee emails</span>
              </div>
            ) : attendeesWithEmail.length > 0 ? (
              attendeesWithEmail.map((a, i) => (
                <div key={i} className="flex items-center gap-2 px-3 py-2" data-testid={`recipient-row-${i}`}>
                  <div className="w-6 h-6 rounded-full bg-emerald-100 flex items-center justify-center flex-shrink-0">
                    <span className="text-xs font-semibold text-emerald-700">{a.name?.[0] || "?"}</span>
                  </div>
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-gray-800 truncate">{a.name}</p>
                    <p className="text-xs text-gray-500 truncate">{a.email}</p>
                  </div>
                </div>
              ))
            ) : (
              <div className="px-3 py-3 text-xs text-gray-400 italic text-center">No attendees have an email address on record.</div>
            )}
            {extraEmails.map((email, i) => (
              <div key={`extra-${i}`} className="flex items-center gap-2 px-3 py-2 bg-blue-50">
                <div className="w-6 h-6 rounded-full bg-blue-100 flex items-center justify-center flex-shrink-0">
                  <Plus className="w-3 h-3 text-blue-600" />
                </div>
                <p className="text-xs text-blue-700 flex-1 truncate">{email}</p>
                <button onClick={() => handleRemoveExtra(email)} className="text-gray-400 hover:text-red-500">
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>

          {/* Add custom email */}
          <div className="flex gap-1.5">
            <input
              type="email"
              value={newEmail}
              onChange={e => setNewEmail(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleAddEmail()}
              placeholder="Add another recipient email…"
              className="flex-1 px-3 py-1.5 border border-gray-300 rounded-md text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500"
              data-testid="add-recipient-input"
            />
            <button
              onClick={handleAddEmail}
              className="px-2.5 py-1.5 bg-gray-100 text-gray-600 rounded-md text-xs hover:bg-gray-200 font-medium"
              data-testid="add-recipient-btn"
            >
              Add
            </button>
          </div>

          {/* Warning for attendees without email */}
          {attendeesWithoutEmail.length > 0 && (
            <div className="mt-2 flex items-start gap-1.5 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
              <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
              <span>
                <strong>{attendeesWithoutEmail.map(a => a.name).join(", ")}</strong>{" "}
                {attendeesWithoutEmail.length === 1 ? "has" : "have"} no email address on record and will not receive this report.
              </span>
            </div>
          )}
        </div>

        {/* Optional message */}
        <textarea
          value={emailMessage}
          onChange={e => setEmailMessage(e.target.value)}
          placeholder="Optional personal message to include in the email…"
          rows={2}
          className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 resize-none mb-4"
          data-testid="email-message-input"
        />

        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm border border-gray-300 text-gray-600 rounded-md hover:bg-gray-50">Cancel</button>
          <button
            onClick={handleSend}
            disabled={sendingEmail || (attendeesWithEmail.length === 0 && extraEmails.length === 0 && !usingCreatorFallback)}
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

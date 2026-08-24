import React from "react";
import { History, AlertTriangle } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";

const AUDIT_EVENT_CONFIG = {
  meeting_created:   { color: "bg-blue-100 text-blue-700", dot: "bg-blue-400" },
  recording_started: { color: "bg-red-100 text-red-700", dot: "bg-red-400" },
  recording_paused:  { color: "bg-amber-100 text-amber-700", dot: "bg-amber-400" },
  recording_resumed: { color: "bg-amber-100 text-amber-700", dot: "bg-amber-400" },
  recording_stopped: { color: "bg-gray-100 text-gray-600", dot: "bg-gray-400" },
  recording_notice_acknowledged: { color: "bg-gray-100 text-gray-600", dot: "bg-gray-300" },
  transcribed:       { color: "bg-indigo-100 text-indigo-700", dot: "bg-indigo-400" },
  analyzed:          { color: "bg-purple-100 text-purple-700", dot: "bg-purple-400" },
  edit_summary:      { color: "bg-blue-50 text-blue-600", dot: "bg-blue-300" },
  edit_actions:      { color: "bg-blue-50 text-blue-600", dot: "bg-blue-300" },
  edit_action_completion:        { color: "bg-emerald-100 text-emerald-700", dot: "bg-emerald-400" },
  action_status_changed:         { color: "bg-emerald-100 text-emerald-700", dot: "bg-emerald-400" },
  learning_need_status_changed:  { color: "bg-sky-100 text-sky-700", dot: "bg-sky-400" },
  achievement_acknowledged:      { color: "bg-amber-100 text-amber-700", dot: "bg-amber-400" },
  edit_evidence:     { color: "bg-blue-50 text-blue-600", dot: "bg-blue-300" },
  edit_post_signoff_evidence_edit: { color: "bg-red-100 text-red-700 font-semibold", dot: "bg-red-500" },
  mark_reviewed:     { color: "bg-emerald-100 text-emerald-700", dot: "bg-emerald-400" },
  signed_off:        { color: "bg-emerald-100 text-emerald-800 font-semibold", dot: "bg-emerald-600" },
  comment_added:     { color: "bg-gray-100 text-gray-700", dot: "bg-gray-400" },
  audio_deleted:     { color: "bg-red-50 text-red-600", dot: "bg-red-300" },
};

const ISO_TIMESTAMP_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z?$/;

function AuditEvent({ event }) {
  const cfg = AUDIT_EVENT_CONFIG[event.type] || { color: "bg-gray-100 text-gray-600", dot: "bg-gray-400" };
  const isPostSignoff = event.flagged;
  // Some older log entries stored the raw event timestamp as the "detail" text — redundant
  // now that the formatted timestamp already renders on the right of every entry, so hide it.
  const showDetail = event.detail && !ISO_TIMESTAMP_RE.test(event.detail.trim());
  return (
    <div className="relative">
      <div className={`absolute -left-5 w-2.5 h-2.5 rounded-full border-2 border-white ${cfg.dot}`} style={{ top: "0.35rem" }} />
      <div className={`border rounded-lg p-3 shadow-sm ${isPostSignoff ? "bg-red-50 border-red-200" : "bg-white border-gray-200"}`}>
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-1.5">
            {isPostSignoff && <AlertTriangle className="w-3.5 h-3.5 text-red-500 flex-shrink-0" />}
            <span className={`inline-block text-xs px-2 py-0.5 rounded-full ${cfg.color}`}>{event.label}</span>
          </div>
          <span className="text-xs text-gray-400 whitespace-nowrap flex-shrink-0">
            {event.timestamp ? new Date(event.timestamp).toLocaleString("en-GB") : "—"}
          </span>
        </div>
        <p className="text-xs text-gray-500 mt-1">by <strong className="text-gray-700">{event.actor}</strong></p>
        {showDetail && <p className="text-xs text-gray-600 mt-1 italic">"{event.detail}"</p>}
      </div>
    </div>
  );
}

export function AuditTrailTab({ auditLoading, auditTrail, fetchAuditTrail }) {
  return (
    <div data-testid="audit-trail-view">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <History className="w-4 h-4 text-gray-500" />
          <h3 className="text-sm font-semibold text-gray-700 font-display">Audit Trail</h3>
        </div>
        <button onClick={fetchAuditTrail} className="text-xs text-[#1E3A8A] hover:underline" data-testid="refresh-audit-btn">Refresh</button>
      </div>

      {auditLoading && (
        <div className="relative" aria-busy="true" aria-label="Loading audit trail">
          <div className="absolute left-3 top-0 bottom-0 w-px bg-gray-200" />
          <div className="space-y-4 pl-8">
            {[72, 56, 80, 64, 48].map((pillW, i) => (
              <div key={i} className="relative">
                {/* timeline dot */}
                <div className="absolute -left-5 w-2.5 h-2.5 rounded-full border-2 border-white bg-gray-200" style={{ top: "0.35rem" }} />
                <div className="border border-gray-200 rounded-lg p-3 bg-white shadow-sm space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <Skeleton className="h-5 rounded-full" style={{ width: pillW }} />
                    <Skeleton className="h-3.5 w-24 rounded" />
                  </div>
                  <Skeleton className="h-3.5 w-32 rounded" />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {!auditLoading && auditTrail?.length === 0 && (
        <p className="text-sm text-gray-400 text-center py-8">No audit events yet</p>
      )}
      {!auditLoading && auditTrail && auditTrail.length > 0 && (
        <div className="relative" data-testid="audit-trail-list">
          <div className="absolute left-3 top-0 bottom-0 w-px bg-gray-200" />
          <div className="space-y-4 pl-8">
            {auditTrail.map((ev, idx) => (
              <AuditEvent key={idx} event={ev} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

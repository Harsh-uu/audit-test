import React from "react";
import {
  Edit3, CheckCircle, Clock, Pause, AlertTriangle, Plus, Trash2, Check, Shield,
} from "lucide-react";

export function EvidenceTab({
  meeting,
  analysis,
  canReview,
  editingSummary,
  setEditingSummary,
  summaryText,
  setSummaryText,
  saveSummary,
  addingAction,
  setAddingAction,
  newAction,
  setNewAction,
  addAction,
  removeAction,
  toggleActionComplete,
  actionMessage,
}) {
  return (
    <div className="space-y-6">
      {/* Summary */}
      <div className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-gray-900 text-sm font-display">Meeting Summary</h3>
          {canReview && !editingSummary && (
            <button onClick={() => setEditingSummary(true)} className="text-xs text-[#1E3A8A] flex items-center gap-1 hover:underline" data-testid="edit-summary-btn">
              <Edit3 className="w-3 h-3" /> Edit
            </button>
          )}
        </div>
        {editingSummary ? (
          <div>
            <textarea value={summaryText} onChange={e => setSummaryText(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm resize-none focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]" rows={5} data-testid="summary-textarea" />
            <div className="flex gap-2 mt-2">
              <button onClick={saveSummary} className="text-xs bg-[#1E3A8A] text-white px-3 py-1.5 rounded hover:bg-[#1E40AF]" data-testid="save-summary-btn">Save</button>
              <button onClick={() => setEditingSummary(false)} className="text-xs border border-gray-300 text-gray-600 px-3 py-1.5 rounded">Cancel</button>
            </div>
          </div>
        ) : (
          <p className="text-sm text-gray-700 leading-relaxed" data-testid="summary-text">
            {analysis.edited_summary || analysis.summary || "No summary available."}
          </p>
        )}
      </div>

      {/* Pauses */}
      {meeting.paused_periods?.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <Pause className="w-4 h-4 text-amber-600" />
            <h4 className="text-sm font-medium text-amber-800">Recording Paused</h4>
          </div>
          <p className="text-xs text-amber-700 mb-2">The recording was paused during this meeting. Paused sections were not recorded.</p>
          {meeting.paused_periods.map((p, i) => (
            <div key={p.paused_at || i} className="text-xs text-amber-700 font-mono">
              Pause {i + 1}: {new Date(p.paused_at).toLocaleTimeString()} — {p.resumed_at ? new Date(p.resumed_at).toLocaleTimeString() : "ongoing"} ({p.duration_seconds}s)
            </div>
          ))}
        </div>
      )}

      {/* Actions */}
      {(analysis.actions?.length > 0 || canReview) && (
        <div className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold text-gray-900 text-sm font-display">
              Action Items
              {analysis.actions?.length > 0 && (
                <span className="ml-2 text-xs font-normal text-gray-400">({analysis.actions.length})</span>
              )}
            </h3>
            {canReview && !addingAction && (
              <button onClick={() => setAddingAction(true)} className="flex items-center gap-1 text-xs text-[#1E3A8A] hover:underline font-medium" data-testid="add-action-btn">
                <Plus className="w-3 h-3" /> Add Action
              </button>
            )}
          </div>

          <div className="space-y-2" data-testid="actions-list">
            {(analysis.actions || []).map((action, i) => (
              <div key={action.id || action.text?.slice(0, 40) || i} className={`flex items-start gap-3 p-2.5 rounded-md group border transition-colors ${action.completed ? "bg-gray-50 border-gray-100 opacity-70" : action.is_rolled_over ? "bg-amber-50 border-amber-200" : "bg-gray-50 border-transparent"}`}>
                <button
                  onClick={() => toggleActionComplete(action.id || i, !action.completed)}
                  className={`w-5 h-5 rounded border-2 flex items-center justify-center flex-shrink-0 mt-0.5 transition-colors ${action.completed ? "bg-emerald-500 border-emerald-500 text-white" : "border-gray-300 hover:border-emerald-400"}`}
                  title={action.completed ? "Mark as outstanding" : "Mark as complete"}
                  data-testid={`complete-action-${i}`}
                >
                  {action.completed && <Check className="w-3 h-3" />}
                </button>
                <div className="flex-1 min-w-0">
                  <p className={`text-sm ${action.completed ? "line-through text-gray-400" : "text-gray-800"}`}>{action.text}</p>
                  {action.is_rolled_over && !action.completed && (
                    <p className="text-xs text-amber-600 font-medium mt-0.5">Carried over from: {action.source_meeting_title}</p>
                  )}
                  {(action.assigned_to || action.due_date) && (
                    <p className="text-xs text-gray-500 mt-0.5">
                      {action.assigned_to && `Assigned: ${action.assigned_to}`}
                      {action.assigned_to && action.due_date && " · "}
                      {action.due_date && `Due: ${action.due_date}`}
                    </p>
                  )}
                </div>
                {canReview && !action.is_rolled_over && (
                  <button onClick={() => removeAction(i)} className="opacity-0 group-hover:opacity-100 p-1 text-gray-400 hover:text-red-500 transition-all rounded flex-shrink-0" data-testid={`remove-action-${i}`} title="Remove action">
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            ))}
            {analysis.actions?.length === 0 && !addingAction && (
              <p className="text-sm text-gray-400 py-2 text-center">No actions yet — add one below</p>
            )}
          </div>

          {addingAction && (
            <div className="mt-3 border border-dashed border-[#1E3A8A] rounded-md p-3 bg-blue-50 fade-in" data-testid="add-action-form">
              <p className="text-xs font-semibold text-[#1E3A8A] mb-2">New Action</p>
              <input
                type="text"
                value={newAction.text}
                onChange={e => setNewAction(a => ({ ...a, text: e.target.value }))}
                placeholder="Describe the action required..."
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] bg-white mb-2"
                data-testid="new-action-text"
                autoFocus
                onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); addAction(); } }}
              />
              <div className="grid grid-cols-2 gap-2 mb-3">
                <input type="text" value={newAction.assigned_to} onChange={e => setNewAction(a => ({ ...a, assigned_to: e.target.value }))} placeholder="Assigned to (optional)" className="px-3 py-1.5 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] bg-white" data-testid="new-action-assigned" />
                <input type="text" value={newAction.due_date} onChange={e => setNewAction(a => ({ ...a, due_date: e.target.value }))} placeholder="Due date (optional)" className="px-3 py-1.5 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] bg-white" data-testid="new-action-due" />
              </div>
              <div className="flex gap-2">
                <button onClick={addAction} disabled={!newAction.text.trim()} className="flex items-center gap-1.5 bg-[#1E3A8A] text-white px-3 py-1.5 rounded-md text-xs font-medium hover:bg-[#1E40AF] disabled:opacity-50 transition-colors" data-testid="save-new-action-btn">
                  <Plus className="w-3 h-3" /> Add Action
                </button>
                <button onClick={() => { setAddingAction(false); setNewAction({ text: "", assigned_to: "", due_date: "" }); }} className="px-3 py-1.5 border border-gray-300 text-gray-600 rounded-md text-xs hover:bg-gray-50 transition-colors" data-testid="cancel-add-action-btn">
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Risks */}
      {analysis.risks?.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
          <h3 className="font-semibold text-gray-900 text-sm mb-3 font-display">Risks &amp; Concerns</h3>
          <div className="space-y-2" data-testid="risks-list">
            {analysis.risks.map((risk, i) => (
              <div key={risk.text?.slice(0, 40) || i} className={`flex items-start gap-2 p-2.5 rounded-md border ${risk.severity === "high" ? "bg-red-50 border-red-200" : risk.severity === "medium" ? "bg-amber-50 border-amber-200" : "bg-gray-50 border-gray-200"}`}>
                <AlertTriangle className={`w-3.5 h-3.5 mt-0.5 flex-shrink-0 ${risk.severity === "high" ? "text-red-500" : risk.severity === "medium" ? "text-amber-500" : "text-gray-400"}`} />
                <p className="text-sm text-gray-800">{risk.text}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Attendees review status */}
      {meeting.attendees?.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm">
          <h3 className="font-semibold text-gray-900 text-sm mb-3 font-display">Review Status</h3>
          <div className="space-y-2">
            {meeting.attendees.map(a => (
              <div key={a.user_id} className="flex items-center justify-between">
                <span className="text-sm text-gray-700">{a.name}</span>
                {a.reviewed
                  ? <span className="text-xs text-emerald-600 flex items-center gap-1"><CheckCircle className="w-3 h-3" /> Reviewed</span>
                  : <span className="text-xs text-amber-600 flex items-center gap-1"><Clock className="w-3 h-3" /> Pending</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Sign-off info */}
      {meeting.sign_off_record && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-4">
          <div className="flex items-center gap-2">
            <Shield className="w-4 h-4 text-emerald-600" />
            <p className="text-sm font-medium text-emerald-800">Signed off by {meeting.sign_off_record.signed_by_name}</p>
          </div>
          <p className="text-xs text-emerald-600 mt-1">{new Date(meeting.sign_off_record.signed_at).toLocaleString("en-GB")}</p>
        </div>
      )}

      {/* Audio status */}
      {meeting.audio_deletion_status !== "none" && (
        <div className={`border rounded-lg p-3 text-xs ${meeting.audio_deletion_status === "deleted" ? "bg-gray-50 border-gray-200 text-gray-500" : "bg-amber-50 border-amber-200 text-amber-700"}`} data-testid="audio-status">
          <strong>Audio:</strong> {
            meeting.audio_deletion_status === "grace_period" ? "Grace period — will be deleted in ~5 minutes" :
            meeting.audio_deletion_status === "deleted" ? "Deleted (GDPR compliant)" :
            "Pending deletion"
          }
        </div>
      )}

      {actionMessage && (
        <div className="bg-blue-50 border border-blue-200 text-blue-700 rounded-md p-3 text-sm" data-testid="action-message">
          {actionMessage}
        </div>
      )}
    </div>
  );
}

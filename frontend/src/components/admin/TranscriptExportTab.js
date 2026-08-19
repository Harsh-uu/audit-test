import React from "react";
import { Download, Calendar, Users, Loader2, X } from "lucide-react";
import { UkDatePicker } from "@/components/ui/uk-date-picker";

export function TranscriptExportTab({
  users,
  exportStaffIds,
  toggleExportStaff,
  exportDateFrom,
  setExportDateFrom,
  exportDateTo,
  setExportDateTo,
  exportMeetings,
  exportSelectedMeetings,
  toggleExportMeeting,
  exportLoading,
  exportMeetingsLoading,
  handleTranscriptExport,
  setExportSelectedMeetings,
  setExportStaffIds,
}) {
  return (
    <div data-testid="transcript-export-tab">
      <div className="max-w-2xl">
        <p className="text-sm text-gray-500 mb-6">
          Export full transcripts as a PDF, one session per page, with speaker turns and meeting metadata.
          Filter by staff member, date range, or pick specific meetings.
        </p>

        {/* Date range */}
        <div className="mb-5">
          <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2">
            <Calendar className="inline w-3.5 h-3.5 mr-1" />
            Date Range (optional)
          </label>
          <div className="flex items-center gap-3">
            <UkDatePicker value={exportDateFrom} onChange={setExportDateFrom} className="text-sm px-3 py-1.5" testId="tx-export-date-from" />
            <span className="text-gray-400 text-sm">to</span>
            <UkDatePicker value={exportDateTo} onChange={setExportDateTo} minDate={exportDateFrom ? new Date(exportDateFrom) : undefined} className="text-sm px-3 py-1.5" testId="tx-export-date-to" />
            {(exportDateFrom || exportDateTo) && (
              <button onClick={() => { setExportDateFrom(""); setExportDateTo(""); }} className="text-xs text-gray-400 hover:text-gray-600">Clear</button>
            )}
          </div>
        </div>

        {/* Staff filter */}
        {users.length > 0 && (
          <div className="mb-5">
            <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2">
              <Users className="inline w-3.5 h-3.5 mr-1" />
              Staff Member (optional)
            </label>
            <div className="flex flex-wrap gap-2">
              {users.map(u => (
                <button
                  key={u.id}
                  onClick={() => toggleExportStaff(u.id)}
                  className={`text-xs px-2.5 py-1 rounded-full border transition-colors flex items-center gap-1 ${
                    exportStaffIds.includes(u.id) ? "bg-[#1E3A8A] text-white border-[#1E3A8A]" : "bg-white text-gray-600 border-gray-200 hover:bg-gray-50"
                  }`}
                  data-testid={`tx-export-staff-${u.id}`}
                >
                  {u.name}
                  {exportStaffIds.includes(u.id) && <X className="w-2.5 h-2.5" />}
                </button>
              ))}
            </div>
            {exportStaffIds.length > 0 && (
              <button onClick={() => setExportStaffIds([])} className="text-xs text-gray-400 hover:text-gray-600 mt-1">Clear selection</button>
            )}
          </div>
        )}

        {/* Meeting picker */}
        <div className="mb-6">
          <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2">
            Or pick specific meetings
          </label>
          {exportMeetingsLoading ? (
            <div className="flex items-center gap-2 text-xs text-gray-400"><Loader2 className="w-3.5 h-3.5 animate-spin" />Loading meetings…</div>
          ) : exportMeetings.length === 0 ? (
            <p className="text-xs text-gray-400">No signed-off meetings found.</p>
          ) : (
            <div className="max-h-48 overflow-y-auto border border-gray-200 rounded-lg divide-y divide-gray-100">
              {exportMeetings.map(m => (
                <label key={m.id} className="flex items-center gap-3 px-3 py-2 hover:bg-gray-50 cursor-pointer">
                  <input type="checkbox" checked={exportSelectedMeetings.includes(m.id)} onChange={() => toggleExportMeeting(m.id)} className="w-3.5 h-3.5 accent-[#1E3A8A]" />
                  <span className="text-sm text-gray-700 flex-1">{m.title}</span>
                  <span className="text-xs text-gray-400 flex-shrink-0">{m.date?.slice(0, 10)}</span>
                </label>
              ))}
            </div>
          )}
          {exportSelectedMeetings.length > 0 && (
            <button onClick={() => setExportSelectedMeetings([])} className="text-xs text-gray-400 hover:text-gray-600 mt-1">Clear selection</button>
          )}
        </div>

        <button
          onClick={handleTranscriptExport}
          disabled={exportLoading}
          className="flex items-center gap-2 bg-[#1E3A8A] text-white px-5 py-2.5 rounded-lg text-sm font-medium hover:bg-[#1E40AF] transition-colors disabled:opacity-60"
          data-testid="tx-export-btn"
        >
          {exportLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
          {exportLoading ? "Generating…" : "Download Transcripts PDF"}
        </button>
      </div>
    </div>
  );
}

import React from "react";
import { Download, Calendar, Users, Filter, Loader, X } from "lucide-react";

export function ExportTab({
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
  handleExport,
  setExportSelectedMeetings,
  setExportStaffIds,
}) {
  return (
    <div data-testid="export-tab">
      <div className="max-w-2xl">
        <p className="text-sm text-gray-500 mb-6">
          Export all compliance evidence records as a single formatted PDF report, covering all CQC and Care Certificate mappings across signed-off supervision meetings.
          Filter by staff member, date range, or specific meetings.
        </p>

        {/* Date range */}
        <div className="mb-5">
          <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2">
            <Calendar className="inline w-3.5 h-3.5 mr-1" />
            Date Range (optional)
          </label>
          <div className="flex items-center gap-3">
            <input
              type="date"
              value={exportDateFrom}
              onChange={e => setExportDateFrom(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
              data-testid="export-date-from"
            />
            <span className="text-gray-400 text-sm">to</span>
            <input
              type="date"
              value={exportDateTo}
              onChange={e => setExportDateTo(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
              data-testid="export-date-to"
            />
            {(exportDateFrom || exportDateTo) && (
              <button onClick={() => { setExportDateFrom(""); setExportDateTo(""); }} className="text-xs text-gray-400 hover:text-gray-600">Clear</button>
            )}
          </div>
        </div>

        {/* Staff filter */}
        <div className="mb-5">
          <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2">
            <Users className="inline w-3.5 h-3.5 mr-1" />
            Staff Members (optional — leave blank for all)
          </label>
          <div className="flex flex-wrap gap-2 p-3 border border-gray-200 rounded-md bg-gray-50 max-h-36 overflow-y-auto">
            {users.filter(u => ["attendee", "manager"].includes(u.role)).map(u => (
              <button
                key={u.id}
                onClick={() => toggleExportStaff(u.id)}
                className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border transition-colors ${
                  exportStaffIds.includes(u.id)
                    ? "bg-[#1E3A8A] text-white border-[#1E3A8A]"
                    : "bg-white text-gray-700 border-gray-300 hover:bg-gray-100"
                }`}
                data-testid={`staff-chip-${u.id}`}
              >
                {exportStaffIds.includes(u.id) && <X className="w-2.5 h-2.5" />}
                {u.name}
              </button>
            ))}
          </div>
          {exportStaffIds.length > 0 && (
            <button onClick={() => setExportStaffIds([])} className="text-xs text-gray-400 hover:text-gray-600 mt-1">Clear selection</button>
          )}
        </div>

        {/* Specific meetings */}
        <div className="mb-6">
          <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2">
            <Filter className="inline w-3.5 h-3.5 mr-1" />
            Specific Meetings (optional — overrides above filters if selected)
          </label>
          {exportMeetingsLoading ? (
            <div className="flex items-center gap-2 text-sm text-gray-400 py-2"><Loader className="w-4 h-4 animate-spin" /> Loading meetings…</div>
          ) : (
            <div className="border border-gray-200 rounded-md bg-gray-50 max-h-48 overflow-y-auto">
              {exportMeetings.length === 0 ? (
                <p className="text-xs text-gray-400 p-3">No signed-off meetings available</p>
              ) : (
                exportMeetings.map(m => (
                  <label
                    key={m.id}
                    className="flex items-center gap-3 px-3 py-2 hover:bg-white cursor-pointer border-b border-gray-100 last:border-0"
                    data-testid={`meeting-check-${m.id}`}
                  >
                    <input
                      type="checkbox"
                      checked={exportSelectedMeetings.includes(m.id)}
                      onChange={() => toggleExportMeeting(m.id)}
                      className="w-3.5 h-3.5 accent-[#1E3A8A]"
                    />
                    <span className="flex-1 text-sm text-gray-800 truncate">{m.title}</span>
                    <span className="text-xs text-gray-400 flex-shrink-0">{m.date ? m.date.slice(0, 10) : "—"}</span>
                  </label>
                ))
              )}
            </div>
          )}
          {exportSelectedMeetings.length > 0 && (
            <button onClick={() => setExportSelectedMeetings([])} className="text-xs text-gray-400 hover:text-gray-600 mt-1">Clear selection</button>
          )}
        </div>

        <button
          onClick={handleExport}
          disabled={exportLoading}
          className="flex items-center gap-2 bg-[#1E3A8A] text-white px-6 py-2.5 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors disabled:opacity-60"
          data-testid="run-export-btn"
        >
          <Download className="w-4 h-4" />
          {exportLoading ? "Generating…" : "Export PDF"}
        </button>
      </div>
    </div>
  );
}

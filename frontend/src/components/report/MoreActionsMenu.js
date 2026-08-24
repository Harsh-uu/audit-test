import React from "react";
import { MoreHorizontal, FileText, Share2 } from "lucide-react";

export function MoreActionsMenu({
  menuRef, show, onToggle,
  includeTranscript, setIncludeTranscript,
  exportingPdf, onExportPdf,
  exportingTranscript, onExportTranscript,
  meeting, onShare,
}) {
  return (
    <div className="relative" ref={menuRef}>
      <button
        onClick={onToggle}
        className="w-9 h-9 flex items-center justify-center border border-gray-200 rounded-md text-gray-500 hover:bg-gray-50 transition-colors"
        data-testid="more-actions-btn"
        title="More actions"
      >
        <MoreHorizontal className="w-4 h-4" />
      </button>
      {show && (
        <div className="absolute right-0 top-full mt-1.5 w-64 bg-white rounded-lg shadow-lg border border-gray-200 z-30 overflow-hidden py-1.5" data-testid="more-actions-menu">
          <label className="flex items-center gap-2 px-3.5 py-1.5 text-xs text-gray-500 cursor-pointer select-none">
            <input type="checkbox" checked={includeTranscript} onChange={e => setIncludeTranscript(e.target.checked)} className="w-3.5 h-3.5 accent-[#1E3A8A]" data-testid="include-transcript-toggle" />
            Include full transcript in PDF
          </label>
          <button onClick={onExportPdf} disabled={exportingPdf} className="w-full flex items-center gap-2.5 px-3.5 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors disabled:opacity-60" data-testid="export-pdf-btn">
            <FileText className="w-4 h-4 text-gray-400" />
            {exportingPdf ? "Generating…" : "Export PDF"}
          </button>
          <button onClick={onExportTranscript} disabled={exportingTranscript} className="w-full flex items-center gap-2.5 px-3.5 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors disabled:opacity-60" data-testid="export-transcript-btn">
            <FileText className="w-4 h-4 text-gray-400" />
            {exportingTranscript ? "Generating…" : "Export Transcript"}
          </button>
          <div className="border-t border-gray-100 my-1"></div>
          <button onClick={onShare} className="w-full flex items-center gap-2.5 px-3.5 py-2 text-sm text-indigo-700 hover:bg-indigo-50 transition-colors" data-testid="share-report-btn">
            <Share2 className="w-4 h-4 text-indigo-400" />
            {meeting?.shared_with?.length ? `Shared (${meeting.shared_with.length})` : "Share with team"}
          </button>
        </div>
      )}
    </div>
  );
}

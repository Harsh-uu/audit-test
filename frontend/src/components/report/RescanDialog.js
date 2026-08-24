import React from "react";
import { Loader2, RefreshCw } from "lucide-react";

export function RescanDialog({ menuRef, rescanning, show, onToggle, rescanPrompt, setRescanPrompt, onRescanWithGuidance, onRescanWithoutGuidance, onCancel }) {
  return (
    <div className="relative" ref={menuRef}>
      <button
        onClick={() => !rescanning && onToggle()}
        disabled={rescanning}
        data-testid="rescan-evidence-btn"
        title="Re-scan compliance evidence — optionally with custom guidance"
        className="flex items-center gap-1.5 text-sm px-3 py-2 rounded-md border border-gray-200 bg-white text-gray-600 hover:bg-blue-50 hover:border-blue-200 hover:text-blue-700 transition-colors disabled:opacity-60"
      >
        {rescanning
          ? <Loader2 className="w-4 h-4 animate-spin" />
          : <RefreshCw className="w-4 h-4" />}
        <span className="hidden sm:inline">{rescanning ? "Re-scanning…" : "Re-scan"}</span>
      </button>
      {show && !rescanning && (
        <div
          className="absolute right-0 top-full mt-1.5 w-80 border border-blue-200 rounded-lg bg-blue-50 p-3 shadow-lg z-30"
          data-testid="rescan-dialog"
        >
          <p className="text-xs font-semibold text-blue-800 mb-1.5 flex items-center gap-1.5">
            <RefreshCw className="w-3 h-3" /> Guide the re-scan (optional)
          </p>
          <textarea
            value={rescanPrompt}
            onChange={e => setRescanPrompt(e.target.value)}
            placeholder="e.g. Focus on medication management and manual handling, or look for evidence of Care Certificate Standard 9"
            className="w-full text-xs px-2.5 py-2 border border-blue-200 rounded-md bg-white resize-none focus:outline-none focus:ring-2 focus:ring-blue-400 text-gray-700 placeholder-gray-400"
            rows={3}
            data-testid="rescan-prompt-input"
          />
          <div className="flex items-center gap-2 mt-2">
            <button
              onClick={() => onRescanWithGuidance(rescanPrompt.trim())}
              disabled={!rescanPrompt.trim()}
              className="text-xs px-3 py-1.5 bg-[#1E3A8A] text-white rounded-md font-medium hover:bg-[#1E40AF] disabled:opacity-40 transition-colors"
              data-testid="rescan-with-guidance-btn"
            >
              Re-scan with guidance
            </button>
            <button
              onClick={onRescanWithoutGuidance}
              className="text-xs px-3 py-1.5 border border-gray-300 text-gray-600 rounded-md hover:bg-white transition-colors"
              data-testid="rescan-without-guidance-btn"
            >
              Re-scan without guidance
            </button>
            <button
              onClick={onCancel}
              className="ml-auto text-xs text-gray-400 hover:text-gray-600"
              data-testid="rescan-cancel-btn"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

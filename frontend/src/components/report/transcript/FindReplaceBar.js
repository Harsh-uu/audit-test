import React from "react";
import { Search, ChevronUp, ChevronDown, X } from "lucide-react";

export function FindReplaceBar({
  findInputRef, findQuery, setFindQuery, replaceWith, setReplaceWith,
  findMatches, findMatchIdx, viewMode,
  onFindNext, onFindPrev, onClose, onReplaceOne, onReplaceAll,
}) {
  return (
    <div className="border-b border-blue-200 bg-blue-50 px-4 py-3" data-testid="find-replace-bar">
      {/* Row 1 — Find */}
      <div className="flex items-center gap-2 mb-2">
        <Search className="w-3.5 h-3.5 text-blue-500 flex-shrink-0" />
        <input
          ref={findInputRef}
          type="text"
          value={findQuery}
          onChange={e => setFindQuery(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter") { e.shiftKey ? onFindPrev() : onFindNext(); } }}
          placeholder="Find…"
          className="flex-1 min-w-0 text-xs px-2.5 py-1.5 rounded border border-blue-200 bg-white focus:outline-none focus:ring-1 focus:ring-[#1E3A8A] placeholder-gray-400"
          data-testid="find-input"
        />
        {/* Match counter */}
        <span className="text-xs text-gray-500 min-w-[44px] text-center flex-shrink-0">
          {findQuery.trim()
            ? findMatches.length === 0
              ? <span className="text-red-500">No match</span>
              : `${findMatchIdx + 1} / ${findMatches.length}`
            : ""}
        </span>
        {/* Prev / Next */}
        <button
          onClick={onFindPrev}
          disabled={findMatches.length === 0}
          className="p-1 rounded hover:bg-blue-100 disabled:opacity-30 transition-colors"
          title="Previous (Shift+Enter)"
          data-testid="find-prev-btn"
        >
          <ChevronUp className="w-3.5 h-3.5 text-gray-600" />
        </button>
        <button
          onClick={onFindNext}
          disabled={findMatches.length === 0}
          className="p-1 rounded hover:bg-blue-100 disabled:opacity-30 transition-colors"
          title="Next (Enter)"
          data-testid="find-next-btn"
        >
          <ChevronDown className="w-3.5 h-3.5 text-gray-600" />
        </button>
        {/* Close */}
        <button
          onClick={onClose}
          className="ml-1 p-1 rounded hover:bg-blue-100 transition-colors"
          title="Close (Escape)"
          data-testid="find-replace-close-btn"
        >
          <X className="w-3.5 h-3.5 text-gray-500" />
        </button>
      </div>
      {/* Row 2 — Replace */}
      <div className="flex items-center gap-2">
        <div className="w-3.5 flex-shrink-0" /> {/* align with search icon */}
        <input
          type="text"
          value={replaceWith}
          onChange={e => setReplaceWith(e.target.value)}
          onKeyDown={e => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") onReplaceAll(); }}
          placeholder="Replace with…"
          className="flex-1 min-w-0 text-xs px-2.5 py-1.5 rounded border border-blue-200 bg-white focus:outline-none focus:ring-1 focus:ring-[#1E3A8A] placeholder-gray-400"
          data-testid="replace-input"
        />
        <button
          onClick={onReplaceOne}
          disabled={findMatches.length === 0}
          className="text-xs px-3 py-1.5 rounded border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 disabled:opacity-40 transition-colors flex-shrink-0 font-medium"
          data-testid="replace-one-btn"
        >
          Replace
        </button>
        <button
          onClick={onReplaceAll}
          disabled={findMatches.length === 0}
          className="text-xs px-3 py-1.5 rounded bg-[#1E3A8A] text-white hover:bg-[#1E40AF] disabled:opacity-40 transition-colors flex-shrink-0 font-semibold"
          data-testid="replace-all-btn"
        >
          Replace All
        </button>
        {viewMode === "speaker" && findMatches.length > 0 && (
          <span className="text-xs text-gray-400 hidden sm:inline">
            Changes will appear in Save flow
          </span>
        )}
      </div>
    </div>
  );
}

import React from "react";
import { FileText, Search, Users, Loader2 } from "lucide-react";

export function TranscriptToolbar({
  viewMode, canAnonymise,
  showFindReplaceBtn, findReplaceOpen, onToggleFindReplace,
  hasSpeakerText, onSetViewMode,
  raw, generating, onGenerateSpeakerView,
}) {
  return (
    <div className="flex items-start gap-2 mb-4 flex-wrap">
      <div className="flex-1 bg-amber-50 border border-amber-200 rounded-md p-3 hidden sm:flex items-center gap-2">
        <FileText className="w-4 h-4 text-amber-600 flex-shrink-0" />
        <p className="text-xs text-amber-700 flex-1">
          {viewMode === "speaker"
            ? "Rename speakers in the panel. Click any pill to reassign a turn. Click the pencil icon to edit turn text. Select text within a turn to split it."
            : canAnonymise
            ? "Highlight any name and click Anonymise to replace it with an initial."
            : "Transcript is read-only. Use the Evidence tab to edit summaries and evidence wording."}
        </p>
      </div>

      {/* Find & Replace button — always visible when transcript exists */}
      {showFindReplaceBtn && (
        <button
          onClick={onToggleFindReplace}
          className={`flex-shrink-0 flex items-center gap-1.5 px-3 py-2 rounded-md border text-xs font-medium transition-colors ${
            findReplaceOpen
              ? "bg-[#1E3A8A] border-[#1E3A8A] text-white"
              : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50"
          }`}
          data-testid="find-replace-btn"
          title="Find & Replace (Ctrl+H)"
        >
          <Search className="w-3.5 h-3.5" />
          Find & Replace
        </button>
      )}

      {hasSpeakerText ? (
        <div className="flex rounded-md border border-gray-200 overflow-hidden flex-shrink-0 text-xs font-medium">
          <button
            className={`px-3 py-2 transition-colors ${viewMode === "full" ? "bg-[#1E3A8A] text-white" : "bg-white text-gray-600 hover:bg-gray-50"}`}
            onClick={() => onSetViewMode("full")}
            data-testid="transcript-full-btn"
          >
            Full Text
          </button>
          <button
            className={`px-3 py-2 flex items-center gap-1.5 transition-colors ${viewMode === "speaker" ? "bg-[#1E3A8A] text-white" : "bg-white text-gray-600 hover:bg-gray-50"}`}
            onClick={() => onSetViewMode("speaker")}
            data-testid="transcript-speaker-btn"
          >
            <Users className="w-3.5 h-3.5" />
            Speaker View
          </button>
        </div>
      ) : raw ? (
        <button
          onClick={onGenerateSpeakerView}
          disabled={generating}
          className="flex-shrink-0 flex items-center gap-1.5 px-3 py-2 rounded-md border border-blue-200 bg-blue-50 text-blue-700 text-xs font-medium hover:bg-blue-100 transition-colors disabled:opacity-60"
          data-testid="generate-speaker-btn"
        >
          {generating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Users className="w-3.5 h-3.5" />}
          {generating ? "Identifying…" : "Identify Speakers"}
        </button>
      ) : null}
    </div>
  );
}

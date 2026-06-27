import React, { useState, useEffect, useCallback } from "react";
import { FileText } from "lucide-react";
import { anonymiseTranscript } from "@/utils/anonymise";

/**
 * Split transcript text into readable paragraphs.
 * Respects existing newlines; falls back to grouping every 3 sentences for blob text.
 */
function formatTranscript(text) {
  if (!text) return [];
  const lines = text.split(/\n+/).map(l => l.trim()).filter(Boolean);
  if (lines.length > 2) return lines;
  // Blob: split into sentences and group 3 per paragraph
  const sentences = text.match(/[^.!?]+[.!?]+["']?\s*/g) || [text];
  const paragraphs = [];
  for (let i = 0; i < sentences.length; i += 3) {
    const chunk = sentences.slice(i, i + 3).join("").trim();
    if (chunk) paragraphs.push(chunk);
  }
  return paragraphs.length ? paragraphs : [text];
}

export function TranscriptTab({ meeting, onAnonymise, canAnonymise }) {
  const [selectionText, setSelectionText] = useState("");
  const [popupPos, setPopupPos] = useState(null);

  const handleMouseUp = useCallback(() => {
    if (!canAnonymise) return;
    const sel = window.getSelection();
    const text = sel?.toString().trim();
    if (!text || text.length < 2) {
      setSelectionText("");
      setPopupPos(null);
      return;
    }
    const range = sel.getRangeAt(0);
    const rect = range.getBoundingClientRect();
    setSelectionText(text);
    setPopupPos({
      top: Math.max(10, rect.top - 44),
      left: rect.left + rect.width / 2,
    });
  }, [canAnonymise]);

  useEffect(() => {
    const clearPopup = (e) => {
      if (e.target.closest("[data-anonymise-btn]")) return;
      setSelectionText("");
      setPopupPos(null);
    };
    document.addEventListener("mousedown", clearPopup);
    return () => document.removeEventListener("mousedown", clearPopup);
  }, []);

  const handleAnonymise = () => {
    if (!selectionText || !onAnonymise) return;
    onAnonymise(selectionText);
    setSelectionText("");
    setPopupPos(null);
    window.getSelection()?.removeAllRanges();
  };

  return (
    <div data-testid="transcript-view">
      <div className="bg-amber-50 border border-amber-200 rounded-md p-3 mb-4 flex items-center gap-2">
        <FileText className="w-4 h-4 text-amber-600 flex-shrink-0" />
        <p className="text-xs text-amber-700">
          {canAnonymise
            ? "Highlight any name in the transcript and click Anonymise to replace it with an initial."
            : "Transcript is read-only. Use the Evidence tab to edit summaries and evidence wording."}
        </p>
      </div>
      <div
        className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm"
        onMouseUp={handleMouseUp}
        data-testid="transcript-text"
      >
        {(() => {
          const raw = anonymiseTranscript(meeting.transcript?.text, meeting.attendees || []);
          if (!raw) return <p className="text-sm text-gray-400 italic">Transcript not available.</p>;
          return formatTranscript(raw).map((para, i) => (
            <p key={i} className="text-sm text-gray-700 leading-relaxed mb-3 last:mb-0">
              {para}
            </p>
          ));
        })()}
      </div>

      {popupPos && selectionText && (
        <div
          data-anonymise-btn="true"
          style={{
            position: "fixed",
            top: popupPos.top,
            left: popupPos.left,
            transform: "translateX(-50%)",
            zIndex: 9999,
          }}
          className="bg-[#1E3A8A] text-white text-xs font-semibold px-3 py-1.5 rounded-full shadow-lg cursor-pointer hover:bg-[#1E40AF] transition-colors select-none flex items-center gap-1.5"
          onMouseDown={(e) => { e.preventDefault(); handleAnonymise(); }}
          data-testid="anonymise-popup-btn"
        >
          <span>Anonymise</span>
          <span className="opacity-75 max-w-[120px] truncate">
            &ldquo;{selectionText.length > 20 ? selectionText.slice(0, 20) + "…" : selectionText}&rdquo;
          </span>
        </div>
      )}
    </div>
  );
}

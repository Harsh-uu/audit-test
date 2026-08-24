import React from "react";
import { ArrowLeftRight, Pencil, Check } from "lucide-react";
import { HighlightedText, MultiHighlightText } from "./HighlightedText";

/** A single speaker-turn row in the Speaker View — pill, reassign menu, editable text, split-to-highlight support */
export function SpeakerTurnRow({
  turn, index, pillClass, pillStyle, rowClassName, rowStyle,
  canEditSpeakers, isMenuOpen, onToggleMenu, uniqueSpeakers, onAssign, onFlipFromHere,
  isEditing, editingTurnText, setEditingTurnText, onSaveTurnText, onCancelTurnText, onStartEdit,
  isHighlighted, highlightRef,
  findReplaceOpen, findQueryTrimmed, turnMatches, findMatchIdx, effectiveHighlightQuery,
}) {
  return (
    <div className={`flex flex-col sm:flex-row gap-1.5 sm:gap-3 px-5 py-3.5 ${rowClassName}`} style={rowStyle}>
      {/* Speaker column: timestamp badge + speaker pill — inline row on mobile (above the text), stacked column on sm+ (beside the text) */}
      <div className="relative sm:flex-shrink-0 sm:mt-0.5 flex flex-row sm:flex-col items-center sm:items-start gap-2 sm:gap-1">
        {turn.timestamp && (
          <span className="text-[10px] font-mono text-gray-400 tabular-nums leading-none">
            {turn.timestamp}
          </span>
        )}
        {canEditSpeakers ? (
          <button
            data-testid={`speaker-pill-${index}`}
            onMouseDown={e => { e.stopPropagation(); onToggleMenu(index); }}
            className={`inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full h-fit transition-all ${pillClass} ${isMenuOpen ? "ring-2 ring-offset-1 ring-blue-400" : "hover:opacity-80"}`}
            style={pillStyle}
            title="Click to reassign this speaker turn"
          >
            {turn.speaker}
            <svg className="w-2.5 h-2.5 opacity-70" viewBox="0 0 10 6" fill="none">
              <path d="M1 1l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
          </button>
        ) : (
          <span
            className={`inline-flex items-center text-xs font-semibold px-2 py-0.5 rounded-full h-fit ${pillClass}`}
            style={pillStyle}
          >
            {turn.speaker}
          </span>
        )}

        {canEditSpeakers && isMenuOpen && (
          <div
            onMouseDown={e => e.stopPropagation()}
            data-testid={`turn-menu-${index}`}
            className="absolute left-0 top-full mt-1 z-20 bg-white border border-gray-200 rounded-lg shadow-lg w-52 py-1 text-xs"
          >
            <p className="px-3 pt-1.5 pb-1 text-gray-400 font-semibold uppercase tracking-wide" style={{ fontSize: "10px" }}>
              Assign turn {index + 1} to
            </p>
            {uniqueSpeakers.map(s => (
              <button
                key={s}
                onMouseDown={() => onAssign(index, s)}
                data-testid={`assign-turn-${index}-${s}`}
                className={`w-full text-left px-3 py-1.5 hover:bg-blue-50 flex items-center gap-2 transition-colors ${
                  turn.speaker === s ? "text-[#1E3A8A] font-semibold bg-blue-50/60" : "text-gray-700"
                }`}
              >
                <span className={`w-2 h-2 rounded-full flex-shrink-0 ${turn.speaker === s ? "bg-[#1E3A8A]" : "bg-gray-300"}`} />
                {s}
                {turn.speaker === s && <span className="ml-auto text-[10px] text-gray-400">current</span>}
              </button>
            ))}
            {uniqueSpeakers.length >= 2 && (
              <>
                <div className="my-1 border-t border-gray-100" />
                <button
                  onMouseDown={() => onFlipFromHere(index)}
                  data-testid={`flip-from-here-${index}`}
                  className="w-full text-left px-3 py-1.5 hover:bg-amber-50 text-amber-700 font-medium transition-colors flex items-center gap-2"
                  title="Swap all speakers from this turn to the end"
                >
                  <ArrowLeftRight className="w-3 h-3 flex-shrink-0" />
                  Flip speakers from here
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {/* Turn text — editable by managers, selectable for splitting */}
      <div className="flex-1 min-w-0 relative group/turntext">
        {canEditSpeakers && isEditing ? (
          <div onMouseDown={e => e.stopPropagation()}>
            <textarea
              autoFocus
              value={editingTurnText}
              onChange={e => setEditingTurnText(e.target.value)}
              onKeyDown={e => {
                if (e.key === "Escape") onCancelTurnText();
                if ((e.ctrlKey || e.metaKey) && e.key === "Enter") onSaveTurnText(index);
              }}
              className="w-full text-sm text-gray-800 leading-relaxed border border-blue-300 rounded-md px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-200 resize-none bg-white"
              rows={Math.max(2, Math.ceil(editingTurnText.length / 80))}
              data-testid={`turn-text-edit-${index}`}
            />
            <div className="flex items-center gap-1.5 mt-1.5">
              <button
                onMouseDown={e => { e.preventDefault(); onSaveTurnText(index); }}
                className="flex items-center gap-1 text-xs px-2.5 py-1 bg-[#1E3A8A] text-white rounded hover:bg-[#1E40AF] transition-colors"
                data-testid={`turn-text-save-${index}`}
              >
                <Check className="w-3 h-3" /> Save
              </button>
              <button
                onMouseDown={e => { e.preventDefault(); onCancelTurnText(); }}
                className="text-xs px-2.5 py-1 border border-gray-200 text-gray-600 rounded hover:bg-gray-50 transition-colors"
                data-testid={`turn-text-cancel-${index}`}
              >
                Cancel
              </button>
              <span className="text-xs text-gray-400 hidden sm:inline">Ctrl+Enter · Esc to cancel</span>
            </div>
          </div>
        ) : (
          <div className="relative" ref={isHighlighted ? highlightRef : null}>
            <p
              data-turn-index={index}
              className={`text-sm text-gray-800 leading-relaxed select-text cursor-text pr-5 transition-colors duration-300 ${
                isHighlighted ? "rounded px-1 -mx-1 bg-yellow-50 ring-1 ring-yellow-300" : ""
              }`}
            >
              {findReplaceOpen && findQueryTrimmed && turnMatches
                ? <MultiHighlightText text={turn.text} matches={turnMatches} currentGlobalIdx={findMatchIdx} />
                : isHighlighted
                ? <HighlightedText text={turn.text} query={effectiveHighlightQuery} />
                : turn.text}
            </p>
            {canEditSpeakers && (
              <button
                onMouseDown={e => {
                  e.stopPropagation();
                  onStartEdit(index, turn.text);
                }}
                className="absolute top-0 right-0 opacity-0 group-hover/turntext:opacity-100 transition-opacity text-gray-400 hover:text-gray-700 p-0.5 rounded hover:bg-white/80"
                data-testid={`turn-text-edit-btn-${index}`}
                title="Edit turn text"
              >
                <Pencil className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

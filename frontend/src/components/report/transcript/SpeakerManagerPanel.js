import React, { useState, useEffect, useMemo } from "react";
import { Loader2, ArrowLeftRight, ChevronUp, ChevronDown, RotateCcw } from "lucide-react";

// ── Speaker Manager Panel ────────────────────────────────────────────────────
export function SpeakerManagerPanel({ localTurns, onRenameAll, onSwapAll, onSave, onDiscard, onReset, onRestoreBackup, saving, isDirty, lastEditedBy, lastEditedAt, backupBy, backupAt }) {
  const speakerCounts = useMemo(() => {
    const counts = {};
    for (const t of localTurns) counts[t.speaker] = (counts[t.speaker] || 0) + 1;
    return counts;
  }, [localTurns]);

  const uniqueSpeakers = Object.keys(speakerCounts);
  const canSwap = uniqueSpeakers.length === 2;
  const [collapsed, setCollapsed] = useState(false);

  // Staging: temporary rename values before committing to localTurns
  const [staged, setStaged] = useState({});
  useEffect(() => { setStaged({}); }, [localTurns.length]);

  const applyRename = (original) => {
    const newName = (staged[original] || "").trim();
    if (newName && newName !== original) {
      onRenameAll(original, newName);
      setStaged(prev => { const n = { ...prev }; delete n[original]; return n; });
    } else {
      setStaged(prev => { const n = { ...prev }; delete n[original]; return n; });
    }
  };

  return (
    <div className="bg-gray-50 border-b border-gray-200" data-testid="speaker-manager-panel">
      {/* Always-visible header row */}
      <div className="flex items-center justify-between px-5 py-3">
        <div className="flex items-center gap-2.5 flex-wrap min-w-0">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide flex-shrink-0">Speaker Labels</p>
          {collapsed && uniqueSpeakers.map(s => (
            <span key={s} className="text-xs px-2 py-0.5 bg-white border border-gray-200 text-gray-600 rounded-full">
              {staged[s] ?? s}
            </span>
          ))}
          {lastEditedBy && !isDirty && (
            <span className="text-xs text-gray-400 italic" data-testid="speaker-last-edited-badge">
              Last saved by {lastEditedBy}
              {lastEditedAt ? ` · ${new Date(lastEditedAt).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}` : ""}
            </span>
          )}
        </div>
        <button
          onClick={() => setCollapsed(c => !c)}
          className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-700 transition-colors flex-shrink-0 ml-3"
          data-testid="toggle-speaker-panel"
        >
          {collapsed
            ? <><ChevronDown className="w-3.5 h-3.5" /> Expand</>
            : <><ChevronUp className="w-3.5 h-3.5" /> Minimise</>}
        </button>
      </div>

      {/* Collapsible body */}
      {!collapsed && (
        <div className="px-5 pb-4">
          <div className="flex items-start gap-4">
            <div className="flex-1 min-w-0">
              <div className="flex flex-col gap-2.5">
                {uniqueSpeakers.map(speaker => (
                  <div key={speaker} className="flex items-center gap-2 flex-wrap">
                    <input
                      className="text-xs font-semibold px-2.5 py-1.5 rounded border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-200 focus:outline-none w-44 bg-white"
                      value={staged[speaker] ?? speaker}
                      onChange={e => setStaged(prev => ({ ...prev, [speaker]: e.target.value }))}
                      onBlur={() => applyRename(speaker)}
                      onKeyDown={e => { if (e.key === "Enter") { e.target.blur(); } }}
                      placeholder="Enter label…"
                      data-testid={`speaker-rename-${speaker.replace(/\s/g, "-")}`}
                    />
                    <span className="text-xs text-gray-400">
                      {speakerCounts[speaker]} turn{speakerCounts[speaker] !== 1 ? "s" : ""}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            <div className="flex flex-col gap-2 flex-shrink-0">
              {canSwap && (
                <button
                  onClick={onSwapAll}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-gray-200 bg-white text-gray-600 hover:bg-gray-100 transition-colors"
                  data-testid="swap-speakers-btn"
                  title="Swap all speaker labels"
                >
                  <ArrowLeftRight className="w-3.5 h-3.5" />
                  Swap all
                </button>
              )}
              {isDirty && (
                <>
                  <button
                    onClick={() => onSave(staged)}
                    disabled={saving}
                    className="flex items-center justify-center gap-1.5 text-xs px-3 py-1.5 rounded bg-[#1E3A8A] text-white hover:bg-[#1E40AF] transition-colors disabled:opacity-60"
                    data-testid="save-speaker-map-btn"
                  >
                    {saving && <Loader2 className="w-3 h-3 animate-spin" />}
                    Save
                  </button>
                  <button
                    onClick={onDiscard}
                    className="text-xs px-3 py-1.5 rounded border border-gray-200 bg-white text-gray-600 hover:bg-gray-50 transition-colors"
                    data-testid="discard-speaker-map-btn"
                  >
                    Discard
                  </button>
                </>
              )}
              {!isDirty && lastEditedBy && onReset && (
                <button
                  onClick={onReset}
                  className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded border border-red-200 text-red-500 hover:bg-red-50 transition-colors mt-1"
                  data-testid="reset-speaker-labels-btn"
                  title="Clear edited speaker labels and restore full raw transcript"
                >
                  <RotateCcw className="w-3 h-3" />
                  Reset
                </button>
              )}
              {!isDirty && backupBy && onRestoreBackup && (
                <button
                  onClick={onRestoreBackup}
                  className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded border border-amber-300 text-amber-700 hover:bg-amber-50 transition-colors mt-1"
                  data-testid="restore-backup-btn"
                  title={`Restore previous save by ${backupBy}${backupAt ? ` at ${new Date(backupAt).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}` : ""}`}
                >
                  <RotateCcw className="w-3 h-3" />
                  Restore previous save
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

import React, { useState, useEffect, useCallback, useRef } from "react";
import { FileText, Users, Loader, Pencil } from "lucide-react";
import axios from "axios";
import { anonymiseTranscript } from "@/utils/anonymise";

const API = process.env.REACT_APP_BACKEND_URL;

function formatTranscript(text) {
  if (!text) return [];
  const lines = text.split(/\n+/).map(l => l.trim()).filter(Boolean);
  if (lines.length > 2) return lines;
  const sentences = text.match(/[^.!?]+[.!?]+["']?\s*/g) || [text];
  const paragraphs = [];
  for (let i = 0; i < sentences.length; i += 3) {
    const chunk = sentences.slice(i, i + 3).join("").trim();
    if (chunk) paragraphs.push(chunk);
  }
  return paragraphs.length ? paragraphs : [text];
}

function parseSpeakerText(text) {
  if (!text) return [];
  const turns = [];
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const match = trimmed.match(/^([^:]{1,50}):\s*(.+)/);
    if (match) {
      turns.push({ speaker: match[1].trim(), text: match[2].trim() });
    } else if (turns.length > 0) {
      turns[turns.length - 1].text += " " + trimmed;
    } else {
      turns.push({ speaker: "Speaker", text: trimmed });
    }
  }
  return turns;
}

function serializeTurns(turns) {
  return turns.map(t => `${t.speaker}: ${t.text}`).join("\n");
}

function getSpeakerStyle(speaker, managerName) {
  const s = speaker.toLowerCase();
  const mn = (managerName || "").toLowerCase();
  const isManager =
    s === "manager" ||
    s === "supervisor" ||
    (mn && mn.split(" ").filter(w => w.length > 2).some(w => s.includes(w)));
  return isManager
    ? { pill: "bg-[#1E3A8A] text-white", row: "border-blue-100 bg-blue-50/40" }
    : { pill: "bg-emerald-700 text-white", row: "border-emerald-100 bg-emerald-50/40" };
}

export function TranscriptTab({ meeting, onAnonymise, canAnonymise, onSpeakerTextGenerated }) {
  const [viewMode, setViewMode] = useState("full");
  const [selectionText, setSelectionText] = useState("");
  const [popupPos, setPopupPos] = useState(null);
  const [generating, setGenerating] = useState(false);

  // Speaker correction state
  const [editedTurns, setEditedTurns] = useState(null); // null = no edits yet
  const [editingIdx, setEditingIdx] = useState(null);
  const [saving, setSaving] = useState(false);
  const inputRef = useRef(null);

  const hasSpeakerText = Boolean(meeting.transcript?.speaker_text);
  const originalTurns = hasSpeakerText ? parseSpeakerText(meeting.transcript.speaker_text) : [];
  const workingTurns = editedTurns || originalTurns;
  const hasChanges = editedTurns !== null &&
    serializeTurns(editedTurns) !== meeting.transcript?.speaker_text;

  const managerName = meeting.sign_off_manager_name || "";
  const workerName = meeting.attendees?.length === 1 ? meeting.attendees[0].name : "";

  // Quick-pick labels for the inline editor
  const quickLabels = [
    managerName || "Manager",
    workerName || "Worker",
    "Speaker",
  ].filter((v, i, a) => a.indexOf(v) === i);

  // Default to speaker view when available
  useEffect(() => {
    if (hasSpeakerText) setViewMode("speaker");
  }, [hasSpeakerText]);

  // Focus the input when entering edit mode
  useEffect(() => {
    if (editingIdx !== null && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editingIdx]);

  const startEditing = (idx) => {
    if (!editedTurns) setEditedTurns(originalTurns.map(t => ({ ...t })));
    setEditingIdx(idx);
  };

  const commitEdit = () => setEditingIdx(null);

  const updateSpeakerLabel = (idx, newLabel) => {
    setEditedTurns(prev =>
      (prev || originalTurns.map(t => ({ ...t }))).map((t, j) =>
        j === idx ? { ...t, speaker: newLabel } : t
      )
    );
  };

  const discardChanges = () => {
    setEditedTurns(null);
    setEditingIdx(null);
  };

  const saveSpeakerCorrections = async () => {
    if (!editedTurns) return;
    setSaving(true);
    try {
      const token = localStorage.getItem("token");
      const newText = serializeTurns(editedTurns);
      await axios.patch(
        `${API}/api/review/${meeting.id}/speaker-text`,
        { speaker_text: newText },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (onSpeakerTextGenerated) onSpeakerTextGenerated(newText);
      setEditedTurns(null);
      setEditingIdx(null);
    } catch (e) {
      alert(e?.response?.data?.detail || "Failed to save corrections. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const generateSpeakerView = async () => {
    setGenerating(true);
    try {
      const token = localStorage.getItem("token");
      const res = await axios.post(
        `${API}/api/processing/${meeting.id}/diarize`,
        {},
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (onSpeakerTextGenerated) onSpeakerTextGenerated(res.data.speaker_text);
      setEditedTurns(null);
      setViewMode("speaker");
    } catch (e) {
      alert(e?.response?.data?.detail || "Failed to generate speaker view. Please try again.");
    } finally {
      setGenerating(false);
    }
  };

  const handleMouseUp = useCallback(() => {
    if (!canAnonymise || viewMode !== "full") return;
    const sel = window.getSelection();
    const text = sel?.toString().trim();
    if (!text || text.length < 2) { setSelectionText(""); setPopupPos(null); return; }
    const range = sel.getRangeAt(0);
    const rect = range.getBoundingClientRect();
    setSelectionText(text);
    setPopupPos({ top: Math.max(10, rect.top - 44), left: rect.left + rect.width / 2 });
  }, [canAnonymise, viewMode]);

  useEffect(() => {
    const clearPopup = (e) => {
      if (e.target.closest("[data-anonymise-btn]")) return;
      setSelectionText(""); setPopupPos(null);
    };
    document.addEventListener("mousedown", clearPopup);
    return () => document.removeEventListener("mousedown", clearPopup);
  }, []);

  const handleAnonymise = () => {
    if (!selectionText || !onAnonymise) return;
    onAnonymise(selectionText);
    setSelectionText(""); setPopupPos(null);
    window.getSelection()?.removeAllRanges();
  };

  const raw = anonymiseTranscript(meeting.transcript?.text, meeting.attendees || []);
  const wordCount = raw ? raw.trim().split(/\s+/).filter(Boolean).length : 0;
  const readMins = Math.ceil(wordCount / 150);

  return (
    <div data-testid="transcript-view">
      {/* Header row */}
      <div className="flex items-start gap-2 mb-4">
        <div className="flex-1 bg-amber-50 border border-amber-200 rounded-md p-3 flex items-center gap-2">
          <FileText className="w-4 h-4 text-amber-600 flex-shrink-0" />
          <p className="text-xs text-amber-700 flex-1">
            {viewMode === "speaker"
              ? "Click any speaker label to correct it. Switch to Full Text to anonymise names."
              : canAnonymise
              ? "Highlight any name and click Anonymise to replace it with an initial."
              : "Transcript is read-only. Use the Evidence tab to edit summaries and evidence wording."}
          </p>
        </div>
        {hasSpeakerText ? (
          <div className="flex rounded-md border border-gray-200 overflow-hidden flex-shrink-0 text-xs font-medium">
            <button
              className={`px-3 py-2 transition-colors ${viewMode === "full" ? "bg-[#1E3A8A] text-white" : "bg-white text-gray-600 hover:bg-gray-50"}`}
              onClick={() => setViewMode("full")}
              data-testid="transcript-full-btn"
            >
              Full Text
            </button>
            <button
              className={`px-3 py-2 flex items-center gap-1.5 transition-colors ${viewMode === "speaker" ? "bg-[#1E3A8A] text-white" : "bg-white text-gray-600 hover:bg-gray-50"}`}
              onClick={() => setViewMode("speaker")}
              data-testid="transcript-speaker-btn"
            >
              <Users className="w-3.5 h-3.5" />
              Speaker View
            </button>
          </div>
        ) : raw ? (
          <button
            onClick={generateSpeakerView}
            disabled={generating}
            className="flex-shrink-0 flex items-center gap-1.5 px-3 py-2 rounded-md border border-blue-200 bg-blue-50 text-blue-700 text-xs font-medium hover:bg-blue-100 transition-colors disabled:opacity-60"
            data-testid="generate-speaker-btn"
          >
            {generating ? <Loader className="w-3.5 h-3.5 animate-spin" /> : <Users className="w-3.5 h-3.5" />}
            {generating ? "Identifying…" : "Identify Speakers"}
          </button>
        ) : null}
      </div>

      {/* Transcript body */}
      <div
        className="bg-white border border-gray-200 rounded-lg shadow-sm overflow-hidden"
        onMouseUp={handleMouseUp}
        data-testid="transcript-text"
      >
        {/* Word count bar */}
        {raw && (
          <div className="flex items-center gap-3 px-5 py-2.5 border-b border-gray-100 text-xs text-gray-400">
            <span data-testid="word-count">{wordCount.toLocaleString()} words</span>
            <span className="text-gray-200">·</span>
            <span>~{readMins} min read</span>
            {hasSpeakerText && viewMode === "speaker" && (
              <>
                <span className="text-gray-200">·</span>
                <span className="text-blue-500">Speaker identified</span>
              </>
            )}
          </div>
        )}

        {!raw ? (
          <p className="p-5 text-sm text-gray-400 italic">Transcript not available.</p>
        ) : viewMode === "speaker" && hasSpeakerText ? (
          // ── Speaker view with inline label editing ───────────────────────────
          <>
            <div className="divide-y divide-gray-100" data-testid="speaker-view">
              {workingTurns.map((turn, i) => {
                const style = getSpeakerStyle(turn.speaker, managerName);
                const isEditing = editingIdx === i;
                const isChanged = editedTurns && editedTurns[i]?.speaker !== originalTurns[i]?.speaker;

                return (
                  <div key={i} className={`flex gap-3 px-5 py-3.5 ${style.row}`}>
                    {isEditing ? (
                      // ── Inline edit mode ────────────────────────────────────
                      <div className="flex-shrink-0 flex flex-col gap-1.5 mt-0.5 w-32" data-testid={`speaker-edit-${i}`}>
                        <input
                          ref={inputRef}
                          className="text-xs font-semibold px-2 py-1 rounded border border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400 w-full"
                          value={(editedTurns || originalTurns)[i]?.speaker || ""}
                          onChange={e => updateSpeakerLabel(i, e.target.value)}
                          onBlur={commitEdit}
                          onKeyDown={e => {
                            if (e.key === "Enter") commitEdit();
                            if (e.key === "Escape") { discardChanges(); setEditingIdx(null); }
                          }}
                          data-testid={`speaker-input-${i}`}
                        />
                        <div className="flex flex-wrap gap-1">
                          {quickLabels.map(label => (
                            <button
                              key={label}
                              className="text-xs px-1.5 py-0.5 bg-gray-100 hover:bg-gray-200 rounded transition-colors leading-none"
                              onMouseDown={e => {
                                e.preventDefault();
                                updateSpeakerLabel(i, label);
                                setEditingIdx(null);
                              }}
                              data-testid={`quick-label-${label.replace(/\s/g,"-")}`}
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                      </div>
                    ) : (
                      // ── Display mode (clickable pill) ───────────────────────
                      <button
                        className={`group inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full flex-shrink-0 mt-0.5 h-fit transition-opacity hover:opacity-80 ${style.pill} ${isChanged ? "ring-2 ring-offset-1 ring-amber-400" : ""}`}
                        onClick={() => startEditing(i)}
                        title="Click to edit speaker label"
                        data-testid={`speaker-pill-${i}`}
                      >
                        {turn.speaker}
                        <Pencil className="w-2.5 h-2.5 opacity-50 group-hover:opacity-100 transition-opacity" />
                      </button>
                    )}
                    <p className="text-sm text-gray-800 leading-relaxed">{turn.text}</p>
                  </div>
                );
              })}
            </div>

            {/* Save / discard bar */}
            {hasChanges && (
              <div className="flex items-center justify-between px-5 py-3 bg-amber-50 border-t border-amber-200" data-testid="speaker-save-bar">
                <span className="text-xs text-amber-700 font-medium">Unsaved speaker corrections</span>
                <div className="flex gap-2">
                  <button
                    onClick={discardChanges}
                    className="text-xs px-3 py-1.5 rounded border border-gray-200 bg-white text-gray-600 hover:bg-gray-50 transition-colors"
                    data-testid="discard-corrections-btn"
                  >
                    Discard
                  </button>
                  <button
                    onClick={saveSpeakerCorrections}
                    disabled={saving}
                    className="text-xs px-3 py-1.5 rounded bg-[#1E3A8A] text-white hover:bg-[#1E40AF] transition-colors disabled:opacity-60 flex items-center gap-1.5"
                    data-testid="save-corrections-btn"
                  >
                    {saving && <Loader className="w-3 h-3 animate-spin" />}
                    Save corrections
                  </button>
                </div>
              </div>
            )}
          </>
        ) : (
          // ── Full text view ────────────────────────────────────────────────
          <div className="p-5">
            {formatTranscript(raw).map((para, i) => (
              <p key={i} className="text-sm text-gray-700 leading-relaxed mb-3 last:mb-0">
                {para}
              </p>
            ))}
          </div>
        )}
      </div>

      {/* Anonymise popup (full text mode only) */}
      {popupPos && selectionText && viewMode === "full" && (
        <div
          data-anonymise-btn="true"
          style={{ position: "fixed", top: popupPos.top, left: popupPos.left, transform: "translateX(-50%)", zIndex: 9999 }}
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

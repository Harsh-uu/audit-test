import React, { useState, useEffect, useCallback, useMemo } from "react";
import { FileText, Users, Loader, ArrowLeftRight } from "lucide-react";
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
    s === "manager" || s === "supervisor" ||
    (mn && mn.split(" ").filter(w => w.length > 2).some(w => s.includes(w)));
  return isManager
    ? { pill: "bg-[#1E3A8A] text-white", row: "bg-blue-50/40" }
    : { pill: "bg-emerald-700 text-white", row: "bg-emerald-50/40" };
}

// ── Speaker Manager Panel ────────────────────────────────────────────────────
function SpeakerManagerPanel({ turns, speakerMap, onChange, onSwap, onSave, onDiscard, saving, hasChanges }) {
  const speakerCounts = useMemo(() => {
    const counts = {};
    for (const t of turns) counts[t.speaker] = (counts[t.speaker] || 0) + 1;
    return counts;
  }, [turns]);

  const uniqueSpeakers = Object.keys(speakerCounts);
  const canSwap = uniqueSpeakers.length === 2;

  return (
    <div className="px-5 py-4 bg-gray-50 border-b border-gray-200" data-testid="speaker-manager-panel">
      <div className="flex items-start gap-4">
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
            Detected Speakers
          </p>
          <div className="flex flex-col gap-2.5">
            {uniqueSpeakers.map(original => (
              <div key={original} className="flex items-center gap-2 flex-wrap">
                <span className="text-xs text-gray-400 font-mono w-24 truncate" title={original}>
                  {original}
                </span>
                <span className="text-gray-300 text-xs">→</span>
                <input
                  className="text-xs font-semibold px-2.5 py-1.5 rounded border border-gray-200 focus:border-blue-400 focus:ring-1 focus:ring-blue-200 focus:outline-none w-40 bg-white"
                  value={speakerMap[original] ?? original}
                  onChange={e => onChange(original, e.target.value)}
                  placeholder="Enter label…"
                  data-testid={`speaker-rename-${original.replace(/\s/g, "-")}`}
                />
                <span className="text-xs text-gray-400">
                  {speakerCounts[original]} turn{speakerCounts[original] !== 1 ? "s" : ""}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-2 flex-shrink-0 mt-6">
          {canSwap && (
            <button
              onClick={onSwap}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-gray-200 bg-white text-gray-600 hover:bg-gray-100 transition-colors"
              data-testid="swap-speakers-btn"
              title="Swap all labels between the two speakers"
            >
              <ArrowLeftRight className="w-3.5 h-3.5" />
              Swap all
            </button>
          )}
          {hasChanges && (
            <>
              <button
                onClick={onSave}
                disabled={saving}
                className="flex items-center justify-center gap-1.5 text-xs px-3 py-1.5 rounded bg-[#1E3A8A] text-white hover:bg-[#1E40AF] transition-colors disabled:opacity-60"
                data-testid="save-speaker-map-btn"
              >
                {saving && <Loader className="w-3 h-3 animate-spin" />}
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
        </div>
      </div>
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────
export function TranscriptTab({ meeting, onAnonymise, canAnonymise, onSpeakerTextGenerated }) {
  const [viewMode, setViewMode] = useState("full");
  const [selectionText, setSelectionText] = useState("");
  const [popupPos, setPopupPos] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [speakerMap, setSpeakerMap] = useState(null);
  const [saving, setSaving] = useState(false);

  const hasSpeakerText = Boolean(meeting.transcript?.speaker_text);
  const originalTurns = useMemo(
    () => parseSpeakerText(meeting.transcript?.speaker_text || ""),
    [meeting.transcript?.speaker_text]
  );

  const managerName = meeting.sign_off_manager_name || "";

  // Build identity speakerMap whenever speaker_text changes
  useEffect(() => {
    if (originalTurns.length) {
      const map = {};
      for (const t of originalTurns) {
        if (!(t.speaker in map)) map[t.speaker] = t.speaker;
      }
      setSpeakerMap(map);
    }
  }, [meeting.transcript?.speaker_text]); // eslint-disable-line react-hooks/exhaustive-deps

  // Default to speaker view when speaker_text is present
  useEffect(() => {
    if (hasSpeakerText) setViewMode("speaker");
  }, [hasSpeakerText]);

  const hasChanges = speakerMap !== null &&
    Object.entries(speakerMap).some(([orig, renamed]) => orig !== renamed);

  const handleRename = (original, newLabel) =>
    setSpeakerMap(prev => ({ ...prev, [original]: newLabel }));

  const handleSwap = () => {
    if (!speakerMap) return;
    const keys = Object.keys(speakerMap);
    if (keys.length !== 2) return;
    setSpeakerMap({ [keys[0]]: speakerMap[keys[1]], [keys[1]]: speakerMap[keys[0]] });
  };

  const handleDiscard = () => {
    const map = {};
    for (const t of originalTurns) {
      if (!(t.speaker in map)) map[t.speaker] = t.speaker;
    }
    setSpeakerMap(map);
  };

  const handleSave = async () => {
    if (!speakerMap) return;
    setSaving(true);
    try {
      const token = localStorage.getItem("supervision_token");
      const newText = serializeTurns(
        originalTurns.map(t => ({ ...t, speaker: speakerMap[t.speaker] ?? t.speaker }))
      );
      await axios.patch(
        `${API}/api/review/${meeting.id}/speaker-text`,
        { speaker_text: newText },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (onSpeakerTextGenerated) onSpeakerTextGenerated(newText);
      // speakerMap resets via the useEffect above when speaker_text prop updates
    } catch (e) {
      alert(e?.response?.data?.detail || "Failed to save speaker labels. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const generateSpeakerView = async () => {
    setGenerating(true);
    try {
      const token = localStorage.getItem("supervision_token");
      const res = await axios.post(
        `${API}/api/processing/${meeting.id}/diarize`,
        {},
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (onSpeakerTextGenerated) onSpeakerTextGenerated(res.data.speaker_text);
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
    const clear = (e) => {
      if (e.target.closest("[data-anonymise-btn]")) return;
      setSelectionText(""); setPopupPos(null);
    };
    document.addEventListener("mousedown", clear);
    return () => document.removeEventListener("mousedown", clear);
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
              ? "Rename or swap speakers above the transcript, then Save. Switch to Full Text to anonymise names."
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
          <>
            {/* Speaker manager panel */}
            {speakerMap && (
              <SpeakerManagerPanel
                turns={originalTurns}
                speakerMap={speakerMap}
                onChange={handleRename}
                onSwap={handleSwap}
                onSave={handleSave}
                onDiscard={handleDiscard}
                saving={saving}
                hasChanges={hasChanges}
              />
            )}

            {/* Turns */}
            <div className="divide-y divide-gray-100" data-testid="speaker-view">
              {originalTurns.map((turn, i) => {
                const displaySpeaker = speakerMap?.[turn.speaker] ?? turn.speaker;
                const style = getSpeakerStyle(displaySpeaker, managerName);
                return (
                  <div key={i} className={`flex gap-3 px-5 py-3.5 ${style.row}`}>
                    <span
                      className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full flex-shrink-0 mt-0.5 h-fit ${style.pill}`}
                      data-testid={`speaker-pill-${i}`}
                    >
                      {displaySpeaker}
                    </span>
                    <p className="text-sm text-gray-800 leading-relaxed">{turn.text}</p>
                  </div>
                );
              })}
            </div>
          </>
        ) : (
          <div className="p-5">
            {formatTranscript(raw).map((para, i) => (
              <p key={i} className="text-sm text-gray-700 leading-relaxed mb-3 last:mb-0">
                {para}
              </p>
            ))}
          </div>
        )}
      </div>

      {/* Anonymise popup */}
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

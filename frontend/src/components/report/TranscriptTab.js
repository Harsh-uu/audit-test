import React, { useState, useEffect, useCallback } from "react";
import { FileText, Users, Loader } from "lucide-react";
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

  const hasSpeakerText = Boolean(meeting.transcript?.speaker_text);

  // Default to speaker view when available
  useEffect(() => {
    if (hasSpeakerText) setViewMode("speaker");
  }, [hasSpeakerText]);

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
    if (!text || text.length < 2) {
      setSelectionText("");
      setPopupPos(null);
      return;
    }
    const range = sel.getRangeAt(0);
    const rect = range.getBoundingClientRect();
    setSelectionText(text);
    setPopupPos({ top: Math.max(10, rect.top - 44), left: rect.left + rect.width / 2 });
  }, [canAnonymise, viewMode]);

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

  const raw = anonymiseTranscript(meeting.transcript?.text, meeting.attendees || []);
  const wordCount = raw ? raw.trim().split(/\s+/).filter(Boolean).length : 0;
  const readMins = Math.ceil(wordCount / 150);
  const managerName = meeting.sign_off_manager_name || "";

  return (
    <div data-testid="transcript-view">
      {/* Header row: info banner + view toggle / generate button */}
      <div className="flex items-start gap-2 mb-4">
        <div className="flex-1 bg-amber-50 border border-amber-200 rounded-md p-3 flex items-center gap-2">
          <FileText className="w-4 h-4 text-amber-600 flex-shrink-0" />
          <p className="text-xs text-amber-700 flex-1">
            {viewMode === "speaker"
              ? "Speaker view shows AI-identified turns. Switch to Full Text to anonymise."
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
        className="bg-white border border-gray-200 rounded-lg shadow-sm"
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
        ) : viewMode === "speaker" && meeting.transcript?.speaker_text ? (
          // ── Speaker view ────────────────────────────────────────────────────
          <div className="divide-y divide-gray-100" data-testid="speaker-view">
            {parseSpeakerText(meeting.transcript.speaker_text).map((turn, i) => {
              const style = getSpeakerStyle(turn.speaker, managerName);
              return (
                <div key={i} className={`flex gap-3 px-5 py-3.5 ${style.row}`}>
                  <span className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full flex-shrink-0 mt-0.5 h-fit ${style.pill}`}>
                    {turn.speaker}
                  </span>
                  <p className="text-sm text-gray-800 leading-relaxed">{turn.text}</p>
                </div>
              );
            })}
          </div>
        ) : (
          // ── Full text view ───────────────────────────────────────────────────
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

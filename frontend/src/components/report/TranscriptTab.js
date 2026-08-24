import React, { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { FileText, Users, Loader2, ArrowLeftRight, Scissors, ChevronUp, ChevronDown, Pencil, Check, RotateCcw, Search, X } from "lucide-react";
import axios from "axios";
import { toast } from "sonner";
import { anonymiseTranscript } from "@/utils/anonymise";
import { useAuth } from "@/context/AuthContext";

/** Strip leading/trailing curly quotes and truncate for searching */
function cleanExcerpt(excerpt) {
  return (excerpt || "")
    .replace(/^[\u201C\u201D\u2018\u2019"']+|[\u201C\u201D\u2018\u2019"']+$/g, "")
    .trim()
    .slice(0, 120);
}

/**
 * Find the best searchable substring of an excerpt within text.
 * First tries the full cleaned excerpt; if not found, falls back to
 * progressively shorter word-prefix matches (10 → 8 → 6 → 4 words).
 * This handles cases where the AI paraphrases a quote very slightly.
 * Returns the matched string, or "" if nothing was found.
 */
function resolveExcerptQuery(text, excerpt) {
  // Strip [MM:SS] timestamp and optional "SpeakerName: " prefix the AI may have included
  const cleaned = cleanExcerpt(excerpt)
    .replace(/^\[\d{1,2}:\d{2}\]\s*/, "")
    .replace(/^[^:]{1,50}:\s*/, "");
  if (!cleaned) return "";
  const tLower = text.toLowerCase();

  if (tLower.includes(cleaned.toLowerCase())) return cleaned;

  const words = cleaned.split(/\s+/).filter(Boolean);
  for (const n of [10, 8, 6, 4]) {
    if (words.length <= n) continue;
    const partial = words.slice(0, n).join(" ");
    if (tLower.includes(partial.toLowerCase())) return partial;
  }

  if (words.length >= 4) {
    const partial = words.slice(0, 4).join(" ");
    if (tLower.includes(partial.toLowerCase())) return partial;
  }

  return "";
}

/** Render text with a highlighted substring */
function HighlightedText({ text, query }) {
  if (!query) return <>{text}</>;
  const q = cleanExcerpt(query).toLowerCase();
  if (!q) return <>{text}</>;
  const idx = text.toLowerCase().indexOf(q);
  if (idx === -1) return <>{text}</>;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="bg-yellow-200 text-gray-900 rounded-sm px-0.5 not-italic">{text.slice(idx, idx + q.length)}</mark>
      {text.slice(idx + q.length)}
    </>
  );
}

/** Escape special regex chars */
function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Render text with multiple highlighted spans — supports current (amber) + other (yellow) */
function MultiHighlightText({ text, matches, currentGlobalIdx }) {
  if (!matches || !matches.length) return <>{text}</>;
  const parts = [];
  let last = 0;
  for (const { start, end, globalIdx } of matches) {
    if (start > last) parts.push(<span key={`t${last}`}>{text.slice(last, start)}</span>);
    const isCurrent = globalIdx === currentGlobalIdx;
    parts.push(
      <mark
        key={`m${globalIdx}`}
        data-find-match={isCurrent ? "current" : undefined}
        className={`rounded-sm px-0.5 not-italic transition-colors ${
          isCurrent ? "bg-orange-300 text-gray-900 ring-1 ring-orange-400" : "bg-yellow-200 text-gray-900"
        }`}
      >
        {text.slice(start, end)}
      </mark>
    );
    last = end;
  }
  if (last < text.length) parts.push(<span key="tail">{text.slice(last)}</span>);
  return <>{parts}</>;
}

const API = "/api";

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
    // Extract optional [MM:SS] timestamp prefix
    const tsMatch = trimmed.match(/^\[(\d{1,2}:\d{2})\]\s+(.+)/);
    const timestamp = tsMatch ? tsMatch[1] : null;
    const rest = tsMatch ? tsMatch[2] : trimmed;
    const match = rest.match(/^([^:]{1,50}):\s*(.+)/);
    if (match) {
      turns.push({ speaker: match[1].trim(), text: match[2].trim(), timestamp });
    } else if (turns.length > 0) {
      turns[turns.length - 1].text += " " + rest;
    } else {
      turns.push({ speaker: "Speaker", text: rest, timestamp });
    }
  }
  return turns;
}

function serializeTurns(turns) {
  return turns.map(t => t.timestamp ? `[${t.timestamp}] ${t.speaker}: ${t.text}` : `${t.speaker}: ${t.text}`).join("\n");
}

function getSpeakerRole(speaker, managerName) {
  const s = speaker.toLowerCase();
  const mn = (managerName || "").toLowerCase();
  const isManager =
    s === "manager" || s === "supervisor" ||
    (mn && mn.split(" ").filter(w => w.length > 2).some(w => s.includes(w)));
  return isManager ? "manager" : "worker";
}

function roleToStyle(role) {
  return role === "manager"
    ? { pill: "bg-[#1E3A8A] text-white", row: "bg-blue-50/40" }
    : { pill: "bg-emerald-700 text-white", row: "bg-emerald-50/40" };
}

// ── Speaker colour palette — pastel / -300 range ─────────────────────────────
const SPEAKER_PALETTE = [
  "#93C5FD",  // blue-300
  "#C4B5FD",  // violet-300
  "#6EE7B7",  // emerald-300
  "#FCA5A5",  // red-300
  "#FCD34D",  // amber-300
  "#67E8F9",  // cyan-300
  "#F9A8D4",  // pink-300
  "#FDBA74",  // orange-300
  "#A5B4FC",  // indigo-300
  "#86EFAC",  // green-300
];

/** Return dark or white text based on background luminance */
function getContrastColor(hex) {
  if (!hex || hex.length < 7) return "#fff";
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return lum > 0.55 ? "#374151" : "#ffffff";
}

// ── Speaker Manager Panel ────────────────────────────────────────────────────
function SpeakerManagerPanel({ localTurns, onRenameAll, onSwapAll, onSave, onDiscard, onReset, onRestoreBackup, saving, isDirty, lastEditedBy, lastEditedAt, backupBy, backupAt, stagedColors, onColorChange }) {
  const speakerCounts = useMemo(() => {
    const counts = {};
    for (const t of localTurns) counts[t.speaker] = (counts[t.speaker] || 0) + 1;
    return counts;
  }, [localTurns]);

  const uniqueSpeakers = Object.keys(speakerCounts);
  const canSwap = uniqueSpeakers.length === 2;
  const [collapsed, setCollapsed] = useState(false);
  const [openColorPicker, setOpenColorPicker] = useState(null);

  // Close palette on click outside
  React.useEffect(() => {
    if (!openColorPicker) return;
    const handler = (e) => { if (!e.target.closest("[data-colorpicker]")) setOpenColorPicker(null); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [openColorPicker]);

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
                    {/* Colour swatch + palette picker */}
                    <div className="relative flex-shrink-0" data-colorpicker>
                      <button
                        type="button"
                        onClick={() => setOpenColorPicker(openColorPicker === speaker ? null : speaker)}
                        className="w-6 h-6 rounded-full border-2 border-white shadow ring-1 ring-gray-300 hover:ring-blue-400 transition-all flex-shrink-0"
                        style={{ backgroundColor: stagedColors?.[speaker] || "#6B7280" }}
                        title="Pick colour"
                        data-testid={`color-swatch-${speaker.replace(/\s/g, "-")}`}
                      />
                      {openColorPicker === speaker && (
                        <div className="absolute left-0 top-8 z-30 bg-white border border-gray-200 rounded-xl shadow-xl p-2.5 grid grid-cols-5 gap-1.5 w-max">
                          {SPEAKER_PALETTE.map(c => (
                            <button
                              key={c}
                              type="button"
                              data-colorpicker
                              onClick={() => { onColorChange(speaker, c); setOpenColorPicker(null); }}
                              className="w-6 h-6 rounded-full transition-transform hover:scale-125 focus:outline-none"
                              style={{
                                backgroundColor: c,
                                outline: stagedColors?.[speaker] === c ? `2px solid ${c}` : "none",
                                outlineOffset: "2px",
                              }}
                              title={c}
                            />
                          ))}
                        </div>
                      )}
                    </div>
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

// ── Main component ───────────────────────────────────────────────────────────
export const TranscriptTab = React.memo(function TranscriptTab({ meeting, onAnonymise, canAnonymise, canEditSpeakers = true, onSpeakerTextGenerated, onDirtyChange, highlightExcerpt = "", highlightKey = 0, onFindReplace }) {
  const { API, getAuthConfig } = useAuth();
  const [viewMode, setViewMode] = useState("full");

  // ── Speaker editing state ─────────────────────────────────────────────────
  const [localTurns, setLocalTurns] = useState([]);
  const [speakerRoleMap, setSpeakerRoleMap] = useState({}); // name → "manager"|"worker"
  const [isDirty, setIsDirty] = useState(false);
  // Ref mirrors isDirty so the useEffect always reads the latest value
  // even if a concurrent render has not yet committed the state update.
  const isDirtyRef = React.useRef(false);
  const setDirty = React.useCallback((val) => {
    isDirtyRef.current = val;
    setIsDirty(val);
  }, []);

  // Propagate dirty state to parent (MeetingReport) via effect — the React way
  useEffect(() => {
    if (onDirtyChange) onDirtyChange(isDirty);
  }, [isDirty]); // eslint-disable-line react-hooks/exhaustive-deps
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [openTurnMenu, setOpenTurnMenu] = useState(null);
  const [editingTurnIndex, setEditingTurnIndex] = useState(null);
  const [editingTurnText, setEditingTurnText] = useState("");

  // ── Find & Replace state ───────────────────────────────────────────────────
  const [findReplaceOpen, setFindReplaceOpen] = useState(false);
  const [findQuery, setFindQuery] = useState("");
  const [replaceWith, setReplaceWith] = useState("");
  const [findMatchIdx, setFindMatchIdx] = useState(0);
  const findInputRef = useRef(null);

  // ── Full-text anonymise popup ─────────────────────────────────────────────
  const [selectionText, setSelectionText] = useState("");
  const [popupPos, setPopupPos] = useState(null);

  // ── Split turn popup (Speaker View) ──────────────────────────────────────
  const [splitPopup, setSplitPopup] = useState(null);
  // { turnIndex, selStart, selEnd, selectedText, top, left }

  // ── Lazy full-text loading ────────────────────────────────────────────────
  // The main GET /meetings/{id} strips `transcript.text` (~50 KB) when
  // speaker_text is present. We fetch it on demand when the user switches to
  // the Full Text view.
  const [lazyRawText, setLazyRawText] = useState(null);   // null = not yet fetched
  const [rawTextLoading, setRawTextLoading] = useState(false);

  const fetchFullText = useCallback(async () => {
    if (rawTextLoading || lazyRawText !== null) return;
    setRawTextLoading(true);
    try {
      const { data } = await axios.get(
        `${API}/meetings/${meeting.id}/transcript-text`,
        getAuthConfig()
      );
      setLazyRawText(data.text || "");
    } catch {
      setLazyRawText("");   // prevent repeated retries
      toast.error("Could not load full transcript text.");
    } finally {
      setRawTextLoading(false);
    }
  }, [meeting.id, rawTextLoading, lazyRawText]); // eslint-disable-line

  // Trigger lazy fetch when the user switches to Full Text and text isn't inlined
  useEffect(() => {
    if (viewMode === "full" && !meeting.transcript?.text && lazyRawText === null) {
      fetchFullText();
    }
  }, [viewMode, meeting.transcript?.text, lazyRawText]); // eslint-disable-line

  const hasSpeakerText = Boolean(meeting.transcript?.speaker_text);
  const originalTurns = useMemo(
    () => parseSpeakerText(meeting.transcript?.speaker_text || ""),
    [meeting.transcript?.speaker_text]
  );

  const managerName = meeting.sign_off_manager_name || "";

  // Initialise / reset localTurns + role map when speaker_text changes
  useEffect(() => {
    // Use the ref (not state) to read isDirty — avoids stale-closure issues in
    // React 19 Concurrent Mode where the committed render may differ from the
    // render that enqueued setIsDirty(false) earlier in the same flush.
    if (isDirtyRef.current) return;
    const map = {};
    for (const t of originalTurns) {
      if (!(t.speaker in map)) {
        map[t.speaker] = getSpeakerRole(t.speaker, managerName);
      }
    }
    setSpeakerRoleMap(map);
    setLocalTurns(originalTurns.map(t => ({ ...t })));
  }, [meeting.transcript?.speaker_text]); // eslint-disable-line react-hooks/exhaustive-deps

  // Default to speaker view when speaker_text is present
  useEffect(() => {
    if (hasSpeakerText) setViewMode("speaker");
  }, [hasSpeakerText]);

  // ── Highlight / scroll-to-excerpt ─────────────────────────────────────────
  const highlightRef = useRef(null);

  const matchTurnIdx = useMemo(() => {
    if (!highlightExcerpt || !localTurns.length) return -1;
    return localTurns.findIndex(t => resolveExcerptQuery(t.text, highlightExcerpt) !== "");
  }, [highlightExcerpt, localTurns]);

  // For raw text mode — uses lazy-loaded text as fallback when the main response
  // stripped it (speaker_text present). Declared here so hooks below can reference it.
  const rawParas = useMemo(
    () => formatTranscript(meeting.transcript?.text || lazyRawText || ""),
    [meeting.transcript?.text, lazyRawText]
  );

  // What actually matched — may be a shorter word-prefix if the full excerpt wasn't verbatim.
  // Used to drive the yellow highlight so it renders on the right substring.
  const effectiveHighlightQuery = useMemo(() => {
    if (!highlightExcerpt) return "";
    if (hasSpeakerText && localTurns.length) {
      for (const turn of localTurns) {
        const q = resolveExcerptQuery(turn.text, highlightExcerpt);
        if (q) return q;
      }
      return "";
    }
    for (const para of rawParas) {
      const q = resolveExcerptQuery(para, highlightExcerpt);
      if (q) return q;
    }
    return "";
  }, [highlightExcerpt, localTurns, rawParas, hasSpeakerText]);

  // ── Find & Replace match computation ──────────────────────────────────────
  const findMatches = useMemo(() => {
    const q = findQuery.trim();
    if (!q) return [];
    const ql = q.toLowerCase();
    const matches = [];

    if (viewMode === "speaker" && localTurns.length) {
      localTurns.forEach((turn, turnIdx) => {
        const tl = turn.text.toLowerCase();
        let pos = 0, idx;
        while ((idx = tl.indexOf(ql, pos)) !== -1) {
          matches.push({ turnIdx, start: idx, end: idx + ql.length, type: "turn" });
          pos = idx + 1;
        }
      });
    } else {
      rawParas.forEach((para, paraIdx) => {
        const pl = para.toLowerCase();
        let pos = 0, idx;
        while ((idx = pl.indexOf(ql, pos)) !== -1) {
          matches.push({ paraIdx, start: idx, end: idx + ql.length, type: "para" });
          pos = idx + 1;
        }
      });
    }
    return matches;
  }, [findQuery, viewMode, localTurns, rawParas]);

  // Build per-turn / per-para match maps with globalIdx for multi-highlight rendering
  const turnMatchMap = useMemo(() => {
    const map = {};
    findMatches.forEach((m, gi) => {
      if (m.type === "turn") {
        if (!map[m.turnIdx]) map[m.turnIdx] = [];
        map[m.turnIdx].push({ start: m.start, end: m.end, globalIdx: gi });
      }
    });
    return map;
  }, [findMatches]);

  const paraMatchMap = useMemo(() => {
    const map = {};
    findMatches.forEach((m, gi) => {
      if (m.type === "para") {
        if (!map[m.paraIdx]) map[m.paraIdx] = [];
        map[m.paraIdx].push({ start: m.start, end: m.end, globalIdx: gi });
      }
    });
    return map;
  }, [findMatches]);
  const matchParaIdx = useMemo(() => {
    if (!highlightExcerpt || hasSpeakerText) return -1;
    return rawParas.findIndex(p => resolveExcerptQuery(p, highlightExcerpt) !== "");
  }, [highlightExcerpt, rawParas, hasSpeakerText]);

  useEffect(() => {
    const hasMatch = hasSpeakerText ? matchTurnIdx >= 0 : matchParaIdx >= 0;
    if (hasMatch && highlightRef.current) {
      setTimeout(() => {
        highlightRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 200);
    }
  }, [matchTurnIdx, matchParaIdx, highlightExcerpt, highlightKey]); // eslint-disable-line react-hooks/exhaustive-deps
  // ─────────────────────────────────────────────────────────────────────────

  // Close turn menu when clicking outside
  useEffect(() => {
    if (openTurnMenu === null) return;
    const close = () => setOpenTurnMenu(null);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [openTurnMenu]);

  // Close split popup when clicking outside
  useEffect(() => {
    if (!splitPopup) return;
    const close = () => setSplitPopup(null);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [splitPopup]);

  // Unique display speakers (for per-turn dropdown and flip-from-here)
  const uniqueSpeakers = useMemo(() => {
    const seen = new Set();
    return localTurns.map(t => t.speaker).filter(s => { if (seen.has(s)) return false; seen.add(s); return true; });
  }, [localTurns]);

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleRenameAll = useCallback((original, newName) => {
    setLocalTurns(prev => prev.map(t => t.speaker === original ? { ...t, speaker: newName } : t));
    setSpeakerRoleMap(prev => {
      if (!(original in prev)) return prev;
      const { [original]: role, ...rest } = prev;
      return { ...rest, [newName]: role };
    });
    setDirty(true);
  }, []);

  const handleSwapAll = useCallback(() => {
    if (uniqueSpeakers.length !== 2) return;
    const [a, b] = uniqueSpeakers;
    setLocalTurns(prev => prev.map(t => ({ ...t, speaker: t.speaker === a ? b : a })));
    setDirty(true);
  }, [uniqueSpeakers]);

  const handleTurnAssign = useCallback((index, newSpeaker) => {
    setLocalTurns(prev => prev.map((t, i) => i === index ? { ...t, speaker: newSpeaker } : t));
    setDirty(true);
    setOpenTurnMenu(null);
  }, []);

  const [pendingEditNotes, setPendingEditNotes] = useState([]);

  const handleFlipFromHere = useCallback((fromIndex) => {
    if (uniqueSpeakers.length < 2) return;
    const currentSpeaker = localTurns[fromIndex]?.speaker;
    if (!currentSpeaker) return;

    // With exactly 2 speakers use the only other one; with 3+ pick the most-common non-current speaker
    let otherSpeaker;
    if (uniqueSpeakers.length === 2) {
      otherSpeaker = uniqueSpeakers.find(s => s !== currentSpeaker);
    } else {
      const counts = {};
      for (const t of localTurns) {
        if (t.speaker !== currentSpeaker) counts[t.speaker] = (counts[t.speaker] || 0) + 1;
      }
      otherSpeaker = Object.keys(counts).sort((a, b) => counts[b] - counts[a])[0];
    }
    if (!otherSpeaker) return;

    setLocalTurns(prev => {
      const next = [...prev];
      for (let j = fromIndex; j < next.length; j++) {
        if (next[j].speaker === currentSpeaker) next[j] = { ...next[j], speaker: otherSpeaker };
        else if (next[j].speaker === otherSpeaker) next[j] = { ...next[j], speaker: currentSpeaker };
        // third-speaker turns are left unchanged
      }
      return next;
    });
    setPendingEditNotes(prev => [
      ...prev,
      `Speakers flipped from Turn ${fromIndex + 1} onwards: '${currentSpeaker}' \u2194 '${otherSpeaker}'`,
    ]);
    setDirty(true);
    setOpenTurnMenu(null);
  }, [uniqueSpeakers, localTurns]);

  // Split a turn at the text selection boundaries
  const handleSplitTurn = useCallback(() => {
    if (!splitPopup) return;
    const { turnIndex, selStart, selEnd } = splitPopup;
    const turn = localTurns[turnIndex];
    if (!turn) return;

    const before = turn.text.slice(0, selStart).trim();
    const selected = turn.text.slice(selStart, selEnd).trim();
    const after = turn.text.slice(selEnd).trim();

    const parts = [
      before ? { speaker: turn.speaker, text: before, timestamp: turn.timestamp } : null,
      selected ? { speaker: turn.speaker, text: selected } : null,
      after ? { speaker: turn.speaker, text: after } : null,
    ].filter(Boolean);

    if (parts.length <= 1) { setSplitPopup(null); return; }

    setLocalTurns(prev => {
      const next = [...prev];
      next.splice(turnIndex, 1, ...parts);
      return next;
    });
    setPendingEditNotes(prev => [
      ...prev,
      `Turn ${turnIndex + 1} split into ${parts.length} turns`,
    ]);
    setDirty(true);
    setSplitPopup(null);
    window.getSelection()?.removeAllRanges();
  }, [splitPopup, localTurns]);

  const handleDiscard = useCallback(() => {
    setLocalTurns(originalTurns.map(t => ({ ...t })));
    setDirty(false);
    setEditingTurnIndex(null);
    setEditingTurnText("");
    setPendingEditNotes([]);
  }, [originalTurns]); // eslint-disable-line react-hooks/exhaustive-deps

  const [stagedColors, setStagedColors] = useState(meeting.transcript?.speaker_colors || {});

  // Sync saved colors when meeting reloads (only when not dirty)
  React.useEffect(() => {
    if (isDirtyRef.current) return;
    setStagedColors(meeting.transcript?.speaker_colors || {});
  }, [meeting.transcript?.speaker_colors]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleColorChange = React.useCallback((speaker, color) => {
    setStagedColors(prev => ({ ...prev, [speaker]: color }));
    setDirty(true);
  }, [setDirty]);

  const handleRestoreBackup = async () => {
    const backupBy = meeting.transcript?.speaker_text_backup_by;
    const backupAt = meeting.transcript?.speaker_text_backup_at;
    const label = backupBy ? ` (saved by ${backupBy}${backupAt ? ` at ${new Date(backupAt).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}` : ""})` : "";
    if (!window.confirm(`Restore the previous version of speaker labels${label}? This will overwrite the current labels.`)) return;
    try {
      const res = await axios.post(
        `${API}/review/${meeting.id}/speaker-text/restore-backup`,
        {}
      );
      toast.success("Previous speaker labels restored");
      if (onSpeakerTextGenerated) onSpeakerTextGenerated(res.data.speaker_text, res.data.edited_by_name, res.data.edited_at);
    } catch {
      toast.error("No backup available to restore");
    }
  };

  const handleReset = async () => {
    if (!window.confirm("This will clear the edited speaker labels and restore the full raw transcript. Continue?")) return;
    try {
      await axios.delete(
        `${API}/review/${meeting.id}/speaker-text`
      );
      setLocalTurns([]);
      setDirty(false);
      setViewMode("full");
      toast.success("Speaker labels cleared — full transcript restored");
      if (onSpeakerTextGenerated) onSpeakerTextGenerated(null, null, null);
    } catch {
      toast.error("Failed to reset speaker labels");
    }
  };

  const handleSave = async (stagedOverrides = {}) => {
    setSaving(true);
    try {
      // Apply any renames still pending in the panel's staged map (user clicked
      // Save without blurring the input first, so localTurns may be stale).
      const finalTurns = Object.keys(stagedOverrides).length
        ? localTurns.map(t => {
            const pending = (stagedOverrides[t.speaker] || "").trim();
            return pending && pending !== t.speaker ? { ...t, speaker: pending } : t;
          })
        : localTurns;
      const newText = serializeTurns(finalTurns);

      // Remap color keys to match any pending renames
      const finalColors = {};
      for (const [oldName, color] of Object.entries(stagedColors)) {
        const newName = stagedOverrides[oldName] ?? oldName;
        finalColors[newName] = color;
      }

      const res = await axios.patch(
        `${API}/review/${meeting.id}/speaker-text`,
        {
          speaker_text: newText,
          speaker_colors: Object.keys(finalColors).length ? finalColors : null,
          edit_note: pendingEditNotes.length ? pendingEditNotes.join("; ") : null,
        }
      );
      // Immediately commit the saved state — must happen before onSpeakerTextGenerated
      // so the isDirty guard in the useEffect doesn't skip the reset
      setLocalTurns(finalTurns.map(t => ({ ...t })));
      setDirty(false);
      setPendingEditNotes([]);
      toast.success("Speaker labels saved");
      if (onSpeakerTextGenerated) onSpeakerTextGenerated(newText, res.data.edited_by_name, res.data.edited_at, res.data.speaker_colors);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to save speaker labels. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const generateSpeakerView = async () => {
    setGenerating(true);
    try {
      const res = await axios.post(
        `${API}/processing/${meeting.id}/diarize`,
        {}
      );

      if (res.data.status === "processing") {
        toast.info("Identifying speakers — this may take 1–2 minutes for long transcripts…");
        // Poll every 5s until done or failed
        const intervalId = setInterval(async () => {
          try {
            const poll = await axios.get(
              `${API}/processing/${meeting.id}/status`
            );
            if (poll.data.diarize_status === "done") {
              clearInterval(intervalId);
              // Only update localTurns if the user hasn't made manual changes
              if (!isDirtyRef.current) {
                const updated = await axios.get(
                  `${API}/review/${meeting.id}`
                );
                const newSpeakerText = updated.data.transcript?.speaker_text;
                if (onSpeakerTextGenerated) onSpeakerTextGenerated(newSpeakerText, null, null);
                setViewMode("speaker");
                toast.success("Speaker labels generated");
              } else {
                toast.success("Speaker identification complete — save or discard your current changes to see the new labels");
              }
              setGenerating(false);
            } else if (poll.data.diarize_status === "failed") {
              clearInterval(intervalId);
              setGenerating(false);
              toast.error("Speaker identification failed — please try again");
            }
          } catch {
            clearInterval(intervalId);
            setGenerating(false);
          }
        }, 5000);
        // Safety timeout after 5 minutes
        setTimeout(() => {
          clearInterval(intervalId);
          setGenerating(false);
          toast.error("Speaker identification is taking longer than expected — reload the page to check");
        }, 300000);
      } else if (res.data.speaker_text) {
        if (onSpeakerTextGenerated) onSpeakerTextGenerated(res.data.speaker_text, null, null);
        setViewMode("speaker");
        setGenerating(false);
      }
    } catch (e) {
      setGenerating(false);
      toast.error(e?.response?.data?.detail || "Failed to start speaker identification. Please try again.");
    }
  };

  // ── Turn text inline editing ───────────────────────────────────────────────
  const handleTurnTextSave = useCallback((index) => {
    const trimmed = editingTurnText.trim();
    if (trimmed) {
      setLocalTurns(prev => prev.map((t, i) => i === index ? { ...t, text: trimmed } : t));
      setDirty(true);
    }
    setEditingTurnIndex(null);
    setEditingTurnText("");
  }, [editingTurnText, setDirty]);

  const handleTurnTextCancel = useCallback(() => {
    setEditingTurnIndex(null);
    setEditingTurnText("");
  }, []);

  // ── Find & Replace effects ─────────────────────────────────────────────────
  // Reset match index when query changes
  useEffect(() => { setFindMatchIdx(0); }, [findQuery, viewMode]);

  // Focus search input when bar opens
  useEffect(() => {
    if (findReplaceOpen) setTimeout(() => findInputRef.current?.focus(), 50);
  }, [findReplaceOpen]);

  // Scroll to current match
  useEffect(() => {
    if (!findMatches.length) return;
    const el = document.querySelector("[data-find-match='current']");
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [findMatchIdx, findMatches]);

  // Keyboard shortcut: Ctrl/Cmd+H to open, Escape to close
  useEffect(() => {
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "h") { e.preventDefault(); setFindReplaceOpen(true); }
      if (e.key === "Escape" && findReplaceOpen) { setFindReplaceOpen(false); setFindQuery(""); }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [findReplaceOpen]);

  // ── Find & Replace handlers ────────────────────────────────────────────────
  const handleFindNext = useCallback(() => {
    if (!findMatches.length) return;
    setFindMatchIdx(i => (i + 1) % findMatches.length);
  }, [findMatches.length]);

  const handleFindPrev = useCallback(() => {
    if (!findMatches.length) return;
    setFindMatchIdx(i => (i - 1 + findMatches.length) % findMatches.length);
  }, [findMatches.length]);

  const handleReplaceOne = useCallback(async () => {
    if (!findMatches.length) return;
    const match = findMatches[findMatchIdx];

    if (match.type === "turn") {
      setLocalTurns(prev => prev.map((t, i) => {
        if (i !== match.turnIdx) return t;
        const newText = t.text.slice(0, match.start) + replaceWith + t.text.slice(match.end);
        return { ...t, text: newText };
      }));
      setDirty(true);
      // Move to next (or clamp) after replacement since matches will recompute
      setFindMatchIdx(i => Math.min(i, findMatches.length - 2));
    } else if (match.type === "para" && onFindReplace) {
      // Full text: replace exactly the highlighted occurrence.
      // Count how many full-text (para) matches precede the current one to get the 0-based index.
      const occurrenceIndex = findMatches.slice(0, findMatchIdx).filter(m => m.type === "para").length;
      await onFindReplace(findQuery, replaceWith, 1, occurrenceIndex);
    }
  }, [findMatches, findMatchIdx, replaceWith, rawParas, onFindReplace, setDirty]); // eslint-disable-line

  const handleReplaceAll = useCallback(async () => {
    if (!findQuery.trim() || !findMatches.length) return;
    const count = findMatches.length;

    if (viewMode === "speaker") {
      const pattern = new RegExp(escapeRegex(findQuery), "gi");
      setLocalTurns(prev => prev.map(t => ({ ...t, text: t.text.replace(pattern, replaceWith) })));
      setDirty(true);
      toast.success(`Replaced ${count} occurrence${count !== 1 ? "s" : ""} — save to persist`);
    } else if (onFindReplace) {
      await onFindReplace(findQuery, replaceWith);
      toast.success(`Replaced ${count} occurrence${count !== 1 ? "s" : ""}`);
    }

    setFindQuery("");
    setReplaceWith("");
    setFindReplaceOpen(false);
  }, [findQuery, replaceWith, viewMode, findMatches.length, onFindReplace, setDirty]); // eslint-disable-line

  // ── Anonymise selection (Full Text only) ──────────────────────────────────
  const handleFullTextMouseUp = useCallback(() => {
    if (!canAnonymise) return;
    const sel = window.getSelection();
    const text = sel?.toString().trim();
    if (!text || text.length < 2) { setSelectionText(""); setPopupPos(null); return; }
    const range = sel.getRangeAt(0);
    const rect = range.getBoundingClientRect();
    setSelectionText(text);
    setPopupPos({ top: Math.max(10, rect.top - 44), left: rect.left + rect.width / 2 });
  }, [canAnonymise]);

  const handleAnonymise = () => {
    if (!selectionText || !onAnonymise) return;
    onAnonymise(selectionText);
    setSelectionText(""); setPopupPos(null);
    window.getSelection()?.removeAllRanges();
  };

  useEffect(() => {
    const clear = (e) => {
      if (e.target.closest("[data-anonymise-btn]")) return;
      setSelectionText(""); setPopupPos(null);
    };
    document.addEventListener("mousedown", clear);
    return () => document.removeEventListener("mousedown", clear);
  }, []);

  // ── Split turn: detect selection within a specific turn ───────────────────
  const handleSpeakerViewMouseUp = useCallback(() => {
    if (editingTurnIndex !== null) return; // Don't activate split popup while editing turn text
    const sel = window.getSelection();
    const selectedText = sel?.toString().trim();
    if (!selectedText || selectedText.length < 2) { setSplitPopup(null); return; }

    const range = sel.getRangeAt(0);

    // Walk up from the selection's start node to find the turn container
    let startNode = range.startContainer;
    while (startNode && startNode.nodeType !== 1) startNode = startNode.parentNode;
    const startTurnEl = startNode?.closest("[data-turn-index]");

    // Walk up from the selection's end node
    let endNode = range.endContainer;
    while (endNode && endNode.nodeType !== 1) endNode = endNode.parentNode;
    const endTurnEl = endNode?.closest("[data-turn-index]");

    // Only proceed if selection is entirely within one turn
    if (!startTurnEl || !endTurnEl || startTurnEl !== endTurnEl) {
      setSplitPopup(null);
      return;
    }

    const turnIndex = parseInt(startTurnEl.dataset.turnIndex, 10);
    const rect = range.getBoundingClientRect();

    setSplitPopup({
      turnIndex,
      selStart: range.startOffset,
      selEnd: range.endOffset,
      selectedText,
      top: Math.max(10, rect.top - 50),
      left: rect.left + rect.width / 2,
    });
  }, [editingTurnIndex]);

  const raw = anonymiseTranscript(meeting.transcript?.text || lazyRawText, meeting.attendees || []);
  const wordCount = raw ? raw.trim().split(/\s+/).filter(Boolean).length : 0;
  const readMins = Math.ceil(wordCount / 150);

  return (
    <div data-testid="transcript-view">
      {/* Header row */}
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
        {(meeting.transcript?.text || lazyRawText || meeting.transcript?.speaker_text) && (canAnonymise || canEditSpeakers) && (
          <button
            onClick={() => setFindReplaceOpen(v => !v)}
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
            {generating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Users className="w-3.5 h-3.5" />}
            {generating ? "Identifying…" : "Identify Speakers"}
          </button>
        ) : null}
      </div>

      {/* Transcript body */}
      <div className="bg-white border border-gray-200 rounded-lg shadow-sm overflow-hidden">
        {/* Word count bar */}
        {raw && (
          <div className="flex items-center gap-3 px-5 py-2.5 border-b border-gray-100 text-xs text-gray-400">
            <span data-testid="word-count">{wordCount.toLocaleString()} words</span>
            <span className="text-gray-200">·</span>
            <span>~{readMins} min read</span>
            {hasSpeakerText && viewMode === "speaker" && (
              <>
                <span className="text-gray-200">·</span>
                <span className="text-blue-500">{localTurns.length} turns</span>
              </>
            )}
          </div>
        )}

        {/* ── Find & Replace Bar ──────────────────────────────────────────── */}
        {findReplaceOpen && (
          <div className="border-b border-blue-200 bg-blue-50 px-4 py-3" data-testid="find-replace-bar">
            {/* Row 1 — Find */}
            <div className="flex items-center gap-2 mb-2">
              <Search className="w-3.5 h-3.5 text-blue-500 flex-shrink-0" />
              <input
                ref={findInputRef}
                type="text"
                value={findQuery}
                onChange={e => setFindQuery(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") { e.shiftKey ? handleFindPrev() : handleFindNext(); } }}
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
                onClick={handleFindPrev}
                disabled={findMatches.length === 0}
                className="p-1 rounded hover:bg-blue-100 disabled:opacity-30 transition-colors"
                title="Previous (Shift+Enter)"
                data-testid="find-prev-btn"
              >
                <ChevronUp className="w-3.5 h-3.5 text-gray-600" />
              </button>
              <button
                onClick={handleFindNext}
                disabled={findMatches.length === 0}
                className="p-1 rounded hover:bg-blue-100 disabled:opacity-30 transition-colors"
                title="Next (Enter)"
                data-testid="find-next-btn"
              >
                <ChevronDown className="w-3.5 h-3.5 text-gray-600" />
              </button>
              {/* Close */}
              <button
                onClick={() => { setFindReplaceOpen(false); setFindQuery(""); setReplaceWith(""); }}
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
                onKeyDown={e => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") handleReplaceAll(); }}
                placeholder="Replace with…"
                className="flex-1 min-w-0 text-xs px-2.5 py-1.5 rounded border border-blue-200 bg-white focus:outline-none focus:ring-1 focus:ring-[#1E3A8A] placeholder-gray-400"
                data-testid="replace-input"
              />
              <button
                onClick={handleReplaceOne}
                disabled={findMatches.length === 0}
                className="text-xs px-3 py-1.5 rounded border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 disabled:opacity-40 transition-colors flex-shrink-0 font-medium"
                data-testid="replace-one-btn"
              >
                Replace
              </button>
              <button
                onClick={handleReplaceAll}
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
        )}

        {viewMode === "full" && rawTextLoading ? (
          <div className="flex items-center justify-center gap-2.5 py-12 text-sm text-gray-400">
            <Loader2 className="w-4 h-4 animate-spin" />
            Loading full transcript…
          </div>
        ) : (!raw && !hasSpeakerText) ? (
          <p className="p-5 text-sm text-gray-400 italic">Transcript not available.</p>
        ) : viewMode === "speaker" && hasSpeakerText ? (
          <>
            {/* Speaker manager panel — managers/admins only */}
            {canEditSpeakers ? (
              <SpeakerManagerPanel
                localTurns={localTurns}
                onRenameAll={handleRenameAll}
                onSwapAll={handleSwapAll}
                onSave={handleSave}
                onDiscard={handleDiscard}
                onReset={handleReset}
                onRestoreBackup={handleRestoreBackup}
                saving={saving}
                isDirty={isDirty}
                lastEditedBy={meeting.transcript?.speaker_text_edited_by_name}
                lastEditedAt={meeting.transcript?.speaker_text_edited_at}
                backupBy={meeting.transcript?.speaker_text_backup_by}
                backupAt={meeting.transcript?.speaker_text_backup_at}
                stagedColors={stagedColors}
                onColorChange={handleColorChange}
              />
            ) : (
              <div className="flex items-center gap-2 px-5 py-2.5 bg-amber-50 border-b border-amber-100 text-xs text-amber-700">
                <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                Speaker labels are view-only. Only managers can edit speaker assignments.
              </div>
            )}

            {/* Turns */}
            <div
              className="divide-y divide-gray-100"
              data-testid="speaker-view"
              onMouseUp={handleSpeakerViewMouseUp}
            >
              {localTurns.map((turn, i) => {
                const style = roleToStyle(speakerRoleMap[turn.speaker] || getSpeakerRole(turn.speaker, managerName));
                const customColor = stagedColors[turn.speaker];
                const isMenuOpen = openTurnMenu === i;
                const rowStyle = customColor ? { backgroundColor: `${customColor}30` } : {};
                const pillStyle = customColor ? { backgroundColor: customColor, color: getContrastColor(customColor) } : {};
                const pillClass = customColor ? "" : style.pill;
                return (
                  <div key={i} className={`flex gap-3 px-5 py-3.5 ${customColor ? "" : style.row}`} style={rowStyle}>
                    {/* Speaker column: timestamp badge + speaker pill */}
                    <div className="relative flex-shrink-0 mt-0.5 flex flex-col items-start gap-1">
                      {turn.timestamp && (
                        <span className="text-[10px] font-mono text-gray-400 tabular-nums leading-none">
                          {turn.timestamp}
                        </span>
                      )}
                      {canEditSpeakers ? (
                        <button
                          data-testid={`speaker-pill-${i}`}
                          onMouseDown={e => { e.stopPropagation(); setOpenTurnMenu(isMenuOpen ? null : i); setSplitPopup(null); }}
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
                          data-testid={`turn-menu-${i}`}
                          className="absolute left-0 top-full mt-1 z-20 bg-white border border-gray-200 rounded-lg shadow-lg w-52 py-1 text-xs"
                        >
                          <p className="px-3 pt-1.5 pb-1 text-gray-400 font-semibold uppercase tracking-wide" style={{ fontSize: "10px" }}>
                            Assign turn {i + 1} to
                          </p>
                          {uniqueSpeakers.map(s => (
                            <button
                              key={s}
                              onMouseDown={() => handleTurnAssign(i, s)}
                              data-testid={`assign-turn-${i}-${s}`}
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
                                onMouseDown={() => handleFlipFromHere(i)}
                                data-testid={`flip-from-here-${i}`}
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
                      {canEditSpeakers && editingTurnIndex === i ? (
                        <div onMouseDown={e => e.stopPropagation()}>
                          <textarea
                            autoFocus
                            value={editingTurnText}
                            onChange={e => setEditingTurnText(e.target.value)}
                            onKeyDown={e => {
                              if (e.key === "Escape") handleTurnTextCancel();
                              if ((e.ctrlKey || e.metaKey) && e.key === "Enter") handleTurnTextSave(i);
                            }}
                            className="w-full text-sm text-gray-800 leading-relaxed border border-blue-300 rounded-md px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-200 resize-none bg-white"
                            rows={Math.max(2, Math.ceil(editingTurnText.length / 80))}
                            data-testid={`turn-text-edit-${i}`}
                          />
                          <div className="flex items-center gap-1.5 mt-1.5">
                            <button
                              onMouseDown={e => { e.preventDefault(); handleTurnTextSave(i); }}
                              className="flex items-center gap-1 text-xs px-2.5 py-1 bg-[#1E3A8A] text-white rounded hover:bg-[#1E40AF] transition-colors"
                              data-testid={`turn-text-save-${i}`}
                            >
                              <Check className="w-3 h-3" /> Save
                            </button>
                            <button
                              onMouseDown={e => { e.preventDefault(); handleTurnTextCancel(); }}
                              className="text-xs px-2.5 py-1 border border-gray-200 text-gray-600 rounded hover:bg-gray-50 transition-colors"
                              data-testid={`turn-text-cancel-${i}`}
                            >
                              Cancel
                            </button>
                            <span className="text-xs text-gray-400 hidden sm:inline">Ctrl+Enter · Esc to cancel</span>
                          </div>
                        </div>
                      ) : (
                        <div className="relative" ref={matchTurnIdx === i ? highlightRef : null}>
                          <p
                            data-turn-index={i}
                            className={`text-sm text-gray-800 leading-relaxed select-text cursor-text pr-5 transition-colors duration-300 ${
                              matchTurnIdx === i ? "rounded px-1 -mx-1 bg-yellow-50 ring-1 ring-yellow-300" : ""
                            }`}
                          >
                            {findReplaceOpen && findQuery.trim() && turnMatchMap[i]
                              ? <MultiHighlightText text={turn.text} matches={turnMatchMap[i]} currentGlobalIdx={findMatchIdx} />
                              : matchTurnIdx === i
                              ? <HighlightedText text={turn.text} query={effectiveHighlightQuery} />
                              : turn.text}
                          </p>
                          {canEditSpeakers && (
                            <button
                              onMouseDown={e => {
                                e.stopPropagation();
                                setSplitPopup(null);
                                setOpenTurnMenu(null);
                                setEditingTurnIndex(i);
                                setEditingTurnText(turn.text);
                              }}
                              className="absolute top-0 right-0 opacity-0 group-hover/turntext:opacity-100 transition-opacity text-gray-400 hover:text-gray-700 p-0.5 rounded hover:bg-white/80"
                              data-testid={`turn-text-edit-btn-${i}`}
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
              })}
            </div>
          </>
        ) : (
          <div className="p-5" onMouseUp={handleFullTextMouseUp}>
            {/* Privileged-user notice when redactions have been applied to speaker view */}
            {meeting.pii_redactions?.length > 0 && (
              <div className="mb-4 flex items-center gap-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m0-6v2m-6 4h12a2 2 0 002-2V7a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2z"/></svg>
                Original transcript — {meeting.pii_redactions.length} redaction{meeting.pii_redactions.length !== 1 ? "s" : ""} applied in Speaker View
              </div>
            )}
            {rawParas.map((para, idx) => (
              <p
                key={idx}
                ref={matchParaIdx === idx ? highlightRef : null}
                className={`text-sm text-gray-700 leading-relaxed mb-3 last:mb-0 transition-colors duration-300 ${
                  matchParaIdx === idx ? "rounded px-1 -mx-1 bg-yellow-50 ring-1 ring-yellow-300" : ""
                }`}
              >
                {findReplaceOpen && findQuery.trim() && paraMatchMap[idx]
                  ? <MultiHighlightText text={para} matches={paraMatchMap[idx]} currentGlobalIdx={findMatchIdx} />
                  : matchParaIdx === idx
                  ? <HighlightedText text={para} query={effectiveHighlightQuery} />
                  : para}
              </p>
            ))}
          </div>
        )}
      </div>

      {/* ── Anonymise popup (Full Text only) ──────────────────────────────── */}
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

      {/* ── Split turn popup (Speaker View only) ──────────────────────────── */}
      {splitPopup && viewMode === "speaker" && (
        <div
          data-testid="split-turn-popup"
          onMouseDown={e => e.stopPropagation()}
          style={{
            position: "fixed",
            top: splitPopup.top,
            left: splitPopup.left,
            transform: "translateX(-50%)",
            zIndex: 9999,
          }}
          className="bg-white border border-gray-200 rounded-lg shadow-xl text-xs flex items-stretch overflow-hidden"
        >
          <button
            onMouseDown={(e) => { e.preventDefault(); handleSplitTurn(); }}
            className="flex items-center gap-1.5 px-3 py-2 bg-[#1E3A8A] text-white font-semibold hover:bg-[#1E40AF] transition-colors"
          >
            <Scissors className="w-3.5 h-3.5" />
            Split turn here
          </button>
          <div className="px-2.5 py-2 text-gray-500 max-w-[160px] truncate border-l border-gray-200 bg-gray-50 flex items-center">
            &ldquo;{splitPopup.selectedText.length > 24 ? splitPopup.selectedText.slice(0, 24) + "…" : splitPopup.selectedText}&rdquo;
          </div>
        </div>
      )}
    </div>
  );
});

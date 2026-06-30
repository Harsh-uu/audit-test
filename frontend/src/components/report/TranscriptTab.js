import React, { useState, useEffect, useCallback, useMemo } from "react";
import { FileText, Users, Loader, ArrowLeftRight, Scissors, ChevronUp, ChevronDown } from "lucide-react";
import axios from "axios";
import { toast } from "sonner";
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

// ── Speaker Manager Panel ────────────────────────────────────────────────────
function SpeakerManagerPanel({ localTurns, onRenameAll, onSwapAll, onSave, onDiscard, saving, isDirty }) {
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
      )}
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────
export function TranscriptTab({ meeting, onAnonymise, canAnonymise, canEditSpeakers = true, onSpeakerTextGenerated }) {
  const [viewMode, setViewMode] = useState("full");

  // ── Speaker editing state ─────────────────────────────────────────────────
  const [localTurns, setLocalTurns] = useState([]);
  const [speakerRoleMap, setSpeakerRoleMap] = useState({}); // name → "manager"|"worker"
  const [isDirty, setIsDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [openTurnMenu, setOpenTurnMenu] = useState(null);

  // ── Full-text anonymise popup ─────────────────────────────────────────────
  const [selectionText, setSelectionText] = useState("");
  const [popupPos, setPopupPos] = useState(null);

  // ── Split turn popup (Speaker View) ──────────────────────────────────────
  const [splitPopup, setSplitPopup] = useState(null);
  // { turnIndex, selStart, selEnd, selectedText, top, left }

  const hasSpeakerText = Boolean(meeting.transcript?.speaker_text);
  const originalTurns = useMemo(
    () => parseSpeakerText(meeting.transcript?.speaker_text || ""),
    [meeting.transcript?.speaker_text]
  );

  const managerName = meeting.sign_off_manager_name || "";

  // Initialise / reset localTurns + role map when speaker_text changes
  useEffect(() => {
    // Don't overwrite the user's unsaved edits when a background fetchMeeting
    // updates meeting.transcript.speaker_text with the old DB value.
    // isDirty=false means either initial load or post-save, which are safe to reset.
    if (isDirty) return;
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
    setIsDirty(true);
  }, []);

  const handleSwapAll = useCallback(() => {
    if (uniqueSpeakers.length !== 2) return;
    const [a, b] = uniqueSpeakers;
    setLocalTurns(prev => prev.map(t => ({ ...t, speaker: t.speaker === a ? b : a })));
    setIsDirty(true);
  }, [uniqueSpeakers]);

  const handleTurnAssign = useCallback((index, newSpeaker) => {
    setLocalTurns(prev => prev.map((t, i) => i === index ? { ...t, speaker: newSpeaker } : t));
    setIsDirty(true);
    setOpenTurnMenu(null);
  }, []);

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
    setIsDirty(true);
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
      before ? { speaker: turn.speaker, text: before } : null,
      selected ? { speaker: turn.speaker, text: selected } : null,
      after ? { speaker: turn.speaker, text: after } : null,
    ].filter(Boolean);

    if (parts.length <= 1) { setSplitPopup(null); return; }

    setLocalTurns(prev => {
      const next = [...prev];
      next.splice(turnIndex, 1, ...parts);
      return next;
    });
    setIsDirty(true);
    setSplitPopup(null);
    window.getSelection()?.removeAllRanges();
  }, [splitPopup, localTurns]);

  const handleDiscard = useCallback(() => {
    setLocalTurns(originalTurns.map(t => ({ ...t })));
    setIsDirty(false);
  }, [originalTurns]);

  const handleSave = async (stagedOverrides = {}) => {
    setSaving(true);
    try {
      const token = localStorage.getItem("supervision_token");
      // Apply any renames still pending in the panel's staged map (user clicked
      // Save without blurring the input first, so localTurns may be stale).
      const finalTurns = Object.keys(stagedOverrides).length
        ? localTurns.map(t => {
            const pending = (stagedOverrides[t.speaker] || "").trim();
            return pending && pending !== t.speaker ? { ...t, speaker: pending } : t;
          })
        : localTurns;
      const newText = serializeTurns(finalTurns);
      await axios.patch(
        `${API}/api/review/${meeting.id}/speaker-text`,
        { speaker_text: newText },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      // Immediately commit the saved state — must happen before onSpeakerTextGenerated
      // so the isDirty guard in the useEffect doesn't skip the reset
      setLocalTurns(finalTurns.map(t => ({ ...t })));
      setIsDirty(false);
      toast.success("Speaker labels saved");
      if (onSpeakerTextGenerated) onSpeakerTextGenerated(newText);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to save speaker labels. Please try again.");
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
  }, []);

  const raw = anonymiseTranscript(meeting.transcript?.text, meeting.attendees || []);
  const wordCount = raw ? raw.trim().split(/\s+/).filter(Boolean).length : 0;
  const readMins = Math.ceil(wordCount / 150);

  return (
    <div data-testid="transcript-view">
      {/* Header row */}
      <div className="flex items-start gap-2 mb-4">
        <div className="flex-1 bg-amber-50 border border-amber-200 rounded-md p-3 hidden sm:flex items-center gap-2">
          <FileText className="w-4 h-4 text-amber-600 flex-shrink-0" />
          <p className="text-xs text-amber-700 flex-1">
            {viewMode === "speaker"
              ? "Rename speakers in the panel. Click any pill to reassign a turn. Select text within a turn to split it into separate turns."
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

        {!raw ? (
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
                saving={saving}
                isDirty={isDirty}
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
                const isMenuOpen = openTurnMenu === i;
                return (
                  <div key={i} className={`flex gap-3 px-5 py-3.5 ${style.row}`}>
                    {/* Speaker pill — clickable to reassign (managers/admins only) */}
                    <div className="relative flex-shrink-0 mt-0.5">
                      {canEditSpeakers ? (
                        <button
                          data-testid={`speaker-pill-${i}`}
                          onMouseDown={e => { e.stopPropagation(); setOpenTurnMenu(isMenuOpen ? null : i); setSplitPopup(null); }}
                          className={`inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full h-fit transition-all ${style.pill} ${isMenuOpen ? "ring-2 ring-offset-1 ring-blue-400" : "hover:opacity-80"}`}
                          title="Click to reassign this speaker turn"
                        >
                          {turn.speaker}
                          <svg className="w-2.5 h-2.5 opacity-70" viewBox="0 0 10 6" fill="none">
                            <path d="M1 1l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                          </svg>
                        </button>
                      ) : (
                        <span className={`inline-flex items-center text-xs font-semibold px-2 py-0.5 rounded-full h-fit ${style.pill}`}>
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

                    {/* Turn text — selectable for splitting */}
                    <p
                      data-turn-index={i}
                      className="text-sm text-gray-800 leading-relaxed select-text cursor-text"
                    >
                      {turn.text}
                    </p>
                  </div>
                );
              })}
            </div>
          </>
        ) : (
          <div className="p-5" onMouseUp={handleFullTextMouseUp}>
            {formatTranscript(raw).map((para, idx) => (
              <p key={idx} className="text-sm text-gray-700 leading-relaxed mb-3 last:mb-0">
                {para}
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
}

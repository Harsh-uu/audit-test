import React, { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { Loader2, Scissors } from "lucide-react";
import axios from "axios";
import { toast } from "sonner";
import { anonymiseTranscript } from "@/utils/anonymise";
import { useAuth } from "@/context/AuthContext";
import {
  resolveExcerptQuery, escapeRegex, formatTranscript,
  parseSpeakerText, serializeTurns, getContrastColor,
  getRoleBasedSpeakerColors,
} from "@/utils/transcriptHelpers";
import { HighlightedText, MultiHighlightText } from "./transcript/HighlightedText";
import { SpeakerManagerPanel } from "./transcript/SpeakerManagerPanel";
import { FindReplaceBar } from "./transcript/FindReplaceBar";
import { TranscriptToolbar } from "./transcript/TranscriptToolbar";
import { SpeakerTurnRow } from "./transcript/SpeakerTurnRow";

// ── Main component ───────────────────────────────────────────────────────────
export const TranscriptTab = React.memo(function TranscriptTab({ meeting, onAnonymise, canAnonymise, canEditSpeakers = true, onSpeakerTextGenerated, onDirtyChange, highlightExcerpt = "", highlightKey = 0, onFindReplace }) {
  const { API, getAuthConfig, user } = useAuth();
  const [viewMode, setViewMode] = useState("full");

  // ── Speaker editing state ─────────────────────────────────────────────────
  const [localTurns, setLocalTurns] = useState([]);
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
  // PERF-004: the raw query updates the input instantly (so typing feels
  // responsive), but the expensive full-transcript scan below is driven by
  // this debounced copy instead, so it only runs once typing pauses rather
  // than on every keystroke.
  const [debouncedFindQuery, setDebouncedFindQuery] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebouncedFindQuery(findQuery), 200);
    return () => clearTimeout(t);
  }, [findQuery]);
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

  // Initialise / reset localTurns when speaker_text changes
  useEffect(() => {
    // Use the ref (not state) to read isDirty — avoids stale-closure issues in
    // React 19 Concurrent Mode where the committed render may differ from the
    // render that enqueued setIsDirty(false) earlier in the same flush.
    if (isDirtyRef.current) return;
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
  // PERF-004: driven by debouncedFindQuery, not the raw findQuery, so this
  // full-transcript scan runs once per pause-in-typing, not per keystroke.
  const findMatches = useMemo(() => {
    const q = debouncedFindQuery.trim();
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
  }, [debouncedFindQuery, viewMode, localTurns, rawParas]);

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

  // Effective colour per speaker — role-based (manager vs attendee), configured
  // once org-wide in Settings > Branding. Used for both the panel and turn rows.
  const speakerColorMap = useMemo(
    () => getRoleBasedSpeakerColors(uniqueSpeakers, meeting, user?.org_branding?.speaker_colors),
    [uniqueSpeakers, meeting, user?.org_branding?.speaker_colors]
  );

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

      const res = await axios.patch(
        `${API}/review/${meeting.id}/speaker-text`,
        {
          speaker_text: newText,
          edit_note: pendingEditNotes.length ? pendingEditNotes.join("; ") : null,
        }
      );
      // Immediately commit the saved state — must happen before onSpeakerTextGenerated
      // so the isDirty guard in the useEffect doesn't skip the reset
      setLocalTurns(finalTurns.map(t => ({ ...t })));
      setDirty(false);
      setPendingEditNotes([]);
      toast.success("Speaker labels saved");
      if (onSpeakerTextGenerated) onSpeakerTextGenerated(newText, res.data.edited_by_name, res.data.edited_at);
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

  const handleTurnMenuToggle = useCallback((index) => {
    setOpenTurnMenu(prev => (prev === index ? null : index));
    setSplitPopup(null);
  }, []);

  const handleStartTurnEdit = useCallback((index, text) => {
    setSplitPopup(null);
    setOpenTurnMenu(null);
    setEditingTurnIndex(index);
    setEditingTurnText(text);
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
      setFindMatchIdx(i => Math.max(0, Math.min(i, findMatches.length - 2)));
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

  const handleCloseFindReplace = useCallback(() => {
    setFindReplaceOpen(false);
    setFindQuery("");
    setReplaceWith("");
  }, []);

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

  // PERF-005: was called directly in the render body — re-ran the full
  // find-and-replace over the whole transcript on every render, including
  // ones from unrelated state (typing in Find/Replace, editing a turn,
  // opening a speaker menu). Memoized so it only recomputes when the
  // actual transcript text or attendee list changes.
  const raw = useMemo(
    () => anonymiseTranscript(meeting.transcript?.text || lazyRawText, meeting.attendees || []),
    [meeting.transcript?.text, lazyRawText, meeting.attendees]
  );
  const wordCount = raw ? raw.trim().split(/\s+/).filter(Boolean).length : 0;
  const readMins = Math.ceil(wordCount / 150);
  const findQueryTrimmed = Boolean(findQuery.trim());
  const showFindReplaceBtn = Boolean(
    (meeting.transcript?.text || lazyRawText || meeting.transcript?.speaker_text) && (canAnonymise || canEditSpeakers)
  );

  return (
    <div data-testid="transcript-view">
      {/* Header row */}
      <TranscriptToolbar
        viewMode={viewMode}
        canAnonymise={canAnonymise}
        showFindReplaceBtn={showFindReplaceBtn}
        findReplaceOpen={findReplaceOpen}
        onToggleFindReplace={() => setFindReplaceOpen(v => !v)}
        hasSpeakerText={hasSpeakerText}
        onSetViewMode={setViewMode}
        raw={raw}
        generating={generating}
        onGenerateSpeakerView={generateSpeakerView}
      />

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
          <FindReplaceBar
            findInputRef={findInputRef}
            findQuery={findQuery}
            setFindQuery={setFindQuery}
            replaceWith={replaceWith}
            setReplaceWith={setReplaceWith}
            findMatches={findMatches}
            findMatchIdx={findMatchIdx}
            viewMode={viewMode}
            onFindNext={handleFindNext}
            onFindPrev={handleFindPrev}
            onClose={handleCloseFindReplace}
            onReplaceOne={handleReplaceOne}
            onReplaceAll={handleReplaceAll}
          />
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
                const customColor = speakerColorMap[turn.speaker];
                const rowStyle = { backgroundColor: `${customColor}30` };
                const pillStyle = { backgroundColor: customColor, color: getContrastColor(customColor) };
                return (
                  <SpeakerTurnRow
                    key={i}
                    turn={turn}
                    index={i}
                    pillStyle={pillStyle}
                    rowStyle={rowStyle}
                    canEditSpeakers={canEditSpeakers}
                    isMenuOpen={openTurnMenu === i}
                    onToggleMenu={handleTurnMenuToggle}
                    uniqueSpeakers={uniqueSpeakers}
                    onAssign={handleTurnAssign}
                    onFlipFromHere={handleFlipFromHere}
                    isEditing={editingTurnIndex === i}
                    editingTurnText={editingTurnText}
                    setEditingTurnText={setEditingTurnText}
                    onSaveTurnText={handleTurnTextSave}
                    onCancelTurnText={handleTurnTextCancel}
                    onStartEdit={handleStartTurnEdit}
                    isHighlighted={matchTurnIdx === i}
                    highlightRef={highlightRef}
                    findReplaceOpen={findReplaceOpen}
                    findQueryTrimmed={findQueryTrimmed}
                    turnMatches={turnMatchMap[i]}
                    findMatchIdx={findMatchIdx}
                    effectiveHighlightQuery={effectiveHighlightQuery}
                  />
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
                {findReplaceOpen && findQueryTrimmed && paraMatchMap[idx]
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

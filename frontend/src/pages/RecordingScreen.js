import React, { useState, useEffect, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import {
  Mic, MicOff, Pause, Play, Square, AlertTriangle, Clock, Info, Upload, ArrowRight, Users, ExternalLink, CheckSquare, ChevronDown, ChevronUp, BookOpen, Sparkles
} from "lucide-react";

function formatDuration(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}:${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}`;
  return `${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}`;
}

const RECORDING_NOTICE = "This meeting is being recorded in line with our recording policy and requirement to gather evidence of compliance for CQC.";

// Detect if running inside an iframe (e.g. Emergent platform preview)
function isInIframe() {
  try { return window.self !== window.top; } catch { return true; }
}

// Check if the browser supports getUserMedia in this context
function canUseMediaDevices() {
  return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
}

// ── IndexedDB audio backup helpers ──────────────────────────────────────────
// Keeps the recorded audio blob alive across page refreshes so uploads can
// be retried even after the browser tab is reloaded.

function openAudioDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open("supervision_audio", 1);
    req.onupgradeneeded = (e) => {
      e.target.result.createObjectStore("recordings", { keyPath: "meetingId" });
    };
    req.onsuccess = (e) => resolve(e.target.result);
    req.onerror = (e) => reject(e.target.error);
  });
}

async function saveAudioBackup(meetingId, blob) {
  try {
    const db = await openAudioDB();
    await new Promise((resolve, reject) => {
      const tx = db.transaction("recordings", "readwrite");
      tx.objectStore("recordings").put({ meetingId, blob, savedAt: Date.now() });
      tx.oncomplete = resolve;
      tx.onerror = (e) => reject(e.target.error);
    });
  } catch (e) {
    console.warn("IndexedDB save failed:", e);
  }
}

async function loadAudioBackup(meetingId) {
  try {
    const db = await openAudioDB();
    return await new Promise((resolve, reject) => {
      const tx = db.transaction("recordings", "readonly");
      const req = tx.objectStore("recordings").get(meetingId);
      req.onsuccess = (e) => resolve(e.target.result?.blob || null);
      req.onerror = (e) => reject(e.target.error);
    });
  } catch (e) {
    return null;
  }
}

async function clearAudioBackup(meetingId) {
  try {
    const db = await openAudioDB();
    await new Promise((resolve, reject) => {
      const tx = db.transaction("recordings", "readwrite");
      tx.objectStore("recordings").delete(meetingId);
      tx.oncomplete = resolve;
      tx.onerror = (e) => reject(e.target.error);
    });
  } catch (e) {
    console.warn("IndexedDB clear failed:", e);
  }
}

export default function RecordingScreen() {
  const { meetingId } = useParams();
  const { getAuthConfig, API, silentRefresh, user } = useAuth();
  const navigate = useNavigate();
  const [meeting, setMeeting] = useState(null);
  const [stage, setStage] = useState("notice"); // notice | ready | recording | paused | stopped | uploading | processing
  const [error, setError] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [pausedTotal, setPausedTotal] = useState(0);
  const [pauseStart, setPauseStart] = useState(null);
  const [events, setEvents] = useState([]);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadFailed, setUploadFailed] = useState(false);
  const [savedBlob, setSavedBlob] = useState(null);
  const [checkingBackup, setCheckingBackup] = useState(false);
  const [inIframe, setInIframe] = useState(false);
  const [template, setTemplate] = useState(null);
  const [prep, setPrep] = useState(null);
  const [completedSteps, setCompletedSteps] = useState({});
  const [guideOpen, setGuideOpen] = useState(() => window.innerWidth >= 768);
  const [prepMode, setPrepMode] = useState(true); // true = show prep agenda, false = static template
  const [processingStatus, setProcessingStatus] = useState("processing"); // backend meeting.status during processing stage
  const [processingError, setProcessingError] = useState(null);
  const [step2Progress, setStep2Progress] = useState(0);
  const [step3Progress, setStep3Progress] = useState(0);
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const timerRef = useRef(null);
  const elapsedRef = useRef(0);
  const wakeLockRef = useRef(null);
  const chunkSaveIntervalRef = useRef(null);
  const [wakeLockActive, setWakeLockActive] = useState(false);

  useEffect(() => {
    setInIframe(isInIframe());
    axios.get(`${API}/admin/template`, getAuthConfig())
      .then(r => { if (r.data?.steps?.length > 0) setTemplate(r.data); })
      .catch(() => {});
    // Load prep agenda if it exists
    axios.get(`${API}/prep/${meetingId}`, getAuthConfig())
      .then(r => { if (r.data?.sections?.length > 0) setPrep(r.data); })
      .catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    axios.get(`${API}/meetings/${meetingId}`, getAuthConfig())
      .then(r => {
        setMeeting(r.data);
        if (["processing", "transcribing", "analyzing", "in_review", "reviewed", "signed_off", "shared"].includes(r.data.status)) {
          navigate(`/meetings/${meetingId}/report`);
        }
        // Check IndexedDB for a saved blob (e.g. upload failed due to server restart)
        if (["recording", "stopped", "draft"].includes(r.data.status)) {
          setCheckingBackup(true);
          loadAudioBackup(meetingId).then(blob => {
            setCheckingBackup(false);
            if (blob) {
              setSavedBlob(blob);
              setStage("stopped");
            }
          }).catch(() => setCheckingBackup(false));
        }
      })
      .catch(e => setError("Meeting not found"));
  }, [meetingId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (chunkSaveIntervalRef.current) clearInterval(chunkSaveIntervalRef.current);
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
        mediaRecorderRef.current.stop();
      }
      // Release wake lock on unmount
      if (wakeLockRef.current) {
        wakeLockRef.current.release().catch(() => {});
        wakeLockRef.current = null;
      }
    };
  }, []);

  const acquireWakeLock = async () => {
    if (!("wakeLock" in navigator)) return;
    try {
      wakeLockRef.current = await navigator.wakeLock.request("screen");
      setWakeLockActive(true);
      wakeLockRef.current.addEventListener("release", () => {
        setWakeLockActive(false);
        wakeLockRef.current = null;
      });
    } catch (err) {
      console.warn("Wake lock unavailable:", err.message);
    }
  };

  const releaseWakeLock = async () => {
    if (wakeLockRef.current) {
      // Intentional: release can throw if the lock was already released by the OS (e.g. low battery)
      try { await wakeLockRef.current.release(); } catch {}
      wakeLockRef.current = null;
      setWakeLockActive(false);
    }
  };

  // ── Poll backend status when in processing stage ─────────────────────────
  useEffect(() => {
    if (stage !== "processing") return;
    setStep2Progress(0);
    setStep3Progress(0);
    setProcessingError(null);
    const poll = setInterval(async () => {
      try {
        const { data } = await axios.get(`${API}/meetings/${meetingId}`, getAuthConfig());
        setProcessingStatus(data.status);
        if (data.processing_error) {
          setProcessingError(data.processing_error);
          clearInterval(poll);
          return;
        }
        if (!["processing", "transcribing", "analyzing"].includes(data.status)) {
          clearInterval(poll);
          navigate(`/meetings/${meetingId}/report`);
        }
      } catch {}
    }, 3000);
    return () => clearInterval(poll);
  }, [stage]); // eslint-disable-line react-hooks/exhaustive-deps

  // Animate step 2 progress bar while transcribing
  useEffect(() => {
    const isActive = stage === "processing" && ["processing", "transcribing"].includes(processingStatus);
    if (!isActive) return;
    const t = setInterval(() => setStep2Progress(p => {
      const remaining = 88 - p; return p < 88 ? p + Math.max(0.15, remaining * 0.018) : p;
    }), 1000);
    return () => clearInterval(t);
  }, [stage, processingStatus]);

  // Animate step 3 progress bar while analyzing
  useEffect(() => {
    const isActive = stage === "processing" && processingStatus === "analyzing";
    if (!isActive) return;
    const t = setInterval(() => setStep3Progress(p => {
      const remaining = 88 - p; return p < 88 ? p + Math.max(0.2, remaining * 0.025) : p;
    }), 1000);
    return () => clearInterval(t);
  }, [stage, processingStatus]);
  useEffect(() => {
    const handleVisibility = async () => {
      if (document.visibilityState === "visible" && !wakeLockRef.current) {
        await acquireWakeLock();
      }
    };
    if (stage === "recording" || stage === "paused") {
      document.addEventListener("visibilitychange", handleVisibility);
      return () => document.removeEventListener("visibilitychange", handleVisibility);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stage]);

  const logNotice = async () => {
    try {
      await axios.post(`${API}/recording/${meetingId}/notice`, {}, getAuthConfig());
    } catch (err) {
      console.error("Notice log failed:", err);
    }
    setStage("ready");
  };

  const getBestMimeType = () => {
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/ogg",
      "audio/mp4",
      "audio/mpeg",
    ];
    for (const t of candidates) {
      // Intentional: isTypeSupported can throw in some browsers; probe each type silently
      try { if (MediaRecorder.isTypeSupported(t)) return t; } catch {}
    }
    return ""; // let browser decide
  };

  const startRecording = async () => {
    setError("");
    await acquireWakeLock();

    // Check if running in an embedded iframe — browsers block mic access there
    if (inIframe || !canUseMediaDevices()) {
      setError(
        "Microphone access is blocked because this page is running inside an embedded preview. " +
        "Please open the app in a full browser tab to use recording."
      );
      return;
    }

    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    } catch (err) {
      if (err.name === "NotAllowedError" || err.name === "PermissionDeniedError") {
        setError("Microphone access was denied. Please click the camera/microphone icon in your browser address bar and allow access, then try again.");
      } else if (err.name === "NotFoundError" || err.name === "DevicesNotFoundError") {
        setError("No microphone found. Please connect a microphone and try again.");
      } else if (err.name === "NotReadableError" || err.name === "TrackStartError") {
        setError("Microphone is in use by another application. Please close other apps using the microphone and try again.");
      } else {
        setError(`Could not access microphone: ${err.message}`);
      }
      return;
    }

    // Build MediaRecorder with best available format + low bitrate for voice
    // 32 kbps keeps a 30-min recording under 8 MB, well within Cloudflare's proxy limits
    let recorder;
    try {
      const mimeType = getBestMimeType();
      const options = {
        ...(mimeType ? { mimeType } : {}),
        audioBitsPerSecond: 32000,
      };
      recorder = new MediaRecorder(stream, options);
    } catch (err) {
      // Fallback: try with no options at all
      try {
        recorder = new MediaRecorder(stream);
      } catch (e2) {
        stream.getTracks().forEach(t => t.stop());
        setError(`Your browser does not support audio recording. Please use Chrome or Firefox.`);
        return;
      }
    }

    audioChunksRef.current = [];
    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) {
        audioChunksRef.current.push(e.data);
      }
    };
    recorder.onstop = () => {
      stream.getTracks().forEach(t => t.stop());
      const blob = new Blob(audioChunksRef.current, { type: "audio/webm" });
      // Persist to IndexedDB so the upload can be retried after a page refresh
      saveAudioBackup(meetingId, blob).then(() => handleUpload());
    };
    recorder.onerror = (e) => {
      setError(`Recording error: ${e.error?.message || "unknown error"}`);
      setStage("stopped");
    };

    try {
      recorder.start(1000);
    } catch (err) {
      stream.getTracks().forEach(t => t.stop());
      setError(`Failed to start recording: ${err.message}`);
      return;
    }

    mediaRecorderRef.current = recorder;

    // Save progress to IndexedDB every 3 minutes so at most 3 min is at risk
    // if the session is interrupted (pod restart, page refresh, tab close).
    chunkSaveIntervalRef.current = setInterval(async () => {
      if (audioChunksRef.current.length > 0) {
        const progressBlob = new Blob(audioChunksRef.current, { type: "audio/webm" });
        await saveAudioBackup(meetingId, progressBlob);
      }
    }, 3 * 60 * 1000);

    // Log start event (non-blocking — don't let API failures break recording)
    const ts = new Date().toISOString();
    axios.post(`${API}/recording/${meetingId}/start`, { timestamp: ts }, getAuthConfig())
      .catch(e => console.warn("Failed to log recording start:", e.message));
    addEvent("Recording started", ts, "start");
    setStage("recording");

    elapsedRef.current = 0;
    timerRef.current = setInterval(() => {
      elapsedRef.current += 1;
      setElapsed(elapsedRef.current);
    }, 1000);
  };

  const pauseRecording = async () => {
    if (!mediaRecorderRef.current || mediaRecorderRef.current.state !== "recording") return;
    mediaRecorderRef.current.pause();
    clearInterval(timerRef.current);
    const ts = new Date().toISOString();
    setPauseStart(ts);
    setStage("paused");
    axios.post(`${API}/recording/${meetingId}/pause`, { timestamp: ts }, getAuthConfig())
      .catch(e => console.warn("Failed to log pause:", e.message));
    addEvent("Recording paused", ts, "pause");
  };

  const resumeRecording = async () => {
    if (!mediaRecorderRef.current || mediaRecorderRef.current.state !== "paused") return;
    mediaRecorderRef.current.resume();
    const ts = new Date().toISOString();
    const ps = pauseStart;
    const pauseDurationSec = ps ? Math.floor((new Date(ts) - new Date(ps)) / 1000) : 0;
    setPausedTotal(prev => prev + pauseDurationSec);
    setPauseStart(null);
    setStage("recording");
    axios.post(`${API}/recording/${meetingId}/resume`, { timestamp: ts, pause_start: ps }, getAuthConfig())
      .catch(e => console.warn("Failed to log resume:", e.message));
    addEvent("Recording resumed", ts, "resume");

    timerRef.current = setInterval(() => {
      elapsedRef.current += 1;
      setElapsed(elapsedRef.current);
    }, 1000);
  };

  const stopRecording = async () => {
    if (!mediaRecorderRef.current || mediaRecorderRef.current.state === "inactive") return;
    clearInterval(timerRef.current);
    clearInterval(chunkSaveIntervalRef.current);
    await releaseWakeLock();
    const ts = new Date().toISOString();
    setStage("stopped");
    axios.post(`${API}/recording/${meetingId}/stop`, { timestamp: ts }, getAuthConfig())
      .catch(e => console.warn("Failed to log stop:", e.message));
    addEvent("Recording stopped", ts, "stop");
    mediaRecorderRef.current.stop();
  };

  const handleUpload = async (retryAttempt = 0) => {
    const MAX_RETRIES = 8;
    const RETRY_DELAY_MS = 8000;

    // Resolve the blob — prefer in-memory chunks, fall back to IndexedDB backup
    let blob;
    if (audioChunksRef.current.length > 0) {
      blob = new Blob(audioChunksRef.current, { type: "audio/webm" });
    } else if (savedBlob) {
      blob = savedBlob;
    } else {
      setError("No audio data found. Please re-record the meeting.");
      setStage("stopped");
      return;
    }

    setStage("uploading");
    setUploadFailed(false);
    setError("");
    setUploadProgress(0);

    try {
      try { await silentRefresh(); } catch {}
      const token = localStorage.getItem("supervision_token");
      await axios.post(`${API}/processing/${meetingId}/upload`, blob, {
        headers: {
          "Content-Type": "application/octet-stream",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        onUploadProgress: (e) => {
          if (e.total) setUploadProgress(Math.round((e.loaded / e.total) * 100));
        },
      });
      // Success — clear the IndexedDB backup
      await clearAudioBackup(meetingId);
      setSavedBlob(null);
      setStage("processing");
      // Polling effect will watch for completion and navigate
    } catch (err) {
      const status = err.response?.status;
      const detail = err.response?.data?.detail || err.message;
      const isAuthError = status === 401;
      const isServerDown = !status || status === 404 || status === 503 || status === 502;

      console.error("[Upload failed]", {
        meetingId, httpStatus: status, message: err.message, retryAttempt,
      });

      // Auto-retry on server-down errors — pod restart takes up to 60s
      if (isServerDown && !isAuthError && retryAttempt < MAX_RETRIES) {
        const remaining = MAX_RETRIES - retryAttempt;
        setStage("stopped");
        setError(`Server restarting — retrying automatically in ${RETRY_DELAY_MS / 1000}s (${remaining} attempt${remaining !== 1 ? "s" : ""} left). Your recording is safe.`);
        await new Promise(r => setTimeout(r, RETRY_DELAY_MS));
        return handleUpload(retryAttempt + 1);
      }

      setError(
        isAuthError
          ? "Session expired — your recording is saved in this browser. Refresh the page, log back in, then return here to upload."
          : `Upload failed after ${MAX_RETRIES} attempts. Your recording is saved — click Retry Upload to try again.`
      );
      setUploadFailed(true);
      setStage("stopped");
    }
  };

  const addEvent = (label, ts, type) => {
    const timeStr = new Date(ts).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    setEvents(prev => [...prev, { label, time: timeStr, type }]);
  };

  const eventIcons = { start: "text-emerald-600", pause: "text-amber-600", resume: "text-blue-600", stop: "text-red-600" };

  return (
    <Layout>
      <div className="p-4 sm:p-6 md:p-8 max-w-2xl mx-auto w-full fade-in">
        {meeting && (
          <div className="mb-5">
            <h1 className="text-lg sm:text-xl font-semibold text-gray-900 leading-snug font-display">{meeting.title}</h1>
            <div className="flex flex-wrap items-center gap-2 sm:gap-3 mt-1 text-sm text-gray-500">
              {meeting.attendees?.length > 0 && (
                <span className="flex items-center gap-1"><Users className="w-3.5 h-3.5" />{meeting.attendees.length} attendee{meeting.attendees.length !== 1 ? "s" : ""}</span>
              )}
              {meeting.sign_off_manager_name && <span className="hidden sm:inline">Manager: {meeting.sign_off_manager_name}</span>}
            </div>
          </div>
        )}

        {/* Session Guide — shows Prep Agenda if available, else static template */}
        {(prep || (template && template.steps?.length > 0)) && (
          <div className="mb-5 bg-indigo-50 border border-indigo-200 rounded-lg overflow-hidden" data-testid="session-guide">
            {/* Header: title + progress + toggle */}
            <div
              onClick={() => setGuideOpen(o => !o)}
              className="w-full flex items-center justify-between px-4 py-3 cursor-pointer select-none"
            >
              <div className="flex items-center gap-2">
                {prep && prepMode ? <Sparkles className="w-4 h-4 text-indigo-600" /> : <BookOpen className="w-4 h-4 text-indigo-600" />}
                <span className="text-sm font-semibold text-indigo-800">
                  {prep && prepMode ? "Prep Agenda" : (template?.name || "Session Guide")}
                </span>
                <span className="text-xs text-indigo-500">
                  {prep && prepMode
                    ? `${Object.values(completedSteps).filter(Boolean).length}/${prep.sections.reduce((n, s) => n + s.questions.filter(q => q.included !== false).length, 0)} covered`
                    : `${Object.values(completedSteps).filter(Boolean).length}/${template?.steps?.length || 0} covered`
                  }
                </span>
              </div>
              <div className="flex items-center gap-2">
                {/* Toggle between prep and template if both exist */}
                {prep && template?.steps?.length > 0 && (
                  <button
                    onClick={e => { e.stopPropagation(); setPrepMode(m => !m); }}
                    className="text-xs text-indigo-500 hover:text-indigo-700 border border-indigo-300 rounded px-2 py-0.5"
                  >
                    {prepMode ? "Template" : "Prep Agenda"}
                  </button>
                )}
                {guideOpen ? <ChevronUp className="w-4 h-4 text-indigo-500" /> : <ChevronDown className="w-4 h-4 text-indigo-500" />}
              </div>
            </div>

            {guideOpen && (
              <div className="border-t border-indigo-100 px-4 py-3 space-y-3">
                {/* Prep Agenda view */}
                {prep && prepMode && (
                  <>
                    {prep.focus_topic && (
                      <p className="text-xs font-medium text-indigo-700 bg-indigo-100 px-2.5 py-1.5 rounded-lg">
                        Focus: {prep.focus_topic}
                      </p>
                    )}
                    {prep.sections.map((section) => {
                      const includedQs = section.questions.filter(q => q.included !== false);
                      if (!includedQs.length) return null;
                      return (
                        <div key={section.section_id} className="space-y-1.5">
                          <p className="text-xs font-semibold text-indigo-600 uppercase tracking-wide">{section.label}</p>
                          {includedQs.map((q) => (
                            <label key={q.id} className="flex items-start gap-3 cursor-pointer group" data-testid={`prep-q-${q.id}`}>
                              <div
                                onClick={() => setCompletedSteps(cs => ({ ...cs, [q.id]: !cs[q.id] }))}
                                className={`w-5 h-5 rounded border-2 flex items-center justify-center flex-shrink-0 mt-0.5 transition-colors ${completedSteps[q.id] ? "bg-indigo-600 border-indigo-600 text-white" : "border-indigo-300 group-hover:border-indigo-500"}`}
                              >
                                {completedSteps[q.id] && <CheckSquare className="w-3.5 h-3.5" />}
                              </div>
                              <p className={`text-sm leading-snug transition-colors ${completedSteps[q.id] ? "line-through text-indigo-400" : "text-indigo-900"}`}>
                                {q.text}
                              </p>
                            </label>
                          ))}
                        </div>
                      );
                    })}
                  </>
                )}

                {/* Static template view */}
                {(!prep || !prepMode) && template?.steps?.length > 0 && (
                  <>
                    {template.description && <p className="text-xs text-indigo-600 mb-3">{template.description}</p>}
                    {template.steps.map((step, i) => (
                      <label key={step.id || i} className="flex items-start gap-3 cursor-pointer group" data-testid={`guide-step-${i}`}>
                        <div
                          onClick={() => setCompletedSteps(cs => ({ ...cs, [step.id || i]: !cs[step.id || i] }))}
                          className={`w-5 h-5 rounded border-2 flex items-center justify-center flex-shrink-0 mt-0.5 transition-colors ${completedSteps[step.id || i] ? "bg-indigo-600 border-indigo-600 text-white" : "border-indigo-300 group-hover:border-indigo-500"}`}
                        >
                          {completedSteps[step.id || i] && <CheckSquare className="w-3.5 h-3.5" />}
                        </div>
                        <div className="flex-1">
                          <p className={`text-sm font-medium transition-colors ${completedSteps[step.id || i] ? "line-through text-indigo-400" : "text-indigo-900"}`}>
                            {i + 1}. {step.title}
                          </p>
                          {step.description && <p className="text-xs text-indigo-500 mt-0.5">{step.description}</p>}
                        </div>
                      </label>
                    ))}
                  </>
                )}
              </div>
            )}
          </div>
        )}

        {/* Iframe / preview environment warning */}
        {inIframe && (
          <div className="bg-blue-50 border border-blue-300 rounded-lg p-4 mb-5 fade-in" data-testid="iframe-warning">
            <div className="flex items-start gap-3">
              <ExternalLink className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-semibold text-blue-900 mb-1">Open in a full browser tab to record</p>
                <p className="text-sm text-blue-700 mb-3">
                  Your browser blocks microphone access inside embedded previews. To use recording, open Supervision directly in its own tab.
                </p>
                <a
                  href={window.location.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-blue-700 transition-colors"
                  data-testid="open-new-tab-btn"
                >
                  <ExternalLink className="w-4 h-4" />
                  Open in New Tab
                </a>
              </div>
            </div>
          </div>
        )}

        {error && (
          <div className="flex items-start gap-3 bg-red-50 border border-red-200 text-red-700 rounded-md p-3 mb-5 text-sm" data-testid="recording-error">
            <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" />
            <div>
              <p>{error}</p>
              {(error.includes("blocked") || error.includes("iframe") || error.includes("embedded")) && (
                <a
                  href={window.location.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 mt-2 text-red-700 underline font-medium text-xs"
                >
                  <ExternalLink className="w-3 h-3" /> Open in new tab
                </a>
              )}
            </div>
          </div>
        )}

        {/* Stuck recording — audio lost, no IndexedDB backup */}
        {meeting && meeting.status === "recording" && stage === "notice" && !savedBlob && !checkingBackup && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-5 mb-5 fade-in">
            <div className="flex items-start gap-3">
              <AlertTriangle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <p className="text-sm font-semibold text-red-900 mb-1">Recording not completed</p>
                <p className="text-sm text-red-700 mb-3">
                  This meeting was being recorded but the audio was not uploaded — it may have been interrupted by a server restart or page refresh. The audio data is no longer available.
                </p>
                <p className="text-sm text-red-700 mb-4">
                  Please delete this meeting and start a new recording.
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={async () => {
                      if (!window.confirm("Delete this meeting and all its data?")) return;
                      try {
                        await axios.delete(`${API}/meetings/${meetingId}`, getAuthConfig());
                        navigate("/dashboard");
                      } catch (e) {
                        setError("Delete failed: " + (e.response?.data?.detail || e.message));
                      }
                    }}
                    className="bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded-md text-sm font-medium transition-colors"
                    data-testid="delete-stuck-meeting-btn"
                  >
                    Delete Meeting
                  </button>
                  <button
                    onClick={() => navigate("/dashboard")}
                    className="bg-white border border-gray-300 text-gray-700 px-4 py-2 rounded-md text-sm font-medium hover:bg-gray-50 transition-colors"
                  >
                    Back to Dashboard
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Checking IndexedDB for saved audio */}
        {checkingBackup && (
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-5 text-sm text-blue-800 fade-in">
            Checking for saved recording...
          </div>
        )}

        {/* Notice stage */}
        {stage === "notice" && (
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-6 mb-6 fade-in" data-testid="recording-notice">
            <div className="flex items-start gap-3 mb-4">
              <Info className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
              <div>
                <h3 className="font-semibold text-amber-900 mb-2 font-display">Recording Notice</h3>
                <p className="text-amber-800 text-sm leading-relaxed">{RECORDING_NOTICE}</p>
              </div>
            </div>
            <button
              onClick={logNotice}
              className="w-full bg-[#1E3A8A] text-white py-2.5 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors flex items-center justify-center gap-2"
              data-testid="acknowledge-notice-btn"
            >
              I understand — Proceed to Recording
              <ArrowRight className="w-4 h-4" />
            </button>
            {/* Dynamic Prep shortcut — shown before recording starts */}
            {(user?.role === "manager" || user?.role === "admin") && !prep && (
              <button
                onClick={() => navigate(`/meetings/${meetingId}/prepare?from=record`)}
                className="w-full mt-3 flex items-center justify-center gap-2 text-indigo-700 bg-indigo-50 border border-indigo-200 py-2 rounded-md text-sm font-medium hover:bg-indigo-100 transition-colors"
                data-testid="prepare-from-notice-btn"              >
                <Sparkles className="w-4 h-4" />
                Generate a prep agenda first (optional)
              </button>
            )}
          </div>
        )}

        {/* Recording controls */}
        {["ready", "recording", "paused", "stopped"].includes(stage) && (
          <div className="bg-white border border-gray-200 rounded-xl p-6 sm:p-8 shadow-sm fade-in">
            {/* Timer */}
            <div className="text-center mb-8 sm:mb-10">
              <div
                className={`text-5xl sm:text-6xl font-mono font-bold tracking-tight mb-2 ${stage === "recording" ? "text-[#DC2626]" : "text-gray-400"}`}
                data-testid="recording-timer"
              >
                {formatDuration(elapsed)}
              </div>
              {pausedTotal > 0 && (
                <p className="text-sm text-amber-600">
                  <Clock className="inline w-3.5 h-3.5 mr-1" />
                  Paused for {formatDuration(pausedTotal)} total
                </p>
              )}
              {stage === "recording" && (
                <div className="flex items-center justify-center gap-3 mt-2 flex-wrap">
                  <div className="flex items-center gap-2">
                    <div className="w-2.5 h-2.5 bg-[#DC2626] rounded-full recording-pulse"></div>
                    <span className="text-sm text-[#DC2626] font-medium">Recording in progress</span>
                  </div>
                  {wakeLockActive && (
                    <span className="flex items-center gap-1 text-xs text-emerald-600 bg-emerald-50 border border-emerald-200 rounded-full px-2 py-0.5" title="Screen will not dim during recording" data-testid="wake-lock-indicator">
                      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" /></svg>
                      Screen stay-on
                    </span>
                  )}
                </div>
              )}
              {stage === "paused" && (
                <div className="flex items-center justify-center gap-2 mt-2">
                  <div className="w-2.5 h-2.5 bg-amber-500 rounded-full"></div>
                  <span className="text-sm text-amber-600 font-medium">Paused — sensitive discussion</span>
                </div>
              )}
            </div>

            {/* Controls */}
            <div className="flex items-center justify-center gap-4 sm:gap-6">
              {stage === "ready" && (
                <>
                  {/* Dynamic Prep shortcut — visible to managers/admins before start */}
                  {(user?.role === "manager" || user?.role === "admin") && (
                    <button
                      onClick={() => navigate(`/meetings/${meetingId}/prepare?from=record`)}
                      className="flex flex-col items-center justify-center gap-1.5 border-2 border-indigo-300 text-indigo-700 bg-indigo-50 rounded-2xl px-5 py-4 hover:bg-indigo-100 transition-all"
                      data-testid="prepare-meeting-btn"
                    >
                      <Sparkles className="w-6 h-6" />
                      <span className="text-xs font-semibold">Prepare</span>
                    </button>
                  )}
                  <button
                    onClick={startRecording}
                    className="flex flex-col items-center justify-center gap-2 bg-[#DC2626] text-white rounded-full w-28 h-28 sm:w-32 sm:h-32 shadow-lg hover:bg-red-700 active:scale-95 transition-all touch-manipulation"
                    data-testid="start-recording-btn"
                  >
                    <Mic className="w-9 h-9 sm:w-10 sm:h-10" />
                    <span className="text-xs font-semibold tracking-wide">TAP TO START</span>
                  </button>
                </>
              )}

              {stage === "recording" && (
                <>
                  <button
                    onClick={pauseRecording}
                    className="flex flex-col items-center gap-2 px-5 py-4 sm:px-6 sm:py-5 border-2 border-amber-400 text-amber-700 rounded-xl hover:bg-amber-50 active:scale-95 transition-all touch-manipulation min-w-[80px]"
                    data-testid="pause-recording-btn"
                  >
                    <Pause className="w-7 h-7 sm:w-8 sm:h-8" />
                    <span className="text-xs font-semibold">Pause</span>
                  </button>
                  <div className="flex flex-col items-center justify-center gap-1.5 bg-[#DC2626] text-white rounded-full w-24 h-24 sm:w-28 sm:h-28 recording-pulse shadow-lg cursor-default flex-shrink-0">
                    <Mic className="w-8 h-8 sm:w-9 sm:h-9" />
                    <span className="text-xs font-bold tracking-wide">REC</span>
                  </div>
                  <button
                    onClick={stopRecording}
                    className="flex flex-col items-center gap-2 px-5 py-4 sm:px-6 sm:py-5 border-2 border-gray-300 text-gray-700 rounded-xl hover:bg-gray-50 active:scale-95 transition-all touch-manipulation min-w-[80px]"
                    data-testid="stop-recording-btn"
                  >
                    <Square className="w-7 h-7 sm:w-8 sm:h-8" />
                    <span className="text-xs font-semibold">Stop</span>
                  </button>
                </>
              )}

              {stage === "paused" && (
                <>
                  <button
                    onClick={resumeRecording}
                    className="flex flex-col items-center gap-2 px-5 py-4 sm:px-6 sm:py-5 bg-[#1E3A8A] text-white rounded-xl hover:bg-[#1E40AF] active:scale-95 transition-all touch-manipulation min-w-[80px]"
                    data-testid="resume-recording-btn"
                  >
                    <Play className="w-7 h-7 sm:w-8 sm:h-8" />
                    <span className="text-xs font-semibold">Resume</span>
                  </button>
                  <div className="flex flex-col items-center justify-center gap-1.5 bg-amber-100 text-amber-700 rounded-full w-24 h-24 sm:w-28 sm:h-28 border-2 border-amber-300 flex-shrink-0 cursor-default">
                    <MicOff className="w-8 h-8 sm:w-9 sm:h-9" />
                    <span className="text-xs font-bold">PAUSED</span>
                  </div>
                  <button
                    onClick={stopRecording}
                    className="flex flex-col items-center gap-2 px-5 py-4 sm:px-6 sm:py-5 border-2 border-gray-300 text-gray-700 rounded-xl hover:bg-gray-50 active:scale-95 transition-all touch-manipulation min-w-[80px]"
                    data-testid="stop-paused-recording-btn"
                  >
                    <Square className="w-7 h-7 sm:w-8 sm:h-8" />
                    <span className="text-xs font-semibold">Stop</span>
                  </button>
                </>
              )}

              {stage === "stopped" && (
                <div className="flex flex-col items-center gap-4">
                  <div className="flex items-center justify-center w-24 h-24 bg-gray-100 rounded-full">
                    <MicOff className="w-10 h-10 text-gray-400" />
                  </div>
                  <p className="text-sm text-gray-500">Recording stopped</p>
                  {savedBlob && !uploadFailed && (
                    <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-lg p-3 max-w-xs text-xs text-amber-800">
                      <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
                      <span>A saved recording was found for this meeting — your audio was preserved. Click Upload to process it.</span>
                    </div>
                  )}
                  <button
                    onClick={handleUpload}
                    className={`flex items-center gap-2 ${uploadFailed ? "bg-red-600 hover:bg-red-700" : "bg-[#1E3A8A] hover:bg-[#1E40AF]"} text-white px-6 py-3 rounded-lg text-sm font-medium active:scale-95 transition-all touch-manipulation`}
                    data-testid="upload-process-btn"
                  >
                    <Upload className="w-4 h-4" />
                    {uploadFailed ? "Retry Upload" : savedBlob ? "Upload Saved Recording" : "Upload & Process"}
                  </button>
                  {uploadFailed && (
                    <p className="text-xs text-red-500 text-center max-w-xs">
                      Upload failed — your audio is still saved in this browser. Check the error above, then click Retry.
                    </p>
                  )}
                </div>
              )}
            </div>

            {(stage === "ready" || stage === "recording" || stage === "paused") && (
              <p className="text-center text-xs text-gray-400 mt-6 leading-relaxed max-w-sm mx-auto">
                {stage === "paused"
                  ? "Audio is not being recorded during this pause. Sensitive discussion will not be captured."
                  : "Use Pause for any sensitive or personal discussion — paused audio is never recorded."}
              </p>
            )}
          </div>
        )}

        {/* ── Unified processing progress ─────────────────────────────────── */}
        {(stage === "uploading" || stage === "processing") && (() => {
          // Derive per-step state
          const step1 = stage === "processing"
            ? { state: "complete", progress: 100, right: "Complete" }
            : { state: "active", progress: uploadProgress, right: `${uploadProgress}%` };

          const transcribingActive = stage === "processing" && ["processing", "transcribing"].includes(processingStatus);
          const transcribingDone  = stage === "processing" && ["analyzing", "in_review", "reviewed", "signed_off"].includes(processingStatus);
          const step2 = transcribingDone
            ? { state: "complete", progress: 100, right: "Complete" }
            : transcribingActive
            ? { state: "active", progress: step2Progress, right: "~1–5 minutes" }
            : { state: "waiting", progress: 0, right: "Waiting" };

          const analyzingActive = stage === "processing" && processingStatus === "analyzing";
          const analyzingDone   = stage === "processing" && ["in_review", "reviewed", "signed_off"].includes(processingStatus);
          const step3 = analyzingDone
            ? { state: "complete", progress: 100, right: "Complete" }
            : analyzingActive
            ? { state: "active", progress: step3Progress, right: "~1–3 minutes" }
            : { state: "waiting", progress: 0, right: "Waiting" };

          const steps = [
            { num: 1, label: "Uploading & Compressing Audio", ...step1 },
            { num: 2, label: "Transcribing Recording",        ...step2 },
            { num: 3, label: "Mapping Compliance Evidence",   ...step3 },
          ];

          const barColor = s => s === "complete" ? "#22C55E" : s === "active" ? "#1E3A8A" : "#D1D5DB";
          const bgColor  = s => s === "complete" ? "#F0FDF4" : s === "active" ? "#EFF6FF" : "white";
          const borderColor = s => s === "complete" ? "#BBF7D0" : s === "active" ? "#BFDBFE" : "#E5E7EB";
          const labelColor  = s => s === "complete" ? "#15803D" : s === "active" ? "#1E3A8A" : "#9CA3AF";
          const rightColor  = s => s === "complete" ? "#22C55E" : s === "active" ? "#1E3A8A" : "#9CA3AF";

          return (
            <div className="fade-in" data-testid="unified-processing-screen">
              <div className="text-center mb-8">
                <div className="w-12 h-12 border-[3px] border-[#1E3A8A] border-t-transparent rounded-full spin mx-auto mb-4"></div>
                <h2 className="text-xl font-bold text-gray-900 font-display">Processing your recording</h2>
                <p className="text-sm text-gray-500 mt-1">This page will update automatically — you can safely leave and come back</p>
              </div>

              {processingError && (
                <div className="mb-4 bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
                  <p className="font-semibold mb-1">Processing failed</p>
                  <p className="font-mono text-xs whitespace-pre-wrap">{processingError}</p>
                </div>
              )}

              <div className="space-y-3">
                {steps.map(({ num, label, state, progress, right }) => (
                  <div
                    key={num}
                    style={{ background: bgColor(state), borderColor: borderColor(state) }}
                    className="border rounded-xl px-5 py-4 transition-all duration-500"
                  >
                    <div className="flex items-center gap-3 mb-3">
                      {state === "complete" ? (
                        <div className="w-8 h-8 rounded-full bg-emerald-500 flex items-center justify-center flex-shrink-0">
                          <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" /></svg>
                        </div>
                      ) : (
                        <div
                          style={{ background: state === "active" ? "#1E3A8A" : "#E5E7EB", color: state === "active" ? "white" : "#9CA3AF" }}
                          className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 text-sm font-bold"
                        >
                          {num}
                        </div>
                      )}
                      <span style={{ color: labelColor(state) }} className="font-semibold text-sm flex-1">{label}</span>
                      <span style={{ color: rightColor(state) }} className="text-sm font-medium">{right}</span>
                    </div>
                    <div className="h-1.5 w-full bg-gray-200 rounded-full overflow-hidden">
                      <div
                        style={{ width: `${progress}%`, background: barColor(state), transition: "width 0.8s ease-out" }}
                        className="h-full rounded-full"
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })()}

        {/* Event timeline */}
        {events.length > 0 && (
          <div className="mt-6 bg-white border border-gray-200 rounded-lg p-4 shadow-sm" data-testid="event-timeline">
            <h4 className="text-xs font-semibold uppercase text-gray-500 tracking-wider mb-3">Recording Timeline</h4>
            <div className="space-y-2">
              {events.map((ev, i) => (
                <div key={`${ev.time}-${ev.label}`} className="flex items-center gap-3 text-sm">
                  <span className={`font-mono text-xs ${eventIcons[ev.type]}`}>{ev.time}</span>
                  <div className={`w-1.5 h-1.5 rounded-full ${ev.type === "start" ? "bg-emerald-500" : ev.type === "pause" ? "bg-amber-500" : ev.type === "resume" ? "bg-blue-500" : "bg-red-500"}`}></div>
                  <span className="text-gray-700">{ev.label}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
}

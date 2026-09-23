import React, { useState, useEffect, useMemo } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Download, Search, Loader2, ShieldAlert, X } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const STATUS_LABELS = {
  draft: "Draft", recording: "Recording", stopped: "Stopped", processing: "Processing",
  transcribing: "Transcribing", analyzing: "Analysing", in_review: "In Review",
  reviewed: "Reviewed", processing_failed: "Failed",
};

function ConsentModal({ meeting, orgName, onCancel, onConfirm, downloading }) {
  const [agreed, setAgreed] = useState(false);
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" data-testid="audio-consent-modal">
      <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-6">
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-2">
            <ShieldAlert className="w-5 h-5 text-amber-500 flex-shrink-0" />
            <h3 className="text-sm font-semibold text-gray-900">Data Protection Notice</h3>
          </div>
          <button onClick={onCancel} className="text-gray-400 hover:text-gray-600" data-testid="audio-consent-close-btn">
            <X className="w-4 h-4" />
          </button>
        </div>
        <p className="text-sm text-gray-600 italic leading-relaxed mb-4">
          Downloading raw audio transfers data controller responsibility for this file directly to{" "}
          <strong className="not-italic">{orgName || "your organisation"}</strong>. Ensure this recording is
          stored in a secure, access-controlled directory in accordance with your internal UK GDPR and DSPT
          policies.
        </p>
        <p className="text-xs text-gray-500 mb-4">
          Downloading <span className="font-medium text-gray-700">"{meeting.title}"</span> will be recorded in
          the audit trail, including your name and IP address.
        </p>
        <label className="flex items-start gap-2.5 mb-5 cursor-pointer">
          <input
            type="checkbox"
            checked={agreed}
            onChange={e => setAgreed(e.target.checked)}
            className="w-4 h-4 mt-0.5 accent-[#1E3A8A]"
            data-testid="audio-consent-checkbox"
          />
          <span className="text-sm text-gray-700">I understand and agree</span>
        </label>
        <div className="flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="text-sm px-4 py-2 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 transition-colors"
            data-testid="audio-consent-cancel-btn"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={!agreed || downloading}
            className="flex items-center gap-2 text-sm px-4 py-2 rounded-lg bg-[#1E3A8A] text-white hover:bg-[#1E40AF] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            data-testid="audio-consent-confirm-btn"
          >
            {downloading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {downloading ? "Downloading…" : "Download Audio"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function DownloadAudioTab() {
  const { API, getAuthConfig, user } = useAuth();
  const [meetings, setMeetings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [pendingMeeting, setPendingMeeting] = useState(null);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    axios.get(`${API}/meetings/downloadable-audio`, getAuthConfig())
      .then(res => setMeetings(res.data || []))
      .catch(() => toast.error("Failed to load meetings"))
      .finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return meetings;
    return meetings.filter(m => (m.title || "").toLowerCase().includes(q));
  }, [meetings, search]);

  const handleConfirmDownload = async () => {
    const meeting = pendingMeeting;
    setDownloading(true);
    try {
      const res = await axios.get(
        `${API}/meetings/${meeting.id}/audio-download?consent=true`,
        { ...getAuthConfig(), responseType: "blob" }
      );
      const url = URL.createObjectURL(res.data);
      const disposition = res.headers["content-disposition"] || "";
      const match = disposition.match(/filename="?([^"]+)"?/);
      const safeTitle = (meeting.title || "audio").replace(/[^a-z0-9 _-]/gi, "").trim().replace(/\s+/g, "_");
      const a = document.createElement("a");
      a.href = url;
      a.download = match ? match[1] : `${safeTitle || "audio"}.webm`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast.success("Audio downloaded");
      setPendingMeeting(null);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to download audio");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="max-w-2xl" data-testid="download-audio-tab">
      <p className="text-sm text-gray-500 mb-1">
        Download the raw recording for a meeting if circumstances require it — for example, a complaint or
        investigation. Only available before a meeting is signed off; audio is deleted shortly after sign-off
        as part of our data-minimisation policy.
      </p>
      <p className="text-xs text-gray-400 mb-5">
        You can only download audio for meetings you are the sign-off manager for (admins can download any
        meeting in the organisation).
      </p>

      <div className="relative mb-4">
        <Search className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search meetings by title…"
          className="w-full pl-9 pr-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
          data-testid="download-audio-search"
        />
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-xs text-gray-400"><Loader2 className="w-3.5 h-3.5 animate-spin" />Loading meetings…</div>
      ) : filtered.length === 0 ? (
        <p className="text-xs text-gray-400" data-testid="download-audio-empty">
          {meetings.length === 0 ? "No meetings with audio available to download right now." : "No meetings match your search."}
        </p>
      ) : (
        <div className="border border-gray-200 rounded-lg divide-y divide-gray-100 max-h-96 overflow-y-auto" data-testid="download-audio-list">
          {filtered.map(m => (
            <div key={m.id} className="flex items-center gap-3 px-4 py-3" data-testid={`download-audio-row-${m.id}`}>
              <div className="flex-1 min-w-0">
                <p className="text-sm text-gray-800 truncate">{m.title}</p>
                <p className="text-xs text-gray-400">
                  {m.date ? new Date(m.date).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : ""}
                  {" · "}{STATUS_LABELS[m.status] || m.status}
                </p>
              </div>
              <button
                onClick={() => setPendingMeeting(m)}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 transition-colors flex-shrink-0"
                data-testid={`download-audio-btn-${m.id}`}
              >
                <Download className="w-3.5 h-3.5" />
                Download
              </button>
            </div>
          ))}
        </div>
      )}

      {pendingMeeting && (
        <ConsentModal
          meeting={pendingMeeting}
          orgName={user?.org_name}
          downloading={downloading}
          onCancel={() => setPendingMeeting(null)}
          onConfirm={handleConfirmDownload}
        />
      )}
    </div>
  );
}

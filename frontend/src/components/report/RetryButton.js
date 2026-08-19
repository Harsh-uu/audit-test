import React, { useState } from "react";
import axios from "axios";
import { RefreshCw } from "lucide-react";

export function RetryButton({ meetingId, onRetry, API, getAuthConfig }) {
  const [retrying, setRetrying] = useState(false);
  const [msg, setMsg] = useState("");
  const handleRetry = async () => {
    setRetrying(true);
    setMsg("");
    try {
      await axios.post(`${API}/processing/${meetingId}/retry`, {}, getAuthConfig());
      setMsg("Retry started — the page will update automatically.");
      setTimeout(onRetry, 3000);
    } catch (err) {
      setMsg(err.response?.data?.detail || "Retry failed");
    } finally {
      setRetrying(false);
    }
  };
  return (
    <div>
      <button
        onClick={handleRetry}
        disabled={retrying}
        data-testid="retry-processing-btn"
        className="inline-flex items-center gap-2 bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors disabled:opacity-50"
      >
        <RefreshCw className={`w-4 h-4 ${retrying ? "animate-spin" : ""}`} />
        {retrying ? "Retrying…" : "Retry Processing"}
      </button>
      {msg && <p className="text-xs text-gray-500 mt-2">{msg}</p>}
    </div>
  );
}

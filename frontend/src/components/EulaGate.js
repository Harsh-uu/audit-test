import React, { useState, useEffect } from "react";
import axios from "axios";
import { useLocation } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { ShieldCheck, Loader2 } from "lucide-react";

const API = "/api";
const PUBLIC_PATHS = ["/login", "/reset-password", "/accept-invite", "/set-password", "/checkout", "/checkout-cancelled", "/onboard"];

// Blocking EULA acceptance prompt, mounted once at the app root (not inside
// ProtectedRoute — that re-mounts per route). Fetches once per login; the
// user gets up to 3 "Remind me later" dismissals before it becomes a true
// hard block (no dismiss option, must click "I Agree" to continue).
export function EulaGate() {
  const { user } = useAuth();
  const location = useLocation();
  const [eula, setEula] = useState(null);
  const [accepting, setAccepting] = useState(false);
  const [dismissedThisSession, setDismissedThisSession] = useState(false);

  useEffect(() => {
    if (!user || user.must_change_password) return;
    let active = true;
    axios.get(`${API}/eula/current`).then(({ data }) => {
      if (active) setEula(data);
    }).catch(() => {});
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);

  if (!user || user.must_change_password) return null;
  if (PUBLIC_PATHS.includes(location.pathname)) return null;
  if (!eula || !eula.needs_acceptance || dismissedThisSession) return null;

  const canDismiss = eula.decline_count < 3;

  const handleAgree = async () => {
    setAccepting(true);
    try {
      await axios.post(`${API}/eula/accept`);
      setEula(e => ({ ...e, needs_acceptance: false }));
    } catch {
      setAccepting(false);
    }
  };

  const handleRemindLater = async () => {
    try {
      const { data } = await axios.post(`${API}/eula/decline`);
      setEula(e => ({ ...e, decline_count: data.decline_count }));
    } catch { /* still dismiss for this session even if the log-call failed */ }
    setDismissedThisSession(true);
  };

  return (
    <>
      <div className="fixed inset-0 bg-black/60 z-[200]" data-testid="eula-modal-backdrop" />
      <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
        <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg flex flex-col max-h-[85vh]" data-testid="eula-modal">
          <div className="px-6 py-5 border-b border-gray-100 flex items-center gap-2.5 flex-shrink-0">
            <ShieldCheck className="w-5 h-5 text-[#1E3A8A] flex-shrink-0" />
            <h2 className="font-bold font-display text-[#1E3A8A] text-lg">End User Licence Agreement</h2>
          </div>
          <div className="flex-1 overflow-y-auto px-6 py-5 text-sm text-gray-600 whitespace-pre-wrap leading-relaxed" data-testid="eula-content">
            {eula.content}
          </div>
          {!canDismiss && (
            <p className="px-6 pb-1 text-xs text-amber-600 font-medium flex-shrink-0" data-testid="eula-hard-block-notice">
              You must accept this agreement to continue using 1two.one.
            </p>
          )}
          <div className="px-6 py-4 border-t border-gray-100 flex items-center justify-end gap-3 flex-shrink-0">
            {canDismiss && (
              <button
                onClick={handleRemindLater}
                data-testid="eula-remind-later-btn"
                className="px-4 py-2 rounded-lg text-sm font-medium text-gray-500 hover:bg-gray-50 transition-colors"
              >
                Remind me later
              </button>
            )}
            <button
              onClick={handleAgree}
              disabled={accepting}
              data-testid="eula-agree-btn"
              className="flex items-center gap-2 px-5 py-2 bg-[#1E3A8A] text-white rounded-lg text-sm font-semibold hover:bg-[#1e40af] disabled:opacity-60 transition-colors"
            >
              {accepting ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
              I Agree
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

import React, { useState, useEffect } from "react";
import { X, Share2, Check, Users, Loader } from "lucide-react";
import axios from "axios";
import { useAuth } from "../../context/AuthContext";

export function ShareModal({ show, onClose, meeting, onShared }) {
  const { API, getAuthConfig } = useAuth();
  const [orgUsers, setOrgUsers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [selectedIds, setSelectedIds] = useState([]);

  useEffect(() => {
    if (!show) return;
    setSelectedIds([]);
    setLoading(true);
    axios.get(`${API}/admin/users`, getAuthConfig())
      .then(res => setOrgUsers(res.data || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [show, API, getAuthConfig]);

  if (!show) return null;

  const attendeeIds = new Set((meeting?.attendees || []).map(a => a.user_id).filter(Boolean));
  const sharedIds = new Set((meeting?.shared_with || []).map(s => s.user_id).filter(Boolean));

  // Only show users not already an attendee
  const candidates = orgUsers.filter(u => !attendeeIds.has(u.id));

  const toggle = (id) => {
    setSelectedIds(prev => prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id]);
  };

  const handleShare = async () => {
    if (!selectedIds.length) return;
    setSharing(true);
    try {
      const { data } = await axios.post(
        `${API}/review/${meeting.id}/share`,
        { user_ids: selectedIds },
        getAuthConfig()
      );
      onShared?.(data.shared_with);
      onClose();
    } catch (err) {
      alert(err?.response?.data?.detail || "Share failed");
    } finally {
      setSharing(false);
    }
  };

  const newCount = selectedIds.filter(id => !sharedIds.has(id)).length;

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md">
        <div className="flex items-center justify-between px-6 pt-5 pb-4 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <Share2 className="w-4 h-4 text-indigo-600" />
            <h3 className="font-semibold text-gray-900">Share this report</h3>
          </div>
          <button onClick={onClose}><X className="w-4 h-4 text-gray-400 hover:text-gray-600" /></button>
        </div>

        <div className="px-6 py-4">
          <p className="text-sm text-gray-500 mb-4">
            Grant read access to this signed-off report for team members who weren't in the meeting.
          </p>

          {/* Already shared */}
          {sharedIds.size > 0 && (
            <div className="mb-4">
              <p className="text-xs font-medium text-gray-500 mb-2 uppercase tracking-wide">Already shared with</p>
              <div className="flex flex-wrap gap-2">
                {(meeting?.shared_with || []).map(s => (
                  <span key={s.user_id} className="flex items-center gap-1 text-xs px-2.5 py-1 bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-full">
                    <Check className="w-3 h-3" /> {s.name}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Candidate users */}
          <p className="text-xs font-medium text-gray-500 mb-2 uppercase tracking-wide">
            {sharedIds.size > 0 ? "Add more" : "Select people"}
          </p>

          {loading ? (
            <div className="flex items-center justify-center py-6">
              <Loader className="w-5 h-5 text-gray-400 animate-spin" />
            </div>
          ) : candidates.length === 0 ? (
            <p className="text-sm text-gray-400 italic py-4 text-center">All org members are already attendees or shared.</p>
          ) : (
            <div className="space-y-1.5 max-h-56 overflow-y-auto">
              {candidates.map(u => {
                const isAlreadyShared = sharedIds.has(u.id);
                const isSelected = selectedIds.includes(u.id);
                return (
                  <button
                    key={u.id}
                    onClick={() => !isAlreadyShared && toggle(u.id)}
                    disabled={isAlreadyShared}
                    data-testid={`share-user-${u.id}`}
                    className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg border text-left transition-colors ${
                      isAlreadyShared
                        ? "border-emerald-200 bg-emerald-50 opacity-70 cursor-default"
                        : isSelected
                          ? "border-indigo-300 bg-indigo-50"
                          : "border-gray-200 hover:bg-gray-50"
                    }`}
                  >
                    <div className={`w-5 h-5 rounded border-2 flex items-center justify-center flex-shrink-0 transition-colors ${
                      isAlreadyShared ? "bg-emerald-400 border-emerald-400 text-white"
                        : isSelected ? "bg-indigo-600 border-indigo-600 text-white"
                          : "border-gray-300"
                    }`}>
                      {(isSelected || isAlreadyShared) && <Check className="w-3 h-3" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-800 truncate">{u.name}</p>
                      <p className="text-xs text-gray-400 truncate">{u.email} · {u.role}</p>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className="flex gap-2 justify-end px-6 pb-5">
          <button onClick={onClose} className="px-4 py-2 text-sm border border-gray-200 text-gray-600 rounded-lg hover:bg-gray-50">
            Cancel
          </button>
          <button
            onClick={handleShare}
            disabled={newCount === 0 || sharing}
            className="flex items-center gap-2 px-4 py-2 text-sm bg-[#1E3A8A] text-white rounded-lg font-medium hover:bg-[#1E40AF] disabled:opacity-40 transition-colors"
            data-testid="confirm-share-btn"
          >
            {sharing ? <Loader className="w-3.5 h-3.5 animate-spin" /> : <Users className="w-3.5 h-3.5" />}
            {sharing ? "Sharing…" : `Share with ${newCount} person${newCount !== 1 ? "s" : ""}`}
          </button>
        </div>
      </div>
    </div>
  );
}

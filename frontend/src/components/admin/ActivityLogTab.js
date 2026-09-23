import React, { useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { UserX, Trash2, MailX, History, Loader2 } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const ACTION_CONFIG = {
  user_deactivated: { label: "Staff deactivated", icon: UserX, color: "text-amber-600 bg-amber-50" },
  user_hard_deleted: { label: "Staff permanently deleted", icon: Trash2, color: "text-red-600 bg-red-50" },
  invite_revoked: { label: "Invite revoked", icon: MailX, color: "text-gray-500 bg-gray-100" },
};

export function ActivityLogTab() {
  const { API, getAuthConfig } = useAuth();
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get(`${API}/admin/activity-log`, getAuthConfig())
      .then(res => setEntries(res.data || []))
      .catch(() => toast.error("Failed to load activity log"))
      .finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="max-w-2xl" data-testid="activity-log-tab">
      <p className="text-sm text-gray-500 mb-1">
        A chronological record of staff lifecycle actions across your organisation — who deactivated or
        permanently deleted an account, and when.
      </p>
      <p className="text-xs text-gray-400 mb-5">
        Only Deactivate and Delete Permanently actions are tracked here. Admin only.
      </p>

      {loading ? (
        <div className="flex items-center gap-2 text-xs text-gray-400"><Loader2 className="w-3.5 h-3.5 animate-spin" />Loading activity…</div>
      ) : entries.length === 0 ? (
        <div className="text-center py-12 text-gray-400" data-testid="activity-log-empty">
          <History className="w-8 h-8 mx-auto mb-2 opacity-30" />
          <p className="text-xs font-medium">No activity yet</p>
          <p className="text-[11px] mt-1">Deactivate or Delete Permanently actions will appear here.</p>
        </div>
      ) : (
        <div className="border border-gray-200 rounded-lg divide-y divide-gray-100 max-h-[32rem] overflow-y-auto" data-testid="activity-log-list">
          {entries.map(e => {
            const cfg = ACTION_CONFIG[e.action] || { label: e.action, icon: History, color: "text-gray-500 bg-gray-100" };
            const Icon = cfg.icon;
            const when = e.timestamp ? new Date(e.timestamp).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
            return (
              <div key={e.id} className="flex items-start gap-3 px-4 py-3" data-testid={`activity-log-row-${e.id}`}>
                <div className={`w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 ${cfg.color}`}>
                  <Icon className="w-3.5 h-3.5" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-800">{cfg.label}</p>
                  <p className="text-xs text-gray-500 mt-0.5">{e.detail}</p>
                  <p className="text-[11px] text-gray-400 mt-1">By {e.actor_name || "Unknown"} · {when}</p>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

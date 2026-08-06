import React, { useState, useEffect, useCallback } from "react";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import { FileText, Download, Palette, CheckCircle, AlertCircle, X, Target, Plus, Trash2, Star, Shield } from "lucide-react";
import { TemplateTab } from "@/components/admin/TemplateTab";
import { ExportTab } from "@/components/admin/ExportTab";
import { BrandingTab } from "@/components/admin/BrandingTab";
import { TranscriptExportTab } from "@/components/admin/TranscriptExportTab";
import { toast } from "sonner";

function FocusTopicsTab({ API, getAuthConfig }) {
  const [topics, setTopics]   = useState([]);
  const [newTopic, setNewTopic] = useState("");
  const [newMonth, setNewMonth] = useState("");
  const [saving, setSaving]   = useState(false);
  const thisMonth = new Date().toISOString().slice(0, 7);

  const load = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/prep/focus-topics`, getAuthConfig());
      setTopics(data || []);
    } catch { toast.error("Failed to load focus topics"); }
  }, [API, getAuthConfig]);

  useEffect(() => { load(); }, [load]);

  const handleAdd = async () => {
    if (!newTopic.trim()) return;
    setSaving(true);
    try {
      await axios.post(`${API}/prep/focus-topics`, {
        topic: newTopic.trim(),
        is_current: topics.length === 0,
        active_month: newMonth || null,
      }, getAuthConfig());
      setNewTopic(""); setNewMonth("");
      await load();
      toast.success("Focus topic added");
    } catch (err) { toast.error(err.response?.data?.detail || "Failed to add"); }
    finally { setSaving(false); }
  };

  const handleSetCurrent = async (topic) => {
    try {
      await axios.put(`${API}/prep/focus-topics/${topic.id}`, {
        topic: topic.topic, is_current: true, active_month: topic.active_month || null,
      }, getAuthConfig());
      await load();
      toast.success("Current focus topic updated");
    } catch { toast.error("Failed to update"); }
  };

  const handleDelete = async (id) => {
    try {
      await axios.delete(`${API}/prep/focus-topics/${id}`, getAuthConfig());
      setTopics(t => t.filter(x => x.id !== id));
    } catch { toast.error("Failed to delete"); }
  };

  const formatMonth = (ym) => {
    if (!ym) return null;
    const [y, m] = ym.split("-");
    return new Date(+y, +m - 1).toLocaleString("default", { month: "long", year: "numeric" });
  };

  return (
    <div className="space-y-5 max-w-xl">
      <div>
        <h3 className="text-sm font-semibold text-gray-800 mb-0.5">Organisational Focus Topics</h3>
        <p className="text-xs text-gray-500">
          Set supervision focus topics and optionally assign them to a month — the right topic activates automatically. Managers see the active topic in Dynamic Supervision Prep.
        </p>
      </div>

      {/* Add new */}
      <div className="space-y-2">
        <input
          type="text"
          value={newTopic}
          onChange={e => setNewTopic(e.target.value)}
          onKeyDown={e => e.key === "Enter" && handleAdd()}
          placeholder="e.g. Medication management, Safeguarding, Personal development…"
          className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
          data-testid="new-focus-topic-input"
        />
        <div className="flex gap-2 items-end">
          <div className="flex-1">
            <label className="block text-xs text-gray-500 mb-1">Assign to month <span className="text-gray-400">(optional)</span></label>
            <input
              type="month"
              value={newMonth}
              onChange={e => setNewMonth(e.target.value)}
              className="w-full px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
              data-testid="new-focus-topic-month"
            />
          </div>
          <button
            onClick={handleAdd}
            disabled={saving || !newTopic.trim()}
            className="flex items-center gap-1.5 px-4 py-2 bg-[#1E3A8A] text-white text-sm font-medium rounded-lg hover:bg-[#1E40AF] disabled:opacity-60 transition-colors"
            data-testid="add-focus-topic-btn"
          >
            <Plus className="w-4 h-4" /> Add
          </button>
        </div>
      </div>

      {/* Topic list */}
      {topics.length === 0 && (
        <p className="text-xs text-gray-400 italic">No focus topics yet — add the first one above.</p>
      )}
      <div className="space-y-2">
        {topics.map(t => {
          const isActiveMonth = t.active_month === thisMonth;
          const isCurrent = t.effective_current || t.is_current;
          return (
            <div
              key={t.id}
              className={`flex items-center gap-3 p-3 rounded-xl border-2 transition-all ${
                isCurrent ? "border-indigo-300 bg-indigo-50" : "border-gray-200 bg-white"
              }`}
              data-testid={`focus-topic-row-${t.id}`}
            >
              {isCurrent && <Star className="w-4 h-4 text-indigo-600 flex-shrink-0" fill="currentColor" />}
              <div className="flex-1 min-w-0">
                <span className={`text-sm ${isCurrent ? "font-semibold text-indigo-800" : "text-gray-700"}`}>{t.topic}</span>
                {t.active_month && (
                  <p className="mt-0.5">
                    <span className={`inline-flex items-center text-xs font-medium px-2 py-0.5 rounded-full ${
                      isActiveMonth ? "bg-emerald-100 text-emerald-700" : "bg-gray-100 text-gray-500"
                    }`}>
                      {isActiveMonth ? "Active — " : ""}{formatMonth(t.active_month)}
                    </span>
                  </p>
                )}
              </div>
              {isCurrent && !t.active_month && (
                <span className="text-xs font-medium text-indigo-600 bg-indigo-100 px-2 py-0.5 rounded-full">Current</span>
              )}
              {!isCurrent && !t.active_month && (
                <button
                  onClick={() => handleSetCurrent(t)}
                  className="text-xs text-gray-500 hover:text-indigo-600 border border-gray-200 hover:border-indigo-300 px-2.5 py-1 rounded-lg transition-colors"
                  data-testid={`set-current-topic-${t.id}`}
                >
                  Set as current
                </button>
              )}
              <button
                onClick={() => handleDelete(t.id)}
                className="p-1.5 text-gray-400 hover:text-red-500 rounded-lg transition-colors"
                data-testid={`delete-topic-${t.id}`}
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          );
        })}
      </div>
      <p className="text-xs text-gray-400">Topics with a month activate automatically. Topics without a month can be set manually as current.</p>
    </div>
  );
}



function SecurityTab({ API, getAuthConfig, user, updateMfaStatus }) {
  const [step, setStep] = useState("idle"); // "idle" | "sent" | "saving"
  const [code, setCode] = useState("");
  const [pendingEnable, setPendingEnable] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const isMfaOn = Boolean(user?.mfa_enabled);

  const requestCode = async (enable) => {
    setError("");
    setSuccess("");
    setPendingEnable(enable);
    try {
      await axios.post(`${API}/auth/request-mfa-code`, {}, getAuthConfig());
      setStep("sent");
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to send code. Please try again.");
    }
  };

  const confirmToggle = async (e) => {
    e.preventDefault();
    setError("");
    setStep("saving");
    try {
      const { data } = await axios.post(`${API}/auth/toggle-mfa`, { code: code.trim(), enable: pendingEnable }, getAuthConfig());
      updateMfaStatus(data.mfa_enabled);
      setSuccess(data.message);
      setStep("idle");
      setCode("");
    } catch (err) {
      setError(err.response?.data?.detail || "Invalid code. Please try again.");
      setStep("sent");
    }
  };

  return (
    <div className="max-w-xl">
      <div className="bg-white border border-gray-200 rounded-lg p-6">
        <div className="flex items-start gap-4">
          <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${isMfaOn ? "bg-emerald-100" : "bg-gray-100"}`}>
            <Shield className={`w-5 h-5 ${isMfaOn ? "text-emerald-600" : "text-gray-400"}`} />
          </div>
          <div className="flex-1">
            <h3 className="text-sm font-semibold text-gray-900">Two-Factor Authentication</h3>
            <p className="text-xs text-gray-500 mt-0.5">
              {isMfaOn
                ? "2FA is enabled. You will be asked for an email code on every sign-in."
                : "Add an extra layer of security. You will be emailed a code each time you sign in."}
            </p>
            <div className="mt-1">
              <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${isMfaOn ? "bg-emerald-50 text-emerald-700" : "bg-gray-100 text-gray-500"}`}>
                {isMfaOn ? "Enabled" : "Disabled"}
              </span>
            </div>
          </div>
        </div>

        {success && (
          <div className="mt-4 flex items-center gap-2 bg-emerald-50 border border-emerald-200 text-emerald-700 rounded p-3 text-sm">
            <CheckCircle className="w-4 h-4 flex-shrink-0" />{success}
          </div>
        )}
        {error && (
          <div className="mt-4 flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded p-3 text-sm">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />{error}
          </div>
        )}

        {step === "idle" && !success && (
          <div className="mt-5">
            <button
              onClick={() => requestCode(!isMfaOn)}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                isMfaOn
                  ? "bg-red-50 text-red-600 border border-red-200 hover:bg-red-100"
                  : "bg-[#1E3A8A] text-white hover:bg-[#1E40AF]"
              }`}
              data-testid="mfa-toggle-btn"
            >
              {isMfaOn ? "Disable 2FA" : "Enable 2FA"}
            </button>
          </div>
        )}

        {step === "sent" && (
          <form onSubmit={confirmToggle} className="mt-5 space-y-3">
            <p className="text-xs text-gray-600">
              A 6-digit code has been sent to <strong>{user?.email}</strong>. Enter it below to confirm.
            </p>
            <input
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={code}
              onChange={e => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
              placeholder="000000"
              maxLength={6}
              autoFocus
              className="w-40 px-3 py-2 border border-gray-300 rounded-md text-center text-lg font-mono tracking-[0.4em] focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
              data-testid="mfa-confirm-code-input"
            />
            <div className="flex gap-2">
              <button
                type="submit"
                disabled={code.length !== 6}
                className="px-4 py-2 bg-[#1E3A8A] text-white rounded-md text-sm font-medium hover:bg-[#1E40AF] disabled:opacity-60 transition-colors"
                data-testid="mfa-confirm-btn"
              >
                Confirm
              </button>
              <button
                type="button"
                onClick={() => { setStep("idle"); setCode(""); setError(""); }}
                className="px-4 py-2 bg-gray-100 text-gray-600 rounded-md text-sm font-medium hover:bg-gray-200 transition-colors"
              >
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>

      <p className="mt-3 text-xs text-gray-400">
        Codes expire after 10 minutes. Your password is required to disable 2FA on the next sign-in regardless.
      </p>
    </div>
  );
}


function TabBtn({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
        active ? "border-[#1E3A8A] text-[#1E3A8A]" : "border-transparent text-gray-500 hover:text-gray-700"
      }`}
    >
      {children}
    </button>
  );
}

export default function OrgSettings() {
  const { getAuthConfig, API, user, updateMfaStatus } = useAuth();
  const canBrand = user?.role === "admin" || user?.role === "manager";
  const [tab, setTab] = useState(user?.role === "manager" ? "security" : "template");
  const [message, setMessage] = useState("");
  const [error, setError]     = useState("");
  const [loading, setLoading] = useState(true);

  // ── Template state ────────────────────────────────────────────────────────
  const [template, setTemplate]           = useState({ name: "Supervision Template", description: "", steps: [] });
  const [templateSaving, setTemplateSaving] = useState(false);
  const [newStepTitle, setNewStepTitle]   = useState("");
  const [newStepDesc, setNewStepDesc]     = useState("");

  // ── Export + Transcript state (shared filters) ────────────────────────────
  const [users, setUsers]                           = useState([]);
  const [exportStaffIds, setExportStaffIds]         = useState([]);
  const [exportDateFrom, setExportDateFrom]         = useState("");
  const [exportDateTo, setExportDateTo]             = useState("");
  const [exportMeetings, setExportMeetings]         = useState([]);
  const [exportSelectedMeetings, setExportSelectedMeetings] = useState([]);
  const [exportLoading, setExportLoading]           = useState(false);
  const [txExportLoading, setTxExportLoading]       = useState(false);
  const [exportMeetingsLoading, setExportMeetingsLoading] = useState(false);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const [tmplRes, usersRes] = await Promise.all([
          axios.get(`${API}/admin/template`, getAuthConfig()),
          axios.get(`${API}/admin/users`, getAuthConfig()),
        ]);
        setTemplate(tmplRes.data || { name: "Supervision Template", description: "", steps: [] });
        setUsers(usersRes.data || []);
      } catch {
        setError("Failed to load settings. Please refresh.");
      }
      setLoading(false);
    };
    load();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fetchExportMeetings = async () => {
    setExportMeetingsLoading(true);
    try {
      const { data } = await axios.get(`${API}/admin/meetings-brief`, getAuthConfig());
      setExportMeetings(data);
    } catch { /* silent */ }
    setExportMeetingsLoading(false);
  };

  // ── Template handlers ─────────────────────────────────────────────────────
  const handleAddStep = () => {
    if (!newStepTitle.trim()) return;
    const steps = template.steps || [];
    setTemplate(t => ({ ...t, steps: [...steps, { id: `step_${Date.now()}`, order: steps.length + 1, title: newStepTitle.trim(), description: newStepDesc.trim() }] }));
    setNewStepTitle("");
    setNewStepDesc("");
  };

  const handleRemoveStep = (idx) => setTemplate(t => ({ ...t, steps: t.steps.filter((_, i) => i !== idx) }));

  const handleMoveStep = (idx, dir) => {
    const steps = [...template.steps];
    const target = idx + dir;
    if (target < 0 || target >= steps.length) return;
    [steps[idx], steps[target]] = [steps[target], steps[idx]];
    steps.forEach((s, i) => { s.order = i + 1; });
    setTemplate(t => ({ ...t, steps }));
  };

  const handleSaveTemplate = async () => {
    setTemplateSaving(true);
    setError("");
    try {
      await axios.put(`${API}/admin/template`, template, getAuthConfig());
      setMessage("Supervision template saved");
    } catch { setError("Failed to save template"); }
    setTemplateSaving(false);
  };

  // ── Export handlers ───────────────────────────────────────────────────────
  const toggleExportStaff   = (uid) => setExportStaffIds(ids => ids.includes(uid) ? ids.filter(i => i !== uid) : [...ids, uid]);
  const toggleExportMeeting = (mid) => setExportSelectedMeetings(ids => ids.includes(mid) ? ids.filter(i => i !== mid) : [...ids, mid]);

  const handleExport = async () => {
    setExportLoading(true);
    setError("");
    try {
      const token = localStorage.getItem("supervision_token");
      const payload = {
        format: "pdf",
        staff_ids: exportStaffIds.length ? exportStaffIds : null,
        date_from: exportDateFrom || null,
        date_to: exportDateTo || null,
        meeting_ids: exportSelectedMeetings.length ? exportSelectedMeetings : null,
      };
      const resp = await fetch(`${API}/admin/export-evidence`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) throw new Error(await resp.text());
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "evidence_export.pdf";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) { setError("Export failed: " + err.message); }
    setExportLoading(false);
  };

  const handleTranscriptExport = async () => {
    setTxExportLoading(true);
    setError("");
    try {
      const token = localStorage.getItem("supervision_token");
      const payload = {
        staff_ids: exportStaffIds.length ? exportStaffIds : null,
        date_from: exportDateFrom || null,
        date_to: exportDateTo || null,
        meeting_ids: exportSelectedMeetings.length ? exportSelectedMeetings : null,
      };
      const resp = await fetch(`${API}/admin/export-transcripts`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) throw new Error(await resp.text());
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = "transcripts_export.pdf"; a.click();
      URL.revokeObjectURL(url);
    } catch (err) { setError("Transcript export failed: " + err.message); }
    setTxExportLoading(false);
  };

  if (loading) return <Layout><div className="p-8 text-center text-gray-400 text-sm">Loading…</div></Layout>;

  return (
    <Layout>
      <div className="p-6 md:p-8 fade-in">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold text-gray-900 font-display">Settings</h1>
          <p className="text-sm text-gray-500 mt-0.5">Manage supervision templates, evidence export and branding</p>
        </div>

        {message && (
          <div className="flex items-center gap-2 bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-md p-3 mb-4 text-sm">
            <CheckCircle className="w-4 h-4 flex-shrink-0" />{message}
            <button onClick={() => setMessage("")} className="ml-auto"><X className="w-3.5 h-3.5" /></button>
          </div>
        )}
        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-md p-3 mb-4 text-sm">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />{error}
            <button onClick={() => setError("")} className="ml-auto"><X className="w-3.5 h-3.5" /></button>
          </div>
        )}

        <div className="border-b border-gray-200 mb-6 flex">
          <TabBtn active={tab === "template"} onClick={() => setTab("template")}>
            <FileText className="w-3.5 h-3.5" />Supervision Template
          </TabBtn>
          <TabBtn active={tab === "export"} onClick={() => { setTab("export"); if (!exportMeetings.length) fetchExportMeetings(); }}>
            <Download className="w-3.5 h-3.5" />Export All
          </TabBtn>
          <TabBtn active={tab === "transcripts"} onClick={() => { setTab("transcripts"); if (!exportMeetings.length) fetchExportMeetings(); }}>
            <FileText className="w-3.5 h-3.5" />Transcripts
          </TabBtn>
          {canBrand && (
            <TabBtn active={tab === "branding"} onClick={() => setTab("branding")}>
              <Palette className="w-3.5 h-3.5" />Branding
            </TabBtn>
          )}
          <TabBtn active={tab === "focus"} onClick={() => setTab("focus")}>
            <Target className="w-3.5 h-3.5" />Focus Topics
          </TabBtn>
          <TabBtn active={tab === "security"} onClick={() => setTab("security")}>
            <Shield className="w-3.5 h-3.5" />Security
          </TabBtn>
        </div>

        {tab === "template" && (
          <TemplateTab
            template={template}
            setTemplate={setTemplate}
            templateSaving={templateSaving}
            newStepTitle={newStepTitle}
            setNewStepTitle={setNewStepTitle}
            newStepDesc={newStepDesc}
            setNewStepDesc={setNewStepDesc}
            handleAddStep={handleAddStep}
            handleRemoveStep={handleRemoveStep}
            handleMoveStep={handleMoveStep}
            handleSaveTemplate={handleSaveTemplate}
          />
        )}

        {tab === "export" && (
          <ExportTab
            users={users}
            exportStaffIds={exportStaffIds}
            toggleExportStaff={toggleExportStaff}
            exportDateFrom={exportDateFrom}
            setExportDateFrom={setExportDateFrom}
            exportDateTo={exportDateTo}
            setExportDateTo={setExportDateTo}
            exportMeetings={exportMeetings}
            exportSelectedMeetings={exportSelectedMeetings}
            toggleExportMeeting={toggleExportMeeting}
            exportLoading={exportLoading}
            exportMeetingsLoading={exportMeetingsLoading}
            handleExport={handleExport}
            setExportSelectedMeetings={setExportSelectedMeetings}
            setExportStaffIds={setExportStaffIds}
          />
        )}

        {tab === "transcripts" && (
          <TranscriptExportTab
            users={users}
            exportStaffIds={exportStaffIds}
            toggleExportStaff={toggleExportStaff}
            exportDateFrom={exportDateFrom}
            setExportDateFrom={setExportDateFrom}
            exportDateTo={exportDateTo}
            setExportDateTo={setExportDateTo}
            exportMeetings={exportMeetings}
            exportSelectedMeetings={exportSelectedMeetings}
            toggleExportMeeting={toggleExportMeeting}
            exportLoading={txExportLoading}
            exportMeetingsLoading={exportMeetingsLoading}
            handleTranscriptExport={handleTranscriptExport}
            setExportSelectedMeetings={setExportSelectedMeetings}
            setExportStaffIds={setExportStaffIds}
          />
        )}

        {tab === "branding" && canBrand && <BrandingTab />}

        {tab === "focus" && <FocusTopicsTab API={API} getAuthConfig={getAuthConfig} />}

        {tab === "security" && (
          <SecurityTab API={API} getAuthConfig={getAuthConfig} user={user} updateMfaStatus={updateMfaStatus} />
        )}
      </div>
    </Layout>
  );
}

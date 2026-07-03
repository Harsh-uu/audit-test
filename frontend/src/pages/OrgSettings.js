import React, { useState, useEffect } from "react";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import { FileText, Download, Palette, CheckCircle, AlertCircle, X } from "lucide-react";
import { TemplateTab } from "@/components/admin/TemplateTab";
import { ExportTab } from "@/components/admin/ExportTab";
import { BrandingTab } from "@/components/admin/BrandingTab";

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
  const { getAuthConfig, API, user } = useAuth();
  const canBrand = user?.role === "admin" || user?.role === "manager";

  const [tab, setTab] = useState("template");
  const [message, setMessage] = useState("");
  const [error, setError]     = useState("");
  const [loading, setLoading] = useState(true);

  // ── Template state ────────────────────────────────────────────────────────
  const [template, setTemplate]           = useState({ name: "Supervision Template", description: "", steps: [] });
  const [templateSaving, setTemplateSaving] = useState(false);
  const [newStepTitle, setNewStepTitle]   = useState("");
  const [newStepDesc, setNewStepDesc]     = useState("");

  // ── Export state ──────────────────────────────────────────────────────────
  const [users, setUsers]                           = useState([]);
  const [exportFormat, setExportFormat]             = useState("pdf");
  const [exportStaffIds, setExportStaffIds]         = useState([]);
  const [exportDateFrom, setExportDateFrom]         = useState("");
  const [exportDateTo, setExportDateTo]             = useState("");
  const [exportMeetings, setExportMeetings]         = useState([]);
  const [exportSelectedMeetings, setExportSelectedMeetings] = useState([]);
  const [exportLoading, setExportLoading]           = useState(false);
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
        format: exportFormat,
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
      a.download = exportFormat === "csv" ? "evidence_export.csv" : "evidence_export.pdf";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) { setError("Export failed: " + err.message); }
    setExportLoading(false);
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
            <Download className="w-3.5 h-3.5" />Evidence Export
          </TabBtn>
          {canBrand && (
            <TabBtn active={tab === "branding"} onClick={() => setTab("branding")}>
              <Palette className="w-3.5 h-3.5" />Branding
            </TabBtn>
          )}
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
            exportFormat={exportFormat}
            setExportFormat={setExportFormat}
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

        {tab === "branding" && canBrand && <BrandingTab />}
      </div>
    </Layout>
  );
}

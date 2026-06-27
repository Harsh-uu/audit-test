import React, { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import { Shield, Award, BookOpen, FileText, Users, Download, CheckCircle, AlertCircle, X, Palette } from "lucide-react";
import { StandardsTab } from "@/components/admin/StandardsTab";
import { DocumentsTab } from "@/components/admin/DocumentsTab";
import { TemplateTab } from "@/components/admin/TemplateTab";
import { UsersTab } from "@/components/admin/UsersTab";
import { ExportTab } from "@/components/admin/ExportTab";
import { BrandingTab } from "@/components/admin/BrandingTab";

function TabBtn({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${active ? "border-[#1E3A8A] text-[#1E3A8A]" : "border-transparent text-gray-500 hover:text-gray-700"}`}
    >
      {children}
    </button>
  );
}

export default function AdminLibrary() {
  const { getAuthConfig, API } = useAuth();
  const navigate = useNavigate();
  const [tab, setTab] = useState("cqc");
  const [standards, setStandards] = useState([]);
  const [users, setUsers] = useState([]);
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showNewStandard, setShowNewStandard] = useState(false);
  const [showNewUser, setShowNewUser] = useState(false);
  const [newStandard, setNewStandard] = useState({ type: "cqc", reference: "", name: "", description: "", keywords: [] });
  const [newUser, setNewUser] = useState({ email: "", name: "", role: "attendee", password: "" });
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [uploadLabel, setUploadLabel] = useState("");
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef(null);
  const pollRef = useRef(null);
  const [template, setTemplate] = useState({ name: "Supervision Template", description: "", steps: [] });
  const [templateSaving, setTemplateSaving] = useState(false);
  const [newStepTitle, setNewStepTitle] = useState("");
  const [newStepDesc, setNewStepDesc] = useState("");
  const [exportFormat, setExportFormat] = useState("csv");
  const [exportStaffIds, setExportStaffIds] = useState([]);
  const [exportDateFrom, setExportDateFrom] = useState("");
  const [exportDateTo, setExportDateTo] = useState("");
  const [exportMeetings, setExportMeetings] = useState([]);
  const [exportSelectedMeetings, setExportSelectedMeetings] = useState([]);
  const [exportLoading, setExportLoading] = useState(false);
  const [exportMeetingsLoading, setExportMeetingsLoading] = useState(false);

  useEffect(() => {
    fetchAll();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const hasParsingDocs = docs.some(d => d.parse_status === "parsing" || d.parse_status === "uploaded");
    if (hasParsingDocs && !pollRef.current) {
      pollRef.current = setInterval(async () => {
        try {
          const { data } = await axios.get(`${API}/admin/standards/documents`, getAuthConfig());
          setDocs(data);
          const stillParsing = data.some(d => d.parse_status === "parsing" || d.parse_status === "uploaded");
          if (!stillParsing && pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
        } catch (err) { console.error("Poll status error:", err); }
      }, 3000);
    } else if (!hasParsingDocs && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docs]);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [stdRes, userRes, docRes, tmplRes] = await Promise.all([
        axios.get(`${API}/admin/standards`, getAuthConfig()),
        axios.get(`${API}/admin/users`, getAuthConfig()),
        axios.get(`${API}/admin/standards/documents`, getAuthConfig()),
        axios.get(`${API}/admin/template`, getAuthConfig()),
      ]);
      setStandards(stdRes.data);
      setUsers(userRes.data);
      setDocs(docRes.data);
      setTemplate(tmplRes.data || { name: "Supervision Template", description: "", steps: [] });
    } catch (err) {
      console.error("Admin fetchAll failed:", err);
      setError("Failed to load admin data. Please refresh.");
    }
    setLoading(false);
  };

  const fetchExportMeetings = async () => {
    setExportMeetingsLoading(true);
    try {
      const { data } = await axios.get(`${API}/admin/meetings-brief`, getAuthConfig());
      setExportMeetings(data);
    } catch (err) { console.error("Failed to load meetings for export:", err); }
    setExportMeetingsLoading(false);
  };

  const handleExport = async () => {
    setExportLoading(true);
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

  const toggleExportStaff = (uid) => setExportStaffIds(ids => ids.includes(uid) ? ids.filter(i => i !== uid) : [...ids, uid]);
  const toggleExportMeeting = (mid) => setExportSelectedMeetings(ids => ids.includes(mid) ? ids.filter(i => i !== mid) : [...ids, mid]);

  const cqcStandards = standards.filter(s => s.type === "cqc");
  const ccStandards = standards.filter(s => s.type === "care_cert");

  const handleCreateStandard = async () => {
    setError("");
    if (!newStandard.reference || !newStandard.name) return setError("Reference and name are required");
    try {
      await axios.post(`${API}/admin/standards`, newStandard, getAuthConfig());
      setMessage("Standard created");
      setShowNewStandard(false);
      setNewStandard({ type: "cqc", reference: "", name: "", description: "", keywords: [] });
      fetchAll();
    } catch (err) { setError(err.response?.data?.detail || "Failed to create"); }
  };

  const handleDeleteStandard = async (id) => {
    if (!window.confirm("Deactivate this standard?")) return;
    try {
      await axios.delete(`${API}/admin/standards/${id}`, getAuthConfig());
      setMessage("Standard deactivated");
      fetchAll();
    } catch (err) { console.error("Delete standard failed:", err); setError("Failed to deactivate standard."); }
  };

  const handleCreateUser = async () => {
    setError("");
    if (!newUser.email || !newUser.name || !newUser.password) return setError("All fields required");
    try {
      await axios.post(`${API}/admin/users`, newUser, getAuthConfig());
      setMessage("User created");
      setShowNewUser(false);
      setNewUser({ email: "", name: "", role: "attendee", password: "" });
      fetchAll();
    } catch (err) { setError(err.response?.data?.detail || "Failed to create user"); }
  };

  const handleUploadDoc = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setUploading(true);
    setError("");
    const formData = new FormData();
    formData.append("file", file);
    formData.append("label", uploadLabel || file.name.replace(/\.[^.]+$/, ""));
    const token = localStorage.getItem("supervision_token");
    try {
      await axios.post(`${API}/admin/standards/upload`, formData, {
        headers: { "Content-Type": "multipart/form-data", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      });
      setMessage("Document uploaded — AI is now extracting criteria (this takes ~10 seconds)");
      setUploadLabel("");
      fetchAll();
    } catch (err) { setError("Upload failed: " + (err.response?.data?.detail || err.message)); }
    setUploading(false);
    e.target.value = "";
  };

  const handleToggleDoc = async (id, is_active) => {
    try {
      await axios.patch(`${API}/admin/standards/documents/${id}`, { is_active }, getAuthConfig());
      setDocs(docs.map(d => d.id === id ? { ...d, is_active } : d));
    } catch (err) { console.error("Toggle document failed:", err); setError("Failed to update document status."); }
  };

  const handleDeleteDoc = async (id) => {
    if (!window.confirm("Delete this document? It will no longer be used in evidence matching.")) return;
    try {
      await axios.delete(`${API}/admin/standards/documents/${id}`, getAuthConfig());
      setDocs(docs.filter(d => d.id !== id));
      setMessage("Document deleted");
    } catch (err) { console.error("Delete document failed:", err); setError("Failed to delete document."); }
  };

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
    try {
      await axios.put(`${API}/admin/template`, template, getAuthConfig());
      setMessage("Supervision template saved");
    } catch (err) { setError("Failed to save template"); }
    setTemplateSaving(false);
  };

  if (loading) return <Layout><div className="p-8 text-center text-gray-400 text-sm">Loading…</div></Layout>;

  return (
    <Layout>
      <div className="p-6 md:p-8 fade-in">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold text-gray-900 font-display">Admin Panel</h1>
          <p className="text-sm text-gray-500 mt-0.5">Manage standards library and users</p>
        </div>

        {message && (
          <div className="flex items-center gap-2 bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-md p-3 mb-4 text-sm" data-testid="success-message">
            <CheckCircle className="w-4 h-4 flex-shrink-0" />
            {message}
            <button onClick={() => setMessage("")} className="ml-auto"><X className="w-3.5 h-3.5" /></button>
          </div>
        )}
        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-md p-3 mb-4 text-sm" data-testid="error-message">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            {error}
            <button onClick={() => setError("")} className="ml-auto"><X className="w-3.5 h-3.5" /></button>
          </div>
        )}

        <div className="border-b border-gray-200 mb-6">
          <TabBtn active={tab === "cqc"} onClick={() => setTab("cqc")}>
            <Shield className="inline w-3.5 h-3.5 mr-1.5" />
            CQC Regulations ({cqcStandards.length})
          </TabBtn>
          <TabBtn active={tab === "care_cert"} onClick={() => setTab("care_cert")}>
            <Award className="inline w-3.5 h-3.5 mr-1.5" />
            Care Certificate ({ccStandards.length})
          </TabBtn>
          <TabBtn active={tab === "documents"} onClick={() => setTab("documents")}>
            <BookOpen className="inline w-3.5 h-3.5 mr-1.5" />
            Custom Standards ({docs.length})
          </TabBtn>
          <TabBtn active={tab === "template"} onClick={() => setTab("template")}>
            <FileText className="inline w-3.5 h-3.5 mr-1.5" />
            Supervision Template
          </TabBtn>
          <TabBtn active={tab === "users"} onClick={() => setTab("users")}>
            <Users className="inline w-3.5 h-3.5 mr-1.5" />
            Users ({users.length})
          </TabBtn>
          <TabBtn active={tab === "export"} onClick={() => { setTab("export"); if (!exportMeetings.length) fetchExportMeetings(); }}>
            <Download className="inline w-3.5 h-3.5 mr-1.5" />
            Evidence Export
          </TabBtn>
          <TabBtn active={tab === "branding"} onClick={() => setTab("branding")}>
            <Palette className="inline w-3.5 h-3.5 mr-1.5" />
            Branding
          </TabBtn>
        </div>

        {(tab === "cqc" || tab === "care_cert") && (
          <StandardsTab
            tab={tab}
            cqcStandards={cqcStandards}
            ccStandards={ccStandards}
            showNewStandard={showNewStandard}
            setShowNewStandard={setShowNewStandard}
            newStandard={newStandard}
            setNewStandard={setNewStandard}
            handleCreateStandard={handleCreateStandard}
            handleDeleteStandard={handleDeleteStandard}
          />
        )}

        {tab === "documents" && (
          <DocumentsTab
            docs={docs}
            uploading={uploading}
            uploadLabel={uploadLabel}
            setUploadLabel={setUploadLabel}
            handleUploadDoc={handleUploadDoc}
            handleToggleDoc={handleToggleDoc}
            handleDeleteDoc={handleDeleteDoc}
            fileInputRef={fileInputRef}
          />
        )}

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

        {tab === "users" && (
          <UsersTab
            users={users}
            showNewUser={showNewUser}
            setShowNewUser={setShowNewUser}
            newUser={newUser}
            setNewUser={setNewUser}
            handleCreateUser={handleCreateUser}
            navigate={navigate}
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

        {tab === "branding" && <BrandingTab />}
      </div>
    </Layout>
  );
}

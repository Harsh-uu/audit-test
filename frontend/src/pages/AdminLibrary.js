import React, { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import {
  Shield, Award, BookOpen, Upload, Plus, Trash2, CheckCircle, AlertCircle,
  Users, UserPlus, X, Loader, ToggleLeft, ToggleRight, FileText, ChevronDown, ChevronUp, ArrowUp, ArrowDown,
  Download, TrendingUp, Calendar, Filter
} from "lucide-react";

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

function ParseStatusBadge({ status }) {
  const cfg = {
    parsing:  { cls: "bg-amber-100 text-amber-700", label: "Parsing…", icon: <Loader className="w-3 h-3 animate-spin" /> },
    parsed:   { cls: "bg-emerald-100 text-emerald-700", label: "Ready", icon: <CheckCircle className="w-3 h-3" /> },
    failed:   { cls: "bg-red-100 text-red-700", label: "Failed", icon: <AlertCircle className="w-3 h-3" /> },
    uploaded: { cls: "bg-gray-100 text-gray-500", label: "Uploading…", icon: <Loader className="w-3 h-3 animate-spin" /> },
  };
  const c = cfg[status] || cfg.uploaded;
  return (
    <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium ${c.cls}`}>
      {c.icon} {c.label}
    </span>
  );
}

function DocCard({ doc, onToggle, onDelete }) {
  const [expanded, setExpanded] = useState(false);
  const isActive = doc.is_active !== false;
  const criteria = doc.extracted_criteria || [];

  return (
    <div className={`border border-gray-200 rounded-lg overflow-hidden shadow-sm transition-opacity ${!isActive ? "opacity-60" : ""}`} data-testid={`doc-card-${doc.id}`}>
      <div className="flex items-start justify-between p-4 bg-white">
        <div className="flex items-start gap-3 min-w-0 flex-1">
          <div className="p-2 bg-teal-50 rounded-lg flex-shrink-0">
            <FileText className="w-4 h-4 text-teal-600" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-gray-900 truncate">{doc.label || doc.filename}</p>
            <p className="text-xs text-gray-400 truncate">{doc.filename} · {(doc.size_bytes / 1024).toFixed(1)} KB · {new Date(doc.created_at).toLocaleDateString("en-GB")}</p>
            {doc.document_summary && <p className="text-xs text-gray-500 mt-1 italic">{doc.document_summary}</p>}
            <div className="flex items-center gap-2 mt-1.5">
              <ParseStatusBadge status={doc.parse_status} />
              {doc.parse_status === "parsed" && (
                <span className="text-xs text-teal-700 font-medium">{criteria.length} criteria extracted</span>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0 ml-2">
          <button
            onClick={() => onToggle(doc.id, !isActive)}
            title={isActive ? "Disable (exclude from evidence matching)" : "Enable (include in evidence matching)"}
            className="p-1 text-gray-400 hover:text-teal-600 transition-colors"
            data-testid={`toggle-doc-${doc.id}`}
          >
            {isActive ? <ToggleRight className="w-5 h-5 text-teal-600" /> : <ToggleLeft className="w-5 h-5" />}
          </button>
          {criteria.length > 0 && (
            <button onClick={() => setExpanded(e => !e)} className="p-1 text-gray-400 hover:text-gray-600 transition-colors">
              {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </button>
          )}
          <button onClick={() => onDelete(doc.id)} className="p-1 text-gray-400 hover:text-red-500 transition-colors" data-testid={`delete-doc-${doc.id}`}>
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>
      {expanded && criteria.length > 0 && (
        <div className="border-t border-gray-100 bg-teal-50 p-3">
          <p className="text-xs font-semibold text-teal-700 mb-2">Extracted Criteria ({criteria.length})</p>
          <div className="space-y-1">
            {criteria.map((c, i) => (
              <div key={i} className="flex gap-2 text-xs text-gray-700">
                <span className="font-medium text-teal-700 flex-shrink-0">{c.ref}.</span>
                <span><strong>{c.name}</strong>{c.description ? ` — ${c.description}` : ""}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
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
  // Template state
  const [template, setTemplate] = useState({ name: "Supervision Template", description: "", steps: [] });
  const [templateSaving, setTemplateSaving] = useState(false);
  const [newStepTitle, setNewStepTitle] = useState("");
  const [newStepDesc, setNewStepDesc] = useState("");
  // Export state
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
  }, []);

  // Poll for parsing status if any doc is still parsing
  useEffect(() => {
    const hasParsingDocs = docs.some(d => d.parse_status === "parsing" || d.parse_status === "uploaded");
    if (hasParsingDocs && !pollRef.current) {
      pollRef.current = setInterval(async () => {
        try {
          const { data } = await axios.get(`${API}/admin/standards/documents`, getAuthConfig());
          setDocs(data);
          const stillParsing = data.some(d => d.parse_status === "parsing" || d.parse_status === "uploaded");
          if (!stillParsing && pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
        } catch {}
      }, 3000);
    } else if (!hasParsingDocs && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
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
    } catch {}
    setLoading(false);
  };

  const fetchExportMeetings = async () => {
    setExportMeetingsLoading(true);
    try {
      const { data } = await axios.get(`${API}/admin/meetings-brief`, getAuthConfig());
      setExportMeetings(data);
    } catch {}
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
    } catch (err) {
      setError("Export failed: " + err.message);
    } finally {
      setExportLoading(false);
    }
  };

  const toggleExportStaff = (uid) => {
    setExportStaffIds(ids => ids.includes(uid) ? ids.filter(i => i !== uid) : [...ids, uid]);
  };

  const toggleExportMeeting = (mid) => {
    setExportSelectedMeetings(ids => ids.includes(mid) ? ids.filter(i => i !== mid) : [...ids, mid]);
  };

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
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to create");
    }
  };

  const handleDeleteStandard = async (id) => {
    if (!window.confirm("Deactivate this standard?")) return;
    try {
      await axios.delete(`${API}/admin/standards/${id}`, getAuthConfig());
      setMessage("Standard deactivated");
      fetchAll();
    } catch {}
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
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to create user");
    }
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
    } catch (err) {
      setError("Upload failed: " + (err.response?.data?.detail || err.message));
    }
    setUploading(false);
    e.target.value = "";
  };

  const handleToggleDoc = async (id, is_active) => {
    try {
      await axios.patch(`${API}/admin/standards/documents/${id}`, { is_active }, getAuthConfig());
      setDocs(docs.map(d => d.id === id ? { ...d, is_active } : d));
    } catch {}
  };

  const handleDeleteDoc = async (id) => {
    if (!window.confirm("Delete this document? It will no longer be used in evidence matching.")) return;
    try {
      await axios.delete(`${API}/admin/standards/documents/${id}`, getAuthConfig());
      setDocs(docs.filter(d => d.id !== id));
      setMessage("Document deleted");
    } catch {}
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
    steps.forEach((s, i) => s.order = i + 1);
    setTemplate(t => ({ ...t, steps }));
  };

  const handleSaveTemplate = async () => {
    setTemplateSaving(true);
    try {
      await axios.put(`${API}/admin/template`, template, getAuthConfig());
      setMessage("Supervision template saved");
    } catch (err) {
      setError("Failed to save template");
    }
    setTemplateSaving(false);
  };

  return (
    <Layout>
      <div className="p-6 md:p-8 fade-in">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold text-gray-900" style={{fontFamily:'Work Sans,sans-serif'}}>Admin Panel</h1>
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

        {/* Tabs */}
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
        </div>

        {/* CQC / Care Cert standards */}
        {(tab === "cqc" || tab === "care_cert") && (
          <div>
            <div className="flex justify-end mb-4">
              <button
                onClick={() => { setShowNewStandard(true); setNewStandard(s => ({...s, type: tab})); }}
                className="flex items-center gap-2 bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors"
                data-testid="add-standard-btn"
              >
                <Plus className="w-4 h-4" />
                Add Standard
              </button>
            </div>

            {showNewStandard && (
              <div className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm mb-4 fade-in">
                <h4 className="font-medium text-gray-900 mb-4">New Standard</h4>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Reference</label>
                    <input value={newStandard.reference} onChange={e => setNewStandard(s => ({...s, reference: e.target.value}))} placeholder="e.g. Regulation 18" className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]" data-testid="standard-reference-input" />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Name</label>
                    <input value={newStandard.name} onChange={e => setNewStandard(s => ({...s, name: e.target.value}))} placeholder="e.g. Staffing" className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]" data-testid="standard-name-input" />
                  </div>
                  <div className="col-span-2">
                    <label className="block text-xs font-medium text-gray-600 mb-1">Description</label>
                    <textarea value={newStandard.description} onChange={e => setNewStandard(s => ({...s, description: e.target.value}))} rows={2} className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] resize-none" data-testid="standard-desc-input" />
                  </div>
                </div>
                <div className="flex gap-2 mt-4">
                  <button onClick={handleCreateStandard} className="bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF]" data-testid="save-standard-btn">Create</button>
                  <button onClick={() => setShowNewStandard(false)} className="border border-gray-300 text-gray-600 px-4 py-2 rounded-md text-sm font-medium hover:bg-gray-50">Cancel</button>
                </div>
              </div>
            )}

            <div className="bg-white border border-gray-200 rounded-lg shadow-sm overflow-hidden" data-testid="standards-table">
              <table className="w-full">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-200">
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-600 uppercase tracking-wide">Reference</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-600 uppercase tracking-wide">Name</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-600 uppercase tracking-wide hidden md:table-cell">Description</th>
                    <th className="px-4 py-3 text-xs font-semibold text-gray-600 uppercase tracking-wide text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {(tab === "cqc" ? cqcStandards : ccStandards).map(s => (
                    <tr key={s.id} className="hover:bg-gray-50 transition-colors" data-testid={`standard-row-${s.id}`}>
                      <td className="px-4 py-3 text-sm font-medium text-[#1E3A8A]">{s.reference}</td>
                      <td className="px-4 py-3 text-sm text-gray-900">{s.name}</td>
                      <td className="px-4 py-3 text-xs text-gray-500 hidden md:table-cell max-w-xs truncate">{s.description}</td>
                      <td className="px-4 py-3 text-right">
                        <button onClick={() => handleDeleteStandard(s.id)} className="p-1.5 text-gray-400 hover:text-red-500 transition-colors rounded" data-testid={`delete-standard-${s.id}`}>
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {(tab === "cqc" ? cqcStandards : ccStandards).length === 0 && (
                    <tr><td colSpan={4} className="px-4 py-8 text-center text-sm text-gray-400">No standards found</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Custom Standards Documents */}
        {tab === "documents" && (
          <div>
            <div className="mb-4 p-4 bg-teal-50 border border-teal-200 rounded-lg text-sm text-teal-800">
              <strong>How it works:</strong> Upload any document — job description, company values, policy document, competency framework. The AI will extract standards and criteria from it. These will then be included automatically in all future meeting evidence matching.
            </div>

            {/* Upload form */}
            <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm mb-4" data-testid="upload-form">
              <h3 className="text-sm font-semibold text-gray-800 mb-3">Upload a Standards Document</h3>
              <div className="flex gap-3 items-end">
                <div className="flex-1">
                  <label className="block text-xs font-medium text-gray-600 mb-1">Document label (what is it?)</label>
                  <input
                    value={uploadLabel}
                    onChange={e => setUploadLabel(e.target.value)}
                    placeholder="e.g. Company Values, Job Description – Care Worker, NICE Guidelines"
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
                    data-testid="upload-label-input"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">File (PDF, DOCX, TXT)</label>
                  <label
                    className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium cursor-pointer transition-colors ${uploading ? "bg-gray-200 text-gray-400" : "bg-teal-600 text-white hover:bg-teal-700"}`}
                    data-testid="upload-doc-btn"
                  >
                    {uploading ? <Loader className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                    {uploading ? "Uploading…" : "Choose File"}
                    <input ref={fileInputRef} type="file" accept=".pdf,.docx,.txt,.md,.csv" onChange={handleUploadDoc} className="hidden" disabled={uploading} />
                  </label>
                </div>
              </div>
              <p className="text-xs text-gray-400 mt-2">Accepted: PDF, DOCX, TXT, MD, CSV. The AI will extract criteria automatically (~10–30 seconds).</p>
            </div>

            {/* Document list */}
            {docs.length === 0 ? (
              <div className="text-center py-16 text-gray-400">
                <BookOpen className="w-10 h-10 mx-auto mb-3 opacity-30" />
                <p className="text-sm font-medium">No documents uploaded yet</p>
                <p className="text-xs mt-1">Upload a document above to get started</p>
              </div>
            ) : (
              <div className="space-y-3" data-testid="documents-list">
                {docs.map(doc => (
                  <DocCard key={doc.id} doc={doc} onToggle={handleToggleDoc} onDelete={handleDeleteDoc} />
                ))}
              </div>
            )}
          </div>
        )}

        {/* Supervision Template */}
        {tab === "template" && (
          <div data-testid="template-tab">
            <div className="mb-4 p-4 bg-indigo-50 border border-indigo-200 rounded-lg text-sm text-indigo-800">
              <strong>Supervision Template:</strong> Define the steps of your organisation's supervision method. These appear as a live checklist during recording, and the AI uses them as context when generating the meeting summary and evidence mapping.
            </div>

            {/* Template name/description */}
            <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm mb-4">
              <div className="grid grid-cols-2 gap-4 mb-4">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Template name</label>
                  <input value={template.name} onChange={e => setTemplate(t => ({...t, name: e.target.value}))} className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" data-testid="template-name-input" />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Description (optional)</label>
                  <input value={template.description} onChange={e => setTemplate(t => ({...t, description: e.target.value}))} placeholder="e.g. Monthly 1:1 Supervision Framework" className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" data-testid="template-desc-input" />
                </div>
              </div>

              {/* Steps list */}
              <h3 className="text-sm font-semibold text-gray-800 mb-2">Session Steps</h3>
              {template.steps.length === 0 && (
                <p className="text-sm text-gray-400 text-center py-6">No steps yet — add your first step below</p>
              )}
              <div className="space-y-2 mb-4" data-testid="template-steps-list">
                {template.steps.map((step, idx) => (
                  <div key={step.id} className="flex items-start gap-2 p-3 bg-gray-50 border border-gray-200 rounded-lg" data-testid={`template-step-${idx}`}>
                    <span className="flex-shrink-0 w-6 h-6 rounded-full bg-indigo-100 text-indigo-700 text-xs font-bold flex items-center justify-center mt-0.5">{idx + 1}</span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-900">{step.title}</p>
                      {step.description && <p className="text-xs text-gray-500 mt-0.5">{step.description}</p>}
                    </div>
                    <div className="flex items-center gap-1 flex-shrink-0">
                      <button onClick={() => handleMoveStep(idx, -1)} disabled={idx === 0} className="p-1 text-gray-400 hover:text-gray-600 disabled:opacity-30 transition-colors"><ArrowUp className="w-3.5 h-3.5" /></button>
                      <button onClick={() => handleMoveStep(idx, 1)} disabled={idx === template.steps.length - 1} className="p-1 text-gray-400 hover:text-gray-600 disabled:opacity-30 transition-colors"><ArrowDown className="w-3.5 h-3.5" /></button>
                      <button onClick={() => handleRemoveStep(idx)} className="p-1 text-gray-400 hover:text-red-500 transition-colors"><X className="w-3.5 h-3.5" /></button>
                    </div>
                  </div>
                ))}
              </div>

              {/* Add step */}
              <div className="border-t border-gray-100 pt-4">
                <p className="text-xs font-medium text-gray-600 mb-2">Add a step</p>
                <div className="flex gap-2">
                  <input
                    value={newStepTitle}
                    onChange={e => setNewStepTitle(e.target.value)}
                    onKeyDown={e => e.key === "Enter" && handleAddStep()}
                    placeholder="Step title, e.g. Wellbeing Check"
                    className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    data-testid="new-step-title-input"
                  />
                  <input
                    value={newStepDesc}
                    onChange={e => setNewStepDesc(e.target.value)}
                    placeholder="Description (optional)"
                    className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    data-testid="new-step-desc-input"
                  />
                  <button onClick={handleAddStep} className="flex items-center gap-1.5 px-3 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 transition-colors" data-testid="add-step-btn">
                    <Plus className="w-4 h-4" /> Add
                  </button>
                </div>
              </div>
            </div>

            <div className="flex justify-end">
              <button onClick={handleSaveTemplate} disabled={templateSaving} className="flex items-center gap-2 bg-indigo-600 text-white px-5 py-2 rounded-md text-sm font-semibold hover:bg-indigo-700 disabled:opacity-60 transition-colors" data-testid="save-template-btn">
                <CheckCircle className="w-4 h-4" />
                {templateSaving ? "Saving…" : "Save Template"}
              </button>
            </div>
          </div>
        )}

        {/* Users */}
        {tab === "users" && (
          <div>
            <div className="flex justify-end mb-4">
              <button onClick={() => setShowNewUser(true)} className="flex items-center gap-2 bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors" data-testid="add-user-btn">
                <UserPlus className="w-4 h-4" />
                Add User
              </button>
            </div>

            {showNewUser && (
              <div className="bg-white border border-gray-200 rounded-lg p-5 shadow-sm mb-4 fade-in">
                <h4 className="font-medium text-gray-900 mb-4">New User</h4>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Full name</label>
                    <input value={newUser.name} onChange={e => setNewUser(u => ({...u, name: e.target.value}))} className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]" data-testid="new-user-name" />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Email</label>
                    <input type="email" value={newUser.email} onChange={e => setNewUser(u => ({...u, email: e.target.value}))} className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]" data-testid="new-user-email" />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Role</label>
                    <select value={newUser.role} onChange={e => setNewUser(u => ({...u, role: e.target.value}))} className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] bg-white" data-testid="new-user-role">
                      <option value="attendee">Care Worker / Attendee</option>
                      <option value="manager">Manager</option>
                      <option value="shared_reviewer">Shared Reviewer</option>
                      <option value="admin">Admin</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Password</label>
                    <input type="password" value={newUser.password} onChange={e => setNewUser(u => ({...u, password: e.target.value}))} className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]" data-testid="new-user-password" />
                  </div>
                </div>
                <div className="flex gap-2 mt-4">
                  <button onClick={handleCreateUser} className="bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF]" data-testid="save-user-btn">Create</button>
                  <button onClick={() => setShowNewUser(false)} className="border border-gray-300 text-gray-600 px-4 py-2 rounded-md text-sm font-medium hover:bg-gray-50">Cancel</button>
                </div>
              </div>
            )}

            <div className="bg-white border border-gray-200 rounded-lg shadow-sm overflow-hidden" data-testid="users-table">
              <table className="w-full">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-200">
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-600 uppercase tracking-wide">Name</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-600 uppercase tracking-wide">Email</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-600 uppercase tracking-wide">Role</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-600 uppercase tracking-wide">Status</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-600 uppercase tracking-wide">Portfolio</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {users.map(u => (
                    <tr key={u.id} className="hover:bg-gray-50" data-testid={`user-row-${u.id}`}>
                      <td className="px-4 py-3 text-sm font-medium text-gray-900">{u.name}</td>
                      <td className="px-4 py-3 text-sm text-gray-600">{u.email}</td>
                      <td className="px-4 py-3">
                        <span className="text-xs px-2 py-0.5 bg-blue-100 text-blue-700 rounded-full capitalize">{u.role}</span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`text-xs ${u.is_active ? "text-emerald-600" : "text-red-500"}`}>{u.is_active ? "Active" : "Inactive"}</span>
                      </td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => navigate(`/portfolio/${u.id}`)}
                          className="flex items-center gap-1 text-xs text-[#1E3A8A] hover:underline"
                          data-testid={`view-portfolio-${u.id}`}
                        >
                          <TrendingUp className="w-3 h-3" /> Portfolio
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Evidence Export */}
        {tab === "export" && (
          <div data-testid="export-tab">
            <div className="max-w-2xl">
              <p className="text-sm text-gray-500 mb-6">
                Export compliance evidence records across signed-off supervision meetings.
                Filter by staff member, date range, or specific meetings. Choose PDF or CSV format.
              </p>

              {/* Format toggle */}
              <div className="mb-5">
                <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2">Export Format</label>
                <div className="flex gap-2">
                  {["csv", "pdf"].map(f => (
                    <button
                      key={f}
                      onClick={() => setExportFormat(f)}
                      className={`flex items-center gap-2 px-4 py-2 rounded-md border text-sm font-medium transition-colors ${
                        exportFormat === f
                          ? "bg-[#1E3A8A] text-white border-[#1E3A8A]"
                          : "bg-white text-gray-700 border-gray-300 hover:bg-gray-50"
                      }`}
                      data-testid={`format-${f}`}
                    >
                      <Download className="w-3.5 h-3.5" />
                      {f.toUpperCase()}
                      <span className="text-xs opacity-70">{f === "csv" ? "spreadsheet" : "formatted report"}</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Date range */}
              <div className="mb-5">
                <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2">
                  <Calendar className="inline w-3.5 h-3.5 mr-1" />
                  Date Range (optional)
                </label>
                <div className="flex items-center gap-3">
                  <input
                    type="date"
                    value={exportDateFrom}
                    onChange={e => setExportDateFrom(e.target.value)}
                    className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
                    data-testid="export-date-from"
                  />
                  <span className="text-gray-400 text-sm">to</span>
                  <input
                    type="date"
                    value={exportDateTo}
                    onChange={e => setExportDateTo(e.target.value)}
                    className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
                    data-testid="export-date-to"
                  />
                  {(exportDateFrom || exportDateTo) && (
                    <button onClick={() => { setExportDateFrom(""); setExportDateTo(""); }} className="text-xs text-gray-400 hover:text-gray-600">Clear</button>
                  )}
                </div>
              </div>

              {/* Staff filter */}
              <div className="mb-5">
                <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2">
                  <Users className="inline w-3.5 h-3.5 mr-1" />
                  Staff Members (optional — leave blank for all)
                </label>
                <div className="flex flex-wrap gap-2 p-3 border border-gray-200 rounded-md bg-gray-50 max-h-36 overflow-y-auto">
                  {users.filter(u => ["attendee", "manager"].includes(u.role)).map(u => (
                    <button
                      key={u.id}
                      onClick={() => toggleExportStaff(u.id)}
                      className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border transition-colors ${
                        exportStaffIds.includes(u.id)
                          ? "bg-[#1E3A8A] text-white border-[#1E3A8A]"
                          : "bg-white text-gray-700 border-gray-300 hover:bg-gray-100"
                      }`}
                      data-testid={`staff-chip-${u.id}`}
                    >
                      {exportStaffIds.includes(u.id) && <X className="w-2.5 h-2.5" />}
                      {u.name}
                    </button>
                  ))}
                </div>
                {exportStaffIds.length > 0 && (
                  <button onClick={() => setExportStaffIds([])} className="text-xs text-gray-400 hover:text-gray-600 mt-1">Clear selection</button>
                )}
              </div>

              {/* Specific meetings */}
              <div className="mb-6">
                <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2">
                  <Filter className="inline w-3.5 h-3.5 mr-1" />
                  Specific Meetings (optional — overrides above filters if selected)
                </label>
                {exportMeetingsLoading ? (
                  <div className="flex items-center gap-2 text-sm text-gray-400 py-2"><Loader className="w-4 h-4 animate-spin" /> Loading meetings…</div>
                ) : (
                  <div className="border border-gray-200 rounded-md bg-gray-50 max-h-48 overflow-y-auto">
                    {exportMeetings.length === 0 ? (
                      <p className="text-xs text-gray-400 p-3">No signed-off meetings available</p>
                    ) : (
                      exportMeetings.map(m => (
                        <label
                          key={m.id}
                          className="flex items-center gap-3 px-3 py-2 hover:bg-white cursor-pointer border-b border-gray-100 last:border-0"
                          data-testid={`meeting-check-${m.id}`}
                        >
                          <input
                            type="checkbox"
                            checked={exportSelectedMeetings.includes(m.id)}
                            onChange={() => toggleExportMeeting(m.id)}
                            className="w-3.5 h-3.5 accent-[#1E3A8A]"
                          />
                          <span className="flex-1 text-sm text-gray-800 truncate">{m.title}</span>
                          <span className="text-xs text-gray-400 flex-shrink-0">{m.date ? m.date.slice(0, 10) : "—"}</span>
                        </label>
                      ))
                    )}
                  </div>
                )}
                {exportSelectedMeetings.length > 0 && (
                  <button onClick={() => setExportSelectedMeetings([])} className="text-xs text-gray-400 hover:text-gray-600 mt-1">Clear selection</button>
                )}
              </div>

              <button
                onClick={handleExport}
                disabled={exportLoading}
                className="flex items-center gap-2 bg-[#1E3A8A] text-white px-6 py-2.5 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors disabled:opacity-60"
                data-testid="run-export-btn"
              >
                <Download className="w-4 h-4" />
                {exportLoading ? "Generating…" : `Export ${exportFormat.toUpperCase()}`}
              </button>
            </div>
          </div>
        )}

      </div>
    </Layout>
  );
}


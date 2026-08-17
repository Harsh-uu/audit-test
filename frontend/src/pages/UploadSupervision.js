import React, { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { cachedGet } from "@/utils/apiCache";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import {
  Upload, FileText, CheckCircle, AlertCircle, Loader2, User,
  Calendar, Tag, X, ChevronRight, FileUp, Clock
} from "lucide-react";

const DOC_TYPE_OPTIONS = [
  { value: "supervision_record", label: "Previous Supervision Record" },
  { value: "job_description", label: "Job Description" },
  { value: "service_user_feedback", label: "Service User Feedback" },
  { value: "family_carer_feedback", label: "Family / Carer Feedback" },
  { value: "peer_staff_feedback", label: "Peer / Staff Feedback" },
  { value: "observation_record", label: "Observation Record" },
  { value: "performance_review", label: "Performance Review" },
  { value: "training_record", label: "Training Record" },
  { value: "other", label: "Other" },
];

const STATUS_CONFIG = {
  processing:  { icon: Loader2, color: "text-amber-600", bg: "bg-amber-50 border-amber-200", label: "Analysing…", spin: true },
  text_ready:  { icon: Loader2, color: "text-amber-600", bg: "bg-amber-50 border-amber-200", label: "Mapping evidence…", spin: true },
  done:        { icon: CheckCircle, color: "text-emerald-600", bg: "bg-emerald-50 border-emerald-200", label: "Analysis complete" },
  failed:      { icon: AlertCircle, color: "text-red-600", bg: "bg-red-50 border-red-200", label: "Failed" },
};

function UploadCard({ upload, onDelete, navigate }) {
  const cfg = STATUS_CONFIG[upload.status] || STATUS_CONFIG.processing;
  const Icon = cfg.icon;
  const cqcCount = upload.cqc_mappings?.length || 0;
  const ccCount = upload.care_cert_mappings?.length || 0;
  const customCount = upload.custom_mappings?.length || 0;

  return (
    <div
      className="bg-white border border-gray-200 rounded-lg p-4 flex items-start gap-3 hover:shadow-md transition-all duration-150 group"
      data-testid={`upload-card-${upload.id}`}
    >
      <div className="w-9 h-9 rounded-lg bg-indigo-50 border border-indigo-100 flex items-center justify-center flex-shrink-0 mt-0.5">
        <FileText className="w-4 h-4 text-indigo-600" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-900 truncate">{upload.label || upload.filename}</p>
        <p className="text-xs text-gray-500 mt-0.5">
          {upload.staff_name} · {upload.meeting_date}
          {upload.doc_type && upload.doc_type !== "other" && (
            <span className="ml-1.5 px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 text-[10px] font-medium capitalize">
              {DOC_TYPE_OPTIONS.find(o => o.value === upload.doc_type)?.label || upload.doc_type}
            </span>
          )}
        </p>
        <div className={`inline-flex items-center gap-1.5 mt-2 px-2 py-0.5 rounded-full border text-xs font-medium ${cfg.bg} ${cfg.color}`}>
          <Icon className={`w-3 h-3 ${cfg.spin ? "animate-spin" : ""}`} />
          {cfg.label}
        </div>
        {upload.status === "done" && (
          <div className="flex items-center gap-2 mt-2 flex-wrap">
            {cqcCount > 0 && (
              <span className="text-xs bg-purple-50 text-purple-700 border border-purple-100 rounded-full px-2 py-0.5">
                {cqcCount} CQC
              </span>
            )}
            {ccCount > 0 && (
              <span className="text-xs bg-blue-50 text-blue-700 border border-blue-100 rounded-full px-2 py-0.5">
                {ccCount} Care Cert
              </span>
            )}
            {customCount > 0 && (
              <span className="text-xs bg-teal-50 text-teal-700 border border-teal-100 rounded-full px-2 py-0.5">
                {customCount} Custom
              </span>
            )}
          </div>
        )}
        {upload.status === "failed" && upload.error && (
          <p className="text-xs text-red-600 mt-1">{upload.error}</p>
        )}
      </div>
      <div className="flex items-center gap-1 flex-shrink-0">
        {upload.status === "done" && (
          <button
            onClick={() => navigate(`/doc-uploads/${upload.id}`)}
            className="text-xs font-medium text-[#1E3A8A] hover:underline flex items-center gap-0.5"
            data-testid={`view-evidence-${upload.id}`}
          >
            View <ChevronRight className="w-3 h-3" />
          </button>
        )}
        <button
          onClick={() => onDelete(upload.id)}
          className="p-1 text-gray-300 hover:text-red-500 transition-colors opacity-0 group-hover:opacity-100 ml-1"
          data-testid={`delete-upload-${upload.id}`}
          title="Delete"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}

export default function UploadSupervision() {
  const { getAuthConfig, API } = useAuth();
  const navigate = useNavigate();

  const [staffList, setStaffList] = useState([]);
  const [uploads, setUploads] = useState([]);
  const [loadingStaff, setLoadingStaff] = useState(true);

  const [staffId, setStaffId] = useState("");
  const [label, setLabel] = useState("");
  const [docType, setDocType] = useState("supervision_record");
  const [customDocType, setCustomDocType] = useState("");
  const [meetingDate, setMeetingDate] = useState(new Date().toISOString().slice(0, 10));
  const [file, setFile] = useState(null);
  const [dragOver, setDragOver] = useState(false);

  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");

  const fileInputRef = useRef(null);
  const pollRef = useRef(null);

  const fetchStaff = async () => {
    try {
      const { data } = await cachedGet(`${API}/admin/users`, getAuthConfig());
      setStaffList(data.filter(u => u.is_active !== false));
    } catch {
      setError("Could not load staff list");
    }
    setLoadingStaff(false);
  };

  const fetchUploads = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API}/doc-uploads/`, getAuthConfig());
      setUploads(data);
    } catch {}
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [API]);

  useEffect(() => {
    fetchStaff();
    fetchUploads();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Poll while any upload is still in-flight (processing = extracting text, text_ready = AI mapping)
  useEffect(() => {
    const hasProcessing = uploads.some(u => ["processing", "text_ready"].includes(u.status));
    if (hasProcessing && !pollRef.current) {
      pollRef.current = setInterval(fetchUploads, 3000);
    } else if (!hasProcessing && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, [uploads, fetchUploads]);

  const handleFile = (f) => {
    if (!f) return;
    const ext = f.name.split(".").pop().toLowerCase();
    if (!["pdf", "docx"].includes(ext)) {
      setError("Only PDF and DOCX files are supported");
      return;
    }
    setFile(f);
    setError("");
    if (!label) setLabel(f.name.replace(/\.[^.]+$/, ""));
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    if (!staffId) return setError("Please select a staff member");
    if (!file) return setError("Please select a file to upload");

    setUploading(true);
    const form = new FormData();
    form.append("file", file);
    form.append("staff_id", staffId);
    form.append("label", label);
    form.append("meeting_date", meetingDate);
    form.append("doc_type", docType === "other" && customDocType.trim() ? customDocType.trim() : docType);

    try {
      await axios.post(`${API}/doc-uploads/`, form, {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      });
      setFile(null);
      setLabel("");
      setStaffId("");
      setDocType("supervision_record");
      setCustomDocType("");
      setMeetingDate(new Date().toISOString().slice(0, 10));
      fetchUploads();
    } catch (err) {
      setError(err.response?.data?.detail || "Upload failed");
    }
    setUploading(false);
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this document upload?")) return;
    try {
      await axios.delete(`${API}/doc-uploads/${id}`, getAuthConfig());
      setUploads(prev => prev.filter(u => u.id !== id));
    } catch {
      setError("Failed to delete upload");
    }
  };

  return (
    <Layout>
      <div className="max-w-5xl mx-auto p-6 md:p-8 fade-in">
        {/* Page header */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-1">
            <div className="w-8 h-8 rounded-lg bg-indigo-100 flex items-center justify-center">
              <FileUp className="w-4 h-4 text-indigo-700" />
            </div>
            <h1 className="text-2xl font-semibold text-gray-900 font-display">Import Supervision Document</h1>
          </div>
          <p className="text-sm text-gray-500 ml-11">
            Upload any document for a staff member — supervision records, job descriptions, feedback, observations and more — to scan for CQC and Care Certificate evidence.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-5 gap-8">

          {/* ── Upload form ───────────────────────────────────── */}
          <div className="lg:col-span-2">
            <form onSubmit={handleSubmit} className="bg-white border border-gray-200 rounded-xl p-6 space-y-5">
              <h2 className="text-sm font-semibold text-gray-800">Document details</h2>

              {/* Staff member */}
              <div>
                <label className="flex items-center gap-1.5 text-xs font-medium text-gray-700 mb-1.5">
                  <User className="w-3.5 h-3.5" /> Staff member
                </label>
                {loadingStaff ? (
                  <div className="flex items-center gap-2 text-sm text-gray-400 py-2">
                    <Loader2 className="w-4 h-4 animate-spin" /> Loading…
                  </div>
                ) : (
                  <select
                    value={staffId}
                    onChange={e => setStaffId(e.target.value)}
                    required
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white"
                    data-testid="staff-select"
                  >
                    <option value="">Select staff member…</option>
                    {staffList.map(u => (
                      <option key={u.id} value={u.id}>{u.name} ({u.role})</option>
                    ))}
                  </select>
                )}
              </div>

              {/* Meeting date */}
              <div>
                <label className="flex items-center gap-1.5 text-xs font-medium text-gray-700 mb-1.5">
                  <Calendar className="w-3.5 h-3.5" /> Supervision date
                </label>
                <input
                  type="date"
                  value={meetingDate}
                  onChange={e => setMeetingDate(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  data-testid="meeting-date-input"
                />
              </div>

              {/* Label */}
              <div>
                <label className="flex items-center gap-1.5 text-xs font-medium text-gray-700 mb-1.5">
                  <Tag className="w-3.5 h-3.5" /> Document label <span className="text-gray-400 font-normal">(optional)</span>
                </label>
                <input
                  type="text"
                  value={label}
                  onChange={e => setLabel(e.target.value)}
                  placeholder="e.g. Annual review Jan 2025"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  data-testid="label-input"
                />
              </div>

              {/* Document type */}
              <div>
                <label className="flex items-center gap-1.5 text-xs font-medium text-gray-700 mb-1.5">
                  <Tag className="w-3.5 h-3.5" /> Document type
                </label>
                <select
                  value={docType}
                  onChange={e => setDocType(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white"
                  data-testid="doc-type-select"
                >
                  {DOC_TYPE_OPTIONS.map(o => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
                {docType === "other" && (
                  <input
                    type="text"
                    value={customDocType}
                    onChange={e => setCustomDocType(e.target.value)}
                    placeholder="Describe the document type…"
                    className="w-full mt-1.5 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    data-testid="custom-doc-type-input"
                  />
                )}
              </div>

              {/* File upload zone */}
              <div>
                <label className="flex items-center gap-1.5 text-xs font-medium text-gray-700 mb-1.5">
                  <Upload className="w-3.5 h-3.5" /> Document file
                </label>
                <div
                  onDragOver={e => { e.preventDefault(); setDragOver(true); }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={handleDrop}
                  onClick={() => fileInputRef.current?.click()}
                  className={`border-2 border-dashed rounded-lg p-5 text-center cursor-pointer transition-colors ${
                    dragOver
                      ? "border-indigo-400 bg-indigo-50"
                      : file
                      ? "border-emerald-400 bg-emerald-50"
                      : "border-gray-300 hover:border-indigo-400 hover:bg-indigo-50/40"
                  }`}
                  data-testid="file-drop-zone"
                >
                  {file ? (
                    <div className="flex items-center justify-center gap-2">
                      <FileText className="w-5 h-5 text-emerald-600" />
                      <span className="text-sm font-medium text-emerald-700 truncate max-w-[180px]">{file.name}</span>
                      <button
                        type="button"
                        onClick={e => { e.stopPropagation(); setFile(null); }}
                        className="ml-1 text-gray-400 hover:text-red-500"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                  ) : (
                    <>
                      <Upload className="w-6 h-6 mx-auto mb-2 text-gray-400" />
                      <p className="text-sm text-gray-500">Drop a file or <span className="text-indigo-600 font-medium">browse</span></p>
                      <p className="text-xs text-gray-400 mt-1">PDF or Word (.docx) · max 20 MB</p>
                    </>
                  )}
                </div>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,.docx"
                  className="hidden"
                  onChange={e => handleFile(e.target.files[0])}
                  data-testid="file-input"
                />
              </div>

              {error && (
                <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg p-3 text-xs">
                  <AlertCircle className="w-4 h-4 flex-shrink-0" />
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={uploading || !file || !staffId}
                className="w-full flex items-center justify-center gap-2 bg-[#1E3A8A] text-white py-2.5 rounded-lg text-sm font-medium hover:bg-[#1E40AF] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                data-testid="submit-upload-btn"
              >
                {uploading ? (
                  <><Loader2 className="w-4 h-4 animate-spin" /> Uploading…</>
                ) : (
                  <><FileUp className="w-4 h-4" /> Import &amp; Scan for Evidence</>
                )}
              </button>
            </form>
          </div>

          {/* ── Uploads list ──────────────────────────────────── */}
          <div className="lg:col-span-3">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-gray-800">Recent imports</h2>
              {uploads.some(u => u.status === "processing") && (
                <span className="inline-flex items-center gap-1.5 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2.5 py-1">
                  <Clock className="w-3 h-3 animate-pulse" /> Scanning…
                </span>
              )}
            </div>

            {uploads.length === 0 ? (
              <div className="bg-white border border-dashed border-gray-200 rounded-xl p-10 text-center">
                <FileUp className="w-8 h-8 mx-auto mb-3 text-gray-300" />
                <p className="text-sm text-gray-500">No documents imported yet</p>
                <p className="text-xs text-gray-400 mt-1">Upload a supervision document to get started</p>
              </div>
            ) : (
              <div className="space-y-3">
                {uploads.map(u => (
                  <UploadCard
                    key={u.id}
                    upload={u}
                    onDelete={handleDelete}
                    navigate={navigate}
                  />
                ))}
              </div>
            )}
          </div>

        </div>
      </div>
    </Layout>
  );
}

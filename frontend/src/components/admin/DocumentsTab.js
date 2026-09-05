import React, { useState } from "react";
import { FileText, ToggleLeft, ToggleRight, ChevronDown, ChevronUp, Trash2, BookOpen, Upload, Loader2, CheckCircle, AlertCircle, Download } from "lucide-react";

function ParseStatusBadge({ status }) {
  const cfg = {
    parsing:  { cls: "bg-amber-100 text-amber-700", label: "Parsing…", icon: <Loader2 className="w-3 h-3 animate-spin" /> },
    parsed:   { cls: "bg-emerald-100 text-emerald-700", label: "Ready", icon: <CheckCircle className="w-3 h-3" /> },
    failed:   { cls: "bg-red-100 text-red-700", label: "Failed", icon: <AlertCircle className="w-3 h-3" /> },
    uploaded: { cls: "bg-gray-100 text-gray-500", label: "Uploading…", icon: <Loader2 className="w-3 h-3 animate-spin" /> },
  };
  const c = cfg[status] || cfg.uploaded;
  return (
    <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium ${c.cls}`}>
      {c.icon} {c.label}
    </span>
  );
}

function DocCard({ doc, onToggle, onDelete, onDownload }) {
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
          <button onClick={() => onDownload(doc.id, doc.filename)} title="Download original file" className="p-1 text-gray-400 hover:text-teal-600 transition-colors" data-testid={`download-doc-${doc.id}`}>
            <Download className="w-4 h-4" />
          </button>
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

export function DocumentsTab({ docs, uploading, uploadLabel, setUploadLabel, handleUploadDoc, handleToggleDoc, handleDeleteDoc, handleDownloadDoc, fileInputRef }) {
  return (
    <div>
      <div className="mb-4 p-4 bg-teal-50 border border-teal-200 rounded-lg text-sm text-teal-800">
        <strong>How it works:</strong> Upload any document — job description, company values, policy document, competency framework. The AI will extract standards and criteria from it. These will then be included automatically in all future meeting evidence matching.
      </div>

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
              {uploading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
              {uploading ? "Uploading…" : "Choose File"}
              <input ref={fileInputRef} type="file" accept=".pdf,.docx,.txt,.md,.csv" onChange={handleUploadDoc} className="hidden" disabled={uploading} />
            </label>
          </div>
        </div>
        <p className="text-xs text-gray-400 mt-2">Accepted: PDF, DOCX, TXT, MD, CSV. The AI will extract criteria automatically (~10–30 seconds).</p>
      </div>

      {docs.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          <BookOpen className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p className="text-sm font-medium">No documents uploaded yet</p>
          <p className="text-xs mt-1">Upload a document above to get started</p>
        </div>
      ) : (
        <div className="space-y-3" data-testid="documents-list">
          {docs.map(doc => (
            <DocCard key={doc.id} doc={doc} onToggle={handleToggleDoc} onDelete={handleDeleteDoc} onDownload={handleDownloadDoc} />
          ))}
        </div>
      )}
    </div>
  );
}

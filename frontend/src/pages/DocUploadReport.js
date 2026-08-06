import React, { useState, useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import { EvidenceSidebar } from "@/components/report/EvidenceSidebar";
import {
  ArrowLeft, FileText, User, Calendar, Upload, Loader, AlertCircle,
  CheckCircle, Clock
} from "lucide-react";

const STATUS_CONFIG = {
  processing: {
    icon: Loader,
    color: "text-amber-700",
    bg: "bg-amber-50 border-amber-200",
    label: "Scanning document for evidence…",
    spin: true,
  },
  done: {
    icon: CheckCircle,
    color: "text-emerald-700",
    bg: "bg-emerald-50 border-emerald-200",
    label: "Evidence scan complete",
  },
  failed: {
    icon: AlertCircle,
    color: "text-red-700",
    bg: "bg-red-50 border-red-200",
    label: "Scan failed",
  },
};

export default function DocUploadReport() {
  const { uploadId } = useParams();
  const { getAuthConfig, API } = useAuth();
  const navigate = useNavigate();

  const [upload, setUpload] = useState(null);
  const [loading, setLoading] = useState(true);
  const pollRef = useRef(null);

  const fetchUpload = async () => {
    try {
      const { data } = await axios.get(`${API}/doc-uploads/${uploadId}`, getAuthConfig());
      setUpload(data);
      if (!["processing", "text_ready"].includes(data.status) && pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    } catch (err) {
      console.error("Failed to load upload:", err);
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchUpload();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uploadId]);

  // Start polling if status is still in-flight (extracting text or AI mapping)
  useEffect(() => {
    if (["processing", "text_ready"].includes(upload?.status) && !pollRef.current) {
      pollRef.current = setInterval(fetchUpload, 3000);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [upload?.status]);

  if (loading) {
    return (
      <Layout>
        <div className="flex items-center justify-center h-full py-24">
          <div className="flex items-center gap-3 text-gray-500">
            <div className="w-5 h-5 border-2 border-[#1E3A8A] border-t-transparent rounded-full animate-spin"></div>
            <span className="text-sm">Loading…</span>
          </div>
        </div>
      </Layout>
    );
  }

  if (!upload) {
    return (
      <Layout>
        <div className="p-8 text-center text-gray-500">Document not found</div>
      </Layout>
    );
  }

  const cfg = STATUS_CONFIG[upload.status] || STATUS_CONFIG.processing;
  const StatusIcon = cfg.icon;

  const analysis = {
    cqc_mappings: upload.cqc_mappings || [],
    care_cert_mappings: upload.care_cert_mappings || [],
    custom_mappings: upload.custom_mappings || [],
  };

  const totalCount = analysis.cqc_mappings.length + analysis.care_cert_mappings.length + analysis.custom_mappings.length;

  return (
    <Layout>
      <div className="flex flex-col h-full">

        {/* ── Top bar ──────────────────────────────────────────── */}
        <div className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between sticky top-0 z-20 flex-shrink-0">
          <div className="flex items-center gap-4 min-w-0">
            <button
              onClick={() => navigate(-1)}
              className="text-gray-500 hover:text-gray-700 flex-shrink-0"
              data-testid="back-btn"
            >
              <ArrowLeft className="w-4 h-4" />
            </button>

            <div className="flex items-center gap-3 min-w-0">
              <div className="w-9 h-9 rounded-lg bg-indigo-50 border border-indigo-100 flex items-center justify-center flex-shrink-0">
                <FileText className="w-4 h-4 text-indigo-600" />
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <h1 className="text-base font-semibold text-gray-900 font-display truncate">
                    {upload.label || upload.filename}
                  </h1>
                  <span className="inline-flex items-center text-xs px-2 py-0.5 bg-indigo-50 border border-indigo-200 text-indigo-700 rounded-full font-medium flex-shrink-0">
                    Document Import
                  </span>
                </div>
                <div className="flex items-center gap-3 mt-0.5 text-xs text-gray-500 flex-wrap">
                  <span className="flex items-center gap-1">
                    <User className="w-3 h-3" /> {upload.staff_name}
                  </span>
                  <span className="flex items-center gap-1">
                    <Calendar className="w-3 h-3" /> {upload.meeting_date}
                  </span>
                  <span className="flex items-center gap-1">
                    <Upload className="w-3 h-3" /> Uploaded by {upload.uploader_name}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <button
            onClick={() => navigate(`/portfolio/${upload.staff_id}`)}
            className="flex items-center gap-2 text-sm text-[#1E3A8A] font-medium hover:underline flex-shrink-0 ml-4"
            data-testid="view-portfolio-btn"
          >
            View portfolio
          </button>
        </div>

        {/* ── Status banner ────────────────────────────────────── */}
        <div className={`px-6 py-3 flex items-center gap-3 border-b ${cfg.bg} flex-shrink-0`}>
          <StatusIcon className={`w-4 h-4 flex-shrink-0 ${cfg.color} ${cfg.spin ? "animate-spin" : ""}`} />
          <span className={`text-sm font-medium ${cfg.color}`}>{cfg.label}</span>
          {upload.status === "done" && (
            <span className="text-sm text-gray-500 ml-auto">{totalCount} evidence item{totalCount !== 1 ? "s" : ""} found</span>
          )}
          {upload.status === "failed" && upload.error && (
            <span className="text-sm text-red-600 ml-2">{upload.error}</span>
          )}
          {upload.status === "processing" && (
            <span className="text-xs text-amber-600 ml-auto flex items-center gap-1">
              <Clock className="w-3 h-3" /> This may take 20–30 seconds
            </span>
          )}
        </div>

        {/* ── Evidence ─────────────────────────────────────────── */}
        {upload.status === "processing" ? (
          <div className="flex-1 flex items-center justify-center py-24 text-gray-400">
            <div className="text-center">
              <div className="w-10 h-10 border-2 border-indigo-300 border-t-indigo-600 rounded-full animate-spin mx-auto mb-4"></div>
              <p className="text-sm font-medium text-gray-500">AI is scanning your document…</p>
              <p className="text-xs mt-1">Mapping content to CQC regulations and Care Certificate standards</p>
            </div>
          </div>
        ) : upload.status === "failed" ? (
          <div className="flex-1 flex items-center justify-center py-24 text-red-400">
            <div className="text-center">
              <AlertCircle className="w-10 h-10 mx-auto mb-3 opacity-50" />
              <p className="text-sm font-medium text-red-600">Evidence scan failed</p>
              <p className="text-xs text-gray-500 mt-1">{upload.error || "An unexpected error occurred"}</p>
            </div>
          </div>
        ) : (
          <div className="flex-1 overflow-hidden">
            <EvidenceSidebar
              analysis={analysis}
              canReview={false}
              updateEvidence={() => {}}
              className="h-full overflow-y-auto"
              noMaxHeight={true}
            />
          </div>
        )}

      </div>
    </Layout>
  );
}

import React, { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { cachedGet, invalidateCache } from "@/utils/apiCache";
import { useAuth } from "@/context/AuthContext";
import { Skeleton } from "@/components/ui/skeleton";
import Layout from "@/components/Layout";
import { Shield, Award, BookOpen, Users, CheckCircle, AlertCircle, X } from "lucide-react";
import { StandardsTab } from "@/components/admin/StandardsTab";
import { DocumentsTab } from "@/components/admin/DocumentsTab";
import { UsersTab } from "@/components/admin/UsersTab";

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
  const { getAuthConfig, API, user } = useAuth();
  const isAdmin = user?.role === "admin";
  const navigate = useNavigate();

  // Jurisdiction-aware tab labels
  const jurisdiction = user?.org_jurisdiction || "england";
  const serviceType = user?.org_service_type || "";
  const OFSTED_REG_LABEL  = { early_years: "EYFS Safeguarding", childrens_home: "CHQS", school: "EIF" }[serviceType] || "EIF";
  const OFSTED_CERT_LABEL = { early_years: "EYFS Learning", childrens_home: "L3 Diploma", school: "Teachers' Standards" }[serviceType] || "Teachers' Standards";
  const regLabel      = { wales: "CIW", scotland: "Care Inspectorate", northern_ireland: "RQIA", ofsted: OFSTED_REG_LABEL }[jurisdiction] || "CQC";
  const certLabel     = { wales: "AWIF / SCW", scotland: "SSSC", northern_ireland: "NISCC", ofsted: OFSTED_CERT_LABEL }[jurisdiction] || "Care Certificate";
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

  useEffect(() => {
    fetchAll();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const hasParsingDocs = docs.some(d => d.parse_status === "parsing" || d.parse_status === "uploaded");
    if (hasParsingDocs && !pollRef.current) {
      pollRef.current = setInterval(async () => {
        // Bump the SAME counter fetchAll() uses — poll and fetchAll now share one
        // monotonic request-order guard, so whichever call started LAST always wins,
        // regardless of which resolves first. Poll also bypasses the 120s doc cache
        // (via plain axios.get, not cachedGet) since its entire purpose is to observe
        // parse_status changes in near-real-time — a cached response would just replay
        // the same snapshot for up to 2 minutes.
        fetchReqRef.current += 1;
        const req = fetchReqRef.current;
        try {
          const { data } = await axios.get(`${API}/admin/standards/documents`, getAuthConfig());
          if (req !== fetchReqRef.current) return; // superseded by a newer fetchAll/poll
          invalidateCache("/admin/standards/documents");
          setDocs(data);
          const stillParsing = data.some(d => d.parse_status === "parsing" || d.parse_status === "uploaded");
          if (!stillParsing && pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
        } catch (err) { console.error("Poll status error:", err.message); }
      }, 3000);
    } else if (!hasParsingDocs && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docs]);

  // Stale-request guard: fetchAll() is called both on mount and after every
  // mutation (upload/create/delete). Without this, a slow mount-time request
  // can resolve AFTER a later post-mutation refresh and silently overwrite
  // fresh state with the pre-mutation snapshot (e.g. an uploaded document
  // briefly "disappearing" until the next unrelated refresh happens to win the race).
  const fetchReqRef = useRef(0);

  const fetchAll = async () => {
    fetchReqRef.current += 1;
    const req = fetchReqRef.current;
    setLoading(true);
    try {
      const requests = [
        cachedGet(`${API}/admin/standards`, getAuthConfig()),
        cachedGet(`${API}/admin/standards/documents`, getAuthConfig()),
      ];
      if (user?.role === "admin") {
        requests.push(cachedGet(`${API}/admin/users`, getAuthConfig()));
      }
      const results = await Promise.all(requests);
      if (req !== fetchReqRef.current) return; // a newer fetchAll superseded this one
      const [stdRes, docRes] = results;
      setStandards(stdRes.data);
      setDocs(docRes.data);
      if (user?.role === "admin" && results[2]) setUsers(results[2].data);
    } catch (err) {
      console.error("Admin fetchAll failed:", err.message);
      if (req === fetchReqRef.current) setError("Failed to load admin data. Please refresh.");
    }
    if (req === fetchReqRef.current) setLoading(false);
  };

  // "Regulations" bucket vs "Induction/Cert" bucket — must match every jurisdiction's system
  // standard `type` values, not just England's literal "cqc"/"care_cert" (pre-existing bug:
  // Wales/Scotland/NI/Ofsted standards were silently hidden because their type values
  // (ciw, ci, rqia_dom, rqia_res, eif, eyfs_safeguarding, chqs, etc.) never matched "cqc").
  const REG_TYPES = new Set(["cqc", "ciw", "ci", "rqia_dom", "rqia_res", "eif", "eyfs_safeguarding", "chqs"]);
  const cqcStandards = standards.filter(s => REG_TYPES.has(s.type));
  const ccStandards = standards.filter(s => !REG_TYPES.has(s.type));

  const handleCreateStandard = async () => {
    setError("");
    if (!newStandard.reference || !newStandard.name) return setError("Reference and name are required");
    try {
      await axios.post(`${API}/admin/standards`, newStandard, getAuthConfig());
      setMessage("Standard created");
      setShowNewStandard(false);
      setNewStandard({ type: "cqc", reference: "", name: "", description: "", keywords: [] });
      invalidateCache("/admin/standards");
      fetchAll();
    } catch (err) { setError(err.response?.data?.detail || "Failed to create"); }
  };

  const handleDeleteStandard = async (id) => {
    if (!window.confirm("Deactivate this standard?")) return;
    try {
      await axios.delete(`${API}/admin/standards/${id}`, getAuthConfig());
      setMessage("Standard deactivated");
      invalidateCache("/admin/standards");
      fetchAll();
    } catch (err) { console.error("Delete standard failed:", err.message); setError("Failed to deactivate standard."); }
  };

  const handleCreateUser = async () => {
    setError("");
    if (!newUser.email || !newUser.name || !newUser.password) return setError("All fields required");
    try {
      await axios.post(`${API}/admin/users`, newUser, getAuthConfig());
      setMessage("User created");
      setShowNewUser(false);
      setNewUser({ email: "", name: "", role: "attendee", password: "" });
      invalidateCache("/admin/users");
      fetchAll();
    } catch (err) { setError(err.response?.data?.detail || "Failed to create user"); }
  };

  const handleUpdateUser = async (userId, data) => {
    try {
      await axios.put(`${API}/admin/users/${userId}`, data, getAuthConfig());
      setMessage("User updated");
      invalidateCache("/admin/users");
      fetchAll();
    } catch (err) {
      throw new Error(err.response?.data?.detail || "Failed to update user");
    }
  };

  const handleResetPassword = async (userId, newPassword) => {
    try {
      await axios.post(`${API}/admin/users/${userId}/reset-password`, { new_password: newPassword }, getAuthConfig());
      setMessage("Password reset successfully");
    } catch (err) {
      throw new Error(err.response?.data?.detail || "Failed to reset password");
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
    try {
      await axios.post(`${API}/admin/standards/upload`, formData, {
        ...getAuthConfig(),
        headers: { "Content-Type": "multipart/form-data" },
      });
      setMessage("Document uploaded — AI is now extracting criteria (this takes ~10 seconds)");
      setUploadLabel("");
      invalidateCache("/admin/standards/documents");
      fetchAll();
    } catch (err) { setError("Upload failed: " + (err.response?.data?.detail || err.message)); }
    setUploading(false);
    e.target.value = "";
  };

  const handleToggleDoc = async (id, is_active) => {
    try {
      await axios.patch(`${API}/admin/standards/documents/${id}`, { is_active }, getAuthConfig());
      fetchReqRef.current += 1; // supersede any in-flight poll/fetchAll before this optimistic update
      setDocs(docs.map(d => d.id === id ? { ...d, is_active } : d));
      invalidateCache("/admin/standards/documents");
    } catch (err) { console.error("Toggle document failed:", err.message); setError("Failed to update document status."); }
  };

  const handleDeleteDoc = async (id) => {
    if (!window.confirm("Delete this document? It will no longer be used in evidence matching.")) return;
    try {
      await axios.delete(`${API}/admin/standards/documents/${id}`, getAuthConfig());
      fetchReqRef.current += 1; // supersede any in-flight poll/fetchAll before this optimistic update
      setDocs(docs.filter(d => d.id !== id));
      setMessage("Document deleted");
      invalidateCache("/admin/standards/documents");
    } catch (err) { console.error("Delete document failed:", err.message); setError("Failed to delete document."); }
  };

  const handleDownloadDoc = async (id, filename) => {
    try {
      const res = await axios.get(`${API}/admin/standards/documents/${id}/download`, { ...getAuthConfig(), responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url; a.download = filename || "document"; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) { console.error("Download document failed:", err.message); setError("Failed to download document."); }
  };

  if (loading) return (
    <Layout>
      <div className="p-6 md:p-8">
        {/* Page header skeleton */}
        <div className="mb-6 space-y-2">
          <Skeleton className="h-7 w-36" />
          <Skeleton className="h-4 w-56" />
        </div>
        {/* Tab bar skeleton */}
        <div className="border-b border-gray-200 mb-6 flex gap-6 pb-0">
          {[80, 104, 128, 56].map((w, i) => (
            <Skeleton key={i} className="h-4 mb-3 rounded" style={{ width: w }} />
          ))}
        </div>
        {/* Table rows skeleton */}
        <div className="space-y-2">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="flex items-center gap-4 py-3 border-b border-gray-100">
              <Skeleton className="h-4 w-20 flex-shrink-0" />
              <Skeleton className="h-4 flex-1" />
              <Skeleton className="h-5 w-16 rounded-full flex-shrink-0" />
              <Skeleton className="h-6 w-6 rounded flex-shrink-0" />
            </div>
          ))}
        </div>
      </div>
    </Layout>
  );

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
            {regLabel} ({cqcStandards.length})
          </TabBtn>
          <TabBtn active={tab === "care_cert"} onClick={() => setTab("care_cert")}>
            <Award className="inline w-3.5 h-3.5 mr-1.5" />
            {certLabel} ({ccStandards.length})
          </TabBtn>
          <TabBtn active={tab === "documents"} onClick={() => setTab("documents")}>
            <BookOpen className="inline w-3.5 h-3.5 mr-1.5" />
            Custom Standards ({docs.length})
          </TabBtn>
          {isAdmin && (
            <TabBtn active={tab === "users"} onClick={() => setTab("users")}>
              <Users className="inline w-3.5 h-3.5 mr-1.5" />
              Users ({users.length})
            </TabBtn>
          )}
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
            handleDownloadDoc={handleDownloadDoc}
            fileInputRef={fileInputRef}
          />
        )}

        {tab === "users" && isAdmin && (
          <UsersTab
            users={users}
            showNewUser={showNewUser}
            setShowNewUser={setShowNewUser}
            newUser={newUser}
            setNewUser={setNewUser}
            handleCreateUser={handleCreateUser}
            onUpdateUser={handleUpdateUser}
            onResetPassword={handleResetPassword}
            navigate={navigate}
          />
        )}
      </div>
    </Layout>
  );
}

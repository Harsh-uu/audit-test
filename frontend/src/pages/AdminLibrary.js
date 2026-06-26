import React, { useState, useEffect } from "react";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import { Shield, Award, BookOpen, Upload, Plus, Trash2, CheckCircle, AlertCircle, Users, UserPlus, X } from "lucide-react";

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

  useEffect(() => {
    fetchAll();
  }, []);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [stdRes, userRes, docRes] = await Promise.all([
        axios.get(`${API}/admin/standards`, getAuthConfig()),
        axios.get(`${API}/admin/users`, getAuthConfig()),
        axios.get(`${API}/admin/standards/documents`, getAuthConfig()),
      ]);
      setStandards(stdRes.data);
      setUsers(userRes.data);
      setDocs(docRes.data);
    } catch {}
    setLoading(false);
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
    const formData = new FormData();
    formData.append("file", file);
    const token = localStorage.getItem("supervision_token");
    try {
      await axios.post(`${API}/admin/standards/upload`, formData, {
        headers: { "Content-Type": "multipart/form-data", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      });
      setMessage("Document uploaded");
      fetchAll();
    } catch (err) {
      setError("Upload failed: " + (err.response?.data?.detail || err.message));
    }
    e.target.value = "";
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
            Documents ({docs.length})
          </TabBtn>
          <TabBtn active={tab === "users"} onClick={() => setTab("users")}>
            <Users className="inline w-3.5 h-3.5 mr-1.5" />
            Users ({users.length})
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

        {/* Documents */}
        {tab === "documents" && (
          <div>
            <div className="flex justify-end mb-4">
              <label className="flex items-center gap-2 bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors cursor-pointer" data-testid="upload-doc-btn">
                <Upload className="w-4 h-4" />
                Upload Document
                <input type="file" accept=".pdf,.doc,.docx,.txt" onChange={handleUploadDoc} className="hidden" />
              </label>
            </div>
            <div className="bg-white border border-gray-200 rounded-lg shadow-sm" data-testid="documents-list">
              {docs.length === 0 ? (
                <div className="text-center py-12 text-gray-400">
                  <BookOpen className="w-8 h-8 mx-auto mb-2 opacity-40" />
                  <p className="text-sm">No documents uploaded yet</p>
                </div>
              ) : (
                <div className="divide-y divide-gray-100">
                  {docs.map(doc => (
                    <div key={doc.id} className="flex items-center justify-between px-4 py-3" data-testid={`doc-${doc.id}`}>
                      <div>
                        <p className="text-sm font-medium text-gray-900">{doc.filename}</p>
                        <p className="text-xs text-gray-500">{(doc.size_bytes / 1024).toFixed(1)} KB · {new Date(doc.created_at).toLocaleDateString("en-GB")}</p>
                      </div>
                      <span className={`text-xs px-2 py-0.5 rounded-full ${doc.parse_status === "parsed" ? "bg-emerald-100 text-emerald-700" : "bg-gray-100 text-gray-500"}`}>
                        {doc.parse_status || "uploaded"}
                      </span>
                    </div>
                  ))}
                </div>
              )}
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
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
}

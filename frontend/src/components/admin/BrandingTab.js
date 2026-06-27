import React, { useState, useRef } from "react";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";
import { Upload, Check, AlertCircle, Image, X } from "lucide-react";

export function BrandingTab() {
  const { getAuthConfig, API, user, updateOrgBranding } = useAuth();
  const current = user?.org_branding || {};

  const [primaryColor, setPrimaryColor] = useState(current.primary_color || "#1E3A8A");
  const [hasLogo, setHasLogo] = useState(current.has_logo || false);
  const [logoPreview, setLogoPreview] = useState(
    current.has_logo ? `${API}/org/branding/logo/${user?.org_id}?t=${Date.now()}` : ""
  );
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const fileRef = useRef(null);

  const handleLogoUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setUploading(true);
    setError("");
    const formData = new FormData();
    formData.append("file", file);
    const token = localStorage.getItem("supervision_token");
    try {
      await axios.post(`${API}/org/branding/logo`, formData, {
        headers: { "Content-Type": "multipart/form-data", Authorization: `Bearer ${token}` },
      });
      setHasLogo(true);
      setLogoPreview(`${API}/org/branding/logo/${user?.org_id}?t=${Date.now()}`);
    } catch (err) {
      setError(err.response?.data?.detail || "Logo upload failed");
    }
    setUploading(false);
    e.target.value = "";
  };

  const removeLogo = async () => {
    setError("");
    try {
      await axios.put(`${API}/org/branding`, { logo_url: "" }, getAuthConfig());
      setHasLogo(false);
      setLogoPreview("");
      updateOrgBranding({ ...current, has_logo: false });
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to remove logo");
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError("");
    try {
      await axios.put(`${API}/org/branding`, { primary_color: primaryColor }, getAuthConfig());
      updateOrgBranding({ has_logo: hasLogo, primary_color: primaryColor });
      setMessage("Branding saved");
      setTimeout(() => setMessage(""), 3000);
    } catch (err) {
      setError(err.response?.data?.detail || "Save failed");
    }
    setSaving(false);
  };

  return (
    <div className="max-w-lg space-y-8" data-testid="branding-tab">

      {/* Logo */}
      <div>
        <h3 className="text-sm font-semibold text-gray-900 mb-1">Organisation Logo</h3>
        <p className="text-xs text-gray-500 mb-4">
          Shown alongside the 1two.one logo in the navigation header. PNG, JPG, SVG or WebP — max 2 MB.
        </p>
        <div className="flex items-center gap-4">
          <div className="w-28 h-16 rounded-lg border-2 border-dashed border-gray-200 flex items-center justify-center bg-gray-50 overflow-hidden flex-shrink-0">
            {logoPreview ? (
              <img
                src={logoPreview}
                alt="Organisation logo"
                className="max-w-full max-h-full object-contain p-1"
                data-testid="logo-preview"
              />
            ) : (
              <Image className="w-7 h-7 text-gray-300" />
            )}
          </div>
          <div className="space-y-2">
            <button
              onClick={() => fileRef.current?.click()}
              disabled={uploading}
              className="flex items-center gap-2 text-sm border border-gray-300 rounded-md px-3 py-1.5 text-gray-700 hover:bg-gray-50 transition-colors disabled:opacity-50"
              data-testid="upload-logo-btn"
            >
              <Upload className="w-3.5 h-3.5" />
              {uploading ? "Uploading…" : hasLogo ? "Replace Logo" : "Upload Logo"}
            </button>
            {hasLogo && (
              <button
                onClick={removeLogo}
                className="flex items-center gap-1.5 text-xs text-red-500 hover:text-red-700 transition-colors"
                data-testid="remove-logo-btn"
              >
                <X className="w-3 h-3" /> Remove logo
              </button>
            )}
            <input
              ref={fileRef}
              type="file"
              accept=".png,.jpg,.jpeg,.svg,.webp"
              className="hidden"
              onChange={handleLogoUpload}
              data-testid="logo-file-input"
            />
          </div>
        </div>
      </div>

      {/* Brand colour */}
      <div>
        <h3 className="text-sm font-semibold text-gray-900 mb-1">Brand Colour</h3>
        <p className="text-xs text-gray-500 mb-4">
          Applied to navigation highlights and active states. Enter a hex value or use the colour picker.
        </p>
        <div className="flex items-center gap-3">
          <input
            type="color"
            value={primaryColor}
            onChange={e => setPrimaryColor(e.target.value)}
            className="w-10 h-10 rounded-md border border-gray-300 cursor-pointer p-0.5 bg-white"
            data-testid="color-picker"
          />
          <input
            type="text"
            value={primaryColor}
            onChange={e => {
              if (/^#[0-9A-Fa-f]{0,6}$/.test(e.target.value)) setPrimaryColor(e.target.value);
            }}
            className="w-28 px-3 py-2 text-sm border border-gray-300 rounded-md font-mono focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
            placeholder="#1E3A8A"
            data-testid="color-hex-input"
          />
          <div
            className="w-8 h-8 rounded-full border border-gray-200 flex-shrink-0"
            style={{ backgroundColor: primaryColor }}
            title="Colour preview"
          />
          <button
            onClick={() => setPrimaryColor("#1E3A8A")}
            className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
            title="Reset to default"
          >
            Reset
          </button>
        </div>
      </div>

      {/* Feedback */}
      {message && (
        <div className="flex items-center gap-2 text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-md p-3 text-sm" data-testid="branding-success">
          <Check className="w-4 h-4 flex-shrink-0" /> {message}
        </div>
      )}
      {error && (
        <div className="flex items-center gap-2 text-red-700 bg-red-50 border border-red-200 rounded-md p-3 text-sm" data-testid="branding-error">
          <AlertCircle className="w-4 h-4 flex-shrink-0" /> {error}
        </div>
      )}

      <button
        onClick={handleSave}
        disabled={saving}
        className="bg-[#1E3A8A] text-white px-5 py-2.5 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors disabled:opacity-60"
        data-testid="save-branding-btn"
      >
        {saving ? "Saving…" : "Save Branding"}
      </button>
    </div>
  );
}

import React, { useState, useRef, useEffect } from "react";
import axios from "axios";
import { cachedGet, invalidateCache } from "@/utils/apiCache";
import { useAuth } from "@/context/AuthContext";
import { Upload, Check, AlertCircle, Image, X } from "lucide-react";
import { SPEAKER_PALETTE, DEFAULT_ORG_SPEAKER_COLORS } from "@/utils/transcriptHelpers";

const ATTENDEE_SLOT_LABELS = ["Attendee 1", "Attendee 2", "Attendee 3", "Attendee 4"];

function SwatchPicker({ label, value, onChange, testId }) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-gray-600 w-24 flex-shrink-0">{label}</span>
      <div className="flex items-center gap-1.5" data-testid={testId}>
        {SPEAKER_PALETTE.map(c => (
          <button
            key={c}
            type="button"
            onClick={() => onChange(c)}
            className="w-6 h-6 rounded-full transition-transform hover:scale-125 focus:outline-none"
            style={{
              backgroundColor: c,
              outline: value === c ? `2px solid ${c}` : "none",
              outlineOffset: "2px",
              boxShadow: value === c ? "0 0 0 1.5px white inset" : "none",
            }}
            title={c}
            data-testid={`${testId}-swatch-${c}`}
          />
        ))}
      </div>
    </div>
  );
}

export function BrandingTab() {
  const { getAuthConfig, API, user, updateOrgBranding } = useAuth();
  const current = user?.org_branding || {};

  const [primaryColor, setPrimaryColor] = useState(current.primary_color || "#1E3A8A");
  const [hasLogo, setHasLogo] = useState(current.has_logo || false);
  const [logoPreview, setLogoPreview] = useState(
    current.has_logo ? `${API}/org/branding/logo/${user?.org_id}?t=${Date.now()}` : ""
  );
  const [managerColor, setManagerColor] = useState(current.speaker_colors?.manager || DEFAULT_ORG_SPEAKER_COLORS.manager);
  const [attendeeColors, setAttendeeColors] = useState(
    current.speaker_colors?.attendees?.length === 4 ? current.speaker_colors.attendees : DEFAULT_ORG_SPEAKER_COLORS.attendees
  );
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const fileRef = useRef(null);

  // Re-fetch branding on mount so we always show the persisted values,
  // even when the login response did not include org_branding.
  useEffect(() => {
    cachedGet(`${API}/org/branding`, getAuthConfig())
      .then(res => {
        if (res.data) {
          setPrimaryColor(res.data.primary_color || "#1E3A8A");
          setHasLogo(res.data.has_logo || false);
          if (res.data.has_logo) {
            setLogoPreview(`${API}/org/branding/logo/${user?.org_id}?t=${Date.now()}`);
          } else {
            setLogoPreview("");
          }
          if (res.data.speaker_colors?.manager) setManagerColor(res.data.speaker_colors.manager);
          if (res.data.speaker_colors?.attendees?.length === 4) setAttendeeColors(res.data.speaker_colors.attendees);
        }
      })
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleLogoUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setUploading(true);
    setError("");
    const formData = new FormData();
    formData.append("file", file);
    try {
      await axios.post(`${API}/org/branding/logo`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setHasLogo(true);
      setLogoPreview(`${API}/org/branding/logo/${user?.org_id}?t=${Date.now()}`);
      // Keep context in sync so other components see updated branding
      updateOrgBranding({ ...(user?.org_branding || {}), has_logo: true });
      invalidateCache("/org/branding");
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
      invalidateCache("/org/branding");
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to remove logo");
    }
  };

  const setAttendeeColor = (index, color) => {
    setAttendeeColors(prev => prev.map((c, i) => i === index ? color : c));
  };

  const handleSave = async () => {
    setSaving(true);
    setError("");
    try {
      const speaker_colors = { manager: managerColor, attendees: attendeeColors };
      await axios.put(`${API}/org/branding`, { primary_color: primaryColor, speaker_colors }, getAuthConfig());
      updateOrgBranding({ has_logo: hasLogo, primary_color: primaryColor, speaker_colors });
      invalidateCache("/org/branding");
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

      {/* Speaker colours */}
      <div>
        <h3 className="text-sm font-semibold text-gray-900 mb-1">Speaker Colours</h3>
        <p className="text-xs text-gray-500 mb-4">
          Applied to every meeting transcript org-wide, by role — not chosen per meeting. The
          manager colour is used for whoever is running the supervision; attendee colours rotate
          for everyone else, so team meetings with several attendees still read clearly.
        </p>
        <div className="space-y-2.5" data-testid="speaker-colours-section">
          <SwatchPicker label="Manager" value={managerColor} onChange={setManagerColor} testId="manager-color-picker" />
          {ATTENDEE_SLOT_LABELS.map((label, i) => (
            <SwatchPicker
              key={label}
              label={label}
              value={attendeeColors[i]}
              onChange={c => setAttendeeColor(i, c)}
              testId={`attendee-color-picker-${i + 1}`}
            />
          ))}
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

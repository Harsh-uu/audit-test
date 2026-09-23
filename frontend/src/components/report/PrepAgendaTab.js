import React from "react";
import axios from "axios";
import { toast } from "sonner";

// ── Prep Agenda Tab (inline view for report page) ───────────────────────────
const SECTION_COLORS = {
  wellbeing:            "text-sky-600 bg-sky-50",
  working_well:         "text-emerald-600 bg-emerald-50",
  needs_attention:      "text-amber-600 bg-amber-50",
  learning_development: "text-purple-600 bg-purple-50",
  achievements:         "text-rose-600 bg-rose-50",
  aob:                  "text-gray-600 bg-gray-50",
  practice_impact:      "text-teal-600 bg-teal-50",
  bonus:                "text-amber-700 bg-amber-50",
};

const COVERAGE_CONFIG = {
  covered: { label: "Covered",  cls: "bg-emerald-100 text-emerald-700", dot: "bg-emerald-500" },
  partial: { label: "Partial",  cls: "bg-amber-100 text-amber-700",    dot: "bg-amber-400" },
  missed:  { label: "Missed",   cls: "bg-red-100 text-red-600",        dot: "bg-red-500" },
};

export function PrepAgendaTab({ meetingId, API, getAuthConfig, role, navigate }) {
  const [prep, setPrep] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [carryingForward, setCarryingForward] = React.useState(false);

  React.useEffect(() => {
    axios.get(`${API}/prep/${meetingId}`, getAuthConfig())
      .then(r => setPrep(r.data))
      .catch(() => setPrep(null))
      .finally(() => setLoading(false));
  }, [meetingId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) return <div className="flex justify-center py-12"><div className="w-6 h-6 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" /></div>;

  if (!prep?.sections?.length) {
    return (
      <div className="text-center py-12 space-y-3">
        <div className="w-12 h-12 rounded-full bg-indigo-50 flex items-center justify-center mx-auto">
          <span className="text-2xl">✨</span>
        </div>
        <p className="text-sm text-gray-500">No prep agenda for this meeting yet.</p>
        {(role === "manager" || role === "admin") && (
          <button
            onClick={() => navigate(`/meetings/${meetingId}/prepare`)}
            className="inline-flex items-center gap-1.5 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 transition-colors"
          >
            Create prep agenda
          </button>
        )}
      </div>
    );
  }

  const coverage = prep.coverage_results || {};
  const hasCoverage = Object.keys(coverage).length > 0;
  const missedQuestions = [];

  if (hasCoverage) {
    prep.sections?.forEach(section => {
      section.questions?.forEach(q => {
        if (q.included !== false && coverage[q.id]?.status === "missed") {
          missedQuestions.push({ ...q, section_label: section.label });
        }
      });
    });
  }

  const handleCarryForward = async () => {
    if (!missedQuestions.length) return;
    setCarryingForward(true);
    try {
      // Convert each missed question to an action via the review endpoint
      await axios.post(`${API}/prep/${meetingId}/carry-forward-missed`, {}, getAuthConfig());
      toast.success(`${missedQuestions.length} missed question${missedQuestions.length > 1 ? "s" : ""} added as actions.`);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to carry forward");
    } finally { setCarryingForward(false); }
  };

  return (
    <div className="space-y-4">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {prep.focus_topic && (
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-indigo-50 border border-indigo-200">
              <span className="text-xs font-semibold text-indigo-700">Focus:</span>
              <span className="text-sm text-indigo-800">{prep.focus_topic}</span>
            </div>
          )}
          {hasCoverage && (
            <div className="flex items-center gap-2 text-xs">
              {["covered","partial","missed"].map(s => {
                const count = Object.values(coverage).filter(r => r.status === s).length;
                if (!count) return null;
                const cfg = COVERAGE_CONFIG[s];
                return <span key={s} className={`px-2 py-0.5 rounded-full font-medium ${cfg.cls}`}>{count} {cfg.label}</span>;
              })}
            </div>
          )}
        </div>
        {(role === "manager" || role === "admin") && (
          <button onClick={() => navigate(`/meetings/${meetingId}/prepare`)} className="text-xs text-indigo-600 hover:underline">
            Edit prep →
          </button>
        )}
      </div>

      {/* Missed questions carry-forward banner */}
      {hasCoverage && missedQuestions.length > 0 && (
        <div className="flex items-center gap-3 p-3 rounded-lg bg-amber-50 border border-amber-200">
          <span className="text-xs text-amber-800 flex-1">
            <strong>{missedQuestions.length} question{missedQuestions.length > 1 ? "s" : ""}</strong> weren't covered in this session.
          </span>
          <button
            onClick={handleCarryForward}
            disabled={carryingForward}
            className="text-xs px-3 py-1.5 bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-60 transition-colors"
            data-testid="carry-forward-btn"
          >
            {carryingForward ? "Adding…" : "Carry forward as actions"}
          </button>
        </div>
      )}

      {!prep.shared_with_attendees && role === "attendee" && (
        <p className="text-xs text-gray-400 italic">The prep agenda hasn't been shared with you yet.</p>
      )}

      {/* Sections */}
      {prep.sections.map(section => {
        const included = (section.questions || []).filter(q => q.included !== false);
        if (!included.length) return null;
        const colorCls = SECTION_COLORS[section.section_id] || "text-gray-600 bg-gray-50";
        return (
          <div key={section.section_id} className="space-y-2">
            <h3 className={`text-xs font-semibold uppercase tracking-wide px-2 py-1 rounded-md inline-block ${colorCls}`}>{section.label}</h3>
            <ul className="space-y-2 pl-1">
              {included.map(q => {
                const cov = coverage[q.id];
                const cfg = cov ? COVERAGE_CONFIG[cov.status] : null;
                return (
                  <li key={q.id} className="flex items-start gap-2.5">
                    {cfg && (
                      <span className={`mt-1.5 w-2 h-2 rounded-full flex-shrink-0 ${cfg.dot}`} title={cfg.label} />
                    )}
                    {!cfg && <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-gray-300 flex-shrink-0" />}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-gray-700 leading-relaxed">{q.text}</p>
                      {cov?.evidence && (
                        <p className="text-xs text-gray-400 italic mt-0.5">"{cov.evidence}"</p>
                      )}
                    </div>
                    {cfg && (
                      <span className={`flex-shrink-0 text-xs px-2 py-0.5 rounded-full font-medium ${cfg.cls}`}>{cfg.label}</span>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

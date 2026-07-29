import React, { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import axios from "axios";
import { useAuth } from "../context/AuthContext";
import { toast } from "sonner";
import {
  Sparkles, ChevronDown, ChevronUp, Plus, Trash2, Edit2,
  Check, X, Share2, ArrowLeft, RefreshCw, BookOpen,
  FileText, Users, Building2, Target, Loader, Eye, EyeOff, ChevronRight, Mic,
} from "lucide-react";

const SECTIONS = [
  { id: "wellbeing",            label: "Wellbeing",               color: "bg-sky-50 border-sky-200",     dot: "bg-sky-400" },
  { id: "working_well",         label: "What's Working Well",      color: "bg-emerald-50 border-emerald-200", dot: "bg-emerald-400" },
  { id: "needs_attention",      label: "What Needs Attention",     color: "bg-amber-50 border-amber-200", dot: "bg-amber-400" },
  { id: "learning_development", label: "Learning & Development",   color: "bg-purple-50 border-purple-200", dot: "bg-purple-400" },
  { id: "achievements",         label: "Achievements",             color: "bg-rose-50 border-rose-200",   dot: "bg-rose-400" },
  { id: "aob",                  label: "Any Other Business",       color: "bg-gray-50 border-gray-200",   dot: "bg-gray-400" },
];

const SOURCE_ICONS = {
  previous_meeting: Users,
  doc_upload: FileText,
  org_standards: Building2,
};

const DOC_TYPE_LABELS = {
  supervision_record: "Prev. Supervision",
  job_description: "Job Description",
  service_user_feedback: "Service User Feedback",
  family_carer_feedback: "Family Feedback",
  peer_staff_feedback: "Peer Feedback",
  observation_record: "Observation",
  performance_review: "Performance Review",
  training_record: "Training Record",
  other: "Document",
};

// ── Single question row ────────────────────────────────────────────────────────
function QuestionRow({ question, onToggle, onEdit, onDelete }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(question.text);

  const save = () => { onEdit(question.id, text); setEditing(false); };

  return (
    <div
      className={`group flex items-start gap-3 p-3 rounded-lg border transition-all ${
        question.included ? "bg-white border-gray-200" : "bg-gray-50 border-dashed border-gray-200 opacity-50"
      }`}
      data-testid={`question-row-${question.id}`}
    >
      <button
        onClick={() => onToggle(question.id)}
        className={`mt-0.5 flex-shrink-0 w-5 h-5 rounded border-2 flex items-center justify-center transition-colors ${
          question.included ? "bg-[#1E3A8A] border-[#1E3A8A] text-white" : "border-gray-300"
        }`}
        title={question.included ? "Exclude this question" : "Include this question"}
      >
        {question.included && <Check className="w-3 h-3" />}
      </button>

      <div className="flex-1 min-w-0">
        {editing ? (
          <div className="space-y-2">
            <textarea
              value={text}
              onChange={e => setText(e.target.value)}
              rows={2}
              className="w-full text-sm border border-indigo-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
              autoFocus
            />
            <div className="flex gap-2">
              <button onClick={save} className="text-xs px-2.5 py-1 bg-[#1E3A8A] text-white rounded-md">Save</button>
              <button onClick={() => { setEditing(false); setText(question.text); }} className="text-xs px-2.5 py-1 border rounded-md text-gray-600">Cancel</button>
            </div>
          </div>
        ) : (
          <p className="text-sm text-gray-800 leading-relaxed">{question.text}</p>
        )}
      </div>

      <div className="flex-shrink-0 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button onClick={() => setEditing(true)} className="p-1 text-gray-400 hover:text-indigo-600 rounded" title="Edit question">
          <Edit2 className="w-3.5 h-3.5" />
        </button>
        <button onClick={() => onDelete(question.id)} className="p-1 text-gray-400 hover:text-red-500 rounded" title="Remove question">
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}

// ── Section panel ─────────────────────────────────────────────────────────────
function SectionPanel({ section, sectionMeta, onChange }) {
  const [open, setOpen] = useState(true);
  const [adding, setAdding] = useState(false);
  const [newText, setNewText] = useState("");

  const questions = section?.questions || [];
  const included = questions.filter(q => q.included).length;

  const handleToggle = (qid) => {
    onChange({ ...section, questions: questions.map(q => q.id === qid ? { ...q, included: !q.included } : q) });
  };
  const handleEdit = (qid, text) => {
    onChange({ ...section, questions: questions.map(q => q.id === qid ? { ...q, text } : q) });
  };
  const handleDelete = (qid) => {
    onChange({ ...section, questions: questions.filter(q => q.id !== qid) });
  };
  const handleAdd = () => {
    if (!newText.trim()) return;
    const q = { id: `manual_${Date.now()}`, text: newText.trim(), generated: false, included: true };
    onChange({ ...section, questions: [...questions, q] });
    setNewText(""); setAdding(false);
  };

  return (
    <div className={`rounded-xl border-2 ${sectionMeta.color} overflow-hidden`}>
      <button
        className="w-full flex items-center gap-3 px-4 py-3"
        onClick={() => setOpen(o => !o)}
      >
        <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${sectionMeta.dot}`} />
        <span className="flex-1 text-left text-sm font-semibold text-gray-800">{sectionMeta.label}</span>
        <span className="text-xs text-gray-500 mr-2">{included}/{questions.length} included</span>
        {open ? <ChevronUp className="w-4 h-4 text-gray-400" /> : <ChevronDown className="w-4 h-4 text-gray-400" />}
      </button>

      {open && (
        <div className="px-4 pb-4 space-y-2">
          {questions.length === 0 && (
            <p className="text-xs text-gray-400 italic py-2">No questions yet — add one below or regenerate.</p>
          )}
          {questions.map(q => (
            <QuestionRow
              key={q.id}
              question={q}
              onToggle={handleToggle}
              onEdit={handleEdit}
              onDelete={handleDelete}
            />
          ))}

          {adding ? (
            <div className="space-y-2 pt-1">
              <textarea
                value={newText}
                onChange={e => setNewText(e.target.value)}
                placeholder="Type your question (make it open-ended — avoid yes/no answers)…"
                rows={2}
                className="w-full text-sm border border-indigo-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
                autoFocus
              />
              <div className="flex gap-2">
                <button onClick={handleAdd} className="text-xs px-2.5 py-1 bg-[#1E3A8A] text-white rounded-md">Add</button>
                <button onClick={() => { setAdding(false); setNewText(""); }} className="text-xs px-2.5 py-1 border rounded-md text-gray-600">Cancel</button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setAdding(true)}
              className="flex items-center gap-1.5 text-xs text-indigo-600 hover:text-indigo-800 mt-1 py-1"
            >
              <Plus className="w-3.5 h-3.5" /> Add question
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── Context source card ───────────────────────────────────────────────────────
function SourceCard({ source, included, onToggle }) {
  const Icon = SOURCE_ICONS[source.source_type] || FileText;
  const typeLabel = source.doc_type ? (DOC_TYPE_LABELS[source.doc_type] || source.doc_type) : null;

  return (
    <div
      className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer select-none transition-all ${
        included ? "border-indigo-300 bg-indigo-50" : "border-gray-200 bg-white opacity-60"
      }`}
      onClick={() => onToggle(source.source_id)}
      data-testid={`source-card-${source.source_id}`}
    >
      <div className={`mt-0.5 p-1.5 rounded-lg ${included ? "bg-indigo-100" : "bg-gray-100"}`}>
        <Icon className={`w-4 h-4 ${included ? "text-indigo-600" : "text-gray-400"}`} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-800 truncate">{source.label}</p>
        <p className="text-xs text-gray-500">
          {typeLabel && <span className="mr-1.5">{typeLabel}</span>}
          {source.date && <span>{source.date}</span>}
        </p>
      </div>
      <div className={`flex-shrink-0 w-5 h-5 rounded border-2 flex items-center justify-center mt-0.5 ${
        included ? "bg-indigo-600 border-indigo-600 text-white" : "border-gray-300"
      }`}>
        {included && <Check className="w-3 h-3" />}
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function MeetingPrep() {
  const { meetingId } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const fromNew = searchParams.get("from") === "new"; // came from New Meeting wizard step 3
  const { API, getAuthConfig, user } = useAuth();

  const [meeting, setMeeting] = useState(null);
  const [context, setContext] = useState(null);
  const [prep, setPrep] = useState(null);
  const [sections, setSections] = useState([]);
  const [focusTopic, setFocusTopic] = useState("");
  const [includedSourceIds, setIncludedSourceIds] = useState(null); // null = all
  const [focusTopics, setFocusTopics] = useState([]);
  const [saving, setSaving] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [loading, setLoading] = useState(true);
  const pollRef = useRef(null);

  // ── Load ───────────────────────────────────────────────────────────────────
  const loadAll = useCallback(async () => {
    try {
      const [meetingRes, ctxRes, prepRes, ftRes] = await Promise.all([
        axios.get(`${API}/meetings/${meetingId}`, getAuthConfig()),
        axios.get(`${API}/prep/${meetingId}/context`, getAuthConfig()),
        axios.get(`${API}/prep/${meetingId}`, getAuthConfig()),
        axios.get(`${API}/prep/focus-topics`, getAuthConfig()),
      ]);
      setMeeting(meetingRes.data);
      setContext(ctxRes.data);
      const p = prepRes.data;
      setPrep(p);
      if (p.sections?.length) setSections(p.sections);
      if (p.focus_topic !== undefined) setFocusTopic(p.focus_topic || "");
      if (p.included_source_ids?.length) setIncludedSourceIds(p.included_source_ids);
      setFocusTopics(ftRes.data || []);
      // Default focus topic from org if none set
      if (!p.focus_topic) {
        const current = (ftRes.data || []).find(t => t.is_current);
        if (current) setFocusTopic(current.topic);
      }
    } catch {
      toast.error("Failed to load prep data");
    } finally { setLoading(false); }
  }, [API, meetingId, getAuthConfig]);

  useEffect(() => { loadAll(); }, [loadAll]);

  // ── Poll while generating ──────────────────────────────────────────────────
  useEffect(() => {
    const status = prep?.gen_status;
    if (status === "generating") {
      pollRef.current = setInterval(async () => {
        try {
          const { data } = await axios.get(`${API}/prep/${meetingId}`, getAuthConfig());
          setPrep(data);
          if (data.gen_status !== "generating") {
            clearInterval(pollRef.current);
            if (data.gen_status === "done") {
              setSections(data.sections || []);
              toast.success("Questions generated — review and edit below.");
            } else {
              toast.error("Question generation failed. Try again.");
            }
          }
        } catch { clearInterval(pollRef.current); }
      }, 3000);
    }
    return () => clearInterval(pollRef.current);
  }, [prep?.gen_status, API, meetingId, getAuthConfig]);

  // ── Helpers ────────────────────────────────────────────────────────────────
  const allSources = context?.sources || [];
  const effectiveIds = includedSourceIds || allSources.map(s => s.source_id);
  const isLocked = !!focusTopics.find(t => t.is_current && t.topic === focusTopic);

  const handleSourceToggle = (sid) => {
    setIncludedSourceIds(prev => {
      const current = prev || allSources.map(s => s.source_id);
      return current.includes(sid) ? current.filter(id => id !== sid) : [...current, sid];
    });
  };

  const handleGenerate = async () => {
    try {
      await axios.post(
        `${API}/prep/${meetingId}/generate`,
        null,
        { ...getAuthConfig(), params: { focus_topic: focusTopic, included_source_ids: effectiveIds } }
      );
      setPrep(p => ({ ...p, gen_status: "generating" }));
      toast.info("Generating questions… won't be long.");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Generation failed");
    }
  };

  const handleSave = async (share = false, goRecord = false) => {
    setSaving(true);
    try {
      await axios.put(`${API}/prep/${meetingId}`, {
        focus_topic: focusTopic,
        context_source_ids: effectiveIds,
        sections: sections.map(s => ({
          section_id: s.section_id,
          label: s.label,
          questions: s.questions.map(q => ({ id: q.id, text: q.text, included: q.included })),
        })),
        shared_with_attendees: share || prep?.shared_with_attendees,
      }, getAuthConfig());
      if (share) {
        await axios.post(`${API}/prep/${meetingId}/share`, null, getAuthConfig());
        setPrep(p => ({ ...p, shared_with_attendees: true }));
        toast.success("Prep agenda shared with supervisee.");
      } else {
        toast.success("Prep saved.");
      }
      if (goRecord) navigate(`/meetings/${meetingId}/record`);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Save failed");
    } finally { setSaving(false); }
  };

  const handleSectionChange = (idx, updated) => {
    setSections(prev => prev.map((s, i) => i === idx ? updated : s));
  };

  const generating = prep?.gen_status === "generating";

  // ── Render ─────────────────────────────────────────────────────────────────
  if (loading) return (
    <div className="min-h-screen flex items-center justify-center">
      <Loader className="w-8 h-8 text-indigo-600 animate-spin" />
    </div>
  );

  const superviseeNames = context?.supervisees?.map(s => s.name).join(", ") || "supervisee";
  const currentFocusTopic = focusTopics.find(t => t.is_current);

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-6">
      {/* Step breadcrumb when coming from New Meeting wizard */}
      {fromNew && (
        <div className="flex items-center gap-2 text-sm mb-2">
          <span className="text-gray-400 flex items-center gap-1"><span className="w-5 h-5 rounded-full bg-gray-200 text-gray-500 flex items-center justify-center text-xs font-semibold">1</span> Meeting Details</span>
          <ChevronRight className="w-3.5 h-3.5 text-gray-300" />
          <span className="text-gray-400 flex items-center gap-1"><span className="w-5 h-5 rounded-full bg-gray-200 text-gray-500 flex items-center justify-center text-xs font-semibold">2</span> Attendees & Manager</span>
          <ChevronRight className="w-3.5 h-3.5 text-gray-300" />
          <span className="text-[#1E3A8A] font-semibold flex items-center gap-1"><span className="w-5 h-5 rounded-full bg-[#1E3A8A] text-white flex items-center justify-center text-xs font-semibold">3</span> <Sparkles className="w-3 h-3 text-indigo-600" /> Prepare</span>
        </div>
      )}

      {/* Header */}
      <div className="flex items-start gap-4">
        {!fromNew && (
          <button
            onClick={() => navigate(-1)}
            className="mt-1 p-2 rounded-lg border hover:bg-gray-50 transition-colors"
          >
            <ArrowLeft className="w-4 h-4 text-gray-600" />
          </button>
        )}
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-0.5">
            <Sparkles className="w-5 h-5 text-indigo-600" />
            <h1 className="text-xl font-bold text-gray-900">Dynamic Supervision Prep</h1>
            {prep?.shared_with_attendees && (
              <span className="px-2 py-0.5 text-xs font-medium bg-emerald-100 text-emerald-700 rounded-full flex items-center gap-1">
                <Eye className="w-3 h-3" /> Shared with supervisee
              </span>
            )}
          </div>
          <p className="text-sm text-gray-500">{meeting?.title || "Meeting"} · with {superviseeNames}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: context + focus */}
        <div className="lg:col-span-1 space-y-4">

          {/* Focus topic */}
          <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
            <div className="flex items-center gap-2">
              <Target className="w-4 h-4 text-indigo-600" />
              <h3 className="text-sm font-semibold text-gray-800">Focus Topic</h3>
            </div>
            {currentFocusTopic && currentFocusTopic.topic !== focusTopic ? (
              <button
                onClick={() => setFocusTopic(currentFocusTopic.topic)}
                className="w-full text-left text-xs px-3 py-2 rounded-lg bg-indigo-50 border border-indigo-200 text-indigo-700"
              >
                <span className="font-medium">Org focus:</span> {currentFocusTopic.topic}
                <span className="ml-2 text-indigo-500 underline">use this</span>
              </button>
            ) : null}
            <textarea
              value={focusTopic}
              onChange={e => setFocusTopic(e.target.value)}
              placeholder="e.g. Medication management, Personal development, Safeguarding…"
              rows={2}
              className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
              data-testid="focus-topic-input"
            />
            {focusTopics.filter(t => !t.is_current).length > 0 && (
              <div className="space-y-1">
                <p className="text-xs font-medium text-gray-500">Previous focus topics:</p>
                {focusTopics.filter(t => !t.is_current).slice(0, 3).map(t => (
                  <button
                    key={t.id}
                    onClick={() => setFocusTopic(t.topic)}
                    className="block text-xs text-indigo-600 hover:underline text-left"
                  >
                    {t.topic}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Context sources */}
          <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
            <div className="flex items-center gap-2">
              <BookOpen className="w-4 h-4 text-indigo-600" />
              <h3 className="text-sm font-semibold text-gray-800">Context Sources</h3>
              <span className="ml-auto text-xs text-gray-400">{effectiveIds.length}/{allSources.length} selected</span>
            </div>
            {allSources.length === 0 && (
              <p className="text-xs text-gray-400 italic">No previous supervisions or uploaded documents found for this supervisee.</p>
            )}
            <div className="space-y-2">
              {allSources.map(s => (
                <SourceCard
                  key={s.source_id}
                  source={s}
                  included={effectiveIds.includes(s.source_id)}
                  onToggle={handleSourceToggle}
                />
              ))}
            </div>
          </div>

          {/* Generate button */}
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-indigo-600 text-white rounded-xl font-semibold text-sm hover:bg-indigo-700 disabled:opacity-60 transition-colors"
            data-testid="generate-questions-btn"
          >
            {generating ? (
              <><Loader className="w-4 h-4 animate-spin" /> Generating…</>
            ) : (
              <><Sparkles className="w-4 h-4" /> {sections.length ? "Regenerate Questions" : "Generate Questions"}</>
            )}
          </button>
        </div>

        {/* Right: question sections */}
        <div className="lg:col-span-2 space-y-3">
          {generating && sections.length === 0 && (
            <div className="flex flex-col items-center justify-center gap-3 py-16 bg-white rounded-xl border border-dashed border-indigo-200">
              <Loader className="w-8 h-8 text-indigo-400 animate-spin" />
              <p className="text-sm text-gray-500">AI is crafting personalised questions…</p>
            </div>
          )}

          {sections.length === 0 && !generating && (
            <div className="flex flex-col items-center justify-center gap-3 py-16 bg-white rounded-xl border border-dashed border-gray-200">
              <Sparkles className="w-8 h-8 text-gray-300" />
              <p className="text-sm text-gray-400 text-center max-w-xs">
                Select your context sources and click <strong>Generate Questions</strong> to get personalised, open-ended supervision questions.
              </p>
            </div>
          )}

          {sections.map((section, idx) => {
            const meta = SECTIONS.find(s => s.id === section.section_id) || SECTIONS[5];
            return (
              <SectionPanel
                key={section.section_id}
                section={section}
                sectionMeta={meta}
                onChange={updated => handleSectionChange(idx, updated)}
              />
            );
          })}

          {sections.length > 0 && (
            <div className="flex items-center gap-3 pt-2 flex-wrap">
              {fromNew ? (
                <>
                  <button
                    onClick={() => handleSave(false, true)}
                    disabled={saving}
                    className="flex items-center gap-2 px-5 py-2.5 bg-[#1E3A8A] text-white rounded-xl font-medium text-sm hover:bg-[#1E40AF] transition-colors disabled:opacity-60"
                    data-testid="save-and-record-btn"
                  >
                    {saving ? <Loader className="w-4 h-4 animate-spin" /> : <Mic className="w-4 h-4" />}
                    Save Prep & Start Recording
                  </button>
                  <button
                    onClick={() => navigate(`/meetings/${meetingId}/record`)}
                    className="flex items-center gap-2 px-4 py-2.5 border border-gray-300 text-gray-600 rounded-xl font-medium text-sm hover:bg-gray-50 transition-colors"
                    data-testid="skip-prep-btn"
                  >
                    Skip — go straight to recording
                  </button>
                </>
              ) : (
                <>
                  <button
                    onClick={() => handleSave(false)}
                    disabled={saving}
                    className="flex items-center gap-2 px-4 py-2.5 border-2 border-[#1E3A8A] text-[#1E3A8A] rounded-xl font-medium text-sm hover:bg-indigo-50 transition-colors"
                    data-testid="save-prep-btn"
                  >
                    {saving ? <Loader className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                    Save for myself
                  </button>
                  <button
                    onClick={() => handleSave(true)}
                    disabled={saving || prep?.shared_with_attendees}
                    className="flex items-center gap-2 px-4 py-2.5 bg-[#1E3A8A] text-white rounded-xl font-medium text-sm hover:bg-[#1E40AF] disabled:opacity-60 transition-colors"
                    data-testid="share-prep-btn"
                  >
                    {prep?.shared_with_attendees
                      ? <><Eye className="w-4 h-4" /> Shared with {superviseeNames}</>
                      : <><Share2 className="w-4 h-4" /> Share with supervisee</>
                    }
                  </button>
                </>
              )}
            </div>
          )}

          {/* fromNew footer — always visible for skip option even before generating */}
          {fromNew && sections.length === 0 && !generating && (
            <div className="pt-2 flex items-center gap-3">
              <button
                onClick={() => navigate(`/meetings/${meetingId}/record`)}
                className="flex items-center gap-2 px-4 py-2.5 border border-gray-300 text-gray-600 rounded-xl font-medium text-sm hover:bg-gray-50 transition-colors"
                data-testid="skip-prep-btn-empty"
              >
                Skip prep — go straight to recording
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

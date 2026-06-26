import React from "react";
import { CheckCircle, ArrowUp, ArrowDown, X, Plus } from "lucide-react";

export function TemplateTab({
  template,
  setTemplate,
  templateSaving,
  newStepTitle,
  setNewStepTitle,
  newStepDesc,
  setNewStepDesc,
  handleAddStep,
  handleRemoveStep,
  handleMoveStep,
  handleSaveTemplate,
}) {
  return (
    <div data-testid="template-tab">
      <div className="mb-4 p-4 bg-indigo-50 border border-indigo-200 rounded-lg text-sm text-indigo-800">
        <strong>Supervision Template:</strong> Define the steps of your organisation's supervision method. These appear as a live checklist during recording, and the AI uses them as context when generating the meeting summary and evidence mapping.
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm mb-4">
        <div className="grid grid-cols-2 gap-4 mb-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Template name</label>
            <input
              value={template.name}
              onChange={e => setTemplate(t => ({ ...t, name: e.target.value }))}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              data-testid="template-name-input"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Description (optional)</label>
            <input
              value={template.description}
              onChange={e => setTemplate(t => ({ ...t, description: e.target.value }))}
              placeholder="e.g. Monthly 1:1 Supervision Framework"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              data-testid="template-desc-input"
            />
          </div>
        </div>

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
        <button
          onClick={handleSaveTemplate}
          disabled={templateSaving}
          className="flex items-center gap-2 bg-indigo-600 text-white px-5 py-2 rounded-md text-sm font-semibold hover:bg-indigo-700 disabled:opacity-60 transition-colors"
          data-testid="save-template-btn"
        >
          <CheckCircle className="w-4 h-4" />
          {templateSaving ? "Saving…" : "Save Template"}
        </button>
      </div>
    </div>
  );
}

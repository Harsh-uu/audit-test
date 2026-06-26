import React from "react";
import { Plus, Trash2 } from "lucide-react";

export function StandardsTab({
  tab,
  cqcStandards,
  ccStandards,
  showNewStandard,
  setShowNewStandard,
  newStandard,
  setNewStandard,
  handleCreateStandard,
  handleDeleteStandard,
}) {
  const displayStandards = tab === "cqc" ? cqcStandards : ccStandards;

  return (
    <div>
      <div className="flex justify-end mb-4">
        <button
          onClick={() => { setShowNewStandard(true); setNewStandard(s => ({ ...s, type: tab })); }}
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
              <input
                value={newStandard.reference}
                onChange={e => setNewStandard(s => ({ ...s, reference: e.target.value }))}
                placeholder="e.g. Regulation 18"
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
                data-testid="standard-reference-input"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Name</label>
              <input
                value={newStandard.name}
                onChange={e => setNewStandard(s => ({ ...s, name: e.target.value }))}
                placeholder="e.g. Staffing"
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]"
                data-testid="standard-name-input"
              />
            </div>
            <div className="col-span-2">
              <label className="block text-xs font-medium text-gray-600 mb-1">Description</label>
              <textarea
                value={newStandard.description}
                onChange={e => setNewStandard(s => ({ ...s, description: e.target.value }))}
                rows={2}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] resize-none"
                data-testid="standard-desc-input"
              />
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
            {displayStandards.map(s => (
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
            {displayStandards.length === 0 && (
              <tr><td colSpan={4} className="px-4 py-8 text-center text-sm text-gray-400">No standards found</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

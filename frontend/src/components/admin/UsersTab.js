import React from "react";
import { UserPlus, TrendingUp, X } from "lucide-react";

export function UsersTab({ users, showNewUser, setShowNewUser, newUser, setNewUser, handleCreateUser, navigate }) {
  return (
    <div>
      <div className="flex justify-end mb-4">
        <button
          onClick={() => setShowNewUser(true)}
          className="flex items-center gap-2 bg-[#1E3A8A] text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-[#1E40AF] transition-colors"
          data-testid="add-user-btn"
        >
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
              <input value={newUser.name} onChange={e => setNewUser(u => ({ ...u, name: e.target.value }))} className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]" data-testid="new-user-name" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Email</label>
              <input type="email" value={newUser.email} onChange={e => setNewUser(u => ({ ...u, email: e.target.value }))} className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]" data-testid="new-user-email" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Role</label>
              <select value={newUser.role} onChange={e => setNewUser(u => ({ ...u, role: e.target.value }))} className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A] bg-white" data-testid="new-user-role">
                <option value="attendee">Care Worker / Attendee</option>
                <option value="manager">Manager</option>
                <option value="shared_reviewer">Shared Reviewer</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Password</label>
              <input type="password" value={newUser.password} onChange={e => setNewUser(u => ({ ...u, password: e.target.value }))} className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]" data-testid="new-user-password" />
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
              <th className="text-left px-4 py-3 text-xs font-semibold text-gray-600 uppercase tracking-wide">Portfolio</th>
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
                <td className="px-4 py-3">
                  <button
                    onClick={() => navigate(`/portfolio/${u.id}`)}
                    className="flex items-center gap-1 text-xs text-[#1E3A8A] hover:underline"
                    data-testid={`view-portfolio-${u.id}`}
                  >
                    <TrendingUp className="w-3 h-3" /> Portfolio
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

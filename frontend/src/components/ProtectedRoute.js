import React from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

// ── Shimmer primitive ──────────────────────────────────────────────────────────
const Sk = ({ className }) => (
  <div className={`bg-gray-200 rounded animate-pulse ${className}`} />
);

// ── App-shell skeleton — matches Layout.js structure so the page shape is
//    painted immediately while /auth/me resolves. ──────────────────────────────
function AppShellSkeleton() {
  return (
    <div className="min-h-screen flex bg-[#F8F9FA]">

      {/* Sidebar */}
      <aside className="hidden md:flex flex-col w-56 bg-white border-r border-gray-200 flex-shrink-0">
        {/* Logo area */}
        <div className="px-4 py-5 border-b border-gray-100 flex items-center gap-3">
          <Sk className="w-8 h-8 rounded-lg flex-shrink-0" />
          <Sk className="h-4 w-24" />
        </div>

        {/* Nav items */}
        <nav className="flex-1 px-3 py-4 space-y-1">
          {[80, 64, 72, 56, 68, 60].map((w, i) => (
            <div key={i} className="flex items-center gap-3 px-2 py-2">
              <Sk className="w-4 h-4 rounded flex-shrink-0" />
              <Sk className={`h-3 w-${w === 80 ? "[80px]" : w === 64 ? "[64px]" : w === 72 ? "[72px]" : w === 56 ? "[56px]" : w === 68 ? "[68px]" : "[60px]"}`} />
            </div>
          ))}
        </nav>

        {/* User profile stub */}
        <div className="px-3 py-4 border-t border-gray-100 flex items-center gap-3">
          <Sk className="w-8 h-8 rounded-full flex-shrink-0" />
          <div className="flex-1 space-y-1">
            <Sk className="h-3 w-20" />
            <Sk className="h-2.5 w-14" />
          </div>
        </div>
      </aside>

      {/* Main content column */}
      <div className="flex-1 flex flex-col min-w-0">

        {/* Org name bar */}
        <div className="h-10 bg-[#1E3A8A] flex items-center px-6 gap-3 flex-shrink-0">
          <Sk className="h-3 w-40 bg-blue-400/40 rounded" />
          <span className="flex-1" />
          <Sk className="w-7 h-7 rounded-full bg-blue-400/40" />
        </div>

        {/* Page content shimmer */}
        <main className="flex-1 px-6 py-8 space-y-5 max-w-5xl">
          {/* Page heading */}
          <div className="space-y-2">
            <Sk className="h-6 w-48" />
            <Sk className="h-4 w-64" />
          </div>
          {/* Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {[0, 1, 2].map(i => (
              <div key={i} className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
                <Sk className="h-4 w-20" />
                <Sk className="h-7 w-12" />
                <Sk className="h-3 w-full" />
              </div>
            ))}
          </div>
          {/* List rows */}
          {[0, 1, 2, 3].map(i => (
            <div key={i} className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-4">
              <Sk className="w-10 h-10 rounded-lg flex-shrink-0" />
              <div className="flex-1 space-y-2">
                <Sk className="h-3.5 w-56" />
                <Sk className="h-3 w-36" />
              </div>
              <Sk className="h-6 w-20 rounded-full flex-shrink-0" />
            </div>
          ))}
        </main>
      </div>
    </div>
  );
}

// ── Protected route wrapper ────────────────────────────────────────────────────
export default function ProtectedRoute({ children, roles }) {
  const { user } = useAuth();
  const location = useLocation();

  // Auth check in flight — paint the app shell shape rather than a blank spinner
  if (user === undefined) return <AppShellSkeleton />;

  if (!user) return <Navigate to="/login" replace />;

  // Force password change before accessing anything else
  if (user.must_change_password && location.pathname !== "/set-password") {
    return <Navigate to="/set-password" replace />;
  }

  if (roles && !roles.includes(user.role)) {
    return <Navigate to="/dashboard" replace />;
  }

  return children;
}

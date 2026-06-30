import React, { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import {
  LayoutDashboard, Mic, LogOut, ChevronLeft, Menu, BookOpen,
  TrendingUp, Download, BarChart2, X, Building2, ShieldCheck, Calendar
} from "lucide-react";

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  const orgPrimary = user?.org_branding?.primary_color || "#1E3A8A";
  const orgLogoUrl = user?.org_branding?.has_logo && user?.org_id
    ? `${process.env.REACT_APP_BACKEND_URL}/api/org/branding/logo/${user.org_id}`
    : null;

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const isActive = (path) =>
    location.pathname === path || location.pathname.startsWith(path + "/");

  // ── Super Admin Layout ───────────────────────────────────────────────────
  if (user?.role === "super_admin") {
    return (
      <div className="flex h-screen bg-[#F8F9FA] overflow-hidden">
        <aside className="hidden lg:flex flex-col w-56 bg-[#1E3A8A] flex-shrink-0">
          <div className="p-4 border-b border-white/10">
            <div className="flex items-center gap-2">
              <img src="/logo.svg" alt="1two.one" className="w-7 h-7 flex-shrink-0" />
              <span className="font-semibold text-white text-base tracking-tight">1two.one</span>
            </div>
            <p className="text-xs text-blue-300 mt-1 font-medium">Super Admin</p>
          </div>
          <nav className="flex-1 p-3 space-y-1">
            <Link
              to="/super-admin"
              data-testid="nav-organisations"
              className={`flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-colors ${
                isActive("/super-admin") ? "bg-white/20 text-white" : "text-blue-200 hover:bg-white/10 hover:text-white"
              }`}
            >
              <Building2 className="w-4 h-4 flex-shrink-0" />
              <span>Organisations</span>
            </Link>
          </nav>
          <div className="p-3 border-t border-white/10">
            <div className="mb-2 px-3 py-2 bg-white/10 rounded-md">
              <p className="text-sm font-medium text-white truncate">{user?.name}</p>
              <p className="text-xs text-blue-300">Super Admin</p>
            </div>
            <button
              onClick={handleLogout}
              data-testid="logout-btn"
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-sm text-blue-200 hover:bg-white/10 hover:text-white transition-colors"
            >
              <LogOut className="w-4 h-4 flex-shrink-0" />
              <span>Sign out</span>
            </button>
          </div>
        </aside>

        {/* Mobile top bar for super admin */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          <div className="lg:hidden flex items-center gap-3 px-4 py-3 bg-[#1E3A8A] flex-shrink-0">
            <img src="/logo.svg" alt="1two.one" className="w-6 h-6" />
            <span className="font-semibold text-white text-sm">1two.one — Super Admin</span>
            <button onClick={handleLogout} className="ml-auto text-blue-200 hover:text-white">
              <LogOut className="w-5 h-5" />
            </button>
          </div>
          <main className="flex-1 overflow-y-auto">
            {children}
          </main>
        </div>
      </div>
    );
  }

  // ── Regular User Layout ──────────────────────────────────────────────────
  const navItems = [
    { path: "/dashboard",                 icon: LayoutDashboard, label: "Dashboard"    },
    { path: "/meetings/new",              icon: Mic,             label: "New Meeting"  },
    { path: `/portfolio/${user?.id}`,     icon: TrendingUp,      label: "My Portfolio", matchBase: "/portfolio" },
  ];

  const SidebarContent = ({ onNavClick }) => (
    <div className="flex flex-col h-full">
      {/* Logo */}
      <div className="flex items-center justify-between p-4 border-b border-gray-200 h-auto min-h-16 flex-shrink-0">
        {!collapsed && (
          <div className="flex flex-col gap-1.5 min-w-0 flex-1">
            <Link to="/dashboard" onClick={onNavClick} className="flex items-center gap-2">
              <img src="/logo.svg" alt="1two.one" className="w-8 h-8 flex-shrink-0" />
              <span className="font-semibold text-[#1E3A8A] text-lg tracking-tight">
                1two.one
              </span>
            </Link>
            {orgLogoUrl && (
              <img
                src={orgLogoUrl}
                alt="Organisation"
                className="h-7 w-auto max-w-[120px] object-contain"
                data-testid="org-logo-sidebar"
              />
            )}
          </div>
        )}
        {collapsed && <img src="/logo.svg" alt="1two.one" className="w-7 h-7 mx-auto" />}
        <button
          onClick={() => { setCollapsed(!collapsed); }}
          className="p-1 rounded hover:bg-gray-100 text-gray-500 hidden lg:block flex-shrink-0"
          data-testid="sidebar-toggle"
        >
          {collapsed ? <Menu className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
        {/* Mobile close button */}
        <button
          onClick={() => setMobileOpen(false)}
          className="p-1 rounded hover:bg-gray-100 text-gray-500 lg:hidden flex-shrink-0"
          data-testid="sidebar-mobile-close"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
        {navItems.map(({ path, icon: Icon, label, matchBase }) => {
          const active = isActive(matchBase || path);
          return (
            <Link
              key={path}
              to={path}
              onClick={onNavClick}
              data-testid={`nav-${label.toLowerCase().replace(/\s/g, "-")}`}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-colors ${
                active ? "text-white" : "text-gray-600 hover:bg-gray-100"
              }`}
              style={active ? { backgroundColor: orgPrimary } : {}}
            >
              <Icon className="w-4 h-4 flex-shrink-0" />
              {!collapsed && <span>{label}</span>}
            </Link>
          );
        })}

        {(user?.role === "admin" || user?.role === "manager") && (
          <>
            {!collapsed && (
              <div className="pt-3 pb-1 px-3 text-xs font-semibold uppercase text-gray-400 tracking-wider">Admin</div>
            )}
            {[
              { path: "/admin/team", icon: BarChart2, label: "Team Intelligence", testId: "nav-team-intelligence" },
              ...(user?.role === "admin" || user?.role === "manager"
                ? [
                    { path: "/organisation", icon: Building2, label: "Organisation", testId: "nav-organisation" },
                    { path: "/admin/schedules", icon: Calendar, label: "Schedules", testId: "nav-schedules" },
                  ]
                : []),
              ...(user?.role === "admin"
                ? [{ path: "/admin", icon: BookOpen, label: "Standards Library", testId: "nav-standards-library", exact: true }]
                : []),
            ].map(({ path, icon: Icon, label, testId, exact }) => {
              const active = exact ? location.pathname === path : isActive(path);
              return (
                <Link
                  key={path}
                  to={path}
                  onClick={onNavClick}
                  data-testid={testId}
                  className={`flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-colors ${
                    active ? "text-white" : "text-gray-600 hover:bg-gray-100"
                  }`}
                  style={active ? { backgroundColor: orgPrimary } : {}}
                >
                  <Icon className="w-4 h-4 flex-shrink-0" />
                  {!collapsed && <span>{label}</span>}
                </Link>
              );
            })}
          </>
        )}
      </nav>

      {/* User */}
      <div className="p-3 border-t border-gray-200 flex-shrink-0">
        {!collapsed && (
          <div className="mb-2 px-3 py-2 bg-gray-50 rounded-md">
            <p className="text-sm font-medium text-gray-900 truncate">{user?.name}</p>
            <p className="text-xs text-gray-500 capitalize">{user?.role}</p>
          </div>
        )}
        <button
          onClick={handleLogout}
          data-testid="logout-btn"
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-sm text-gray-600 hover:bg-red-50 hover:text-red-600 transition-colors"
        >
          <LogOut className="w-4 h-4 flex-shrink-0" />
          {!collapsed && <span>Sign out</span>}
        </button>
      </div>
    </div>
  );

  return (
    <div className="flex h-screen bg-[#F8F9FA] overflow-hidden">

      {/* ── Mobile backdrop ──────────────────────────────────────────────── */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/30 lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* ── Desktop sidebar ──────────────────────────────────────────────── */}
      <aside
        data-testid="sidebar"
        className={`
          hidden lg:flex flex-col flex-shrink-0 bg-white border-r border-gray-200
          transition-all duration-200
          ${collapsed ? "w-16" : "w-60"}
        `}
      >
        <SidebarContent onNavClick={() => {}} />
      </aside>

      {/* ── Mobile sidebar (slide-over) ───────────────────────────────────── */}
      <aside
        data-testid="sidebar-mobile"
        className={`
          fixed inset-y-0 left-0 z-50 w-72 bg-white shadow-xl
          transform transition-transform duration-200 ease-in-out
          lg:hidden
          ${mobileOpen ? "translate-x-0" : "-translate-x-full"}
        `}
      >
        <SidebarContent onNavClick={() => setMobileOpen(false)} />
      </aside>

      {/* ── Main content ─────────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Mobile top bar */}
        <div className="lg:hidden flex items-center gap-3 px-4 py-3 bg-white border-b border-gray-200 flex-shrink-0">
          <button
            onClick={() => setMobileOpen(true)}
            className="p-1.5 rounded-md hover:bg-gray-100 text-gray-600"
            data-testid="mobile-menu-btn"
          >
            <Menu className="w-5 h-5" />
          </button>
          <Link to="/dashboard" className="flex items-center gap-2">
            <img src="/logo.svg" alt="1two.one" className="w-7 h-7 flex-shrink-0" />
            <span className="font-semibold text-[#1E3A8A] text-base tracking-tight">
              1two.one
            </span>
          </Link>
          {orgLogoUrl && (
            <img
              src={orgLogoUrl}
              alt="Organisation"
              className="ml-auto h-7 w-auto max-w-[100px] object-contain"
              data-testid="org-logo-mobile"
            />
          )}
        </div>

        <main className="flex-1 overflow-y-auto">
          {children}
        </main>
      </div>

    </div>
  );
}



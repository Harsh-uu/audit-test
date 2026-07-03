import React, { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import axios from "axios";
import {
  LayoutDashboard, Mic, LogOut, ChevronLeft, Menu, BookOpen,
  TrendingUp, BarChart2, X, Building2, Calendar, FileUp, LayoutGrid, ClipboardCheck,
  Pencil, Check, Loader, KeyRound, Settings
} from "lucide-react";
import ChangePasswordModal from "./ChangePasswordModal";

export default function Layout({ children }) {
  const { user, logout, getAuthConfig, updateOrgName, API } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [showChangePassword, setShowChangePassword] = useState(false);

  // ── Org name banner state ─────────────────────────────────────────────────
  const [editingOrgName, setEditingOrgName] = useState(false);
  const [orgNameDraft, setOrgNameDraft] = useState("");
  const [savingOrgName, setSavingOrgName] = useState(false);

  const canManage = user?.role === "admin" || user?.role === "manager";

  const saveOrgName = async () => {
    const trimmed = orgNameDraft.trim();
    if (!trimmed || trimmed === user?.org_name) { setEditingOrgName(false); return; }
    setSavingOrgName(true);
    try {
      await axios.patch(`${API}/org/name`, { name: trimmed }, getAuthConfig());
      updateOrgName(trimmed);
      setEditingOrgName(false);
    } catch {
      // silent — org page still shows flash messages for its own saves
    }
    setSavingOrgName(false);
  };

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
        {showChangePassword && <ChangePasswordModal onClose={() => setShowChangePassword(false)} />}
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
              onClick={() => setShowChangePassword(true)}
              data-testid="super-admin-change-password-btn"
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-sm text-blue-200 hover:bg-white/10 hover:text-white transition-colors"
            >
              <KeyRound className="w-4 h-4 flex-shrink-0" />
              <span>Change password</span>
            </button>
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
              ...(user?.role === "admin" || user?.role === "manager"
                ? [
                    { path: "/organisation", icon: Building2, label: "Organisation", testId: "nav-organisation" },
                    { path: "/admin/schedules", icon: Calendar, label: "Schedules", testId: "nav-schedules" },
                  ]
                : []),
              ...(user?.role === "admin" || user?.role === "manager"
                ? [{ path: "/admin", icon: BookOpen, label: "Standards Library", testId: "nav-standards-library", exact: true },
                   { path: "/upload-supervision", icon: FileUp, label: "Import Supervision", testId: "nav-import-supervision", exact: true },
                   { path: "/supervision-matrix", icon: LayoutGrid, label: "Supervision Matrix", testId: "nav-supervision-matrix", exact: true },
                   { path: "/admin/team", icon: BarChart2, label: "Team Intelligence", testId: "nav-team-intelligence", exact: true },
                   { path: "/inspection-prep", icon: ClipboardCheck, label: "Inspection Prep", testId: "nav-inspection-prep", exact: true },
                   { path: "/settings", icon: Settings, label: "Settings", testId: "nav-settings", exact: true }]
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
          onClick={() => setShowChangePassword(true)}
          data-testid="change-password-btn"
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-sm text-gray-600 hover:bg-gray-100 transition-colors"
        >
          <KeyRound className="w-4 h-4 flex-shrink-0" />
          {!collapsed && <span>Change password</span>}
        </button>
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

      {/* ── Change Password modal ─────────────────────────────────────────── */}
      {showChangePassword && <ChangePasswordModal onClose={() => setShowChangePassword(false)} />}

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

        {/* ── Org name banner (all pages) ─────────────────────────────────── */}
        <div className="bg-[#1E3A8A] px-6 py-2.5 flex items-center gap-3 flex-shrink-0" data-testid="org-name-bar">
          <Building2 className="w-4 h-4 text-white/60 flex-shrink-0" />
          {editingOrgName ? (
            <>
              <input
                autoFocus
                value={orgNameDraft}
                onChange={e => setOrgNameDraft(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") saveOrgName(); if (e.key === "Escape") setEditingOrgName(false); }}
                className="bg-white/10 border border-white/40 rounded px-2.5 py-0.5 text-white text-sm font-semibold focus:outline-none focus:bg-white/20 min-w-0 w-48"
                data-testid="org-name-input"
              />
              <button
                onClick={saveOrgName}
                disabled={savingOrgName}
                className="p-1 rounded bg-white/10 hover:bg-white/20 text-white disabled:opacity-50"
                data-testid="org-name-save"
              >
                {savingOrgName ? <Loader className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
              </button>
              <button
                onClick={() => setEditingOrgName(false)}
                className="p-1 rounded hover:bg-white/10 text-white/70 hover:text-white"
                data-testid="org-name-cancel"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </>
          ) : (
            <>
              <span className="text-sm font-semibold text-white">{user?.org_name || "Organisation"}</span>
              {canManage && (
                <button
                  onClick={() => { setEditingOrgName(true); setOrgNameDraft(user?.org_name || ""); }}
                  className="p-1 rounded hover:bg-white/10 text-white/50 hover:text-white transition-colors"
                  data-testid="org-name-edit"
                  title="Rename organisation"
                >
                  <Pencil className="w-3.5 h-3.5" />
                </button>
              )}
            </>
          )}
        </div>

        <main className="flex-1 overflow-y-auto">
          {children}
        </main>
      </div>

    </div>
  );
}



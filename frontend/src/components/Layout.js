import React, { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import {
  LayoutDashboard, Mic, LogOut, ChevronLeft, Menu, BookOpen,
  TrendingUp, Download, BarChart2, X, Building2
} from "lucide-react";

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const isActive = (path) =>
    location.pathname === path || location.pathname.startsWith(path + "/");

  const navItems = [
    { path: "/dashboard",                 icon: LayoutDashboard, label: "Dashboard"    },
    { path: "/meetings/new",              icon: Mic,             label: "New Meeting"  },
    { path: `/portfolio/${user?.id}`,     icon: TrendingUp,      label: "My Portfolio", matchBase: "/portfolio" },
  ];

  const SidebarContent = ({ onNavClick }) => (
    <div className="flex flex-col h-full">
      {/* Logo */}
      <div className="flex items-center justify-between p-4 border-b border-gray-200 h-16 flex-shrink-0">
        {!collapsed && (
          <Link to="/dashboard" onClick={onNavClick} className="flex items-center gap-2">
            <img src="/logo.svg" alt="1two.one" className="w-8 h-8 flex-shrink-0" />
            <span className="font-semibold text-[#1E3A8A] text-lg tracking-tight">
              1two.one
            </span>
          </Link>
        )}
        {collapsed && <img src="/logo.svg" alt="1two.one" className="w-7 h-7 mx-auto" />}
        <button
          onClick={() => { setCollapsed(!collapsed); }}
          className="p-1 rounded hover:bg-gray-100 text-gray-500 hidden lg:block"
          data-testid="sidebar-toggle"
        >
          {collapsed ? <Menu className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
        {/* Mobile close button */}
        <button
          onClick={() => setMobileOpen(false)}
          className="p-1 rounded hover:bg-gray-100 text-gray-500 lg:hidden"
          data-testid="sidebar-mobile-close"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
        {navItems.map(({ path, icon: Icon, label, matchBase }) => (
          <Link
            key={path}
            to={path}
            onClick={onNavClick}
            data-testid={`nav-${label.toLowerCase().replace(/\s/g, "-")}`}
            className={`flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-colors ${
              isActive(matchBase || path)
                ? "bg-[#1E3A8A] text-white"
                : "text-gray-600 hover:bg-gray-100"
            }`}
          >
            <Icon className="w-4 h-4 flex-shrink-0" />
            {!collapsed && <span>{label}</span>}
          </Link>
        ))}

        {(user?.role === "admin" || user?.role === "manager") && (
          <>
            {!collapsed && (
              <div className="pt-3 pb-1 px-3 text-xs font-semibold uppercase text-gray-400 tracking-wider">Admin</div>
            )}
            <Link
              to="/admin/team"
              onClick={onNavClick}
              data-testid="nav-team-intelligence"
              className={`flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-colors ${
                isActive("/admin/team") ? "bg-[#1E3A8A] text-white" : "text-gray-600 hover:bg-gray-100"
              }`}
            >
              <BarChart2 className="w-4 h-4 flex-shrink-0" />
              {!collapsed && <span>Team Intelligence</span>}
            </Link>
            {(user?.role === "admin" || user?.role === "manager") && (
              <Link
                to="/organisation"
                onClick={onNavClick}
                data-testid="nav-organisation"
                className={`flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-colors ${
                  isActive("/organisation") ? "bg-[#1E3A8A] text-white" : "text-gray-600 hover:bg-gray-100"
                }`}
              >
                <Building2 className="w-4 h-4 flex-shrink-0" />
                {!collapsed && <span>Organisation</span>}
              </Link>
            )}
            {user?.role === "admin" && (
              <>
                <Link
                  to="/admin"
                  onClick={onNavClick}
                  data-testid="nav-standards-library"
                  className={`flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-colors ${
                    location.pathname === "/admin" ? "bg-[#1E3A8A] text-white" : "text-gray-600 hover:bg-gray-100"
                  }`}
                >
                  <BookOpen className="w-4 h-4 flex-shrink-0" />
                  {!collapsed && <span>Standards Library</span>}
                </Link>
              </>
            )}
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
        </div>

        <main className="flex-1 overflow-y-auto">
          {children}
        </main>
      </div>

    </div>
  );
}



import React, { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import {
  LayoutDashboard, Mic, FileText, Settings, LogOut, Shield, ChevronLeft, Menu, BookOpen, Users, TrendingUp, Download, BarChart2
} from "lucide-react";

export default function Layout({ children }) {
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const isActive = (path) => location.pathname === path || location.pathname.startsWith(path + "/");

  const navItems = [
    { path: "/dashboard", icon: LayoutDashboard, label: "Dashboard" },
    { path: "/meetings/new", icon: Mic, label: "New Meeting" },
    { path: `/portfolio/${user?.id}`, icon: TrendingUp, label: "My Portfolio", matchBase: "/portfolio" },
  ];

  const adminItems = [
    { path: "/admin", icon: BookOpen, label: "Standards Library" },
    { path: "/admin/team", icon: BarChart2, label: "Team Intelligence" },
  ];

  return (
    <div className="flex h-screen bg-[#F8F9FA] overflow-hidden">
      {/* Sidebar */}
      <aside
        data-testid="sidebar"
        className={`${collapsed ? "w-16" : "w-60"} flex-shrink-0 bg-white border-r border-gray-200 flex flex-col transition-all duration-200`}
      >
        {/* Logo */}
        <div className="flex items-center justify-between p-4 border-b border-gray-200 h-16">
          {!collapsed && (
            <Link to="/dashboard" className="flex items-center gap-2">
              <Shield className="w-6 h-6 text-[#1E3A8A]" />
              <span className="font-semibold text-[#1E3A8A] text-lg tracking-tight" style={{fontFamily:'Work Sans,sans-serif'}}>
                Supervision
              </span>
            </Link>
          )}
          {collapsed && <Shield className="w-6 h-6 text-[#1E3A8A] mx-auto" />}
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="p-1 rounded hover:bg-gray-100 text-gray-500"
            data-testid="sidebar-toggle"
          >
            {collapsed ? <Menu className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          {navItems.map(({ path, icon: Icon, label, matchBase }) => (
            <Link
              key={path}
              to={path}
              data-testid={`nav-${label.toLowerCase().replace(/\s/g, '-')}`}
              className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
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
              {!collapsed && <div className="pt-3 pb-1 px-3 text-xs font-semibold uppercase text-gray-400 tracking-wider">Admin</div>}
              {/* Team Intelligence visible to both admin and manager */}
              <Link
                to="/admin/team"
                data-testid="nav-team-intelligence"
                className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  isActive("/admin/team") ? "bg-[#1E3A8A] text-white" : "text-gray-600 hover:bg-gray-100"
                }`}
              >
                <BarChart2 className="w-4 h-4 flex-shrink-0" />
                {!collapsed && <span>Team Intelligence</span>}
              </Link>
              {user?.role === "admin" && (
                <>
                  <Link
                    to="/admin"
                    data-testid="nav-standards-library"
                    className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                      location.pathname === "/admin" ? "bg-[#1E3A8A] text-white" : "text-gray-600 hover:bg-gray-100"
                    }`}
                  >
                    <BookOpen className="w-4 h-4 flex-shrink-0" />
                    {!collapsed && <span>Standards Library</span>}
                  </Link>
                  <Link
                    to="/admin"
                    data-testid="nav-evidence-export"
                    onClick={() => setTimeout(() => document.querySelector('[data-tab="export"]')?.click(), 100)}
                    className="flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors text-gray-600 hover:bg-gray-100"
                  >
                    <Download className="w-4 h-4 flex-shrink-0" />
                    {!collapsed && <span>Evidence Export</span>}
                  </Link>
                </>
              )}
            </>
          )}
        </nav>

        {/* User */}
        <div className="p-3 border-t border-gray-200">
          {!collapsed && (
            <div className="mb-2 px-3 py-2 bg-gray-50 rounded-md">
              <p className="text-sm font-medium text-gray-900 truncate">{user?.name}</p>
              <p className="text-xs text-gray-500 capitalize">{user?.role}</p>
            </div>
          )}
          <button
            onClick={handleLogout}
            data-testid="logout-btn"
            className="w-full flex items-center gap-3 px-3 py-2 rounded-md text-sm text-gray-600 hover:bg-red-50 hover:text-red-600 transition-colors"
          >
            <LogOut className="w-4 h-4 flex-shrink-0" />
            {!collapsed && <span>Sign out</span>}
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        {children}
      </main>
    </div>
  );
}

import React from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import Layout from "@/components/Layout";
import { Calendar, LayoutGrid, Users, BarChart2, BookOpen, Settings, TrendingUp, Plus, ChevronRight } from "lucide-react";

const TILES = {
  meetings:  { key: "meetings",  title: "Meetings",     route: "/meetings",         icon: Calendar,    accent: "blue",    description: "Start, record and review supervision meetings." },
  matrix:    { key: "matrix",    title: "Matrix",       route: "/supervision-matrix", icon: LayoutGrid, accent: "indigo",  description: "Organisation-wide supervision compliance grid." },
  people:    { key: "people",    title: "People",       route: "/organisation",     icon: Users,       accent: "emerald", description: "Care settings, teams and staff structure." },
  evidence:  { key: "evidence",  title: "Evidence",     route: "/admin/team",       icon: BarChart2,   accent: "purple",  description: "AI evidence trends and team themes." },
  resources: { key: "resources", title: "Resources",    route: "/resources",        icon: BookOpen,    accent: "amber",   description: "Downloads and supervision courses." },
  settings:  { key: "settings",  title: "Settings",     route: "/settings",         icon: Settings,    accent: "slate",   description: "Organisation configuration." },
  portfolio: { key: "portfolio", title: "My Portfolio", route: "",                  icon: TrendingUp,  accent: "teal",    description: "Your supervision history and evidence." },
};

const ACCENTS = {
  blue:    { iconBg: "bg-blue-100",    iconText: "text-blue-600",    hoverBorder: "hover:border-blue-400" },
  indigo:  { iconBg: "bg-indigo-100",  iconText: "text-indigo-600",  hoverBorder: "hover:border-indigo-400" },
  emerald: { iconBg: "bg-emerald-100", iconText: "text-emerald-600", hoverBorder: "hover:border-emerald-400" },
  purple:  { iconBg: "bg-purple-100",  iconText: "text-purple-600",  hoverBorder: "hover:border-purple-400" },
  amber:   { iconBg: "bg-amber-100",   iconText: "text-amber-600",   hoverBorder: "hover:border-amber-400" },
  slate:   { iconBg: "bg-slate-100",   iconText: "text-slate-600",   hoverBorder: "hover:border-slate-400" },
  teal:    { iconBg: "bg-teal-100",    iconText: "text-teal-600",    hoverBorder: "hover:border-teal-400" },
};

export default function Dashboard() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const canManage = user?.role === "admin" || user?.role === "manager";

  const tileKeys = canManage
    ? ["meetings", "matrix", "people", "evidence", "resources", "settings"]
    : ["meetings", "resources", "portfolio"];

  const tiles = tileKeys.map(k => {
    const t = TILES[k];
    return k === "portfolio" ? { ...t, route: `/portfolio/${user?.id}` } : t;
  });

  return (
    <Layout>
      {/* Zero data-fetch: everything below is derived synchronously from the
          already-loaded auth user, so this page paints instantly on mount. */}
      <div className="p-6 md:p-10 fade-in max-w-6xl mx-auto">
        <div className="mb-8">
          <h1 className="text-2xl sm:text-3xl font-semibold text-gray-900" data-testid="dashboard-welcome-heading">
            Welcome back{user?.name ? `, ${user.name.split(" ")[0]}` : ""}
          </h1>
          <p className="text-sm text-gray-500 mt-1">Jump straight to what you need.</p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5" data-testid="dashboard-tile-grid">
          {tiles.map(tile => {
            const Icon = tile.icon;
            const accent = ACCENTS[tile.accent];
            return (
              <Link
                key={tile.key}
                to={tile.route}
                data-testid={`tile-${tile.key}`}
                className={`group relative bg-white border border-gray-200 rounded-2xl p-6 shadow-sm hover:shadow-lg hover:-translate-y-1 transition-all duration-200 ${accent.hoverBorder}`}
              >
                <div className="flex items-start justify-between">
                  <div className={`w-12 h-12 rounded-xl ${accent.iconBg} flex items-center justify-center`}>
                    <Icon className={`w-6 h-6 ${accent.iconText}`} />
                  </div>
                  {tile.key === "meetings" && (
                    <button
                      onClick={e => { e.preventDefault(); e.stopPropagation(); navigate("/meetings/new"); }}
                      data-testid="tile-meetings-quick-add"
                      title="New Meeting"
                      className="w-8 h-8 rounded-full bg-[#1E3A8A] text-white flex items-center justify-center hover:bg-[#1E40AF] transition-colors"
                    >
                      <Plus className="w-4 h-4" />
                    </button>
                  )}
                </div>
                <h3 className="text-lg font-semibold text-gray-900 mt-4">{tile.title}</h3>
                <p className="text-sm text-gray-500 mt-1 leading-relaxed">{tile.description}</p>
                <div className="flex items-center gap-1 text-xs font-medium text-gray-400 mt-4 group-hover:text-[#1E3A8A] transition-colors">
                  Open <ChevronRight className="w-3.5 h-3.5" />
                </div>
              </Link>
            );
          })}
        </div>
      </div>
    </Layout>
  );
}

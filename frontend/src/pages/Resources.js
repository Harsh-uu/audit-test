import React, { useEffect, useState } from "react";
import Layout from "@/components/Layout";
import { Link } from "react-router-dom";
import { BookOpen, Download, GraduationCap, Sparkles, ExternalLink, Loader2, ArrowRight } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { cachedGet } from "@/utils/apiCache";

const API = process.env.REACT_APP_BACKEND_URL + "/api";

export default function Resources() {
  const { user } = useAuth();
  const [data, setData] = useState({ downloads: [], courses: [] });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    cachedGet(`${API}/resources/`)
      .then(res => setData(res.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  // Auth state is still resolving — avoid flashing the anonymous sidebar
  // for a split second before we know whether there's a real session.
  if (user === undefined) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <Loader2 className="w-8 h-8 animate-spin text-[#1E3A8A]" />
      </div>
    );
  }

  return (
    <Layout>
      <div className="p-6 md:p-10 fade-in max-w-4xl mx-auto">
        {!user && (
          <div
            className="mb-8 rounded-2xl bg-[#1E3A8A] px-6 py-5 flex flex-col sm:flex-row sm:items-center gap-4 justify-between"
            data-testid="public-resources-cta"
          >
            <div>
              <p className="text-white font-semibold text-sm sm:text-base">This is a free resource from 1two.one</p>
              <p className="text-blue-200 text-xs sm:text-sm mt-0.5">Sign in to run supervision meetings with built-in evidence tracking.</p>
            </div>
            <Link
              to="/login"
              data-testid="public-resources-cta-signin"
              className="flex items-center justify-center gap-1.5 px-4 py-2 bg-white text-[#1E3A8A] rounded-lg text-sm font-semibold hover:bg-blue-50 transition-colors flex-shrink-0"
            >
              Sign In <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>
        )}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-xl bg-amber-100 flex items-center justify-center flex-shrink-0">
              <BookOpen className="w-5 h-5 text-amber-600" />
            </div>
            <h1 className="text-2xl sm:text-3xl font-semibold text-gray-900">Resources</h1>
          </div>
          <p className="text-sm text-gray-500">Downloads, templates and supervision training.</p>
        </div>

        <div className="mb-8" data-testid="resources-downloads-section">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center flex-shrink-0">
              <Download className="w-4 h-4 text-blue-600" />
            </div>
            <h2 className="text-base md:text-lg font-semibold text-gray-900">Useful Downloads</h2>
          </div>
          {loading ? (
            <div className="bg-white border border-gray-200 rounded-2xl p-6 animate-pulse h-28" />
          ) : data.downloads.length > 0 ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
              {data.downloads.map(r => (
                <a
                  key={r.id}
                  href={r.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group bg-white border border-gray-200 rounded-2xl p-6 shadow-sm hover:shadow-md hover:border-blue-300 hover:-translate-y-0.5 transition-all duration-150"
                  data-testid={`resource-download-${r.id}`}
                >
                  <div className="flex items-center justify-between">
                    <div className="w-10 h-10 rounded-xl bg-blue-100 flex items-center justify-center mb-4">
                      <Download className="w-5 h-5 text-blue-600" />
                    </div>
                    <ExternalLink className="w-4 h-4 text-gray-300 group-hover:text-blue-500 transition-colors" />
                  </div>
                  <h3 className="text-base font-semibold text-gray-900">{r.title}</h3>
                  {r.description && (
                    <p className="text-sm text-gray-500 mt-1.5 leading-relaxed">{r.description}</p>
                  )}
                  {r.source_label && (
                    <span className="inline-flex items-center gap-1.5 mt-4 text-xs font-medium bg-blue-50 text-blue-700 px-2.5 py-1 rounded-full">
                      Source: {r.source_label}
                    </span>
                  )}
                </a>
              ))}
            </div>
          ) : (
            <div className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm" data-testid="resources-downloads-card">
              <p className="text-sm text-gray-500 leading-relaxed">
                Supervision templates, checklists and framework guides you'll be able to download and use straight away.
              </p>
              <span className="inline-flex items-center gap-1.5 mt-4 text-xs font-medium bg-amber-100 text-amber-800 px-2.5 py-1 rounded-full">
                <Sparkles className="w-3 h-3" /> Coming soon
              </span>
            </div>
          )}
        </div>

        <div data-testid="resources-course-section">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-8 h-8 rounded-lg bg-emerald-100 flex items-center justify-center flex-shrink-0">
              <GraduationCap className="w-4 h-4 text-emerald-600" />
            </div>
            <h2 className="text-base md:text-lg font-semibold text-gray-900">Supervision Course</h2>
          </div>
          {!loading && data.courses.length > 0 ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
              {data.courses.map(r => (
                <a
                  key={r.id}
                  href={r.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group bg-white border border-gray-200 rounded-2xl p-6 shadow-sm hover:shadow-md hover:border-emerald-300 hover:-translate-y-0.5 transition-all duration-150"
                  data-testid={`resource-course-${r.id}`}
                >
                  <div className="flex items-center justify-between">
                    <div className="w-10 h-10 rounded-xl bg-emerald-100 flex items-center justify-center mb-4">
                      <GraduationCap className="w-5 h-5 text-emerald-600" />
                    </div>
                    <ExternalLink className="w-4 h-4 text-gray-300 group-hover:text-emerald-500 transition-colors" />
                  </div>
                  <h3 className="text-base font-semibold text-gray-900">{r.title}</h3>
                  {r.description && (
                    <p className="text-sm text-gray-500 mt-1.5 leading-relaxed">{r.description}</p>
                  )}
                </a>
              ))}
            </div>
          ) : (
            <div className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm" data-testid="resources-courses-card">
              <p className="text-sm text-gray-500 leading-relaxed">
                A short course on running effective, compliant supervision meetings for managers and supervisors.
              </p>
              <span className="inline-flex items-center gap-1.5 mt-4 text-xs font-medium bg-amber-100 text-amber-800 px-2.5 py-1 rounded-full">
                <Sparkles className="w-3 h-3" /> Coming soon
              </span>
            </div>
          )}
        </div>
      </div>
    </Layout>
  );
}


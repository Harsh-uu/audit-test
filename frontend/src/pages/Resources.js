import React from "react";
import Layout from "@/components/Layout";
import { BookOpen, Download, GraduationCap, Sparkles } from "lucide-react";

export default function Resources() {
  return (
    <Layout>
      <div className="p-6 md:p-10 fade-in max-w-4xl mx-auto">
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-xl bg-amber-100 flex items-center justify-center flex-shrink-0">
              <BookOpen className="w-5 h-5 text-amber-600" />
            </div>
            <h1 className="text-2xl sm:text-3xl font-semibold text-gray-900">Resources</h1>
          </div>
          <p className="text-sm text-gray-500">Downloads, templates and supervision training — coming soon.</p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
          <div className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm" data-testid="resources-downloads-card">
            <div className="w-10 h-10 rounded-xl bg-blue-100 flex items-center justify-center mb-4">
              <Download className="w-5 h-5 text-blue-600" />
            </div>
            <h3 className="text-lg font-semibold text-gray-900">Useful Downloads</h3>
            <p className="text-sm text-gray-500 mt-1.5 leading-relaxed">
              Supervision templates, checklists and framework guides you'll be able to download and use straight away.
            </p>
            <span className="inline-flex items-center gap-1.5 mt-4 text-xs font-medium bg-amber-100 text-amber-800 px-2.5 py-1 rounded-full">
              <Sparkles className="w-3 h-3" /> Coming soon
            </span>
          </div>

          <div className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm" data-testid="resources-courses-card">
            <div className="w-10 h-10 rounded-xl bg-emerald-100 flex items-center justify-center mb-4">
              <GraduationCap className="w-5 h-5 text-emerald-600" />
            </div>
            <h3 className="text-lg font-semibold text-gray-900">Supervision Course</h3>
            <p className="text-sm text-gray-500 mt-1.5 leading-relaxed">
              A short course on running effective, compliant supervision meetings for managers and supervisors.
            </p>
            <span className="inline-flex items-center gap-1.5 mt-4 text-xs font-medium bg-amber-100 text-amber-800 px-2.5 py-1 rounded-full">
              <Sparkles className="w-3 h-3" /> Coming soon
            </span>
          </div>
        </div>
      </div>
    </Layout>
  );
}

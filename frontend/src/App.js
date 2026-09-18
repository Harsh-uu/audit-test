import React, { lazy, Suspense, useEffect } from "react";
import { Loader2 } from "lucide-react";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AuthProvider } from "@/context/AuthContext";
import { useAuth } from "@/context/AuthContext";
import ProtectedRoute from "@/components/ProtectedRoute";
import { Toaster } from "@/components/ui/sonner";
import { RouteErrorBoundary } from "@/components/RouteErrorBoundary";
import { EulaGate } from "@/components/EulaGate";
import { TooltipProvider } from "@/components/ui/tooltip";

// Auth/public pages — loaded eagerly so login is instant
import Login from "@/pages/Login";
import ResetPassword from "@/pages/ResetPassword";
import SetPassword from "@/pages/SetPassword";
import AcceptInvite from "@/pages/AcceptInvite";

// All app pages — lazy-loaded per route (separate JS chunks)
const Dashboard         = lazy(() => import("@/pages/Dashboard"));
const Meetings          = lazy(() => import("@/pages/Meetings"));
const Resources         = lazy(() => import("@/pages/Resources"));
const NewMeeting        = lazy(() => import("@/pages/NewMeeting"));
const RecordingScreen   = lazy(() => import("@/pages/RecordingScreen"));
const MeetingReport     = lazy(() => import("@/pages/MeetingReport"));
const MeetingPrep       = lazy(() => import("@/pages/MeetingPrep"));
const AdminLibrary      = lazy(() => import("@/pages/AdminLibrary"));
const UploadSupervision = lazy(() => import("@/pages/UploadSupervision"));
const DocUploadReport   = lazy(() => import("@/pages/DocUploadReport"));
const SupervisionMatrix = lazy(() => import("@/pages/SupervisionMatrix"));
const InspectionPrep    = lazy(() => import("@/pages/InspectionPrep"));
const StaffPortfolio    = lazy(() => import("@/pages/StaffPortfolio"));
const TeamInsights      = lazy(() => import("@/pages/TeamInsights"));
const OrgStructure      = lazy(() => import("@/pages/OrgStructure"));
const PeopleHub         = lazy(() => import("@/pages/PeopleHub"));
const Schedules         = lazy(() => import("@/pages/Schedules"));
const CareCertPrep      = lazy(() => import("@/pages/CareCertPrep"));
const OrgSettings       = lazy(() => import("@/pages/OrgSettings"));
const SuperAdminDashboard = lazy(() => import("@/pages/SuperAdminDashboard"));
const SuperAdminOrgDetail = lazy(() => import("@/pages/SuperAdminOrgDetail"));

import "@/App.css";

function PageLoader() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <Loader2 className="w-8 h-8 animate-spin text-[#1E3A8A]" />
    </div>
  );
}

function RootRedirect() {
  const { user } = useAuth();
  if (user?.role === "super_admin") return <Navigate to="/super-admin" replace />;
  return <Navigate to="/dashboard" replace />;
}

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    document.getElementById("app-scroll-container")?.scrollTo(0, 0);
    document.getElementById("report-scroll-container")?.scrollTo(0, 0);
    window.scrollTo(0, 0);
  }, [pathname]);
  return null;
}

function App() {
  return (
    <AuthProvider>
      <TooltipProvider delayDuration={300}>
      <BrowserRouter>
        <RouteErrorBoundary>
        <ScrollToTop />
        <EulaGate />
        <Suspense fallback={<PageLoader />}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route path="/accept-invite" element={<AcceptInvite />} />
          <Route path="/set-password" element={<SetPassword />} />
          <Route path="/" element={<ProtectedRoute><RootRedirect /></ProtectedRoute>} />
          <Route path="/super-admin" element={<ProtectedRoute roles={["super_admin"]}><SuperAdminDashboard /></ProtectedRoute>} />
          <Route path="/super-admin/orgs/:orgId" element={<ProtectedRoute roles={["super_admin"]}><SuperAdminOrgDetail /></ProtectedRoute>} />
          <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
          <Route path="/meetings" element={<ProtectedRoute><Meetings /></ProtectedRoute>} />
          <Route path="/resources" element={<ProtectedRoute><Resources /></ProtectedRoute>} />
          <Route path="/meetings/new" element={<ProtectedRoute><NewMeeting /></ProtectedRoute>} />
          <Route path="/meetings/:meetingId/record" element={<ProtectedRoute><RecordingScreen /></ProtectedRoute>} />
          <Route path="/meetings/:meetingId/prepare" element={<ProtectedRoute roles={["admin","manager"]}><MeetingPrep /></ProtectedRoute>} />
          <Route path="/meetings/:meetingId/report" element={<ProtectedRoute><MeetingReport /></ProtectedRoute>} />
          <Route path="/admin" element={<ProtectedRoute roles={["admin", "manager"]}><AdminLibrary /></ProtectedRoute>} />
          <Route path="/upload-supervision" element={<ProtectedRoute roles={["admin", "manager"]}><UploadSupervision /></ProtectedRoute>} />
          <Route path="/doc-uploads/:uploadId" element={<ProtectedRoute roles={["admin", "manager"]}><DocUploadReport /></ProtectedRoute>} />
          <Route path="/supervision-matrix" element={<ProtectedRoute roles={["admin", "manager"]}><SupervisionMatrix /></ProtectedRoute>} />
          <Route path="/inspection-prep" element={<ProtectedRoute roles={["admin", "manager"]}><InspectionPrep /></ProtectedRoute>} />
          <Route path="/care-cert" element={<ProtectedRoute roles={["admin", "manager"]}><CareCertPrep /></ProtectedRoute>} />
          <Route path="/settings" element={<ProtectedRoute roles={["admin", "manager"]}><OrgSettings /></ProtectedRoute>} />
          <Route path="/admin/team" element={<ProtectedRoute roles={["admin", "manager"]}><TeamInsights /></ProtectedRoute>} />
          <Route path="/organisation" element={<ProtectedRoute roles={["admin", "manager"]}><PeopleHub /></ProtectedRoute>} />
          <Route path="/admin/schedules" element={<ProtectedRoute roles={["admin", "manager"]}><Schedules /></ProtectedRoute>} />
          <Route path="/portfolio" element={<ProtectedRoute><StaffPortfolio /></ProtectedRoute>} />
          <Route path="/portfolio/:userId" element={<ProtectedRoute><StaffPortfolio /></ProtectedRoute>} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
        </Suspense>
        </RouteErrorBoundary>
      </BrowserRouter>
      </TooltipProvider>
      <Toaster richColors position="top-right" />
    </AuthProvider>
  );
}

export default App;

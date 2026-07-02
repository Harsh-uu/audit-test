import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "@/context/AuthContext";
import { useAuth } from "@/context/AuthContext";
import ProtectedRoute from "@/components/ProtectedRoute";
import { Toaster } from "@/components/ui/sonner";
import Login from "@/pages/Login";
import ResetPassword from "@/pages/ResetPassword";
import Dashboard from "@/pages/Dashboard";
import NewMeeting from "@/pages/NewMeeting";
import RecordingScreen from "@/pages/RecordingScreen";
import MeetingReport from "@/pages/MeetingReport";
import AdminLibrary from "@/pages/AdminLibrary";
import UploadSupervision from "@/pages/UploadSupervision";
import DocUploadReport from "@/pages/DocUploadReport";
import StaffPortfolio from "@/pages/StaffPortfolio";
import TeamInsights from "@/pages/TeamInsights";
import OrgStructure from "@/pages/OrgStructure";
import Schedules from "@/pages/Schedules";
import SuperAdminDashboard from "@/pages/SuperAdminDashboard";
import AcceptInvite from "@/pages/AcceptInvite";
import "@/App.css";

function RootRedirect() {
  const { user } = useAuth();
  if (user?.role === "super_admin") return <Navigate to="/super-admin" replace />;
  return <Navigate to="/dashboard" replace />;
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route path="/accept-invite" element={<AcceptInvite />} />
          <Route path="/" element={<ProtectedRoute><RootRedirect /></ProtectedRoute>} />
          <Route path="/super-admin" element={<ProtectedRoute roles={["super_admin"]}><SuperAdminDashboard /></ProtectedRoute>} />
          <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
          <Route path="/meetings/new" element={<ProtectedRoute><NewMeeting /></ProtectedRoute>} />
          <Route path="/meetings/:meetingId/record" element={<ProtectedRoute><RecordingScreen /></ProtectedRoute>} />
          <Route path="/meetings/:meetingId/report" element={<ProtectedRoute><MeetingReport /></ProtectedRoute>} />
          <Route path="/admin" element={<ProtectedRoute roles={["admin", "manager"]}><AdminLibrary /></ProtectedRoute>} />
          <Route path="/upload-supervision" element={<ProtectedRoute roles={["admin", "manager"]}><UploadSupervision /></ProtectedRoute>} />
          <Route path="/doc-uploads/:uploadId" element={<ProtectedRoute roles={["admin", "manager"]}><DocUploadReport /></ProtectedRoute>} />
          <Route path="/admin/team" element={<ProtectedRoute roles={["admin", "manager"]}><TeamInsights /></ProtectedRoute>} />
          <Route path="/organisation" element={<ProtectedRoute roles={["admin", "manager"]}><OrgStructure /></ProtectedRoute>} />
          <Route path="/admin/schedules" element={<ProtectedRoute roles={["admin", "manager"]}><Schedules /></ProtectedRoute>} />
          <Route path="/portfolio" element={<ProtectedRoute><StaffPortfolio /></ProtectedRoute>} />
          <Route path="/portfolio/:userId" element={<ProtectedRoute><StaffPortfolio /></ProtectedRoute>} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </BrowserRouter>
      <Toaster richColors position="top-right" />
    </AuthProvider>
  );
}

export default App;

import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "@/context/AuthContext";
import ProtectedRoute from "@/components/ProtectedRoute";
import Login from "@/pages/Login";
import ResetPassword from "@/pages/ResetPassword";
import Dashboard from "@/pages/Dashboard";
import NewMeeting from "@/pages/NewMeeting";
import RecordingScreen from "@/pages/RecordingScreen";
import MeetingReport from "@/pages/MeetingReport";
import AdminLibrary from "@/pages/AdminLibrary";
import StaffPortfolio from "@/pages/StaffPortfolio";
import TeamInsights from "@/pages/TeamInsights";
import OrgStructure from "@/pages/OrgStructure";
import "@/App.css";

const ADMIN_ONLY = ["admin"];
const ADMIN_MANAGER = ["admin", "manager"];

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route path="/" element={<ProtectedRoute><Navigate to="/dashboard" replace /></ProtectedRoute>} />
          <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
          <Route path="/meetings/new" element={<ProtectedRoute><NewMeeting /></ProtectedRoute>} />
          <Route path="/meetings/:meetingId/record" element={<ProtectedRoute><RecordingScreen /></ProtectedRoute>} />
          <Route path="/meetings/:meetingId/report" element={<ProtectedRoute><MeetingReport /></ProtectedRoute>} />
          <Route path="/admin" element={<ProtectedRoute roles={["admin"]}><AdminLibrary /></ProtectedRoute>} />
          <Route path="/admin/team" element={<ProtectedRoute roles={["admin", "manager"]}><TeamInsights /></ProtectedRoute>} />
          <Route path="/organisation" element={<ProtectedRoute roles={["admin", "manager"]}><OrgStructure /></ProtectedRoute>} />
          <Route path="/portfolio" element={<ProtectedRoute><StaffPortfolio /></ProtectedRoute>} />
          <Route path="/portfolio/:userId" element={<ProtectedRoute><StaffPortfolio /></ProtectedRoute>} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;

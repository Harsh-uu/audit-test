import React from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

export default function ProtectedRoute({ children, roles }) {
  const { user } = useAuth();
  const location = useLocation();

  if (user === undefined) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#F8F9FA]">
        <div className="flex items-center gap-3 text-[#64748B]">
          <div className="w-5 h-5 border-2 border-[#1E3A8A] border-t-transparent rounded-full spin"></div>
          <span className="text-sm font-medium">Loading Supervision...</span>
        </div>
      </div>
    );
  }

  if (!user) return <Navigate to="/login" replace />;

  // Force password change before accessing anything else
  if (user.must_change_password && location.pathname !== "/set-password") {
    return <Navigate to="/set-password" replace />;
  }

  if (roles && !roles.includes(user.role)) {
    return <Navigate to="/dashboard" replace />;
  }

  return children;
}

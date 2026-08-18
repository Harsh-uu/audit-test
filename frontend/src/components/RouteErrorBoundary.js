import React from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

/**
 * Catches render errors inside lazy-loaded route components.
 * In production, React swallows uncaught render errors silently (blank page).
 * This boundary shows a user-friendly message and a one-click reload instead.
 */
export class RouteErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    // Log to console so it's visible in DevTools even in production
    console.error("[RouteErrorBoundary] Render error:", error, info?.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="min-h-screen flex items-center justify-center p-6 bg-gray-50">
          <div className="max-w-md w-full text-center space-y-4">
            <div className="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center mx-auto">
              <AlertTriangle className="w-6 h-6 text-red-600" />
            </div>
            <h2 className="text-lg font-semibold text-gray-900 font-display">Something went wrong</h2>
            <p className="text-sm text-gray-500">
              This page ran into an unexpected error. Refreshing usually fixes it.
            </p>
            {process.env.NODE_ENV !== "production" && (
              <pre className="text-left text-xs bg-gray-100 rounded-lg p-3 overflow-auto max-h-40 text-red-700">
                {this.state.error?.message}
              </pre>
            )}
            <button
              onClick={() => window.location.reload()}
              className="inline-flex items-center gap-2 px-4 py-2 bg-[#1E3A8A] text-white text-sm font-medium rounded-lg hover:bg-[#1E40AF] transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Reload page
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

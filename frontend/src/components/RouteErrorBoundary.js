import React from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

// Matches "Failed to fetch dynamically imported module" and related errors
// thrown when a code-split chunk 404s after a redeploy.
const isChunkError = (err) =>
  err?.message?.includes("Failed to fetch dynamically imported module") ||
  err?.message?.includes("Loading CSS chunk") ||
  err?.message?.includes("Importing a module script failed") ||
  err?.name === "ChunkLoadError";

const CHUNK_RELOAD_KEY = "__boundary_chunk_reloaded";

/**
 * Catches render errors inside lazy-loaded route components.
 *
 * Stale chunk after redeploy → auto-reload once (sessionStorage flag prevents
 * loops). Returns null while reloading — never renders an imported component
 * that might be missing from the old bundle.
 *
 * Any other render error → user-friendly card built entirely with
 * React.createElement so the card itself can never throw a ReferenceError.
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
    if (isChunkError(error)) {
      if (!sessionStorage.getItem(CHUNK_RELOAD_KEY)) {
        sessionStorage.setItem(CHUNK_RELOAD_KEY, "1");
        window.location.reload();
      }
    } else {
      console.error("[RouteErrorBoundary] Render error:", error, info?.componentStack);
    }
  }

  componentDidUpdate() {
    // Clear flag after a successful render so future chunk errors can also auto-recover.
    if (!this.state.error) {
      sessionStorage.removeItem(CHUNK_RELOAD_KEY);
    }
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    // Chunk error — show a spinner while the auto-reload fires rather than a blank screen
    if (isChunkError(error)) {
      return React.createElement(
        "div",
        {
          style: {
            minHeight: "100vh", display: "flex", flexDirection: "column",
            alignItems: "center", justifyContent: "center", background: "#f9fafb", gap: 12,
          },
        },
        React.createElement("div", {
          style: {
            width: 36, height: 36,
            border: "3px solid #e5e7eb", borderTopColor: "#1E3A8A",
            borderRadius: "50%",
            animation: "spin 0.8s linear infinite",
          },
        }),
        React.createElement("p", { style: { fontSize: 13, color: "#9ca3af" } }, "Loading…")
      );
    }

    // All other render errors — built with React.createElement to guarantee
    // the boundary card never itself throws a ReferenceError.
    return React.createElement(
      "div",
      {
        style: {
          minHeight: "100vh", display: "flex", alignItems: "center",
          justifyContent: "center", padding: 24, background: "#f9fafb",
        },
      },
      React.createElement(
        "div",
        { style: { maxWidth: 448, width: "100%", textAlign: "center" } },
        React.createElement(
          "div",
          {
            style: {
              width: 48, height: 48, borderRadius: "50%", background: "#fee2e2",
              display: "flex", alignItems: "center", justifyContent: "center",
              margin: "0 auto 16px",
            },
          },
          React.createElement(AlertTriangle, { style: { width: 24, height: 24, color: "#dc2626" } })
        ),
        React.createElement(
          "h2",
          { style: { fontSize: 18, fontWeight: 600, color: "#111827", marginBottom: 8 } },
          "Something went wrong"
        ),
        React.createElement(
          "p",
          { style: { fontSize: 14, color: "#6b7280", marginBottom: 20 } },
          "This page ran into an unexpected error. Refreshing usually fixes it."
        ),
        process.env.NODE_ENV !== "production" &&
          React.createElement(
            "pre",
            {
              style: {
                textAlign: "left", fontSize: 11, background: "#f3f4f6", borderRadius: 8,
                padding: 12, overflow: "auto", maxHeight: 160, color: "#b91c1c", marginBottom: 16,
              },
            },
            error?.message
          ),
        React.createElement(
          "button",
          {
            onClick: () => window.location.reload(),
            style: {
              display: "inline-flex", alignItems: "center", gap: 8,
              padding: "8px 16px", background: "#1E3A8A", color: "#fff",
              fontSize: 14, fontWeight: 500, borderRadius: 8, border: "none", cursor: "pointer",
            },
          },
          React.createElement(RefreshCw, { style: { width: 14, height: 14 } }),
          " Reload page"
        )
      )
    );
  }
}

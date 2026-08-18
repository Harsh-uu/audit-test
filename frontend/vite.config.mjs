import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";
import { fileURLToPath } from "url";
import { VitePWA } from "vite-plugin-pwa";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig(({ mode }) => {
  // Load ALL .env variables (not just VITE_-prefixed ones) so we can forward
  // REACT_APP_BACKEND_URL via define — existing source files need zero changes.
  const env = loadEnv(mode, process.cwd(), "");

  return {
    plugins: [
      react(),

      // ── Service Worker / PWA ──────────────────────────────────────────────
      // generateSW mode: Workbox writes the SW automatically from these rules.
      // autoUpdate: the SW silently installs updates; no "refresh needed" prompt.
      VitePWA({
        registerType: "autoUpdate",
        strategies: "generateSW",
        injectRegister: "auto",

        // Manifest — minimal, enough for "Add to Home Screen" on mobile devices
        manifest: {
          name: "1two Supervision",
          short_name: "1two",
          start_url: "/",
          display: "standalone",
          background_color: "#ffffff",
          theme_color: "#1E3A8A",
          icons: [
            { src: "/favicon.ico", sizes: "any", type: "image/x-icon" },
          ],
        },

        workbox: {
          // ── Precache: every hashed build asset ─────────────────────────────
          // Content-hashed filenames mean these are safe to cache forever;
          // a new deploy produces new hashes → SW auto-updates → stale cache
          // is discarded. Use separate patterns (brace expansion unsupported
          // in this version of workbox-build's glob engine).
          globPatterns: [
            "**/*.js",
            "**/*.css",
            "**/*.html",
            "**/*.ico",
            "**/*.png",
            "**/*.svg",
            "**/*.woff",
            "**/*.woff2",
          ],
          globIgnores: ["**/node_modules/**", "**/workbox-*.js", "**/sw.js"],

          // index.html: navigate to it from SW cache (offline shell),
          // but exclude /api routes from the navigation fallback so they
          // always go to the network.
          navigateFallback: "/index.html",
          navigateFallbackDenylist: [/^\/api\//],

          // SW file itself must never be cached (browsers enforce this
          // natively; belt-and-suspenders via Cache-Control below).
          // autoUpdate keeps max size manageable.

          runtimeCaching: [
            // ── NetworkOnly: auth + recording + processing ──────────────────
            // These MUST always hit the network — never serve stale auth
            // tokens or stale meeting processing state.
            {
              urlPattern: /\/api\/(auth|recording|processing|jobs)\//,
              handler: "NetworkOnly",
            },

            // ── StaleWhileRevalidate: stable reference data ─────────────────
            // Standards library and org structure change at most once a day.
            // Serve the cached copy instantly, refresh silently in background.
            {
              urlPattern: /\/api\/(admin\/standards|org\/structure)/,
              handler: "StaleWhileRevalidate",
              options: {
                cacheName: "api-stable",
                expiration: { maxEntries: 20, maxAgeSeconds: 3600 }, // 1 hour
                cacheableResponse: { statuses: [0, 200] },
              },
            },

            // ── NetworkFirst: live meeting data ─────────────────────────────
            // Always try the network; fall back to cache if offline so
            // previously loaded meeting reports remain readable.
            // 4-second timeout keeps the UI responsive on poor connections.
            {
              urlPattern: /\/api\/(meetings|review)\//,
              handler: "NetworkFirst",
              options: {
                cacheName: "api-meetings",
                networkTimeoutSeconds: 4,
                expiration: { maxEntries: 50, maxAgeSeconds: 300 }, // 5 min
                cacheableResponse: { statuses: [0, 200] },
              },
            },

            // ── CacheFirst: Google Fonts + any CDN assets ───────────────────
            {
              urlPattern: /^https:\/\/fonts\.(googleapis|gstatic)\.com\//,
              handler: "CacheFirst",
              options: {
                cacheName: "google-fonts",
                expiration: { maxEntries: 10, maxAgeSeconds: 60 * 60 * 24 * 365 },
                cacheableResponse: { statuses: [0, 200] },
              },
            },
          ],
        },
      }),

      // Serve index.html with no-store headers so browsers never cache the HTML
      // shell. Hashed JS/CSS assets keep their default long-lived cache headers.
      // The SW file itself is excluded — browsers handle SW caching natively.
      {
        name: "no-cache-html",
        configurePreviewServer(server) {
          server.middlewares.use((req, res, next) => {
            const url = req.url?.split("?")[0] ?? "";
            if (url === "/" || url.endsWith(".html")) {
              res.setHeader("Cache-Control", "no-store, no-cache, must-revalidate");
              res.setHeader("Pragma", "no-cache");
              res.setHeader("Expires", "0");
            } else if (url === "/sw.js" || url.startsWith("/workbox-")) {
              // SW update check: no-cache (conditional GET) not no-store,
              // so the browser fetches a fresh copy on every navigation.
              res.setHeader("Cache-Control", "no-cache");
            }
            next();
          });
        },
      },
    ],

    resolve: {
      alias: { "@": path.resolve(__dirname, "./src") },
    },

    // Forward REACT_APP_ vars so existing process.env.REACT_APP_* refs compile correctly.
    define: {
      "process.env.REACT_APP_BACKEND_URL": JSON.stringify(
        env.REACT_APP_BACKEND_URL
      ),
      "process.env.NODE_ENV": JSON.stringify(mode),
    },

    // The codebase uses JSX syntax in .js files (CRA allowed this).
    // Setting esbuild.include to cover ALL src files ensures esbuild's JSX
    // transform runs for both .js files (where we need loader:"jsx") and .jsx/.tsx
    // files (where the React plugin delegates JSX transform to esbuild in prod).
    esbuild: {
      loader: "jsx",
      include: /src\/.*\.[jt]sx?$/,
      exclude: [],
    },
    // Pre-bundle ALL dependencies at startup so Vite never discovers a new dep
    // at runtime and triggers a disruptive "Re-optimizing dependencies" full-reload.
    // Without this, the initial rolldown dep scan fails (JSX in .js files), only
    // 14/48 deps get pre-bundled, and every lazy-loaded page that imports a missing
    // dep causes a full page reload — catastrophic during recordings.
    optimizeDeps: {
      include: [
        "react", "react-dom", "react-dom/client",
        "react/jsx-runtime", "react/jsx-dev-runtime",
        "react-router-dom",
        "@tanstack/react-query",
        "axios",
        "lucide-react",
        "clsx", "tailwind-merge", "class-variance-authority",
        "sonner", "next-themes",
        "@hello-pangea/dnd",
        "react-hook-form",
        "recharts",
        "react-day-picker", "date-fns", "date-fns/locale",
        "cmdk",
        "vaul",
        "input-otp",
        "embla-carousel-react",
        "react-resizable-panels",
        "tailwindcss-animate",
        "@radix-ui/react-accordion",
        "@radix-ui/react-alert-dialog",
        "@radix-ui/react-aspect-ratio",
        "@radix-ui/react-avatar",
        "@radix-ui/react-checkbox",
        "@radix-ui/react-collapsible",
        "@radix-ui/react-context-menu",
        "@radix-ui/react-dialog",
        "@radix-ui/react-dropdown-menu",
        "@radix-ui/react-hover-card",
        "@radix-ui/react-label",
        "@radix-ui/react-menubar",
        "@radix-ui/react-navigation-menu",
        "@radix-ui/react-popover",
        "@radix-ui/react-progress",
        "@radix-ui/react-radio-group",
        "@radix-ui/react-scroll-area",
        "@radix-ui/react-select",
        "@radix-ui/react-separator",
        "@radix-ui/react-slider",
        "@radix-ui/react-slot",
        "@radix-ui/react-switch",
        "@radix-ui/react-tabs",
        "@radix-ui/react-toast",
        "@radix-ui/react-toggle",
        "@radix-ui/react-toggle-group",
        "@radix-ui/react-tooltip",
      ],
      esbuildOptions: {
        loader: { ".js": "jsx" },
      },
    },

    server: {
      host: process.env.HOST || "0.0.0.0",
      port: parseInt(process.env.PORT || "3000", 10),
      strictPort: true,
      allowedHosts: true,
      hmr: {
        clientPort: 443,
        timeout: 5000,
      },
    },

    // Preview server config — used by `vite preview` which serves the
    // production build. No HMR WebSocket, no 90-second K8s ingress drops.
    preview: {
      host: process.env.HOST || "0.0.0.0",
      port: parseInt(process.env.PORT || "3000", 10),
      strictPort: true,
      allowedHosts: true,
    },

    build: {
      outDir: "build",
      sourcemap: false,
      chunkSizeWarningLimit: 1000,
    },
  };
});

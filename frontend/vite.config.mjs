import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig(({ mode }) => {
  // Load ALL .env variables (not just VITE_-prefixed ones) so we can forward
  // REACT_APP_BACKEND_URL via define — existing source files need zero changes.
  const env = loadEnv(mode, process.cwd(), "");

  return {
    plugins: [
      react(),
      // Serve index.html with no-store headers so browsers never cache the HTML
      // shell. Hashed JS/CSS assets keep their default long-lived cache headers.
      {
        name: "no-cache-html",
        configurePreviewServer(server) {
          server.middlewares.use((req, res, next) => {
            if (req.url === "/" || req.url?.split("?")[0].endsWith(".html")) {
              res.setHeader("Cache-Control", "no-store, no-cache, must-revalidate");
              res.setHeader("Pragma", "no-cache");
              res.setHeader("Expires", "0");
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

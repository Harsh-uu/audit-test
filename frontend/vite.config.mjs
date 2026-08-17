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
    plugins: [react()],

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
    // Also tell the dep pre-bundler about JSX in .js files.
    optimizeDeps: {
      esbuildOptions: {
        loader: { ".js": "jsx" },
      },
    },

    server: {
      host: process.env.HOST || "0.0.0.0",
      port: parseInt(process.env.PORT || "3000", 10),
      strictPort: true,
      // Allow all hosts — the app runs behind the Kubernetes ingress with a
      // dynamic preview subdomain that we can't hardcode.
      allowedHosts: true,
      // The preview URL is served over HTTPS/443 by the Kubernetes ingress.
      hmr: {
        clientPort: 443,
      },
    },

    build: {
      outDir: "build",
      sourcemap: false,
      chunkSizeWarningLimit: 1000,
    },
  };
});

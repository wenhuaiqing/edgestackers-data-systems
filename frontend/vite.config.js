import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend port is overridable so the dev server can run beside other projects.
const BACKEND = process.env.VITE_BACKEND_URL || "http://localhost:8041";

export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.VITE_PORT || 5241),
    strictPort: true,
    // Only backend-owned paths; everything else is an SPA route.
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
      "/health": { target: BACKEND, changeOrigin: true },
    },
  },
});

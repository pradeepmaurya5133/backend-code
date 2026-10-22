import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    // The shared API client is used by every front end, so it lives outside web/.
    alias: { "@shared": path.resolve(__dirname, "../shared") },
  },
  server: {
    port: 5173,
    proxy: {
      // Same-origin in dev, so no CORS round trips while developing.
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});

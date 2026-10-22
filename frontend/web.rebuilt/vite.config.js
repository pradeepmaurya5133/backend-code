import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

// The shared API client lives outside this package (frontend/shared), so the
// dev server has to be allowed to serve a file from the parent directory.
const shared = fileURLToPath(new URL("../shared", import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@shared": shared },
  },
  server: {
    port: 5173,
    // Everything under /api is proxied, so the browser talks to one origin and
    // CORS never enters the picture during development.
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
    fs: { allow: [".", shared] },
  },
});

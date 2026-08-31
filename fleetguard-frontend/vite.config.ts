import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The app talks to the API on its own origin ("/api/..."), so the same client
// code works in three places without a build flag: the dev server proxies to a
// locally running uvicorn, nginx proxies to the backend container in Docker,
// and a deployment behind one hostname needs no proxy at all. Set
// VITE_API_BASE_URL only when the API genuinely lives on another origin.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_DEV_API_TARGET ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});

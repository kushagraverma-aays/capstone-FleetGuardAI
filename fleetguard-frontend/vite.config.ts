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
        // 127.0.0.1, never "localhost". Node 17+ stopped preferring IPv4 when
        // resolving localhost, so "localhost:8000" reaches ::1 first - and on a
        // machine that has also run `docker compose up`, ::1:8000 is the
        // *container's* backend while a locally run uvicorn binds only
        // 127.0.0.1. The dev server then silently proxies to a stale image, and
        // every endpoint added since that image was built answers 404 "Not
        // Found" with no other symptom. Pinning the literal address removes the
        // ambiguity; set VITE_DEV_API_TARGET to talk to anything else on purpose.
        target: process.env.VITE_DEV_API_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});

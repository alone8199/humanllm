import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies API + WebSocket to the HumanLLM backend (default :8000).
//  - /api/* -> http://localhost:8000/*       (REST: auth, worker, admin, v1)
//  - /ws/*  -> ws://localhost:8000/ws/*      (worker workbench websocket)
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
        changeOrigin: true,
        // Keep /ws prefix: backend route is /ws/worker; rewrite would strip it to /worker.
      },
    },
  },
  build: {
    outDir: "dist",
  },
});

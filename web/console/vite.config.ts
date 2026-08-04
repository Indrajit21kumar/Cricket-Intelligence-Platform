import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Each CIP service defaults to :8000, so in local dev run them on distinct
// ports (see web/console/README.md) and proxy per-service prefixes to them.
// The browser only ever calls same-origin /api/* — no backend CORS needed.
//   identity-service (M02)  ->  :8000    (uvicorn identity_service.main:app --port 8000)
//   profile-service  (M04)  ->  :8002    (uvicorn profile_service.main:app  --port 8002)
//   video-service    (M05)  ->  :8003    (uvicorn video_service.main:app    --port 8003)
//   pose-service     (M06)  ->  :8004    (uvicorn pose_service.main:app     --port 8004)
//   biomechanics     (M10)  ->  :8010    (uvicorn biomechanics_service.main:app --port 8010)
// `scripts/run_console_stack.py` starts exactly this set on these ports.
const svc = (target: string) => ({
  target,
  changeOrigin: true,
  rewrite: (path: string) => path.replace(/^\/api\/[a-z]+/, ""),
});

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180,
    proxy: {
      "/api/identity": svc("http://127.0.0.1:8000"),
      "/api/profile": svc("http://127.0.0.1:8002"),
      "/api/video": svc("http://127.0.0.1:8003"),
      "/api/pose": svc("http://127.0.0.1:8004"),
      "/api/biomechanics": svc("http://127.0.0.1:8010"),
    },
  },
});

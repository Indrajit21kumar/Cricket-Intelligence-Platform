import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The identity-service (M02) runs on :8000. Proxy /api -> that service so the
// browser never makes a cross-origin call (no CORS setup needed on the backend).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});

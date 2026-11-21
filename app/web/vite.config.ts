import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the API is reached through the same /api prefix as in production
// (nginx adds the token there); `npm run dev` proxies it to the running API.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.API_URL ?? "http://localhost:8000",
        rewrite: (path) => path.replace(/^\/api/, ""),
        headers: { Authorization: `Bearer ${process.env.API_TOKEN ?? ""}` },
      },
    },
  },
});

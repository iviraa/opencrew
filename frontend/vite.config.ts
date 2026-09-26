import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  worker: { format: "es" },
  server: { proxy: { "/api": process.env.API_URL ?? "http://localhost:8000", "/config.js": process.env.API_URL ?? "http://localhost:8000" } },  // API_URL lets a second backend run side by side
});

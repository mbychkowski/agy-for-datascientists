import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Relative base: the bundle is served at the root of the board's own port, both
// in the Antigravity side pane and in the standalone `./evidence-board` tab.
// `npm run dev` proxies the API to a backend started with `./evidence-board`.
export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 1200 },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
});

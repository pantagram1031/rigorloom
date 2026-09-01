import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Port is pinned so the Tauri devUrl and the smoke script agree.
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: { port: 5184, strictPort: true },
  build: { target: "esnext" },
});

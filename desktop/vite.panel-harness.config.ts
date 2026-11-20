import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-only harness for WP4: the real store and runtime, the shell replaced by
// a plain frame. Built into a temporary directory and served by a wrapper
// around rt_ui.py; never part of ui_dist.
export default defineConfig({
  plugins: [react()],
  base: "./",
  clearScreen: false,
  build: {
    target: "esnext",
    outDir: process.env.WP4_HARNESS_OUT ?? "/tmp/ui2-wp4/dist",
    emptyOutDir: true,
    assetsDir: "assets",
    rollupOptions: {
      input: "panel-harness.html",
      external: ["/assets/fonts/PretendardVariable.woff2"],
    },
  },
});

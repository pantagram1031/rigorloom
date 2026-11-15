import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Builds the standalone browser bundle served by runtime/scripts/rt_ui.py.
// /assets/fonts/PretendardVariable.woff2 remains external so the wheel stays
// small while the server can still serve it when running from a source checkout.
export default defineConfig({
  plugins: [react()],
  base: "./",
  clearScreen: false,
  build: {
    target: "esnext",
    outDir: "../runtime/scripts/ui_dist",
    emptyOutDir: true,
    assetsDir: "assets",
    rollupOptions: {
      external: ["/assets/fonts/PretendardVariable.woff2"],
    },
  },
});

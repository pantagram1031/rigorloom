/**
 * Application entry point owned by WP1b (`desktop/index.html` -> `/src/ui/entry.ts`).
 *
 * In `import.meta.env.DEV`, visiting `/__ui` or `?route=ui-gallery` mounts the
 * isolated primitives gallery without touching `main.tsx` or `App.tsx` (owned by WP2).
 * In production builds Vite replaces `import.meta.env.DEV` with `false`, so the
 * gallery chunk is completely tree-shaken out of `ui_dist`.
 */
async function bootEntry(): Promise<void> {
  if (import.meta.env.DEV && typeof window !== "undefined") {
    const params = new URLSearchParams(window.location.search);
    const isGalleryRoute =
      window.location.pathname === "/__ui" ||
      window.location.pathname === "/__ui/" ||
      params.get("route") === "ui-gallery";
    if (isGalleryRoute) {
      const { mountUiGallery } = await import("./Gallery");
      const root = document.getElementById("root");
      if (root) mountUiGallery(root);
      return;
    }
  }
  await import("../main");
}

void bootEntry();

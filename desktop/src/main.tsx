import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { loadPrefs, savePrefs } from "./runtime";
import "./styles.css";
import { migrateLegacyEditorPref, resolveUiVariant, setUiVariant, uiVariantFromQuery } from "./uiVariant";

// Editor v2 is the default; v1-tokens.css applies only when data-ui is "v1".
setUiVariant("v2");

if (import.meta.env.DEV) {
  // Hot reload re-evaluates modules; let defineDocSlice accept a re-definition.
  (globalThis as { __RL_HMR__?: boolean }).__RL_HMR__ = true;
}

async function start() {
  // Design work in a plain browser, replaying a recorded real session. The
  // guard is a literal after Vite's replacement, so both this branch and
  // src/devMock.ts (and its fixture) are absent from a production bundle.
  const hasInjectedToken =
    (typeof window !== "undefined" && "__RIGORLOOM_UI__" in window) ||
    new URLSearchParams(window.location.search).has("token");
  if (import.meta.env.DEV && !hasInjectedToken) {
    const { installDevMock } = await import("./devMock");
    installDevMock();
  }
  // Editor v2 by default; `?ui=v1|v2` or `editorVariant` can override.
  const query = uiVariantFromQuery(window.location.search);
  const loaded = query ? null : await loadPrefs().catch(() => null);
  // The desktop app reads prefs.json without the runtime bridge, so an old
  // `devEditorV2` key is migrated here too (once; a failed save retries next launch).
  const { prefs, patch } = migrateLegacyEditorPref(loaded);
  if (patch) void savePrefs(patch).catch(() => null);
  setUiVariant(resolveUiVariant(query, prefs));
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </React.StrictMode>,
  );
}

void start();

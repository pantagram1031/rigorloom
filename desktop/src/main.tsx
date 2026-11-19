import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { loadPrefs } from "./runtime";
import "./styles.css";
import { resolveUiVariant, setUiVariant, uiVariantFromQuery } from "./uiVariant";

// The v1 screens keep main's palette (v1-tokens.css applies under this mark).
setUiVariant("v1");

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
  // v1 unless `?ui=v2` or the devEditorV2 developer preference opts in.
  const query = uiVariantFromQuery(window.location.search);
  const prefs = query ? null : await loadPrefs().catch(() => null);
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

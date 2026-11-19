import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import "./styles.css";

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
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </React.StrictMode>,
  );
}

void start();

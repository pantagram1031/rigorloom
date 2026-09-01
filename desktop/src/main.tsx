import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import "./styles.css";

async function start() {
  // Design work in a plain browser, replaying a recorded real session. The
  // guard is a literal after Vite's replacement, so both this branch and
  // src/devMock.ts (and its fixture) are absent from a production bundle.
  if (import.meta.env.DEV) {
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

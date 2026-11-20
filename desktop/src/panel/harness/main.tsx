/**
 * WP4 dev harness. Boots the real store and runtime connection the way App
 * does, then draws a plain frame around the page and the `rightPanel` slot.
 * The title bar, strip and status bar here are stand-ins until WP2's shell
 * lands; they exist so the panel can be seen beside a real page.
 */
import React, { useMemo } from "react";
import ReactDOM from "react-dom/client";

import "../../styles.css";
import "../../views/review.css";
import "./harness.css";
import "../register";

import {
  boot,
  loadCorpusFiles,
  openPath,
  setLanguage,
  setSelectedChangeId,
  toggleTheme,
} from "../../actions";
import { PageSheet } from "../../components/PageSheet";
import { deliverDocumentEvents } from "../../documentEvents";
import * as rt from "../../runtime";
import {
  activeInspect,
  activeSession,
  activeText,
  getState,
  pushActivity,
  pushHostEvents,
  setState,
  useWorkspace,
} from "../../store";
import { buildRegionTextMap } from "../../workspace/externalPlan";
import { buildIndexedChanges, getReviewGuardSummary, useReviewGuardSummary } from "../../workspace/guardHelper";
import { dispatch as dispatchKey } from "../../shell/keys";
import { slotEntries } from "../../shell/slots";
import { latestView, panelSlice } from "../state";

function Frame() {
  const session = useWorkspace(activeSession);
  const inspect = useWorkspace(activeInspect);
  const texts = useWorkspace(activeText);
  const draft = useWorkspace((s) => s.draft);
  const language = useWorkspace((s) => s.language);
  const selected = useWorkspace((s) => s.selectedChangeId);
  const guard = useReviewGuardSummary();
  const textMap = useMemo(() => buildRegionTextMap(texts), [texts]);
  const changes = useMemo(() => buildIndexedChanges(draft, inspect, textMap, language), [draft, inspect, textMap, language]);
  const Panel = slotEntries("rightPanel")[0]?.component ?? null;
  const title = session ? session.source.name.replace(/\.[^.]+$/, "") : "";
  const ext = session ? session.source.name.slice(session.source.name.lastIndexOf(".")) : "";
  return (
    <div className="hx" data-testid="harness">
      <header className="hx-title">
        <span className="hx-mark" aria-hidden="true" />
        {session ? (
          <span className="hx-tab">
            {title}
            <span className="hx-ext">{ext}</span>
          </span>
        ) : null}
      </header>
      <div className="hx-main">
        <main className="hx-canvas">
          <div className="hx-strip">
            <span className="hx-strip-fill" />
          </div>
          <div className="hx-desk">
            {session && inspect ? (
              <PageSheet
                sessionId={session.sessionId}
                inspect={inspect}
                texts={texts}
                textMap={textMap}
                changes={changes}
                rowAudits={guard.rowAudits}
                selectedChangeId={selected}
                language={language}
                onSelectChange={(id) => setSelectedChangeId(id)}
              />
            ) : null}
          </div>
        </main>
        {Panel ? <Panel sessionId={session?.sessionId ?? null} /> : null}
      </div>
    </div>
  );
}

/** Hooks the screenshot and walkthrough scripts drive. Harness only. */
const harness = {
  async openSample(fileName: string): Promise<string | null> {
    const files = await loadCorpusFiles();
    const entry = files.find((f) => f.path.endsWith(fileName) || f.name === fileName);
    if (!entry) return null;
    return openPath(entry.path);
  },
  theme: (t: "light" | "dark") => toggleTheme(t),
  view: () => latestView(getState().activeSessionId),
  guard: () => getReviewGuardSummary(),
  panel: () => panelSlice.get(getState().activeSessionId),
  setPanel: (patch: Record<string, unknown>) => panelSlice.set(getState().activeSessionId, patch),
  state: () => getState(),
  setState,
};
(window as unknown as { __wp4: typeof harness }).__wp4 = harness;

async function start() {
  // No shell here: the harness feeds keys to the shell's registry itself.
  window.addEventListener("keydown", (e) => {
    dispatchKey(e);
  });
  await rt.onActivity(pushActivity);
  await rt.onEvents(deliverDocumentEvents);
  await rt.onAgentEvents(pushHostEvents);
  await rt.onStatus((s) => setState({ status: s }));
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <Frame />
    </React.StrictMode>,
  );
  await boot();
  await setLanguage(new URLSearchParams(window.location.search).get("lang") === "en" ? "en" : "ko");
}

void start();

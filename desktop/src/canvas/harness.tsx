import { StrictMode, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";

import { wp3t } from "../i18n/v2/wp3";
import type { CanvasChangeRef } from "../model/page";
import * as rt from "../runtime";
import { setState, useWorkspace, type QueuedOp } from "../store";
import { BlanksPane } from "../panes/BlanksPane";
import { FindPane } from "../panes/FindPane";
import { OutlinePane } from "../panes/OutlinePane";
import { bindLeftPaneNavigator, dispatchCanvasKeyEvent, getRegisteredSlot } from "./_shim";
import { setCanvasQueueAdapter } from "./actions";
import { canvas, setCanvasSlice, useCanvasSlice } from "./controller";
import { registerCanvasModule } from "./register";
import {
  buildDefaultGongmunChanges,
  buildHarnessInspect,
  buildHarnessTexts,
  changesToQueuedOps,
  HARNESS_DOC_NAME,
  HARNESS_DOC_PATH,
  HARNESS_SESSION_ID,
  HARNESS_SOURCE,
  type HarnessScenario,
} from "./__tests__/harnessData";
import "./harness.css";

registerCanvasModule();

function readUrlParams(): {
  scenario: HarnessScenario;
  theme: "light" | "dark";
  pane: "outline" | "blanks" | "find" | null;
  docPath: string | null;
  findQuery: string | null;
} {
  if (typeof window === "undefined") {
    return { scenario: "default", theme: "light", pane: null, docPath: null, findQuery: null };
  }
  const sp = new URLSearchParams(window.location.search);
  const rawScenario = sp.get("scenario") ?? "default";
  const scenario: HarnessScenario =
    rawScenario === "marks" ||
    rawScenario === "typing" ||
    rawScenario === "outline" ||
    rawScenario === "find" ||
    rawScenario === "drying" ||
    rawScenario === "live"
      ? rawScenario
      : "default";
  const theme = sp.get("theme") === "dark" ? "dark" : "light";
  const p = sp.get("pane");
  const pane = p === "outline" || p === "blanks" || p === "find" ? p : null;
  return {
    scenario,
    theme,
    pane,
    docPath: sp.get("path"),
    findQuery: sp.get("q"),
  };
}

function seedScenario(scenario: HarnessScenario, initialFindQuery?: string | null) {
  const inspect = buildHarnessInspect();
  const texts = buildHarnessTexts();
  const seeded = buildDefaultGongmunChanges(scenario);
  const queuedOps = changesToQueuedOps(seeded.changes);

  setState({
    activeSessionId: HARNESS_SESSION_ID,
    sessions: [
      {
        sessionId: HARNESS_SESSION_ID,
        source: HARNESS_SOURCE,
        inspect,
        texts,
        openedAt: "2026-11-19T00:00:00Z",
        active: true,
      } as never,
    ],
    inspects: { [HARNESS_SESSION_ID]: inspect },
    texts: { [HARNESS_SESSION_ID]: texts },
    draft: {
      candidateId: null,
      ops: queuedOps,
      opsCount: queuedOps.length,
      preview: null,
      validation: null,
      plan: null,
      boundSha256: HARNESS_SOURCE.sha256,
      stale: false,
      reverses: null,
      agentRun: null,
    } as never,
    candidates: { [HARNESS_SESSION_ID]: [] },
    render: {
      available: true,
      rendering: false,
      pageCount: 1,
      pageUrls: [],
      dpi: 96,
      engine: null,
      error: null,
    } as never,
    page: 1,
    inlineEdit: null,
    language: "ko",
  });

  setCanvasSlice(
    {
      view: seeded.initialView,
      selectedChangeId: seeded.initialSelectedId,
      selectedSeatKey: seeded.initialSeatKey,
      decisions: seeded.initialDecisions,
      decisionUndoStack: [],
      findQuery: initialFindQuery ?? seeded.initialFindQuery,
      drying: seeded.drying,
      statusNotice: null,
    },
    HARNESS_SESSION_ID,
  );

  return seeded;
}

function Wp3HarnessApp() {
  const params = useMemo(readUrlParams, []);
  const language = useWorkspace((s) => s.language);
  const slice = useCanvasSlice(HARNESS_SESSION_ID);

  const [theme, setTheme] = useState<"light" | "dark">(params.theme);
  const [leftPane, setLeftPane] = useState<"outline" | "blanks" | "find">(
    () =>
      params.pane ??
      (params.scenario === "outline"
        ? "outline"
        : params.scenario === "find"
          ? "find"
          : "blanks"),
  );
  const [changes, setChanges] = useState<CanvasChangeRef[]>([]);
  const [liveReady, setLiveReady] = useState(params.scenario !== "live");
  const [liveError, setLiveError] = useState<string | null>(null);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    return bindLeftPaneNavigator((pane) => setLeftPane(pane));
  }, []);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      dispatchCanvasKeyEvent(e as unknown as Parameters<typeof dispatchCanvasKeyEvent>[0]);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    if (params.scenario !== "live") {
      const seeded = seedScenario(params.scenario, params.findQuery);
      setChanges(seeded.changes);
      setCanvasQueueAdapter({
        upsertOp: (op: QueuedOp, replaceOpId?: string | null) => {
          const opId = op.opId ?? replaceOpId ?? `op-${Date.now()}`;
          const key = `c:${op.kind === "fill_cell" || op.kind === "replace_at_cell" ? op.table : 0}:${
            op.kind === "fill_cell" || op.kind === "replace_at_cell" ? op.row : 0
          }:${op.kind === "fill_cell" || op.kind === "replace_at_cell" ? op.col : 0}`;
          const newRef: CanvasChangeRef = {
            id: opId,
            n: 0,
            at:
              op.kind === "fill_cell" || op.kind === "replace_at_cell"
                ? `t${op.table}/r${op.row}/c${op.col}`
                : "p0",
            kind: op.kind,
            opKind: op.kind,
            label: opId,
            before: op.before ?? "",
            after: op.text,
            page: 1,
            source: op.origin === "user" ? "user" : "agent",
            decision: "accepted",
            guard: "none",
            hard: false,
            isFactChanged: false,
            isStale: false,
            cellKey:
              op.kind === "fill_cell" || op.kind === "replace_at_cell" ? key : undefined,
            run: op.kind === "replace_at_cell" ? op.run : undefined,
            hasFormText: Boolean(op.before && op.before.trim().length > 0),
            bodyStyleApplied: true,
          };
          setChanges((prev) => {
            const idx = prev.findIndex((c) => c.id === opId || c.id === replaceOpId);
            if (idx >= 0) {
              const copy = [...prev];
              copy[idx] = { ...newRef, n: copy[idx].n, label: copy[idx].label };
              return copy;
            }
            return [...prev, { ...newRef, n: prev.length + 1 }];
          });
        },
        removeOp: (opId: string) => {
          setChanges((prev) => prev.filter((c) => c.id !== opId));
        },
      });
      return () => setCanvasQueueAdapter(null);
    }

    // Live RPC mode connected to `rigorloom ui`
    let cancelled = false;
    (async () => {
      try {
        const opened = await rt.openPath(params.docPath ?? HARNESS_DOC_PATH);
        const inspect = await rt.inspect(opened.sessionId);
        const regionSelectors: Array<{ table?: number; row?: number; col?: number; atPara?: number }> = [];
        for (const tbl of inspect.graph.tables) {
          for (const c of tbl.cells) {
            regionSelectors.push({ table: tbl.index, row: c.addr.row, col: c.addr.col });
          }
        }
        const regionsResp = await rt.readRegion(opened.sessionId, regionSelectors);
        if (cancelled) return;
        setState({
          activeSessionId: opened.sessionId,
          sessions: [
            {
              sessionId: opened.sessionId,
              source: opened.source,
              inspect,
              texts: regionsResp.regions,
              openedAt: new Date().toISOString(),
              active: true,
            } as never,
          ],
          inspects: { [opened.sessionId]: inspect },
          texts: { [opened.sessionId]: regionsResp.regions },
          draft: {
            candidateId: null,
            ops: [],
            opsCount: 0,
            preview: null,
            validation: null,
            plan: null,
            boundSha256: opened.source.sha256,
            stale: false,
            reverses: null,
            agentRun: null,
          } as never,
          candidates: { [opened.sessionId]: [] },
          language: "ko",
        });
        setChanges([]);
        setLiveReady(true);
      } catch (err) {
        if (!cancelled) {
          setLiveError(err instanceof Error ? err.message : String(err));
          setLiveReady(true);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [params]);

  const CanvasSlot = getRegisteredSlot("canvas");
  const StatusLeftSlot = getRegisteredSlot("statusLeft");
  const StatusRightSlot = getRegisteredSlot("statusRight");

  return (
    <div className="rl-harness-shell" data-testid="wp3-harness" data-scenario={params.scenario}>
      <header className="rl-harness-titlebar">
        <div className="rl-harness-brand">
          <span>Rigorloom</span>
          <span className="rl-harness-doc-tab" data-accent="true">
            <span className="rl-harness-doc-dot" aria-hidden="true" />
            <span>{HARNESS_DOC_NAME}</span>
          </span>
        </div>
        <button
          type="button"
          className="rl-harness-theme-btn"
          data-testid="harness-theme-toggle"
          onClick={() => setTheme((t) => (t === "light" ? "dark" : "light"))}
        >
          {theme.toUpperCase()}
        </button>
      </header>

      <div className="rl-harness-body">
        <aside className="rl-harness-left" data-docked="true">
          <div className="rl-harness-pane-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={leftPane === "outline"}
              className={`rl-harness-pane-tab${
                leftPane === "outline" ? " rl-harness-pane-tab--active" : ""
              }`}
              data-testid="tab-pane-outline"
              onClick={() => setLeftPane("outline")}
            >
              {wp3t("pane_outline_title", language)}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={leftPane === "blanks"}
              className={`rl-harness-pane-tab${
                leftPane === "blanks" ? " rl-harness-pane-tab--active" : ""
              }`}
              data-testid="tab-pane-blanks"
              onClick={() => setLeftPane("blanks")}
            >
              {wp3t("pane_blanks_title", language)}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={leftPane === "find"}
              className={`rl-harness-pane-tab${
                leftPane === "find" ? " rl-harness-pane-tab--active" : ""
              }`}
              data-testid="tab-pane-find"
              onClick={() => setLeftPane("find")}
            >
              {wp3t("pane_find_title", language)}
            </button>
          </div>
          <div className="rl-harness-pane-body">
            {leftPane === "outline" ? (
              <OutlinePane changesOverride={changes.length > 0 ? changes : undefined} />
            ) : leftPane === "blanks" ? (
              <BlanksPane changesOverride={changes.length > 0 ? changes : undefined} />
            ) : (
              <FindPane changesOverride={changes.length > 0 ? changes : undefined} />
            )}
          </div>
        </aside>

        <main className="rl-harness-center">
          {liveError ? (
            <div data-testid="harness-live-error">{liveError}</div>
          ) : liveReady && CanvasSlot ? (
            <CanvasSlot
              changesOverride={params.scenario === "live" ? undefined : changes}
            />
          ) : null}
        </main>

        <aside className="rl-harness-right" data-docked="true">
          <div className="rl-harness-right-list">
            {changes.map((ch) => {
              const effectiveDecision = slice.decisions[ch.id] ?? ch.decision;
              const isSelected = slice.selectedChangeId === ch.id;
              return (
                <button
                  key={ch.id}
                  type="button"
                  className={`rl-harness-change-row${
                    isSelected ? " rl-harness-change-row--active" : ""
                  }`}
                  data-testid={`harness-change-${ch.id}`}
                  onClick={() => canvas.select(ch.id, { fromCanvas: false })}
                >
                  <span
                    className="rl-harness-change-n rl-num"
                    data-accent={effectiveDecision === "pending" ? "true" : undefined}
                    data-decided={effectiveDecision !== "pending" ? "true" : undefined}
                  >
                    {ch.n}
                  </span>
                  <span className="rl-harness-change-label">{ch.label}</span>
                </button>
              );
            })}
          </div>
          <div className="rl-harness-right-footer">
            <button
              type="button"
              className="rl-harness-primary-btn"
              data-variant="primary"
              data-testid="harness-export-btn"
              onClick={() => {
                setCanvasSlice({ drying: true });
                window.setTimeout(() => setCanvasSlice({ drying: false }), 400);
              }}
            >
              {wp3t("canvas_export", language)}
            </button>
          </div>
        </aside>
      </div>

      <footer className="rl-harness-statusbar">
        {StatusLeftSlot ? <StatusLeftSlot /> : <span />}
        {StatusRightSlot ? <StatusRightSlot /> : <span />}
      </footer>
    </div>
  );
}

const rootEl = document.getElementById("root");
if (rootEl) {
  createRoot(rootEl).render(
    <StrictMode>
      <Wp3HarnessApp />
    </StrictMode>,
  );
}

import { SOURCE_COPY } from "./sourceCopy";
import { useMemo } from "react";

import { exportApplied } from "../actions";
import { errorCodeMessage } from "../i18n/vocabulary";
import { wp3t } from "../i18n/v2/wp3";
import type { SlotProps } from "../shell/slots";
import {
  activeDisplayText,
  activeSession,
  getState,
  headCandidate,
  showToast,
  useWorkspace,
} from "../store";
import { buildRegionTextMap } from "../workspace/externalPlan";
import { stepCanvasChange } from "./actions";
import { useCanvasChanges } from "./changes";
import { canvas, useCanvasSlice } from "./controller";

export function useCanvasBaseName(): string {
  return useWorkspace((s) => {
    const session = activeSession(s);
    const head = headCandidate(s);
    const index = session && head
      ? (s.candidates[session.sessionId] ?? []).findIndex((c) => c.runId === head.runId)
      : -1;
    return index >= 0
      ? wp3t("canvas_view_base_revision", s.language, [index + 1])
      : wp3t("canvas_view_base_source", s.language);
  });
}

export function DocumentStripStart() {
  const language = useWorkspace((s) => s.language);
  const draft = useWorkspace((s) => s.draft);
  const baseName = useCanvasBaseName();
  const count = draft.ops.length;
  const { rasterSource, rasterApprox } = useCanvasSlice();
  const stale = draft.validation?.stale ||
    (draft.plan && draft.boundSha256 && draft.plan.boundSha256 !== draft.boundSha256);
  const subjectText = count
    ? wp3t(stale ? "canvas_strip_stale" : "canvas_strip_breadcrumb", language, [baseName, count])
    : baseName;

  return (
    <div className="rl-strip-left" data-testid="doc-strip">
      <span className="rl-strip-version" data-testid="strip-version">{subjectText}</span>
      <span className="rl-strip-source" data-page-source={rasterSource ?? "projection"}>
        {wp3t(rasterSource ? SOURCE_COPY[rasterSource] : "page_source_projection", language)}
        {rasterApprox ? ` · ${wp3t("page_source_approx", language)}` : null}
      </span>
      {rasterSource !== "engine" ? (
        <span className="rl-strip-grade" data-testid="strip-grade">{wp3t("canvas_grade_preview", language)}</span>
      ) : null}
    </div>
  );
}

export function DocumentStrip({ sessionId }: SlotProps) {
  const language = useWorkspace((s) => s.language);
  const exporting = useWorkspace((s) => s.exportPhase === "starting");
  const exportRunId = useWorkspace((s) => {
    if (!sessionId || s.activeSessionId !== sessionId) return null;
    return s.applied?.sessionId === sessionId ? s.applied.runId : headCandidate(s)?.runId ?? null;
  });
  const texts = useWorkspace(activeDisplayText);
  const textMap = useMemo(() => buildRegionTextMap(texts), [texts]);
  const changes = useCanvasChanges(sessionId, textMap);
  const { view, selectedChangeId } = useCanvasSlice(sessionId);
  const baseName = useCanvasBaseName();
  const selectedIdx = changes.findIndex((c) => c.id === selectedChangeId);
  const currentPos = Math.max(1, selectedIdx + 1);

  const handleExport = async () => {
    if (getState().activeSessionId !== sessionId || !exportRunId) return;
    if (await exportApplied(undefined, exportRunId)) return;
    const { exportError, language: lang } = getState();
    if (exportError) showToast(errorCodeMessage(exportError.code, lang), 3200);
  };

  if (changes.length === 0 && !exportRunId) return null;

  return (
    <div className="rl-strip-right">
      {changes.length > 0 ? (
        <>
          <div
            className="rl-view-switch"
            role="tablist"
            data-testid="canvas-view-switch"
            aria-label={wp3t("cmd_cycle_view", language)}
          >
            <button
              type="button"
              role="tab"
              aria-selected={view === "marks"}
              className={`rl-view-seg${view === "marks" ? " rl-view-seg--active" : ""}`}
              data-testid="view-seg-marks"
              onClick={() => canvas.setView("marks")}
            >
              {wp3t("canvas_view_marks", language)}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={view === "clean"}
              className={`rl-view-seg${view === "clean" ? " rl-view-seg--active" : ""}`}
              data-testid="view-seg-clean"
              onClick={() => canvas.setView("clean")}
            >
              {wp3t("canvas_view_clean", language)}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={view === "base"}
              className={`rl-view-seg${view === "base" ? " rl-view-seg--active" : ""}`}
              data-testid="view-seg-base"
              onClick={() => canvas.setView("base")}
            >
              {baseName}
            </button>
          </div>

          <div className="rl-stepper" data-testid="canvas-stepper">
            <button
              type="button"
              className="rl-step-btn"
              data-testid="stepper-prev"
              aria-label={wp3t("canvas_stepper_prev", language)}
              disabled={changes.length <= 1}
              onClick={() => stepCanvasChange(-1)}
            >
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                <path
                  d="M3 7.5 6 4.5l3 3"
                  stroke="currentColor"
                  strokeWidth="1.25"
                  strokeLinecap="square"
                />
              </svg>
            </button>
            <span className="rl-step-pos" data-testid="stepper-pos">
              {wp3t("canvas_stepper_pos", language, [currentPos, changes.length])}
            </span>
            <button
              type="button"
              className="rl-step-btn"
              data-testid="stepper-next"
              aria-label={wp3t("canvas_stepper_next", language)}
              disabled={changes.length <= 1}
              onClick={() => stepCanvasChange(1)}
            >
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                <path
                  d="M3 4.5 6 7.5l3-3"
                  stroke="currentColor"
                  strokeWidth="1.25"
                  strokeLinecap="square"
                />
              </svg>
            </button>
          </div>
        </>
      ) : null}
      {exportRunId ? (
        <button
          type="button"
          className="rl-strip-export"
          data-testid="strip-export"
          disabled={exporting}
          onClick={() => void handleExport()}
        >
          {wp3t("canvas_export", language)}
        </button>
      ) : null}
    </div>
  );
}

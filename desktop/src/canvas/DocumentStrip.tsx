import type { ReactNode } from "react";

import { wp3t } from "../i18n/v2/wp3";
import type { CanvasChangeRef, PageViewMode } from "../model/page";
import type { UiLanguage } from "../types";

export interface DocumentStripProps {
  baseName: string;
  changes: readonly CanvasChangeRef[];
  selectedChangeId: string | null;
  view: PageViewMode;
  gradeLabel?: string | null;
  isStale?: boolean;
  readOnly?: boolean;
  language: UiLanguage;
  onSetView: (view: PageViewMode) => void;
  onStepChange: (delta: -1 | 1) => void;
  stripStart?: ReactNode;
  stripEnd?: ReactNode;
}

export function DocumentStrip({
  baseName,
  changes,
  selectedChangeId,
  view,
  gradeLabel,
  isStale = false,
  readOnly = false,
  language,
  onSetView,
  onStepChange,
  stripStart,
  stripEnd,
}: DocumentStripProps) {
  const hasPending = changes.length > 0;
  const selectedIdx = hasPending
    ? changes.findIndex((c) => c.id === selectedChangeId)
    : -1;
  const currentPos = selectedIdx >= 0 ? selectedIdx + 1 : hasPending ? 1 : 0;

  const subjectText = readOnly
    ? wp3t("canvas_strip_readonly", language, [baseName])
    : isStale && hasPending
      ? wp3t("canvas_strip_stale", language, [baseName, changes.length])
      : hasPending
        ? wp3t("canvas_strip_pending", language, [baseName, changes.length])
        : baseName;

  const fullGrade = gradeLabel ?? wp3t("canvas_grade_preview", language);
  const shortGrade = wp3t("canvas_grade_preview_short", language);

  return (
    <header
      className="rl-doc-strip"
      data-testid="doc-strip"
      data-docked="true"
    >
      <div className="rl-strip-left">
        {stripStart ?? (
          <span className="rl-strip-version" data-testid="strip-version">
            {subjectText}
          </span>
        )}
        <span className="rl-strip-sep" aria-hidden="true">
          ·
        </span>
        <span className="rl-strip-grade rl-strip-grade--full" data-testid="strip-grade">
          {fullGrade}
        </span>
        <span className="rl-strip-grade rl-strip-grade--short">
          {shortGrade}
        </span>
      </div>

      <div className="rl-strip-right">
        {hasPending ? (
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
                onClick={() => onSetView("marks")}
              >
                {wp3t("canvas_view_marks", language)}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={view === "clean"}
                className={`rl-view-seg${view === "clean" ? " rl-view-seg--active" : ""}`}
                data-testid="view-seg-clean"
                onClick={() => onSetView("clean")}
              >
                {wp3t("canvas_view_clean", language)}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={view === "base"}
                className={`rl-view-seg${view === "base" ? " rl-view-seg--active" : ""}`}
                data-testid="view-seg-base"
                onClick={() => onSetView("base")}
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
                onClick={() => onStepChange(-1)}
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
                onClick={() => onStepChange(1)}
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

        {stripEnd ?? (
          <button
            type="button"
            className="rl-strip-export"
            data-testid="strip-export"
          >
            {wp3t("canvas_export", language)}
          </button>
        )}
      </div>
    </header>
  );
}

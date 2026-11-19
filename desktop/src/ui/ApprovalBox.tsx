import type { HTMLAttributes, ReactNode } from "react";

import { tWp1b } from "../i18n/v2/wp1b";
import type { UiLanguage } from "../i18n/vocabulary";
import { principleAttributes } from "./attributes";

export interface ApprovalBoxProps extends HTMLAttributes<HTMLDivElement> {
  /** UI language for column headers (`제안` · `점검` · `승인`). */
  lang?: UiLanguage;
  /** First cell body (e.g. `에이전트 · 24건`). */
  propose: ReactNode;
  /** Second cell body (e.g. `바뀐 사실 0 · 확인 1`). */
  check: ReactNode;
  /**
   * Third cell body. Empty until applied (`직접 승인 · 오후 2:31` or `정책으로 적용`).
   * Never renders a stamp, dashed seal placeholder, or hover preview (D1 §5, J1 §1 Defect 26).
   */
  approve?: ReactNode;
  /** Set true when the `점검` cell highlights a non-zero changed-fact count (`data-fact=""`). */
  hasChangedFact?: boolean;
  /** Single-line summary variant for `기록` timeline nodes (D1 §3f). */
  compact?: boolean;
}

/**
 * Ruled three-cell approval box (`제안 | 점검 | 승인`, D1 §5, J1 §1 Defects 20 & 26).
 *
 * Geometry: 20 px header (`--text-sm`, `--text-3`), 36 px body (`--text-base`, `--ink`),
 * 1 px `--line-strong` hairlines, `--radius-0` (0 px), zero shadow (`data-docked=""`).
 * The word `결재` never appears on screen (J1 §3 Copy #11).
 */
export function ApprovalBox({
  lang = "ko",
  propose,
  check,
  approve,
  hasChangedFact = false,
  compact = false,
  className = "",
  ...rest
}: ApprovalBoxProps) {
  const proposeLabel = tWp1b("approval_col_propose", lang);
  const checkLabel = tWp1b("approval_col_check", lang);
  const approveLabel = tWp1b("approval_col_approve", lang);

  if (compact) {
    return (
      <div
        className={`rl-approval-compact ${className}`.trim()}
        {...principleAttributes({ docked: true })}
        {...rest}
      >
        <span className="rl-approval-compact-item">
          <span className="rl-approval-compact-key">{proposeLabel}</span> {propose}
        </span>
        <span className="rl-approval-compact-sep" aria-hidden="true">
          ·
        </span>
        <span
          className="rl-approval-compact-item"
          {...principleAttributes({ fact: hasChangedFact })}
        >
          <span className="rl-approval-compact-key">{checkLabel}</span> {check}
        </span>
        {approve ? (
          <>
            <span className="rl-approval-compact-sep" aria-hidden="true">
              ·
            </span>
            <span className="rl-approval-compact-item">
              <span className="rl-approval-compact-key">{approveLabel}</span> {approve}
            </span>
          </>
        ) : null}
      </div>
    );
  }

  return (
    <div
      role="group"
      aria-label={`${proposeLabel} · ${checkLabel} · ${approveLabel}`}
      className={`rl-approval-box ${className}`.trim()}
      {...principleAttributes({ docked: true })}
      {...rest}
    >
      <div className="rl-approval-cell">
        <div className="rl-approval-head">{proposeLabel}</div>
        <div className="rl-approval-body">{propose}</div>
      </div>
      <div
        className={`rl-approval-cell${hasChangedFact ? " rl-approval-cell--fact" : ""}`}
        {...principleAttributes({ fact: hasChangedFact })}
      >
        <div className="rl-approval-head">{checkLabel}</div>
        <div className="rl-approval-body">{check}</div>
      </div>
      <div className="rl-approval-cell">
        <div className="rl-approval-head">{approveLabel}</div>
        <div className="rl-approval-body rl-approval-body--approve">{approve ?? null}</div>
      </div>
    </div>
  );
}

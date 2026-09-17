/**
 * 검사 결과 — one row per offline checker from `candidate/verify`.
 *
 * Unavailable is a designed state with the runtime's reason, never pass.
 * The footer is the renderer-freeze line: this is bytes and offline rules,
 * not a render proof.
 */
import { setState, useWorkspace } from "../store";
import {
  VERIFY_FOOTER,
  checkerCounts,
  checkerFindings,
  checkerVerdict,
  verdictLabel,
  verdictTone,
  verifyTargetLabel,
} from "../verifyReport";
import { Tag } from "./Tag";

function findingWhere(item: { at?: string; page?: number | null }): string {
  const parts: string[] = [];
  if (typeof item.page === "number") parts.push(`쪽 ${item.page}`);
  if (item.at) parts.push(String(item.at));
  return parts.join(" · ") || "위치 없음";
}

export function VerifyPanel() {
  const open = useWorkspace((s) => s.verifyPanelOpen);
  const phase = useWorkspace((s) => s.checkPhase);
  const result = useWorkspace((s) => s.verifyResult);
  if (!open) return null;

  const rows = result?.checks.checks ?? [];

  return (
    <section className="verify-panel" data-testid="verify-results" aria-label="검사 결과">
      <header className="verify-panel-head">
        <h3>검사 결과</h3>
        {phase === "starting" ? <Tag tone="none">검사 중</Tag> : null}
        {result ? (
          <span className="count" data-testid="verify-run-meta">
            {verifyTargetLabel(result)} · {result.checkedUtc}
          </span>
        ) : null}
        <button
          className="ghost"
          style={{ color: "var(--fg-muted)" }}
          onClick={() => setState({ verifyPanelOpen: false })}
          data-testid="close-verify-results"
        >
          닫기
        </button>
      </header>
      <div className="verify-panel-body">
        {phase === "starting" ? (
          <p className="empty" data-testid="verify-progress">
            오프라인 검사를 실행하는 중입니다.
          </p>
        ) : phase === "failed" ? (
          <p className="empty" data-testid="verify-failed">
            검사를 완료하지 못했습니다. 지금은 검사 결과를 확인할 수 없습니다.
          </p>
        ) : rows.length === 0 ? (
          <p className="empty">검사기가 반환한 행이 없습니다.</p>
        ) : (
          <ul className="verify-checkers" data-testid="verify-checkers">
            {rows.map((row) => {
              const verdict = checkerVerdict(row);
              const counts = checkerCounts(row);
              const findings = checkerFindings(row);
              const reason = typeof row.reason === "string" ? row.reason : null;
              return (
                <li
                  key={row.checker}
                  className="verify-checker"
                  data-testid={`verify-checker-${row.checker}`}
                  data-verdict={verdict}
                >
                  <div className="verify-checker-head">
                    <span className="mono">{row.checker}</span>
                    <Tag tone={verdictTone(verdict)} title={reason ?? undefined}>
                      {verdictLabel(verdict)}
                    </Tag>
                    <span className="count">
                      막힘 {counts.hard} · 주의 {counts.warn}
                    </span>
                  </div>
                  {verdict === "unavailable" ? (
                    <p className="verify-unavailable" data-testid={`verify-unavailable-${row.checker}`}>
                      {reason ?? "이 검사는 실행되지 않았습니다. 실행되지 않은 검사는 통과로 세지 않습니다."}
                    </p>
                  ) : findings.length > 0 ? (
                    <details className="verify-findings" data-testid={`verify-findings-${row.checker}`}>
                      <summary>지적 {findings.length}건</summary>
                      <ul>
                        {findings.map((item, index) => (
                          <li
                            key={`${item.code ?? "f"}-${index}`}
                            className="verify-finding"
                            data-testid={`verify-finding-${row.checker}-${index}`}
                          >
                            <span className="where">{findingWhere(item)}</span>
                            <span className="what">{item.msg ?? item.code ?? ""}</span>
                          </li>
                        ))}
                      </ul>
                    </details>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
        <p className="verify-footer" data-testid="verify-footer">
          {VERIFY_FOOTER}
        </p>
      </div>
    </section>
  );
}

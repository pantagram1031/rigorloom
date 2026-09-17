/**
 * Fill progress + result inside the 파이프라인 disclosure.
 *
 * Contact sheets are images labelled with the loop's own proof grade.
 * Layout QA and verify_format reuse P2 checker rows. Never a render certificate.
 */
import { cancelFill, runFill } from "../actions";
import {
  FILL_FOOTER,
  canRunFill,
  proofGradeLabel,
} from "../fillReport";
import { useWorkspace } from "../store";
import {
  checkerCounts,
  checkerFindings,
  checkerVerdict,
  verdictLabel,
  verdictTone,
} from "../verifyReport";
import { Tag } from "./Tag";

function findingWhere(item: { at?: string; page?: number | null }): string {
  const parts: string[] = [];
  if (typeof item.page === "number") parts.push(`쪽 ${item.page}`);
  if (item.at) parts.push(String(item.at));
  return parts.join(" · ") || "위치 없음";
}

export function FillCard() {
  const status = useWorkspace((s) => s.pipelineStatus);
  const capabilities = useWorkspace((s) => s.capabilities);
  const phase = useWorkspace((s) => s.fillPhase);
  const progress = useWorkspace((s) => s.fillProgress);
  const result = useWorkspace((s) => s.fillResult);
  const error = useWorkspace((s) => s.fillError);
  const runnable = canRunFill(status, capabilities);

  return (
    <div className="fill-card" data-testid="fill-card">
      <div className="fill-card-actions">
        {runnable && phase !== "starting" ? (
          <button
            type="button"
            className="action"
            data-testid="fill-run"
            onClick={() => void runFill()}
          >
            채우기 실행
          </button>
        ) : null}
        {phase === "starting" ? (
          <button
            type="button"
            className="ghost"
            data-testid="fill-cancel"
            onClick={() => void cancelFill()}
          >
            멈추기
          </button>
        ) : null}
      </div>
      {phase === "starting" ? (
        <div className="fill-progress" data-testid="fill-progress">
          <Tag tone="none">채우는 중</Tag>
          <span data-testid="fill-progress-iter">
            반복 {progress?.iteration ?? "…"}
          </span>
          <span data-testid="fill-progress-state">
            상태 {progress?.state ?? "…"}
          </span>
          {progress?.proofGrade ? (
            <span data-testid="fill-progress-grade">
              {proofGradeLabel(String(progress.proofGrade))}
            </span>
          ) : null}
        </div>
      ) : null}
      {phase === "failed" && error ? (
        <p className="prose" data-testid="fill-error">
          {error.message}
        </p>
      ) : null}
      {result ? (
        <div className="fill-result" data-testid="fill-result" data-state={result.state}>
          <div className="fill-result-head">
            <span className="mono" data-testid="fill-state">
              {result.state}
            </span>
            <span data-testid="fill-page-count">쪽 {result.pageCount ?? "—"}</span>
            <span data-testid="fill-proof-grade">
              {proofGradeLabel(result.proofGrade)}
            </span>
          </div>
          <ul className="fill-sheets" data-testid="fill-sheets">
            {result.contactSheets.map((sheet, index) => (
              <li
                key={sheet.sha256 || sheet.path}
                className="fill-sheet"
                data-testid={`fill-sheet-${index}`}
                data-proof-grade={result.proofGrade}
              >
                {sheet.data ? (
                  <img
                    src={`data:${sheet.mediaType};base64,${sheet.data}`}
                    alt={proofGradeLabel(result.proofGrade)}
                  />
                ) : null}
                <span className="fill-sheet-label">{proofGradeLabel(result.proofGrade)}</span>
                <span className="mono fill-sheet-hash">{sheet.sha256.slice(0, 12)}</span>
              </li>
            ))}
          </ul>
          <ul className="verify-checkers" data-testid="fill-checkers">
            {(result.checks.checks.length ? result.checks.checks : [result.layoutQa, result.verifyFormat]).map(
              (row) => {
                const verdict = checkerVerdict(row);
                const counts = checkerCounts(row);
                const findings = checkerFindings(row);
                const reason = typeof row.reason === "string" ? row.reason : null;
                return (
                  <li
                    key={row.checker}
                    className="verify-checker"
                    data-testid={`fill-checker-${row.checker}`}
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
                      <p className="verify-unavailable">{reason ?? "이 검사는 실행되지 않았습니다."}</p>
                    ) : findings.length > 0 ? (
                      <ul>
                        {findings.map((item, index) => (
                          <li key={`${item.code ?? "f"}-${index}`}>
                            {findingWhere(item)} · {item.msg ?? item.code ?? ""}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </li>
                );
              },
            )}
          </ul>
          <ul className="fill-outputs" data-testid="fill-outputs">
            {result.outputs.map((row) => (
              <li key={row.role} data-testid={`fill-output-${row.role}`}>
                <span className="mono">{row.role}</span>
                <span className="mono">{row.sha256}</span>
                <span>{row.bytes} B</span>
              </li>
            ))}
          </ul>
          <p className="verify-footer" data-testid="fill-footer">
            {FILL_FOOTER}
          </p>
        </div>
      ) : null}
    </div>
  );
}

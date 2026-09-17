/**
 * Poster build + verify inside the 파이프라인 disclosure.
 *
 * The PNG is labelled as a preview, not a proof. Verifier rows reuse P2.
 */
import { runPoster } from "../actions";
import {
  POSTER_FOOTER,
  POSTER_PREVIEW_LABEL,
  canRunPoster,
} from "../posterReport";
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

export function PosterCard() {
  const status = useWorkspace((s) => s.pipelineStatus);
  const capabilities = useWorkspace((s) => s.capabilities);
  const phase = useWorkspace((s) => s.posterPhase);
  const result = useWorkspace((s) => s.posterResult);
  const error = useWorkspace((s) => s.posterError);
  const runnable = canRunPoster(status, capabilities);

  return (
    <div className="fill-card poster-card" data-testid="poster-card">
      <div className="fill-card-actions">
        {runnable && phase !== "starting" ? (
          <button
            type="button"
            className="action"
            data-testid="poster-run"
            onClick={() => void runPoster()}
          >
            포스터 만들기
          </button>
        ) : null}
      </div>
      {phase === "starting" ? (
        <div className="fill-progress" data-testid="poster-progress">
          <Tag tone="none">포스터 만드는 중</Tag>
        </div>
      ) : null}
      {phase === "failed" && error ? (
        <p className="prose" data-testid="poster-error">
          {error.message}
        </p>
      ) : null}
      {result ? (
        <div className="fill-result" data-testid="poster-result" data-state={result.state}>
          <div className="fill-result-head">
            <span className="mono" data-testid="poster-state">
              {result.state}
            </span>
          </div>
          {result.preview ? (
            <div className="fill-sheet" data-testid="poster-preview">
              {result.preview.data ? (
                <img
                  src={`data:${result.preview.mediaType};base64,${result.preview.data}`}
                  alt={POSTER_PREVIEW_LABEL}
                />
              ) : null}
              <span className="fill-sheet-label">{POSTER_PREVIEW_LABEL}</span>
              <span className="mono fill-sheet-hash">{result.preview.sha256.slice(0, 12)}</span>
            </div>
          ) : null}
          <ul className="verify-checkers" data-testid="poster-checkers">
            {result.verify.map((row, index) => {
              const verdict = checkerVerdict(row);
              const counts = checkerCounts(row);
              const findings = checkerFindings(row);
              const reason = typeof row.reason === "string" ? row.reason : null;
              const key = String(row.checker ?? row.name ?? index);
              return (
                <li
                  key={`${key}-${index}`}
                  className="verify-checker"
                  data-testid={`poster-checker-${key}`}
                  data-verdict={verdict}
                >
                  <div className="verify-checker-head">
                    <span className="mono">{key}</span>
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
                      {findings.map((item, findingIndex) => (
                        <li key={`${item.code ?? "f"}-${findingIndex}`}>
                          {findingWhere(item)} · {item.msg ?? item.code ?? ""}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              );
            })}
          </ul>
          <ul className="fill-outputs" data-testid="poster-outputs">
            {result.outputs.map((row) => (
              <li key={row.role} data-testid={`poster-output-${row.role}`}>
                <span className="mono">{row.role}</span>
                <span className="mono">{row.sha256}</span>
                <span>{row.bytes} B</span>
              </li>
            ))}
          </ul>
          <p className="verify-footer" data-testid="poster-footer">
            {POSTER_FOOTER}
          </p>
        </div>
      ) : null}
    </div>
  );
}

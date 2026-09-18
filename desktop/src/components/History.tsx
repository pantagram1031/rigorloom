/**
 * 기록 — a checkpoint timeline: 원본, then each published candidate.
 *
 * Restore is a reverse plan through approve → apply. Receipts are the only
 * proof. Protocol chatter lives under a collapsed 이벤트 disclosure so the
 * three event lifetimes stay separate: document history here, shell protocol
 * activity in Timeline, provider events on the 에이전트 tab.
 */
import { useEffect } from "react";

import {
  compareInspectRefusals,
  exportApplied,
  loadReceipt,
  loadSessionEvents,
  restoreRun,
  runCompareInspect,
  selectHistory,
  setCompareAgainst,
  setCompareLeft,
  setCompareUseSelection,
  setHead,
} from "../actions";
import { relativeWhen } from "../label";
import {
  activeCandidates,
  headCandidate,
  lineage,
  reversedBy,
  useWorkspace,
} from "../store";
import type { Candidate, CandidateCompare } from "../types";
import { EmptyIconHistory, EmptyState } from "./EmptyState";
import { Icon } from "./Icon";
import { Tag } from "./Tag";
import { Timeline } from "./Timeline";

/** `2026-09-02T11:04:07Z` → `11:04:07`. The date is on the receipt. */
function clock(utc: string | undefined): string {
  if (!utc) return "";
  const at = utc.indexOf("T");
  return at < 0 ? utc : utc.slice(at + 1).replace(/Z$/, "");
}

function opSummary(row: Candidate): string {
  const kinds = row.opKinds ?? [];
  if (kinds.length === 0) return "작업 없음";
  const counted = new Map<string, number>();
  for (const kind of kinds) counted.set(kind, (counted.get(kind) ?? 0) + 1);
  return [...counted.entries()].map(([kind, n]) => `${kind} ${n}`).join(" · ");
}

function Row({
  row,
  depth,
  isHead,
  selected,
  undoneBy,
  backend,
  receiptPresent,
}: {
  row: Candidate;
  depth: number;
  isHead: boolean;
  selected: boolean;
  undoneBy: Candidate | null;
  backend: string | null;
  receiptPresent: boolean;
}) {
  const runId = row.runId ?? "";
  const undoPhase = useWorkspace((s) => s.undoPhase);
  return (
    <li
      className={`history-row checkpoint-row${selected ? " selected" : ""}${isHead ? " head is-head" : ""}`}
      data-testid={`history-${runId}`}
      data-depth={depth}
      style={{ paddingLeft: `calc(var(--s3) + ${Math.min(depth, 4)} * var(--s3))` }}
    >
      <span className="checkpoint-dot" aria-hidden="true">
        <Icon name={isHead ? "check" : "history"} />
      </span>
      <button
        className="history-head"
        data-testid={`history-select-${runId}`}
        aria-expanded={selected}
        aria-controls={selected ? `history-detail-${runId}` : undefined}
        aria-current={isHead ? "true" : undefined}
        onClick={() => selectHistory(selected ? null : runId)}
      >
        <span>{relativeWhen(row.createdUtc) || clock(row.createdUtc) || "후보본"}</span>
        {backend ? <Tag tone="none">{backend}</Tag> : null}
        {isHead ? (
          <Tag tone="ok" title="지금 이 후보본을 문서의 현재 상태로 보고 있습니다">
            현재
          </Tag>
        ) : null}
        {row.reverses ? (
          <Tag tone="warn" title={`되돌림 대상 ${row.reverses.runId.slice(0, 12)}`}>
            되돌리기
          </Tag>
        ) : null}
        {undoneBy ? (
          <Tag tone="none" title={`${undoneBy.runId?.slice(0, 12)} 이(가) 되돌렸습니다`}>
            되돌려짐
          </Tag>
        ) : null}
        {row.acceptance === true ? (
          <Tag tone="ok">검사 통과</Tag>
        ) : row.acceptance === false ? (
          <Tag tone="warn">검사 미통과</Tag>
        ) : (
          <Tag tone="none">검사 결과 없음</Tag>
        )}
        <span
          className={`receipt-dot${receiptPresent ? " is-on" : ""}`}
          title={receiptPresent ? "영수증 있음" : "영수증 없음"}
          data-testid={`history-receipt-dot-${runId}`}
        />
      </button>

      <details className="disclosure" data-testid={`history-facts-${runId}`}>
        <summary>기술 정보</summary>
        <p className="mono tiny">
          {opSummary(row)}
          {" · "}
          {row.base ? `이전 ${row.base.runId.slice(0, 12)} 위에` : "원본에서 바로"}
        </p>
        <p className="mono tiny" data-testid={`history-provenance-${runId}`}>
          run {runId.slice(0, 12)}
          {" · "}
          parent {row.base?.runId ? row.base.runId.slice(0, 12) : "source"}
          {" · "}
          backend {backend ?? "—"}
          {" · "}
          {receiptPresent ? "영수증 있음" : "영수증 없음"}
        </p>
      </details>

      <div className="checkpoint-actions">
        <button
          className="ghost dark-safe btn-icon"
          data-testid={`history-receipt-${runId}`}
          title="영수증"
          aria-label="자세히"
          onClick={() => void loadReceipt(runId)}
        >
          <Icon name="receipt" />
        </button>
        <button
          className="action btn-icon"
          data-testid={`history-restore-${runId}`}
          disabled={undoPhase === "starting"}
          title="되돌리는 계획을 제안합니다. 원본은 바뀌지 않습니다."
          aria-label="여기로 되돌리기"
          onClick={() => void restoreRun(runId)}
        >
          <Icon name="undo" />
        </button>
        <button
          className="ghost dark-safe btn-icon"
          data-testid={`history-compare-${runId}`}
          title="비교"
          aria-label="비교"
          onClick={() => setCompareLeft(runId)}
        >
          <Icon name="compare" />
        </button>
      </div>

      {selected ? (
        <div
          className="history-detail"
          id={`history-detail-${runId}`}
          data-testid={`history-detail-${runId}`}
        >
          <div className="gate-actions">
            <button
              className="ghost dark-safe"
              data-testid={`history-head-${runId}`}
              disabled={isHead}
              onClick={() => void setHead(runId)}
            >
              이 후보본을 현재로
            </button>
            <button
              className="ghost dark-safe"
              data-testid={`history-export-${runId}`}
              onClick={() => void exportApplied(undefined, runId)}
            >
              이 후보본 내보내기
            </button>
          </div>
        </div>
      ) : null}
    </li>
  );
}

function againstIsSource(against: { runId: string } | { source: true }): boolean {
  return "source" in against && against.source === true;
}

function CompareInspect({ rows }: { rows: Candidate[] }) {
  const leftRunId = useWorkspace(
    (s) => s.compareLeftRunId ?? s.historySelected ?? s.head,
  );
  const against = useWorkspace((s) => s.compareAgainst);
  const useSelection = useWorkspace((s) => s.compareUseSelection);
  const phase = useWorkspace((s) => s.comparePhase);
  const error = useWorkspace((s) => s.compareError);
  const result = useWorkspace((s) => s.compareResult);
  const receipts = useWorkspace((s) => s.receipts);
  const left = rows.find((row) => row.runId === leftRunId) ?? null;
  const receipt = leftRunId ? receipts[leftRunId] : undefined;
  const refusals = compareInspectRefusals({
    acceptance: left?.acceptance ?? receipt?.checks.acceptance,
    exitCodes: receipt?.steps.map((step) => step.exitCode),
    error,
  });

  return (
    <div className="receipt-block" data-testid="compare-inspect">
      <h4>비교</h4>
      <details className="disclosure">
        <summary>기술 정보</summary>
        <p className="prose tiny">
          candidate/compare 만 씁니다. verify/* 는 프로토콜에 없습니다.
        </p>
      </details>
      <p className="prose tiny">왼쪽 후보본</p>
      <div className="gate-actions">
        {rows.map((row) => (
          <button
            key={row.runId}
            className="ghost dark-safe"
            data-testid={`compare-left-${row.runId}`}
            aria-pressed={row.runId === leftRunId}
            onClick={() => setCompareLeft(row.runId ?? null)}
          >
            {(row.runId ?? "").slice(0, 12)}
          </button>
        ))}
      </div>
      <p className="prose tiny">비교 대상</p>
      <div className="gate-actions">
        <button
          className="ghost dark-safe"
          data-testid="compare-against-source"
          aria-pressed={againstIsSource(against)}
          onClick={() => setCompareAgainst({ source: true })}
        >
          원본
        </button>
        {rows
          .filter((row) => row.runId && row.runId !== leftRunId)
          .map((row) => (
            <button
              key={row.runId}
              className="ghost dark-safe"
              data-testid={`compare-against-${row.runId}`}
              aria-pressed={"runId" in against && against.runId === row.runId}
              onClick={() => setCompareAgainst({ runId: row.runId! })}
            >
              {(row.runId ?? "").slice(0, 12)}
            </button>
          ))}
      </div>
      <label className="prose tiny">
        <input
          type="checkbox"
          data-testid="compare-use-selection"
          checked={useSelection}
          onChange={(e) => setCompareUseSelection(e.target.checked)}
        />{" "}
        지금 고른 자리만
      </label>
      <div className="gate-actions">
        <button
          className="ghost dark-safe btn-icon"
          data-testid="compare-run"
          disabled={!leftRunId || phase === "starting"}
          onClick={() => void runCompareInspect()}
        >
          <Icon name="compare" />
          {phase === "starting" ? "비교 중…" : "비교"}
        </button>
      </div>

      {refusals.acceptanceRefused ? (
        <div className="refusal" data-testid="compare-acceptance-refusal">
          <Tag tone="warn">받아들일 수 없음</Tag>
          <p className="prose tiny">acceptance: false 는 통과가 아닙니다.</p>
        </div>
      ) : null}
      {refusals.exit3 ? (
        <div className="refusal" data-testid="compare-exit3-refusal">
          <Tag tone="bad">거절 exit 3</Tag>
          <p className="prose tiny">exit 3 은 성공으로 표시하지 않습니다.</p>
        </div>
      ) : null}
      {error ? (
        <div className="refusal" data-testid="compare-error">
          <Tag tone="bad">비교를 거절했습니다</Tag>
          <p className="prose">{error.message}</p>
          <p className="mono tiny">{error.code}</p>
        </div>
      ) : null}
      {result ? <ComparePayload compare={result} /> : null}
    </div>
  );
}

function ComparePayload({ compare }: { compare: CandidateCompare }) {
  return (
    <div data-testid="compare-payload">
      <div className="queue-verdict-head">
        {compare.regionsEqual === true ? (
          <Tag tone="ok">자리 글자 일치</Tag>
        ) : compare.regionsEqual === false ? (
          <Tag tone="bad">자리 글자 불일치</Tag>
        ) : (
          <Tag tone="none">자리를 비교하지 않음</Tag>
        )}
      </div>
      <p className="prose tiny">{compare.note}</p>
      <details className="disclosure" data-testid="compare-raw">
        <summary>기술 정보</summary>
        <p className="mono tiny" data-testid="compare-artifact-equal">
          파일 전체 해시 일치: {String(compare.artifactEqual)} · 비교 기준 {compare.normalizer}
        </p>
        <pre>{JSON.stringify(compare, null, 2)}</pre>
      </details>
    </div>
  );
}

export function History() {
  const rows = useWorkspace(activeCandidates);
  const head = useWorkspace(headCandidate);
  const selected = useWorkspace((s) => s.historySelected);
  const undoError = useWorkspace((s) => s.undoError);
  const proof = useWorkspace((s) => s.inverseProof);
  const sessionId = useWorkspace((s) => s.activeSessionId);
  const sourceHash = useWorkspace((s) => {
    const session = s.sessions?.find((row) => row.sessionId === s.activeSessionId);
    return session?.source?.sha256 ?? null;
  });
  const eventCount = useWorkspace((s) => s.events?.length ?? 0);
  const receipts = useWorkspace((s) => s.receipts);

  useEffect(() => {
    if (sessionId) void loadSessionEvents();
  }, [sessionId]);

  if (rows.length === 0 && !sourceHash) {
    return (
      <div className="section" data-testid="history-empty">
        <EmptyState
          icon={<EmptyIconHistory />}
          title="아직 후보본이 없습니다"
          body="승인하고 적용할 때마다 여기에 하나씩 쌓입니다."
        />
      </div>
    );
  }

  const ordered = lineage(rows);
  const depthOf = new Map<string, number>();
  for (const row of ordered) {
    const parent = row.base?.runId;
    const depth = parent && depthOf.has(parent) ? (depthOf.get(parent) ?? 0) + 1 : 0;
    if (row.runId) depthOf.set(row.runId, depth);
  }

  return (
    <div className="section history" data-testid="history">
      <h3 data-testid="history-heading">기록</h3>

      <ul className="history-rows checkpoint-list">
        {sourceHash ? (
          <li className="history-row checkpoint-row is-source" data-testid="history-source">
            <span className="checkpoint-dot" aria-hidden="true">
              <Icon name="open" />
            </span>
            <p className="history-head">
              <span>원본</span>
            </p>
            <details className="disclosure">
              <summary>기술 정보</summary>
              <p className="mono tiny" title={sourceHash}>
                {sourceHash.slice(0, 12)}
              </p>
            </details>
          </li>
        ) : null}
        {ordered.map((row) => (
          <Row
            key={row.runId ?? row.sha256}
            row={row}
            depth={depthOf.get(row.runId ?? "") ?? 0}
            isHead={!!row.runId && row.runId === head?.runId}
            selected={row.runId === selected}
            undoneBy={row.runId ? reversedBy(rows, row.runId) : null}
            backend={row.backend ?? receipts[row.runId ?? ""]?.backend ?? null}
            receiptPresent={Boolean(receipts[row.runId ?? ""] || row.receipt)}
          />
        ))}
      </ul>

      {rows.length > 0 ? <CompareInspect rows={rows} /> : null}

      <details className="disclosure history-events" data-testid="history-events">
        <summary>이벤트 ({eventCount})</summary>
        <Timeline />
      </details>

      {undoError ? (
        <div className="refusal" data-testid="undo-error">
          <Tag tone="bad">되돌리기를 만들지 못했습니다</Tag>
          <p className="prose">{undoError.message}</p>
          <p className="mono tiny">{undoError.code}</p>
        </div>
      ) : null}

      {proof ? (
        <div
          className={proof.compare.regionsEqual === true ? "queue-verdict" : "refusal"}
          data-testid="inverse-proof"
        >
          <div className="queue-verdict-head">
            {proof.compare.regionsEqual === true ? (
              <Tag tone="ok">되돌리기 확인됨</Tag>
            ) : proof.compare.regionsEqual === false ? (
              <Tag tone="bad">되돌아가지 않았습니다</Tag>
            ) : (
              <Tag tone="none">확인하지 못했습니다</Tag>
            )}
            <span className="count mono">{proof.runId.slice(0, 12)}</span>
          </div>
          <p className="prose">
            {proof.compare.regionsEqual === true
              ? `엔진이 ${proof.compare.regionsCompared}개 자리를 다시 읽어 되돌리기 이전 값과 같음을 확인했습니다.`
              : proof.compare.regionsEqual === false
                ? "다시 읽은 값이 되돌리기 이전 값과 다릅니다."
                : "비교할 수 있는 자리가 없었습니다."}
          </p>
          <details className="disclosure">
            <summary>기술 정보</summary>
            <p className="mono tiny" data-testid="inverse-proof-bytes">
              파일 전체 해시 일치: {String(proof.compare.artifactEqual)} · 비교 기준{" "}
              {proof.compare.normalizer}
            </p>
            <p className="prose tiny">글자는 되돌아가도 파일 바이트까지 같아지지는 않습니다.</p>
            <ul className="deferred">
              {proof.compare.regions.map((region) => (
                <li key={region.address} className="mono tiny">
                  {region.address} · {String(region.equal)} · {JSON.stringify(region.left)}
                </li>
              ))}
            </ul>
          </details>
        </div>
      ) : null}
    </div>
  );
}

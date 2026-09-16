/**
 * 기록 — the candidate chain, in lineage order, with what each one did.
 *
 * This panel is what makes undo something a person can reason about instead of
 * a button they have to trust. Four things it states rather than implies:
 *
 * 1. **Lineage, not a list.** Every row shows the candidate it was built ON.
 *    Before the runtime recorded a parent, two applies produced two siblings of
 *    the source and the second silently dropped the first edit — so a flat list
 *    here would be hiding exactly the fact this panel exists to show.
 * 2. **Which row reverses which.** `reverses` comes out of the receipt, so the
 *    arrow between an edit and its undo is a runtime fact, not a UI guess.
 * 3. **The head is a CHOICE.** The runtime keeps no head (§15.7): a chain can
 *    fork and it will publish both branches without complaint. So the head is
 *    the shell's, it is marked, and moving it is a deliberate click — never a
 *    silent switch that changes what the file on disk would be.
 * 4. **Selecting is reading.** Clicking a row shows it. It does not move the
 *    head, does not re-render the page as that candidate, and does not change
 *    what an export writes: export names its run explicitly, on this row.
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
import {
  activeCandidates,
  headCandidate,
  lineage,
  reversedBy,
  sessionHistory,
  useWorkspace,
} from "../store";
import type { Candidate, CandidateCompare } from "../types";
import { EmptyIconHistory, EmptyState } from "./EmptyState";
import { Tag } from "./Tag";

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
      className={`history-row${selected ? " selected" : ""}${isHead ? " head" : ""}`}
      data-testid={`history-${runId}`}
      data-depth={depth}
      style={{ paddingLeft: `calc(var(--s3) + ${Math.min(depth, 4) * 12}px)` }}
    >
      <button
        className="history-head"
        data-testid={`history-select-${runId}`}
        aria-expanded={selected}
        aria-controls={selected ? `history-detail-${runId}` : undefined}
        aria-current={isHead ? "true" : undefined}
        onClick={() => selectHistory(selected ? null : runId)}
      >
        <span className="mono">{runId.slice(0, 12)}</span>
        <span className="mono tiny">{clock(row.createdUtc)}</span>
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
      </button>

      <p className="mono tiny history-facts" data-testid={`history-facts-${runId}`}>
        {opSummary(row)}
        {" · "}
        {row.base
          ? `이전 ${row.base.runId.slice(0, 12)} 위에`
          : "원본에서 바로"}
        {" · "}
        {(row.sha256 ?? "").slice(0, 12)}
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

      {selected ? (
        <div
          className="history-detail"
          id={`history-detail-${runId}`}
          data-testid={`history-detail-${runId}`}
        >
          {/* The listing does not re-hash the artifact and says so; the receipt
              read below is the one that does, and its refusal is the answer
              that matters when bytes have drifted. */}
          <p className="prose tiny">
            이 목록의 해시는 영수증에 적힌 값을 읽어 온 것입니다. 바이트를 다시
            확인하는 것은 영수증 읽기 쪽이고, 어긋나면 그쪽이 거절합니다.
          </p>
          <div className="gate-actions">
            <button
              className="ghost dark-safe"
              data-testid={`history-receipt-${runId}`}
              onClick={() => void loadReceipt(runId)}
            >
              영수증 확인
            </button>
            <button
              className="ghost dark-safe"
              data-testid={`history-head-${runId}`}
              disabled={isHead}
              onClick={() => void setHead(runId)}
            >
              이 후보본을 현재로
            </button>
            <button
              className="action"
              data-testid={`history-restore-${runId}`}
              disabled={undoPhase === "starting"}
              title="이 후보본을 되돌리는 계획을 제안합니다. 승인하고 적용해야 후보본이 하나 더 생깁니다. 원본은 바꾸지 않습니다."
              onClick={() => void restoreRun(runId)}
            >
              되돌리기
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

function EventRow({
  at,
  seq,
  eventKind,
  runId,
  parent,
  backend,
  receiptPresent,
}: {
  at: string;
  seq: number | null;
  eventKind: string | null;
  runId: string | null;
  parent: string | null;
  backend: string | null;
  receiptPresent: boolean;
}) {
  const id = runId ?? `seq-${seq ?? at}`;
  return (
    <li className="history-row" data-testid={`history-event-${seq ?? id}`}>
      <p className="mono tiny">{eventKind ?? "event"} · {clock(at)}</p>
      <p className="mono tiny" data-testid={`history-provenance-${id}`}>
        run {runId ? runId.slice(0, 12) : "—"}
        {" · "}
        parent {parent ? parent.slice(0, 12) : "source"}
        {" · "}
        backend {backend ?? "—"}
        {" · "}
        {receiptPresent ? "영수증 있음" : "영수증 없음"}
      </p>
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
      <p className="prose tiny">
        런타임의 <span className="mono">candidate/compare</span> 만 씁니다.{" "}
        <span className="mono">verify/*</span> 는 프로토콜에 없습니다.
      </p>
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
          className="ghost dark-safe"
          data-testid="compare-run"
          disabled={!leftRunId || phase === "starting"}
          onClick={() => void runCompareInspect()}
        >
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
      <p className="mono tiny" data-testid="compare-artifact-equal">
        파일 전체 해시 일치: {String(compare.artifactEqual)} · 비교 기준 {compare.normalizer}
      </p>
      <p className="prose tiny">{compare.note}</p>
      <details className="disclosure" data-testid="compare-raw">
        <summary>비교 응답</summary>
        <pre>{JSON.stringify(compare, null, 2)}</pre>
      </details>
    </div>
  );
}

export function History() {
  const rows = useWorkspace(activeCandidates);
  const timeline = useWorkspace(sessionHistory);
  const head = useWorkspace(headCandidate);
  const selected = useWorkspace((s) => s.historySelected);
  const undoError = useWorkspace((s) => s.undoError);
  const proof = useWorkspace((s) => s.inverseProof);
  const sessionId = useWorkspace((s) => s.activeSessionId);

  useEffect(() => {
    if (sessionId) void loadSessionEvents();
  }, [sessionId]);

  if (timeline.length === 0) {
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
      <h3>
        기록
        <span className="count" data-testid="history-count">
          {timeline.length}
        </span>
      </h3>
      <p className="prose tiny">
        세션 사건과 공개된 후보본을 한 줄로 봅니다. 되돌리기는 원본을 고치는
        일이 아니라, 되돌리는 계획을 제안한 뒤 승인하고 적용하는 일입니다.
      </p>

      <ul className="history-rows">
        {timeline.map((item) =>
          item.candidate ? (
            <Row
              key={item.key}
              row={item.candidate}
              depth={depthOf.get(item.candidate.runId ?? "") ?? 0}
              isHead={!!item.candidate.runId && item.candidate.runId === head?.runId}
              selected={item.candidate.runId === selected}
              undoneBy={item.candidate.runId ? reversedBy(rows, item.candidate.runId) : null}
              backend={item.backend}
              receiptPresent={item.receiptPresent}
            />
          ) : (
            <EventRow
              key={item.key}
              at={item.at}
              seq={item.seq}
              eventKind={item.eventKind}
              runId={item.runId}
              parent={item.parent}
              backend={item.backend}
              receiptPresent={item.receiptPresent}
            />
          ),
        )}
      </ul>

      <CompareInspect rows={rows} />

      {undoError ? (
        <div className="refusal" data-testid="undo-error">
          <Tag tone="bad">되돌리기를 만들지 못했습니다</Tag>
          <p className="prose">{undoError.message}</p>
          <p className="mono tiny">{undoError.code}</p>
        </div>
      ) : null}

      {/* THE PROOF. The runtime's own answer, printed with both equalities
          apart: text restored is what an undo claims, and bytes restored is
          something an undo does not claim and normally cannot deliver — the
          engine rewrites and rezips. Drawing artifactEqual:false as a failure
          would be this panel inventing a defect. */}
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
              ? `런타임이 ${proof.compare.regionsCompared}개 자리를 다시 읽어 되돌리기 이전 값과 같음을 확인했습니다.`
              : proof.compare.regionsEqual === false
                ? "다시 읽은 값이 되돌리기 이전 값과 다릅니다. 이 후보본은 되돌리기가 아닙니다."
                : "비교할 수 있는 자리가 없었습니다. 이것은 통과가 아닙니다."}
          </p>
          <p className="mono tiny" data-testid="inverse-proof-bytes">
            파일 전체 해시 일치: {String(proof.compare.artifactEqual)} · 비교 기준{" "}
            {proof.compare.normalizer}
          </p>
          <p className="prose tiny">
            글자는 되돌아가도 파일 바이트까지 같아지지는 않습니다. 편집기가 XML을
            다시 쓰고 다시 압축하기 때문이고, 되돌리기가 실패했다는 뜻이 아닙니다.
          </p>
          <details className="disclosure">
            <summary>런타임이 비교한 자리</summary>
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

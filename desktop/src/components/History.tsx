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
import {
  exportApplied,
  loadReceipt,
  proposeUndoOf,
  selectHistory,
  setHead,
} from "../actions";
import {
  activeCandidates,
  headCandidate,
  lineage,
  reversedBy,
  useWorkspace,
} from "../store";
import type { Candidate } from "../types";
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
}: {
  row: Candidate;
  depth: number;
  isHead: boolean;
  selected: boolean;
  undoneBy: Candidate | null;
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

      {selected ? (
        <div className="history-detail" data-testid={`history-detail-${runId}`}>
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
              data-testid={`history-undo-${runId}`}
              disabled={undoPhase === "starting"}
              title="이 후보본이 한 일을 되돌리는 계획을 대기열에 냅니다. 지우지 않습니다."
              onClick={() => void proposeUndoOf(runId)}
            >
              되돌리기 제안
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

export function History() {
  const rows = useWorkspace(activeCandidates);
  const head = useWorkspace(headCandidate);
  const selected = useWorkspace((s) => s.historySelected);
  const undoError = useWorkspace((s) => s.undoError);
  const proof = useWorkspace((s) => s.inverseProof);

  if (rows.length === 0) {
    return (
      <div className="section" data-testid="history-empty">
        <h3>기록</h3>
        <p className="prose">
          아직 만들어진 후보본이 없습니다. 승인하고 적용할 때마다 여기에 하나씩
          쌓이고, 지워지는 것은 없습니다.
        </p>
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
          {rows.length}
        </span>
      </h3>
      <p className="prose tiny">
        적용할 때마다 후보본이 하나씩 늘어납니다. 되돌리기도 후보본을 하나 더
        만드는 일이지, 무언가를 지우는 일이 아닙니다.
      </p>

      <ul className="history-rows">
        {ordered.map((row) => (
          <Row
            key={row.runId}
            row={row}
            depth={depthOf.get(row.runId ?? "") ?? 0}
            isHead={!!row.runId && row.runId === head?.runId}
            selected={row.runId === selected}
            undoneBy={row.runId ? reversedBy(rows, row.runId) : null}
          />
        ))}
      </ul>

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

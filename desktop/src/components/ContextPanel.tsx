/**
 * Document view, right column: what is true about the current selection.
 *
 * The agent panel proper is the next slice. This phase shows the honest
 * precursor — the selection's own facts, and a statement of what the agent
 * surface will be and is not yet. It does not mock a conversation.
 */
import { useEffect } from "react";

import { beginEdit } from "../actions";
import {
  inspectorAgentUnread,
  inspectorHistoryBadge,
  markAgentTurnsSeen,
  markHistoryCandidatesSeen,
  selectInspectorTab,
  selectionId,
  useWorkspace,
  visibleInspectorTab,
  type InspectorTab,
  type Selection,
} from "../store";
import type { InspectResult, RegionText } from "../types";
import { Composer } from "./Composer";
import { Conversation } from "./Conversation";
import { DocumentContext } from "./DocumentContext";
import { History } from "./History";
import { ApproveAllButton, ReviewQueue } from "./ReviewQueue";
import { CLASSIFICATION_LABEL, Tag } from "./Tag";

function Fact({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <>
      <dt>{k}</dt>
      <dd>{v}</dd>
    </>
  );
}

function formatRegionAddress(address: {
  table?: number;
  row?: number;
  col?: number;
  atPara?: number;
}): string {
  if (address.atPara !== undefined) return `at_para ${address.atPara}`;
  if (address.row !== undefined && address.col !== undefined) {
    return `표 ${address.table ?? 0} R${address.row}C${address.col}`;
  }
  return "";
}

function RegionRuns({ runs }: { runs: NonNullable<RegionText["runs"]> }) {
  return (
    <ul className="deferred" data-testid="region-source-runs">
      {runs.map((run) => (
        <li key={run.index} className="mono tiny">
          #{run.index}
          {run.charpr ? ` · charPr ${run.charpr}` : ""}
          {": "}
          {run.text}
        </li>
      ))}
    </ul>
  );
}

/**
 * Exact document/readRegion text for the tree selection.
 *
 * Always a display: no input, so no IME composition guard belongs here.
 * Approve/apply gating stays on the review queue. Forbidden rows never mount
 * an edit control.
 */
function RegionSourceSection() {
  const source = useWorkspace((s) => s.selectedRegionSource);
  if (!source) return null;
  const forbidden = source.access === "forbidden";
  const editable = source.access === "editable";
  const text = source.region?.text ?? "";
  const accessLabel =
    source.access === "editable" ? "가능" : source.access === "forbidden" ? "금지" : "읽기 전용";
  return (
    <div
      className="section"
      data-testid="region-source"
      data-editable={editable ? "true" : "false"}
      data-forbidden={forbidden ? "true" : "false"}
      data-phase={source.phase}
    >
      <h3>자리 원문</h3>
      <dl className="kv">
        <Fact
          k="주소"
          v={
            <span className="mono" data-testid="region-source-address">
              {formatRegionAddress(source.address)}
            </span>
          }
        />
        <Fact
          k="쓰기"
          v={
            <Tag tone={forbidden ? "bad" : editable ? "fill" : "none"}>{accessLabel}</Tag>
          }
        />
      </dl>
      {source.phase === "starting" ? (
        <p className="empty">이 자리의 글을 읽는 중입니다.</p>
      ) : source.error ? (
        <p className="prose" data-testid="region-source-error">
          {source.error.message}
        </p>
      ) : !source.region ? (
        <p className="empty" data-testid="region-source-missing">
          런타임이 이 자리의 글을 돌려주지 않았습니다. 없는 자리를 만들지 않습니다.
        </p>
      ) : forbidden ? (
        <div data-testid="region-source-forbidden">
          <p className="prose" style={{ userSelect: "text", color: "var(--fg)" }}>
            {text || "(빈 자리)"}
          </p>
          {source.region.runs && source.region.runs.length > 0 ? (
            <RegionRuns runs={source.region.runs} />
          ) : null}
        </div>
      ) : (
        <div data-testid="region-source-text">
          <p className="prose" style={{ userSelect: "text", color: "var(--fg)" }}>
            {text || "(빈 자리)"}
          </p>
          {source.region.runs && source.region.runs.length > 0 ? (
            <RegionRuns runs={source.region.runs} />
          ) : null}
        </div>
      )}
    </div>
  );
}

function CellDetail({ inspect, sel }: { inspect: InspectResult; sel: Extract<Selection, { kind: "cell" }> }) {
  const table = inspect.graph.tables.find((t) => t.index === sel.table);
  const cell = table?.cells.find((c) => c.addr.row === sel.row && c.addr.col === sel.col);
  if (!cell) {
    return <p className="empty">이 주소의 칸을 문서 그래프에서 찾지 못했습니다.</p>;
  }
  const seat = inspect.regions.regions.find(
    (r) => r.kind === "cell" && r.table === sel.table && r.row === sel.row && r.col === sel.col,
  );
  return (
    <>
      <div className="section">
        <h3>칸 {`표 ${sel.table} R${sel.row}C${sel.col}`}</h3>
        <dl className="kv">
          <Fact
            k="분류"
            v={
              <Tag tone={cell.classification === "fill_target" ? "fill" : "none"}>
                {CLASSIFICATION_LABEL[cell.classification] ?? cell.classification}
              </Tag>
            }
          />
          {cell.spacerPattern ? <Fact k="여백 형태" v={cell.spacerPattern} /> : null}
          {cell.charPr ? <Fact k="charPr" v={cell.charPr} /> : null}
          {cell.charPrSuggested ? <Fact k="권장 charPr" v={cell.charPrSuggested} /> : null}
        </dl>
      </div>

      {cell.textPreview ? (
        <div className="section">
          <h3>미리보기{cell.truncated ? " (잘림)" : ""}</h3>
          <p className="prose" style={{ userSelect: "text" }}>
            {cell.textPreview}
          </p>
          {cell.truncated ? (
            <p className="empty" style={{ padding: "var(--s2) 0 0" }}>
              전체 글자는 요청해야 옵니다. 구조만 보내는 것이 기본값입니다.
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="section">
        <h3>쓰기 전 확인</h3>
        {seat ? (
          <dl className="kv">
            <Fact
              k="색 이상"
              v={
                seat.colorAnomaly ? (
                  <Tag tone="bad">있음</Tag>
                ) : seat.colorAnomaly === false ? (
                  <Tag tone="ok">없음</Tag>
                ) : (
                  <Tag tone="none">판단 불가</Tag>
                )
              }
            />
            <Fact
              k="글자속성 이상"
              v={
                seat.scriptAnomaly ? (
                  <Tag tone="warn">있음</Tag>
                ) : seat.scriptAnomaly === false ? (
                  <Tag tone="ok">없음</Tag>
                ) : (
                  <Tag tone="none">판단 불가</Tag>
                )
              }
            />
          </dl>
        ) : (
          <p className="prose">
            이 칸은 값을 넣는 자리가 아닙니다. 쓰기 전 확인은 채움 자리에만 붙습니다.
          </p>
        )}
        {seat?.colorAnomaly ? (
          <p className="prose" style={{ color: "var(--bad)", marginTop: "var(--s2)" }}>
            글자색이 본문 기준과 다릅니다. 이대로 채우면 색이 남습니다.
          </p>
        ) : null}
        {seat ? (
          <button
            className="action primary"
            data-testid="edit-seat"
            style={{ marginTop: "var(--s3)" }}
            onClick={() => beginEdit(sel.table, sel.row, sel.col)}
          >
            이 자리에 값 넣기
          </button>
        ) : null}
      </div>
    </>
  );
}

function ParagraphDetail({ inspect, atPara }: { inspect: InspectResult; atPara: number }) {
  const para = inspect.graph.paragraphs.find((p) => p.at_para === atPara);
  if (!para) return <p className="empty">이 문단을 찾지 못했습니다.</p>;
  const removal = inspect.summary.removalTargets.find((t) => t.para_idx === para.para_idx);
  return (
    <>
      <div className="section">
        <h3>문단 at_para {para.at_para}</h3>
        <dl className="kv">
          <Fact k="구역" v={para.section} />
          <Fact k="para_idx" v={String(para.para_idx)} />
          {removal ? <Fact k="삭제 후보" v={`확신도 ${removal.confidence}`} /> : null}
        </dl>
      </div>
      <div className="section">
        <h3>본문</h3>
        <p className="prose" style={{ userSelect: "text", color: "var(--fg)" }}>
          {para.text || "(빈 문단)"}
        </p>
      </div>
    </>
  );
}

const TABS: { id: InspectorTab; label: string }[] = [
  { id: "selection", label: "선택" },
  { id: "review", label: "검토" },
  { id: "history", label: "기록" },
  { id: "agent", label: "에이전트" },
];

function SelectionPane({ inspect }: { inspect: InspectResult | null }) {
  const selection = useWorkspace((s) => s.selection);
  if (!inspect || !selection) {
    return (
      <p className="empty">
        왼쪽에서 문단이나 표의 칸을 고르면 그 자리에 대해 아는 것을 여기에 모아
        보여 줍니다.
      </p>
    );
  }
  if (selection.kind === "cell") {
    return (
      <>
        <RegionSourceSection />
        <CellDetail inspect={inspect} sel={selection} />
      </>
    );
  }
  if (selection.kind === "paragraph") {
    return (
      <>
        <RegionSourceSection />
        <ParagraphDetail inspect={inspect} atPara={selection.atPara} />
      </>
    );
  }
  return (
    <div className="section">
      <h3>표 {selection.table}</h3>
      <dl className="kv">
        <Fact
          k="칸"
          v={String(
            inspect.graph.tables.find((t) => t.index === selection.table)?.cells.length ?? 0,
          )}
        />
      </dl>
    </div>
  );
}

export function ContextPanel({ inspect }: { inspect: InspectResult | null }) {
  const selection = useWorkspace((s) => s.selection);
  const tab = useWorkspace((s) =>
    typeof visibleInspectorTab === "function" ? visibleInspectorTab(s) : "selection",
  );
  const reviewCount = useWorkspace((s) => s.draft?.ops?.length ?? 0);
  const reviewPending = useWorkspace((s) => s.approvalPhase === "pending");
  const historyCount = useWorkspace((s) =>
    typeof inspectorHistoryBadge === "function" ? inspectorHistoryBadge(s) : 0,
  );
  const agentUnread = useWorkspace((s) =>
    typeof inspectorAgentUnread === "function" ? inspectorAgentUnread(s) : 0,
  );
  const turnCount = useWorkspace((s) => s.turns?.length ?? 0);
  const candidateCount = useWorkspace((s) =>
    s.activeSessionId ? (s.candidates?.[s.activeSessionId] ?? []).length : 0,
  );
  const id = selectionId(selection);

  useEffect(() => {
    if (tab === "agent" && typeof markAgentTurnsSeen === "function") markAgentTurnsSeen();
  }, [tab, turnCount]);

  useEffect(() => {
    if (tab === "history" && typeof markHistoryCandidatesSeen === "function") {
      markHistoryCandidatesSeen();
    }
  }, [tab, candidateCount]);

  function onTabListKey(e: React.KeyboardEvent<HTMLDivElement>) {
    const idx = TABS.findIndex((row) => row.id === tab);
    if (idx < 0) return;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      e.preventDefault();
      if (typeof selectInspectorTab === "function") {
        selectInspectorTab(TABS[(idx + 1) % TABS.length]!.id);
      }
    } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
      e.preventDefault();
      if (typeof selectInspectorTab === "function") {
        selectInspectorTab(TABS[(idx - 1 + TABS.length) % TABS.length]!.id);
      }
    } else if (e.key === "Home") {
      e.preventDefault();
      if (typeof selectInspectorTab === "function") selectInspectorTab(TABS[0]!.id);
    } else if (e.key === "End") {
      e.preventDefault();
      if (typeof selectInspectorTab === "function") {
        selectInspectorTab(TABS[TABS.length - 1]!.id);
      }
    }
  }

  return (
    <aside className="panel inspector" aria-label="검사기" data-testid="context-panel">
      <div
        className="inspector-tabs"
        role="tablist"
        aria-label="검사기"
        data-testid="inspector-tabs"
        onKeyDown={onTabListKey}
      >
        {TABS.map((row) => {
          const selected = tab === row.id;
          let badge: React.ReactNode = null;
          if (row.id === "review") {
            badge = (
              <>
                {reviewCount > 0 ? (
                  <span className="tab-badge" data-testid="badge-review">
                    {reviewCount}
                  </span>
                ) : null}
                {reviewPending ? (
                  <span
                    className="tab-badge-dot"
                    data-testid="badge-review-pending"
                    title="승인 대기"
                  />
                ) : null}
              </>
            );
          } else if (row.id === "history" && historyCount > 0) {
            badge = (
              <span className="tab-badge" data-testid="badge-history">
                {historyCount}
              </span>
            );
          } else if (row.id === "agent" && agentUnread > 0) {
            badge = (
              <span className="tab-badge" data-testid="badge-agent">
                {agentUnread}
              </span>
            );
          }
          return (
            <button
              key={row.id}
              type="button"
              role="tab"
              id={`inspector-tab-${row.id}`}
              aria-selected={selected}
              aria-controls={`inspector-panel-${row.id}`}
              tabIndex={selected ? 0 : -1}
              data-testid={`inspector-tab-${row.id}`}
              onClick={() => {
                if (typeof selectInspectorTab === "function") selectInspectorTab(row.id);
              }}
            >
              {row.label}
              {badge}
            </button>
          );
        })}
      </div>
      <div className="panel-head inspector-head">
        <span className="panel-title">
          {tab === "selection"
            ? "선택 항목"
            : tab === "review"
              ? "검토"
              : tab === "history"
                ? "기록"
                : "에이전트"}
        </span>
        {tab === "selection" ? (
          <span className="count" data-testid="selection-id">
            {id}
          </span>
        ) : null}
        {tab === "review" ? <ApproveAllButton /> : null}
      </div>
      <div
        className={`panel-body inspector-body${tab === "agent" ? " is-agent" : ""}`}
        role="tabpanel"
        id={`inspector-panel-${tab}`}
        aria-labelledby={`inspector-tab-${tab}`}
        data-testid="inspector-panel"
        data-tab={tab}
      >
        {tab === "selection" ? <SelectionPane inspect={inspect} /> : null}
        {tab === "review" ? <ReviewQueue /> : null}
        {tab === "history" ? <History /> : null}
        {tab === "agent" ? (
          <>
            <DocumentContext />
            <Conversation />
            <Composer />
          </>
        ) : null}
      </div>
    </aside>
  );
}

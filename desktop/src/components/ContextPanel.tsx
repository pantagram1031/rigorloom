/**
 * Document view, right column: what is true about the current selection.
 *
 * The agent panel proper is the next slice. This phase shows the honest
 * precursor — the selection's own facts, and a statement of what the agent
 * surface will be and is not yet. It does not mock a conversation.
 */
import { useEffect } from "react";

import { beginEdit, bindFormToActiveDocument, needsBoundFormHint } from "../actions";
import { humanCellAddress, humanSelectionLabel, humanTableLabel, machineTableIndex, seatStateLine } from "../label";
import {
  inspectorAgentUnread,
  inspectorHistoryBadge,
  markAgentTurnsSeen,
  markHistoryCandidatesSeen,
  selectInspectorTab,
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
import { Icon } from "./Icon";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../ui/Collapsible";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../ui/Tabs";
import { Tooltip } from "../ui/Tooltip";

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
  if (address.atPara !== undefined) return `문단 ${address.atPara}`;
  if (address.row !== undefined && address.col !== undefined) {
    return humanCellAddress(address.table ?? 0, address.row, address.col);
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
              {source.address.atPara !== undefined ? (
                <Tooltip content={`at_para ${source.address.atPara}`}>
                  <span>{formatRegionAddress(source.address)}</span>
                </Tooltip>
              ) : (
                formatRegionAddress(source.address)
              )}
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
          <p className="prose selectable">
            {text || "(빈 자리)"}
          </p>
          {source.region.runs && source.region.runs.length > 0 ? (
            <Collapsible className="disclosure">
        <CollapsibleTrigger>기술 정보</CollapsibleTrigger>
        <CollapsibleContent>
<RegionRuns runs={source.region.runs} />
      </CollapsibleContent>
      </Collapsible>
          ) : null}
        </div>
      ) : (
        <div data-testid="region-source-text">
          <p className="prose selectable">
            {text || "(빈 자리)"}
          </p>
          {source.region.runs && source.region.runs.length > 0 ? (
            <Collapsible className="disclosure">
        <CollapsibleTrigger>기술 정보</CollapsibleTrigger>
        <CollapsibleContent>
<RegionRuns runs={source.region.runs} />
      </CollapsibleContent>
      </Collapsible>
          ) : null}
        </div>
      )}
    </div>
  );
}

function CellDetail({ inspect, sel }: { inspect: InspectResult; sel: Extract<Selection, { kind: "cell" }> }) {
  const source = useWorkspace((s) => s.selectedRegionSource);
  const table = inspect.graph.tables.find((t) => t.index === sel.table);
  const cell = table?.cells.find((c) => c.addr.row === sel.row && c.addr.col === sel.col);
  if (!cell) {
    return <p className="empty">이 주소의 칸을 문서 그래프에서 찾지 못했습니다.</p>;
  }
  const seat = inspect.regions.regions.find(
    (r) => r.kind === "cell" && r.table === sel.table && r.row === sel.row && r.col === sel.col,
  );
  const text =
    (source?.region &&
    source.address.row === sel.row &&
    source.address.col === sel.col
      ? source.region.text
      : null) ??
    cell.textPreview ??
    "";
  const stateLine = seatStateLine({
    text,
    scriptAnomaly: seat?.scriptAnomaly === true,
  });
  return (
    <>
      <div className="section" data-testid="seat-pane">
        <h3 data-testid="seat-title">{humanCellAddress(sel.table, sel.row, sel.col)}</h3>
        <p className="prose" data-testid="seat-state">
          {stateLine}
        </p>
        {seat ? (
          <Button
            variant="primary"
            className="stack-s3"
            data-testid="edit-seat"
            onClick={() => beginEdit(sel.table, sel.row, sel.col)}
          >
            값 넣기
          </Button>
        ) : (
          <p className="prose">이 칸은 값을 넣는 자리가 아닙니다.</p>
        )}
        <Collapsible className="disclosure">
        <CollapsibleTrigger>기술 정보</CollapsibleTrigger>
        <CollapsibleContent>
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
            {cell.charPr ? <Fact k="글자 모양" v={cell.charPr} /> : null}
            {cell.charPrSuggested ? <Fact k="권장 글자 모양" v={cell.charPrSuggested} /> : null}
            {seat ? (
              <>
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
              </>
            ) : null}
          </dl>
      </CollapsibleContent>
      </Collapsible>
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
        <h3>문단 {para.at_para}</h3>
        <dl className="kv">
          <Fact k="구역" v={para.section} />
          {removal ? <Fact k="삭제 후보" v={`확신도 ${removal.confidence}`} /> : null}
        </dl>
        <Collapsible className="disclosure">
        <CollapsibleTrigger>기술 정보</CollapsibleTrigger>
        <CollapsibleContent>
<dl className="kv">
            <Fact k="문단 번호" v={String(para.para_idx)} />
          </dl>
      </CollapsibleContent>
      </Collapsible>
      </div>
      <div className="section">
        <h3>본문</h3>
        <p className="prose selectable">
          {para.text || "(빈 문단)"}
        </p>
      </div>
    </>
  );
}

const TABS: { id: InspectorTab; label: string; icon: "cell" | "list" | "history" | "bot" }[] = [
  { id: "selection", label: "선택", icon: "cell" },
  { id: "review", label: "검토", icon: "list" },
  { id: "history", label: "기록", icon: "history" },
  { id: "agent", label: "에이전트", icon: "bot" },
];

function SelectionPane({ inspect }: { inspect: InspectResult | null }) {
  const selection = useWorkspace((s) => s.selection);
  if (!inspect || !selection) {
    return (
      <p className="empty" data-testid="center-caveat">
        입력 칸을 누르면 값을 넣을 수 있습니다. 승인 전에는 문서가 바뀌지 않습니다.
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
      <h3>{humanTableLabel(selection.table)}</h3>
      <dl className="kv">
        <Fact
          k="칸"
          v={String(
            inspect.graph.tables.find((t) => t.index === selection.table)?.cells.length ?? 0,
          )}
        />
      </dl>
      <Collapsible className="disclosure">
        <CollapsibleTrigger>기술 정보</CollapsibleTrigger>
        <CollapsibleContent>
<dl className="kv">
          <Fact k="table" v={machineTableIndex(selection.table)} />
        </dl>
      </CollapsibleContent>
      </Collapsible>
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
  const providerId = useWorkspace((s) => s.provider?.provider ?? null);
  const candidateCount = useWorkspace((s) =>
    s.activeSessionId ? (s.candidates?.[s.activeSessionId] ?? []).length : 0,
  );

  useEffect(() => {
    if (tab === "agent" && typeof markAgentTurnsSeen === "function") markAgentTurnsSeen();
  }, [tab, turnCount]);

  useEffect(() => {
    if (tab === "history" && typeof markHistoryCandidatesSeen === "function") {
      markHistoryCandidatesSeen();
    }
  }, [tab, candidateCount]);

  return (
    <aside className="panel inspector" aria-label="패널" data-testid="context-panel">
      <Tabs
        className="inspector-chrome"
        value={tab}
        defaultValue="selection"
        onValueChange={(v) => {
          if (typeof selectInspectorTab === "function") selectInspectorTab(v as InspectorTab);
        }}
      >
      <TabsList className="inspector-tabs" aria-label="패널" data-testid="inspector-tabs">
        {TABS.map((row) => {
          let badge: React.ReactNode = null;
          if (row.id === "review") {
            badge = (
              <>
                {reviewCount > 0 ? (
                  <Badge variant="secondary" className="tab-badge" data-testid="badge-review">
                    {reviewCount}
                  </Badge>
                ) : null}
                {reviewPending ? (
                  <Tooltip content="승인 대기">
                    <span className="tab-badge-dot" data-testid="badge-review-pending" />
                  </Tooltip>
                ) : null}
              </>
            );
          } else if (row.id === "history" && historyCount > 0) {
            badge = (
              <Badge variant="secondary" className="tab-badge" data-testid="badge-history">
                {historyCount}
              </Badge>
            );
          } else if (row.id === "agent" && agentUnread > 0) {
            badge = (
              <Badge variant="secondary" className="tab-badge" data-testid="badge-agent">
                {agentUnread}
              </Badge>
            );
          }
          return (
            <TabsTrigger key={row.id} value={row.id} data-testid={`inspector-tab-${row.id}`}>
              <Icon name={row.icon} />
              {row.label}
              {badge}
            </TabsTrigger>
          );
        })}
      </TabsList>
      <div className="panel-head inspector-head">
        <span className="panel-title" data-testid={tab === "history" ? "history-heading" : undefined}>
          {tab === "selection"
            ? "선택"
            : tab === "review"
              ? "검토"
              : tab === "history"
                ? "기록"
                : "에이전트"}
        </span>
        {tab === "selection" ? (
          <span className="count" data-testid="selection-id">
            {humanSelectionLabel(selection)}
          </span>
        ) : null}
        {tab === "review" ? <ApproveAllButton /> : null}
        {tab === "agent" && providerId ? (
          <span className="tiny dim" data-testid="composer-provider">
            {providerId}
          </span>
        ) : null}
      </div>
      {tab === "review" && needsBoundFormHint(inspect) ? (
        <div className="form-bind-hint" data-testid="form-bind-hint">
          <p>
            이 문서는 완성본으로 보입니다. 양식을 연결하면 검사 판정이 정확해집니다
          </p>
          <Button
            variant="ghost"
            className="btn-icon"
            data-testid="review-bind-form"
            onClick={() => void bindFormToActiveDocument()}
          >
            <Icon name="link" />
            양식 연결
          </Button>
        </div>
      ) : null}
      <TabsContent
        value="selection"
        className="panel-body inspector-body inspector-pane"
        data-testid="inspector-panel"
        data-tab="selection"
      >
        <SelectionPane inspect={inspect} />
      </TabsContent>
      <TabsContent
        value="review"
        className="panel-body inspector-body inspector-pane"
        data-testid="inspector-panel"
        data-tab="review"
      >
        <ReviewQueue />
      </TabsContent>
      <TabsContent
        value="history"
        className="panel-body inspector-body inspector-pane"
        data-testid="inspector-panel"
        data-tab="history"
      >
        <History />
      </TabsContent>
      <TabsContent
        value="agent"
        className="panel-body inspector-body inspector-pane is-agent"
        data-testid="inspector-panel"
        data-tab="agent"
      >
        <DocumentContext />
        <Conversation />
        <Composer />
      </TabsContent>
      </Tabs>
    </aside>
  );
}

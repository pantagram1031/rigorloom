/**
 * The document's structure, from real `document/inspect` data.
 *
 * Primary groups are an outline: 표, 입력 칸, 안내문. Forbidden inventory and
 * capability gaps live under 기술 정보. Addresses are 1-based human rows.
 */
import { useMemo } from "react";

import { selectStructureNode } from "../actions";
import { humanCellAddress, humanTableLabel, trimLabel } from "../label";
import {
  selectionId,
  toggleExpanded,
  useWorkspace,
  type Selection,
} from "../store";
import type { Capabilities, EditableRegion, ForbiddenInventory, InspectResult } from "../types";
import { Icon } from "./Icon";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../ui/Collapsible";
import { Tooltip } from "../ui/Tooltip";

type SeatState = "empty" | "filled" | "anomaly";

function seatState(input: {
  text?: string | null;
  colorAnomaly?: boolean;
  scriptAnomaly?: boolean;
}): { kind: SeatState; label: string } {
  if (input.colorAnomaly || input.scriptAnomaly) {
    return { kind: "anomaly", label: "글자속성 이상" };
  }
  const text = (input.text ?? "").replace(/\s+/g, " ").trim();
  if (!text) return { kind: "empty", label: "빈 칸" };
  return { kind: "filled", label: "값 있음" };
}

function charPrTitle(charPr?: string, suggested?: string): string | undefined {
  if (!charPr && !suggested) return undefined;
  if (charPr && suggested && charPr !== suggested) return `charPr ${charPr} → ${suggested}`;
  if (charPr) return `charPr ${charPr}`;
  return `charPr ${suggested}`;
}

function Row({
  id,
  depth,
  label,
  hint,
  preview,
  previewEmpty,
  title,
  state,
  selection,
  expandable,
  expanded,
  testId,
  editable,
}: {
  id: string;
  depth: 0 | 1 | 2;
  label: string;
  hint?: string;
  preview?: string;
  previewEmpty?: boolean;
  title?: string;
  state?: { kind: SeatState; label: string };
  selection?: Selection;
  expandable?: boolean;
  expanded?: boolean;
  testId?: string;
  /** Set only from inspect: fill seats / fill_target true; forbidden never. */
  editable?: boolean;
}) {
  const current = useWorkspace((s) => selectionId(s.selection));
  const selected = selection ? selectionId(selection) === current : false;
  const row = (
    <button
      className={`node depth-${depth}`}
      role="treeitem"
      aria-selected={selected}
      aria-expanded={expandable ? expanded : undefined}
      data-node-id={id}
      data-testid={testId}
      data-editable={editable === undefined ? undefined : editable ? "true" : "false"}
      onClick={() => {
        if (expandable) toggleExpanded(id);
        if (selection !== undefined) selectStructureNode(selection);
      }}
    >
      <span className="twisty">
        {expandable ? <Icon name={expanded ? "chevron-down" : "chevron-right"} /> : null}
      </span>
      <span className="label">
        {label}
        {preview != null ? (
          <span className={`dim${previewEmpty ? " is-empty" : ""}`}>　{preview}</span>
        ) : hint ? (
          <span className="dim">　{hint}</span>
        ) : null}
      </span>
      {state ? (
        <Tooltip content={state.label}>
          <span className={`state-dot is-${state.kind}`} />
        </Tooltip>
      ) : null}
    </button>
  );
  if (!title) return row;
  return <Tooltip content={title}>{row}</Tooltip>;
}

function forbiddenSelection(
  atPara: number | null | undefined,
): Selection | undefined {
  if (typeof atPara !== "number") return undefined;
  return { kind: "paragraph", atPara };
}

function ForbiddenRows({
  forbidden,
}: {
  forbidden: ForbiddenInventory;
}) {
  const count =
    forbidden.counts.anchors +
    forbidden.counts.placeholders +
    forbidden.counts.removalTargets;
  return (
    <>
      <div className="group-head" data-testid="forbidden-group">
        <span className="group-label">금지</span>
        <span className="count">{count}</span>
      </div>
      {forbidden.anchors.map((anchor, i) => (
        <Row
          key={`forbidden-anchor-${i}`}
          id={`forbidden:anchor:${i}`}
          depth={0}
          label={trimLabel(anchor.text || "(앵커)")}
          hint={
            typeof anchor.atPara === "number" ? `at_para ${anchor.atPara}` : "주소 없음"
          }
          selection={forbiddenSelection(anchor.atPara)}
          testId={`forbidden-anchor-${i}`}
          editable={false}
        />
      ))}
      {forbidden.placeholders.map((placeholder, i) => (
        <Row
          key={`forbidden-placeholder-${i}`}
          id={`forbidden:placeholder:${i}`}
          depth={0}
          label={trimLabel(placeholder.text || "(자리표시)")}
          testId={`forbidden-placeholder-${i}`}
          editable={false}
        />
      ))}
      {forbidden.removalTargets.map((target, i) => (
        <Row
          key={`forbidden-removal-${i}`}
          id={`forbidden:removal:${i}`}
          depth={0}
          label={trimLabel(target.text || target.reason || "(제거 대상)")}
          hint={
            typeof target.atPara === "number" ? `at_para ${target.atPara}` : undefined
          }
          selection={forbiddenSelection(target.atPara)}
          testId={`forbidden-removal-${i}`}
          editable={false}
        />
      ))}
      {forbidden.note ? <p className="empty">{forbidden.note}</p> : null}
    </>
  );
}

function seatPreview(region: EditableRegion, inspect: InspectResult): string {
  if (region.kind === "cell" && region.table !== undefined) {
    const table = inspect.graph.tables.find((row) => row.index === region.table);
    const cell = table?.cells.find(
      (item) => item.addr.row === region.row && item.addr.col === region.col,
    );
    return (cell?.textPreview ?? "").replace(/\s+/g, " ").trim();
  }
  if (region.atPara !== undefined) {
    const para = inspect.graph.paragraphs.find((row) => row.at_para === region.atPara);
    return (para?.text ?? "").replace(/\s+/g, " ").trim();
  }
  return "";
}

export function StructureTree({
  inspect,
  capabilities,
}: {
  inspect: InspectResult;
  capabilities: Capabilities | null;
}) {
  const expanded = useWorkspace((s) => s.expanded);
  const isOpen = (id: string) => expanded.includes(id);

  const sections = useMemo(() => {
    const map = new Map<string, InspectResult["graph"]["paragraphs"]>();
    for (const p of inspect.graph.paragraphs) {
      const list = map.get(p.section) ?? [];
      list.push(p);
      map.set(p.section, list);
    }
    return [...map.entries()];
  }, [inspect]);

  const guides = useMemo(
    () =>
      inspect.graph.tables.flatMap((t) =>
        t.cells
          .filter((c) => c.classification === "guide")
          .map((c) => ({ table: t.index, cell: c })),
      ),
    [inspect],
  );

  const seats = inspect.regions.regions;
  const manySeats = seats.length > 6;
  const seatsOpen = manySeats ? isOpen("seats") : !isOpen("seats");

  const forbiddenCount = inspect.forbidden
    ? inspect.forbidden.counts.anchors +
      inspect.forbidden.counts.placeholders +
      inspect.forbidden.counts.removalTargets
    : 0;

  const unreachable = useMemo(() => {
    if (!capabilities) return [];
    const out: Array<{ label: string; reason: string }> = [];
    for (const [name, backend] of Object.entries(capabilities.backends)) {
      if (backend.state !== "available") {
        out.push({
          label: `${name} 연산 ${backend.opKinds.length}종`,
          reason: backend.reason ?? "이 빌드에서 사용할 수 없습니다.",
        });
      } else if (backend.notImplemented?.length) {
        out.push({
          label: `${name}: ${backend.notImplemented.join(", ")}`,
          reason: "선언되어 있으나 이 빌드에는 구현이 없습니다.",
        });
      }
    }
    for (const [key, reason] of Object.entries(capabilities.unavailable)) {
      out.push({ label: key, reason });
    }
    return out;
  }, [capabilities]);

  return (
    <div className="tree" role="tree" aria-label="문서 구조" data-testid="structure-tree">
      {sections.map(([section, paragraphs]) => {
        const id = `sec:${section}`;
        const open = isOpen(id);
        return (
          <div key={id}>
            <Row
              id={id}
              depth={0}
              label={section.split("/").pop() ?? section}
              hint={`문단 ${paragraphs.length}`}
              expandable
              expanded={open}
            />
            {open &&
              paragraphs.map((p) => (
                <Row
                  key={`p:${p.at_para}`}
                  id={`p:${p.at_para}`}
                  depth={1}
                  label={trimLabel(p.text) || "(빈 문단)"}
                  title={`at_para ${p.at_para}`}
                  selection={{ kind: "paragraph", atPara: p.at_para }}
                  testId={`para-${p.at_para}`}
                />
              ))}
          </div>
        );
      })}

      <div className="group-head">
        <span className="group-label">표</span>
        <span className="count">{inspect.graph.tables.length}</span>
      </div>
      {inspect.graph.tables.map((table) => {
        const id = `t:${table.index}`;
        const open = isOpen(id);
        return (
          <div key={id}>
            <Row
              id={id}
              depth={0}
              label={humanTableLabel(table.index)}
              hint={`${table.cells.length}칸`}
              expandable
              expanded={open}
              selection={{ kind: "table", table: table.index }}
              testId={`table-${table.index}`}
            />
            {open &&
              table.cells.map((cell) => {
                const isFill = cell.classification === "fill_target";
                const preview = (cell.textPreview ?? "").replace(/\s+/g, " ").trim();
                const state = isFill
                  ? seatState({
                      text: preview,
                      colorAnomaly: cell.colorAnomaly,
                      scriptAnomaly: cell.scriptAnomaly,
                    })
                  : undefined;
                return (
                  <Row
                    key={`${id}:R${cell.addr.row}C${cell.addr.col}`}
                    id={`c:${table.index}:${cell.addr.row}:${cell.addr.col}`}
                    depth={1}
                    label={humanCellAddress(table.index, cell.addr.row, cell.addr.col)}
                    preview={isFill ? preview || "빈 칸" : preview || undefined}
                    previewEmpty={isFill && !preview}
                    title={charPrTitle(cell.charPr, cell.charPrSuggested)}
                    state={state}
                    selection={{
                      kind: "cell",
                      table: table.index,
                      row: cell.addr.row,
                      col: cell.addr.col,
                    }}
                    testId={`cell-${table.index}-${cell.addr.row}-${cell.addr.col}`}
                    editable={isFill}
                  />
                );
              })}
          </div>
        );
      })}

      <Collapsible open={seatsOpen} onOpenChange={() => toggleExpanded("seats")}>
        <CollapsibleTrigger className="group-head" data-testid="seats-group">
          <span className="group-label">입력 칸</span>
          <span className="count">{seats.length}</span>
        </CollapsibleTrigger>
        <CollapsibleContent>
        {seats.map((region, i) => {
          const key =
            region.kind === "cell" && region.table !== undefined
              ? humanCellAddress(region.table, region.row ?? 0, region.col ?? 0)
              : `문단 ${region.atPara}`;
          const selection: Selection =
            region.kind === "cell" && region.table !== undefined
              ? { kind: "cell", table: region.table, row: region.row!, col: region.col! }
              : region.atPara !== undefined
                ? { kind: "paragraph", atPara: region.atPara }
                : null;
          const preview = seatPreview(region, inspect);
          const state = seatState({
            text: preview,
            colorAnomaly: region.colorAnomaly,
            scriptAnomaly: region.scriptAnomaly,
          });
          return (
            <Row
              key={`r${i}`}
              id={`seat:${i}`}
              depth={0}
              label={key}
              preview={preview || "빈 칸"}
              previewEmpty={!preview}
              title={charPrTitle(region.charPr, region.charPrSuggested)}
              state={state}
              selection={selection}
              testId={`seat-${i}`}
              editable={true}
            />
          );
        })}
        </CollapsibleContent>
      </Collapsible>

      {guides.length > 0 && (
        <>
          <div className="group-head">
            <span className="group-label">안내문</span>
            <span className="count">{guides.length}</span>
          </div>
          {guides.map(({ table, cell }) => (
            <Row
              key={`g:${table}:${cell.addr.row}:${cell.addr.col}`}
              id={`g:${table}:${cell.addr.row}:${cell.addr.col}`}
              depth={0}
              label={trimLabel(cell.textPreview ?? "(미리보기 없음)", 30)}
              hint={humanCellAddress(table, cell.addr.row, cell.addr.col)}
              selection={{ kind: "cell", table, row: cell.addr.row, col: cell.addr.col }}
              editable={false}
            />
          ))}
        </>
      )}

      <Collapsible className="disclosure tree-tech" data-testid="tree-tech">
        <CollapsibleTrigger>기술 정보</CollapsibleTrigger>
        <CollapsibleContent>
{inspect.forbidden && forbiddenCount > 0 ? (
          <ForbiddenRows forbidden={inspect.forbidden} />
        ) : (
          <p className="empty" data-testid="forbidden-protocol-gap">
            금지 구역은 이 응답에 없습니다.
          </p>
        )}
        {unreachable.length === 0 ? (
          <p className="empty">엔진이 아직 능력 목록을 보내지 않았습니다.</p>
        ) : (
          unreachable.map((item) => (
            <Row
              key={item.label}
              id={`u:${item.label}`}
              depth={0}
              label={item.label}
              hint={trimLabel(item.reason, 30)}
              editable={false}
            />
          ))
        )}
        <p className="empty">해석하지 못한 구조를 따로 알려 주지 않습니다.</p>
      </CollapsibleContent>
      </Collapsible>
    </div>
  );
}

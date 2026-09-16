/**
 * The document's structure, from real `document/inspect` data.
 *
 * Everything rendered here has a producer in the response — nothing is
 * inferred and nothing is invented:
 *
 * | Row | Source |
 * |---|---|
 * | 구역 / 문단 | `graph.paragraphs[]` — `section`, `at_para`, `text` |
 * | 표 / 칸 | `graph.tables[].cells[]` — `addr`, `classification`, `textPreview` |
 * | 채움 자리 | `regions.regions[]` — the fill seats, with their preflight |
 * | 금지 자리 | `forbidden` — residue anchors, placeholders, removal targets |
 * | 이 빌드가 보지 못하는 것 | `capabilities.backends` + `capabilities.unavailable` |
 *
 * `forbidden` is opt-in on the wire (`include` contains `"forbidden"`). The
 * protocol markdown and MCP include-enum still name only summary/graph/regions.
 * When the payload omits the key, this panel prints that gap and does not
 * synthesize anchors from `summary`. Fill seats (`regions.regions`) and
 * `fill_target` cells are the only rows marked editable.
 *
 * The last group is the honest answer to "unsupported structures". The Runtime
 * does not enumerate what it failed to parse, so the panel reports what this
 * build cannot reach instead of implying the document has none. That
 * distinction is the whole point: a `none` caused by an absent capability is a
 * different problem from one caused by a failure.
 */
import { useMemo } from "react";

import {
  locateSelection,
  selectionId,
  toggleExpanded,
  useWorkspace,
  type Selection,
} from "../store";
import type { Capabilities, ForbiddenInventory, InspectResult } from "../types";
import { CLASSIFICATION_LABEL, CLASSIFICATION_TONE, Tag } from "./Tag";

function Row({
  id,
  depth,
  label,
  hint,
  tag,
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
  tag?: React.ReactNode;
  selection?: Selection;
  expandable?: boolean;
  expanded?: boolean;
  testId?: string;
  /** Set only from inspect: fill seats / fill_target true; forbidden never. */
  editable?: boolean;
}) {
  const current = useWorkspace((s) => selectionId(s.selection));
  const selected = selection ? selectionId(selection) === current : false;
  return (
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
        // locate, not just select: picking a node in the tree scrolls the
        // document to it and flashes it. Clicking in the document uses
        // setSelection so the page does not move under the pointer.
        if (selection !== undefined) locateSelection(selection);
      }}
    >
      <span className="twisty">{expandable ? (expanded ? "▼" : "▶") : ""}</span>
      <span className="label">
        {label}
        {hint ? <span className="dim">　{hint}</span> : null}
      </span>
      {tag}
    </button>
  );
}

function trim(text: string, max = 34): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max)}…` : flat;
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
        <span className="latin-caps">forbidden</span>
        <span className="count">{count}</span>
      </div>
      {forbidden.anchors.map((anchor, i) => (
        <Row
          key={`forbidden-anchor-${i}`}
          id={`forbidden:anchor:${i}`}
          depth={0}
          label={trim(anchor.text || "(앵커)")}
          hint={
            typeof anchor.atPara === "number" ? `at_para ${anchor.atPara}` : "주소 없음"
          }
          selection={forbiddenSelection(anchor.atPara)}
          testId={`forbidden-anchor-${i}`}
          editable={false}
          tag={<Tag tone="bad">금지</Tag>}
        />
      ))}
      {forbidden.placeholders.map((placeholder, i) => (
        <Row
          key={`forbidden-placeholder-${i}`}
          id={`forbidden:placeholder:${i}`}
          depth={0}
          label={trim(placeholder.text || "(자리표시)")}
          testId={`forbidden-placeholder-${i}`}
          editable={false}
          tag={<Tag tone="warn">자리표시</Tag>}
        />
      ))}
      {forbidden.removalTargets.map((target, i) => (
        <Row
          key={`forbidden-removal-${i}`}
          id={`forbidden:removal:${i}`}
          depth={0}
          label={trim(target.text || target.reason || "(제거 대상)")}
          hint={
            typeof target.atPara === "number" ? `at_para ${target.atPara}` : undefined
          }
          selection={forbiddenSelection(target.atPara)}
          testId={`forbidden-removal-${i}`}
          editable={false}
          tag={<Tag tone="bad">제거 대상</Tag>}
        />
      ))}
      {forbidden.note ? <p className="empty">{forbidden.note}</p> : null}
    </>
  );
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
      {/* ── 구역과 문단 ─────────────────────────────────────────────── */}
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
                  label={trim(p.text) || "(빈 문단)"}
                  hint={`at_para ${p.at_para}`}
                  selection={{ kind: "paragraph", atPara: p.at_para }}
                  testId={`para-${p.at_para}`}
                />
              ))}
          </div>
        );
      })}

      {/* ── 표와 칸 ─────────────────────────────────────────────────── */}
      <div className="group-head">
        <span className="latin-caps">tables</span>
        <span className="count">{inspect.graph.tables.length}</span>
      </div>
      {inspect.graph.tables.map((table) => {
        const id = `t:${table.index}`;
        const open = isOpen(id);
        const fill = table.cells.filter((c) => c.classification === "fill_target").length;
        return (
          <div key={id}>
            <Row
              id={id}
              depth={0}
              label={`표 ${table.index}`}
              hint={`${table.cells.length}칸 · 채움 ${fill}`}
              expandable
              expanded={open}
              selection={{ kind: "table", table: table.index }}
              testId={`table-${table.index}`}
            />
            {open &&
              table.cells.map((cell) => {
                const addr = `R${cell.addr.row}C${cell.addr.col}`;
                const isFill = cell.classification === "fill_target";
                return (
                  <Row
                    key={`${id}:${addr}`}
                    id={`c:${table.index}:${cell.addr.row}:${cell.addr.col}`}
                    depth={1}
                    label={addr}
                    hint={cell.textPreview ? trim(cell.textPreview, 22) : undefined}
                    selection={{
                      kind: "cell",
                      table: table.index,
                      row: cell.addr.row,
                      col: cell.addr.col,
                    }}
                    testId={`cell-${table.index}-${cell.addr.row}-${cell.addr.col}`}
                    editable={isFill}
                    tag={
                      <>
                        {cell.colorAnomaly ? <Tag tone="bad">색 이상</Tag> : null}
                        {cell.scriptAnomaly ? <Tag tone="warn">글자속성 이상</Tag> : null}
                        <Tag tone={CLASSIFICATION_TONE[cell.classification] ?? "none"}>
                          {CLASSIFICATION_LABEL[cell.classification] ?? cell.classification}
                        </Tag>
                      </>
                    }
                  />
                );
              })}
          </div>
        );
      })}

      {/* ── 채움 자리 ───────────────────────────────────────────────── */}
      <div className="group-head">
        <span className="latin-caps">fill seats</span>
        <span className="count">{inspect.regions.regions.length}</span>
      </div>
      {inspect.regions.regions.map((region, i) => {
        const key =
          region.kind === "cell"
            ? `표 ${region.table} R${region.row}C${region.col}`
            : `문단 ${region.atPara}`;
        const selection: Selection =
          region.kind === "cell" && region.table !== undefined
            ? { kind: "cell", table: region.table, row: region.row!, col: region.col! }
            : region.atPara !== undefined
              ? { kind: "paragraph", atPara: region.atPara }
              : null;
        return (
          <Row
            key={`r${i}`}
            id={`seat:${i}`}
            depth={0}
            label={key}
            hint={
              region.charPr && region.charPrSuggested && region.charPr !== region.charPrSuggested
                ? `charPr ${region.charPr} → ${region.charPrSuggested}`
                : undefined
            }
            selection={selection}
            testId={`seat-${i}`}
            editable={true}
            tag={
              region.colorAnomaly ? (
                <Tag tone="bad">색 이상</Tag>
              ) : region.scriptAnomaly ? (
                <Tag tone="warn">글자속성 이상</Tag>
              ) : (
                <Tag tone="fill">채움</Tag>
              )
            }
          />
        );
      })}

      {/* ── 금지 자리 (payload only; never invented) ────────────────── */}
      {inspect.forbidden ? (
        <ForbiddenRows forbidden={inspect.forbidden} />
      ) : (
        <p className="empty" data-testid="forbidden-protocol-gap">
          이 검사 응답에는 <span className="mono">forbidden</span> 구역이 없습니다.
          프로토콜 문서와 MCP include 열거는 summary, graph, regions 뿐이고, 런타임
          코어·CLI는 선택적으로 금지 목록을 내놓을 수 있습니다. 칸이 없으면 앵커를
          만들지 않으며, 채움 자리만 편집 가능으로 표시합니다.
        </p>
      )}

      {/* ── 안내문 ──────────────────────────────────────────────────── */}
      {guides.length > 0 && (
        <>
          <div className="group-head">
            <span className="latin-caps">guide text</span>
            <span className="count">{guides.length}</span>
          </div>
          {guides.map(({ table, cell }) => (
            <Row
              key={`g:${table}:${cell.addr.row}:${cell.addr.col}`}
              id={`g:${table}:${cell.addr.row}:${cell.addr.col}`}
              depth={0}
              label={trim(cell.textPreview ?? "(미리보기 없음)", 30)}
              hint={`표 ${table} R${cell.addr.row}C${cell.addr.col}`}
              selection={{ kind: "cell", table, row: cell.addr.row, col: cell.addr.col }}
              editable={false}
            />
          ))}
        </>
      )}

      {/* ── 이 빌드가 보지 못하는 것 ────────────────────────────────── */}
      <div className="group-head">
        <span className="latin-caps">not reachable here</span>
        <span className="count">{unreachable.length}</span>
      </div>
      {unreachable.length === 0 ? (
        <p className="empty">런타임이 아직 능력 목록을 보내지 않았습니다.</p>
      ) : (
        unreachable.map((item) => (
          <Row
            key={item.label}
            id={`u:${item.label}`}
            depth={0}
            label={item.label}
            hint={trim(item.reason, 30)}
            tag={<Tag tone="none">불가</Tag>}
            editable={false}
          />
        ))
      )}
      <p className="empty">
        런타임은 해석하지 못한 구조를 따로 알려 주지 않습니다. 위 목록은 이 빌드가 다룰 수
        없는 것이지, 이 문서에 그런 구조가 없다는 뜻은 아닙니다.
      </p>
    </div>
  );
}

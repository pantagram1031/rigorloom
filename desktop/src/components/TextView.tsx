/**
 * 본문 보기 — the document's own content, in reading order.
 *
 * This is not a rendered page and it does not pretend to be one. There is no
 * renderer in this build; inventing a page layout would be the one thing the
 * verification bar exists to prevent. What this shows is the text and table
 * structure the Runtime actually reported, arranged for reading, and the
 * header strip says so in as many words.
 *
 * Two data sources, both real:
 *   - `graph.tables[].cells[]` for structure and classification;
 *   - `document/readRegion` for each cell's full text and its per-run
 *     `charpr` / `color_anomaly` / `color_value`. The graph's `textPreview` is
 *     truncated for anything long, so the graph alone cannot be the source.
 *
 * **Why the table is the body.** In a Korean form the table *is* the document:
 * for the corpus 기안문 별지, table 0's 32 cells hold everything, and the
 * document's 26 paragraphs are the runs inside those cells. Rendering both
 * flows would print the same sentences twice. So the tables render as the
 * document, and only paragraphs whose text appears in no cell run are shown
 * separately below.
 *
 * That coverage test is exact string matching, not a guess: `form_inspect`
 * derives cell runs and paragraphs from the same underlying runs, so the
 * strings are identical when they refer to the same content. It is a
 * workaround for a real gap all the same — the Runtime exposes `at_para` and
 * `row,col#run` as two addressings with no mapping between them. Recorded in
 * README.
 *
 * **Phase 4 note.** Every fill seat is already a discrete, addressed,
 * focusable element carrying its `data-node-id`. Inline editing replaces the
 * slot's contents with an input and drafts an OperationPlan; nothing else about
 * this component has to change.
 */
import { useEffect, useMemo, useRef } from "react";

import {
  activeText,
  selectionId,
  setSelection,
  useWorkspace,
  type Selection,
} from "../store";
import type { GraphCell, InspectResult, RegionText, TextRun } from "../types";

/** Runs render in their real colour when the runtime says the colour is off. */
function Run({ run }: { run: TextRun }) {
  if (!run.color_anomaly) return <>{run.text}</>;
  return (
    <span
      className="run-anomaly"
      style={run.color_value ? { color: run.color_value } : undefined}
      title={`본문 기준과 다른 색: ${run.color_value ?? "알 수 없음"}`}
    >
      {run.text}
    </span>
  );
}

function CellBody({ cell, region }: { cell: GraphCell; region?: RegionText }) {
  const runs = region?.runs ?? [];
  if (runs.length > 0) {
    return (
      <>
        {runs.map((run) => (
          <div key={run.index} className="cell-run">
            <Run run={run} />
          </div>
        ))}
      </>
    );
  }
  const text = region?.text ?? cell.textPreview ?? "";
  if (text.trim().length > 0) {
    return (
      <>
        {text}
        {!region && cell.truncated ? <span className="dim"> …</span> : null}
      </>
    );
  }
  // An empty fill seat: the slot a value goes into. Discrete on purpose.
  if (cell.classification === "fill_target") {
    return <span className="slot" aria-label="값을 넣는 자리" />;
  }
  return null;
}

export function TextView({ inspect }: { inspect: InspectResult }) {
  const texts = useWorkspace(activeText);
  const currentId = useWorkspace((s) => selectionId(s.selection));
  const locateNonce = useWorkspace((s) => s.locateNonce);
  const scroller = useRef<HTMLDivElement>(null);

  /** Address -> its full text, so a cell can find its own runs in O(1). */
  const byAddr = useMemo(() => {
    const map = new Map<string, RegionText>();
    for (const region of texts) {
      if (region.addr) {
        map.set(`${region.table ?? 0}:${region.addr.row}:${region.addr.col}`, region);
      } else if (region.at_para !== undefined) {
        map.set(`p:${region.at_para}`, region);
      }
    }
    return map;
  }, [texts]);

  /** Every string that already appears inside a table cell. */
  const covered = useMemo(() => {
    const set = new Set<string>();
    for (const region of texts) {
      if (!region.addr) continue;
      for (const run of region.runs ?? []) set.add(run.text.trim());
    }
    return set;
  }, [texts]);

  const loose = useMemo(
    () =>
      inspect.graph.paragraphs.filter(
        (p) => p.text.trim().length > 0 && !covered.has(p.text.trim()),
      ),
    [inspect, covered],
  );

  /**
   * Tables, rebuilt onto the column grid the addresses already describe.
   *
   * The runtime reports cells as `row,col` and says nothing about merges. Laid
   * out naively that produces nonsense on a real form: the corpus 기안문 has
   * one row of fifteen cells and several rows of one cell, and an HTML table
   * aligns columns across rows, so the single-cell rows collapse into the
   * first column and the whole document crams into a strip.
   *
   * The fix uses only what the runtime gave. The union of every distinct `col`
   * across the table is the column axis; a cell occupies from its own `col` up
   * to the next occupied `col` in the same row. That is a colspan derived from
   * the addressing, not a guess at merge geometry — and where the addresses are
   * sparse it is exactly the span the address implies.
   */
  const tables = useMemo(
    () =>
      inspect.graph.tables.map((table) => {
        const axis = [...new Set(table.cells.map((c) => c.addr.col))].sort((a, b) => a - b);
        const at = new Map(axis.map((col, i) => [col, i]));

        const grouped = new Map<number, GraphCell[]>();
        for (const cell of table.cells) {
          const list = grouped.get(cell.addr.row) ?? [];
          list.push(cell);
          grouped.set(cell.addr.row, list);
        }

        const rows = [...grouped.entries()]
          .sort((a, b) => a[0] - b[0])
          .map(([row, unsorted]) => {
            const cells = unsorted.sort((a, b) => a.addr.col - b.addr.col);
            const spans = cells.map((cell, i) => {
              const start = at.get(cell.addr.col) ?? 0;
              const next = cells[i + 1];
              const end = next ? (at.get(next.addr.col) ?? axis.length) : axis.length;
              return { cell, colSpan: Math.max(1, end - start) };
            });
            // A row that does not start at the first column keeps its offset.
            const lead = cells.length ? (at.get(cells[0].addr.col) ?? 0) : 0;
            return { row, lead, spans };
          });

        return { index: table.index, columns: axis.length, rows };
      }),
    [inspect],
  );

  // Tree -> centre. Only when something asked (locateNonce), so clicking in
  // the document does not scroll the document out from under the pointer.
  useEffect(() => {
    if (locateNonce === 0 || currentId === "none") return;
    const target = scroller.current?.querySelector<HTMLElement>(
      `[data-node-id="${CSS.escape(currentId)}"]`,
    );
    if (!target) return;
    target.scrollIntoView({ block: "center", behavior: "smooth" });
    target.classList.remove("locate-flash");
    // Force a reflow so the animation restarts on a repeated locate.
    void target.offsetWidth;
    target.classList.add("locate-flash");
  }, [locateNonce, currentId]);

  const select = (selection: Selection) => setSelection(selection);

  return (
    <div className="center-scroll" ref={scroller} data-testid="text-view">
      <article className="paper" data-testid="paper">
        {tables.map((table) => (
          <div key={table.index} className="table-scroll">
          <table className="doc-table">
            <caption>표 {table.index}</caption>
            <tbody>
              {table.rows.map(({ row, lead, spans }) => (
                <tr key={row}>
                  {lead > 0 ? <td className="pad" colSpan={lead} /> : null}
                  {spans.map(({ cell, colSpan }) => {
                    const id = `c:${table.index}:${cell.addr.row}:${cell.addr.col}`;
                    const region = byAddr.get(
                      `${table.index}:${cell.addr.row}:${cell.addr.col}`,
                    );
                    return (
                      <td
                        key={id}
                        colSpan={colSpan}
                        data-node-id={id}
                        data-testid={`doc-cell-${table.index}-${cell.addr.row}-${cell.addr.col}`}
                        className={
                          cell.classification === "fill_target"
                            ? "seat"
                            : cell.classification === "guide"
                              ? "guide"
                              : cell.classification === "spacer"
                                ? "spacer"
                                : ""
                        }
                        aria-selected={currentId === id}
                        title={`R${cell.addr.row}C${cell.addr.col} · ${cell.classification}`}
                        onClick={() =>
                          select({
                            kind: "cell",
                            table: table.index,
                            row: cell.addr.row,
                            col: cell.addr.col,
                          })
                        }
                      >
                        <CellBody cell={cell} region={region} />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        ))}

        {loose.length > 0 && (
          <>
            {tables.length > 0 && (
              <p className="doc-divider latin-caps">표 밖의 문단</p>
            )}
            {loose.map((para) => {
              const id = `p:${para.at_para}`;
              const region = byAddr.get(id);
              return (
                <p
                  key={id}
                  className="doc-para"
                  data-node-id={id}
                  data-testid={`doc-para-${para.at_para}`}
                  aria-selected={currentId === id}
                  title={`at_para ${para.at_para}`}
                  onClick={() => select({ kind: "paragraph", atPara: para.at_para })}
                >
                  {region?.runs?.length
                    ? region.runs.map((run) => <Run key={run.index} run={run} />)
                    : para.text}
                </p>
              );
            })}
          </>
        )}

        {tables.length === 0 && loose.length === 0 && (
          <p className="doc-para empty-para">이 문서에서 읽어 온 글이 없습니다.</p>
        )}
      </article>
    </div>
  );
}

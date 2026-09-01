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
 * **Phase 4.** Every fill seat was already a discrete, addressed element with
 * its own empty slot, so inline editing replaced the slot's contents with a
 * real `<input>` and nothing else about this component changed. A queued edit
 * renders in place as `before → after` so the document on screen shows what
 * the document would become — and shows it as a proposal, not as a fact,
 * because nothing has been written.
 */
import { useEffect, useMemo, useRef, useState } from "react";

import { beginEdit, cancelEdit, commitEdit } from "../actions";
import {
  activeText,
  cellKey,
  selectionId,
  setSelection,
  setState,
  useWorkspace,
  type QueuedOp,
  type Selection,
} from "../store";
import type { GraphCell, InspectResult, RegionText, TextRun } from "../types";

/**
 * The inline editor. A real `<input>`, mounted in the cell.
 *
 * That it is a real input element is the whole design, not an implementation
 * detail: Hangul composition belongs to the IME, and only a real text field
 * gets it. A 두벌식 sequence composes in place, the preedit syllable is
 * visible while it is being built, and Backspace decomposes rather than
 * deletes. A keydown-driven buffer would receive the jamo separately and
 * reassemble them wrongly; a contenteditable would fight the composition
 * events. The spike proved this with real scan codes (M13/M14) and
 * `scripts/ime.ps1` re-proves it against this field.
 *
 * `onKeyDown` deliberately ignores Enter while `isComposing` is true. Pressing
 * Enter to CONFIRM a composing syllable is a normal part of typing Korean, and
 * a handler that committed the edit there would end the edit halfway through
 * the user's word.
 */
function SeatEditor({
  value,
  onCommit,
  onCancel,
}: {
  value: string;
  onCommit: (next: string) => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState(value);
  const field = useRef<HTMLInputElement>(null);
  const composing = useRef(false);

  useEffect(() => {
    field.current?.focus();
    field.current?.select();
  }, []);

  return (
    <input
      ref={field}
      className="seat-input"
      data-testid="seat-input"
      value={text}
      aria-label="이 자리에 넣을 값"
      onChange={(e) => setText(e.target.value)}
      onCompositionStart={() => {
        composing.current = true;
      }}
      onCompositionEnd={(e) => {
        composing.current = false;
        // Recorded so the IME harness can tell a composed string from
        // characters injected straight into the field: both look the same in
        // the value, and only one of them exercised the IME.
        setState({ sawComposition: true });
        // The composed syllable arrives here on some IMEs without a further
        // input event, so read it off the element rather than trusting state.
        setText((e.target as HTMLInputElement).value);
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          if (composing.current || e.nativeEvent.isComposing) return;
          e.preventDefault();
          onCommit(field.current?.value ?? text);
        } else if (e.key === "Escape") {
          e.preventDefault();
          onCancel();
        }
        // Every other key, modifiers included, belongs to the field.
        e.stopPropagation();
      }}
      onBlur={() => onCommit(field.current?.value ?? text)}
      onClick={(e) => e.stopPropagation()}
    />
  );
}

/** A queued edit, drawn in the document as a proposal. */
function QueuedValue({ op }: { op: QueuedOp }) {
  return (
    <span className="queued" data-testid={`queued-${op.table}-${op.row}-${op.col}`}>
      {op.before.trim().length > 0 ? (
        <>
          <s className="was">{op.before}</s>
          <span className="arrow" aria-hidden="true">
            →
          </span>
        </>
      ) : null}
      <span className="will">{op.text}</span>
    </span>
  );
}

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

function CellBody({
  cell,
  region,
  queued,
}: {
  cell: GraphCell;
  region?: RegionText;
  queued?: QueuedOp | null;
}) {
  // A queued edit replaces whatever the cell holds today. Showing both — the
  // document's current text AND the proposed value — is what lets a reviewer
  // check the edit against the form rather than against their memory of it.
  if (queued) return <QueuedValue op={queued} />;
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
  const inlineEdit = useWorkspace((s) => s.inlineEdit);
  const queuedOps = useWorkspace((s) => s.draft.ops);
  const scroller = useRef<HTMLDivElement>(null);

  const queuedByCell = useMemo(() => {
    const map = new Map<string, QueuedOp>();
    for (const op of queuedOps) map.set(cellKey(op.table, op.row, op.col), op);
    return map;
  }, [queuedOps]);

  const editingId = inlineEdit
    ? cellKey(inlineEdit.table, inlineEdit.row, inlineEdit.col)
    : null;

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

  /**
   * The node currently flashing, as state rather than a class poked onto the
   * DOM.
   *
   * The imperative version lost the flash at random: `className` on these
   * cells is a React-controlled prop, so the very next render — a selection
   * change, a text arriving, anything — overwrote the attribute and took
   * `locate-flash` with it. Owning it in state means React writes the class
   * itself and no re-render can drop it.
   */
  const [flashId, setFlashId] = useState<string | null>(null);

  // Tree -> centre. Only when something asked (locateNonce), so clicking in
  // the document does not scroll the document out from under the pointer.
  useEffect(() => {
    if (locateNonce === 0 || currentId === "none") return;
    const target = scroller.current?.querySelector<HTMLElement>(
      `[data-node-id="${CSS.escape(currentId)}"]`,
    );
    if (!target) return;
    target.scrollIntoView({ block: "center", behavior: "smooth" });

    // Set synchronously, with no requestAnimationFrame in the way. WebView2
    // withholds rAF from a window that is not in the foreground, so a callback
    // scheduled that way may simply never run — which would make the flash a
    // coin-flip on any machine where the window lost focus, and made it fail
    // every time under the harness.
    //
    // The cost of not clearing first is that a second locate on the same node
    // inside 900 ms does not restart the animation. After 900 ms the timer has
    // cleared the class and it restarts normally.
    setFlashId(currentId);
    const clear = window.setTimeout(() => setFlashId(null), 900);
    return () => window.clearTimeout(clear);
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
                    const seat = cell.classification === "fill_target";
                    const queued = queuedByCell.get(id) ?? null;
                    const editing = editingId === id;
                    return (
                      <td
                        key={id}
                        colSpan={colSpan}
                        data-node-id={id}
                        data-testid={`doc-cell-${table.index}-${cell.addr.row}-${cell.addr.col}`}
                        className={[
                          seat
                            ? "seat"
                            : cell.classification === "guide"
                              ? "guide"
                              : cell.classification === "spacer"
                                ? "spacer"
                                : "",
                          queued ? "has-edit" : "",
                          editing ? "editing" : "",
                          flashId === id ? "locate-flash" : "",
                        ]
                          .filter(Boolean)
                          .join(" ")}
                        aria-selected={currentId === id}
                        title={
                          seat
                            ? `R${cell.addr.row}C${cell.addr.col} · 채움 자리 — 눌러서 값을 넣습니다`
                            : `R${cell.addr.row}C${cell.addr.col} · ${cell.classification}`
                        }
                        onClick={() => {
                          const selection = {
                            kind: "cell" as const,
                            table: table.index,
                            row: cell.addr.row,
                            col: cell.addr.col,
                          };
                          // A 채움 자리 opens for typing on the first click.
                          // Anything else is a selection, as before: a form's
                          // static text is not editable and offering an input
                          // over it would be a promise the runtime refuses.
                          if (seat && !editing) {
                            beginEdit(table.index, cell.addr.row, cell.addr.col);
                          } else {
                            select(selection);
                          }
                        }}
                      >
                        {editing && inlineEdit ? (
                          <SeatEditor
                            value={queued?.text ?? inlineEdit.before}
                            onCommit={(next) => void commitEdit(next)}
                            onCancel={cancelEdit}
                          />
                        ) : (
                          <CellBody cell={cell} region={region} queued={queued} />
                        )}
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
                  className={flashId === id ? "doc-para locate-flash" : "doc-para"}
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

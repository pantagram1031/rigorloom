import { useEffect, useRef, useState, type CSSProperties } from "react";

import { cancelEdit, setInlineEditMultiline } from "../actions";
import { rectPt, type EngineBox, type EngineGeometry, type EngineTextEdit } from "../model/enginePage";
import { formatCellAddress, resolvePageFontCategory, type PageHitResult } from "../model/page";
import { locateSpanInRuns } from "../run_map";
import { runTextAfterEdit } from "../revision";
import { readRegion } from "../runtime";
import { activeSession, getState, headCandidate, queuedCellOpAt, queuedRunOpAt, setState, useWorkspace } from "../store";
import type { InspectResult } from "../types";
import { commitCellEditV2, commitEngineRunEdit, notifyParagraphNotEditable } from "./actions";
import { SeatEditor } from "./SeatEditor";

const PX_PER_PT = 96 / 72;
const utf16 = (text: string, codePoints: number) => [...text].slice(0, codePoints).join("").length;

type Placement = {
  id: string;
  page: number;
  line: EngineBox;
  face: string | null;
  caret?: number | null | "end";
};

type Pending = Placement & { value: string };

function lineStyle({ line }: Placement): CSSProperties {
  const { x, y, w, h } = rectPt(line.rect);
  return {
    left: x * PX_PER_PT, top: y * PX_PER_PT,
    width: Math.max(line.vertical ? 20 : 28, w * PX_PER_PT),
    minHeight: Math.max(18, h * PX_PER_PT),
    writingMode: line.vertical ? "vertical-rl" : undefined,
    fontSize: Math.min(18, Math.max(10, (line.vertical ? w : h) * PX_PER_PT)),
  };
}

export function useEngineEditOverlay({
  sessionId, geometry, editable, isNarrow, settled, displayedEdits, inspect, hit, onCycleCell,
}: {
  sessionId: string;
  geometry: EngineGeometry | null;
  editable: boolean;
  isNarrow: boolean;
  settled: boolean;
  displayedEdits: readonly EngineTextEdit[];
  inspect: InspectResult;
  hit: PageHitResult | null;
  onCycleCell: (table: number, row: number, col: number, dir: 1 | -1) => void;
}) {
  const edit = useWorkspace((s) => s.inlineEdit);
  const [paragraph, setParagraph] = useState<Placement | null>(null);
  const [pending, setPending] = useState<Pending[]>([]);
  const lastSubmitted = useRef<Pending | null>(null);
  const latestValue = useRef<string | null>(null);
  const geometryRef = useRef(geometry);
  geometryRef.current = geometry;
  const baselineFace = inspect.summary?.baselineCharPr?.face?.hangul ?? null;

  const cellAt = edit?.kind === "cell" ? formatCellAddress(edit.table, edit.row, edit.col) : null;
  const cellLines = cellAt ? geometry?.boxes.filter((box) => box.kind === "line" &&
    (box.queueAddress ?? box.at)?.startsWith(`${cellAt}/p`)) ?? [] : [];
  const pickedCellLine = cellLines.find((box) => box.at === hit?.lineAddress);
  const cellLine = pickedCellLine ?? cellLines[0];
  const queuedCell = edit?.kind === "cell" ? queuedCellOpAt(getState(), edit.table, edit.row, edit.col) : null;
  const cellValue = queuedCell?.kind === "replace_at_cell" && queuedCell.run === undefined && queuedCell.mode === "append"
    ? queuedCell.before + queuedCell.text
    : queuedCell?.kind === "fill_cell" ? queuedCell.lines?.join("\n") ?? queuedCell.text
      : queuedCell?.kind === "replace_at_cell" && queuedCell.run === undefined ? queuedCell.text : edit?.before ?? "";
  const placement: Placement | null = !editable || !geometry || !edit ? null
    : edit.kind === "run" ? paragraph
      : !isNarrow && cellLine && cellAt ? {
          id: cellAt, line: cellLine, page: geometry.page,
          face: inspect.regions.regions.find((region) => region.table === edit.table &&
            region.row === edit.row && region.col === edit.col)?.charPrFace?.hangul ?? baselineFace,
          caret: cellCaret(cellValue, pickedCellLine, hit, cellLines),
        } : null;
  const initial = edit?.kind === "run"
    ? (edit.rangeText ?? edit.before).slice(edit.rangeStart, edit.rangeEnd) : cellValue;
  const activeId = placement?.id;

  useEffect(() => {
    latestValue.current = null;
    lastSubmitted.current = null;
  }, [activeId]);

  useEffect(() => {
    if (!settled || !geometry || pending.length === 0) return;
    const submitted = lastSubmitted.current;
    if (submitted?.page === geometry.page && submitted.id === activeId && latestValue.current === submitted.value) {
      cancelEdit();
    }
    setPending((items) => items.filter((item) => item.page !== geometry.page));
  }, [activeId, geometry, pending, settled]);

  async function beginParagraph(point: PageHitResult) {
    if (!editable || !geometry || !point.lineAddress) return false;
    const line = geometry.boxes.find((box) => box.at === point.lineAddress && box.kind === "line");
    const match = (line?.queueAddress ?? line?.at)?.match(/^p(\d+)#L(\d+)$/);
    if (!line?.text || !match) return false;
    const atPara = Number(match[1]);
    const state = getState();
    const runId = headCandidate(state)?.runId ?? null;
    const intent = state.editIntentGeneration + 1;
    setState({ editIntentGeneration: intent });
    const stillCurrent = () => getState().activeSessionId === sessionId &&
      getState().editIntentGeneration === intent && geometryRef.current === geometry;
    try {
      const { subject, regions } = await readRegion(sessionId, [{ atPara }], runId);
      if (!stillCurrent()) return;
      const baseRuns = regions.find((region) => region.at_para === atPara)?.runs ?? [];
      if (subject?.sha256 !== geometry.rev || (subject.runId ?? null) !== runId) {
        notifyParagraphNotEditable();
        return true;
      }
      const runs = baseRuns.map((run) => ({
        ...run,
        text: displayedEdits.find((op) => op.at === `p${atPara}` && op.run === run.index)?.text ?? run.text,
      }));
      const caret = utf16(line.text, point.lineOffset ?? 0);
      const located = locateSpanInRuns(line.text, runs, caret);
      if (located.kind === "refused") {
        notifyParagraphNotEditable();
        return true;
      }
      const run = baseRuns.find((item) => item.index === located.run);
      if (!run) return true;
      const queued = queuedRunOpAt(getState(), atPara, run.index);
      const runCaret = Math.max(0, Math.min(caret - located.spanOffset, located.rangeEnd - located.rangeStart));
      const [x, y, w, h] = line.rect;
      const runStart = [...line.text.slice(0, located.spanOffset)].length;
      const firstX = line.xs?.[runStart] ?? x;
      setParagraph({
        id: `p${atPara}#${run.index}`, page: geometry.page,
        line: { ...line, rect: [firstX, y, Math.max(0, x + w - firstX), h] },
        face: run.charpr_face?.hangul ?? baselineFace,
        caret: runCaret,
      });
      setState({
        selection: { kind: "paragraph", atPara },
        inlineEdit: { kind: "run", atPara, run: run.index, before: queued?.before ?? run.text,
          opId: queued?.opId ?? null, caret: runCaret, spanIndex: Number(match[2]),
          runId, documentSha256: geometry.rev, rangeText: located.runText, rangeStart: located.rangeStart,
          rangeEnd: located.rangeEnd, offsetUnit: located.offsetUnit },
      });
    } catch {
      if (stillCurrent()) notifyParagraphNotEditable();
    }
    return true;
  }

  const submit = (value: string, keepOpen: boolean) => {
    const state = getState();
    const head = headCandidate(state)?.sha256 ?? activeSession(state)?.source.sha256;
    if (!placement || !edit || state.inlineEdit !== edit || state.activeSessionId !== sessionId ||
        geometry?.rev !== head) return false;
    const previous = lastSubmitted.current;
    if (value === (previous ? previous.value : initial)) {
      if (!keepOpen) cancelEdit();
      return true;
    }
    const item = { ...placement, value };
    lastSubmitted.current = item;
    setPending((items) => [...items.filter((other) => other.id !== item.id), item]);
    if (edit.kind === "cell") void commitCellEditV2(value, { inspect, keepOpen });
    else void commitEngineRunEdit(value, runTextAfterEdit(edit, value), keepOpen);
    return true;
  };

  const editor = placement && edit ? (
    <SeatEditor
      key={placement.id}
      value={initial}
      caret={placement.caret}
      multiline={edit.kind === "cell" && edit.multiline}
      allowMultiline={edit.kind === "cell"}
      onMultilineChange={setInlineEditMultiline}
      fontCategory={resolvePageFontCategory(placement.face)}
      fontFace={placement.face}
      className="rl-seat-input rl-engine-edit"
      style={lineStyle(placement)}
      onValueChange={(value) => { latestValue.current = value; }}
      onCompositionStart={() => { latestValue.current = null; }}
      onIdleCommit={(value) => submit(value, true)}
      onCommit={(value) => submit(value, false)}
      onCycleBlank={edit.kind === "cell" ? (dir, value) => {
        if (!submit(value, false)) return false;
        onCycleCell(edit.table, edit.row, edit.col, dir);
        return true;
      } : undefined}
      onCancel={cancelEdit}
    />
  ) : null;

  return {
    editor,
    beginParagraph,
    pending: pending.filter((item) => !settled && item.page === geometry?.page && item.id !== activeId)
      .map((item) => (
        <span className="rl-seat-input rl-engine-edit rl-engine-edit-pending" data-testid="engine-edit-pending"
          key={item.id} style={{ ...lineStyle(item), fontFamily: item.face ? `"${item.face.replace(/"/g, "")}", inherit` : undefined }}>
          {item.value}
        </span>
      )),
    activeCell: Boolean(editor && cellAt),
  };
}

function cellCaret(value: string, line: EngineBox | undefined, hit: PageHitResult | null, lines: EngineBox[]) {
  if (!line || !hit || !line.at || !value) return "end";
  const index = lines.indexOf(line);
  const before = lines.slice(0, index).reduce((text, entry, i) => {
    const next = lines[i + 1];
    const separator = entry.at?.split("#")[0] === next.at?.split("#")[0] ? "" : "\n";
    return text + (entry.text ?? "") + separator;
  }, "");
  const prefix = before + (line.text ?? "");
  return value.startsWith(prefix) ? before.length + utf16(line.text ?? "", hit.lineOffset ?? 0) : "end";
}

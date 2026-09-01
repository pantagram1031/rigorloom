/**
 * The editor strip above the document. Hangul-editor-shaped, and our own.
 *
 * WHAT IT IS FOR. Until Phase 5 the centre had a two-button mode switch and a
 * caveat line, and the window read as a web page with a document in it. A
 * Hangul editor has a dense functional band between the chrome and the paper —
 * what the caret is standing in, how big the page is drawn, what state the
 * document is in — and that band is most of why the genre feels like an editor.
 * This is that band: dense, keyboard-first, no icon cloning, no Hancom
 * anything. The hanji surface and the one teal accent are unchanged.
 *
 * EVERY FIELD IS READ-ONLY THIS SLICE, and every field is real.
 *
 * WHAT IS NOT HERE, AND WHY. A 글꼴 name. `document/inspect` reports a seat's
 * `charPr` as an ID and reports a HEIGHT only for the two document-level shapes
 * (`baselineCharPr`, `blackCharPr`); no typeface name is on the wire anywhere.
 * So the strip shows the id, shows the body size it can prove, and says the
 * name is not something this build knows — rather than drawing a font dropdown
 * reading "맑은 고딕" because that is what a toolbar usually says. Recorded as
 * runtime gap 16.
 */
import { applyUiZoom, runCheck } from "../actions";
import {
  activeText,
  canRenderPages,
  cellKey,
  setCenterMode,
  setZoom,
  useWorkspace,
  type Selection,
} from "../store";
import type { InspectResult, RegionText } from "../types";
import { Tag } from "./Tag";

/**
 * The charPr the selected node carries, from the graph the runtime returned.
 *
 * NOT A SELECTOR, and the distinction is load-bearing. `useSyncExternalStore`
 * compares snapshots with `Object.is`, so a selector returning a fresh object
 * makes React conclude the store is changing forever and takes the whole root
 * down — the failure that cost a cycle in the design slice and another in Phase
 * 4. This is a plain function over values already pulled through stable
 * selectors, called during render.
 */
function seatCharPr(
  selection: Selection,
  inspect: InspectResult | null,
  texts: RegionText[],
): { id: string | null; suggested: string | null; where: string } {
  if (!inspect || !selection) return { id: null, suggested: null, where: "" };
  if (selection.kind === "cell") {
    const table = inspect.graph.tables.find((t) => t.index === selection.table);
    const cell = table?.cells.find(
      (c) => c.addr.row === selection.row && c.addr.col === selection.col,
    );
    return {
      id: cell?.charPr ?? null,
      suggested: cell?.charPrSuggested ?? null,
      where: cellKey(selection.table, selection.row, selection.col),
    };
  }
  if (selection.kind === "paragraph") {
    // Paragraph runs carry their own charPr, from document/readRegion.
    const region = texts.find((row) => row.at_para === selection.atPara);
    const run = region?.runs?.[0];
    return { id: run?.charpr ?? null, suggested: null, where: `p:${selection.atPara}` };
  }
  return { id: null, suggested: null, where: `t:${selection.table}` };
}

export function EditorToolbar({ inspect }: { inspect: InspectResult | null }) {
  const mode = useWorkspace((s) => s.centerMode);
  const canRender = useWorkspace(canRenderPages);
  const zoom = useWorkspace((s) => s.zoom);
  const uiZoom = useWorkspace((s) => s.uiZoom);
  const selection = useWorkspace((s) => s.selection);
  const texts = useWorkspace(activeText);
  const charPr = seatCharPr(selection, inspect, texts);
  const queued = useWorkspace((s) => s.draft.ops.length);
  const approvalPhase = useWorkspace((s) => s.approvalPhase);
  const applied = useWorkspace((s) => s.applied);
  const checkPhase = useWorkspace((s) => s.checkPhase);
  const findings = useWorkspace((s) => s.findings);

  const baseline = inspect?.summary.baselineCharPr ?? null;
  const hard = findings.filter((f) => f.severity === "hard").length;
  const anomalous = charPr.suggested !== null && charPr.id !== charPr.suggested;

  return (
    <div className="toolbar" data-testid="editor-toolbar" role="toolbar" aria-label="편집 도구">
      {/* 글자 모양. An id and a size, because that is what exists. */}
      <div className="tool-group" data-testid="tool-charpr">
        <span className="tool-label">글자 모양</span>
        <span className="tool-value mono" title={charPr.where || "선택한 곳이 없습니다"}>
          {charPr.id ?? "—"}
        </span>
        {anomalous ? (
          <Tag tone="warn" title={`이 문서의 본문 모양은 ${charPr.suggested} 입니다`}>
            본문과 다름
          </Tag>
        ) : null}
      </div>

      <div className="tool-sep" />

      <div className="tool-group" data-testid="tool-size">
        <span className="tool-label">크기</span>
        <span className="tool-value mono">
          {baseline ? `${baseline.height_pt}pt` : "—"}
        </span>
        <span className="tool-note tiny">본문 기준</span>
      </div>

      <div className="tool-sep" />

      {/* The mode switch, moved here from the centre's own head. */}
      <div className="modeswitch" role="group" aria-label="가운데 화면 모드">
        <button
          aria-pressed={mode === "text"}
          data-testid="mode-text"
          title="문서의 글과 표를 읽기 순서로 (Ctrl+1 은 화면 전환입니다)"
          onClick={() => setCenterMode("text")}
        >
          본문 보기
        </button>
        <button
          aria-pressed={mode === "page"}
          data-testid="mode-page"
          disabled={!canRender}
          title={
            canRender
              ? "실제 페이지 그림"
              : "이 런타임에는 문서를 그림으로 그리는 방법이 아직 없습니다"
          }
          onClick={() => setCenterMode("page")}
        >
          페이지 보기
        </button>
      </div>

      <div className="tool-sep" />

      {/* Document zoom. One number, meaning the same thing in both modes. */}
      <div className="tool-group zoomer" data-testid="tool-zoom">
        <button
          className="ghost"
          aria-label="문서 축소"
          disabled={zoom <= 0.5}
          onClick={() => setZoom(zoom - 0.1)}
        >
          −
        </button>
        <button
          className="tool-value mono"
          data-testid="zoom-value"
          title="100% 로 되돌립니다"
          onClick={() => setZoom(1)}
        >
          {Math.round(zoom * 100)}%
        </button>
        <button
          className="ghost"
          aria-label="문서 확대"
          disabled={zoom >= 4}
          onClick={() => setZoom(zoom + 0.1)}
        >
          +
        </button>
      </div>

      <span className="spacer" />

      {/* State, right-aligned, in the order a person asks about it. */}
      <div className="tool-group" data-testid="tool-state">
        {queued > 0 ? (
          <Tag tone="fill" title="아직 문서는 바뀌지 않았습니다">
            대기 {queued}
          </Tag>
        ) : null}
        {approvalPhase === "pending" ? (
          <Tag tone="warn" title="사람이 승인해야 다음으로 갑니다">
            승인 대기
          </Tag>
        ) : null}
        {applied ? (
          <Tag tone="ok" title={applied.candidate.sha256}>
            후보본 있음
          </Tag>
        ) : null}
        <button
          className="ghost"
          data-testid="toolbar-check"
          disabled={!inspect || checkPhase === "starting"}
          title="서식 검사를 돌립니다"
          onClick={() => void runCheck()}
        >
          {checkPhase === "starting"
            ? "검사 중…"
            : checkPhase === "idle"
              ? "검사"
              : hard > 0
                ? `막힘 ${hard}`
                : `검사 ${findings.length}`}
        </button>
      </div>

      <div className="tool-sep" />

      {/* App zoom, distinct from document zoom and labelled so. */}
      <div className="tool-group" data-testid="tool-uizoom">
        <span className="tool-label">화면</span>
        <button
          className="tool-value mono"
          title="Ctrl+0 으로 되돌립니다"
          disabled={uiZoom === 1}
          onClick={() => void applyUiZoom(1)}
        >
          {Math.round(uiZoom * 100)}%
        </button>
      </div>
    </div>
  );
}

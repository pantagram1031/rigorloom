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
 * EVERY FIELD IS READ-ONLY, and every field is real.
 *
 * 글꼴, AND THE TWO ABSENCES IT KEEPS APART. Runtime gap 16 is closed: §14 puts
 * the declared face on the wire, joined out of the header's own `fontface`
 * tables, so the strip shows 돋움체 where it used to show `charPr 11`. Three
 * rules it is written to, because a font control is the easiest place in this
 * application to fabricate:
 *
 * - **Nothing is defaulted.** A dropdown reading 맑은 고딕 because that is what
 *   a toolbar usually says would be a fabrication. Where the document declares
 *   no resolvable face, the id stands alone and the tooltip says the document
 *   did not name one.
 * - **Two absences stay apart.** `face: null` means THIS document names no face
 *   for that charPr; `summary.typefaces.state === "unavailable"` means nothing
 *   looked — a profile from an older scan, for instance. Collapsing them would
 *   tell a user their document names no fonts when the truth is we did not read.
 * - **한글 first, and the others on hover.** §14 carries a face PER LANGUAGE
 *   because Hangul's own font dialog does; the strip has room for one, so it
 *   shows the 한글 face and the tooltip carries every language declared. It
 *   does not merge them into one name, which would be a guess about which of
 *   two declared truths the reader meant.
 *
 * The T30 mismatch reads in names now rather than integers: a seat inheriting
 * charPr 11 (돋움체) where the preflight suggests charPr 23 (한양중고딕) is a
 * fact a person can act on; "11 vs 23" was not.
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
import type { InspectResult, RegionText, TypefaceByLang } from "../types";
import { Tag } from "./Tag";

/**
 * charPr id -> the face the DOCUMENT declares for it, joined from the two
 * places `document/inspect` already publishes one.
 *
 * Built rather than looked up in one field because the two publishers cover
 * different ids: `summary.baselineCharPr` / `summary.blackCharPr` carry the
 * document-level shapes, and `regions[].charPrFace` /
 * `regions[].charPrSuggestedFace` carry every fill seat's own and the one its
 * preflight suggests. The toolbar's selection can be a graph cell that is not a
 * fill seat, and the graph does not carry faces — so a selection whose charPr
 * appears in neither publisher gets NO name, which is correct: nothing on the
 * wire said what it is.
 *
 * Every pair here is one the runtime stated. Nothing is inferred from another
 * id, nothing is inherited from the baseline, and an id absent from the map is
 * absent from the toolbar.
 */
function faceIndex(inspect: InspectResult | null): Map<string, TypefaceByLang> {
  const index = new Map<string, TypefaceByLang>();
  if (!inspect) return index;
  const add = (id: string | undefined | null, face: TypefaceByLang | null | undefined) => {
    if (!id || !face) return;
    if (!index.has(id)) index.set(id, face);
  };
  add(inspect.summary.baselineCharPr?.id, inspect.summary.baselineCharPr?.face);
  add(inspect.summary.blackCharPr?.id, inspect.summary.blackCharPr?.face);
  for (const region of inspect.regions.regions) {
    add(region.charPr, region.charPrFace);
    add(region.charPrSuggested, region.charPrSuggestedFace);
  }
  return index;
}

/** The 한글 face, which is the one a Korean form is set in. */
function primaryFace(face: TypefaceByLang | undefined): string | null {
  return face?.hangul ?? null;
}

/** Every language the header resolved, for the tooltip. Never merged. */
function allFaces(face: TypefaceByLang | undefined): string {
  if (!face) return "";
  const LANG: Record<string, string> = {
    hangul: "한글",
    latin: "영문",
    hanja: "한자",
    japanese: "일어",
    other: "기타",
    symbol: "기호",
    user: "사용자",
  };
  return Object.entries(face)
    .filter(([, name]) => !!name)
    .map(([lang, name]) => `${LANG[lang] ?? lang} ${name}`)
    .join(" · ");
}

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

  const faces = faceIndex(inspect);
  const typefaces = inspect?.summary.typefaces ?? null;
  const face = charPr.id ? faces.get(charPr.id) : undefined;
  const suggestedFace = charPr.suggested ? faces.get(charPr.suggested) : undefined;
  const name = primaryFace(face);
  const suggestedName = primaryFace(suggestedFace);
  // "this document names none" vs "nothing looked" — the whole reason §14 has
  // two fields. The toolbar prints a different dash for each.
  const faceUnknown =
    !typefaces || typefaces.state !== "read"
      ? (typefaces?.reason ?? "이 빌드는 글꼴 이름을 읽지 못했습니다")
      : null;

  return (
    <div className="toolbar" data-testid="editor-toolbar" role="toolbar" aria-label="편집 도구">
      {/* 글꼴. The face the DOCUMENT declares, never a default (§14). */}
      <div className="tool-group" data-testid="tool-typeface">
        <span className="tool-label">글꼴</span>
        <span
          className="tool-value"
          data-testid="typeface-name"
          data-face={name ?? ""}
          title={
            name
              ? `이 문서가 선언한 글꼴입니다 — ${allFaces(face)}`
              : faceUnknown
                ? `글꼴 이름을 읽을 수 없었습니다 — ${faceUnknown}`
                : charPr.id
                  ? "이 문서는 이 글자 모양에 쓸 글꼴 이름을 선언하지 않았습니다."
                  : "선택한 곳이 없습니다."
          }
        >
          {name ?? "—"}
        </span>
        {!name && charPr.id ? (
          <span className="tool-note tiny" data-testid="typeface-absent">
            {faceUnknown ? "읽지 못함" : "문서가 이름을 안 밝힘"}
          </span>
        ) : null}
      </div>

      <div className="tool-sep" />

      {/* 글자 모양. The id stays: it is what a plan op carries, and it is what
          the T30 preflight names. The mismatch tag reads in NAMES now. */}
      <div className="tool-group" data-testid="tool-charpr">
        <span className="tool-label">글자 모양</span>
        <span className="tool-value mono" title={charPr.where || "선택한 곳이 없습니다"}>
          {charPr.id ?? "—"}
        </span>
        {anomalous ? (
          <Tag
            tone="warn"
            title={
              suggestedName && name
                ? `이 자리는 ${name}(charPr ${charPr.id}) 을 물려받는데, 서식 검사가 권하는 본문 모양은 ${suggestedName}(charPr ${charPr.suggested}) 입니다`
                : `이 문서의 본문 모양은 charPr ${charPr.suggested} 입니다`
            }
          >
            {suggestedName && name && suggestedName !== name
              ? `본문은 ${suggestedName}`
              : "본문과 다름"}
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

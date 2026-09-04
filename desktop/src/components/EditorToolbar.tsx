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
import {
  applyUiZoom,
  exportApplied,
  openViaDialog,
  requestApprovalForDraft,
  runCheck,
  stepUiZoom,
} from "../actions";
import {
  activeText,
  canRenderPages,
  canRequestApproval,
  cellKey,
  setCenterMode,
  setState,
  setView,
  setZoom,
  useWorkspace,
  type Selection,
} from "../store";
import type { InspectResult, RegionText, TypefaceByLang } from "../types";
import { Tag } from "./Tag";

/**
 * A menu in the band: a disclosure, not a popup.
 *
 * The five actions above earn their place in the strip because people reach for
 * them constantly. Everything else — the font the document declares, the shape
 * id, the size, the app zoom — is something a person LOOKS UP, once, when they
 * have a question. Those used to be six always-on fields competing with the
 * actions for the same 40 pixels, which is most of why the band read as a
 * dashboard rather than as a toolbar.
 *
 * `<details>` rather than a floating panel on purpose: its content stays in the
 * DOM when closed, so nothing here becomes unreachable to a screen reader or to
 * the evidence harness, and there is no z-index, no outside-click handler and
 * no portal to keep in step with the window.
 */
function ToolMenu({
  label,
  testId,
  summary,
  children,
}: {
  label: string;
  testId: string;
  /** What the closed menu shows, so a glance still answers the question. */
  summary?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <details className="toolmenu" data-testid={testId}>
      <summary>
        <span className="tool-label">{label}</span>
        {summary ? <span className="tool-value">{summary}</span> : null}
      </summary>
      <div className="toolmenu-body">{children}</div>
    </details>
  );
}

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

/**
 * The same map, plus the faces the RUN inventory carries (§14, fourth field).
 *
 * A caret stands in a paragraph run, and a run's charPr appears in neither
 * publisher `faceIndex` reads — so until `runs[].charpr_face` reached the wire
 * this strip could print nothing but the integer above a caret. Read out of
 * `texts` rather than through a new call: `beginParagraphEdit` files the
 * region it asked for there precisely so the toolbar does not ask the runtime
 * a second time to name what it has already been told.
 */
function faceIndexWithRuns(
  inspect: InspectResult | null,
  texts: RegionText[],
): Map<string, TypefaceByLang> {
  const index = faceIndex(inspect);
  for (const region of texts) {
    for (const run of region.runs ?? []) {
      if (run.charpr && run.charpr_face && !index.has(run.charpr)) {
        index.set(run.charpr, run.charpr_face);
      }
    }
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
  caretRun: number | null,
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
    // Paragraph runs carry their own charPr, from document/readRegion. With a
    // caret open this is the run the caret is standing IN, which is the whole
    // reason the strip can name a face here at all.
    const region = texts.find((row) => row.at_para === selection.atPara);
    const run = caretRun !== null ? region?.runs?.find((r) => r.index === caretRun) : region?.runs?.[0];
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
  const inlineEdit = useWorkspace((s) => s.inlineEdit);
  const caret = inlineEdit?.kind === "run" ? inlineEdit : null;
  const charPr = seatCharPr(selection, inspect, texts, caret?.run ?? null);
  const queued = useWorkspace((s) => s.draft.ops.length);
  const approvalPhase = useWorkspace((s) => s.approvalPhase);
  const applied = useWorkspace((s) => s.applied);
  const checkPhase = useWorkspace((s) => s.checkPhase);
  const findings = useWorkspace((s) => s.findings);
  const exportPhase = useWorkspace((s) => s.exportPhase);
  const canApprove = useWorkspace(canRequestApproval);

  const baseline = inspect?.summary.baselineCharPr ?? null;
  const hard = findings.filter((f) => f.severity === "hard").length;
  const anomalous = charPr.suggested !== null && charPr.id !== charPr.suggested;

  const faces = faceIndexWithRuns(inspect, texts);
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
      {/* THE FIVE ACTIONS, first and unqualified.
          Until now these were scattered across four places — 열기 in the title
          bar, 검사 here, 내보내기 in the verification bar, 되돌리기 behind a tab
          in the other view, 승인 in the right-hand panel — and a person doing
          the ordinary loop had to learn where each of them lived. They are one
          row now. The panels that own the detail still own it; these are the
          doors. Each says why it is unavailable rather than being greyed in
          silence. */}
      <div className="tool-actions" data-testid="tool-actions">
        <button
          className="action"
          data-testid="act-open"
          title="문서 열기 (Ctrl+O)"
          onClick={() => void openViaDialog()}
        >
          열기
        </button>
        <button
          className="action"
          data-testid="act-export"
          disabled={!applied || exportPhase === "starting"}
          title={
            applied
              ? "후보본과 영수증을 함께 저장합니다"
              : "아직 내보낼 후보본이 없습니다. 편집을 승인해 적용하면 생깁니다."
          }
          onClick={() => void exportApplied()}
        >
          {exportPhase === "starting" ? "내보내는 중…" : "저장/내보내기"}
        </button>
        <button
          className="action"
          data-testid="act-undo"
          title="되돌리기와 후보본 계보를 봅니다"
          onClick={() => {
            setView("agent");
            setState({ agentTab: "history" });
          }}
        >
          되돌리기
        </button>
        <button
          className="action"
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
        <button
          className={approvalPhase === "pending" ? "action point" : "action"}
          data-testid="act-approve"
          disabled={approvalPhase !== "pending" && !canApprove}
          title={
            approvalPhase === "pending"
              ? "승인 게이트가 열려 있습니다. 오른쪽 패널에서 결정합니다."
              : canApprove
                ? "대기 중인 편집의 승인을 요청합니다"
                : "승인을 요청할 편집이 없습니다. 채움 자리에 값을 넣으면 대기열에 쌓입니다."
          }
          onClick={() => {
            if (approvalPhase === "pending") {
              document
                .querySelector('[data-testid="approval-gate"]')
                ?.scrollIntoView({ block: "center" });
              return;
            }
            void requestApprovalForDraft();
          }}
        >
          {approvalPhase === "pending" ? "승인 대기" : "승인"}
        </button>
      </div>

      <div className="tool-sep" />

      {/* 서식 — looked up, not watched. §14's two absences stay apart inside. */}
      <ToolMenu
        label="서식"
        testId="tool-format"
        summary={name ?? (charPr.id !== null ? `charPr ${charPr.id}` : "—")}
      >
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

      {/* 크기, AND WHOSE SIZE IT IS.
          Two different facts share this control and they are never merged.
          `baselineCharPr.height_pt` is what the document's HEADER declares for
          the body shape. `span.sizePt` is what the RENDERER drew the caret's
          line at, read out of the PDF. §14.1 is explicit that a run's charPr
          carries no point size of its own, so with a caret open the honest
          number is the render's — labelled 지면에서 잰 값, because a measured
          size presented as a declared one would be the same class of
          fabrication as a font name nobody declared. A line set in two sizes
          at once carries no `sizePt` at all and falls back to the baseline. */}
      <div className="tool-group" data-testid="tool-size">
        <span className="tool-label">크기</span>
        <span
          className="tool-value mono"
          data-testid="size-value"
          data-source={caret?.sizePt ? "render" : "baseline"}
          title={
            caret?.sizePt
              ? "커서가 선 줄을 렌더러가 그린 크기입니다. 문서가 선언한 값이 아니라 지면에서 잰 값입니다."
              : "이 문서가 본문 글자 모양에 선언한 크기입니다."
          }
        >
          {caret?.sizePt ? `${caret.sizePt}pt` : baseline ? `${baseline.height_pt}pt` : "—"}
        </span>
        <span className="tool-note tiny">{caret?.sizePt ? "지면에서 잰 값" : "본문 기준"}</span>
      </div>
      </ToolMenu>

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
      </div>

      <div className="tool-sep" />

      {/* 화면 — the WHOLE application's scale, not the document's. Two numbers
          that both read as a percentage sat side by side in the strip and were
          routinely mistaken for each other; the one people change with the
          keyboard belongs in a menu that names its own shortcuts. */}
      <ToolMenu label="화면" testId="tool-uizoom" summary={`${Math.round(uiZoom * 100)}%`}>
        <div className="tool-group zoomer">
          <button
            className="ghost"
            aria-label="화면 축소"
            title="Ctrl+−"
            disabled={uiZoom <= 0.5}
            onClick={() => stepUiZoom(-1)}
          >
            −
          </button>
          <button
            className="tool-value mono"
            data-testid="uizoom-value"
            title="Ctrl+0 으로 되돌립니다"
            disabled={uiZoom === 1}
            onClick={() => void applyUiZoom(1)}
          >
            {Math.round(uiZoom * 100)}%
          </button>
          <button
            className="ghost"
            aria-label="화면 확대"
            title="Ctrl+="
            disabled={uiZoom >= 2}
            onClick={() => stepUiZoom(1)}
          >
            +
          </button>
        </div>
        <p className="tool-note tiny">
          창 전체를 키웁니다. 문서만 키우려면 왼쪽의 문서 배율을 쓰십시오. Ctrl+= · Ctrl+− ·
          Ctrl+0
        </p>
      </ToolMenu>
    </div>
  );
}

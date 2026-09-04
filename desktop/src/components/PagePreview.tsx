/**
 * 페이지 보기 — the real page, when there is one, and precisely why when not.
 *
 * The Runtime can now rasterise (`document/render`) and can now make the PDF
 * to rasterise from (`document/renderPrepare`). Neither of those makes a page
 * appear on demand, and the honest states are the interesting part of this
 * component rather than an afterthought bolted to it:
 *
 * `available: false` is a RESULT, not an error (§11.1). The reason comes from
 * a closed set, so this switches on it exhaustively instead of matching on
 * prose, and each branch says what would actually change the answer:
 *
 *   needs_conversion         an HWPX — the prepare step is what makes a PDF
 *   rasterizer_missing       a PDF is here, PyMuPDF is not importable
 *   no_rasterizable_artifact nothing here is a PDF
 *   artifact_missing         a run was named and its bytes are gone
 *
 * And the prepare step's own refusals are drawn, not swallowed. On THIS
 * machine the Hancom COM server is broken — `CoCreateInstance` fails — so a
 * live click returns `convert_failed` with the converter's exit code and its
 * stderr tail. That is the true state of this machine, so it is rendered as a
 * designed state with the runtime's own `detail` verbatim and guidance about
 * what a person can do, rather than as a generic error toast. `com_busy` gets
 * the same treatment and says explicitly that the Runtime will not kill
 * somebody else's Hancom, because that restraint is a feature with four RPC
 * crashes behind it (`engine/scripts/guards.py:234-240`).
 *
 * **A raster is not evidence.** Every successful result carries
 * `evidence.class = "structural_only"` and `proofGrade: "none"`, and the strip
 * under the page repeats it. Seeing what bytes draw is not knowing they are
 * the right bytes, and the verification bar keeps saying 증명 없음 throughout.
 */
import { useEffect, useLayoutEffect, useRef } from "react";

import {
  layoutEcho,
  loadChangedAddresses,
  loadGeometry,
  preparePages,
  renderCurrentPage,
  type LayoutEcho,
} from "../actions";
import {
  canPreparePages,
  fitScale,
  headCandidate,
  setFittedZoom,
  setPageFit,
  setZoom,
  useWorkspace,
} from "../store";
import type {
  GeometryResult,
  InspectResult,
  RenderResult,
  RuntimeError,
  SkippedElement,
} from "../types";
import { GeometryLegend, PageOverlay } from "./PageOverlay";
import { Tag } from "./Tag";

/** HWPUNIT is 1/7200 inch. */
const HWPUNIT_PER_INCH = 7200;
const HWPUNIT_PER_CM = HWPUNIT_PER_INCH / 2.54;

/**
 * A ruler over the page, from the page's own geometry.
 *
 * Every number here is `summary.pageMetrics` — real width, real margins, in
 * HWPUNIT straight from the document. The ruler is a Hangul-editor convention
 * and it is also the honest way to show margins: a person who wants to know
 * where the text block starts can read it off the shaded ends rather than
 * opening a dialog.
 *
 * Centimetres, not inches: the corpus form is A4 with 20 mm margins and the
 * whole 기안문 tradition is metric. The tick interval is 1 cm with a longer
 * mark every 5.
 */
function Ruler({ inspect, zoom }: { inspect: InspectResult; zoom: number }) {
  const metrics = inspect.summary.pageMetrics;
  const scale = (96 / HWPUNIT_PER_INCH) * 0.62 * zoom;
  const width = metrics.width * scale;
  const left = (metrics.margin.left ?? 0) * scale;
  const right = (metrics.margin.right ?? 0) * scale;
  const step = HWPUNIT_PER_CM * scale;
  const ticks = Math.max(0, Math.floor(metrics.width / HWPUNIT_PER_CM));

  return (
    <div className="ruler" style={{ width: `${width}px` }} data-testid="page-ruler">
      <div className="ruler-margin left" style={{ width: `${left}px` }} />
      <div className="ruler-margin right" style={{ width: `${right}px` }} />
      {Array.from({ length: ticks + 1 }, (_, index) => (
        <i
          key={index}
          className={index % 5 === 0 ? "tick major" : "tick"}
          style={{ left: `${index * step}px` }}
        >
          {index % 5 === 0 ? <span>{index}</span> : null}
        </i>
      ))}
      <span className="ruler-unit latin-caps">cm</span>
    </div>
  );
}

/** The page-geometry figure. Real numbers, captioned so it cannot be mistaken. */
function Geometry({ inspect, zoom, page }: { inspect: InspectResult; zoom: number; page: number }) {
  const metrics = inspect.summary.pageMetrics;
  const scale = (96 / HWPUNIT_PER_INCH) * 0.62 * zoom;
  const m = metrics.margin;
  return (
    <div
      className="pagefigure"
      style={{ width: `${metrics.width * scale}px`, height: `${metrics.height * scale}px` }}
      aria-label="용지와 여백 치수"
      data-testid="page-geometry"
    >
      <div
        className="margins"
        style={{
          left: `${(m.left ?? 0) * scale}px`,
          right: `${(m.right ?? 0) * scale}px`,
          top: `${((m.top ?? 0) + (m.header ?? 0)) * scale}px`,
          bottom: `${((m.bottom ?? 0) + (m.footer ?? 0)) * scale}px`,
        }}
      />
      <div className="caption">
        <span className="latin-caps">
          page geometry · {page}쪽 · {Math.round(zoom * 100)}%
        </span>
      </div>
    </div>
  );
}

/**
 * WHICH RENDERER DREW THIS PAGE, said on the page.
 *
 * Three tiers can produce a raster now (§11.1c) and they are not equally
 * trustworthy. A page our own renderer drew looks, at a glance, exactly like
 * one Hancom laid out — same paper, same glyphs, same rules — and that
 * resemblance is precisely the problem: a user comparing a form against a
 * submission deadline needs to know whether they are looking at the office
 * suite's own layout or at our reading of the format.
 *
 * So the badge is not decoration and it is not a hover. It sits above the page,
 * it names the tier in Korean, and for our own renderer it carries 미인증 in
 * the word itself — because "uncertified" is the whole claim, and a badge that
 * said only 자체 렌더 would read as a brand rather than as a caveat.
 */
const GRADE_LABEL: Record<string, string> = {
  hancom: "한컴 렌더",
  pdf: "PDF 렌더",
  "own-uncertified": "자체 렌더 · 미인증",
};

const GRADE_NOTE: Record<string, string> = {
  hancom: "한컴이 만든 PDF를 그대로 이미지로 옮긴 지면입니다.",
  pdf: "이 세션이 이미 가지고 있던 PDF를 이미지로 옮긴 지면입니다. 그 PDF를 누가 어떻게 짰는지는 이 빌드가 알 수 있는 것이 아닙니다.",
  "own-uncertified":
    "한컴 없이 우리 렌더러가 직접 그린 지면입니다. 한컴이 그린 지면과 맞춰 검증한 적이 없습니다 — 아래 목록이 못 그린 것들입니다.",
};

function GradeBadge({ render }: { render: RenderResult }) {
  const grade = render.grade ?? "unknown";
  const label = GRADE_LABEL[grade] ?? grade;
  const own = grade === "own-uncertified";
  return (
    <div className="gradebar" data-testid="render-grade" data-grade={grade} data-tier={render.tier}>
      <Tag tone={own ? "warn" : "ok"}>{label}</Tag>
      <span className="grade-note">{GRADE_NOTE[grade] ?? (render.gradeMeaning ?? "")}</span>
      {render.renderer?.id ? (
        <span className="mono tiny" data-testid="render-engine">
          {render.renderer.id}
          {render.renderer.version ? ` ${render.renderer.version}` : ""}
        </span>
      ) : null}
    </div>
  );
}

/**
 * 무엇을 못 그렸나 — one click, and the renderer's own words.
 *
 * The list arrives verbatim from the sidecar and is printed verbatim: element,
 * reason, count. Not summarised into "몇 개 요소 생략" — the useful part is
 * WHICH element and WHY, and a count on its own tells a person nothing they can
 * check against their document.
 *
 * An empty list is stated, not hidden. "This renderer drew everything it found"
 * is a claim worth making, and a disclosure that silently disappears would let
 * a reader assume nothing was skipped on a page where nobody looked.
 */
function SkippedElements({ skipped }: { skipped: SkippedElement[] }) {
  const total = skipped.reduce((sum, entry) => sum + (entry.count || 0), 0);
  return (
    <details className="disclosure skipped" data-testid="skipped-list" data-count={skipped.length}>
      <summary>
        무엇을 못 그렸나{" "}
        <span className="mono tiny">
          {skipped.length === 0 ? "없음" : `${skipped.length}종 · ${total}개`}
        </span>
      </summary>
      {skipped.length === 0 ? (
        <p className="tiny">이 지면에서는 렌더러가 만난 것을 모두 그렸다고 보고했습니다.</p>
      ) : (
        <ul className="skipped-items">
          {skipped.map((entry) => (
            <li key={`${entry.element}·${entry.reason}`} data-testid="skipped-item">
              <code className="mono">{entry.element}</code>
              <span className="count mono">×{entry.count}</span>
              <span className="why">{entry.reason}</span>
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}

/** Which declared typefaces were drawn with something else. Tier 3 only. */
function FontSubstitutions({ render }: { render: RenderResult }) {
  const fonts = render.fonts;
  if (!fonts || fonts.state !== "read") return null;
  const substituted = fonts.substituted ?? [];
  return (
    <p className="raster-note" data-testid="font-substitution" data-substituted={substituted.length}>
      <Tag tone={substituted.length > 0 ? "warn" : "none"}>
        {substituted.length > 0 ? `글꼴 대체 ${substituted.length}` : "글꼴 대체 없음"}
      </Tag>
      <span>
        {substituted.length > 0
          ? substituted
              .map((f) => `${f.declared ?? "?"} → ${f.drawnWith ?? "?"}(${f.characters ?? 0}자)`)
              .join(" · ")
          : `문서가 선언한 글꼴 ${fonts.facesTotal ?? 0}종을 모두 이 기계에서 찾았습니다.`}
      </span>
    </p>
  );
}

/**
 * The overlay is drawn only when its layout and the raster came from the SAME
 * renderer. Never mix tiers on one page.
 *
 * The two answers are independent calls and either can be stale — a geometry
 * cached from a PDF read while the raster in front of the user is now our own,
 * say. Rects from one renderer over pixels from another are the single most
 * convincing way this product could lie: every rectangle would look measured
 * and every one of them would be in the wrong place.
 */
function tiersAgree(render: RenderResult | null, geometry: GeometryResult | null): boolean {
  if (!render?.available || !geometry?.available) return false;
  const rasterOwn = render.grade === "own-uncertified";
  const geometryOwn = geometry.geometrySource === "own";
  return rasterOwn === geometryOwn;
}

function TierMismatch() {
  return (
    <p className="raster-note" data-testid="overlay-tier-mismatch">
      <Tag tone="warn">겹판 보류</Tag>
      <span>
        이 지면을 그린 렌더러와 글줄 위치를 잰 렌더러가 서로 다릅니다. 한쪽의 자리를 다른 쪽
        그림 위에 얹으면 잰 것처럼 보이는 틀린 자리가 됩니다 — 그래서 아무것도 그리지 않습니다.
      </span>
    </p>
  );
}

/** What the user can do about a refusal, per code. Never a bare error string. */
function prepareGuidance(code: string): string {
  switch (code) {
    case "needs_hancom":
      // NOT "한컴이 없습니다". This branch fires whenever the runtime cannot
      // reach the converter, and on this machine the reason is that the frozen
      // sidecar carries no pyhwpx while Hancom itself is installed and running
      // — so the old copy asserted something about the machine that the runtime
      // never said, directly under the runtime's own words saying otherwise.
      // The reason line above is the fact; this is what to do about it.
      return "런타임이 변환기에 닿지 못했습니다. 위에 적힌 이유가 실제 원인입니다. 한컴이 설치되고 변환기를 쓸 수 있는 기계에서 열거나, 이미 PDF인 문서를 여십시오.";
    case "com_busy":
      return "한컴이 이미 떠 있습니다. 그 창을 닫고 다시 누르십시오. 런타임은 남의 한컴을 대신 종료하지 않습니다 — 그렇게 했다가 서로의 작업을 죽인 적이 있습니다.";
    case "not_convertible":
      return "이 문서는 변환기가 받는 형식이 아닙니다.";
    case "convert_failed":
      return "변환기가 실행됐지만 쓸 만한 PDF를 남기지 못했습니다. 한컴 COM 등록이 깨졌을 때 이렇게 보입니다. 한컴을 한 번 직접 실행해 초기화한 뒤 다시 시도해 보십시오.";
    default:
      return "런타임이 이 요청을 거절했습니다.";
  }
}

function PrepareRefusal({ error }: { error: RuntimeError }) {
  const data = (error.data ?? {}) as Record<string, unknown>;
  return (
    <div className="unavailable" data-testid="prepare-refusal">
      <div className="unavailable-head">
        <Tag tone="bad">페이지 그림을 만들지 못했습니다</Tag>
        <code className="mono">{error.code}</code>
      </div>
      {/* The runtime's own words first. Ours after. */}
      <p className="reason" data-testid="prepare-detail">
        {error.message}
      </p>
      <p>{prepareGuidance(error.code)}</p>
      {typeof data.exitCode === "number" ? (
        <p className="mono tiny">converter exit {String(data.exitCode)}</p>
      ) : null}
      {typeof data.stderr === "string" && data.stderr.trim().length > 0 ? (
        <details className="disclosure">
          <summary>변환기가 남긴 말</summary>
          <pre>{data.stderr}</pre>
        </details>
      ) : null}
      <p className="tiny">
        원본은 이 과정에 들어가지 않습니다. 변환은 세션이 가진 사본에만 일어납니다.
      </p>
    </div>
  );
}

/**
 * Geometry that did not arrive, said in the runtime's own words.
 *
 * Deliberately NOT a second unavailable screen. `document/render` and
 * `document/pageGeometry` share one closed reason set (§12.2), so when there is
 * no raster there is no geometry either and `Unavailable` above has already
 * explained why — printing it twice would be noise. This line only appears in
 * the case the shared reason set does not cover: a page that DID draw while its
 * geometry did not, which on a machine without PyMuPDF cannot happen and on a
 * machine with it means something more interesting went wrong.
 */
function GeometryUnavailable({ geometry }: { geometry: GeometryResult }) {
  return (
    <p className="raster-note" data-testid="overlay-unavailable">
      <Tag tone="none">겹판 없음</Tag>
      <span data-testid="overlay-reason">
        document/pageGeometry unavailable.{geometry.unavailable?.reason ?? "unknown"} —{" "}
        {geometry.unavailable?.detail ?? ""}
      </span>
    </p>
  );
}

/**
 * E1.2 — the page is the SOURCE and the document is a candidate. Say so.
 *
 * After an apply there is a newer document than the one this raster was drawn
 * from, and on this machine there is no way to draw the newer one: the frozen
 * sidecar carries no `pyhwpx`, so `renderPrepare` answers `needs_hancom`, and
 * with a Hancom window open it answers `com_busy` instead. Both are real, both
 * are refusals, and neither of them is a reason to fake a page.
 *
 * So the raster stays, labelled, with the affected regions marked from the
 * addresses the RUNTIME's own receipts name — and 다시 그리기 asks for the
 * candidate's page and prints whatever comes back, success or refusal.
 *
 * WHAT THIS WILL NOT DO is paint the edited text onto the raster. The overlay's
 * rule (§12.2) is that every rectangle on the page came out of the renderer's
 * own layout; drawing new glyphs at guessed positions would break it in the
 * most convincing way available — a page that looks right and is not.
 */
function CandidateDiffers({ echo }: { echo: LayoutEcho }) {
  const preparePhase = useWorkspace((s) => s.preparePhase);
  const canPrepare = useWorkspace(canPreparePages);
  return (
    <div className="unavailable" data-testid="layout-echo">
      <div className="unavailable-head">
        <Tag tone="warn">후보본과 다름 — 이 그림은 원본 기준</Tag>
        <code className="mono">{echo.runId.slice(0, 12)}</code>
      </div>
      <p>
        승인한 편집이 담긴 후보본이 있지만, 이 지면 그림은 아직{" "}
        {/* `kind` is the runtime's own word — `session_source_pdf`,
            `prepared_pdf`, `candidate_pdf`. Anything that is not a candidate
            was drawn from the source one way or another, and printing the raw
            token instead would make a person guess. */}
        {echo.rendered.kind.startsWith("candidate")
          ? `다른 후보본(${echo.rendered.runId?.slice(0, 12) ?? "알 수 없음"})`
          : "원본"}
        을 그린 것입니다. 후보본을 그리려면 한 번 더 변환해야 합니다.
      </p>
      <p className="mono tiny">
        그림의 출처 {echo.rendered.kind}
        {echo.rendered.sha256 ? ` · ${echo.rendered.sha256.slice(0, 12)}` : ""}
      </p>
      <p className="mono tiny" data-testid="layout-echo-changed">
        {echo.changed.length > 0
          ? `달라진 자리 ${echo.changed.length}곳: ${echo.changed.join(" ")}`
          : "달라진 자리 목록을 아직 읽지 못했습니다 — 영수증과 계획을 읽는 중입니다"}
      </p>
      <p className="tiny">
        바뀐 글자를 이 그림 위에 그려 넣지는 않습니다. 그것은 편집기가 지어낸
        지면이지 렌더러가 그린 지면이 아니기 때문입니다.
      </p>
      {canPrepare ? (
        <button
          className="action primary"
          data-testid="echo-redraw"
          disabled={preparePhase === "starting"}
          title="후보본을 PDF로 바꿔 다시 그립니다. 원본은 건드리지 않습니다."
          onClick={() => void preparePages(echo.runId)}
        >
          {preparePhase === "starting" ? "한컴을 부르는 중…" : "다시 그리기"}
        </button>
      ) : (
        <p className="reason">
          document/renderPrepare 가 이 연결에 없습니다. 후보본을 그릴 방법이
          없습니다.
        </p>
      )}
    </div>
  );
}

function Unavailable({ render }: { render: RenderResult }) {
  const reason = render.unavailable?.reason ?? "unknown";
  const detail = render.unavailable?.detail ?? "";
  const heading: Record<string, string> = {
    needs_conversion: "이 문서는 아직 그림으로 만들 수 없습니다",
    rasterizer_missing: "PDF는 있지만 그릴 도구가 없습니다",
    no_rasterizable_artifact: "여기에는 그림으로 만들 것이 없습니다",
    artifact_missing: "가리킨 파일이 사라졌습니다",
  };
  const nextStep: Record<string, string> = {
    needs_conversion:
      "아래 “페이지 그림 만들기”가 한컴을 불러 사본을 PDF로 바꿉니다. 원본은 건드리지 않습니다.",
    rasterizer_missing:
      "이 런타임에 PyMuPDF가 없습니다. 선택 의존성이라 없을 수 있고, 없으면 없다고 말합니다.",
    no_rasterizable_artifact: "PDF인 문서를 열거나, 먼저 PDF를 만들어야 합니다.",
    artifact_missing: "그 후보본의 바이트가 더 이상 디스크에 없습니다.",
  };
  return (
    <div className="unavailable" data-testid="preview-unavailable">
      <h2>{heading[reason] ?? "페이지 그림이 없습니다"}</h2>
      <p>{nextStep[reason] ?? ""}</p>
      <p className="reason" data-testid="render-reason">
        document/render unavailable.{reason}
        {"\n"}
        {detail}
      </p>
      {/* The THIRD tier's own refusal. Without this a user is told only about
          the Hancom they do not have, and never that the renderer we DO ship
          also declined — which is the half they can act on. */}
      {render.unavailable?.own ? (
        <p className="reason" data-testid="own-refusal" data-reason={render.unavailable.own.reason}>
          자체 렌더러도 그리지 못했습니다 ({render.unavailable.own.reason})
          {"\n"}
          {render.unavailable.own.detail}
        </p>
      ) : null}
    </div>
  );
}

export function PagePreview({ inspect }: { inspect: InspectResult }) {
  const zoom = useWorkspace((s) => s.zoom);
  const pageFit = useWorkspace((s) => s.pageFit);
  const page = useWorkspace((s) => s.page);
  const render = useWorkspace((s) => s.render);
  const renderPhase = useWorkspace((s) => s.renderPhase);
  const renderError = useWorkspace((s) => s.renderError);
  const preparePhase = useWorkspace((s) => s.preparePhase);
  const prepareError = useWorkspace((s) => s.prepareError);
  const prepareNote = useWorkspace((s) => s.prepareNote);
  const canPrepare = useWorkspace(canPreparePages);
  const sessionId = useWorkspace((s) => s.activeSessionId);
  const geometry = useWorkspace((s) => s.geometry);
  const echo = useWorkspace(layoutEcho);
  const head = useWorkspace(headCandidate);

  // Read the plans behind the head's chain so the echo can name the regions
  // that changed. Nothing is marked until the runtime has said which ones.
  useEffect(() => {
    if (head?.runId) void loadChangedAddresses(head.runId);
  }, [head?.runId]);

  // Ask once when the mode is entered. A render is a real call with a real
  // cost; it is not re-run on every zoom nudge.
  useEffect(() => {
    if (sessionId && renderPhase === "idle") void renderCurrentPage();
  }, [sessionId, renderPhase]);

  // Geometry follows the PAGE, never the zoom. `page` is in the dependency
  // list and `zoom` is deliberately not: the rects are fractions of the page,
  // so a zoom change re-lays out the overlay from numbers already in hand and
  // asks the runtime nothing (§12.1). `loadGeometry` serves its own per-page
  // cache on the way back to a page that was already read, so paging back and
  // forth is one call per page for the life of the session.
  //
  // AFTER the raster, not beside it. Tier 3's geometry reads the render's own
  // sidecar and never starts a render of its own (§11.1c), so a geometry call
  // that won the race against the first render would cache `needs_conversion`
  // for a page that is about to exist and the overlay would never appear.
  useEffect(() => {
    if (sessionId && renderPhase === "ready") void loadGeometry(page);
  }, [sessionId, page, renderPhase]);

  const image = render?.available ? render.image : undefined;
  const pageCount = render?.pageCount ?? 1;

  // --- fitting the page to the window ---------------------------------------
  //
  // Measured, not computed from a guess about the window: the scroller's own
  // box is the only thing that knows how much room the panels left. A layout
  // effect so the first paint is already fitted, and a ResizeObserver so it
  // stays fitted — a 폭 맞춤 that stopped fitting on the first drag of the
  // window edge would be a label that lies.
  //
  // This asks the runtime NOTHING. The raster is drawn at its own dpi and
  // scaled by CSS; the overlay rects are page fractions. One number changes.
  const scroller = useRef<HTMLDivElement>(null);
  const pageWidthCss = image ? (image.widthPx / (render?.dpi ?? 96)) * 96 : 0;
  const pageHeightCss = image ? (image.heightPx / (render?.dpi ?? 96)) * 96 : 0;

  useLayoutEffect(() => {
    if (pageFit === "free" || !scroller.current || pageWidthCss <= 0) return;
    const box = scroller.current;
    const apply = () => {
      const styles = window.getComputedStyle(box);
      const padding =
        parseFloat(styles.paddingLeft || "0") + parseFloat(styles.paddingRight || "0");
      const next = fitScale(
        pageFit,
        { width: pageWidthCss, height: pageHeightCss },
        // A little slack for the scrollbar, so 폭 맞춤 does not itself create
        // the horizontal scroll it is meant to remove.
        { width: box.clientWidth - padding - 12, height: box.clientHeight - 96 },
        zoom,
      );
      if (Math.abs(next - zoom) > 0.002) {
        setFittedZoom(next);
      }
    };
    apply();
    const observer = new ResizeObserver(apply);
    observer.observe(box);
    return () => observer.disconnect();
  }, [pageFit, pageWidthCss, pageHeightCss, zoom]);

  // ONE ruler, rendered directly above whichever page-like thing is drawn —
  // the raster when there is one, the geometry figure when there is not. Its
  // first placement was at the top of the scroller, which put it above the
  // refusal card explaining why there was no page, i.e. measuring nothing. A
  // ruler that is not touching the page it measures is decoration.
  const ruler = <Ruler inspect={inspect} zoom={zoom} />;

  const overlayOk = tiersAgree(render, geometry);

  return (
    <div className="center-scroll paged" data-testid="page-preview" ref={scroller}>
      {renderPhase === "starting" ? (
        <p className="empty">페이지를 그리는 중입니다.</p>
      ) : renderError ? (
        <div className="unavailable" data-testid="render-error">
          <h2>페이지를 그리지 못했습니다</h2>
          <p className="reason">
            {renderError.code}
            {"\n"}
            {renderError.message}
          </p>
        </div>
      ) : image?.data ? (
        <>
          {/* Above the page, not under it: a person must know the picture is
              out of date BEFORE they read it, not after they scroll past. */}
          {echo ? <CandidateDiffers echo={echo} /> : null}
          {/* WHICH RENDERER, above the paper. A person must know what they are
              looking at before they read it, not after. */}
          {render ? <GradeBadge render={render} /> : null}
          {ruler}
          {/* The raster and the overlay share ONE box, sized once. The overlay
              positions its children in percentages of it, so the two cannot
              drift apart at any zoom — there is no second scale factor to keep
              in step, which is the bug this shape exists to make impossible. */}
          <div
            className="page-stage"
            data-testid="page-stage"
            style={{ width: `${(image.widthPx / (render?.dpi ?? 96)) * 96 * zoom}px` }}
          >
            <img
              className="page-raster"
              data-testid="page-raster"
              src={`data:${image.mediaType};base64,${image.data}`}
              alt={`${page}쪽`}
            />
            {overlayOk && geometry ? (
              <PageOverlay geometry={geometry} stale={echo?.changed ?? []} />
            ) : null}
          </div>
          {overlayOk && geometry ? (
            <GeometryLegend geometry={geometry} />
          ) : geometry?.available ? (
            <TierMismatch />
          ) : geometry ? (
            <GeometryUnavailable geometry={geometry} />
          ) : null}
          {/* 무엇을 못 그렸나. One click, and always present on a page a
              renderer graded — an absent list would read as nothing skipped. */}
          {render?.elementsSkipped ? (
            <SkippedElements skipped={render.elementsSkipped} />
          ) : null}
          {render ? <FontSubstitutions render={render} /> : null}
          <p className="raster-note" data-testid="raster-evidence">
            <Tag tone="none">{render?.evidence?.proofGrade ?? "none"}</Tag>
            {render?.evidence?.note ??
              "페이지 그림은 바이트가 무엇을 그리는지 보여 줄 뿐, 그 바이트가 옳다는 증거가 아닙니다."}
          </p>
          <p className="mono tiny">
            {image.widthPx}×{image.heightPx}px · {render?.dpi}dpi ·{" "}
            {render?.source?.kind} · {image.sha256.slice(0, 12)}
          </p>
        </>
      ) : image ? (
        <div className="unavailable">
          <h2>그림이 너무 큽니다</h2>
          <p className="reason">{image.reason ?? "프레임에 담기에 큽니다."}</p>
          <p className="mono tiny">{image.path}</p>
        </div>
      ) : render ? (
        <Unavailable render={render} />
      ) : null}

      {prepareError ? <PrepareRefusal error={prepareError} /> : null}
      {prepareNote ? (
        <p className="prose" data-testid="prepare-note">
          {prepareNote}
        </p>
      ) : null}

      {!image ? (
        <>
          {ruler}
          <Geometry inspect={inspect} zoom={zoom} page={page} />
        </>
      ) : null}

      {/* The page footer. Hangul-editor shape: the page counter in the middle
          with arrows either side, the zoom at the right, and the one action
          this mode has on the left. Nothing here is a guess — `pageCount` is
          the renderer's own, and it is 1 when there is no raster because that
          is what the runtime returned. */}
      <div className="page-footer" data-testid="page-footer">
        {canPrepare ? (
          <button
            className="action primary"
            data-testid="prepare-pages"
            disabled={preparePhase === "starting"}
            title="세션 사본을 PDF로 바꿉니다. 원본은 건드리지 않습니다."
            onClick={() => void preparePages()}
          >
            {preparePhase === "starting" ? "한컴을 부르는 중…" : "페이지 그림 만들기"}
          </button>
        ) : null}

        <span className="spacer" />

        <div className="pager">
          <button
            className="ghost"
            data-testid="page-prev"
            aria-label="이전 쪽"
            disabled={page <= 1}
            onClick={() => void renderCurrentPage(page - 1)}
          >
            ◀
          </button>
          <span className="mono" data-testid="page-indicator">
            {page}쪽 / 전체 {pageCount}
          </span>
          <button
            className="ghost"
            data-testid="page-next"
            aria-label="다음 쪽"
            disabled={page >= pageCount}
            onClick={() => void renderCurrentPage(page + 1)}
          >
            ▶
          </button>
        </div>

        <span className="spacer" />

        {/* PAGE zoom, and the two fits people actually reach for. Distinct
            from 화면 (Ctrl+= / − / 0), which scales the whole application.
            Nothing here refetches: the raster is scaled by CSS and the overlay
            rects are page fractions (§12.1). */}
        <div className="pager zoomer" data-testid="page-zoomer" data-fit={pageFit}>
          <button
            className="ghost"
            data-testid="fit-width"
            aria-pressed={pageFit === "width"}
            title="창 너비에 맞춥니다. 창 크기가 바뀌어도 계속 맞춥니다."
            onClick={() => setPageFit(pageFit === "width" ? "free" : "width")}
          >
            폭 맞춤
          </button>
          <button
            className="ghost"
            data-testid="fit-page"
            aria-pressed={pageFit === "page"}
            title="한 쪽이 통째로 보이게 맞춥니다."
            onClick={() => setPageFit(pageFit === "page" ? "free" : "page")}
          >
            쪽 맞춤
          </button>
          <button className="ghost" aria-label="축소" onClick={() => setZoom(zoom - 0.1)} disabled={zoom <= 0.5}>
            −
          </button>
          <button
            className="mono"
            data-testid="page-zoom"
            title="100% 로 되돌립니다"
            onClick={() => setZoom(1)}
          >
            {Math.round(zoom * 100)}%
          </button>
          <button className="ghost" aria-label="확대" onClick={() => setZoom(zoom + 0.1)} disabled={zoom >= 4}>
            +
          </button>
        </div>
      </div>
    </div>
  );
}

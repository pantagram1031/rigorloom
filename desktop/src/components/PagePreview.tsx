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
import { useEffect } from "react";

import { preparePages, renderCurrentPage } from "../actions";
import { canPreparePages, setZoom, useWorkspace } from "../store";
import type { InspectResult, RenderResult, RuntimeError } from "../types";
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

/** What the user can do about a refusal, per code. Never a bare error string. */
function prepareGuidance(code: string): string {
  switch (code) {
    case "needs_hancom":
      return "이 기계에는 변환에 쓸 한컴오피스가 없습니다. 한컴이 설치된 기계에서 열거나, 이미 PDF인 문서를 여십시오.";
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
    </div>
  );
}

export function PagePreview({ inspect }: { inspect: InspectResult }) {
  const zoom = useWorkspace((s) => s.zoom);
  const page = useWorkspace((s) => s.page);
  const render = useWorkspace((s) => s.render);
  const renderPhase = useWorkspace((s) => s.renderPhase);
  const renderError = useWorkspace((s) => s.renderError);
  const preparePhase = useWorkspace((s) => s.preparePhase);
  const prepareError = useWorkspace((s) => s.prepareError);
  const prepareNote = useWorkspace((s) => s.prepareNote);
  const canPrepare = useWorkspace(canPreparePages);
  const sessionId = useWorkspace((s) => s.activeSessionId);

  // Ask once when the mode is entered. A render is a real call with a real
  // cost; it is not re-run on every zoom nudge.
  useEffect(() => {
    if (sessionId && renderPhase === "idle") void renderCurrentPage();
  }, [sessionId, renderPhase]);

  const image = render?.available ? render.image : undefined;
  const pageCount = render?.pageCount ?? 1;

  return (
    <div className="center-scroll paged" data-testid="page-preview">
      <Ruler inspect={inspect} zoom={zoom} />
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
          <img
            className="page-raster"
            data-testid="page-raster"
            src={`data:${image.mediaType};base64,${image.data}`}
            alt={`${page}쪽`}
            style={{ width: `${(image.widthPx / (render?.dpi ?? 96)) * 96 * zoom}px` }}
          />
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

      {!image ? <Geometry inspect={inspect} zoom={zoom} page={page} /> : null}

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

        <div className="pager">
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

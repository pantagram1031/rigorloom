/**
 * The centre surface of Document view.
 *
 * There is no page render, and this component says so.
 *
 * `capabilities.unavailable.renderProbe` on this build reads: *"not wired in
 * this slice; no renderer capability is reported and none is claimed"*. The
 * Runtime exposes no `document/render`, and `candidate/list` is empty until a
 * plan is applied — which a read-only phase never does. So the honest state is
 * the only state, and it quotes the runtime's own reason rather than
 * paraphrasing it.
 *
 * What IS drawn is `summary.pageMetrics`: real numbers the Runtime returned,
 * rendered to scale as a labelled page-geometry figure. It is captioned as
 * geometry so it can never be mistaken for a render of the content. Never
 * fabricate layout.
 */
import { setZoom, useWorkspace } from "../store";
import type { InspectResult } from "../types";

/** HWPUNIT is 1/7200 inch. */
const HWPUNIT_PER_INCH = 7200;

export function PagePreview({ inspect }: { inspect: InspectResult }) {
  const zoom = useWorkspace((s) => s.zoom);
  const page = useWorkspace((s) => s.page);
  const renderReason = useWorkspace((s) => s.capabilities?.unavailable?.renderProbe ?? null);
  const metrics = inspect.summary.pageMetrics;

  // 96 CSS px per inch, then the shared zoom. The figure is small on purpose:
  // it is a diagram of the page box, not a preview of the page.
  const scale = (96 / HWPUNIT_PER_INCH) * 0.62 * zoom;
  const w = metrics.width * scale;
  const h = metrics.height * scale;
  const m = metrics.margin;

  return (
    <div className="center-scroll" data-testid="page-preview">
      <div className="unavailable" data-testid="preview-unavailable">
        <h2>이 문서의 페이지 그림은 아직 만들 수 없습니다</h2>
        <p>
          지금 연결된 런타임에는 문서를 그림으로 그리는 기능이 없습니다. 페이지 모양을
          지어내지 않기 위해, 실제 렌더 결과가 생기기 전까지는 아무것도 그리지 않습니다.
        </p>
        <p>
          아래 그림은 런타임이 알려 준 <strong>용지와 여백 치수</strong>를 축척대로 옮긴
          것입니다. 본문이 어디에 어떻게 놓이는지는 보여 주지 않습니다.
        </p>
        <p className="reason">
          runtime capabilities.unavailable.renderProbe
          {"\n"}
          {renderReason ?? "(런타임이 아직 능력 목록을 보내지 않았습니다)"}
        </p>
      </div>

      <div
        className="pagefigure"
        style={{ width: `${w}px`, height: `${h}px`, marginBottom: "36px" }}
        aria-label="용지와 여백 치수"
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
          <span className="latin-caps">page geometry · {page}쪽 · {Math.round(zoom * 100)}%</span>
        </div>
      </div>

      <div style={{ display: "flex", gap: "var(--s2)", marginTop: "var(--s6)" }}>
        <button className="action" onClick={() => setZoom(zoom - 0.25)} disabled={zoom <= 0.5}>
          축소
        </button>
        <button className="action" onClick={() => setZoom(1)} disabled={zoom === 1}>
          100%
        </button>
        <button className="action" onClick={() => setZoom(zoom + 0.25)} disabled={zoom >= 4}>
          확대
        </button>
      </div>
    </div>
  );
}

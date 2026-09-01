/**
 * 한글 오버레이 — editing ON the rendered page.
 *
 * This is the marquee feature and it is also the easiest one in the product to
 * make dishonest, so the rules it is written to are worth stating before the
 * code:
 *
 * **1. The layout is the renderer's, never ours.** Every rectangle here is a
 * `[x0, y0, x1, y1]` fraction that came out of `document/pageGeometry`, which
 * read it out of a PDF Hancom laid out (§12.2). Nothing is derived from
 * `summary.pageMetrics`, nothing is nudged to look tidier, and when the runtime
 * returns no geometry this component is not rendered at all. A rectangle in the
 * wrong place is worse than no rectangle: it puts a caret where the text is not
 * and it does so with the authority of a measurement.
 *
 * **2. Ambiguity is shown, never resolved.** A line whose text matches several
 * addresses arrives with `address: null` and every candidate listed, and a
 * click on it opens a chooser. It does not take the first, the nearest, or the
 * likeliest. That is T41 (`engine/scripts/preedit.py:221`), where one unscoped
 * key overwrote five sibling contracts in a six-contract pack and every offline
 * gate passed because the label survived as a prefix. Surfacing the choice in
 * the UI is the entire point of drawing these differently.
 *
 * **3. One mutation path.** Clicking an editable target calls `beginEdit` —
 * the same function `TextView`'s cell click calls, opening the same inline
 * editor, producing the same `fill_cell` op in the same review queue, bound by
 * the same plan, gated by the same approval. There is no overlay-shaped edit
 * route. A value typed on the page and a value typed in the tree are
 * indistinguishable by the time they reach `plan/propose`, which is what makes
 * "editing on the page" a new surface rather than a new risk.
 *
 * **4. Not a wall of boxes.** An editable seat is a quiet affordance that
 * appears on hover. What is permanently visible is the small number of things
 * the user genuinely has to know about: ambiguous spans, because a person has
 * to resolve them, and nothing else.
 *
 * WHAT THIS MACHINE'S CORPUS ACTUALLY PRODUCES, measured rather than assumed:
 * across all ten corpus forms, 51 pages and 473 editable fill regions,
 * `document/pageGeometry` places **zero** seats and returns **zero** unique
 * spans whose address is an editable cell (see desktop/README.md, overlay gap
 * 1). So on today's runtime the editable half of this component draws nothing
 * and the ambiguous half draws a great deal. It is written for both because the
 * seat rule is a runtime GAP with a named fix (§12.6), not a design decision —
 * and a component that only handled the empty case would have to be rewritten
 * the day the runtime places its first seat.
 */
import { useEffect, useRef } from "react";

import {
  addressIsEditable,
  addressLabel,
  chooseCandidate,
  clickOverlaySeat,
  clickOverlaySpan,
  dismissOverlayPick,
} from "../actions";
import { useWorkspace } from "../store";
import type { GeometryResult, GeometrySeat, GeometrySpan, NormRect } from "../types";
import { Tag } from "./Tag";

/** A normalized rect as CSS percentages. The only coordinate maths here. */
function place(rect: NormRect): React.CSSProperties {
  const [x0, y0, x1, y1] = rect;
  return {
    left: `${x0 * 100}%`,
    top: `${y0 * 100}%`,
    width: `${Math.max(0, x1 - x0) * 100}%`,
    height: `${Math.max(0, y1 - y0) * 100}%`,
  };
}

/**
 * How sure the runtime is about where this seat is, in words.
 *
 * Shown rather than flattened, because the three derivations are not equally
 * trustworthy and §12.4 exists so the client can style certainty instead of
 * implying it. `interpolated` is a rectangle inferred from a neighbouring
 * label; it deserves to look less certain than one snapped to a rule that is
 * actually drawn on the page.
 */
const DERIVATION_NOTE: Record<string, string> = {
  matched_text: "이 칸의 글자가 지면에서 그대로 발견된 자리입니다.",
  cell_borders: "지면에 실제로 그려진 선을 따라 잡은 자리입니다.",
  interpolated: "같은 줄의 이름표에서 미루어 잡은 자리입니다. 선이 그려져 있지 않아 위치가 정확하지 않을 수 있습니다.",
};

function SeatOverlay({ seat, picked }: { seat: GeometrySeat; picked: boolean }) {
  const editable = addressIsEditable({
    kind: "cell",
    table: seat.table ?? null,
    row: seat.row ?? null,
    col: seat.col ?? null,
  });
  return (
    <button
      type="button"
      className={[
        "ov ov-seat",
        `ov-${seat.derivation}`,
        editable ? "ov-editable" : "ov-inert",
        picked ? "ov-picked" : "",
      ].join(" ")}
      style={place(seat.rect)}
      data-testid="overlay-seat"
      data-derivation={seat.derivation}
      data-editable={editable ? "true" : "false"}
      data-address={`${seat.table}-${seat.row}-${seat.col}`}
      title={`표${seat.table} (${seat.row},${seat.col})\n${
        DERIVATION_NOTE[seat.derivation] ?? "런타임이 이 자리를 어떻게 잡았는지 알 수 없습니다."
      }`}
      aria-label={`표${seat.table} ${seat.row}행 ${seat.col}열 값 넣기`}
      onClick={(e) => {
        e.stopPropagation();
        clickOverlaySeat(seat);
      }}
    />
  );
}

function SpanOverlay({ span, picked }: { span: GeometrySpan; picked: boolean }) {
  // Unmapped text gets NOTHING. It is on the page, it is readable, and this
  // shell has no address for it — so it gets no affordance rather than a
  // hopeful one.
  if (span.confidence === "unmapped") return null;

  const ambiguous = span.confidence === "ambiguous";
  const editable = !ambiguous && addressIsEditable(span.address);
  const count = span.candidates?.length ?? 0;

  return (
    <button
      type="button"
      className={[
        "ov ov-span",
        ambiguous ? "ov-ambiguous" : editable ? "ov-editable" : "ov-inert",
        picked ? "ov-picked" : "",
      ].join(" ")}
      style={place(span.rect)}
      data-testid={ambiguous ? "overlay-ambiguous" : "overlay-span"}
      data-confidence={span.confidence}
      data-editable={editable ? "true" : "false"}
      data-span-index={span.index}
      title={
        ambiguous
          ? `“${span.text}” — 같은 글자를 가진 주소가 ${count}개입니다. 어느 것인지 런타임은 고르지 않습니다.`
          : span.address
            ? `${addressLabel(span.address)}${editable ? "" : " — 값을 넣는 자리가 아닙니다"}`
            : ""
      }
      onClick={(e) => {
        e.stopPropagation();
        clickOverlaySpan(span);
      }}
    >
      {ambiguous ? <span className="ov-badge">{count}</span> : null}
    </button>
  );
}

/**
 * The chooser. Every candidate, in the runtime's own order, and no default.
 *
 * Deliberately has no "가장 그럴듯한 것" button and no preselected row: a
 * default IS a pick, and the whole reason this panel exists is that nothing may
 * pick for the user. It also says out loud that nothing has been queued, so
 * dismissing it cannot be mistaken for cancelling an edit that was never made.
 */
function CandidateChooser() {
  const pick = useWorkspace((s) => s.overlayPick);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (pick?.kind === "ambiguous") box.current?.focus();
  }, [pick]);

  if (!pick || pick.kind !== "ambiguous") return null;
  const candidates = pick.candidates ?? [];

  return (
    <div
      className="ov-chooser"
      data-testid="overlay-chooser"
      ref={box}
      tabIndex={-1}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          dismissOverlayPick();
        }
      }}
    >
      <div className="ov-chooser-head">
        <Tag tone="warn">후보 {candidates.length}개</Tag>
        <span>런타임은 이 중 하나를 고르지 않습니다</span>
      </div>
      <p className="tiny">
        같은 글자가 여러 주소에 있습니다. 어느 자리를 편집할지는 사람이 정합니다. 지금까지
        대기열에 올라간 것은 없습니다.
      </p>
      <ul className="ov-candidates">
        {candidates.map((candidate, index) => {
          const editable = addressIsEditable(candidate);
          return (
            <li key={`${addressLabel(candidate)}-${index}`}>
              <button
                type="button"
                className="ov-candidate"
                data-testid="overlay-candidate"
                data-editable={editable ? "true" : "false"}
                onClick={() => chooseCandidate(candidate)}
              >
                <span className="mono">{addressLabel(candidate)}</span>
                {candidate.classification ? (
                  <span className="dim tiny">{candidate.classification}</span>
                ) : null}
                {editable ? null : <Tag tone="none">값 자리 아님</Tag>}
              </button>
            </li>
          );
        })}
      </ul>
      <button className="ghost" data-testid="overlay-chooser-dismiss" onClick={dismissOverlayPick}>
        닫기
      </button>
    </div>
  );
}

/**
 * What the runtime said about this page, in its own numbers.
 *
 * Under the page rather than over it, and always shown when geometry ran: a
 * page with no editable overlay on it needs to say WHY there is none, or the
 * user is left to conclude the feature is broken when the honest answer is that
 * the runtime placed no seat here.
 */
function GeometryLegend({ geometry }: { geometry: GeometryResult }) {
  const mapping = geometry.mapping;
  const seats = geometry.seats ?? [];
  const spans = geometry.spans ?? [];
  const editableSpans = spans.filter(
    (s) => s.confidence === "unique" && addressIsEditable(s.address),
  ).length;
  const editableSeats = seats.filter((s) =>
    addressIsEditable({ kind: "cell", table: s.table ?? null, row: s.row ?? null, col: s.col ?? null }),
  ).length;

  if (mapping?.state !== "ran") {
    return (
      <p className="raster-note" data-testid="overlay-legend">
        <Tag tone="none">대응 없음</Tag>
        {mapping?.reason ??
          "이 문서에는 대응시킬 서식 정보가 없어, 글자 위치는 있지만 주소가 없습니다."}
      </p>
    );
  }

  return (
    <p className="raster-note" data-testid="overlay-legend">
      <Tag tone={editableSeats + editableSpans > 0 ? "fill" : "none"}>
        편집 가능 {editableSeats + editableSpans}
      </Tag>
      <span className="mono tiny" data-testid="overlay-counts">
        확정 {mapping.unique ?? 0} · 후보 {mapping.ambiguous ?? 0} · 대응 없음{" "}
        {mapping.unmapped ?? 0} · 자리 {seats.length}
      </span>
      {editableSeats + editableSpans === 0 ? (
        <span className="dim">
          이 쪽에서 런타임이 값을 넣을 자리를 잡아 주지 못했습니다. 그런 자리는 본문 보기에서
          편집하십시오 — 여기에 상자를 그리려면 위치를 지어내야 하고, 그러면 글자가 없는 곳에
          커서를 놓게 됩니다.
        </span>
      ) : null}
    </p>
  );
}

/**
 * The overlay layer itself, stretched over the raster.
 *
 * Positioned in PERCENTAGES against a container that is exactly the raster's
 * drawn size, which is what makes zoom free: the zoom changes the container's
 * pixel width, every child re-lays out from the same fractions, and the runtime
 * is not asked anything. `geometryFetches` in the store is the proof of that,
 * and the smoke reads it across a zoom sweep.
 */
export function PageOverlay({ geometry }: { geometry: GeometryResult }) {
  const pick = useWorkspace((s) => s.overlayPick);
  const spans = geometry.spans ?? [];
  const seats = geometry.seats ?? [];

  return (
    <div className="ov-layer" data-testid="page-overlay" data-page={geometry.page ?? 0}>
      {seats.map((seat) => (
        <SeatOverlay
          key={`seat-${seat.table}-${seat.row}-${seat.col}`}
          seat={seat}
          picked={pick?.targetId === `seat-${seat.table}-${seat.row}-${seat.col}`}
        />
      ))}
      {spans.map((span) => (
        <SpanOverlay
          key={`span-${span.index}`}
          span={span}
          picked={pick?.targetId === `span-${span.index}`}
        />
      ))}
      <CandidateChooser />
    </div>
  );
}

export { GeometryLegend };

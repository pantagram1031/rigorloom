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
 * **3. One mutation path, and one editor.** Clicking an editable target calls
 * `beginEdit` — the same function `TextView`'s cell click calls — and mounts
 * `SeatEditor`, the same COMPONENT `TextView` mounts, in the rectangle the
 * runtime placed. Same element, same IME behaviour, same `fill_cell` op, same
 * review queue, same plan hash, same approval, same receipt. There is no
 * overlay-shaped edit route and no second field to keep in step.
 *
 * That is a correction, not a boast: until the runtime placed its first real
 * seat this branch had never fired, and when it did it opened an edit state
 * with no field on screen — `SeatEditor` lived inside `TextView`, which
 * 페이지 보기 does not mount. Extracting it into `SeatEditor.tsx` was the fix;
 * writing a second input here would have been the defect.
 *
 * **4. An empty seat is an invitation, and it used to be invisible.** The first
 * version of this rule read "an editable seat is a quiet affordance that appears
 * on hover", and it was written when the runtime placed zero seats on every
 * corpus form: there was nothing to be quiet about. `cell_borders` (§12.4)
 * changed the measurement — 73 seats across the corpus, 55 of them on one form,
 * every one of them an address `beginEdit` opens — and a hover-only affordance
 * over 37 real seats on a page means the product's marquee interaction is
 * undiscoverable unless you already know it is there. So a seat now has a
 * resting state: a faint fill tint with a baseline rule, in the SAME accent
 * vocabulary the tree view uses for a value slot, strengthening on hover. What
 * did not change is the vocabulary boundary — ambiguity stays in the warning
 * palette, because it is a question, not an invitation, and inert mapped text
 * still gets nothing at all.
 *
 * WHAT THIS MACHINE'S CORPUS ACTUALLY PRODUCES, measured rather than assumed:
 * across ten corpus forms, 51 pages and 473 editable fill regions,
 * `document/pageGeometry` places **73** seats, all `cell_borders`, and still
 * returns zero unique SPANS whose address is an editable cell — text matching
 * reaches labels, never empty seats, which is the whole reason the border scan
 * exists. The distribution is lumpy and honestly so: 55 on
 * kstartup-jiwon-sincheongseo-saeopgyehoekseo, 0 on the two forms ruled with
 * underlines rather than boxes. 400 of 473 regions still get no seat and §12.6
 * says why, per cause. This component draws exactly what it is given.
 */
import { useEffect, useRef } from "react";

import {
  addressIsCaretTarget,
  addressIsEditable,
  addressLabel,
  cancelEdit,
  chooseCandidate,
  clickOverlaySeat,
  clickOverlaySpan,
  commitEdit,
  dismissOverlayPick,
} from "../actions";
import { fieldTextForRunEdit } from "../revision";
import { useWorkspace, type InlineRunEdit } from "../store";
import type { GeometryResult, GeometrySeat, GeometrySpan, NormRect } from "../types";
import { SeatEditor } from "./SeatEditor";
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

function SeatOverlay({
  seat,
  picked,
  stale,
  editing,
}: {
  seat: GeometrySeat;
  picked: boolean;
  /** The candidate changed this address and this raster predates it (E1.2). */
  stale: boolean;
  /** The open inline edit, when it is THIS seat's. Null otherwise. */
  editing: { before: string } | null;
}) {
  const editable = addressIsEditable({
    kind: "cell",
    table: seat.table ?? null,
    row: seat.row ?? null,
    col: seat.col ?? null,
  });

  // TYPING HAPPENS IN THE RECTANGLE THE RUNTIME PLACED.
  //
  // Found by the first evidence run that had a real seat to click: `beginEdit`
  // opened an edit state and there was no field on screen to type into, because
  // the only `<input>` in the app lived inside `TextView` and 페이지 보기 does
  // not mount it. The fix is the same component, mounted here — not a second
  // editor. `SeatEditor` moved out of `TextView` for exactly this, so a value
  // typed on the page and a value typed in the tree go through one element,
  // one IME path and one commit.
  if (editing) {
    return (
      <div className="ov ov-seat ov-editing" style={place(seat.rect)} data-testid="overlay-editing">
        <SeatEditor
          className="seat-input ov-seat-input"
          value={editing.before}
          onCommit={(next) => void commitEdit(next)}
          onCancel={cancelEdit}
        />
      </div>
    );
  }

  return (
    <button
      type="button"
      className={[
        "ov ov-seat",
        `ov-${seat.derivation}`,
        editable ? "ov-editable" : "ov-inert",
        picked ? "ov-picked" : "",
        stale ? "ov-stale" : "",
      ].join(" ")}
      style={place(seat.rect)}
      data-testid="overlay-seat"
      data-derivation={seat.derivation}
      data-editable={editable ? "true" : "false"}
      data-stale={stale ? "true" : undefined}
      data-address={`${seat.table}-${seat.row}-${seat.col}`}
      title={`표${seat.table} (${seat.row},${seat.col})\n${
        DERIVATION_NOTE[seat.derivation] ?? "런타임이 이 자리를 어떻게 잡았는지 알 수 없습니다."
      }${stale ? "\n후보본과 다름 — 이 그림은 원본 기준입니다" : ""}`}
      aria-label={
        editable
          ? `표${seat.table} ${seat.row}행 ${seat.col}열 — 빈 자리, 눌러서 값 넣기`
          : `표${seat.table} ${seat.row}행 ${seat.col}열 — 값을 넣는 자리가 아님`
      }
      onClick={(e) => {
        e.stopPropagation();
        clickOverlaySeat(seat);
      }}
    />
  );
}

function SpanOverlay({
  span,
  picked,
  stale,
  editing,
  source,
}: {
  span: GeometrySpan;
  picked: boolean;
  /** The candidate changed this address and this raster predates it (E1.2). */
  stale: boolean;
  /** The open caret edit, when it is THIS line's. Null otherwise. */
  editing: InlineRunEdit | null;
  /** Whose layout this is — `"pdf"` or `"own"` (§11.1c). */
  source: string;
}) {
  // Unmapped text gets NOTHING — on a page read out of a PDF. It is on the
  // page, it is readable, and this shell has no address for it, so it gets no
  // affordance rather than a hopeful one. An unmapped line there is a MISS:
  // the text was read and matched nothing, and drawing a target over it would
  // promise an edit that is not available.
  //
  // An own-rendered page keeps its unmapped lines DRAWN, and the reason is no
  // longer "every line here is unmapped by construction" — the sidecar carries
  // the text now, and these lines went through the same scan the rest did and
  // matched nothing. What is different is that on such a line the renderer
  // itself usually knows the address and was deliberately not believed
  // (`addressBasis: "sidecar_only"`). That is a fact worth a hit target: the
  // click prints what the renderer thought and why it was not applied, where
  // deleting the rectangle would leave a page that looks unmeasured. Still no
  // fill and no seat vocabulary — nothing that reads as "type here".
  if (span.confidence === "unmapped") {
    if (source !== "own") return null;
    const knows = !!span.sidecarAddress;
    return (
      <button
        type="button"
        className={["ov", "ov-span", "ov-line", picked ? "ov-picked" : ""].join(" ")}
        style={place(span.rect)}
        data-testid="overlay-span"
        data-confidence="unmapped"
        data-editable="false"
        data-caret-target="false"
        data-has-offsets={span.charX ? "true" : "false"}
        data-address-basis={span.addressBasis ?? ""}
        data-line-mode={span.lineMode ?? ""}
        data-span-index={span.index}
        title={
          knows
            ? "이 줄의 글자를 서식의 어느 자리와도 맞추지 못했습니다. 자체 렌더러는 어디서 그렸는지 알지만, 서식 스캔이 확인해 주지 않은 주소는 쓰지 않습니다."
            : "이 줄의 글자를 서식의 어느 자리와도 맞추지 못했습니다."
        }
        onClick={(e) => {
          e.stopPropagation();
          void clickOverlaySpan(span);
        }}
      />
    );
  }

  const ambiguous = span.confidence === "ambiguous";
  const editable = !ambiguous && addressIsEditable(span.address);
  // A CARET TARGET is not the same thing as an editable seat, and conflating
  // them was the first mistake this branch could have made. A seat is an empty
  // cell that takes a value; a caret target is a line of body text a person
  // can stand in and retype. `addressIsCaretTarget` is a shape check only —
  // whether a paragraph line CAN be typed in is answered by the runtime's run
  // inventory at click time, not by anything visible here (§12.7).
  const caretTarget = !ambiguous && !editable && addressIsCaretTarget(span.address);
  const count = span.candidates?.length ?? 0;

  // TYPING HAPPENS IN THE LINE THE RUNTIME MEASURED. Same component as the
  // seat, same IME path, same commit — mounted in the line's own rect and set
  // at the size the render drew it, so the field sits over the text it
  // replaces rather than beside it.
  if (editing) {
    return (
      <div
        className="ov ov-span ov-caret ov-editing"
        style={place(span.rect)}
        data-testid="overlay-caret-editing"
        data-span-index={span.index}
        data-caret={editing.caret ?? "start"}
      >
        <SeatEditor
          className="seat-input ov-caret-input"
          value={fieldTextForRunEdit(editing.before, editing.rangeStart, editing.rangeEnd)}
          caret={editing.caret}
          style={editing.sizePt ? { fontSize: `${editing.sizePt}pt` } : undefined}
          onCommit={(next) => void commitEdit(next)}
          onCancel={cancelEdit}
        />
      </div>
    );
  }

  return (
    <button
      type="button"
      className={[
        "ov ov-span",
        ambiguous ? "ov-ambiguous" : editable ? "ov-editable" : caretTarget ? "ov-caret" : "ov-inert",
        picked ? "ov-picked" : "",
        stale ? "ov-stale" : "",
      ].join(" ")}
      style={place(span.rect)}
      data-testid={ambiguous ? "overlay-ambiguous" : "overlay-span"}
      data-confidence={span.confidence}
      data-stale={stale ? "true" : undefined}
      data-editable={editable ? "true" : "false"}
      data-caret-target={caretTarget ? "true" : "false"}
      data-has-offsets={span.charX ? "true" : "false"}
      data-span-index={span.index}
      title={
        ambiguous
          ? `“${span.text}” — 같은 글자를 가진 주소가 ${count}개입니다. 어느 것인지 런타임은 고르지 않습니다.`
          : caretTarget
            ? `${addressLabel(span.address!)} — 눌러서 이 줄에 커서를 놓습니다${
                span.charX ? "" : "\n이 줄은 글자별 위치가 없어 줄 앞으로 붙습니다."
              }`
            : span.address
              ? `${addressLabel(span.address)}${editable ? "" : " — 값을 넣는 자리가 아닙니다"}`
              : ""
      }
      onClick={(e) => {
        e.stopPropagation();
        // WHERE in the line, as a fraction of the PAGE — the units `charX` is
        // in, so nothing here converts coordinates. The overlay layer is
        // exactly the raster's box, which is what makes this arithmetic one
        // division rather than a scale factor kept in step by hand.
        const layer = e.currentTarget.closest<HTMLElement>('[data-testid="page-overlay"]');
        const width = layer?.getBoundingClientRect().width ?? 0;
        const fraction =
          width > 0
            ? (e.clientX - layer!.getBoundingClientRect().left) / width
            : undefined;
        void clickOverlaySpan(span, fraction);
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
          // §12.4: a label is routinely registered twice, once as an anchor
          // and once as the cell it sits in, so this list very often holds one
          // of each. Both are now somewhere a person can type, and the row
          // says WHICH kind of typing rather than marking the paragraph half
          // 값 자리 아님 — which was right until the caret existed.
          const caretRow = !editable && addressIsCaretTarget(candidate);
          // The one OUR renderer says it drew this line from. It is MARKED and
          // it is not preselected, does not sort first, and is not a default:
          // the panel exists because nothing may pick for the user, and a
          // second witness does not change that. It is shown because a person
          // choosing between identical labels deserves the one piece of
          // evidence the runtime declined to act on.
          const drawnHere = pick.sidecarPick === index;
          return (
            <li key={`${addressLabel(candidate)}-${index}`}>
              <button
                type="button"
                className="ov-candidate"
                data-testid="overlay-candidate"
                data-editable={editable ? "true" : "false"}
                data-caret-target={caretRow ? "true" : "false"}
                data-sidecar-pick={drawnHere ? "true" : "false"}
                onClick={() => void chooseCandidate(candidate)}
              >
                <span className="mono">{addressLabel(candidate)}</span>
                {drawnHere ? (
                  <Tag
                    tone="none"
                    title="자체 렌더러는 이 줄을 여기서 그렸다고 말합니다. 서식 스캔이 확인해 주지 않았으므로 자동으로 고르지는 않습니다."
                  >
                    렌더러 지목
                  </Tag>
                ) : null}
                {candidate.classification ? (
                  <span className="dim tiny">{candidate.classification}</span>
                ) : null}
                {editable ? null : caretRow ? (
                  <Tag tone="none" title="이 문단 줄에 커서를 놓습니다. 줄 앞에서 시작합니다.">
                    문단 줄
                  </Tag>
                ) : (
                  <Tag tone="none">값 자리 아님</Tag>
                )}
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
      <p className="raster-note ov-legend" data-testid="overlay-legend">
        <Tag tone="none">대응 없음</Tag>
        {mapping?.reason ??
          "이 문서에는 대응시킬 서식 정보가 없어, 글자 위치는 있지만 주소가 없습니다."}
      </p>
    );
  }

  return (
    <p className="raster-note ov-legend" data-testid="overlay-legend">
      <Tag tone={editableSeats + editableSpans > 0 ? "fill" : "none"}>
        편집 가능 {editableSeats + editableSpans}
      </Tag>
      <span className="mono tiny" data-testid="overlay-counts">
        확정 {mapping.unique ?? 0} · 후보 {mapping.ambiguous ?? 0} · 대응 없음{" "}
        {mapping.unmapped ?? 0} · 자리 {seats.length}
      </span>
      {/* The cross-check, in the runtime's own numbers. On an own-rendered page
          the renderer knows where it drew every line, and this row is how a
          person sees that the knowledge was CHECKED rather than taken: 확인
          means both witnesses said the same thing, 불일치 means neither was
          used, 미확인 means the renderer knew and was not believed. */}
      {mapping.crossCheck && (mapping.crossCheck.declared ?? 0) > 0 ? (
        <span
          className="mono tiny dim"
          data-testid="overlay-crosscheck"
          title="자체 렌더러가 스스로 밝힌 주소를 서식 스캔과 대조한 결과입니다. 렌더러 말만으로 주소를 정하지는 않습니다."
        >
          렌더러 대조 — 확인 {mapping.crossCheck.agree ?? 0} · 불일치{" "}
          {mapping.crossCheck.disagree ?? 0} · 미확인 {mapping.crossCheck.sidecarOnly ?? 0}
        </span>
      ) : null}
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
export function PageOverlay({
  geometry,
  stale = [],
}: {
  geometry: GeometryResult;
  /**
   * Addresses the candidate changed and this raster therefore does not show
   * (E1.2), as `c:t:r:c` / `p:N` keys.
   *
   * They come from the RUNTIME's receipts — the ops that actually ran, walked
   * up the base chain — not from anything this shell inferred about the page.
   * A marked rectangle says "what is drawn here is out of date"; it never says
   * what the new text is, because this component draws the renderer's layout
   * and the renderer has not drawn the new text.
   */
  stale?: string[];
}) {
  const pick = useWorkspace((s) => s.overlayPick);
  // Read here rather than in the seat, so the store is subscribed to ONCE for
  // a page that can carry dozens of seats.
  const inlineEdit = useWorkspace((s) => s.inlineEdit);
  const spans = geometry.spans ?? [];
  const seats = geometry.seats ?? [];
  const staleKeys = new Set(stale);

  return (
    <div
      className="ov-layer"
      data-testid="page-overlay"
      data-page={geometry.page ?? 0}
      data-stale={staleKeys.size > 0 ? String(staleKeys.size) : undefined}
    >
      {seats.map((seat) => (
        <SeatOverlay
          key={`seat-${seat.table}-${seat.row}-${seat.col}`}
          seat={seat}
          picked={pick?.targetId === `seat-${seat.table}-${seat.row}-${seat.col}`}
          stale={staleKeys.has(`c:${seat.table}:${seat.row}:${seat.col}`)}
          editing={
            inlineEdit &&
            inlineEdit.kind === "cell" &&
            inlineEdit.table === seat.table &&
            inlineEdit.row === seat.row &&
            inlineEdit.col === seat.col
              ? { before: inlineEdit.before }
              : null
          }
        />
      ))}
      {spans.map((span) => (
        <SpanOverlay
          key={`span-${span.index}`}
          span={span}
          source={geometry.geometrySource ?? "pdf"}
          picked={pick?.targetId === `span-${span.index}`}
          stale={staleKeys.has(spanStaleKey(span))}
          editing={
            inlineEdit && inlineEdit.kind === "run" && inlineEdit.spanIndex === span.index
              ? inlineEdit
              : null
          }
        />
      ))}
      <CandidateChooser />
    </div>
  );
}

/** A span's address as the echo spells it, or a key nothing can match. */
function spanStaleKey(span: GeometrySpan): string {
  const address = span.address;
  if (!address) return "";
  if (address.atPara != null) return `p:${address.atPara}`;
  if (address.table != null && address.row != null && address.col != null) {
    return `c:${address.table}:${address.row}:${address.col}`;
  }
  return "";
}

export { GeometryLegend };

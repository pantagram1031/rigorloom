/**
 * Document-revision binding for overlay edits.
 *
 * The page on screen, the address map, the region read, and the plan base
 * must name the same document revision. A prepared PDF hash is not that
 * revision. Asynchronous prepare returns an effect with a lease; the public
 * commit validates the lease once. Superseded work is a silent no-op — not
 * a refusal a caller can turn back into a stale selection.
 *
 * Card 3 (run-scoped edit) sits on the same lease: the click names one run
 * and a UTF-16 range inside it. See `run_map.ts`.
 *
 * See docs/research/revision-coherence-01.md (PR #254) and this wiring on
 * the desktop-own-render tip (PR #221).
 */

import { locateSpanInRuns, type OffsetUnit } from "./run_map";

export type CaretRefusal =
  | "no_address"
  | "multi_run"
  | "run_text_differs"
  | "no_inventory"
  | "revision_mismatch"
  | "cross_run";

export { OFFSET_UNIT, type OffsetUnit } from "./run_map";
export {
  commitRunScopedReplacement,
  fieldTextForRunEdit,
  locateSpanInRuns,
  replaceUtf16Range,
  utf16Length,
  utf16Slice,
} from "./run_map";

export interface DocumentRevision {
  sessionId: string;
  /** Null means the session source. Never silently upgraded to "latest head". */
  runId: string | null;
  /** HWPX / document digest. Distinct from a PDF or raster artifact digest. */
  documentSha256: string | null;
}

export interface EditLease {
  intent: number;
  sessionId: string;
  runId: string | null;
  documentSha256: string | null;
  /** Object identity of the displayed geometry at click time. */
  geometry: object | null;
  /** Object identity of the displayed raster at click time. */
  render: object | null;
  atPara: number;
}

export type ParagraphEditEffect =
  | {
      kind: "caret";
      lease: EditLease;
      atPara: number;
      run: number;
      before: string;
      caret: number | null;
      spanIndex: number;
      sizePt?: number;
      region: { at_para?: number; runs?: Array<{ index: number; text?: string }> };
      /** UTF-16 range of the clicked visual line inside `before`. */
      offsetUnit: OffsetUnit;
      rangeStart: number;
      rangeEnd: number;
    }
  | {
      kind: "refused";
      lease: EditLease;
      refusal: CaretRefusal;
      address: { kind?: string; atPara?: number | null };
      spanIndex: number;
    };

export interface RevisionView {
  activeSessionId: string | null;
  editIntentGeneration: number;
  geometry: {
    source?: { runId?: string | null; sha256?: string; candidateSha256?: string };
    subject?: { kind?: string; runId?: string | null; sha256?: string };
  } | null;
  render: {
    source?: { runId?: string | null; sha256?: string; candidateSha256?: string };
  } | null;
  sessions?: Array<{ sessionId: string; source?: { sha256?: string } }>;
}

/** The document revision the page is actually showing — not ambient head. */
export function displayedRevision(state: RevisionView): DocumentRevision | null {
  if (!state.activeSessionId) return null;
  const runId =
    state.geometry?.source?.runId ?? state.render?.source?.runId ?? null;
  const documentSha256 =
    state.geometry?.subject?.sha256 ??
    (runId
      ? (state.geometry?.source?.candidateSha256 ?? null)
      : (state.sessions?.find((s) => s.sessionId === state.activeSessionId)?.source
          ?.sha256 ?? null));
  return { sessionId: state.activeSessionId, runId, documentSha256 };
}

export function captureEditLease(
  state: RevisionView,
  atPara: number,
  intent: number,
): EditLease | null {
  const revision = displayedRevision(state);
  if (!revision) return null;
  return {
    intent,
    sessionId: revision.sessionId,
    runId: revision.runId,
    documentSha256: revision.documentSha256,
    geometry: state.geometry,
    render: state.render,
    atPara,
  };
}

/**
 * Session-id equality misses A→B→A. Geometry identity misses another target
 * on the same page. Both the intent generation and the displayed revision
 * have to still be the ones this lease was issued for.
 */
export function leaseIsCurrent(lease: EditLease, state: RevisionView): boolean {
  if (state.editIntentGeneration !== lease.intent) return false;
  if (state.activeSessionId !== lease.sessionId) return false;
  if (state.geometry !== lease.geometry) return false;
  if (state.render !== lease.render) return false;
  const now = displayedRevision(state);
  if (!now) return false;
  if (now.runId !== lease.runId) return false;
  if (
    lease.documentSha256 &&
    now.documentSha256 &&
    now.documentSha256 !== lease.documentSha256
  ) {
    return false;
  }
  return true;
}

export function subjectMatchesLease(
  lease: EditLease,
  subject: { kind?: string; runId?: string | null; sha256?: string } | undefined,
): boolean {
  if (!subject) return false;
  const subjectRunId = subject.runId ?? null;
  if (subjectRunId !== lease.runId) return false;
  if (lease.runId == null && subject.kind && subject.kind !== "session_source") {
    return false;
  }
  if (lease.runId != null && subject.kind && subject.kind !== "candidate") {
    return false;
  }
  if (lease.documentSha256 && subject.sha256 && subject.sha256 !== lease.documentSha256) {
    return false;
  }
  return true;
}

export interface RegionAnswer {
  subject?: { kind?: string; runId?: string | null; sha256?: string };
  regions: Array<{ at_para?: number; runs?: Array<{ index: number; text?: string }> }>;
}

/**
 * Ask the runtime for the line's run inventory. Does not write editor state.
 */
export async function prepareParagraphEdit(args: {
  lease: EditLease;
  spanText: string;
  spanIndex: number;
  sizePt?: number;
  caret: number | null;
  address: { kind?: string; atPara?: number | null };
  readRegion: (
    sessionId: string,
    regions: Array<{ atPara: number }>,
    runId?: string | null,
  ) => Promise<RegionAnswer>;
  queuedBefore?: string | null;
}): Promise<ParagraphEditEffect> {
  const { lease, address } = args;
  const atPara = address.atPara;
  if (atPara == null) {
    return { kind: "refused", lease, refusal: "no_address", address, spanIndex: args.spanIndex };
  }
  let runs: Array<{ index: number; text?: string }> = [];
  let region: { at_para?: number; runs?: Array<{ index: number; text?: string }> } | undefined;
  try {
    const answer = await args.readRegion(lease.sessionId, [{ atPara }], lease.runId);
    if (!subjectMatchesLease(lease, answer.subject)) {
      return {
        kind: "refused",
        lease,
        refusal: "revision_mismatch",
        address,
        spanIndex: args.spanIndex,
      };
    }
    region = answer.regions.find((r) => r.at_para === atPara);
    runs = region?.runs ?? [];
  } catch {
    return { kind: "refused", lease, refusal: "no_inventory", address, spanIndex: args.spanIndex };
  }
  if (runs.length === 0) {
    return { kind: "refused", lease, refusal: "no_inventory", address, spanIndex: args.spanIndex };
  }
  const located = locateSpanInRuns(args.spanText, runs);
  if (located.kind === "refused") {
    return { kind: "refused", lease, refusal: located.refusal, address, spanIndex: args.spanIndex };
  }
  const rangeLen = located.rangeEnd - located.rangeStart;
  const caret =
    args.caret == null ? null : Math.max(0, Math.min(args.caret, rangeLen));
  return {
    kind: "caret",
    lease,
    atPara,
    run: located.run,
    before: args.queuedBefore ?? located.runText,
    caret,
    spanIndex: args.spanIndex,
    sizePt: args.sizePt,
    region: region ?? { at_para: atPara, runs },
    offsetUnit: located.offsetUnit,
    rangeStart: located.rangeStart,
    rangeEnd: located.rangeEnd,
  };
}

export type OverlayCommit =
  | { kind: "noop" }
  | {
      kind: "caret";
      selection: { kind: "paragraph"; atPara: number };
      inlineEdit: {
        kind: "run";
        atPara: number;
        run: number;
        before: string;
        caret: number | null;
        spanIndex: number;
        sizePt?: number;
        runId: string | null;
        documentSha256: string | null;
        offsetUnit: OffsetUnit;
        rangeStart: number;
        rangeEnd: number;
      };
      overlayPick: {
        kind: "caret";
        targetId: string;
        address: { kind: string; atPara: number };
        caret: number | null;
        snapped: boolean;
      };
      region: { at_para?: number; runs?: Array<{ index: number; text?: string }> };
      sessionId: string;
    }
  | {
      kind: "refused";
      selection: { kind: "paragraph"; atPara: number };
      overlayPick: {
        kind: "no_caret";
        targetId: string;
        address: { kind: string; atPara: number };
        refusal: CaretRefusal;
      };
    };

/**
 * Public commit boundary. Stale leases produce a no-op, never a refusal
 * the caller can convert into an old selection or overlay write.
 */
export function commitParagraphClick(
  effect: ParagraphEditEffect,
  state: RevisionView,
): OverlayCommit {
  if (!leaseIsCurrent(effect.lease, state)) return { kind: "noop" };
  const id = `span-${effect.spanIndex}`;
  if (effect.kind === "refused") {
    const atPara = effect.address.atPara;
    if (atPara == null) return { kind: "noop" };
    return {
      kind: "refused",
      selection: { kind: "paragraph", atPara },
      overlayPick: {
        kind: "no_caret",
        targetId: id,
        address: { kind: effect.address.kind ?? "anchor", atPara },
        refusal: effect.refusal,
      },
    };
  }
  return {
    kind: "caret",
    selection: { kind: "paragraph", atPara: effect.atPara },
    inlineEdit: {
      kind: "run",
      atPara: effect.atPara,
      run: effect.run,
      before: effect.before,
      caret: effect.caret,
      spanIndex: effect.spanIndex,
      sizePt: effect.sizePt,
      runId: effect.lease.runId,
      documentSha256: effect.lease.documentSha256,
      offsetUnit: effect.offsetUnit,
      rangeStart: effect.rangeStart,
      rangeEnd: effect.rangeEnd,
    },
    overlayPick: {
      kind: "caret",
      targetId: id,
      address: { kind: "anchor", atPara: effect.atPara },
      caret: effect.caret,
      snapped: effect.caret === null,
    },
    region: effect.region,
    sessionId: effect.lease.sessionId,
  };
}

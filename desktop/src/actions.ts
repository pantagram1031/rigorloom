/**
 * Everything the app can do, as plain functions over the one store.
 *
 * Kept out of components so the scripted smoke drives the same code path a
 * click does — a smoke that exercised its own private path would prove nothing
 * about the app.
 */
import { open as openFileDialog, save as saveFileDialog } from "@tauri-apps/plugin-dialog";
import { getCurrentWebview } from "@tauri-apps/api/webview";

import * as rt from "./runtime";
import {
  DEFAULT_PROVIDER,
  EMPTY_DRAFT,
  activeStoreKey,
  canRequestApproval,
  composerBlocker,
  getState,
  patchTurn,
  providerConfigFields,
  setState,
  setSelection,
  showToast,
  type Draft,
  type QueuedOp,
} from "./store";
import type {
  EditableRegion,
  Finding,
  GeometryAddress,
  GeometrySeat,
  GeometrySpan,
  InspectResult,
  OperationPlan,
  PlanValidation,
  ProviderSettings,
  Recent,
  RegionText,
  RuntimeError,
  Turn,
  VerificationReport,
} from "./types";

const MAX_RECENTS = 8;
export const ZOOM_MIN = 0.5;
export const ZOOM_MAX = 2.0;
const ZOOM_STEPS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.35, 1.5, 1.75, 2.0];

/** Load a session's inspect once and cache it. */
export async function loadInspect(sessionId: string, force = false): Promise<boolean> {
  if (!force && getState().inspects[sessionId]) {
    setState({ inspectPhase: "ready", inspectError: null });
    return true;
  }
  setState({ inspectPhase: "starting", inspectError: null });
  try {
    const result = await rt.inspect(sessionId);
    setState({
      inspects: { ...getState().inspects, [sessionId]: result },
      inspectPhase: "ready",
      inspectError: null,
    });
    return true;
  } catch (e) {
    setState({ inspectPhase: "failed", inspectError: rt.asRuntimeError(e) });
    return false;
  }
}

/**
 * Fetch the document's full text for the centre column.
 *
 * `graph.paragraphs[].text` is already complete, so only table cells need
 * `document/readRegion` — and they genuinely do: `textPreview` in the graph is
 * truncated for anything long, and the runtime flags that with `truncated`.
 * readRegion additionally returns per-run `color_value` and `color_anomaly`,
 * which is the only place the real colour of a run is available.
 *
 * The response is bounded at 256 KiB and the runtime **refuses rather than
 * truncates** (`region_too_large`). So the request is chunked, and a chunk that
 * is still refused is dropped rather than retried forever — the cells it
 * covered fall back to their graph preview, which the UI marks as a preview.
 */
const REGION_CHUNK = 40;

export async function loadText(sessionId: string, force = false): Promise<boolean> {
  if (!force && getState().texts[sessionId]) {
    setState({ textPhase: "ready", textError: null });
    return true;
  }
  const inspect = getState().inspects[sessionId];
  if (!inspect) return false;

  const wanted = inspect.graph.tables.flatMap((t) =>
    t.cells.map((c) => ({ table: t.index, row: c.addr.row, col: c.addr.col })),
  );
  if (wanted.length === 0) {
    setState({ texts: { ...getState().texts, [sessionId]: [] }, textPhase: "ready" });
    return true;
  }

  setState({ textPhase: "starting", textError: null });
  const collected: RegionText[] = [];
  let refused: unknown = null;
  for (let i = 0; i < wanted.length; i += REGION_CHUNK) {
    const chunk = wanted.slice(i, i + REGION_CHUNK);
    try {
      const res = await rt.readRegion(sessionId, chunk);
      collected.push(...res.regions);
    } catch (e) {
      // Honest partial: keep what came back, remember why the rest did not.
      refused = e;
    }
  }
  setState({
    texts: { ...getState().texts, [sessionId]: collected },
    textPhase: "ready",
    textError: refused ? rt.asRuntimeError(refused) : null,
  });
  return true;
}

async function loadCandidates(sessionId: string) {
  try {
    const list = await rt.candidates(sessionId);
    setState({ candidates: { ...getState().candidates, [sessionId]: list } });
  } catch {
    // `candidate/list` is not load-bearing for a read-only phase. Absence is
    // not failure — the bar already renders an explicit empty state.
  }
}

/**
 * Make a session active. Selection is cleared only when the document changes.
 *
 * A pending queue is NOT cleared, and that is deliberate. It belongs to the
 * document it was proposed against, `draftStaleness` says so the moment the
 * active session moves away from it, and the queue offers to go back. Throwing
 * away typed work because somebody clicked another document would be the worse
 * failure of the two.
 */
export async function selectSession(sessionId: string) {
  const previous = getState().activeSessionId;
  setState({
    activeSessionId: sessionId,
    ...(previous !== sessionId
      ? {
          selection: null,
          page: 1,
          findings: [],
          checkedAt: null,
          checkPhase: "idle" as const,
          inlineEdit: null,
          render: null,
          renderPhase: "idle" as const,
          renderError: null,
          prepareError: null,
          prepareNote: null,
          // The geometry CACHE is keyed on the session and survives a switch
          // back; the answer on screen and the click that resolved against it
          // do not, because they belong to the document being left.
          geometry: null,
          geometryPhase: "idle" as const,
          geometryError: null,
          overlayPick: null,
          candidateVerdict: null,
          applied: null,
          receiptOpen: null,
        }
      : {}),
  });
  await rt.savePrefs({ lastSessionId: sessionId });
  await loadInspect(sessionId);
  await loadText(sessionId);
  await loadCandidates(sessionId);
  rememberRecent(sessionId);
  await startEvents(sessionId);
}

export async function refreshSessions(): Promise<void> {
  try {
    setState({ sessions: await rt.sessions() });
  } catch (e) {
    setState({ fatal: rt.asRuntimeError(e) });
  }
}

// --- recents ----------------------------------------------------------------

/**
 * Remember a document so the welcome screen can offer it back.
 *
 * Keyed on the source path, because that is what reopening needs; the hash
 * rides along so the list can show it and so a moved-but-identical file is
 * recognisable. Persisted in the shell's prefs file, not in the runtime root —
 * a recent is a shell affordance, not a runtime fact.
 */
export function rememberRecent(sessionId: string) {
  const session = getState().sessions.find((s) => s.sessionId === sessionId);
  const path = getState().openedPaths[sessionId];
  if (!session || !path) return;
  const entry: Recent = {
    path,
    name: session.source.name,
    sha256: session.source.sha256,
    bytes: session.source.bytes,
    openedUtc: new Date().toISOString().replace(/\.\d+Z$/, "Z"),
  };
  const next = [entry, ...getState().recents.filter((r) => r.path !== path)].slice(
    0,
    MAX_RECENTS,
  );
  setState({ recents: next });
  void rt.savePrefs({ recents: next });
}

// --- opening ----------------------------------------------------------------

/**
 * Open a document by absolute path. `workspace/openPath` is host-only, and it
 * validates, copies into the session and records the SHA-256 — the source
 * itself is never touched.
 */
export async function openPath(path: string): Promise<string | null> {
  try {
    const opened = await rt.openPath(path);
    const openedPaths = { ...getState().openedPaths, [opened.sessionId]: path };
    setState({ openedPaths });
    // Persisted so a relaunch can still name where a session came from; the
    // Runtime deliberately does not keep the source path.
    await rt.savePrefs({ openedPaths });
    await refreshSessions();
    await selectSession(opened.sessionId);
    return opened.sessionId;
  } catch (e) {
    setState({ inspectPhase: "failed", inspectError: rt.asRuntimeError(e) });
    return null;
  }
}

/** The native file dialog. No web upload, no localhost. */
export async function openViaDialog(): Promise<string | null> {
  const chosen = await openFileDialog({
    multiple: false,
    directory: false,
    title: "한글 문서 열기",
    filters: [{ name: "한글 문서", extensions: ["hwpx", "hwp"] }],
  });
  if (typeof chosen !== "string") return null;
  return openPath(chosen);
}

const SUPPORTED = /\.(hwpx|hwp)$/i;

/** Files dropped on the window. Anything unsupported is refused out loud. */
export async function openDropped(paths: string[]): Promise<void> {
  setState({ dragOver: false });
  const usable = paths.filter((p) => SUPPORTED.test(p));
  if (usable.length === 0) {
    showToast("한글 문서(.hwpx, .hwp)만 열 수 있습니다", 2000);
    return;
  }
  for (const path of usable.slice(0, 1)) {
    await openPath(path);
  }
  if (usable.length > 1) {
    showToast(`${usable.length}개 중 첫 문서만 열었습니다`, 2000);
  }
}

// --- the editing loop ---------------------------------------------------------
//
// A person clicks a 채움 자리, types, and presses Enter. What that does, in
// order, is: build one OperationPlan over every queued edit (plan/propose),
// ask the Runtime what is wrong with it (plan/validate), show the answer,
// and stop. Nothing is written until a human resolves an approval, and the
// approval binds the exact plan hash the human was shown.
//
// The queue accumulates into ONE plan rather than many. That is the protocol's
// own discipline (§3.6, from `com_backend.py:1670`): validate the whole plan
// before the first mutation, so a bad step cannot leave a half-edited
// document. Rebuilding the plan on every change is what makes that possible —
// a plan binds `boundSha256` and hashes its whole op list, so there is no
// "append to the existing plan" operation and inventing one would be a lie
// about what was approved.

/** The seat's current text, from the runtime's own read, never guessed. */
export function seatText(
  inspect: InspectResult | null,
  texts: RegionText[],
  table: number,
  row: number,
  col: number,
): string {
  const region = texts.find(
    (r) => r.addr?.row === row && r.addr?.col === col && (r.table ?? 0) === table,
  );
  if (region?.text !== undefined) return region.text;
  const cell = inspect?.graph.tables
    .find((t) => t.index === table)
    ?.cells.find((c) => c.addr.row === row && c.addr.col === col);
  return cell?.textPreview ?? "";
}

/** The fill seat at an address, with its T30/T127 preflight, or null. */
export function seatAt(
  inspect: InspectResult | null,
  table: number,
  row: number,
  col: number,
): EditableRegion | null {
  return (
    inspect?.regions.regions.find(
      (r) => r.kind === "cell" && r.table === table && r.row === row && r.col === col,
    ) ?? null
  );
}

/**
 * Open a seat for typing.
 *
 * A real `<input>` is mounted in the cell rather than a contenteditable div or
 * a keydown-driven buffer, because Hangul composition is the IME's job and
 * only a real input element gets it: a 두벌식 sequence composes in place, the
 * preedit string is visible while it composes, and Backspace decomposes the
 * syllable rather than deleting it. The spike measured that with real scan
 * codes (M13/M14); this build now has a field to send them to.
 */
export function beginEdit(table: number, row: number, col: number): boolean {
  const state = getState();
  const sessionId = state.activeSessionId;
  if (!sessionId) return false;
  const inspect = state.inspects[sessionId] ?? null;
  const seat = seatAt(inspect, table, row, col);
  if (!seat) {
    showToast("이 칸은 값을 넣는 자리가 아닙니다", 1600);
    return false;
  }
  const queued = state.draft.ops.find(
    (op) => op.table === table && op.row === row && op.col === col,
  );
  setState({
    selection: { kind: "cell", table, row, col },
    inlineEdit: {
      table,
      row,
      col,
      before: queued?.before ?? seatText(inspect, state.texts[sessionId] ?? [], table, row, col),
      charPr: queued?.charPr,
      opId: queued?.opId ?? null,
    },
  });
  return true;
}

export function cancelEdit(): void {
  setState({ inlineEdit: null, sawComposition: false });
}

/** Enter. The value joins the queue and the plan is rebuilt around it. */
export async function commitEdit(value: string): Promise<void> {
  const edit = getState().inlineEdit;
  if (!edit) return;
  setState({
    inlineEdit: null,
    lastCommit: { value, composed: getState().sawComposition },
    sawComposition: false,
  });
  const trimmed = value;
  if (trimmed === edit.before) {
    // Nothing changed. Proposing a no-op plan would put a row in the queue
    // that says "A → A", which is noise the reviewer has to read past.
    if (edit.opId) await removeOp(edit.opId);
    return;
  }
  const ops = getState().draft.ops.filter((op) => op.opId !== edit.opId);
  const next: QueuedOp = {
    opId: edit.opId ?? `op-${cellSlug(edit.table, edit.row, edit.col)}`,
    kind: "fill_cell",
    table: edit.table,
    row: edit.row,
    col: edit.col,
    text: trimmed,
    charPr: edit.charPr,
    before: edit.before,
    origin: "user",
  };
  await setQueue([...ops, next]);
}

function cellSlug(table: number, row: number, col: number): string {
  return `t${table}r${row}c${col}`;
}

/** Change a queued op's value without reopening the cell. */
export async function editOpValue(opId: string, text: string): Promise<void> {
  const ops = getState().draft.ops.map((op) =>
    op.opId === opId
      ? { ...op, text, origin: "user" as const, proposer: undefined }
      : op,
  );
  await setQueue(ops, { rewritten: didRewriteAgent(opId) });
}

/** Declare the charPr the engine itself suggested for this seat (T30). */
export async function declareSuggestedCharPr(opId: string): Promise<void> {
  const state = getState();
  const sessionId = state.activeSessionId;
  const inspect = sessionId ? (state.inspects[sessionId] ?? null) : null;
  const ops = state.draft.ops.map((op) => {
    if (op.opId !== opId) return op;
    const seat = seatAt(inspect, op.table, op.row, op.col);
    // The value is the engine's own `charpr_suggested`, never a shell guess.
    return seat?.charPrSuggested ? { ...op, charPr: seat.charPrSuggested } : op;
  });
  await setQueue(ops, { rewritten: didRewriteAgent(opId) });
}

export async function removeOp(opId: string): Promise<void> {
  const rewritten = didRewriteAgent(opId);
  await setQueue(
    getState().draft.ops.filter((op) => op.opId !== opId),
    { rewritten },
  );
}

/** Was the op being changed one an agent proposed? */
function didRewriteAgent(opId: string): boolean {
  const op = getState().draft.ops.find((x) => x.opId === opId);
  return op?.origin === "agent";
}

export async function clearQueue(): Promise<void> {
  setState({
    draft: EMPTY_DRAFT,
    inlineEdit: null,
    approval: null,
    approvalPhase: "idle",
    approvalError: null,
    applyError: null,
  });
}

/**
 * Replace the queue and rebuild the plan.
 *
 * Any change to the queue invalidates an approval that was already requested —
 * the approval binds a `planHash` and the new plan has a different one — so
 * the approval is dropped here rather than being left pointing at a plan
 * nobody is going to apply. `resolve_approval` would refuse it anyway
 * (`approval_binding_mismatch`); dropping it makes the UI agree with the
 * runtime instead of offering a button that cannot work.
 */
async function setQueue(
  ops: QueuedOp[],
  options: { rewritten?: boolean } = {},
): Promise<void> {
  const state = getState();
  const sessionId = state.activeSessionId;
  const rewritten = state.draft.rewrittenFromAgent || options.rewritten === true;

  setState({
    approval: null,
    approvalPhase: "idle",
    approvalError: null,
    applyError: null,
  });

  if (ops.length === 0 || !sessionId) {
    setState({ draft: { ...EMPTY_DRAFT, rewrittenFromAgent: false } });
    return;
  }

  setState({
    draft: {
      ...state.draft,
      ops,
      sessionId,
      phase: "starting",
      error: null,
      rewrittenFromAgent: rewritten,
    },
  });

  try {
    const plan = await rt.proposePlan(
      sessionId,
      ops.map((op) => ({
        opId: op.opId,
        kind: op.kind,
        table: op.table,
        row: op.row,
        col: op.col,
        text: op.text,
        ...(op.charPr ? { charPr: op.charPr } : {}),
      })),
    );
    const validation = await rt.validatePlan(plan.planId);
    setState({
      draft: {
        ops,
        plan,
        validation,
        sessionId,
        boundSha256: plan.boundSha256,
        phase: "ready",
        error: null,
        rewrittenFromAgent: rewritten,
      },
    });
  } catch (e) {
    // A refusal here is a real answer: `unknown_op_kind`, `unsupported_backend`
    // and `unknown_field` are raised by `plan/propose` before a plan exists at
    // all. Keep the queue, drop the plan, show the payload.
    setState({
      draft: {
        ops,
        plan: null,
        validation: null,
        sessionId,
        boundSha256: null,
        phase: "failed",
        error: rt.asRuntimeError(e),
        rewrittenFromAgent: rewritten,
      },
    });
  }
}

/** Re-propose the queue against the document that is open now. */
export async function reproposeDraft(): Promise<void> {
  const ops = getState().draft.ops;
  if (ops.length === 0) return;
  await setQueue(ops);
}

// --- approval ------------------------------------------------------------------

export async function requestApprovalForDraft(): Promise<void> {
  const state = getState();
  const plan = state.draft.plan;
  if (!plan || !canRequestApproval(state)) return;
  setState({ approvalPhase: "requesting", approvalError: null });
  try {
    const approval = await rt.requestApproval(plan.planId);
    setState({ approval, approvalPhase: "pending" });
  } catch (e) {
    setState({ approvalPhase: "idle", approvalError: rt.asRuntimeError(e) });
  }
}

/**
 * The human gate. HOST authority, and the one place vermilion is spent.
 *
 * Approving does not write anything by itself; it records a decision bound to
 * one plan id and one plan hash. `plan/apply` then refuses unless the approval
 * it is handed binds the plan it is applying, so the bytes that change are the
 * bytes that were approved and no others.
 */
export async function resolveApprovalDecision(
  decision: "approved" | "rejected",
  approver = "host-operator",
): Promise<void> {
  const state = getState();
  const approval = state.approval;
  const plan = state.draft.plan;
  if (!approval || !plan) return;
  setState({ approvalPhase: "resolving", approvalError: null });
  try {
    const resolved = await rt.resolveApproval(
      approval.approvalId,
      plan.planId,
      plan.planHash,
      decision,
      approver,
    );
    setState({ approval: resolved, approvalPhase: "resolved" });
    if (decision === "approved") await applyApproved();
    else showToast("계획을 거절했습니다. 문서는 그대로입니다.", 2000);
  } catch (e) {
    // `plan_stale` lands here when the source moved between the approval
    // request and the decision. Keep the queue; offer a re-propose.
    setState({ approvalPhase: "pending", approvalError: rt.asRuntimeError(e) });
  }
}

// --- apply ----------------------------------------------------------------------

const APPLY_TAG = "apply";

export async function applyApproved(): Promise<void> {
  const state = getState();
  const plan = state.draft.plan;
  const approval = state.approval;
  const sessionId = state.activeSessionId;
  if (!plan || !approval || !sessionId) return;
  setState({ applyPhase: "starting", applyError: null, recovery: null });
  try {
    const applied = await rt.applyPlan(plan.planId, approval.approvalId, APPLY_TAG);
    setState({
      applied,
      applyPhase: "ready",
      // The queue has become a candidate. Keeping the ops on screen would
      // invite a second apply of an already-applied plan, which the runtime
      // would refuse anyway (`approval_already_resolved`).
      draft: EMPTY_DRAFT,
      approvalPhase: "idle",
      approval: null,
      candidateVerdict: { runId: applied.runId, report: applied.checks },
    });
    await loadCandidates(sessionId);
    showToast(`후보본을 만들었습니다 · ${applied.candidate.sha256.slice(0, 12)}`, 2200);
  } catch (e) {
    const error = rt.asRuntimeError(e);
    setState({ applyPhase: "failed", applyError: error });
    // A dead sidecar mid-apply is the ambiguous case: the run directory is
    // removed on any failure inside `apply_plan`, but a process that died
    // between the artifact move and the receipt write leaves neither a
    // candidate nor a signal. Record what was in flight and offer to look.
    if (error.code === "sidecar_down" || error.code === "timeout") {
      setState({
        recovery: {
          planId: plan.planId,
          approvalId: approval.approvalId,
          atUtc: new Date().toISOString().replace(/\.\d+Z$/, "Z"),
          reason: error.message,
          outcome: "unknown",
          runId: null,
        },
      });
    }
  }
}

/** Cooperative cancel, between ops. Never a kill. */
export async function cancelApply(): Promise<void> {
  await rt.cancel(APPLY_TAG);
  showToast("적용을 멈추라고 알렸습니다. 진행 중인 한 단계는 끝납니다.", 2400);
}

/**
 * After a crash: did the apply land or not?
 *
 * `candidate/list` only returns runs whose receipt is on disk, which is
 * precisely the definition of "canonical" (`rt_apply.list_candidates`). So the
 * answer is a list read, not a guess — and if a new candidate is there, its
 * receipt is read to prove the bytes still bind.
 */
export async function resolveRecovery(): Promise<void> {
  const state = getState();
  const recovery = state.recovery;
  const sessionId = state.activeSessionId;
  if (!recovery || !sessionId) return;
  const before = new Set((state.candidates[sessionId] ?? []).map((c) => c.runId));
  await loadCandidates(sessionId);
  const after = getState().candidates[sessionId] ?? [];
  const fresh = after.find((c) => c.runId && !before.has(c.runId));
  if (!fresh?.runId) {
    setState({
      recovery: { ...recovery, outcome: "not_applied" },
      draft: getState().draft,
    });
    return;
  }
  setState({ recovery: { ...recovery, outcome: "applied", runId: fresh.runId } });
  await loadReceipt(fresh.runId);
}

// --- receipts and the candidate's verdict ---------------------------------------

export async function loadReceipt(runId: string): Promise<boolean> {
  const sessionId = getState().activeSessionId;
  if (!sessionId) return false;
  try {
    const receipt = await rt.readReceipt(sessionId, runId);
    setState({
      receipts: { ...getState().receipts, [runId]: receipt },
      receiptError: null,
      candidateVerdict: { runId, report: receipt.checks },
    });
    return true;
  } catch (e) {
    // `candidate_hash_mismatch` and `receipt_body_mismatch` arrive here, and
    // they are the interesting outcomes: the receipt refuses rather than
    // reporting a verdict about bytes that drifted.
    setState({ receiptError: rt.asRuntimeError(e) });
    return false;
  }
}

export function openReceipt(runId: string | null): void {
  setState({ receiptOpen: runId });
  if (runId && !getState().receipts[runId]) void loadReceipt(runId);
}

// --- export -----------------------------------------------------------------------

/**
 * Save the candidate and its receipt where the user chooses.
 *
 * `artifact/exportTo` is GAP (§11.5), so the copy is the shell's own work,
 * done in Rust against a path a native dialog returned. Two files leave
 * together and never separately: an artifact without its receipt is a document
 * with no account of where it came from, which is the thing this program
 * exists not to produce.
 */
export async function exportApplied(destination?: string): Promise<boolean> {
  const state = getState();
  const sessionId = state.activeSessionId;
  const applied = state.applied;
  if (!sessionId || !applied) return false;

  let target = destination;
  if (!target) {
    const suggested = state.sessions
      .find((s) => s.sessionId === sessionId)
      ?.source.name.replace(/(\.hwpx?)$/i, "-candidate$1");
    const chosen = await saveFileDialog({
      title: "후보본 내보내기",
      defaultPath: suggested ?? "candidate.hwpx",
      filters: [{ name: "한글 문서", extensions: ["hwpx", "hwp"] }],
    });
    if (typeof chosen !== "string") return false;
    target = chosen;
  }

  setState({ exportPhase: "starting", exportError: null });
  try {
    const result = await rt.exportCandidate(
      sessionId,
      applied.runId,
      applied.candidate.path,
      target,
    );
    // The bytes that left must be the bytes the receipt bound. Rust hashes the
    // copy it wrote; this is the comparison, and it is a refusal, not a log.
    if (result.sha256 !== applied.candidate.sha256) {
      setState({
        exportPhase: "failed",
        exportError: {
          code: "export_hash_mismatch",
          message:
            "내보낸 파일의 해시가 후보본과 다릅니다. 이 파일을 제출하지 마십시오.",
          data: { expected: applied.candidate.sha256, actual: result.sha256 },
        },
      });
      return false;
    }
    setState({ exportPhase: "ready", exportResult: result });
    showToast("후보본과 영수증을 내보냈습니다", 2000);
    return true;
  } catch (e) {
    setState({ exportPhase: "failed", exportError: rt.asRuntimeError(e) });
    return false;
  }
}

/**
 * Open the file that was just exported, as a new session.
 *
 * This is the only proof that matters about an export: not that a copy
 * succeeded, but that what left the application is still a document this
 * application can read. It goes through `workspace/openPath` like any other
 * open, so the reopened session's own source hash is the runtime's word for
 * the bytes on disk.
 */
export async function reopenExported(): Promise<boolean> {
  const result = getState().exportResult;
  if (!result) return false;
  const sessionId = await openPath(result.path);
  if (!sessionId) return false;
  const session = getState().sessions.find((s) => s.sessionId === sessionId);
  setState({
    reopened: {
      path: result.path,
      sessionId,
      sha256: session?.source.sha256 ?? "",
    },
  });
  return true;
}

// --- page rendering ---------------------------------------------------------------

const RENDER_DPI = 110;

/**
 * Ask for a page raster.
 *
 * `available: false` is a RESULT, not an error (§11.1) — "there is no page
 * image for this document" is an answer the UI has to draw, and the reason
 * comes from a closed set. So the unavailable state is stored, not thrown.
 */
export async function renderCurrentPage(page?: number): Promise<void> {
  const state = getState();
  const sessionId = state.activeSessionId;
  if (!sessionId) return;
  const wanted = (page ?? state.page) - 1;
  setState({ renderPhase: "starting", renderError: null });
  try {
    const render = await rt.renderPage(sessionId, Math.max(0, wanted), RENDER_DPI);
    setState({ render, renderPhase: "ready", page: Math.max(0, wanted) + 1 });
  } catch (e) {
    setState({ renderPhase: "failed", renderError: rt.asRuntimeError(e) });
  }
}

// --- page geometry, and the overlay on the raster (protocol §12) -------------
//
// The rule this whole section is written around: **the overlay is the
// renderer's layout, never ours.** Every rectangle drawn on the page came out
// of `document/pageGeometry`, which read it out of a PDF Hancom laid out. When
// the runtime has no geometry the overlay draws nothing at all — there is no
// fallback that approximates a box from `summary.pageMetrics`, because a box in
// the wrong place is worse than no box: it puts a text cursor where the text
// is not, and it does it with the confidence of a real answer.

/** `${sessionId}:${zeroBasedPage}` — the cache key, and the smoke reads it. */
export function geometryKey(sessionId: string, page: number): string {
  return `${sessionId}:${page}`;
}

/**
 * Keys with a call already in the air.
 *
 * Module-level rather than store state because it is not state anybody
 * renders: it exists so that the mount effect and a caller that asks for the
 * same page in the same tick produce ONE request instead of two. Without it a
 * remount doubles the work, `geometryFetches` counts a call nobody asked for,
 * and the harness's "zoom did not re-fetch" reading gets noisier the faster the
 * machine is.
 */
const geometryInFlight = new Map<string, Promise<void>>();

/**
 * Fetch the geometry for a page, or serve the one already held.
 *
 * Cached per (document, page) and NEVER re-fetched on a zoom change: the rects
 * are fractions of the page, so zooming multiplies them by a different pixel
 * size and asks the runtime nothing (§12.1). `geometryFetches` counts the real
 * calls so a harness can prove that rather than take it on faith.
 */
export async function loadGeometry(page?: number): Promise<void> {
  const state = getState();
  const sessionId = state.activeSessionId;
  if (!sessionId) return;
  const wanted = Math.max(0, (page ?? state.page) - 1);
  const key = geometryKey(sessionId, wanted);

  const held = state.geometryCache[key];
  if (held) {
    setState({ geometry: held, geometryPhase: "ready", geometryError: null });
    return;
  }
  const pending = geometryInFlight.get(key);
  if (pending) return pending;

  setState({ geometryPhase: "starting", geometryError: null });
  const call = (async () => {
    try {
      const geometry = await rt.pageGeometry(sessionId, wanted);
      setState({
        geometry,
        geometryPhase: "ready",
        geometryCache: { ...getState().geometryCache, [key]: geometry },
        geometryFetches: getState().geometryFetches + 1,
      });
    } catch (e) {
      // A THROWN error is not the same as `available: false`. The latter is an
      // answer with a reason from a closed set; this is the method failing, and
      // conflating them would let a transport fault masquerade as "this
      // document has no page".
      setState({
        geometryPhase: "failed",
        geometry: null,
        geometryError: rt.asRuntimeError(e),
        geometryFetches: getState().geometryFetches + 1,
      });
    } finally {
      geometryInFlight.delete(key);
    }
  })();
  geometryInFlight.set(key, call);
  return call;
}

/** Is this address a seat the editor will actually open? Runtime's answer. */
export function addressIsEditable(address: GeometryAddress | null | undefined): boolean {
  if (!address || address.kind !== "cell") return false;
  if (address.table == null || address.row == null || address.col == null) return false;
  const state = getState();
  const inspect = state.activeSessionId
    ? (state.inspects[state.activeSessionId] ?? null)
    : null;
  return seatAt(inspect, address.table, address.row, address.col) !== null;
}

/** How the status bar spells an address. Same vocabulary as 위치. */
export function addressLabel(address: GeometryAddress): string {
  if (address.kind === "cell") {
    return `표${address.table} (${address.row},${address.col})`;
  }
  if (address.atPara !== undefined && address.atPara !== null) {
    return `문단 ${address.atPara}`;
  }
  return address.text ? `앵커 “${trimRun(address.text, 12)}”` : "주소 없음";
}

/** Open the seat at an address in the SAME editor a tree click opens. */
function openAddress(address: GeometryAddress): boolean {
  if (address.table == null || address.row == null || address.col == null) return false;
  return beginEdit(address.table, address.row, address.col);
}

/**
 * A click on the page. One of four honest outcomes, and never a fifth.
 *
 * The mutation path is untouched: an editable target calls `beginEdit`, which
 * is the same function `TextView` calls and the same one the IME harness types
 * into. There is no overlay-shaped edit route, no second plan builder and no
 * second validator — a value typed on the page and a value typed in the tree
 * become the same `fill_cell` op in the same queue.
 */
export function clickOverlaySeat(seat: GeometrySeat): void {
  const address: GeometryAddress = {
    kind: "cell",
    table: seat.table ?? null,
    row: seat.row ?? null,
    col: seat.col ?? null,
  };
  const id = `seat-${seat.table}-${seat.row}-${seat.col}`;
  if (!addressIsEditable(address)) {
    // The runtime placed a rect for a cell the T30/T127 preflight does not
    // offer as a seat. Say so; do not open an editor that would refuse anyway.
    setState({
      overlayPick: {
        kind: "not_editable",
        targetId: id,
        address,
        label: `${addressLabel(address)} — 값을 넣는 자리가 아닙니다`,
      },
    });
    return;
  }
  setState({
    overlayPick: { kind: "seat", targetId: id, address, label: addressLabel(address) },
  });
  openAddress(address);
}

/** A click on a mapped line of text. */
export function clickOverlaySpan(span: GeometrySpan): void {
  const id = `span-${span.index}`;
  if (span.confidence === "ambiguous") {
    // T41, surfaced. `engine/scripts/preedit.py:221`: one unscoped key
    // overwrote five sibling contracts in a six-contract pack and every
    // offline gate passed, because the label survived as a prefix. So the
    // click ASKS. It does not pick the first candidate, it does not pick the
    // nearest, and it does not queue anything.
    const candidates = span.candidates ?? [];
    setState({
      overlayPick: {
        kind: "ambiguous",
        targetId: id,
        candidates,
        label: `후보 ${candidates.length}개 — 직접 선택`,
      },
    });
    return;
  }
  const address = span.address;
  if (!address) return; // unmapped: not clickable, and nothing to say
  if (!addressIsEditable(address)) {
    setState({
      overlayPick: {
        kind: "not_editable",
        targetId: id,
        address,
        label: `${addressLabel(address)} — 값을 넣는 자리가 아닙니다`,
      },
    });
    if (address.kind === "cell" && address.table != null && address.row != null &&
        address.col != null) {
      setSelection({ kind: "cell", table: address.table, row: address.row, col: address.col });
    }
    return;
  }
  setState({
    overlayPick: { kind: "unique", targetId: id, address, label: addressLabel(address) },
  });
  openAddress(address);
}

/**
 * The person picked one of the candidates. THEIR choice, recorded as theirs.
 *
 * Nothing is queued by this call either — it opens the editor on the chosen
 * seat, exactly as a direct click on an unambiguous one would, and the value
 * still has to be typed and still has to be approved.
 */
export function chooseCandidate(address: GeometryAddress): void {
  const pick = getState().overlayPick;
  if (!addressIsEditable(address)) {
    setState({
      overlayPick: {
        kind: "not_editable",
        targetId: pick?.targetId ?? "candidate",
        address,
        label: `${addressLabel(address)} — 값을 넣는 자리가 아닙니다`,
      },
    });
    return;
  }
  setState({
    overlayPick: {
      kind: "unique",
      targetId: pick?.targetId ?? "candidate",
      address,
      label: `${addressLabel(address)} — 사용자가 고름`,
    },
  });
  openAddress(address);
}

export function dismissOverlayPick(): void {
  setState({ overlayPick: null });
}

/**
 * 페이지 그림 만들기 — the host-only Hancom conversion.
 *
 * Every refusal it can raise is designed for, because every one of them is a
 * real state of a real machine: `needs_hancom` (this machine has none),
 * `com_busy` (somebody else's Hancom is up — and the Runtime will not kill it,
 * see `rt_convert` rule 2), `not_convertible`, `convert_failed` (the converter
 * ran and did not produce a PDF, which is what a broken COM registration looks
 * like from here).
 */
export async function preparePages(): Promise<void> {
  const sessionId = getState().activeSessionId;
  if (!sessionId) return;
  setState({ preparePhase: "starting", prepareError: null, prepareNote: null });
  try {
    const result = await rt.renderPrepare(sessionId);
    setState({
      preparePhase: "ready",
      prepareNote: result.prepared
        ? `PDF를 만들었습니다 · ${result.pdf?.sha256.slice(0, 12)}`
        : (result.reason ?? "이미 준비되어 있습니다"),
    });
    await renderCurrentPage(1);
  } catch (e) {
    setState({ preparePhase: "failed", prepareError: rt.asRuntimeError(e) });
  }
}

// --- events -------------------------------------------------------------------------

/**
 * Subscribe to the session's own `events.jsonl`.
 *
 * `after: -1` replays from the beginning, so the timeline shows the document's
 * whole history — including everything that happened in a previous launch —
 * rather than starting empty and filling in only while this window happens to
 * be open. The replay and every later event arrive after the subscribe
 * response, so the subscription id is always known before its first event.
 */
export async function startEvents(sessionId: string): Promise<void> {
  const previous = getState().eventSubscription;
  if (previous) {
    try {
      await rt.unsubscribeEvents(previous);
    } catch {
      // A subscription that is already gone is not a failure worth surfacing.
    }
  }
  setState({ eventSubscription: null, events: [], eventPhase: "starting", eventError: null });
  try {
    const { subscriptionId } = await rt.subscribeEvents(sessionId, -1, 250);
    setState({ eventSubscription: subscriptionId, eventPhase: "ready" });
  } catch (e) {
    setState({ eventPhase: "failed", eventError: rt.asRuntimeError(e) });
  }
}

// --- the agent door -------------------------------------------------------------------

export async function refreshAgentTool(): Promise<void> {
  try {
    setState({ agentTool: await rt.agentToolStatus() });
  } catch (e) {
    setState({
      agentTool: { available: false, script: null, reason: String(e) },
    });
  }
}

/**
 * 에이전트 제안 받기 — run the mock agent through the AGENT door.
 *
 * It connects on its own `serve.py --entry agent` connection to the same
 * `--root`, proposes a typed plan, validates it and requests approval. Then it
 * stops, and not because it chose to: `plan/apply` and `approval/resolve` are
 * absent from an agent connection's registry, so the methods are
 * `unknown_method` there (§9). Its plan lands in the SAME queue this shell's
 * own edits use, and is approved by the same human gate — which is the claim,
 * demonstrated rather than asserted.
 */
export async function runAgentProposal(marker = "MOCK-AGENT-0001"): Promise<boolean> {
  const state = getState();
  const sessionId = state.activeSessionId;
  if (!sessionId) return false;
  setState({ agentPhase: "starting", agentError: null });
  try {
    const outcome = await rt.runMockAgent(sessionId, marker);
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(outcome.stdout) as Record<string, unknown>;
    } catch {
      throw {
        code: "agent_output_unreadable",
        message: "에이전트가 JSON을 내놓지 않았습니다.",
        data: { exitCode: outcome.exitCode, stderr: outcome.stderr.slice(-1200) },
      };
    }
    const plan = parsed.plan as { planId: string; ops: Array<Record<string, unknown>> };
    const approval = parsed.approval as { approvalId: string; state: string } | null;

    // Read the plan back over OUR connection rather than trusting the agent's
    // copy of it. The queue must show what the Runtime holds, because that is
    // what an approval will bind to.
    //
    // Shared with the composer since Phase 5 (`adoptAgentPlan`): the mock
    // button and a typed instruction MUST end in the same queue in the same
    // shape, and two code paths claiming to do that would eventually stop.
    // The agent already requested approval on its own connection; that request
    // is a real record under this root, so it is adopted rather than
    // re-created, and its `requestedBy` keeps saying who asked.
    const { plan: authoritative } = await adoptAgentPlan(
      sessionId,
      plan.planId,
      approval?.approvalId ?? null,
    );
    setState({
      agentPhase: "ready",
      agentRun: {
        ok: parsed.ok === true,
        door: String(parsed.door ?? "protocol"),
        scenario: String(parsed.scenario ?? ""),
        marker: String(parsed.marker ?? marker),
        planId: authoritative.planId,
        approvalId: approval?.approvalId ?? null,
        approvalState: approval?.state ?? "none",
        proposer: authoritative.proposer,
        neverCalled: (parsed.neverCalled as string[]) ?? [],
        exitCode: outcome.exitCode,
      },
    });
    return true;
  } catch (e) {
    setState({ agentPhase: "failed", agentError: rt.asRuntimeError(e) });
    return false;
  }
}

// --- checking ---------------------------------------------------------------

/**
 * 검사 실행 — the document's own preflight, and, once a candidate exists, the
 * real offline verdict for it.
 *
 * Two halves, kept apart on purpose because they are different claims:
 *
 * 1. **The source's preflight.** `document/inspect` and `document/readRegion`
 *    re-read, then the engine's own facts are reported: `color_anomaly`
 *    (T127 — the blue body text that once shipped as clean), `scriptAnomaly`
 *    (T30), per-run colour drift. Every finding carries an address.
 *
 * 2. **The candidate's verdict.** `receipt/read` re-hashes the artifact
 *    against its binding before it returns anything, and the `checks` it
 *    carries are `check_residue`'s own output from the run that produced the
 *    candidate — a real offline verification, executed by the Runtime, not
 *    re-derived here. `acceptance` is true only if every required check RAN
 *    and was clean; a check that could not run is `unavailable` and is never
 *    counted as a pass.
 *
 * What is still NOT available, and is not dressed up as if it were: a fresh
 * RE-RUN of the checkers on demand. `verify/*` is GAP on the wire (§11.5) and
 * `RuntimeCore.candidate_verify` is domain-only, reachable from the CLI and
 * not from here. So the badge distinguishes "verified at apply" from "verified
 * just now", and the second one is honestly absent.
 */
export async function runCheck(): Promise<void> {
  const sessionId = getState().activeSessionId;
  if (!sessionId) return;
  setState({ checkPhase: "starting", sheetOpen: true });

  await loadInspect(sessionId, true);
  await loadText(sessionId, true);

  const inspect = getState().inspects[sessionId];
  if (!inspect) {
    setState({ checkPhase: "failed" });
    return;
  }
  const findings = collectFindings(inspect, getState().texts[sessionId] ?? []);
  setState({
    findings,
    checkPhase: "ready",
    checkedAt: new Date().toISOString().replace(/\.\d+Z$/, "Z"),
  });
  await loadCandidates(sessionId);

  // The candidate half. Newest run last in `candidate/list` (sorted run dirs),
  // and the one the user just made is the one they mean.
  const applied = getState().applied;
  const rows = getState().candidates[sessionId] ?? [];
  const runId = applied?.runId ?? rows[rows.length - 1]?.runId ?? null;
  if (runId) {
    const ok = await loadReceipt(runId);
    if (!ok) setState({ candidateVerdict: null });
  } else {
    setState({ candidateVerdict: null });
  }
}

/** Every finding the candidate's own verification report carries. */
export function verdictFindings(report: VerificationReport): Finding[] {
  const out: Finding[] = [];
  for (const row of report.checks) {
    const state = String(row.state ?? "unknown");
    if (state !== "ran") {
      out.push({
        code: `${row.checker}_unavailable`,
        severity: "warn",
        where: `검사 ${row.checker}`,
        selection: null,
        message: `이 검사는 실행되지 않았습니다: ${String(row.reason ?? "이유 없음")}. 실행되지 않은 검사는 통과로 세지 않습니다.`,
      });
      continue;
    }
    const hard = (row.hard as Array<{ code?: string; msg?: string; at?: string }>) ?? [];
    const warn = (row.warn as Array<{ code?: string; msg?: string; at?: string }>) ?? [];
    for (const item of hard) {
      out.push({
        code: item.code ?? "hard",
        severity: "hard",
        where: item.at ?? `검사 ${row.checker}`,
        selection: null,
        message: item.msg ?? "",
      });
    }
    for (const item of warn) {
      out.push({
        code: item.code ?? "warn",
        severity: "warn",
        where: item.at ?? `검사 ${row.checker}`,
        selection: null,
        message: item.msg ?? "",
      });
    }
  }
  return out;
}

export function collectFindings(inspect: InspectResult, texts: RegionText[]): Finding[] {
  const out: Finding[] = [];

  for (const region of inspect.regions.regions) {
    if (region.kind !== "cell" || region.table === undefined) continue;
    const where = `표 ${region.table} R${region.row}C${region.col}`;
    const selection = {
      kind: "cell" as const,
      table: region.table,
      row: region.row!,
      col: region.col!,
    };
    if (region.colorAnomaly) {
      out.push({
        code: "color_anomaly",
        severity: "hard",
        where,
        selection,
        message: "글자색이 본문 기준과 다릅니다. 이대로 채우면 색이 남습니다.",
      });
    }
    if (region.scriptAnomaly) {
      out.push({
        code: "fill_charpr_script_anomaly",
        severity: "warn",
        where,
        selection,
        message: `글자 속성이 본문 기준과 다릅니다. charPr ${region.charPr} → ${region.charPrSuggested} 권장.`,
      });
    }
  }

  // Runs carry the colour the document really has; a seat can look clean at
  // cell level and still contain a coloured run.
  for (const region of texts) {
    for (const run of region.runs ?? []) {
      if (!run.color_anomaly) continue;
      const isCell = region.addr !== undefined;
      out.push({
        code: "run_color_anomaly",
        severity: "warn",
        where: isCell
          ? `표 ${region.table} R${region.addr!.row}C${region.addr!.col} #${run.index}`
          : `문단 ${region.at_para} #${run.index}`,
        selection: isCell
          ? {
              kind: "cell",
              table: region.table ?? 0,
              row: region.addr!.row,
              col: region.addr!.col,
            }
          : region.at_para !== undefined
            ? { kind: "paragraph", atPara: region.at_para }
            : null,
        message: `본문 기준과 다른 색(${run.color_value ?? "알 수 없음"})으로 쓰인 글이 있습니다: "${trimRun(run.text)}"`,
      });
    }
  }

  for (const target of inspect.summary.scriptAnomalyTargets) {
    const where = `표 ${target.table} R${target.addr.row}C${target.addr.col}`;
    if (out.some((f) => f.where === where && f.code.includes("script"))) continue;
    out.push({
      code: "script_anomaly_target",
      severity: "warn",
      where,
      selection: {
        kind: "cell",
        table: target.table,
        row: target.addr.row,
        col: target.addr.col,
      },
      message: `글자 속성 ${target.differing.join(", ")}이(가) 기준과 다릅니다. charPr ${target.charpr} → ${target.charpr_suggested}.`,
    });
  }

  if (out.length === 0) {
    out.push({
      code: "clean",
      severity: "info",
      where: "문서 전체",
      selection: null,
      message: "이 빌드가 볼 수 있는 범위에서는 걸리는 것이 없습니다. 렌더 증명과 제출 검사는 아직 실행할 수 없습니다.",
    });
  }
  return out;
}

function trimRun(text: string, max = 24): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max)}…` : flat;
}

// --- copy -------------------------------------------------------------------

/**
 * Ctrl+C. Defers to a real text selection when the user made one — the paper
 * column is selectable and dragging across it should behave like text — and
 * otherwise copies whatever the selected node contains.
 *
 * Returns false when it did nothing, so the key handler can let the event
 * through to the browser's own copy.
 */
export async function copySelection(): Promise<boolean> {
  const dom = window.getSelection()?.toString() ?? "";
  if (dom.trim().length > 0) return false;

  const state = getState();
  const selection = state.selection;
  const sessionId = state.activeSessionId;
  if (!selection || !sessionId) return false;

  const texts = state.texts[sessionId] ?? [];
  const inspect = state.inspects[sessionId];
  let text: string | null = null;
  let label = "";

  if (selection.kind === "cell") {
    const region = texts.find(
      (r) =>
        r.addr?.row === selection.row &&
        r.addr?.col === selection.col &&
        (r.table ?? 0) === selection.table,
    );
    text =
      region?.text ??
      inspect?.graph.tables
        .find((t) => t.index === selection.table)
        ?.cells.find((c) => c.addr.row === selection.row && c.addr.col === selection.col)
        ?.textPreview ??
      null;
    label = `표 ${selection.table} R${selection.row}C${selection.col}`;
  } else if (selection.kind === "paragraph") {
    text =
      inspect?.graph.paragraphs.find((p) => p.at_para === selection.atPara)?.text ?? null;
    label = `문단 ${selection.atPara}`;
  }

  if (text === null || text.length === 0) {
    showToast("복사할 글이 없습니다", 1400);
    return true;
  }
  await writeClipboard(text);
  showToast(`${label} 복사됨`, 1400);
  return true;
}

async function writeClipboard(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    return;
  } catch {
    // Fall through: some webview configurations refuse the async API.
  }
  const scratch = document.createElement("textarea");
  scratch.value = text;
  scratch.setAttribute("readonly", "");
  scratch.style.position = "fixed";
  scratch.style.opacity = "0";
  document.body.appendChild(scratch);
  scratch.select();
  try {
    document.execCommand("copy");
  } finally {
    document.body.removeChild(scratch);
  }
}

// --- UI zoom ----------------------------------------------------------------

/**
 * Scale the whole app. Uses the webview's own zoom rather than root font-size
 * so vector chrome, the paper column and the logo scale together and text
 * stays crisply re-rasterised rather than resampled.
 *
 * Independent of `zoom`, which is the page-preview scale.
 */
export async function applyUiZoom(factor: number, announce = true): Promise<void> {
  const clamped = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, factor));
  setState({ uiZoom: clamped });
  try {
    await getCurrentWebview().setZoom(clamped);
  } catch {
    // A webview that refuses zoom must not break the app; the store still
    // holds the value and the next launch will try again.
  }
  await rt.savePrefs({ uiZoom: clamped });
  if (announce) showToast(`${Math.round(clamped * 100)}%`);
}

export function stepUiZoom(direction: 1 | -1): void {
  const current = getState().uiZoom;
  const index = ZOOM_STEPS.findIndex((z) => Math.abs(z - current) < 0.001);
  const from = index === -1 ? ZOOM_STEPS.indexOf(1) : index;
  const next = ZOOM_STEPS[Math.min(ZOOM_STEPS.length - 1, Math.max(0, from + direction))];
  void applyUiZoom(next);
}

export const resetUiZoom = () => void applyUiZoom(1);

// --- lifecycle --------------------------------------------------------------

/**
 * Start the runtime and restore what the last run was doing.
 *
 * Objective: close and reopen without a terminal. The Runtime already persists
 * sessions on disk under `--root`, so reattaching is remembering the root and
 * the session id and then calling `session/list`.
 */
export async function boot(): Promise<void> {
  setState({ phase: "starting", phaseNote: "런타임을 시작하는 중", fatal: null });
  try {
    const prefs = await rt.loadPrefs();
    const root = (prefs.root as string | undefined) ?? (await rt.defaultRoot());

    // Restore chrome before the window is shown, so nothing visibly resizes.
    const savedZoom = Number(prefs.uiZoom);
    if (Number.isFinite(savedZoom) && savedZoom !== 1) {
      await applyUiZoom(savedZoom, false);
    }
    if (Array.isArray(prefs.recents)) setState({ recents: prefs.recents as Recent[] });
    if (prefs.openedPaths && typeof prefs.openedPaths === "object") {
      setState({ openedPaths: prefs.openedPaths as Record<string, string> });
    }

    const { status } = await rt.start(root);
    setState({ status, root: status.root ?? root, phaseNote: "능력을 확인하는 중" });

    setState({ capabilities: await rt.capabilities() });
    // Whether the dev-mode agent door is reachable from this build. Cheap:
    // it is a file existence check, not a spawn.
    await refreshAgentTool();
    // Phase 5, and all three are cheap for the same reason: a path test, a
    // prefs read, and one short-lived child. None of them touches a provider
    // and none of them needs a credential, so a cold boot with nothing
    // configured still ends with a composer that can explain itself.
    await refreshAgentHost();
    await loadProviderSettings();
    await loadTaskPacks();
    setState({ phaseNote: "열린 문서를 찾는 중" });
    await refreshSessions();

    const remembered = prefs.lastSessionId as string | undefined;
    const sessions = getState().sessions;
    const target =
      (remembered && sessions.find((s) => s.sessionId === remembered)?.sessionId) ??
      sessions[0]?.sessionId;

    setState({ view: prefs.lastView === "agent" ? "agent" : "document" });

    if (target) {
      setState({ phaseNote: "문서를 다시 읽는 중" });
      await selectSession(target);
    }
    setState({ phase: "ready", phaseNote: "" });
  } catch (e) {
    setState({ phase: "failed", fatal: rt.asRuntimeError(e) });
  }
}

/** A dead sidecar must be recoverable without losing document state. */
export async function restartRuntime(): Promise<void> {
  const keepSession = getState().activeSessionId;
  setState({ phase: "starting", phaseNote: "런타임을 다시 시작하는 중", fatal: null });
  try {
    const { status } = await rt.start(getState().root);
    // The old subscription died with the old process; it is not resumable and
    // pretending otherwise would leave the timeline silently frozen.
    setState({ status, capabilities: await rt.capabilities(), eventSubscription: null });
    await refreshSessions();
    if (keepSession && getState().sessions.some((s) => s.sessionId === keepSession)) {
      setState({ activeSessionId: keepSession });
      await startEvents(keepSession);
    }
    setState({ phase: "ready", phaseNote: "" });
  } catch (e) {
    setState({ phase: "failed", fatal: rt.asRuntimeError(e) });
  }
}

export { setSelection };

// --- the Agent Host: the composer's other end (Phase 5) -----------------------
//
// The whole point of this section is the ONE queue. An instruction typed in the
// composer, a value typed into a fill seat, and the mock button all end in the
// same `draft`, behind the same approval gate, and the queue says which is
// which per op. Nothing here can approve: `host.py` speaks
// `serve.py --entry agent`, where `approval/resolve` and `plan/apply` are not
// in the registry at all (protocol §4). The shell does not enforce that — it
// could not grant them if it tried — and the payload's `neverCompiled` is put
// on screen so a reviewer can read the claim rather than take it.

export async function refreshAgentHost(): Promise<void> {
  try {
    setState({ agentHost: await rt.agentHostStatus() });
  } catch (e) {
    setState({
      agentHost: {
        available: false,
        mode: null,
        script: null,
        program: null,
        reason: String(e),
      },
    });
  }
}

/** Load the saved provider settings, and ask the store whether the key is there. */
export async function loadProviderSettings(): Promise<void> {
  const prefs = await rt.loadPrefs().catch(() => ({}) as Record<string, unknown>);
  const saved = prefs.provider as Partial<ProviderSettings> | undefined;
  const provider: ProviderSettings = {
    ...DEFAULT_PROVIDER,
    ...(saved ?? {}),
    router: { ...DEFAULT_PROVIDER.router, ...(saved?.router ?? {}) },
    anthropic: { ...DEFAULT_PROVIDER.anthropic, ...(saved?.anthropic ?? {}) },
  };
  setState({ provider });
  await refreshCredential();
}

/** Present / absent / how many bytes. The value is never asked for. */
export async function refreshCredential(): Promise<void> {
  const key = activeStoreKey(getState().provider);
  if (!key) {
    setState({ credential: null });
    return;
  }
  try {
    setState({ credential: await rt.credentialStatus(key) });
  } catch (e) {
    setState({ credential: { key, state: "absent", bytes: 0, reason: String(e) } });
  }
}

/**
 * Save the settings, and write the provider's config file.
 *
 * Two stores, deliberately different: the shell's own prefs hold what the UI
 * needs to draw itself again (which provider, which base URL, which STORE KEY
 * NAME), and the config file holds what the Agent Host reads. Neither holds a
 * secret, and the Rust side refuses a secret-shaped member by name before the
 * file is written.
 */
export async function saveProviderSettings(next: ProviderSettings): Promise<boolean> {
  setState({ provider: next, providerProfile: null, probeError: null, probePhase: "idle" });
  await rt.savePrefs({ provider: next as unknown as Record<string, unknown> });
  await refreshCredential();
  if (next.provider === "mock") return true;
  try {
    await rt.agentHostSaveConfig(
      next.provider,
      providerConfigFields(next),
      getState().credential?.state === "present",
    );
    return true;
  } catch (e) {
    setState({ probeError: rt.asRuntimeError(e) });
    return false;
  }
}

/**
 * Put a secret in the OS credential store.
 *
 * The value crosses IPC exactly once, in this direction, and is not written to
 * the store's state, to prefs, or to any log. The caller clears its input
 * immediately afterwards; there is no read-back and no "show" control, because
 * a field that can display a key is a field that can be screenshotted.
 */
export async function storeCredential(secret: string): Promise<boolean> {
  const key = activeStoreKey(getState().provider);
  if (!key) {
    setState({
      probeError: {
        code: "credential_name_missing",
        message: "먼저 자격 증명 이름을 정해야 합니다.",
      },
    });
    return false;
  }
  try {
    await rt.credentialSet(key, secret);
    await refreshCredential();
    // The config's credential member appears only once a key really exists.
    await saveProviderSettings(getState().provider);
    showToast("자격 증명을 이 기계의 저장소에 넣었습니다");
    return true;
  } catch (e) {
    setState({ probeError: rt.asRuntimeError(e) });
    return false;
  }
}

export async function forgetCredential(): Promise<boolean> {
  const key = activeStoreKey(getState().provider);
  if (!key) return false;
  try {
    await rt.credentialDelete(key);
    await refreshCredential();
    await saveProviderSettings(getState().provider);
    return true;
  } catch (e) {
    setState({ probeError: rt.asRuntimeError(e) });
    return false;
  }
}

/**
 * 연결 확인 — `--capabilities`, and nothing more.
 *
 * No network call and no document: this asks the adapter to DESCRIBE itself,
 * which is why it works with no key and why its answer is trustworthy about
 * what it does not know. Three states reach the screen unchanged; an `unknown`
 * is never rounded to a yes or a no, because that is the entire reason the
 * third state exists.
 */
export async function probeProvider(): Promise<boolean> {
  const state = getState();
  setState({ probePhase: "starting", probeError: null });
  try {
    const outcome = await rt.agentHostCapabilities(
      state.provider.provider,
      activeStoreKey(state.provider),
    );
    if (!outcome.payload.ok || !outcome.payload.provider) {
      setState({
        probePhase: "failed",
        providerProfile: null,
        probeError:
          (outcome.payload.error as RuntimeError | undefined) ?? {
            code: "capabilities_failed",
            message: `에이전트 호스트가 exit ${outcome.exitCode} 로 끝났습니다.`,
            detail: outcome.stderr,
          },
      });
      return false;
    }
    setState({ probePhase: "ready", providerProfile: outcome.payload.provider });
    await refreshCredential();
    return true;
  } catch (e) {
    setState({ probePhase: "failed", providerProfile: null, probeError: rt.asRuntimeError(e) });
    return false;
  }
}

/**
 * Adopt a plan an agent proposed into this shell's review queue.
 *
 * Shared by the mock button and the composer, because the two must be
 * indistinguishable downstream: whatever proposed it, the queue holds the
 * Runtime's own copy of the plan, validated over THIS connection, with every op
 * marked as the agent's.
 */
async function adoptAgentPlan(
  sessionId: string,
  planId: string,
  approvalId: string | null,
): Promise<{ plan: OperationPlan; validation: PlanValidation }> {
  const authoritative = await rt.getPlan(planId);
  const validation = await rt.validatePlan(planId);
  const inspect = getState().inspects[sessionId] ?? null;
  const texts = getState().texts[sessionId] ?? [];
  const ops: QueuedOp[] = authoritative.ops.map((op) => {
    const params = op.params as Record<string, number | string>;
    const table = Number(params.table ?? 0);
    const row = Number(params.row);
    const col = Number(params.col);
    return {
      opId: op.opId,
      kind: "fill_cell",
      table,
      row,
      col,
      text: String(params.text ?? ""),
      charPr: params.charPr === undefined ? undefined : String(params.charPr),
      before: seatText(inspect, texts, table, row, col),
      origin: "agent",
      proposer: authoritative.proposer,
    };
  });
  const draft: Draft = {
    ops,
    plan: authoritative,
    validation,
    sessionId,
    boundSha256: authoritative.boundSha256,
    phase: "ready",
    error: null,
    rewrittenFromAgent: false,
  };
  setState({
    draft,
    approval: approvalId ? await rt.getApproval(approvalId).catch(() => null) : null,
    approvalPhase: approvalId ? "pending" : "idle",
    approvalError: null,
  });
  return { plan: authoritative, validation };
}

/** Ids are the shell's, not the host's: the tail thread keys events on them. */
function newTurnId(): string {
  return `t${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

/**
 * Send one instruction. One process, one turn, one plan.
 *
 * The turn card appears before the process does, so a slow provider looks like
 * work in progress rather than a dropped message, and the host's own events
 * stream into it live while it runs (`agenthost://events`, tailed and batched
 * in Rust). When the run ends, the plan — if there is one — is re-read over
 * this shell's connection and adopted into the review queue.
 *
 * A provider fault is NEVER reported as a document verdict. `ah_host` keeps
 * that separation on its side and this keeps it here: `providerFault` gets its
 * own state on the card, the queue is untouched, and no reply is invented.
 */
export async function sendInstruction(instruction: string): Promise<boolean> {
  const state = getState();
  const sessionId = state.activeSessionId;
  const text = instruction.trim();
  if (!sessionId || text === "" || composerBlocker(state) !== null) return false;

  const id = newTurnId();
  const turn: Turn = {
    id,
    instruction: text,
    at: new Date().toISOString().replace(/\.\d+Z$/, "Z"),
    phase: "starting",
    provider: state.provider.provider,
    events: [],
    payload: null,
    exitCode: null,
    error: null,
    planId: null,
  };
  setState({ turns: [...state.turns, turn], activeTurn: id });

  try {
    const outcome = await rt.agentHostRun({
      sessionId,
      instruction: text,
      provider: state.provider.provider,
      storeKey: activeStoreKey(state.provider),
      scenario: state.provider.provider === "mock" ? state.provider.scenario : null,
      turnId: id,
    });
    const payload = outcome.payload;
    patchTurn(id, {
      phase: payload.ok ? "ready" : "failed",
      payload,
      exitCode: outcome.exitCode,
      // The host's own log is authoritative and complete at exit. The tailed
      // events are the same lines arriving early; taking the final copy means
      // a turn whose tail thread missed a flush still shows everything.
      events: payload.events?.events ?? getState().turns.find((t) => t.id === id)?.events ?? [],
    });

    const planId = payload.plan?.planId ?? null;
    if (planId) {
      await adoptAgentPlan(sessionId, planId, payload.approval?.approvalId ?? null);
      patchTurn(id, { planId });
    }
    setState({ activeTurn: null });
    return payload.ok;
  } catch (e) {
    patchTurn(id, { phase: "failed", error: rt.asRuntimeError(e) });
    setState({ activeTurn: null });
    return false;
  }
}

/** Stop the run in flight. It holds no document lock; nothing can be torn. */
export async function stopInstruction(): Promise<boolean> {
  const id = getState().activeTurn;
  const stopped = await rt.agentHostStop().catch(() => false);
  if (id) {
    patchTurn(id, {
      phase: "failed",
      error: { code: "cancelled", message: "사람이 중간에 멈췄습니다." },
    });
  }
  setState({ activeTurn: null });
  return stopped;
}

// --- 작업 팩 --------------------------------------------------------------------

export async function loadTaskPacks(): Promise<void> {
  try {
    setState({ taskPacks: await rt.taskPacks() });
  } catch (e) {
    setState({
      taskPacks: { available: false, mode: null, reason: String(e), packs: [] },
    });
  }
}

// --- the window ------------------------------------------------------------------

export async function toggleFullscreen(): Promise<void> {
  try {
    setState({ fullscreen: await rt.toggleFullscreen() });
  } catch {
    // A window control is an affordance, not a dependency.
  }
}

/**
 * Esc, once, in one place.
 *
 * Three overlays can be open and they close in a fixed order — the innermost
 * first — so a person pressing Esc twice does not find the second press
 * closing something they were not looking at.
 */
export function closeTopmostOverlay(): boolean {
  const state = getState();
  if (state.inlineEdit) {
    cancelEdit();
    return true;
  }
  if (state.receiptOpen) {
    openReceipt(null);
    return true;
  }
  if (state.settingsOpen) {
    setState({ settingsOpen: false });
    return true;
  }
  if (state.packOpen) {
    setState({ packOpen: null });
    return true;
  }
  if (state.sheetOpen) {
    setState({ sheetOpen: false });
    return true;
  }
  return false;
}

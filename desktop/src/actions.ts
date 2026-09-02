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
  headCandidate,
  locateSelection,
  patchTurn,
  providerConfigFields,
  setCenterMode,
  setState,
  setSelection,
  setView,
  showToast,
  queuedOpAt,
  queuedRunOpAt,
  type Draft,
  type QueuedOp,
} from "./store";
import type {
  AppliedCandidate,
  EditableRegion,
  Finding,
  GeometryAddress,
  GeometrySeat,
  GeometrySpan,
  InspectResult,
  OperationPlan,
  PlanOp,
  PlanValidation,
  ProviderSettings,
  Recent,
  RegionText,
  RuntimeError,
  TextRun,
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
          // A module report names the document it checked. Carrying one across
          // a document switch would put another file's verdict under this
          // file's heading, which is the same class of lie as a stale geometry.
          packRun: null,
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
  const queued = queuedOpAt(state, table, row, col);
  setState({
    selection: { kind: "cell", table, row, col },
    inlineEdit: {
      kind: "cell",
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

/**
 * Why a click on a mapped paragraph line could NOT put a caret in it.
 *
 * A closed set, because every one of these is a real answer the runtime gave
 * and the status bar prints a different sentence for each. "Nothing happened"
 * is the one outcome not allowed here: a person who clicks visibly mapped text
 * and gets silence concludes the feature is broken, when the honest answer is
 * that this paragraph has no single run to address.
 */
export type CaretRefusal = "no_address" | "multi_run" | "run_text_differs" | "no_inventory";

const CARET_REFUSAL_TEXT: Record<CaretRefusal, string> = {
  no_address: "이 줄에는 문단 주소가 없습니다",
  multi_run:
    "이 문단은 글 덩어리가 여럿입니다. 어느 덩어리를 고칠지 런타임이 고르지 않으므로 여기에는 커서를 놓지 않습니다",
  run_text_differs:
    "이 줄과 문단의 글 덩어리가 서로 다릅니다. 한 문단이 여러 줄로 접힌 자리라, 줄만 골라 고칠 방법이 없습니다",
  no_inventory: "런타임이 이 문단의 글 덩어리 목록을 돌려주지 못했습니다",
};

export function caretRefusalText(reason: CaretRefusal): string {
  return CARET_REFUSAL_TEXT[reason];
}

/**
 * The mapping's own normalizer, as far as a shell can honestly go.
 *
 * `pipeline/scripts/check_residue.normalize_text` is Python and lives on the
 * other side of the wire; it cannot be imported here. So this comparison is
 * deliberately the WEAKEST one that is still safe — collapse whitespace runs,
 * trim — which is a strict subset of what the gate does. A pair this rejects
 * the gate would reject too. A pair this accepts the gate might have accepted
 * for reasons of its own, and the consequence of that direction is only that a
 * caret is refused where it could have been placed, which is the direction
 * this application errs in on purpose.
 */
function looselySameText(a: string, b: string): boolean {
  return a.replace(/\s+/g, " ").trim() === b.replace(/\s+/g, " ").trim();
}

/**
 * Where in a line a click landed, from the runtime's own character boxes.
 *
 * `null` where the line carried none — the caller SNAPS to the start and says
 * so. Nothing is interpolated from the line's width and its character count: a
 * proportional face makes that wrong by a character or more mid-line, and
 * being wrong about where the cursor is is the failure this feature exists to
 * avoid. `fraction` is a fraction of the PAGE width, the same units `charX`
 * and `rect` are in, so the caller never converts anything.
 */
export function caretOffsetAt(span: GeometrySpan, fraction: number): number | null {
  const xs = span.charX;
  if (!xs || xs.length < 2) return null;
  // The nearest boundary, so clicking the right half of a character puts the
  // caret after it — what every text editor does.
  let best = 0;
  let bestGap = Infinity;
  for (let i = 0; i < xs.length; i += 1) {
    const gap = Math.abs(xs[i] - fraction);
    if (gap < bestGap) {
      bestGap = gap;
      best = i;
    }
  }
  return Math.min(best, span.text.length);
}

/**
 * Put a caret in a paragraph line, or refuse and say which refusal it is.
 *
 * THE CHECK THIS SHELL MUST MAKE ITSELF (§12.7). There is no
 * `replace_paragraph_text` operation and none was invented: what writes a
 * paragraph line is `set_run`, which addresses `(atPara, run)` and preserves
 * the run's charPrIDRef. A line is not a run. The two coincide only where the
 * paragraph holds exactly one run whose text IS the line — and the RUNTIME is
 * asked whether that holds, through `document/readRegion`, rather than this
 * shell inferring it from the fact that the text matched.
 *
 * Measured on the corpus before it was written: of 365 uniquely-mapped
 * paragraph lines across 51 real pages, 314 hold exactly one run and 51 do
 * not. The 51 are refused here, by name, with no caret placed.
 */
export async function beginParagraphEdit(
  span: GeometrySpan,
  fraction?: number,
): Promise<CaretRefusal | null> {
  const sessionId = getState().activeSessionId;
  const address = span.address;
  if (!sessionId || !address || address.atPara == null) return "no_address";
  const atPara = address.atPara;

  let runs: TextRun[] = [];
  try {
    const answer = await rt.readRegion(sessionId, [{ atPara }]);
    const region = answer.regions.find((r) => r.at_para === atPara);
    runs = region?.runs ?? [];
    if (region) {
      // Kept beside the cell texts the tree loaded, so the toolbar over this
      // caret can name the run's face (§14) without a second call.
      const existing = getState().texts[sessionId] ?? [];
      setState({
        texts: {
          ...getState().texts,
          [sessionId]: [...existing.filter((r) => r.at_para !== atPara), region],
        },
      });
    }
  } catch {
    return "no_inventory";
  }
  if (runs.length === 0) return "no_inventory";
  if (runs.length > 1) return "multi_run";
  const run = runs[0];
  if (!looselySameText(run.text ?? "", span.text)) return "run_text_differs";

  const queued = queuedRunOpAt(getState(), atPara, run.index);
  setState({
    selection: { kind: "paragraph", atPara },
    inlineEdit: {
      kind: "run",
      atPara,
      run: run.index,
      before: queued?.before ?? run.text ?? "",
      opId: queued?.opId ?? null,
      caret: fraction === undefined ? null : caretOffsetAt(span, fraction),
      spanIndex: span.index,
      sizePt: span.sizePt,
    },
  });
  return null;
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
  // ONE QUEUE, ONE PLAN PATH, TWO OP KINDS. A value typed into a seat and a
  // sentence typed into a paragraph differ by exactly the operation kind the
  // runtime's own registry names for each. Everything past this line —
  // `setQueue`, `plan/propose`, `plan/validate`, the review queue, approval,
  // apply, the receipt — is the same code for both, which is what makes the
  // caret a new surface rather than a second mutation route.
  const next: QueuedOp =
    edit.kind === "cell"
      ? {
          opId: edit.opId ?? `op-${cellSlug(edit.table, edit.row, edit.col)}`,
          kind: "fill_cell",
          table: edit.table,
          row: edit.row,
          col: edit.col,
          text: trimmed,
          charPr: edit.charPr,
          before: edit.before,
          origin: "user",
        }
      : {
          opId: edit.opId ?? `op-p${edit.atPara}r${edit.run}`,
          kind: "set_run",
          atPara: edit.atPara,
          run: edit.run,
          text: trimmed,
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
    // T30 is a fill seat's preflight, and `set_run` preserves the run's own
    // charPrIDRef rather than declaring one — so there is nothing here for a
    // run op to declare, and it is left exactly as it is.
    if (op.opId !== opId || op.kind !== "fill_cell") return op;
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

// --- undo, tier one: the queue (E1.4) ----------------------------------------
//
// AN EDIT IN THE QUEUE IS NOT IN ANY DOCUMENT. Nothing has been approved and
// nothing has been applied, so taking the op out of the queue IS the undo:
// exact, instant, and involving no runtime mutation at all. The only thing this
// tier owes the user is honest labelling — it is 대기열에서 제거, never
// 문서 되돌리기, because telling someone their document changed back when the
// document never changed is the exact species of lie this application exists
// not to tell.

/** Take an op out of the queue and keep it, so 다시 하기 can put it back. */
export async function undoQueuedOp(opId: string): Promise<boolean> {
  const op = getState().draft.ops.find((x) => x.opId === opId);
  if (!op) return false;
  const rewritten = didRewriteAgent(opId);
  setState({ redoStack: [...getState().redoStack, op] });
  await setQueue(
    getState().draft.ops.filter((x) => x.opId !== opId),
    { rewritten },
  );
  showToast("대기열에서 뺐습니다. 문서는 처음부터 바뀐 적이 없습니다.", 2000);
  return true;
}

/**
 * Put the last removed op back — the same target, the same value.
 *
 * Exactness is the whole claim of this tier, so the op object itself is
 * re-enqueued rather than rebuilt from fields: an op reconstructed from a
 * remembered address and a remembered string would be a new edit that happened
 * to look the same, and `before` would drift the first time it was wrong.
 */
export async function redoQueuedOp(): Promise<boolean> {
  const stack = getState().redoStack;
  const op = stack[stack.length - 1];
  if (!op) return false;
  setState({ redoStack: stack.slice(0, -1) });
  const ops = getState().draft.ops.filter((x) => x.opId !== op.opId);
  await setQueue([...ops, op]);
  return true;
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
  options: { rewritten?: boolean; baseRunId?: string | null; reverses?: string | null } = {},
): Promise<void> {
  const state = getState();
  const sessionId = state.activeSessionId;
  const rewritten = state.draft.rewrittenFromAgent || options.rewritten === true;
  // THE CHAIN. A queue built while a candidate exists chains onto it, so a
  // second edit lands on top of the first rather than beside it — before
  // lineage existed the second candidate silently did not contain the first
  // edit. The head is a shell decision (the runtime keeps no head, §15.7) and
  // it is shown in 기록; an explicit option wins over it, which is how a
  // 되돌리기 제안 names the exact candidate it is chaining onto.
  const baseRunId =
    options.baseRunId !== undefined
      ? options.baseRunId
      : (state.draft.baseRunId ?? headCandidate(state)?.runId ?? null);
  const reverses = options.reverses !== undefined ? options.reverses : state.draft.reverses;

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
      baseRunId,
      reverses,
    },
  });

  try {
    const plan = await rt.proposePlan(
      sessionId,
      // Each kind carries exactly the fields its own op declares and no
      // others: `plan/propose` refuses an op that carries a field its kind
      // does not define (`unknown_field`, rt_plan.py:196), which is the check
      // that would catch a shell sending a cell's triple with a run's address.
      ops.map((op) =>
        op.kind === "fill_cell"
          ? {
              opId: op.opId,
              kind: op.kind,
              table: op.table,
              row: op.row,
              col: op.col,
              text: op.text,
              ...(op.charPr ? { charPr: op.charPr } : {}),
              ...(op.overwrite ? { overwrite: true } : {}),
            }
          : {
              opId: op.opId,
              kind: op.kind,
              atPara: op.atPara,
              run: op.run,
              text: op.text,
            },
      ),
      { baseRunId, reverses },
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
        baseRunId,
        reverses,
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
        baseRunId,
        reverses,
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

// --- undo, tier two: an applied candidate (E1.4) -----------------------------
//
// AN APPLIED CANDIDATE IS IMMUTABLE AND RECEIPTED, so undoing one cannot mean
// changing it and must not mean deleting it. It means proposing the INVERSE as
// a new plan, chained onto the current head, which then travels the same review
// → approve → apply path as anything else and produces one more candidate with
// one more receipt. History only ever grows.
//
// Three rules this function keeps, and each one is a way a shortcut would lie:
//
// 1. **The previous value is READ, never remembered.** It comes from
//    `document/readRegion` against the candidate the edit was made ON — the
//    parent named in the receipt, or the source at the root of the chain. A
//    `before` string the queue happened to still hold would be a client's
//    memory of the document, and the whole point is that it is the document.
// 2. **What cannot be inverted is refused by name.** `fill_cell` and `set_run`
//    are invertible because their previous value is readable. Nothing else is,
//    and a plan carrying one is not offered a 되돌리기 제안 at all.
// 3. **It is a PROPOSAL.** It lands in the queue, is labelled 되돌리기 제안,
//    and a person approves it exactly as they approved the edit. Nothing here
//    writes.

/** Op kinds this shell can build an inverse for, and why only these. */
const INVERTIBLE_KINDS = new Set(["fill_cell", "set_run"]);

/** The address an op targets, in the shape `readRegion` takes. */
function opAddress(op: PlanOp): Record<string, number> | null {
  const p = op.params;
  if (op.kind === "fill_cell") {
    return {
      table: Number(p.table ?? 0),
      row: Number(p.row),
      col: Number(p.col),
    };
  }
  if (op.kind === "set_run") return { atPara: Number(p.atPara) };
  return null;
}

/**
 * Propose the inverse of an applied candidate. Reads the chain; writes nothing.
 *
 * Returns the number of ops queued, or throws nothing — the refusal lands in
 * `undoError` where the panel can print it, because "this cannot be undone" is
 * an answer a person needs to see rather than a silent dead button.
 */
export async function proposeUndoOf(runId: string): Promise<number> {
  const state = getState();
  const sessionId = state.activeSessionId;
  if (!sessionId) return 0;
  setState({ undoPhase: "starting", undoError: null });
  try {
    const receipt = state.receipts[runId] ?? (await rt.readReceipt(sessionId, runId));
    const plan = await rt.getPlan(receipt.planId);

    const uninvertible = plan.ops.filter((op) => !INVERTIBLE_KINDS.has(op.kind));
    if (uninvertible.length > 0) {
      setState({
        undoPhase: "failed",
        undoError: {
          code: "not_invertible",
          message:
            `이 후보본에는 되돌릴 방법이 없는 작업이 있습니다: ` +
            `${uninvertible.map((op) => op.kind).join(", ")}. ` +
            `되돌리기는 이전 값을 읽어올 수 있는 작업(fill_cell, set_run)에만 만들 수 있습니다.`,
          data: { kinds: uninvertible.map((op) => op.kind) },
        },
      });
      return 0;
    }

    // The document this candidate was made FROM. `base` is null at the root of
    // the chain, and then the previous value is the session source's.
    const parentRunId = receipt.base?.runId ?? null;
    const addresses = plan.ops
      .map((op) => ({ op, address: opAddress(op) }))
      .filter((row): row is { op: PlanOp; address: Record<string, number> } =>
        row.address !== null,
      );
    if (addresses.length === 0) {
      setState({
        undoPhase: "failed",
        undoError: {
          code: "not_invertible",
          message: "이 계획의 작업들이 주소를 갖고 있지 않아 이전 값을 읽을 수 없습니다.",
        },
      });
      return 0;
    }

    const answer = await rt.readRegion(
      sessionId,
      addresses.map((row) => row.address),
      parentRunId,
    );

    const ops: QueuedOp[] = [];
    for (const { op, address } of addresses) {
      const previous = regionTextAt(answer.regions, address);
      if (previous === null) {
        // The runtime did not return this address in the parent. That is not
        // an empty string and it must not be filled in as one: the inverse
        // would then WRITE a blank over something unknown.
        setState({
          undoPhase: "failed",
          undoError: {
            code: "previous_value_unreadable",
            message:
              "되돌릴 이전 값을 런타임이 돌려주지 못한 자리가 있습니다. " +
              "빈 값으로 짐작해서 덮어쓰지 않습니다.",
            data: { address, subject: answer.subject },
          },
        });
        return 0;
      }
      ops.push(
        op.kind === "fill_cell"
          ? {
              opId: `undo-${runId.slice(0, 8)}-${op.opId}`,
              kind: "fill_cell",
              table: Number(op.params.table ?? 0),
              row: Number(op.params.row),
              col: Number(op.params.col),
              text: previous,
              // The seat is not empty any more — the edit filled it — so the
              // inverse has to say so. Without this preedit refuses to write
              // into an occupied cell, which is the correct default and the
              // wrong one here.
              overwrite: true,
              before: String(op.params.text ?? ""),
              origin: "user",
            }
          : {
              opId: `undo-${runId.slice(0, 8)}-${op.opId}`,
              kind: "set_run",
              atPara: Number(op.params.atPara),
              run: Number(op.params.run),
              text: previous,
              before: String(op.params.text ?? ""),
              origin: "user",
            },
      );
    }

    // Chained onto the HEAD, not onto the candidate being reversed: undoing an
    // older edit must not throw away the newer ones on top of it.
    await setQueue(ops, {
      baseRunId: headCandidate(getState())?.runId ?? null,
      reverses: runId,
    });
    setState({ undoPhase: "ready", undoError: null, inverseProof: null });
    showToast("되돌리기를 제안했습니다. 승인해야 후보본이 하나 더 생깁니다.", 2600);
    return ops.length;
  } catch (e) {
    setState({ undoPhase: "failed", undoError: rt.asRuntimeError(e) });
    return 0;
  }
}

/** The text the runtime returned for one address, or null if it returned none. */
function regionTextAt(
  regions: RegionText[],
  address: Record<string, number>,
): string | null {
  const match =
    address.atPara !== undefined
      ? regions.find((r) => r.at_para === address.atPara)
      : regions.find(
          (r) =>
            (r.table ?? 0) === address.table &&
            r.addr?.row === address.row &&
            r.addr?.col === address.col,
        );
  return match?.text ?? null;
}

/**
 * Ask the runtime whether the reversal that was just applied IS the inverse.
 *
 * Not computed here on purpose. `candidate/compare` re-reads both documents
 * from bytes their receipts re-verified, at the addresses the reversal
 * touched, and reports equality; a shell comparing two strings it had already
 * fetched would be comparing its own memory and calling it proof.
 */
export async function verifyReversal(
  runId: string,
  reversedRunId: string,
): Promise<boolean> {
  const sessionId = getState().activeSessionId;
  if (!sessionId) return false;
  try {
    const receipt =
      getState().receipts[reversedRunId] ??
      (await rt.readReceipt(sessionId, reversedRunId));
    const reversedPlan = await rt.getPlan(receipt.planId);
    const regions = reversedPlan.ops
      .map(opAddress)
      .filter((a): a is Record<string, number> => a !== null);
    // Compare against the document the reversed edit was made FROM: that is
    // the state the undo claims to have restored.
    const against = receipt.base?.runId
      ? ({ runId: receipt.base.runId } as const)
      : ({ source: true } as const);
    const compare = await rt.compareCandidate(sessionId, runId, against, regions);
    setState({ inverseProof: { runId, reversedRunId, compare } });
    return compare.regionsEqual === true;
  } catch (e) {
    setState({ undoError: rt.asRuntimeError(e) });
    return false;
  }
}

/** Show an older candidate in the 기록 panel. Read-only; never moves the head. */
export function selectHistory(runId: string | null): void {
  setState({ historySelected: runId });
  if (runId && !getState().receipts[runId]) void loadReceipt(runId);
}

/**
 * Make a candidate the one the shell stands on.
 *
 * Explicit, because the runtime has no head and a silent one would be the
 * shell deciding what the file IS without saying so. Moving it re-bases a
 * pending queue, which is why it re-proposes rather than leaving a plan bound
 * to bytes the user has just navigated away from.
 */
export async function setHead(runId: string | null): Promise<void> {
  setState({ head: runId, applied: null });
  if (runId) {
    await loadReceipt(runId);
    const receipt = getState().receipts[runId];
    if (receipt) {
      setState({ candidateVerdict: { runId, report: receipt.checks } });
    }
  }
  if (getState().draft.ops.length > 0) {
    await setQueue(getState().draft.ops, { baseRunId: runId });
  }
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
  const reversed = state.draft.reverses;
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
      // The redo stack belonged to that queue. Offering to re-enqueue an op
      // that is now inside a published candidate would put the same edit in
      // twice, so it goes with the queue it came from.
      redoStack: [],
      approvalPhase: "idle",
      approval: null,
      candidateVerdict: { runId: applied.runId, report: applied.checks },
      // The new candidate is what the document now is, so the next edit chains
      // onto it. Explicit rather than implicit; the 기록 panel shows it.
      head: applied.runId,
      historySelected: applied.runId,
      inverseProof: null,
    });
    await loadCandidates(sessionId);
    // A reversal is not finished when it is applied — it is finished when the
    // runtime says the value came back. Asked here, straight after, so the
    // claim and its proof arrive together rather than the claim standing alone.
    if (reversed) await verifyReversal(applied.runId, reversed);
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
 * An `AppliedCandidate`-shaped record for a run this session did not apply.
 *
 * Built from the RECEIPT, which is the verifying read: `receipt/read` re-hashes
 * the artifact against its binding before it returns, so exporting an older
 * candidate from the 기록 panel goes through the same check as exporting the
 * one just made. Null when the receipt refuses — and a refusal to export is
 * the right outcome for bytes that drifted.
 */
async function candidateRefFor(
  sessionId: string,
  runId: string | null,
): Promise<AppliedCandidate | null> {
  if (!runId) return null;
  const held = getState().receipts[runId];
  const receipt = held ?? (await rt.readReceipt(sessionId, runId).catch(() => null));
  if (!receipt) return null;
  if (!held) setState({ receipts: { ...getState().receipts, [runId]: receipt } });
  return {
    runId,
    sessionId,
    planId: receipt.planId,
    candidate: receipt.candidate,
    base: receipt.base,
    reverses: receipt.reverses,
    checks: receipt.checks,
    receipt: `${runId}/receipt.json`,
    canonical: true,
  };
}

/**
 * Save the candidate and its receipt where the user chooses.
 *
 * `artifact/exportTo` is GAP (§11.5), so the copy is the shell's own work,
 * done in Rust against a path a native dialog returned. Two files leave
 * together and never separately: an artifact without its receipt is a document
 * with no account of where it came from, which is the thing this program
 * exists not to produce.
 */
export async function exportApplied(
  destination?: string,
  runId?: string,
): Promise<boolean> {
  const state = getState();
  const sessionId = state.activeSessionId;
  // WHICH CANDIDATE LEAVES IS ALWAYS NAMED. `runId` is the 기록 panel's
  // explicit choice; otherwise it is the one this session just applied, and
  // otherwise the head. History does not silently decide what gets written to
  // the operator's disk — the receipt that travels says which run it is.
  const chosen =
    runId ??
    state.applied?.runId ??
    headCandidate(state)?.runId ??
    null;
  if (!sessionId || !chosen) return false;
  const applied =
    state.applied && state.applied.runId === chosen
      ? state.applied
      : await candidateRefFor(sessionId, chosen);
  if (!applied) return false;

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
export async function renderCurrentPage(
  page?: number,
  runId?: string | null,
): Promise<void> {
  const state = getState();
  const sessionId = state.activeSessionId;
  if (!sessionId) return;
  const wanted = (page ?? state.page) - 1;
  setState({ renderPhase: "starting", renderError: null });
  try {
    const render = await rt.renderPage(
      sessionId,
      Math.max(0, wanted),
      RENDER_DPI,
      runId ?? null,
    );
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

/**
 * Could this address hold a caret? A SHAPE check, and deliberately only that.
 *
 * True for a paragraph address carrying an `atPara`, which is the only thing
 * `set_run` can address. It is NOT a promise that the caret will be placed:
 * whether the paragraph holds exactly one run is a question only
 * `document/readRegion` can answer, and `beginParagraphEdit` asks it at click
 * time rather than this function guessing. The distinction matters because 51
 * of the corpus's 365 mapped paragraph lines look exactly like the 314 that
 * work, right up until the runtime answers.
 */
export function addressIsCaretTarget(address: GeometryAddress | null | undefined): boolean {
  return !!address && address.kind === "anchor" && address.atPara != null;
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
        derivation: seat.derivation,
        label: `${addressLabel(address)} — 값을 넣는 자리가 아닙니다`,
      },
    });
    return;
  }
  setState({
    overlayPick: {
      kind: "seat",
      targetId: id,
      address,
      // Carried so the status bar can say HOW this rectangle was found. §12.4's
      // three derivations are not equally trustworthy and this is the one class
      // a person types into; leaving that in a tooltip means it is never read.
      derivation: seat.derivation,
      label: `${addressLabel(address)} · ${derivationLabel(seat.derivation)}`,
    },
  });
  openAddress(address);
}

/** How the runtime found this rectangle, in four words. Status-bar length. */
export function derivationLabel(derivation: string): string {
  switch (derivation) {
    case "cell_borders":
      return "그려진 선으로 잡음";
    case "matched_text":
      return "칸의 글자로 잡음";
    case "interpolated":
      return "이름표에서 미루어 잡음";
    default:
      return derivation;
  }
}

/**
 * A click on a mapped line of text. Five honest outcomes, and never a sixth.
 *
 * Ambiguous asks. A mapped CELL opens the seat editor, as it always did. A
 * mapped PARAGRAPH is the new one: it asks the runtime for the line's run
 * inventory and either puts a caret in the line or names the reason it cannot
 * (§12.7). Anything else says it is not a place to type.
 *
 * `fraction` is where along the page width the pointer landed. It is passed
 * straight to `charX` — no scaling, no assumption about zoom — and where the
 * line carries no character boxes, `caret` comes back null and the status bar
 * says the click snapped to the front of the line.
 */
export async function clickOverlaySpan(
  span: GeometrySpan,
  fraction?: number,
): Promise<void> {
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

  // A PARAGRAPH LINE. The caret path, and the runtime decides whether there is
  // one — this shell asks and prints the answer, whichever way it comes back.
  if (addressIsCaretTarget(address)) {
    const refusal = await beginParagraphEdit(span, fraction);
    if (refusal) {
      setState({
        overlayPick: {
          kind: "no_caret",
          targetId: id,
          address,
          refusal,
          label: `${addressLabel(address)} — ${caretRefusalText(refusal)}`,
        },
      });
      setSelection({ kind: "paragraph", atPara: address.atPara! });
      return;
    }
    const edit = getState().inlineEdit;
    const snapped = edit?.kind === "run" && edit.caret === null;
    setState({
      overlayPick: {
        kind: "caret",
        targetId: id,
        address,
        // The offset is stated, and so is its absence. "커서를 줄 앞에 놓음"
        // is not a nicety: it is the difference between a measured position
        // and a fallback, and a user who is not told cannot know which they
        // are looking at.
        caret: edit?.kind === "run" ? edit.caret : null,
        label:
          `${addressLabel(address)}` +
          (snapped
            ? " · 글자별 위치가 없어 줄 앞에 커서를 놓음"
            : ` · ${(edit?.kind === "run" ? edit.caret : 0) ?? 0}번째 글자 앞`),
      },
    });
    return;
  }

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
export async function chooseCandidate(address: GeometryAddress): Promise<void> {
  const pick = getState().overlayPick;

  // A PARAGRAPH CANDIDATE IS A CARET, NOT A DEAD END. §12.4: a form label is
  // routinely registered twice in the target set, once as an `anchor_record`
  // and once as the table cell it sits in — so an ambiguous span's candidate
  // list very often holds exactly one anchor and one cell. Before the caret
  // existed, choosing the anchor half correctly said 값을 넣는 자리가
  // 아닙니다; it is now the wrong sentence, because a paragraph IS somewhere a
  // person types.
  //
  // The caret goes to the START of the line here, and says so, because a
  // choice made from a list carried no pointer position to resolve an offset
  // from. That is the same honest `caret: null` a line with no character boxes
  // gets — a fallback, labelled as one.
  if (addressIsCaretTarget(address)) {
    const span = (getState().geometry?.spans ?? []).find(
      (s) => `span-${s.index}` === pick?.targetId,
    );
    const refusal = span
      ? await beginParagraphEdit({ ...span, address, confidence: "unique" })
      : "no_address";
    setState({
      overlayPick: refusal
        ? {
            kind: "no_caret",
            targetId: pick?.targetId ?? "candidate",
            address,
            refusal,
            label: `${addressLabel(address)} — ${caretRefusalText(refusal)}`,
          }
        : {
            kind: "caret",
            targetId: pick?.targetId ?? "candidate",
            address,
            caret: null,
            label: `${addressLabel(address)} — 사용자가 고름 · 줄 앞에 커서를 놓음`,
          },
    });
    return;
  }

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
export async function preparePages(runId?: string | null): Promise<void> {
  const sessionId = getState().activeSessionId;
  if (!sessionId) return;
  setState({ preparePhase: "starting", prepareError: null, prepareNote: null });
  try {
    const result = await rt.renderPrepare(sessionId, runId ?? null);
    setState({
      preparePhase: "ready",
      prepareNote: result.prepared
        ? `${runId ? "후보본" : "원본"} PDF를 만들었습니다 · ${result.pdf?.sha256.slice(0, 12)}`
        : (result.reason ?? "이미 준비되어 있습니다"),
    });
    await renderCurrentPage(1, runId ?? null);
  } catch (e) {
    setState({ preparePhase: "failed", prepareError: rt.asRuntimeError(e) });
  }
}

/**
 * E1.2, honestly: is the page on screen the document as it now stands?
 *
 * After an apply the raster is still the SOURCE's — a candidate has no raster
 * until somebody converts it, and on a machine without a reachable Hancom
 * nobody can. So the answer is a STATE, not a redraw: the page says
 * 후보본과 다름, marks the regions the runtime says changed, and offers
 * 다시 그리기, which asks the runtime and shows whatever it answers.
 *
 * What this deliberately does NOT do is draw the edited text onto the raster.
 * That would be this shell inventing a layout and presenting it as the
 * renderer's — the same rule the overlay keeps (§12.2), and the reason a
 * refusal is on screen instead of a picture.
 */
export interface LayoutEcho {
  /** The candidate the page ought to be showing. */
  runId: string;
  /** What the raster actually came from. */
  rendered: { kind: string; runId?: string; sha256?: string };
  /** Addresses the candidate's plan touched, as overlay-comparable keys. */
  changed: string[];
}

/** One shared empty value, for the same `Object.is` reason `NO_CANDIDATES` is. */
const NO_ECHO: LayoutEcho | null = null;
let echoCache: LayoutEcho | null = NO_ECHO;

/**
 * The echo state, or null when the page IS the document on screen.
 *
 * Returns a stable reference while nothing changes: this is read through
 * `useWorkspace`, which compares snapshots with `Object.is`, and a fresh
 * object every call is the render loop that took the whole root down once
 * already (see `draftStaleness`).
 */
export function layoutEcho(s: ReturnType<typeof getState>): LayoutEcho | null {
  const head = headCandidate(s);
  if (!head?.runId || !s.render?.available) return (echoCache = null);
  const rendered = s.render.source ?? { kind: "unknown" };
  // The raster already IS this candidate's. Nothing to say.
  if (rendered.runId === head.runId) return (echoCache = null);
  const changed = s.changedByRun[head.runId] ?? [];
  const cached = echoCache;
  if (
    cached &&
    cached.runId === head.runId &&
    cached.rendered.kind === rendered.kind &&
    cached.rendered.runId === rendered.runId &&
    cached.changed === changed
  ) {
    return cached;
  }
  echoCache = { runId: head.runId, rendered, changed };
  return echoCache;
}

/**
 * Read the plans behind a candidate's chain and record which addresses changed.
 *
 * The keys come from the RECEIPTS' own plans — the ops that actually ran —
 * walked back up the `base` links, so a chain of three edits marks all three.
 * Nothing here is inferred from the page.
 *
 * The result goes into the STORE and not into a module memo, and that is a
 * defect this was written around rather than a preference: the echo renders
 * through `useWorkspace`, the last store write in this walk is the receipt
 * read, and a cache filled after it would never reach a render. An ancestor
 * whose plan the runtime cannot hand back stops the walk, and the page then
 * says the list is unread rather than marking a shorter one and looking
 * complete.
 */
export async function loadChangedAddresses(runId: string): Promise<number> {
  const sessionId = getState().activeSessionId;
  if (!sessionId) return 0;
  if (getState().changedByRun[runId]) return getState().changedByRun[runId].length;
  const keys: string[] = [];
  const seen = new Set<string>();
  let cursor: string | null = runId;
  while (cursor && !seen.has(cursor)) {
    seen.add(cursor);
    const current: string = cursor;
    const receipt = getState().receipts[current] ?? (await loadReceiptQuiet(current));
    if (!receipt) break;
    let plan: OperationPlan;
    try {
      plan = await rt.getPlan(receipt.planId);
    } catch {
      break;
    }
    for (const op of plan.ops) {
      const key =
        op.kind === "set_run"
          ? `p:${Number(op.params.atPara)}`
          : `c:${Number(op.params.table ?? 0)}:${Number(op.params.row)}:${Number(op.params.col)}`;
      if (!keys.includes(key)) keys.push(key);
    }
    cursor = receipt.base?.runId ?? null;
  }
  setState({ changedByRun: { ...getState().changedByRun, [runId]: keys } });
  return keys.length;
}

async function loadReceiptQuiet(runId: string) {
  const ok = await loadReceipt(runId);
  return ok ? getState().receipts[runId] : null;
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
    // The runtime's own copy of the plan is authoritative about its lineage
    // too: whether the agent chained onto a candidate is the agent's decision
    // to have made, and the queue reflects what the plan actually says rather
    // than re-deriving it from this shell's head.
    baseRunId: authoritative.base?.runId ?? null,
    reverses: authoritative.reverses?.runId ?? null,
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

/**
 * Which modules the RUNTIME will let `module/check` run, in its own words.
 *
 * Enablement is an operator act recorded in `enabled.yaml` and no wire call can
 * change it (§13.1), so this is a read of a fact rather than a negotiation. It
 * comes from `capabilities.modules`, which the shell already holds — no second
 * call — and it is the authority for the 실행 button, because it is the same
 * reader `module/check` itself consults. `taskPacks` reads the same file
 * through a different child process, and `packEnablementDisagrees` below is
 * what makes a split between the two visible instead of silently resolved.
 */
export function runtimeEnabledModules(): string[] | null {
  const modules = getState().capabilities?.modules;
  if (!modules || !Array.isArray(modules.enabled)) return null;
  return modules.enabled;
}

/** Packs where the registry child and the runtime disagree about enablement. */
export function packEnablementDisagrees(): string[] {
  const runtimeEnabled = runtimeEnabledModules();
  if (runtimeEnabled === null) return [];
  const packs = getState().taskPacks?.packs ?? [];
  return packs
    .filter((pack) => pack.enabled !== runtimeEnabled.includes(pack.name))
    .map((pack) => pack.name);
}

/**
 * 실행 — a distribution module's checkers, against the open session (§13).
 *
 * The one place in this shell that runs anything a module ships. Three things
 * it deliberately does NOT do:
 *
 * - **It does not decide.** No candidate, no plan, no approval; the report is
 *   a read, and the review queue is untouched by it. A checker's verdict is an
 *   input to a human's decision, never a substitute for one.
 * - **It does not translate a verdict.** Every row, reason and finding on
 *   screen is the runtime's own; where a checker was skipped, the reason
 *   printed is `rt_module`'s, not a friendlier one this shell preferred.
 * - **It does not retry.** A `capability_unavailable` because nobody enabled
 *   the module is an answer, not a transient fault, and the panel says which.
 */
export async function runModuleCheck(module: string): Promise<void> {
  const sessionId = getState().activeSessionId;
  if (!sessionId) {
    showToast("문서를 먼저 열어야 검사를 돌립니다", 1600);
    return;
  }
  setState({ packRun: { module, sessionId, phase: "running", report: null, error: null } });
  try {
    const report = await rt.moduleCheck(sessionId, module);
    setState({ packRun: { module, sessionId, phase: "done", report, error: null } });
  } catch (e) {
    setState({
      packRun: { module, sessionId, phase: "failed", report: null, error: rt.asRuntimeError(e) },
    });
  }
}

/**
 * Open a pack, and drop any report that belonged to the previous one.
 *
 * A verdict left under a different pack's heading is the worst kind of stale:
 * it reads as this pack's answer and it is another pack's.
 */
export function openPack(module: string | null): void {
  const current = getState().packRun;
  // Closing the panel (`null`) KEEPS the report: reopening the same pack should
  // show what it found rather than making the user run it again. Only moving to
  // a different pack drops it.
  const keep = module === null || current?.module === module;
  setState({ packOpen: module, packRun: keep ? current : null });
}

/**
 * Go to the cell a module finding names, in the tree view.
 *
 * `locateSelection` rather than `setSelection`: the finding was clicked in the
 * left rail, so the centre SHOULD scroll itself to the address — the rule that
 * keeps the centre still is about clicks made inside the centre.
 */
export function locateFindingAddress(address: {
  table?: number;
  row?: number;
  col?: number;
  atPara?: number;
}): boolean {
  if (address.table != null && address.row != null && address.col != null) {
    setView("document");
    setCenterMode("text");
    locateSelection({ kind: "cell", table: address.table, row: address.row, col: address.col });
    return true;
  }
  if (address.atPara != null) {
    setView("document");
    setCenterMode("text");
    locateSelection({ kind: "paragraph", atPara: address.atPara });
    return true;
  }
  return false;
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

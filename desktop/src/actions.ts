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
  forgetDocumentEvents,
  startDocumentEvents,
  stopDocumentEvents,
} from "./documentEvents";
import {
  agentPlanCellAddresses,
  projectAgentPlan,
} from "./agent/planProjection";
import {
  DEFAULT_PROVIDER,
  EMPTY_DRAFT,
  activeHeadTexts,
  activeStoreKey,
  canRequestApproval,
  composerBlocker,
  draftStaleness,
  draftValidationPending,
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
  queuedCellOpAt,
  upsertQueuedOp,
  queuedOpAt,
  queuedRunOpAt,
  bumpEditIntent,
  bumpPlanGeneration,
  currentPlanGeneration,
  beginDraftSave,
  endDraftSave,
  opSignature,
  type Draft,
  type QueuedOp,
  type WorkspaceState,
} from "./store";
import {
  hasLiveUnappliedPlanInEvents,
  markExternalPlanDismissed,
} from "./workspace/externalPlan";
import {
  activeApprovalBinding,
  approvalBindingIsCurrent,
  approvalBindingStillExists,
} from "./workspace/reviewSummary";
import {
  captureEditLease,
  commitParagraphClick,
  displayedRevision,
  prepareParagraphEdit,
  runTextAfterEdit,
  type CaretRefusal as RevisionCaretRefusal,
  type ParagraphEditEffect,
} from "./revision";
import { WP4 } from "./i18n/v2/wp4";
import { errorCodeMessage, opKindLabel, t, type VocabularyKey } from "./i18n/vocabulary";
import { uiVariant } from "./uiVariant";
import {
  approvalBindsConfirmation,
  autoCharPrFor,
  confirmationBreak,
  foreignOps,
  headTextsKey,
  planOpsPayload,
  queueAdmission,
  requiredAcknowledgements,
  requiredGuardAcks,
  diffDigestBreaks,
  restorableOps,
  returnedFromPrefs,
  savableOps,
  savedDraftEnvelope,
  swapSessionDrafts,
  undoBlockReason,
  withoutSignatures,
  type ConfirmationBinding,
  type ConfirmationBreak,
  type GuardWarningSummary,
} from "./workspace/trust";
import { getReviewGuardSummary } from "./workspace/guardHelper";
import { takeSheetConfirmation } from "./workspace/sheetConfirmation";
import type {
  AppliedCandidate,
  ApprovalRecord,
  EditableRegion,
  Finding,
  GeometryAddress,
  GeometrySeat,
  GeometrySpan,
  InspectResult,
  OperationPlan,
  CorpusFileEntry,
  GuardDiffResult,
  PipelineGatesResult,
  PlanOp,
  PlanValidation,
  ProviderSettings,
  Recent,
  RegionText,
  RuntimeError,
  ScreenId,
  Turn,
  UiLanguage,
  VerificationReport,
} from "./types";

const MAX_RECENTS = 8;
export const ZOOM_MIN = 0.5;
export const ZOOM_MAX = 2.0;
const ZOOM_STEPS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.35, 1.5, 1.75, 2.0];

/**
 * The exact workspace identity allowed to publish a draft.
 *
 * Both local queue rebuilds and agent-plan adoption use this lease. Keeping
 * the ownership rule here prevents the two paths from drifting: a different
 * draft object, document, or candidate head means newer user intent won.
 *
 * `DraftFence` is this identity plus the plan-generation token — never a
 * second copy of the identity rule. Capture a fence from an owner so session,
 * head, and draft object cannot diverge between the two helpers.
 */
interface DraftOwner {
  draft: Draft;
  sessionId: string | null;
  headRunId: string | null;
}

function captureDraftOwner(): DraftOwner {
  const state = getState();
  return {
    draft: state.draft,
    sessionId: state.activeSessionId,
    headRunId: headCandidate(state)?.runId ?? null,
  };
}

function ownsDraft(owner: DraftOwner): boolean {
  const state = getState();
  return (
    state.draft === owner.draft &&
    state.activeSessionId === owner.sessionId &&
    (headCandidate(state)?.runId ?? null) === owner.headRunId
  );
}

interface DraftFence extends DraftOwner {
  generation: number;
}

/** Snapshot identity plus the generation token an async publisher must still hold. */
function captureDraftFence(owner: DraftOwner = captureDraftOwner()): DraftFence {
  return {
    ...owner,
    generation: currentPlanGeneration(),
  };
}

/** True only while the owner still matches and no newer queue rebuild won. */
function ownsDraftFence(fence: DraftFence): boolean {
  return currentPlanGeneration() === fence.generation && ownsDraft(fence);
}

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

export async function loadCandidates(sessionId: string) {
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
let eventSelectionGeneration = 0;

export async function selectSession(sessionId: string) {
  const eventSelection = ++eventSelectionGeneration;
  const previous = getState().activeSessionId;
  if (previous !== sessionId) stopDocumentEvents();
  // ONE QUEUE PER DOCUMENT. The outgoing queue is parked under the session it
  // names and the incoming document gets its own back (or an empty one), so a
  // value typed for one file can never be offered as a change to another.
  const swapped =
    previous !== sessionId && typeof swapSessionDrafts === "function"
      ? swapSessionDrafts(
          getState().parkedDrafts ?? {},
          {
            draft: getState().draft,
            approval: getState().approval,
            approvalPhase: getState().approvalPhase,
            redoStack: getState().redoStack,
          },
          sessionId,
          EMPTY_DRAFT,
        )
      : null;
  if (swapped) {
    cancelDraftValidateTimer();
  }
  setState({
    activeSessionId: sessionId,
    screen: "review" as const,
    mobileReviewPane: "list" as const,
    ...(previous !== sessionId
      ? {
          selection: null,
          selectedChangeId: null,
          expandedChangeId: null,
          returnPopoverOpen: false,
          page: 1,
          findings: [],
          checkedAt: null,
          checkPhase: "idle" as const,
          editIntentGeneration: getState().editIntentGeneration + 1,
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
          ...applyPresentation(sessionId),
          // Applying is globally serial, even if its document is not visible.
          ...(getState().applyPhase === "starting" ? { applyPhase: "starting" as const } : {}),
          receiptOpen: null,
          // A module report names the document it checked. Carrying one across
          // a document switch would put another file's verdict under this
          // file's heading, which is the same class of lie as a stale geometry.
          packRun: null,
          approvalDialogOpen: false,
          guardDiff: null,
          guardDiffPhase: "idle" as const,
          guardDiffError: null,
          events: [],
          eventSubscription: null,
          eventPhase: "starting" as const,
          eventError: null,
          ...(swapped
            ? {
                parkedDrafts: swapped.parked,
                draft: swapped.slot.draft,
                approval: swapped.slot.approval,
                approvalPhase: swapped.slot.approvalPhase,
                approvalError: null,
                reapprovalPrompt: null,
                redoStack: swapped.slot.redoStack,
                showOriginal: false,
                restoredDraft: null,
              }
            : {}),
        }
      : {}),
  });
  const selectedDraft = getState().draft;
  await rt.savePrefs({ lastSessionId: sessionId });
  if (Array.isArray(getState().corpusFiles) && getState().corpusFiles.length === 0) {
    void loadCorpusFiles();
  }
  await loadInspect(sessionId);
  await loadText(sessionId);
  await loadCandidates(sessionId);
  if (
    eventSelection !== eventSelectionGeneration ||
    getState().activeSessionId !== sessionId
  ) {
    return;
  }
  rememberRecent(sessionId);
  await startEvents(sessionId);
  if (typeof loadHeadTexts === "function") {
    const headRun = headCandidate(getState())?.runId ?? null;
    if (headRun && getState().activeSessionId === sessionId) {
      await loadHeadTexts(sessionId, headRun);
    }
  }
  // The canvas can receive edits while the document's open-time reads finish.
  // Restore only the draft that was selected, so a live edit's in-flight plan
  // never gets submitted again by the restore path.
  if (typeof restoreSavedDraft === "function" && getState().activeSessionId === sessionId &&
      (uiVariant() !== "v2" || getState().draft === selectedDraft)) {
    await restoreSavedDraft(sessionId);
  }
}

export async function refreshSessions(): Promise<void> {
  try {
    setState({ sessions: await rt.sessions() });
  } catch (e) {
    setState({ fatal: rt.asRuntimeError(e) });
  }
}

// --- trust: the head on screen, saved entries, returned changes ---------------

/**
 * Read the head 수정본's cell texts, so the page shows what was approved.
 *
 * Cells only, chunked like `loadText`: a cell is addressed by table, row and
 * column, which a candidate keeps, while paragraph indices can move when guide
 * text was deleted. A cell the read did not return falls back to the source's
 * preview, which is the same honest partial `loadText` keeps.
 */
export async function loadHeadTexts(sessionId: string, runId: string): Promise<boolean> {
  const key = headTextsKey(sessionId, runId);
  if (getState().headTexts?.[key]) return true;
  const inspect = getState().inspects[sessionId];
  if (!inspect) return false;
  const wanted = inspect.graph.tables.flatMap((tbl) =>
    tbl.cells.map((c) => ({ table: tbl.index, row: c.addr.row, col: c.addr.col })),
  );
  const collected: RegionText[] = [];
  let failures = 0;
  for (let i = 0; i < wanted.length; i += REGION_CHUNK) {
    try {
      const res = await rt.readRegion(sessionId, wanted.slice(i, i + REGION_CHUNK), runId);
      collected.push(...res.regions);
    } catch {
      failures += 1;
    }
  }
  if (wanted.length > 0 && collected.length === 0 && failures > 0) return false;
  setState({ headTexts: { ...getState().headTexts, [key]: collected } });
  return true;
}

/**
 * Keep the guard warnings a plan was approved with, so the applied state and
 * the export still say what the guard flagged after the queue is gone.
 */
export function rememberApprovedGuard(planId: string, summary: GuardWarningSummary): void {
  setState({ approvedGuard: { ...getState().approvedGuard, [planId]: summary } });
}

/** 원본 보기 ↔ 수정본 보기. Display only; never moves the head or the queue. */
export function toggleShowOriginal(explicit?: boolean): void {
  setState({ showOriginal: explicit ?? !getState().showOriginal });
}

/**
 * Keep the person's typed entries for this document across a reload.
 *
 * Only `origin: "user"` ops: an agent's plan is a runtime record the event log
 * brings back on its own. Written to prefs, which outlive the browser tab and
 * the `rigorloom ui` process.
 */
function persistDraft(sessionId: string, draft: Draft | null): void {
  // Only a queue this session owns is saved under it.
  const ops = draft && !draft.reverses && (draft.sessionId ?? sessionId) === sessionId
    ? savableOps(draft).filter((op) => (op.sessionId ?? sessionId) === sessionId)
    : [];
  const current = getState().savedDrafts ?? {};
  if (ops.length === 0 && !current[sessionId]) return;
  const next = { ...current };
  if (ops.length === 0) {
    delete next[sessionId];
  } else {
    // Versioned envelope: the session and the source digest it was typed on.
    // Restore refuses an entry whose envelope names anything else.
    next[sessionId] = savedDraftEnvelope(
      sessionId,
      sessionSourceDigest(sessionId),
      ops,
      new Date().toISOString().replace(/\.\d+Z$/, "Z"),
    );
  }
  setState({ savedDrafts: next });
  beginDraftSave();
  void rt
    .savePrefs({ drafts: next })
    .catch(() => undefined)
    .finally(() => {
      endDraftSave();
    });
}

/**
 * Bring back the entries a reload would have lost, re-proposed on the head.
 *
 * Also finishes a parked queue whose proposal was still in flight when the
 * person switched away: its result was fenced out, so it is proposed again.
 */
async function restoreSavedDraft(sessionId: string): Promise<void> {
  const state = getState();
  if (state.activeSessionId !== sessionId) return;
  if (state.draft.ops.length > 0) {
    if (
      state.draft.sessionId === sessionId &&
      ((!state.draft.plan && state.draft.phase === "starting") || draftValidationPending(state.draft))
    ) {
      await setQueue(state.draft.ops);
    }
    return;
  }
  const ops = restorableOps(state.savedDrafts?.[sessionId], {
    sessionId,
    sourceSha256: sessionSourceDigest(sessionId),
  });
  if (ops.length === 0) return;
  await setQueue(ops, { baseRunId: headCandidate(getState())?.runId ?? null, reverses: null });
  const after = getState();
  if (after.activeSessionId === sessionId && after.draft.ops === ops) {
    setState({ restoredDraft: { sessionId, count: ops.length } });
  }
}

/** The session source's digest, when the session list knows it. */
function sessionSourceDigest(sessionId: string): string | null {
  const row = (getState().sessions ?? []).find((x) => x.sessionId === sessionId);
  return row?.source?.sha256 ?? null;
}

/** Returned changes outlive a reload: they are kept in prefs, per document. */
function persistReturned(next: Record<string, string[]>): void {
  void rt.savePrefs({ returned: next }).catch(() => undefined);
}

/** Remember changes the person returned, so a re-proposal cannot slip them back in. */
function markReturned(ops: readonly QueuedOp[]): void {
  const state = getState();
  const sessionId = state.draft.sessionId ?? state.activeSessionId;
  if (!sessionId || ops.length === 0) return;
  const current = state.returnedOps?.[sessionId] ?? [];
  const add = ops.map(opSignature).filter((sig) => !current.includes(sig));
  if (add.length === 0) return;
  const next = { ...state.returnedOps, [sessionId]: [...current, ...add] };
  setState({ returnedOps: next });
  if (typeof persistReturned === "function") persistReturned(next);
}

/** The person put these back themselves: they are no longer returned. */
function clearReturned(ops: readonly QueuedOp[]): void {
  const state = getState();
  const sessionId = state.activeSessionId;
  if (!sessionId) return;
  const current = state.returnedOps?.[sessionId];
  if (!current || current.length === 0) return;
  const remaining = withoutSignatures(current, ops);
  if (remaining.length === current.length) return;
  const next = { ...state.returnedOps, [sessionId]: remaining };
  setState({ returnedOps: next });
  if (typeof persistReturned === "function") persistReturned(next);
}

/** 다시 넣기: keep a returned change that came back in a proposal. */
export function readdReturnedOp(opId: string): void {
  const op = getState().draft.ops.find((x) => x.opId === opId);
  if (op) clearReturned([op]);
}

/**
 * 돌려보내기. The proposal leaves the queue and stays returned.
 *
 * The runtime records the decision with the person's words as `reason` — the
 * approver stays the host operator. Every op is remembered as returned, so the
 * next value typed in Fill does not carry the returned ones along into one
 * 변경 2건 approval (GPT review finding 1), and an agent that proposes the same
 * value again gets it shown as returned.
 */
export async function returnDraft(reason: string): Promise<void> {
  const state = getState();
  const sessionId = state.activeSessionId;
  if (!sessionId) return;
  const draft = state.draft;
  if (draft.plan?.planId) markExternalPlanDismissed(sessionId, draft.plan.planId);
  markReturned(draft.ops);
  const approval = state.approval;
  if (approval?.state === "pending" && approval.planId === draft.plan?.planId) {
    await resolveApprovalDecision("rejected", "host-operator", reason.trim() || null);
  } else {
    showToast(t("toast_proposal_returned", getState().language), 2000);
  }
  const after = getState();
  if (after.activeSessionId === sessionId && (after.draft === draft || after.draft.plan?.planId === draft.plan?.planId)) {
    await clearQueue();
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

/** Open form picker: native file dialog in Tauri, or workspace/upload modal in browser mode. */
export async function openViaDialog(): Promise<string | null> {
  if (!rt.isTauri()) {
    setState({ openDialogOpen: true });
    void loadCorpusFiles();
    return null;
  }
  const lang = getState().language;
  const chosen = await openFileDialog({
    multiple: false,
    directory: false,
    title: t("action_open_hwpx_title", lang),
    filters: [{ name: t("action_open_hwpx_filter", lang), extensions: ["hwpx", "hwp"] }],
  });
  if (typeof chosen !== "string") return null;
  return openPath(chosen);
}

export function closeOpenDialog(): void {
  setState({ openDialogOpen: false });
}

export async function loadCorpusFiles(): Promise<CorpusFileEntry[]> {
  setState({ corpusFilesPhase: "starting" });
  try {
    const files = await rt.corpusFiles();
    setState({ corpusFiles: files, corpusFilesPhase: "ready" });
    return files;
  } catch {
    setState({ corpusFilesPhase: "failed" });
    return [];
  }
}

function uint8ArrayToBase64(bytes: Uint8Array): string {
  const chunkSize = 0x8000;
  const parts: string[] = [];
  for (let i = 0; i < bytes.length; i += chunkSize) {
    parts.push(String.fromCharCode(...bytes.subarray(i, i + chunkSize)));
  }
  return btoa(parts.join(""));
}

export async function openUploadedFile(file: File): Promise<string | null> {
  const lang = getState().language;
  if (!SUPPORTED.test(file.name)) {
    showToast(t("toast_hwpx_only", lang), 2400);
    return null;
  }
  try {
    const buf = new Uint8Array(await file.arrayBuffer());
    const contentBase64 = uint8ArrayToBase64(buf);
    const opened = await rt.openUpload(file.name, contentBase64);
    const openedPaths = {
      ...getState().openedPaths,
      [opened.sessionId]: opened.source?.name ?? file.name,
    };
    setState({ openedPaths, openDialogOpen: false });
    await rt.savePrefs({ openedPaths });
    await refreshSessions();
    await selectSession(opened.sessionId);
    return opened.sessionId;
  } catch (e) {
    setState({ inspectPhase: "failed", inspectError: rt.asRuntimeError(e) });
    return null;
  }
}

const SUPPORTED = /\.(hwpx|hwp)$/i;

/** Files dropped on the window. Anything unsupported is refused out loud. */
export async function openDropped(paths: string[]): Promise<void> {
  setState({ dragOver: false });
  const lang = getState().language;
  const usable = paths.filter((p) => SUPPORTED.test(p));
  if (usable.length === 0) {
    showToast(t("toast_hwpx_only", lang), 2000);
    return;
  }
  for (const path of usable.slice(0, 1)) {
    await openPath(path);
  }
  if (usable.length > 1) {
    showToast(t("toast_opened_first_of_many", lang, [usable.length]), 2000);
  }
}

/** Browser HTML5 file drop handler. */
export async function openDroppedFiles(files: File[]): Promise<void> {
  setState({ dragOver: false });
  const lang = getState().language;
  const usable = files.filter((f) => SUPPORTED.test(f.name));
  if (usable.length === 0) {
    showToast(t("toast_hwpx_only", lang), 2000);
    return;
  }
  await openUploadedFile(usable[0]);
  if (usable.length > 1) {
    showToast(t("toast_opened_first_of_many", lang, [usable.length]), 2000);
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
export function beginEdit(
  table: number,
  row: number,
  col: number,
  options?: { multiline?: boolean },
): boolean {
  const state = getState();
  const sessionId = state.activeSessionId;
  if (!sessionId) return false;
  const inspect = state.inspects[sessionId] ?? null;
  const seat = seatAt(inspect, table, row, col);
  if (!seat) {
    showToast(t("toast_not_editable_cell", state.language), 1600);
    return false;
  }
  const queued = queuedOpAt(state, table, row, col);
  const multiline =
    Boolean(options?.multiline) ||
    queued?.lines !== undefined ||
    Boolean(queued?.text.includes("\n"));
  setState({
    selection: { kind: "cell", table, row, col },
    inlineEdit: {
      kind: "cell",
      table,
      row,
      col,
      before: queued?.before ?? seatText(inspect, activeHeadTexts(state) ?? state.texts[sessionId] ?? [], table, row, col),
      charPr: queued?.charPr,
      opId: queued?.opId ?? null,
      multiline,
    },
  });
  return true;
}

/**
 * Explicit escape hatch for static cells not marked as blank seats (`design.md` §2.3):
 * opens an inline editor backed by `replace_at_cell`.
 */
export function beginStaticCellEdit(
  table: number,
  row: number,
  col: number,
  options?: { multiline?: boolean },
): boolean {
  const state = getState();
  const sessionId = state.activeSessionId;
  if (!sessionId) return false;
  const inspect = state.inspects[sessionId] ?? null;
  const seat = seatAt(inspect, table, row, col);
  if (seat && queuedCellOpAt(state, table, row, col)?.kind !== "replace_at_cell") {
    return beginEdit(table, row, col, options);
  }
  const queued = queuedCellOpAt(state, table, row, col);
  const before = queued?.before ?? seatText(inspect, activeHeadTexts(state) ?? state.texts[sessionId] ?? [], table, row, col);
  setState({
    selection: { kind: "cell", table, row, col },
    inlineEdit: {
      kind: "cell",
      table,
      row,
      col,
      before,
      charPr: queued?.charPr,
      opId: queued?.opId ?? null,
      replaceExisting: true,
      multiline: Boolean(options?.multiline) || Boolean(queued?.text.includes("\n")) || before.includes("\n"),
    },
  });
  return true;
}

export function setInlineEditMultiline(multiline: boolean): void {
  const edit = getState().inlineEdit;
  if (!edit || edit.kind !== "cell") return;
  setState({ inlineEdit: { ...edit, multiline } });
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
export type CaretRefusal = RevisionCaretRefusal;

const CARET_REFUSAL_KEYS: Record<CaretRefusal, VocabularyKey> = {
  no_address: "caret_refusal_no_address",
  multi_run: "caret_refusal_multi_run",
  run_text_differs: "caret_refusal_run_text_differs",
  no_inventory: "caret_refusal_no_inventory",
  revision_mismatch: "caret_refusal_revision_mismatch",
  cross_run: "caret_refusal_cross_run",
  utf16_split: "caret_refusal_utf16_split",
};

export function caretRefusalText(
  reason: CaretRefusal,
  lang = getState().language,
): string {
  return t(CARET_REFUSAL_KEYS[reason], lang);
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
 * the run's charPrIDRef. A line is not a run. The click names one run and a
 * UTF-16 range inside it — a wrap is a range of that run; a caret inside a
 * multi-run line names the run that owns that code unit; a span that would
 * join neighbour runs with no unique run is `cross_run` / `multi_run`, not
 * a flattened paragraph.
 */
/**
 * Prepare a paragraph caret against the displayed revision. Does not write
 * selection or overlay — the public click commits the returned effect.
 */
export async function prepareOverlayParagraphEdit(
  span: GeometrySpan,
  fraction: number | undefined,
  intent: number,
): Promise<ParagraphEditEffect | null> {
  const state = getState();
  const address = span.address;
  if (!address || address.atPara == null) return null;
  const lease = captureEditLease(state, address.atPara, intent);
  if (!lease) return null;
  return prepareParagraphEdit({
    lease,
    spanText: span.text,
    spanIndex: span.index,
    sizePt: span.sizePt,
    caret: fraction === undefined ? null : caretOffsetAt(span, fraction),
    address,
    readRegion: rt.readRegion,
  });
}

function applyOverlayParagraphCommit(effect: ParagraphEditEffect): boolean {
  const commit = commitParagraphClick(effect, getState());
  if (commit.kind === "noop") return false;
  if (commit.kind === "refused") {
    setState({
      overlayPick: {
        kind: "no_caret",
        targetId: commit.overlayPick.targetId,
        address: commit.overlayPick.address,
        refusal: commit.overlayPick.refusal,
        label: `${addressLabel(commit.overlayPick.address)} — ${caretRefusalText(commit.overlayPick.refusal)}`,
      },
      selection: commit.selection,
    });
    return true;
  }
  const sessionId = commit.sessionId;
  const existing = getState().texts[sessionId] ?? [];
  const region = commit.region as RegionText;
  const queued = queuedRunOpAt(getState(), commit.inlineEdit.atPara, commit.inlineEdit.run);
  setState({
    texts: {
      ...getState().texts,
      [sessionId]: [...existing.filter((r) => r.at_para !== commit.inlineEdit.atPara), region],
    },
    selection: commit.selection,
    inlineEdit: {
      ...commit.inlineEdit,
      opId: queued?.opId ?? null,
      before: queued?.before ?? commit.inlineEdit.before,
    },
    overlayPick: {
      kind: "caret",
      targetId: commit.overlayPick.targetId,
      address: commit.overlayPick.address,
      caret: commit.overlayPick.caret,
      label:
        `${addressLabel(commit.overlayPick.address)} · ` +
        (commit.overlayPick.snapped
          ? t("overlay_caret_snapped", getState().language)
          : t("overlay_caret_offset", getState().language, [
              commit.overlayPick.caret ?? 0,
            ])),
    },
  });
  return true;
}

/**
 * Put a caret in a paragraph line, or refuse and say which refusal it is.
 *
 * Prepare then commit: the read may await, but only a still-current lease
 * writes selection. A superseded reply is a silent no-op (null), not a
 * refusal a caller can turn into a stale overlay.
 */
export async function beginParagraphEdit(
  span: GeometrySpan,
  fraction?: number,
): Promise<CaretRefusal | null> {
  const intent = bumpEditIntent();
  const effect = await prepareOverlayParagraphEdit(span, fraction, intent);
  if (!effect) return "no_address";
  if (!applyOverlayParagraphCommit(effect)) return null;
  return effect.kind === "refused" ? effect.refusal : null;
}

export function cancelEdit(): void {
  setState({
    inlineEdit: null,
    sawComposition: false,
    editIntentGeneration: getState().editIntentGeneration + 1,
  });
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
  const queuedRun = edit.kind === "run" ? queuedRunOpAt(getState(), edit.atPara, edit.run) : null;
  // The splice base is `edit.rangeText`: the displayed run text the range was
  // measured on. Not `queuedRun.text` (a prior edit's result) and not
  // `edit.before` (the op baseline, overridden from the queued op) — each can
  // differ from the displayed text in length, and offsets measured on one
  // string applied to another splice at a stale position. The queue holds ONE
  // op per run; a second edit replaces the first relative to what the page
  // shows.
  const runText = edit.kind === "run" ? runTextAfterEdit(edit, trimmed) : trimmed;
  const unchanged = edit.kind === "run"
    ? runText === (queuedRun?.before ?? edit.before)
    : trimmed === edit.before;
  if (unchanged || (edit.kind === "cell" && trimmed === "")) {
    // Nothing changed, or Ruling J cleared an already-filled blank: remove with undo
    // rather than leaving a no-op or empty `""` entry in the queue.
    if (edit.opId) await undoQueuedOp(edit.opId);
    return;
  }
  const ops = getState().draft.ops.filter((op) => op.opId !== edit.opId);
  const commitState = getState();
  const commitSession = commitState.activeSessionId ?? undefined;
  const commitInspect = commitSession ? (commitState.inspects[commitSession] ?? null) : null;
  // T30, done for the person: a blank whose own run is superscript or
  // subscript would print the typed value small, and the engine already names
  // the body shape to use. The row says it was applied.
  const autoCharPr =
    edit.kind === "cell" && !edit.replaceExisting
      ? autoCharPrFor(seatAt(commitInspect, edit.table, edit.row, edit.col), edit.charPr)
      : null;
  // A blank the head 수정본 already filled is occupied; writing over it is the
  // intent, and preedit refuses an occupied cell unless told so.
  const headFilled =
    edit.kind === "cell" &&
    !edit.replaceExisting &&
    edit.before.trim().length > 0 &&
    activeHeadTexts(commitState) !== null &&
    edit.before !== seatText(commitInspect, commitSession ? (commitState.texts[commitSession] ?? []) : [], edit.table, edit.row, edit.col);
  // ONE QUEUE, ONE PLAN PATH, TWO OP KINDS. A value typed into a seat and a
  // sentence typed into a paragraph differ by exactly the operation kind the
  // runtime's own registry names for each. Everything past this line —
  // `setQueue`, `plan/propose`, `plan/validate`, the review queue, approval,
  // apply, the receipt — is the same code for both, which is what makes the
  // caret a new surface rather than a second mutation route.
  const next: QueuedOp =
    edit.kind === "cell"
      ? edit.replaceExisting
        ? {
            opId: edit.opId ?? `op-${cellSlug(edit.table, edit.row, edit.col)}`,
            kind: "replace_at_cell",
            table: edit.table,
            row: edit.row,
            col: edit.col,
            text: trimmed,
            mode: "replace",
            ...(edit.before ? { expect: edit.before } : {}),
            charPr: edit.charPr,
            before: edit.before,
            origin: "user",
          }
        : {
            opId: edit.opId ?? `op-${cellSlug(edit.table, edit.row, edit.col)}`,
            kind: "fill_cell",
            table: edit.table,
            row: edit.row,
            col: edit.col,
            text: trimmed,
            ...(trimmed.includes("\n") ? { lines: trimmed.split(/\r?\n/) } : {}),
            charPr: autoCharPr ?? edit.charPr,
            ...(autoCharPr ? { autoCharPr: true } : {}),
            ...(headFilled ? { overwrite: true } : {}),
            before: edit.before,
            origin: "user",
            ...(commitSession ? { sessionId: commitSession } : {}),
          }
      : {
          opId: edit.opId ?? `op-p${edit.atPara}r${edit.run}`,
          kind: "set_run",
          atPara: edit.atPara,
          run: edit.run,
          text: runText,
          before: queuedRun?.before ?? edit.before,
          origin: "user",
        };
  clearReturned([next]);
  await setQueue(
    [...ops, next],
    edit.kind === "run"
      ? { baseRunId: edit.runId ?? null }
      : edit.opId
        ? { rewritten: didRewriteAgent(edit.opId) }
        : {},
  );
}

function cellSlug(table: number, row: number, col: number): string {
  return `t${table}r${row}c${col}`;
}

/** Change a queued op's value without reopening the cell. */
export async function editOpValue(opId: string, text: string): Promise<void> {
  const ops = getState().draft.ops.map((op) => {
    if (op.opId !== opId || op.kind === "delete_guides") return op;
    if (op.kind === "fill_cell" && op.lines !== undefined) {
      return {
        ...op,
        text,
        lines: text.split(/\r?\n/),
        origin: "user" as const,
        proposer: undefined,
      };
    }
    return { ...op, text, origin: "user" as const, proposer: undefined };
  });
  await setQueue(ops, { rewritten: didRewriteAgent(opId) });
}

/** Add an op to the review queue, resolving current seat/run baseline when missing. */
export async function addQueueOp(op: QueuedOp): Promise<void> {
  const state = getState();
  const existingIds = new Set(state.draft.ops.map((item) => item.opId));
  let opId = op.opId || `${op.kind}-${Date.now().toString(36)}`;
  let suffix = 1;
  while (existingIds.has(opId)) {
    suffix += 1;
    opId = `${op.opId || op.kind}-${suffix}`;
  }
  const sessionId = state.activeSessionId;
  const inspect = sessionId ? (state.inspects[sessionId] ?? null) : null;
  const texts = sessionId ? (state.texts[sessionId] ?? []) : [];
  let normalized: QueuedOp = {
    ...op,
    opId,
    ...(sessionId && !op.sessionId ? { sessionId } : {}),
  } as QueuedOp;
  if (normalized.kind === "fill_cell" && normalized.before === "") {
    normalized = {
      ...normalized,
      before: seatText(inspect, texts, normalized.table, normalized.row, normalized.col),
    };
  } else if (normalized.kind === "replace_at_cell" && normalized.before === "") {
    normalized = {
      ...normalized,
      before: seatText(inspect, texts, normalized.table, normalized.row, normalized.col),
    };
  }
  if (normalized.origin === "user") clearReturned([normalized]);
  await setQueue([...state.draft.ops, normalized]);
}

/** Replace a canvas edit and rebuild the plan once, with the queue's existing base. */
export async function upsertQueueOp(op: QueuedOp): Promise<QueuedOp> {
  const { ops, queued, replaced } = upsertQueuedOp(getState().draft.ops, op);
  if (queued.origin === "user") clearReturned([queued]);
  await setQueue(ops, { rewritten: replaced.some((item) => item.origin === "agent") });
  return queued;
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

/** Re-propose a reviewed subset in one queue update. */
export async function removeReviewOps(source: Draft, ids: ReadonlySet<string>): Promise<boolean> {
  const state = getState();
  if (state.draft !== source || state.activeSessionId !== source.sessionId) return false;
  const sessionId = state.activeSessionId;
  if (!sessionId) return false;
  const kept = source.ops
    .filter((op) => !ids.has(op.opId))
    .map((op) => op.sessionId === undefined ? { ...op, sessionId } : op);
  if (kept.length === source.ops.length) return true;
  await setQueue(kept, {
    rewritten: source.ops.some((op) => ids.has(op.opId) && op.origin === "agent"),
    baseRunId: source.baseRunId,
  });
  await flushDraftValidation();
  const current = getState();
  return current.activeSessionId === source.sessionId &&
    (kept.length > 0 ? current.draft.ops === kept && current.draft.plan !== null : current.draft.ops.length === 0);
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
  // 빼기 on an agent's change is a return of that one change.
  if (op.origin === "agent") markReturned([op]);
  setState({ redoStack: [...getState().redoStack, op] });
  await setQueue(
    getState().draft.ops.filter((x) => x.opId !== opId),
    { rewritten },
  );
  showToast(t("toast_removed_from_queue", getState().language), 2000);
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
  clearReturned([op]);
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
  const prev = getState().draft;
  const clearedSession = prev.sessionId ?? getState().activeSessionId;
  if (clearedSession && typeof persistDraft === "function") persistDraft(clearedSession, null);
  if (typeof markExternalPlanDismissed === "function" && prev.sessionId && prev.plan?.planId) {
    markExternalPlanDismissed(prev.sessionId, prev.plan.planId);
  }
  bumpPlanGeneration();
  cancelDraftValidateTimer();
  setState({
    draft: EMPTY_DRAFT,
    inlineEdit: null,
    approval: null,
    approvalPhase: "idle",
    approvalError: null,
    approvalDialogOpen: false,
    reapprovalPrompt: null,
    applyPhase: "idle",
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
  // ADMISSION, for every path into the queue. A malformed op, or one made
  // for another document, stops the whole queue here: nothing is proposed
  // and nothing is saved. An op that names no document is stamped with this
  // one — the explicit migration, never a silent rebinding of a foreign op.
  const refused = typeof queueAdmission === "function" ? queueAdmission(ops, sessionId) : null;
  if (refused) {
    bumpPlanGeneration();
    cancelDraftValidateTimer();
    setState({
      approval: null,
      approvalPhase: "idle",
      approvalError: null,
      draft: {
        ...state.draft,
        plan: null,
        validation: null,
        boundSha256: null,
        phase: "failed",
        error: {
          code: refused.code,
          message: errorCodeMessage(refused.code, state.language),
          data: { opIds: refused.opIds, sessionId },
        },
      },
    });
    return;
  }
  if (sessionId && ops.some((op) => op.sessionId === undefined)) {
    ops = ops.map((op) => (op.sessionId === undefined ? { ...op, sessionId } : op));
  }
  // The plan this queue replaces, when it is this document's: the runtime
  // revokes its open approval in the same step as the new proposal.
  const replaces =
    state.draft.sessionId === sessionId && state.draft.plan?.planId && state.draft.plan.sessionId === sessionId
      ? state.draft.plan.planId
      : null;
  if (
    typeof markExternalPlanDismissed === "function" &&
    state.draft.sessionId &&
    state.draft.plan?.planId
  ) {
    markExternalPlanDismissed(state.draft.sessionId, state.draft.plan.planId);
  }
  // Empty replacements and document-close replacements must invalidate async
  // adopters/apply attempts too, even though they propose no next plan.
  const gen = bumpPlanGeneration();
  cancelDraftValidateTimer();
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
    reapprovalPrompt: null,
    applyPhase: "idle",
    applyError: null,
  });

  if (ops.length === 0 || !sessionId) {
    setState({ draft: { ...EMPTY_DRAFT, rewrittenFromAgent: false } });
    if (sessionId && typeof persistDraft === "function") persistDraft(sessionId, null);
    return;
  }

  // GENERATION FENCE. Bump before the first await so any concurrent call that
  // starts after this one gets a strictly larger token. After each async
  // suspension we check whether we still hold the latest token; if not, a
  // newer setQueue has taken over and this one must return silently rather
  // than overwriting the newer result.
  setState({
    draft: {
      ...state.draft,
      // The preceding plan belongs to the preceding queue. Leaving it visible
      // while a replacement proposal is in flight would let the review pane
      // offer bytes the user has already changed.
      plan: null,
      validation: null,
      boundSha256: null,
      ops,
      sessionId,
      phase: "starting",
      error: null,
      rewrittenFromAgent: rewritten,
      baseRunId,
      reverses,
    },
  });

  // Only this exact draft object owns the results below. Agent adoption uses
  // the same ownership rule, so neither path can overwrite newer user intent.
  let owner = captureDraftOwner();

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
              ...(op.lines !== undefined ? { lines: op.lines } : { text: op.text }),
              ...(op.charPr ? { charPr: op.charPr } : {}),
              ...(op.paraPr ? { paraPr: op.paraPr } : {}),
              ...(op.overwrite ? { overwrite: true } : {}),
            }
          : op.kind === "replace_at_cell"
            ? {
                opId: op.opId,
                kind: op.kind,
                table: op.table,
                row: op.row,
                col: op.col,
                text: op.text,
                ...(op.run !== undefined ? { run: op.run } : {}),
                ...(op.mode !== undefined ? { mode: op.mode } : {}),
                ...(op.expect !== undefined ? { expect: op.expect } : {}),
                ...(op.charPr ? { charPr: op.charPr } : {}),
              }
            : op.kind === "delete_guides"
              ? {
                  opId: op.opId,
                  kind: op.kind,
                  ...(op.color ? { color: op.color } : {}),
                  ...(op.charPrIds !== undefined ? { charPrIds: op.charPrIds } : {}),
                }
              : {
                  opId: op.opId,
                  kind: op.kind,
                  atPara: op.atPara,
                  run: op.run,
                  text: op.text,
                },
      ),
      { baseRunId, reverses, replaces },
    );
    if (typeof markExternalPlanDismissed === "function") {
      markExternalPlanDismissed(sessionId, plan.planId);
    }
    if (currentPlanGeneration() !== gen) return;
    if (!ownsDraft(owner)) return;
    const proposedDraft: Draft = {
      ops,
      plan,
      validation: null,
      sessionId,
      boundSha256: plan.boundSha256,
      phase: "starting",
      error: null,
      rewrittenFromAgent: rewritten,
      baseRunId,
      reverses,
    };
    setState({
      reapprovalPrompt: null,
      draft: proposedDraft,
    });
    owner = captureDraftOwner();
    if (typeof persistDraft === "function") persistDraft(sessionId, getState().draft);
    const runValidate = async (): Promise<void> => {
      if (currentPlanGeneration() !== gen) return;
      if (!ownsDraft(owner)) return;
      try {
        const validation = await rt.validatePlan(plan.planId);
        if (currentPlanGeneration() !== gen) return;
        if (!ownsDraft(owner)) return;
        setState({
          reapprovalPrompt: null,
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
        if (typeof persistDraft === "function") persistDraft(sessionId, getState().draft);
      } catch (e) {
        if (currentPlanGeneration() !== gen) return;
        if (!ownsDraft(owner)) return;
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
        if (typeof persistDraft === "function") persistDraft(sessionId, getState().draft);
      }
    };
    if (typeof setTimeout !== "function") {
      await runValidate();
      return;
    }
    const triggerValidate = (): Promise<void> => {
      cancelDraftValidateTimer();
      const running = runValidate().finally(() => {
        if (draftValidateInFlight === running) {
          draftValidateInFlight = null;
        }
      });
      draftValidateInFlight = running;
      return running;
    };
    draftValidateFlush = triggerValidate;
    draftValidateTimer = setTimeout(() => {
      void triggerValidate();
    }, DRAFT_VALIDATE_SETTLE_MS);
  } catch (e) {
    if (currentPlanGeneration() !== gen) return;
    if (!ownsDraft(owner)) return;
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
    if (typeof persistDraft === "function") persistDraft(sessionId, getState().draft);
  }
}

const DRAFT_VALIDATE_SETTLE_MS = 700;

let draftValidateTimer: ReturnType<typeof setTimeout> | null = null;
let draftValidateFlush: (() => Promise<void>) | null = null;
let draftValidateInFlight: Promise<void> | null = null;

function cancelDraftValidateTimer(): void {
  if (draftValidateTimer !== null) {
    if (typeof clearTimeout === "function") clearTimeout(draftValidateTimer);
    draftValidateTimer = null;
  }
  draftValidateFlush = null;
}

async function flushDraftValidation(): Promise<void> {
  const flush = draftValidateFlush;
  if (flush) {
    await flush();
    return;
  }
  if (draftValidateInFlight) {
    await draftValidateInFlight;
  }
}

/** Re-propose the queue against the document that is open now. */
export async function reproposeDraft(): Promise<void> {
  const state = getState();
  const ops = state.draft.ops;
  if (ops.length === 0) return;
  // A queue made for another document is never re-proposed onto this one.
  const foreign = foreignOps(state.draft, state.activeSessionId);
  if (foreign.length > 0) {
    setState({
      draft: {
        ...state.draft,
        phase: "failed",
        error: {
          code: "foreign_session_ops",
          message: errorCodeMessage("foreign_session_ops", state.language),
          data: { opIds: foreign.map((op) => op.opId), sessionId: state.draft.sessionId },
        },
      },
    });
    return;
  }
  // Re-proposing means "against the document as it is now": the head.
  await setQueue(ops, { baseRunId: headCandidate(state)?.runId ?? null });
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
const INVERTIBLE_KINDS = new Set(["fill_cell", "replace_at_cell", "set_run"]);

/** The address an op targets, in the shape `readRegion` takes. */
function opAddress(op: PlanOp): Record<string, number> | null {
  const p = op.params;
  if (op.kind === "fill_cell" || op.kind === "replace_at_cell") {
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
  const fence = captureDraftFence();
  setState({ undoPhase: "starting", undoError: null });
  try {
    const receipt = state.receipts[runId] ?? (await rt.readReceipt(sessionId, runId));
    const plan = await rt.getPlan(receipt.planId);
    if (!ownsDraftFence(fence)) return 0;

    const uninvertible = plan.ops.filter((op) => !INVERTIBLE_KINDS.has(op.kind));
    if (uninvertible.length > 0) {
      const lang = getState().language;
      setState({
        undoPhase: "failed",
        undoError: {
          code: "not_invertible",
          message: t("err_undo_not_invertible", lang, [
            uninvertible.map((op) => opKindLabel(op.kind, lang)).join(", "),
          ]),
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
          message: t("err_undo_no_addresses", getState().language),
        },
      });
      return 0;
    }

    const answer = await rt.readRegion(
      sessionId,
      addresses.map((row) => row.address),
      parentRunId,
    );
    if (!ownsDraftFence(fence)) return 0;

    // What the inverse would overwrite. The reversed candidate's own value at
    // each target, and the value the HEAD holds there now. If a later 수정본
    // edited the same target, the two differ and the inverse would erase that
    // later edit while showing the reversed edit's value as "before". Refused
    // by name instead (S-WP0 finding 9).
    const undoBase = headCandidate(getState())?.runId ?? null;
    const reversedAnswer = await rt.readRegion(
      sessionId,
      addresses.map((row) => row.address),
      runId,
    );
    if (!ownsDraftFence(fence)) return 0;
    const headAnswer =
      undoBase === runId
        ? reversedAnswer
        : await rt.readRegion(sessionId, addresses.map((row) => row.address), undoBase);
    if (!ownsDraftFence(fence)) return 0;

    const lang0 = getState().language;
    const conflicts: string[] = [];
    const nowAt = new Map<string, string>();
    for (const { op, address } of addresses) {
      const reversedValue = targetTextOf(op, regionMatchAt(reversedAnswer.regions, address));
      const headValue = targetTextOf(op, regionMatchAt(headAnswer.regions, address));
      if (reversedValue === null || headValue === null) {
        setState({
          undoPhase: "failed",
          undoError: {
            code: "previous_value_unreadable",
            message: t("err_undo_previous_unreadable", lang0),
            data: { address, subject: headValue === null ? headAnswer.subject : reversedAnswer.subject },
          },
        });
        return 0;
      }
      if (headValue !== reversedValue) {
        conflicts.push(t("undo_conflict_item", lang0, [undoAddressLabel(address, lang0), headValue, reversedValue]));
      }
      nowAt.set(op.opId, headValue);
    }
    if (conflicts.length > 0) {
      setState({
        undoPhase: "failed",
        undoError: {
          code: "undo_conflict",
          message: `${errorCodeMessage("undo_conflict", lang0)} ${conflicts.join("; ")}`,
          data: { runId, headRunId: undoBase, conflicts },
        },
      });
      return 0;
    }

    const ops: QueuedOp[] = [];
    for (const { op, address } of addresses) {
      const regionMatch = regionMatchAt(answer.regions, address);
      const previous = regionMatch?.text ?? null;
      // The actual value the inverse replaces: read off the head, which the
      // check above proved still equals what the reversed edit wrote.
      const current = nowAt.get(op.opId) ?? "";
      if (previous === null) {
        // The runtime did not return this address in the parent. That is not
        // an empty string and it must not be filled in as one: the inverse
        // would then WRITE a blank over something unknown.
        setState({
          undoPhase: "failed",
          undoError: {
            code: "previous_value_unreadable",
            message: t("err_undo_previous_unreadable", getState().language),
            data: { address, subject: answer.subject },
          },
        });
        return 0;
      }
      if (op.kind === "fill_cell") {
        const afterVal = Array.isArray(op.params.lines)
          ? op.params.lines.map(String).join("\n")
          : String(op.params.text ?? "");
        ops.push({
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
          before: current,
          origin: "user",
        });
        void afterVal;
      } else if (op.kind === "replace_at_cell") {
        const hasRun = op.params.run !== undefined && op.params.run !== null;
        const runIdx = hasRun ? Number(op.params.run) : undefined;
        const prevForTarget =
          runIdx !== undefined
            ? (regionMatch?.runs?.find((r) => r.index === runIdx)?.text ?? previous)
            : previous;
        ops.push({
          opId: `undo-${runId.slice(0, 8)}-${op.opId}`,
          kind: "replace_at_cell",
          table: Number(op.params.table ?? 0),
          row: Number(op.params.row),
          col: Number(op.params.col),
          ...(runIdx !== undefined ? { run: runIdx } : {}),
          text: prevForTarget,
          mode: "replace",
          before: current,
          origin: "user",
        });
      } else {
        const runIdx = Number(op.params.run);
        const runPrev = regionMatch?.runs?.find((r) => r.index === runIdx)?.text ?? previous;
        ops.push({
          opId: `undo-${runId.slice(0, 8)}-${op.opId}`,
          kind: "set_run",
          atPara: Number(op.params.atPara),
          run: runIdx,
          text: runPrev,
          before: current,
          origin: "user",
        });
      }
    }

    // Chained onto the HEAD, not onto the candidate being reversed: undoing an
    // older edit must not throw away the newer ones on top of it.
    if (!ownsDraftFence(fence)) return 0;
    // A 되돌리기 제안 that would land in the queue already unfixable is not a
    // proposal anybody can act on (GPT review finding 10). Validate it first;
    // if it fails, say why and leave the queue alone.
    const dryRun = await rt.proposePlan(sessionId, planOpsPayload(ops), {
      baseRunId: undoBase,
      reverses: runId,
    });
    markExternalPlanDismissed(sessionId, dryRun.planId);
    const dryValidation = await rt.validatePlan(dryRun.planId);
    if (!ownsDraftFence(fence)) return 0;
    const blocked = undoBlockReason(dryValidation, getState().language);
    if (blocked) {
      setState({
        undoPhase: "failed",
        undoError: {
          code: "undo_unfixable",
          message: blocked,
          data: { runId, hard: dryValidation.hard.map((row) => row.code) },
        },
      });
      return 0;
    }
    await setQueue(ops, {
      baseRunId: undoBase,
      reverses: runId,
    });
    if (getState().draft.ops !== ops) return 0;
    setState({ undoPhase: "ready", undoError: null, inverseProof: null });
    showToast(t("toast_undo_proposed", getState().language), 2600);
    return ops.length;
  } catch (e) {
    if (!ownsDraftFence(fence)) return 0;
    setState({ undoPhase: "failed", undoError: rt.asRuntimeError(e) });
    return 0;
  }
}

/**
 * The text one op targets inside a region record: the run it names, or the
 * whole cell. Null when the runtime did not return it.
 */
function targetTextOf(op: PlanOp, region: RegionText | undefined): string | null {
  if (!region) return null;
  const hasRun = op.params.run !== undefined && op.params.run !== null;
  if ((op.kind === "replace_at_cell" && hasRun) || op.kind === "set_run") {
    const idx = Number(op.params.run);
    const run = region.runs?.find((r) => r.index === idx);
    return run ? run.text : (region.text ?? null);
  }
  return region.text ?? null;
}

function undoAddressLabel(address: Record<string, number>, lang: UiLanguage): string {
  return address.atPara !== undefined
    ? t("addr_paragraph", lang, [address.atPara])
    : t("addr_table_cell", lang, [address.table ?? 0, address.row, address.col]);
}

/** The region record the runtime returned for one address, if any. */
function regionMatchAt(
  regions: RegionText[],
  address: Record<string, number>,
): RegionText | undefined {
  return address.atPara !== undefined
    ? regions.find((r) => r.at_para === address.atPara)
    : regions.find(
        (r) =>
          (r.table ?? 0) === address.table &&
          r.addr?.row === address.row &&
          r.addr?.col === address.col,
      );
}

/** The text the runtime returned for one address, or null if it returned none. */
function regionTextAt(
  regions: RegionText[],
  address: Record<string, number>,
): string | null {
  return regionMatchAt(regions, address)?.text ?? null;
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
  const expectedHead = getState().head;
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
    if (getState().activeSessionId !== sessionId || getState().head !== expectedHead) return false;
    setState({ inverseProof: { runId, reversedRunId, compare } });
    // A proof covers every address that was asked about: one unreadable
    // region and it is not a proof, whatever the readable ones say.
    const complete =
      compare.regions.length === regions.length &&
      (compare.regionsUnreadable ?? []).length === 0 &&
      compare.regions.every((row) => row.equal === true);
    return compare.regionsEqual === true && complete;
  } catch (e) {
    if (getState().activeSessionId === sessionId && getState().head === expectedHead) {
      setState({ undoError: rt.asRuntimeError(e) });
    }
    return false;
  }
}

/** Show an older candidate in the 기록 panel. Read-only; never moves the head. */
export function selectHistory(runId: string | null): void {
  setState({ historySelected: runId });
  if (runId && !getState().receipts[runId]) void loadReceipt(runId);
}

interface HeadSelectionLease {
  generation: number;
  sessionId: string | null;
  runId: string | null;
}

let headSelectionGeneration = 0;

/** Begin one explicit head choice; a later choice supersedes it even for the same run. */
function captureHeadSelection(runId: string | null): HeadSelectionLease {
  return {
    generation: ++headSelectionGeneration,
    sessionId: getState().activeSessionId,
    runId,
  };
}

/** The receipt and queue rebase may publish only for the latest unchanged choice. */
function ownsHeadSelection(lease: HeadSelectionLease): boolean {
  const state = getState();
  return (
    headSelectionGeneration === lease.generation &&
    state.activeSessionId === lease.sessionId &&
    state.head === lease.runId
  );
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
  const lease = captureHeadSelection(runId);
  setState({
    head: runId,
    applied: null,
    // A verdict for the preceding head must not remain visible while this
    // candidate's receipt is being verified.
    candidateVerdict: null,
    editIntentGeneration: getState().editIntentGeneration + 1,
  });
  if (runId) {
    await loadReceipt(runId, () => ownsHeadSelection(lease));
  }
  if (!ownsHeadSelection(lease)) return;
  if (getState().draft.ops.length > 0) {
    await setQueue(getState().draft.ops, { baseRunId: runId });
  }
}

// --- approval ------------------------------------------------------------------

let approvalRequestGeneration = 0;

export async function requestApprovalForDraft(): Promise<void> {
  if (draftValidationPending(getState().draft)) {
    await flushDraftValidation();
  }
  const state = getState();
  const plan = state.draft.plan;
  if (
    !plan ||
    !state.activeSessionId ||
    state.draft.sessionId !== state.activeSessionId ||
    plan.sessionId !== state.activeSessionId ||
    (!!state.head && (state.candidates?.[state.activeSessionId] ?? []).some((row) => row.runId === state.head)
      && (plan.base?.runId ?? null) !== state.head) ||
    state.approval !== null ||
    !canRequestApproval(state)
  ) {
    return;
  }
  const generation = ++approvalRequestGeneration;
  const draft = state.draft;
  const captured = {
    sessionId: state.activeSessionId,
    planId: plan.planId,
    planHash: plan.planHash,
  };
  setState({ approvalPhase: "requesting", approvalError: null });
  try {
    const approval = await rt.requestApproval(plan.planId);
    const current = getState();
    if (
      generation !== approvalRequestGeneration ||
      current.approvalPhase !== "requesting" ||
      current.approval !== null ||
      current.draft !== draft ||
      (current.activeSessionId === captured.sessionId && current.head !== state.head) ||
      current.draft.sessionId !== captured.sessionId ||
      current.draft.plan?.sessionId !== captured.sessionId ||
      current.draft.plan.planId !== captured.planId ||
      current.draft.plan.planHash !== captured.planHash ||
      approval.planId !== captured.planId ||
      approval.planHash !== captured.planHash
    ) {
      return;
    }
    setState({ approval, approvalPhase: "pending" });
  } catch (e) {
    const current = getState();
    if (
      generation === approvalRequestGeneration &&
      current.approvalPhase === "requesting" &&
      current.approval === null &&
      current.draft === draft
    ) {
      setState({ approvalPhase: "idle", approvalError: rt.asRuntimeError(e) });
    }
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
  reason: string | null = null,
  options: { confirmed?: ConfirmationBinding; autoApply?: boolean; confirmationToken?: string | null } = {},
): Promise<void> {
  const state = getState();
  const approval = state.approval;
  const binding = activeApprovalBinding(state);
  if (!approval || approval.state !== "pending" || !binding) return;
  // From the approval sheet: the decision is recorded only for the plan the
  // person confirmed, never for whatever the queue holds by now.
  if (options.confirmed && !approvalBindsConfirmation(approval, options.confirmed)) return;
  setState({ approvalPhase: "resolving", approvalError: null });
  try {
    const resolved = await rt.resolveApproval(
      binding.approvalId,
      binding.planId,
      binding.planHash,
      decision,
      approver,
      reason,
      options.confirmationToken ?? null,
    );
    // The decision belongs only to the captured draft/approval. Its resolved
    // record may remain on that exact preserved queue after a session switch,
    // but it must never replace a newer queue or approval.
    const current = getState();
    if (!approvalBindingStillExists(current, binding)) return;
    setState({ approval: resolved, approvalPhase: "resolved" });
    // A resolved approval remains an honest Runtime fact on its preserved
    // queue, but only the still-active exact binding may auto-apply it.
    if (
      decision === "approved" &&
      options.autoApply !== false &&
      current.draft === state.draft &&
      current.head === state.head &&
      approvalBindingIsCurrent(getState(), binding)
    ) {
      await applyApproved(options.confirmed);
    } else if (decision === "rejected" && approvalBindingIsCurrent(getState(), binding)) {
      showToast(t("toast_proposal_returned", getState().language), 2000);
    }
  } catch (e) {
    // `plan_stale` lands here when the source moved between the approval
    // request and the decision. Keep the queue; offer a re-propose.
    if (approvalBindingStillExists(getState(), binding)) {
      setState({ approvalPhase: "pending", approvalError: rt.asRuntimeError(e) });
    }
  }
}

// --- apply ----------------------------------------------------------------------

const APPLY_TAG = "apply";
let applyInFlight = false;

function applyPresentation(sessionId: string | null) {
  const outcome = sessionId ? getState().applyOutcomes?.[sessionId] : undefined;
  return {
    applied: outcome?.applied ?? null,
    applyError: outcome?.error ?? null,
    recovery: outcome?.recovery ?? null,
    applyPhase: outcome?.applied ? "ready" as const : outcome?.error ? "failed" as const : "idle" as const,
  };
}

export async function applyApproved(confirmed?: ConfirmationBinding): Promise<void> {
  const state = getState();
  const plan = state.draft.plan;
  const approval = state.approval;
  const sessionId = state.activeSessionId;
  if (!plan || !approval || approval.state !== "approved" || !sessionId || state.applyPhase === "starting" || applyInFlight) return;
  // The last gate before bytes move: the plan and approval about to be sent
  // are the ones the person confirmed, on the document they confirmed them on.
  if (
    confirmed &&
    (confirmationBreak(confirmed, state) !== null || !approvalBindsConfirmation(approval, confirmed))
  ) {
    return;
  }
  const draft = state.draft;
  const driftMsg = t("reapproval_prompt", state.language);
  const sameDraftApproval =
    draft.sessionId === sessionId &&
    plan.sessionId === sessionId &&
    approval.planId === plan.planId &&
    approval.planHash === plan.planHash;
  const staleness = draftStaleness(state);
  const headMovedOnSession =
    !!state.head &&
    (state.candidates?.[sessionId] ?? []).some((row) => row.runId === state.head) &&
    (plan.base?.runId ?? null) !== state.head;
  if (
    sameDraftApproval &&
    (draft.validation?.stale ||
      staleness?.kind === "source_changed" ||
      (draft.boundSha256 && plan.boundSha256 !== draft.boundSha256) ||
      headMovedOnSession)
  ) {
    setState({
      approval: null,
      approvalPhase: "idle",
      approvalError: { code: "plan_stale", message: driftMsg },
      reapprovalPrompt: driftMsg,
    });
    showToast(driftMsg, 3200);
    return;
  }
  const binding = activeApprovalBinding(state);
  if (!binding) return;
  const priorRecovery = state.applyOutcomes?.[sessionId]?.recovery ?? state.recovery;
  if (priorRecovery && priorRecovery.outcome !== "not_applied" && priorRecovery.planId === plan.planId && priorRecovery.approvalId === approval.approvalId) return;
  const reversed = state.draft.reverses;
  setState({ applyPhase: "starting", applyError: null, recovery: null });
  let applied: AppliedCandidate;
  applyInFlight = true;
  try {
    applied = await rt.applyPlan(plan.planId, approval.approvalId, APPLY_TAG);
  } catch (e) {
    applyInFlight = false;
    const error = rt.asRuntimeError(e);
    // A dead sidecar mid-apply is the ambiguous case: the run directory is
    // removed on any failure inside `apply_plan`, but a process that died
    // between the artifact move and the receipt write leaves neither a
    // candidate nor a signal. Record what was in flight and offer to look.
    const recovery = error.code === "sidecar_down" || error.code === "timeout" || error.code === "apply_outcome_unknown" || error.code === "apply_in_progress"
      ? {
          planId: plan.planId,
          approvalId: approval.approvalId,
          atUtc: new Date().toISOString().replace(/\.\d+Z$/, "Z"),
          reason: error.message,
          outcome: "unknown" as const,
          runId: null,
        }
      : null;
    setState({ applyOutcomes: {
      ...getState().applyOutcomes,
      [sessionId]: { applied: null, error, recovery },
    } });
    const current = getState();
    const staleReject =
      error.code === "plan_stale" || error.code === "approval_binding_mismatch";
    if (staleReject && current.draft === draft && approvalBindingStillExists(current, binding)) {
      setState({
        approval: null,
        approvalPhase: "idle",
        approvalError: error,
        reapprovalPrompt: driftMsg,
      });
      showToast(driftMsg, 3200);
    }
    if (current.activeSessionId === sessionId && current.draft === draft && current.head === state.head) {
      setState(applyPresentation(sessionId));
    } else if (current.applyPhase === "starting") {
      setState(current.activeSessionId !== sessionId
        ? applyPresentation(current.activeSessionId)
        : { applyPhase: "idle" });
    }
    return;
  }

  applyInFlight = false;
  // Publication is separate from Runtime apply: a later refresh failure must
  // never relabel a successfully receipted operation as a failed apply.
  const current = getState();
  const ownsQueue = current.draft === draft && approvalBindingStillExists(current, binding)
    && (current.activeSessionId !== sessionId || current.head === state.head);
  const ownsPresentation = ownsQueue && current.activeSessionId === sessionId && current.head === state.head;
  setState({ applyOutcomes: {
    ...current.applyOutcomes,
    [sessionId]: { applied, error: null, recovery: null },
  } });
  setState({
    ...(ownsPresentation ? applyPresentation(sessionId)
      : current.applyPhase === "starting"
        ? current.activeSessionId !== sessionId
          ? applyPresentation(current.activeSessionId)
          : { applyPhase: "idle" as const }
        : {}),
    ...(ownsQueue
      ? {
          draft: EMPTY_DRAFT,
          redoStack: [],
          approvalPhase: "idle" as const,
          approval: null,
          approvalDialogOpen: false,
          reapprovalPrompt: null,
        }
      : {}),
    ...(ownsPresentation ? {
      candidateVerdict: { runId: applied.runId, report: applied.checks },
      head: applied.runId,
      historySelected: applied.runId,
      inverseProof: null,
      showOriginal: false,
    } : {}),
  });
  if (ownsQueue && typeof markExternalPlanDismissed === "function") {
    markExternalPlanDismissed(sessionId, plan.planId);
  }
  if (ownsQueue && typeof persistDraft === "function") persistDraft(sessionId, null);
  // The applied queue may have been parked by a document switch mid-apply.
  const parkedApplied = getState().parkedDrafts?.[sessionId];
  if (parkedApplied && parkedApplied.draft.plan?.planId === plan.planId) {
    const nextParked = { ...getState().parkedDrafts };
    delete nextParked[sessionId];
    setState({ parkedDrafts: nextParked });
  }
  await loadCandidates(sessionId);
  if (ownsPresentation && typeof loadHeadTexts === "function") {
    await loadHeadTexts(sessionId, applied.runId);
  }
  if (!ownsPresentation || getState().activeSessionId !== sessionId || getState().head !== applied.runId) return;
  if (reversed) await verifyReversal(applied.runId, reversed);
  if (getState().activeSessionId === sessionId && getState().head === applied.runId) {
    const revNum =
      (getState().candidates[sessionId] ?? [])
        .filter((c) => Boolean(c.runId))
        .slice()
        .sort((x, y) => (x.createdUtc ?? "").localeCompare(y.createdUtc ?? ""))
        .findIndex((c) => c.runId === applied.runId) + 1;
    showToast(
      revNum > 0
        ? (uiVariant() === "v2"
          ? WP4.t("wp4_applied_status", getState().language, [revNum])
          : t("apply_done_toast", getState().language, [revNum]))
        : t("review_applied_ok", getState().language),
      2200,
    );
  }
}

/** Cooperative cancel, between ops. Never a kill. */
export async function cancelApply(): Promise<void> {
  await rt.cancel(APPLY_TAG);
  showToast(t("toast_apply_cancelling", getState().language), 2400);
}

export const REAPPROVAL_PROMPT = t("reapproval_prompt", "ko");

/**
 * Re-validate the active draft plan against current source/candidate bytes.
 * Clears any stale approval immediately if the bound SHA-256 or candidate drifted.
 */
export async function revalidateActiveDraft(): Promise<{ ok: boolean; stale: boolean }> {
  cancelDraftValidateTimer();
  const state = getState();
  const draft = state.draft;
  const plan = draft.plan;
  if (!plan) return { ok: false, stale: false };

  if (draftStaleness(state) !== null) {
    setState({
      approval: null,
      approvalPhase: "idle",
      approvalError: { code: "plan_stale", message: REAPPROVAL_PROMPT },
      reapprovalPrompt: REAPPROVAL_PROMPT,
    });
    showToast(REAPPROVAL_PROMPT, 3400);
    return { ok: false, stale: true };
  }

  try {
    const validation = await rt.validatePlan(plan.planId);
    const current = getState();
    // Another validation of the same plan (the one the dialog starts when it
    // opens) may land first and replace the draft object; only a different
    // plan makes this answer moot.
    if (current.draft.plan !== plan || current.draft.sessionId !== draft.sessionId) {
      return { ok: false, stale: false };
    }
    const currentSha =
      typeof validation.currentSha256 === "string" ? validation.currentSha256 : null;
    const staleHard = validation.hard.some((h) => h.code === "plan_stale");
    const drifted =
      Boolean(validation.stale) ||
      staleHard ||
      validation.boundSha256 !== plan.boundSha256 ||
      (currentSha !== null && currentSha !== plan.boundSha256) ||
      draftStaleness(current) !== null;

    if (drifted) {
      const hadApproval = current.approval !== null || current.approvalPhase !== "idle";
      const wasStarting = current.draft.phase === "starting";
      setState({
        draft: {
          ...current.draft,
          validation,
          ...(wasStarting ? { phase: "ready" as const } : {}),
        },
        approval: null,
        approvalPhase: "idle",
        approvalError: { code: "plan_stale", message: REAPPROVAL_PROMPT },
        reapprovalPrompt: REAPPROVAL_PROMPT,
      });
      if (wasStarting && current.draft.sessionId && typeof persistDraft === "function") {
        persistDraft(current.draft.sessionId, getState().draft);
      }
      if (hadApproval || validation.stale) {
        showToast(REAPPROVAL_PROMPT, 3600);
      }
      return { ok: false, stale: true };
    }

    const wasStarting = current.draft.phase === "starting";
    setState({
      draft: {
        ...current.draft,
        validation,
        ...(wasStarting ? { phase: "ready" as const } : {}),
      },
      reapprovalPrompt: null,
    });
    if (wasStarting && current.draft.sessionId && typeof persistDraft === "function") {
      persistDraft(current.draft.sessionId, getState().draft);
    }
    return { ok: validation.ok !== false, stale: false };
  } catch (e) {
    const error = rt.asRuntimeError(e);
    if (error.code === "plan_stale" || error.code === "approval_binding_mismatch") {
      if (getState().draft === draft) {
        setState({
          approval: null,
          approvalPhase: "idle",
          approvalError: error,
          reapprovalPrompt: REAPPROVAL_PROMPT,
        });
        showToast(REAPPROVAL_PROMPT, 3600);
      }
      return { ok: false, stale: true };
    }
    return { ok: false, stale: false };
  }
}

export async function verifyAndApplyApproved(): Promise<void> {
  const check = await revalidateActiveDraft();
  if (check.stale) return;
  await applyApproved();
}

export async function revalidateAndResolveApproval(
  decision: "approved" | "rejected",
  approver = "host-operator",
): Promise<void> {
  if (decision === "approved") {
    const check = await revalidateActiveDraft();
    if (check.stale) return;
  }
  await resolveApprovalDecision(decision, approver);
}

/**
 * The approval sheet's 승인. Bound to what the person confirmed.
 *
 * `confirmed` is captured in the click handler from the sheet as rendered:
 * session, plan id, plan hash, base digest and the acknowledgements ticked.
 * After every wait — revalidation, the approval request, the decision — the
 * live state is checked against it. An adopted agent proposal, a document
 * switch, a failed validation or a new acknowledgement requirement stops the
 * flow before the next step, and the sheet asks for a fresh confirmation.
 * Re-reading "the current draft" after an await is how a confirmation could
 * reach a plan nobody saw (S-WP0 finding 1).
 */
export async function approveAndApplyFromDialog(
  confirmed: ConfirmationBinding | null,
  approver = "host-operator",
): Promise<boolean> {
  if (!confirmed) return false;
  const broken = (): ConfirmationBreak | null => {
    const state = getState();
    const guard = typeof getReviewGuardSummary === "function" ? getReviewGuardSummary() : null;
    const guardAcks = guard && guard.planId === confirmed.planId ? requiredGuardAcks(guard).total : 0;
    if (guard && diffDigestBreaks(guard, confirmed)) return "diff_mismatch";
    return confirmationBreak(confirmed, state, requiredAcknowledgements(state.draft, guardAcks));
  };
  const stop = (why: ConfirmationBreak): false => {
    const lang = getState().language;
    // The sheet that is open now asks again. After a document switch the open
    // sheet belongs to another document, so only the toast speaks.
    if (why !== "document_switched") {
      setState({
        approvalError: {
          code: "confirmation_changed",
          message: errorCodeMessage("confirmation_changed", lang),
          data: { reason: why, planId: confirmed.planId, sessionId: confirmed.sessionId },
        },
      });
    }
    showToast(errorCodeMessage("confirmation_changed", lang), 3600);
    return false;
  };

  let why = broken();
  if (why) return stop(why);

  // Wait 1: revalidation.
  const check = await revalidateActiveDraft();
  if (check.stale) return false;
  why = broken();
  if (why) return stop(why);
  if (!check.ok) return stop("validation_failed");

  // Wait 2: the approval request.
  if (!getState().approval) {
    await requestApprovalForDraft();
    why = broken();
    if (why) return stop(why);
  }
  const requested = getState().approval;
  if (!approvalBindsConfirmation(requested, confirmed)) return stop("plan_replaced");

  // Wait 3: the decision. Apply is NOT chained inside it; it runs below,
  // after one more check. Through the browser bridge the decision carries
  // the sheet's single-use confirmation token for exactly this plan.
  if (requested!.state === "pending") {
    const confirmationToken = await takeSheetConfirmation(confirmed);
    why = broken();
    if (why) return stop(why);
    await resolveApprovalDecision("approved", approver, null, { confirmed, autoApply: false, confirmationToken });
    why = broken();
    if (why) return stop(why);
  }
  const decided = getState().approval;
  if (!approvalBindsConfirmation(decided, confirmed) || decided!.state !== "approved") return false;
  await applyApproved(confirmed);
  return true;
}

export function openApprovalDialog(): void {
  setState({ approvalDialogOpen: true });
  // Also finishes a validation still waiting for the queue to settle: the
  // sheet's confirm stays disabled until the result is in state.
  void revalidateActiveDraft();
}

export function closeApprovalDialog(): void {
  setState({ approvalDialogOpen: false });
}

const THEME_STORAGE_KEY = "rigorloom.theme";

export function effectiveTheme(theme = getState().theme): "light" | "dark" {
  if (theme === "light" || theme === "dark") return theme;
  if (typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches) {
    return "dark";
  }
  return "light";
}

function applyThemeToDom(theme: "auto" | "light" | "dark"): void {
  if (typeof document === "undefined") return;
  if (theme === "auto") {
    document.documentElement.removeAttribute("data-theme");
  } else {
    document.documentElement.setAttribute("data-theme", theme);
  }
}

export function applyStoredTheme(): void {
  let theme: "auto" | "light" | "dark" = "auto";
  try {
    const saved = window.localStorage?.getItem(THEME_STORAGE_KEY);
    if (saved === "light" || saved === "dark" || saved === "auto") {
      theme = saved;
    }
  } catch {
    // ignore storage errors in restricted contexts
  }
  setState({ theme });
  applyThemeToDom(theme);
}

export async function toggleTheme(explicit?: "auto" | "light" | "dark"): Promise<void> {
  const current = getState().theme;
  const next: "auto" | "light" | "dark" =
    explicit ?? (effectiveTheme(current) === "dark" ? "light" : "dark");
  setState({ theme: next });
  applyThemeToDom(next);
  try {
    window.localStorage?.setItem(THEME_STORAGE_KEY, next);
  } catch {
    // ignore storage errors
  }
  await rt.savePrefs({ theme: next }).catch(() => {});
}

export async function refreshGuardDiff(overrides?: {
  sessionId?: string | null;
  runId?: string | null;
  againstRunId?: string | null;
  planId?: string | null;
  beforeText?: string | null;
  afterText?: string | null;
}): Promise<GuardDiffResult | null> {
  const state = getState();
  const useDirect =
    overrides?.beforeText !== undefined && overrides?.afterText !== undefined;
  const sessionId = overrides?.sessionId !== undefined ? overrides.sessionId : state.activeSessionId;
  const planId =
    overrides?.planId !== undefined
      ? overrides.planId
      : (state.draft.sessionId === sessionId ? state.draft.plan?.planId ?? null : null);
  const runId =
    overrides?.runId !== undefined
      ? overrides.runId
      : (state.historySelected ?? headCandidate(state)?.runId ?? null);

  if (!useDirect && !sessionId) {
    setState({ guardDiff: null, guardDiffPhase: "idle", guardDiffError: null });
    return null;
  }

  setState({ guardDiffPhase: "starting", guardDiffError: null });
  try {
    const payload = useDirect
      ? { beforeText: overrides?.beforeText ?? "", afterText: overrides?.afterText ?? "" }
      : {
          sessionId: sessionId ?? undefined,
          ...(planId ? { planId } : {}),
          ...(runId ? { runId } : {}),
          ...(overrides?.againstRunId ? { againstRunId: overrides.againstRunId } : {}),
        };
    const result = await rt.guardDiff(payload);
    setState({ guardDiff: result, guardDiffPhase: "ready", guardDiffError: null });
    return result;
  } catch (e) {
    setState({
      guardDiffPhase: "failed",
      guardDiffError: rt.asRuntimeError(e),
    });
    return null;
  }
}

export async function loadPipelineGates(workspace?: string): Promise<PipelineGatesResult | null> {
  const ws = (workspace ?? getState().pipelineWorkspace).trim();
  if (!ws) {
    setState({
      pipelineGatesPhase: "failed",
      pipelineGatesError: {
        code: "workspace_missing",
        message: t("err_pipeline_workspace_missing", getState().language),
      },
    });
    return null;
  }
  setState({ pipelineWorkspace: ws, pipelineGatesPhase: "starting", pipelineGatesError: null });
  try {
    const res = await rt.pipelineGates(ws);
    setState({
      pipelineWorkspace: res.workspace || ws,
      pipelineGatesResult: res,
      pipelineGatesPhase: "ready",
      pipelineGatesError: null,
    });
    return res;
  } catch (e) {
    setState({
      pipelineGatesPhase: "failed",
      pipelineGatesError: rt.asRuntimeError(e),
    });
    return null;
  }
}

export async function resolvePipelineGateAction(
  workspace: string,
  gate: string,
  decision: "approved" | "rejected",
  reason?: string,
): Promise<boolean> {
  setState({ pipelineGatesPhase: "starting", pipelineGatesError: null });
  try {
    const res = await rt.resolvePipelineGate({
      workspace,
      gate,
      decision,
      approver: "host-operator",
      reason,
    });
    const lang = getState().language;
    showToast(
      t("toast_gate_resolved", lang, [
        res.gate,
        t(
          decision === "approved" ? "gate_decision_approved" : "gate_decision_rejected",
          lang,
        ),
      ]),
      2400,
    );
    await loadPipelineGates(workspace);
    return true;
  } catch (e) {
    setState({
      pipelineGatesPhase: "failed",
      pipelineGatesError: rt.asRuntimeError(e),
    });
    return false;
  }
}

/**
 * After a crash: can the interrupted apply be proven to have landed?
 *
 * A list row is only a lead. It must name the captured plan, and its verifying
 * receipt must bind the captured session, run, plan and approval. Absence is
 * still unknown: the Runtime may still be publishing the candidate.
 */
export async function resolveRecovery(): Promise<void> {
  const state = getState();
  const recovery = state.recovery;
  const sessionId = state.activeSessionId;
  if (!recovery || !sessionId) return;
  const draft = state.draft;
  const approval = state.approval;

  const stillOwned = () => getState().applyOutcomes[sessionId]?.recovery === recovery;
  const publishError = (error: RuntimeError) => {
    const current = getState();
    const outcome = current.applyOutcomes[sessionId];
    if (outcome?.recovery !== recovery) return;
    const visible = current.activeSessionId === sessionId && current.recovery === recovery && current.applyPhase !== "starting";
    setState({
      applyOutcomes: {
        ...current.applyOutcomes,
        [sessionId]: { ...outcome, error },
      },
      ...(visible ? { applyError: error, applyPhase: "failed" as const } : {}),
    });
  };

  if (!stillOwned()) return;

  let candidates;
  try {
    candidates = await rt.candidates(sessionId);
  } catch (error) {
    publishError(rt.asRuntimeError(error));
    return;
  }
  if (!stillOwned()) return;

  const matches = candidates.filter(
    (candidate) => candidate.runId && candidate.planId === recovery.planId,
  );
  if (matches.length !== 1 || !matches[0].runId) return;
  const runId = matches[0].runId;

  let receipt;
  try {
    receipt = await rt.readReceipt(sessionId, runId);
  } catch (error) {
    publishError(rt.asRuntimeError(error));
    return;
  }
  if (!stillOwned()) return;

  const receiptMatches =
    receipt.sessionId === sessionId &&
    receipt.runId === runId &&
    receipt.planId === recovery.planId &&
    receipt.approval?.approvalId === recovery.approvalId &&
    receipt.approval?.planId === recovery.planId;
  if (!receiptMatches) {
    publishError({
      code: "recovery_receipt_mismatch",
      message: t("err_recovery_receipt_mismatch", getState().language),
    });
    return;
  }

  const applied: AppliedCandidate = {
    runId,
    sessionId,
    planId: receipt.planId,
    candidate: receipt.candidate,
    base: receipt.base,
    reverses: receipt.reverses,
    checks: receipt.checks,
    receipt: matches[0].receipt ?? `${runId}/receipt.json`,
    canonical: true,
  };
  const resolved = { ...recovery, outcome: "applied" as const, runId };
  const current = getState();
  const outcome = current.applyOutcomes[sessionId];
  if (outcome?.recovery !== recovery) return;
  const visible = current.activeSessionId === sessionId && current.recovery === recovery && current.applyPhase !== "starting";
  const ownsQueue =
    current.draft === draft &&
    draft.sessionId === sessionId &&
    draft.plan?.planId === recovery.planId &&
    current.approval === approval &&
    approval?.approvalId === recovery.approvalId &&
    approval.planId === recovery.planId;
  setState({
    applyOutcomes: {
      ...current.applyOutcomes,
      [sessionId]: { applied, error: null, recovery: resolved },
    },
    candidates: { ...current.candidates, [sessionId]: candidates },
    receipts: { ...current.receipts, [runId]: receipt },
    ...(ownsQueue
      ? {
          draft: EMPTY_DRAFT,
          redoStack: [],
          approval: null,
          approvalPhase: "idle" as const,
        }
      : {}),
    ...(visible
      ? {
          applied,
          applyError: null,
          applyPhase: "ready" as const,
          recovery: resolved,
          receiptError: null,
        }
      : {}),
  });
}

// --- receipts and the candidate's verdict ---------------------------------------

export async function loadReceipt(
  runId: string,
  ownsPublication: () => boolean = () => true,
): Promise<boolean> {
  const sessionId = getState().activeSessionId;
  if (!sessionId) return false;
  try {
    const receipt = await rt.readReceipt(sessionId, runId);
    if (getState().activeSessionId !== sessionId || !ownsPublication()) return false;
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
    if (getState().activeSessionId !== sessionId || !ownsPublication()) return false;
    const refusal = rt.asRuntimeError(e);
    setState({
      receiptError: refusal,
      receiptFailures: { ...(getState().receiptFailures ?? {}), [runId]: refusal.code },
    });
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
async function sha256Hex(bytes: ArrayBuffer): Promise<string | null> {
  if (typeof globalThis.crypto?.subtle?.digest !== "function") return null;
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

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

  const suggested =
    state.sessions
      .find((s) => s.sessionId === sessionId)
      ?.source.name.replace(/(\.hwpx?)$/i, "-candidate$1") ?? "candidate.hwpx";

  let target: string | null = destination ?? null;
  const lang = getState().language;
  if (!target && rt.isTauri()) {
    const picked = await saveFileDialog({
      title: t("action_export_revision_dialog_title", lang),
      defaultPath: suggested,
      filters: [{ name: t("action_open_hwpx_filter", lang), extensions: ["hwpx", "hwp"] }],
    });
    if (typeof picked !== "string") return false;
    target = picked;
  }

  setState({ exportPhase: "starting", exportError: null });
  try {
    const result = await rt.exportCandidate(
      sessionId,
      applied.runId,
      applied.candidate.path,
      target,
    );
    // The bytes that left must be the bytes the receipt bound. We verify the
    // digest before declaring success or handing off a download.
    if (result.sha256 !== applied.candidate.sha256) {
      setState({
        exportPhase: "failed",
        exportError: {
          code: "export_hash_mismatch",
          message: t("err_export_file_mismatch", lang),
          data: { expected: applied.candidate.sha256, actual: result.sha256 },
        },
      });
      return false;
    }

    if (!rt.isTauri() && result.downloadUrl && typeof document !== "undefined") {
      const resp = await fetch(rt.appendTokenQuery(result.downloadUrl), {
        headers: rt.tokenHeaders(),
      });
      if (!resp.ok) {
        throw {
          code: "export_download_failed",
          message: t("err_export_download_failed", lang, [resp.status]),
        };
      }
      const bytes = await resp.arrayBuffer();
      const digest = await sha256Hex(bytes);
      if (digest && digest !== applied.candidate.sha256) {
        setState({
          exportPhase: "failed",
          exportError: {
            code: "export_hash_mismatch",
            message: t("err_export_download_mismatch", lang),
            data: { expected: applied.candidate.sha256, actual: digest },
          },
        });
        return false;
      }
      const blobUrl = URL.createObjectURL(new Blob([bytes]));
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = suggested;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
    }

    setState({ exportPhase: "ready", exportResult: result });
    showToast(t("export_done_toast", getState().language), 2400);
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

/** `${sessionId}:${page}` for the source; candidate pages add `:${runId}`. */
export function geometryKey(sessionId: string, page: number, runId?: string | null): string {
  return runId ? `${sessionId}:${page}:${runId}` : `${sessionId}:${page}`;
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
  const runId = displayedRevision(state)?.runId ?? state.render?.source?.runId ?? null;
  const key = geometryKey(sessionId, wanted, runId);

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
      const geometry = await rt.pageGeometry(sessionId, wanted, runId);
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
 * which run the click names, and whether the span would cross runs, is a
 * question only `document/readRegion` plus the caret offset can answer, and
 * `beginParagraphEdit` asks it at click time rather than this function guessing.
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
export function addressLabel(
  address: GeometryAddress,
  lang = getState().language,
): string {
  if (address.kind === "cell") {
    return t("addr_table_cell", lang, [
      address.table ?? 0,
      address.row ?? 0,
      address.col ?? 0,
    ]);
  }
  if (address.atPara !== undefined && address.atPara !== null) {
    return t("addr_paragraph", lang, [address.atPara]);
  }
  return address.text
    ? t("addr_anchor", lang, [trimRun(address.text, 12)])
    : t("addr_none", lang);
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
        label: t("overlay_not_editable_cell", getState().language, [
          addressLabel(address),
        ]),
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
export function derivationLabel(
  derivation: string,
  lang = getState().language,
): string {
  switch (derivation) {
    case "cell_borders":
      return t("deriv_cell_borders", lang);
    case "matched_text":
      return t("deriv_matched_text", lang);
    case "interpolated":
      return t("deriv_interpolated", lang);
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
        // On an own-rendered page the runtime also passes along which of these
        // OUR renderer drew the line from. Shown, not taken.
        sidecarPick: span.sidecarPick,
        label: t("overlay_ambiguous_pick", getState().language, [candidates.length]),
      },
    });
    return;
  }
  const address = span.address;
  if (!address) {
    const lang = getState().language;
    // UNMAPPED, and it now says so. This used to return in silence, which was
    // fine while every page came from a PDF and an unmapped line was a rare
    // miss.
    //
    // On an own-rendered page it is a different fact and gets different words.
    // The line WAS matched against the form scan, exactly like a PDF-read line,
    // and matched nothing — and our renderer usually knows perfectly well which
    // paragraph or cell it drew it from. That address is on the span and is
    // deliberately not applied: one witness is not a mapping. Saying so is the
    // point. A silent click would read as a dead page.
    setState({
      overlayPick: {
        kind: "unmapped",
        targetId: id,
        address: null,
        label:
          span.addressBasis === "sidecar_only"
            ? t("overlay_unmapped_sidecar", lang, [
                span.index + 1,
                addressLabel(span.sidecarAddress!, lang),
              ])
            : t("overlay_unmapped_plain", lang, [span.index + 1]),
      },
    });
    return;
  }

  // A PARAGRAPH LINE. Prepare returns an effect with a revision/intent lease;
  // this public boundary is the only place that writes. A superseded reply
  // — including two clicks completed in reverse order — is a silent no-op,
  // not a refusal this handler can turn back into an old selection.
  if (addressIsCaretTarget(address)) {
    const intent = bumpEditIntent();
    const effect = await prepareOverlayParagraphEdit(span, fraction, intent);
    if (!effect) {
      setState({
        overlayPick: {
          kind: "no_caret",
          targetId: id,
          address,
          refusal: "no_address",
          label: `${addressLabel(address)} — ${caretRefusalText("no_address")}`,
        },
      });
      return;
    }
    applyOverlayParagraphCommit(effect);
    return;
  }

  if (!addressIsEditable(address)) {
    setState({
      overlayPick: {
        kind: "not_editable",
        targetId: id,
        address,
        label: t("overlay_not_editable_cell", getState().language, [
          addressLabel(address),
        ]),
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
    if (!span) {
      setState({
        overlayPick: {
          kind: "no_caret",
          targetId: pick?.targetId ?? "candidate",
          address,
          refusal: "no_address",
          label: `${addressLabel(address)} — ${caretRefusalText("no_address")}`,
        },
      });
      return;
    }
    const intent = bumpEditIntent();
    const effect = await prepareOverlayParagraphEdit(
      { ...span, address, confidence: "unique" },
      undefined,
      intent,
    );
    if (!effect) return;
    applyOverlayParagraphCommit(effect);
    return;
  }

  if (!addressIsEditable(address)) {
    setState({
      overlayPick: {
        kind: "not_editable",
        targetId: pick?.targetId ?? "candidate",
        address,
        label: t("overlay_not_editable_cell", getState().language, [
          addressLabel(address),
        ]),
      },
    });
    return;
  }
  setState({
    overlayPick: {
      kind: "unique",
      targetId: pick?.targetId ?? "candidate",
      address,
      label: t("overlay_user_selected", getState().language, [
        addressLabel(address),
      ]),
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
  const lang = getState().language;
  setState({ preparePhase: "starting", prepareError: null, prepareNote: null });
  try {
    const result = await rt.renderPrepare(sessionId, runId ?? null);
    setState({
      preparePhase: "ready",
      prepareNote: result.prepared
        ? t(
            runId ? "prepare_note_revision_ready" : "prepare_note_original_ready",
            lang,
          )
        : (result.reason ?? t("prepare_note_already_ready", lang)),
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
 * The empty address list, shared.
 *
 * `changedByRun` holds no entry until `loadChangedAddresses` has walked the
 * chain, and that window is exactly the moment after an apply — so this
 * default is taken on the renders that matter most. A fresh `[]` there fails
 * the identity check below, rebuilds the echo on every call, and turns
 * `useSyncExternalStore` into the unbounded render loop React reports as
 * #185. The comment on `layoutEcho` said so; the `?? []` did it anyway.
 */
const NO_CHANGES: string[] = [];

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
  const changed = s.changedByRun[head.runId] ?? NO_CHANGES;
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
 * be open. IPC may deliver the first notification before the response; the
 * event owner buffers that window and authenticates it with the returned id.
 */
export async function startEvents(sessionId: string): Promise<void> {
  await startDocumentEvents(sessionId);
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
  // The test agent runs only with the developer setting on.
  if (state.agentHost?.mockAllowed !== true) {
    setState({
      agentPhase: "failed",
      agentError: {
        code: "agent_not_connected",
        message: errorCodeMessage("agent_not_connected", state.language),
      },
    });
    return false;
  }
  const owner = captureDraftOwner();
  setState({ agentPhase: "starting", agentError: null });
  try {
    const outcome = await rt.runMockAgent(sessionId, marker);
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(outcome.stdout) as Record<string, unknown>;
    } catch {
      throw {
        code: "agent_output_unreadable",
        message: t("err_agent_output_unreadable", getState().language),
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
    const adopted = await adoptAgentPlan(
      sessionId,
      plan.planId,
      approval?.approvalId ?? null,
      owner,
    );
    if (!adopted) {
      throw {
        code: "draft_superseded",
        message: t("err_agent_draft_superseded", getState().language),
      };
    }
    const { plan: authoritative } = adopted;
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
export function verdictFindings(
  report: VerificationReport,
  lang = getState().language,
): Finding[] {
  const out: Finding[] = [];
  for (const row of report.checks) {
    const state = String(row.state ?? "unknown");
    if (state !== "ran") {
      out.push({
        code: `${row.checker}_unavailable`,
        severity: "warn",
        where: t("finding_where_checker", lang, [row.checker]),
        selection: null,
        message: t("finding_check_not_run", lang, [
          String(row.reason ?? t("finding_reason_none", lang)),
        ]),
      });
      continue;
    }
    const hard = (row.hard as Array<{ code?: string; msg?: string; at?: string }>) ?? [];
    const warn = (row.warn as Array<{ code?: string; msg?: string; at?: string }>) ?? [];
    for (const item of hard) {
      out.push({
        code: item.code ?? "hard",
        severity: "hard",
        where: item.at ?? t("finding_where_checker", lang, [row.checker]),
        selection: null,
        message: item.msg ?? "",
      });
    }
    for (const item of warn) {
      out.push({
        code: item.code ?? "warn",
        severity: "warn",
        where: item.at ?? t("finding_where_checker", lang, [row.checker]),
        selection: null,
        message: item.msg ?? "",
      });
    }
  }
  return out;
}

export function collectFindings(
  inspect: InspectResult,
  texts: RegionText[],
  lang = getState().language,
): Finding[] {
  const out: Finding[] = [];

  for (const region of inspect.regions.regions) {
    if (region.kind !== "cell" || region.table === undefined) continue;
    const where = t("finding_where_cell", lang, [
      region.table,
      region.row ?? 0,
      region.col ?? 0,
    ]);
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
        message: t("finding_color_anomaly", lang),
      });
    }
    if (region.scriptAnomaly) {
      out.push({
        code: "fill_charpr_script_anomaly",
        severity: "warn",
        where,
        selection,
        message: t("finding_script_anomaly", lang, [
          region.charPr ?? "",
          region.charPrSuggested ?? "",
        ]),
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
          ? t("finding_where_cell_run", lang, [
              region.table ?? 0,
              region.addr!.row,
              region.addr!.col,
              run.index,
            ])
          : t("finding_where_para_run", lang, [region.at_para ?? 0, run.index]),
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
        message: t("finding_run_color_anomaly", lang, [
          run.color_value ?? t("finding_color_unknown", lang),
          trimRun(run.text),
        ]),
      });
    }
  }

  for (const target of inspect.summary.scriptAnomalyTargets) {
    const where = t("finding_where_cell", lang, [
      target.table,
      target.addr.row,
      target.addr.col,
    ]);
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
      message: t("finding_script_anomaly_target", lang, [
        target.differing.join(", "),
        target.charpr,
        target.charpr_suggested,
      ]),
    });
  }

  if (out.length === 0) {
    out.push({
      code: "clean",
      severity: "info",
      where: t("finding_where_document", lang),
      selection: null,
      message: t("finding_clean_notice", lang),
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

  const lang = state.language;
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
    label = t("finding_where_cell", lang, [
      selection.table,
      selection.row,
      selection.col,
    ]);
  } else if (selection.kind === "paragraph") {
    text =
      inspect?.graph.paragraphs.find((p) => p.at_para === selection.atPara)?.text ?? null;
    label = t("addr_paragraph", lang, [selection.atPara]);
  }

  if (text === null || text.length === 0) {
    showToast(t("toast_nothing_to_copy", lang), 1400);
    return true;
  }
  await writeClipboard(text);
  showToast(t("toast_copied_label", lang, [label]), 1400);
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
    if (rt.isTauri()) {
      await getCurrentWebview().setZoom(clamped);
    } else if (typeof document !== "undefined") {
      document.documentElement.style.zoom = clamped === 1 ? "" : String(clamped);
    }
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
  setState({ phase: "starting", phaseNote: t("splash_loading", getState().language), fatal: null });
  applyStoredTheme();
  applyStoredLanguage();
  try {
    const prefs = await rt.loadPrefs();
    if (prefs.theme === "light" || prefs.theme === "dark" || prefs.theme === "auto") {
      setState({ theme: prefs.theme });
      applyThemeToDom(prefs.theme);
    }
    if (prefs.language === "ko" || prefs.language === "en") {
      setState({ language: prefs.language });
      applyLanguageToDom(prefs.language);
    }
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
    if (prefs.drafts && typeof prefs.drafts === "object" && !Array.isArray(prefs.drafts)) {
      setState({ savedDrafts: prefs.drafts as WorkspaceState["savedDrafts"] });
    }
    // Returned changes survive a reload (S-WP0 finding 8).
    if (prefs.returned !== undefined) setState({ returnedOps: returnedFromPrefs(prefs.returned) });

    const { status } = await rt.start(root);
    setState({
      status,
      root: status.root ?? root,
      phaseNote: t("boot_checking_capabilities", getState().language),
    });

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
    if (getState().corpusFiles.length === 0) {
      await loadCorpusFiles();
    }
    setState({ phaseNote: t("boot_finding_open_docs", getState().language) });
    await refreshSessions();

    const remembered = prefs.lastSessionId as string | undefined;
    const sessions = getState().sessions;
    const target =
      (remembered && sessions.find((s) => s.sessionId === remembered)?.sessionId) ??
      sessions[0]?.sessionId;

    setState({ view: prefs.lastView === "agent" ? "agent" : "document" });

    if (target) {
      setState({ phaseNote: t("boot_reloading_doc", getState().language) });
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
  setState({
    phase: "starting",
    phaseNote: t("boot_restarting_runtime", getState().language),
    fatal: null,
  });
  try {
    const { status } = await rt.start(getState().root);
    // The old subscription died with the old process; it is not resumable and
    // pretending otherwise would leave the timeline silently frozen.
    forgetDocumentEvents();
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

/**
 * The developer setting that lets the bundled test agent run.
 *
 * Stored in prefs, which the browser bridge reads on every agent run; the
 * status is re-read so the request box and Settings agree immediately.
 */
export async function setDevMockAgent(on: boolean): Promise<void> {
  await rt.savePrefs({ devMockAgent: on ? true : null }).catch(() => undefined);
  await refreshAgentHost();
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
        message: t("err_credential_name_missing", getState().language),
      },
    });
    return false;
  }
  try {
    await rt.credentialSet(key, secret);
    await refreshCredential();
    // The config's credential member appears only once a key really exists.
    await saveProviderSettings(getState().provider);
    showToast(t("toast_credential_stored", getState().language));
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
            message: t("err_agent_host_exit", state.language, [outcome.exitCode]),
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
  owner: DraftOwner = captureDraftOwner(),
): Promise<{ plan: OperationPlan; validation: PlanValidation } | null> {
  const fence = captureDraftFence(owner);
  if (!ownsDraftFence(fence)) return null;
  const authoritative = await rt.getPlan(planId);
  const validation = await rt.validatePlan(planId);
  if (!ownsDraftFence(fence)) return null;
  if (!ownsDraft(owner)) return null;
  const inspect = getState().inspects[sessionId] ?? null;
  const texts = getState().texts[sessionId] ?? [];
  const addresses = agentPlanCellAddresses(authoritative);
  let beforeCell = (table: number, row: number, col: number) =>
    seatText(inspect, texts, table, row, col);
  let baseCellRegions: RegionText[] = texts;

  // A chained plan is bound to candidate bytes, not the session source cached
  // in `inspect`/`texts`. Read the exact parent so an overwrite review does not
  // show stale source text as the value it will replace.
  if (authoritative.base) {
    const answer = await rt.readRegion(sessionId, addresses, authoritative.base.runId);
    baseCellRegions = answer.regions;
    beforeCell = (table, row, col) => {
      const before = regionTextAt(answer.regions, { table, row, col });
      if (before === null) {
        const lang = getState().language ?? "ko";
        throw {
          code: "agent_plan_before_unreadable",
          message: t("err_agent_plan_before_unreadable", lang),
          data: { planId, runId: authoritative.base?.runId, table, row, col },
        };
      }
      return before;
    };
  }
  const hasMultiOpContext = authoritative.ops.some(
    (op) =>
      op.kind === "set_run" ||
      op.kind === "replace_at_cell" ||
      op.kind === "delete_guides",
  );
  let ops: QueuedOp[];
  if (hasMultiOpContext) {
    const paraAddresses = authoritative.ops
      .filter((op) => op.kind === "set_run" && Number.isFinite(Number(op.params?.atPara)))
      .map((op) => ({ atPara: Number(op.params.atPara) }));
    const paraAnswer =
      paraAddresses.length > 0
        ? await rt
            .readRegion(sessionId, paraAddresses, authoritative.base?.runId ?? null)
            .catch(() => ({ regions: [] as RegionText[] }))
        : { regions: [] as RegionText[] };
    const beforeParaRun = (atPara: number, run: number): string => {
      const match =
        paraAnswer.regions.find((r) => r.at_para === atPara) ??
        texts.find((r) => r.at_para === atPara);
      const runMatch = match?.runs?.find((r) => r.index === run);
      return runMatch?.text ?? match?.text ?? "";
    };
    const beforeCellRun = (table: number, row: number, col: number, run?: number): string => {
      const match = baseCellRegions.find(
        (r) =>
          (r.table ?? 0) === table &&
          r.addr?.row === row &&
          r.addr?.col === col,
      );
      if (run !== undefined && match?.runs) {
        const hit = match.runs.find((r) => r.index === run);
        if (hit) return hit.text;
      }
      return match?.text ?? beforeCell(table, row, col);
    };
    const guideSummary = (): string => {
      const lang = getState().language ?? "ko";
      const guideCells =
        inspect?.graph.tables.flatMap((t) =>
          t.cells.filter((c) => c.classification === "guide"),
        ) ?? [];
      if (guideCells.length === 0) return t("agent_guide_summary_empty", lang);
      const preview = guideCells
        .map((c) => c.textPreview?.trim())
        .filter(Boolean)
        .slice(0, 2)
        .join(" / ");
      return preview
        ? t("agent_guide_summary_preview", lang, [guideCells.length, preview])
        : t("agent_guide_summary_count", lang, [guideCells.length]);
    };
    ops = projectAgentPlan(authoritative, beforeCell, {
      beforeParaRun,
      beforeCellRun,
      guideSummary,
    }) as QueuedOp[];
  } else {
    ops = projectAgentPlan(authoritative, beforeCell) as QueuedOp[];
  }
  // A bundled test agent's ops say so on every surface that shows them. The
  // runtime's provenance decides it — set from the launched provider's
  // identity — never the proposer name, which any caller can write.
  const fromTestAgent = authoritative.provenance === "mock";
  if (fromTestAgent) {
    ops = ops.map((op) => ({ ...op, provenance: "mock" as const }));
  }
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
  const approval = approvalId ? await rt.getApproval(approvalId).catch(() => null) : null;
  if (!ownsDraftFence(fence)) return null;
  if (!ownsDraft(owner)) return null;
  setState({
    draft,
    approval,
    approvalPhase: approvalId ? "pending" : "idle",
    approvalError: null,
    applyPhase: "idle",
    applyError: null,
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
  const owner = captureDraftOwner();

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
      const adopted = await adoptAgentPlan(
        sessionId,
        planId,
        payload.approval?.approvalId ?? null,
        owner,
      );
      if (adopted) patchTurn(id, { planId });
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
      error: {
        code: "cancelled",
        message: t("err_agent_cancelled", getState().language),
      },
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
    showToast(t("toast_open_doc_before_check", getState().language), 1600);
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
  if (state.commandPaletteOpen) {
    setState({ commandPaletteOpen: false });
    return true;
  }
  if (state.returnPopoverOpen) {
    setState({ returnPopoverOpen: false });
    return true;
  }
  if (state.inlineEdit) {
    cancelEdit();
    return true;
  }
  if (state.approvalDialogOpen) {
    setState({ approvalDialogOpen: false });
    return true;
  }
  if (state.operatorModalOpen) {
    setState({ operatorModalOpen: false });
    return true;
  }
  if (state.openDialogOpen) {
    setState({ openDialogOpen: false });
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

// --- Run 1 shell navigation, language & overlay helpers --------------------

const LANGUAGE_STORAGE_KEY = "rigorloom:language";

export function applyLanguageToDom(language: UiLanguage): void {
  if (typeof document === "undefined") return;
  document.documentElement.lang = language;
}

export function applyStoredLanguage(): void {
  let language: UiLanguage = "ko";
  try {
    const saved = window.localStorage?.getItem(LANGUAGE_STORAGE_KEY);
    if (saved === "ko" || saved === "en") {
      language = saved;
    }
  } catch {
    // ignore storage errors in restricted contexts
  }
  setState({ language });
  applyLanguageToDom(language);
}

export async function setLanguage(language: UiLanguage): Promise<void> {
  if (language !== "ko" && language !== "en") return;
  setState({ language });
  applyLanguageToDom(language);
  try {
    window.localStorage?.setItem(LANGUAGE_STORAGE_KEY, language);
  } catch {
    // ignore storage errors
  }
  await rt.savePrefs({ language }).catch(() => {});
  showToast(t("lang_switched_toast", language));
}

export async function toggleLanguage(): Promise<void> {
  const next: UiLanguage = getState().language === "ko" ? "en" : "ko";
  await setLanguage(next);
}

export function navigateScreen(screen: ScreenId): void {
  const state = getState();
  if ((screen === "review" || screen === "fill" || screen === "history") && !state.activeSessionId) {
    setState({ screen: "open" });
    return;
  }
  setState({
    screen,
    ...(screen === "review" || screen === "fill" || screen === "history"
      ? { view: "document" as const }
      : {}),
  });
}

/** 1-based chronological revision number for an applied candidate run in a session. */
export function revisionNumberFor(
  state: WorkspaceState,
  sessionId: string | null | undefined,
  runId: string | null | undefined,
): number | null {
  if (!sessionId || !runId) return null;
  const rows = (state.candidates[sessionId] ?? [])
    .filter((c) => Boolean(c.runId))
    .slice()
    .sort((a, b) => (a.createdUtc ?? "").localeCompare(b.createdUtc ?? ""));
  const idx = rows.findIndex((c) => c.runId === runId);
  if (idx >= 0) return idx + 1;
  if (state.applied?.sessionId === sessionId && state.applied.runId === runId) {
    return rows.length + 1;
  }
  return rows.length > 0 ? rows.length : 1;
}

/** True while any session has an uncommitted draft, active plan in review, or apply in flight. */
export function isWorkspaceFolderLocked(state: WorkspaceState): boolean {
  if (state.inlineEdit !== null) return true;
  if (state.draft.ops.length > 0 || state.draft.plan !== null) return true;
  if (state.draft.phase === "starting") return true;
  if (
    state.approval !== null ||
    state.approvalPhase === "requesting" ||
    state.approvalPhase === "pending" ||
    state.approvalPhase === "resolving"
  ) {
    return true;
  }
  if (state.applyPhase === "starting") return true;
  if (state.activeTurn !== null) return true;
  if (hasLiveUnappliedPlanInEvents(state.events)) return true;
  return Object.values(state.applyOutcomes).some(
    (outcome) => outcome?.recovery?.outcome === "unknown",
  );
}

/**
 * Switch the active runtime workspace root atomically (`rt.start(nextRoot)` first).
 * If starting fails or folder lock holds, rolls back / retains the previous root.
 */
export async function switchWorkspaceRoot(
  nextRoot: string,
): Promise<{ ok: boolean; error: RuntimeError | null }> {
  const trimmed = nextRoot.trim();
  if (!trimmed) {
    return {
      ok: false,
      error: {
        code: "invalid_root",
        message: t("err_invalid_root_path", getState().language),
      },
    };
  }
  const state = getState();
  if (isWorkspaceFolderLocked(state)) {
    return {
      ok: false,
      error: {
        code: "workspace_locked",
        message: t("settings_folder_locked", state.language),
      },
    };
  }
  const prevRoot = state.root;
  if (prevRoot && trimmed === prevRoot) {
    return { ok: true, error: null };
  }
  try {
    const { status } = await rt.start(trimmed);
    if (!status?.running) {
      if (prevRoot) {
        await rt.start(prevRoot).catch(() => {});
      }
      return {
        ok: false,
        error: {
          code: "runtime_start_failed",
          message:
            status?.failure ??
            t("err_workspace_start_failed", getState().language),
        },
      };
    }
    const resolvedRoot = status.root ?? trimmed;
    stopDocumentEvents();
    bumpPlanGeneration();
    cancelDraftValidateTimer();
    await rt.savePrefs({ root: resolvedRoot, lastSessionId: null }).catch(() => {});
    setState({
      status,
      root: resolvedRoot,
      activeSessionId: null,
      sessions: [],
      inspects: {},
      texts: {},
      candidates: {},
      receipts: {},
      applied: null,
      applyPhase: "idle",
      applyError: null,
      applyOutcomes: {},
      approval: null,
      approvalPhase: "idle",
      approvalError: null,
      draft: EMPTY_DRAFT,
      redoStack: [],
      inlineEdit: null,
      selection: null,
      selectedChangeId: null,
      expandedChangeId: null,
      returnPopoverOpen: false,
      events: [],
      eventSubscription: null,
      head: null,
      historySelected: null,
      inverseProof: null,
      candidateVerdict: null,
      guardDiff: null,
      guardDiffError: null,
      guardDiffPhase: "idle",
      render: null,
      renderPhase: "idle",
      renderError: null,
      geometry: null,
    });
    const [caps] = await Promise.all([
      rt.capabilities().catch(() => null),
      refreshSessions(),
    ]);
    if (caps) setState({ capabilities: caps });
    showToast(t("settings_folder_changed", getState().language), 2200);
    return { ok: true, error: null };
  } catch (e) {
    if (prevRoot) {
      const rollback = await rt.start(prevRoot).catch(() => null);
      if (rollback?.status) {
        setState({ status: rollback.status, root: prevRoot });
      }
    }
    return { ok: false, error: rt.asRuntimeError(e) };
  }
}

export async function loadInitialPrefs(): Promise<void> {
  try {
    const prefs = await rt.loadPrefs();
    if (prefs.theme === "light" || prefs.theme === "dark" || prefs.theme === "auto") {
      setState({ theme: prefs.theme });
      applyThemeToDom(prefs.theme);
    }
    if (prefs.language === "ko" || prefs.language === "en") {
      setState({ language: prefs.language });
      applyLanguageToDom(prefs.language);
    }
  } catch {
    // prefs load failure keeps in-memory defaults
  }
}

export function openCommandPalette(): void {
  setState({ commandPaletteOpen: true });
}

export function closeCommandPalette(): void {
  setState({ commandPaletteOpen: false });
}

export function toggleCommandPalette(): void {
  setState({ commandPaletteOpen: !getState().commandPaletteOpen });
}

export function openOperatorModal(): void {
  setState({ operatorModalOpen: true });
}

export function closeOperatorModal(): void {
  setState({ operatorModalOpen: false });
}

export function setReturnPopoverOpen(open: boolean): void {
  setState({ returnPopoverOpen: open });
}

export function setSelectedChangeId(id: string | null): void {
  setState({ selectedChangeId: id });
}

export function setExpandedChangeId(id: string | null): void {
  setState({ expandedChangeId: id });
}

export function togglePrintView(explicit?: boolean): void {
  const next = explicit ?? !getState().printViewEnabled;
  setState({ printViewEnabled: next });
}

export function setMobileReviewPane(pane: "sheet" | "list"): void {
  setState({ mobileReviewPane: pane });
}

let inFlightExternalAdopt: {
  sessionId: string;
  planId: string;
  pendingApprovalId: string | null;
  promise: Promise<{ plan: OperationPlan; validation: PlanValidation } | null>;
} | null = null;

/** Attach an external approval record to the currently adopted draft without replacing `draft`. */
export async function attachExternalApproval(
  sessionId: string,
  planId: string,
  approvalId: string,
): Promise<ApprovalRecord | null> {
  const initial = getState();
  if (
    initial.activeSessionId !== sessionId ||
    initial.draft.sessionId !== sessionId ||
    initial.draft.plan?.planId !== planId
  ) {
    return null;
  }
  const capturedDraft = initial.draft;
  const record = await rt.getApproval(approvalId).catch(() => null);
  if (!record || record.planId !== planId) return null;
  const current = getState();
  if (
    current.activeSessionId !== sessionId ||
    current.draft !== capturedDraft ||
    current.draft.plan?.planId !== planId ||
    current.draft.plan.planHash !== record.planHash
  ) {
    return null;
  }
  if (current.approval?.approvalId === record.approvalId) {
    return current.approval;
  }
  setState({
    approval: record,
    approvalPhase: record.state === "pending" ? "pending" : "resolved",
    approvalError: null,
  });
  return record;
}

export async function adoptExternalPlan(
  sessionId: string,
  planId: string,
  approvalId?: string | null,
): Promise<{ plan: OperationPlan; validation: PlanValidation } | null> {
  const normalizedApprovalId = approvalId ?? null;
  if (
    inFlightExternalAdopt &&
    inFlightExternalAdopt.sessionId === sessionId &&
    inFlightExternalAdopt.planId === planId
  ) {
    if (normalizedApprovalId) {
      inFlightExternalAdopt.pendingApprovalId = normalizedApprovalId;
    }
    return inFlightExternalAdopt.promise;
  }

  const owner = captureDraftOwner();
  const entry = {
    sessionId,
    planId,
    pendingApprovalId: normalizedApprovalId,
    promise: Promise.resolve(null) as Promise<{
      plan: OperationPlan;
      validation: PlanValidation;
    } | null>,
  };
  const run = (async () => {
    try {
      const adopted = await adoptAgentPlan(sessionId, planId, normalizedApprovalId, owner);
      const attachId = entry.pendingApprovalId;
      if (
        adopted &&
        attachId &&
        getState().draft.plan?.planId === planId &&
        getState().approval?.approvalId !== attachId
      ) {
        await attachExternalApproval(sessionId, planId, attachId);
      }
      return adopted;
    } finally {
      if (inFlightExternalAdopt === entry) {
        inFlightExternalAdopt = null;
      }
    }
  })();
  entry.promise = run;
  inFlightExternalAdopt = entry;
  return run;
}


/**
 * The webview's view of the Runtime. Thin on purpose.
 *
 * All protocol I/O is in Rust (`src-tauri/src/sidecar.rs`) — spike finding 2.
 * This module does not frame, correlate or tail anything; it invokes commands
 * and subscribes to the batched activity channel.
 */
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

import type {
  Activity,
  AppliedCandidate,
  ApprovalRecord,
  Candidate,
  Capabilities,
  EventDelivery,
  InspectResult,
  OperationPlan,
  PlanValidation,
  PrepareResult,
  Receipt,
  RegionText,
  RenderResult,
  RuntimeError,
  Session,
  SidecarStatus,
} from "./types";

export const EVENT_ACTIVITY = "runtime://activity";
export const EVENT_STATUS = "runtime://status";
export const EVENT_PANIC = "runtime://panic";
/**
 * The session's own event log, split out from general activity in Rust.
 *
 * A separate channel rather than filtering in the webview, for the reason the
 * spike measured: emitting per line costs 1.1 MiB/s against 7.0 MiB/s for
 * counting in Rust and emitting arrays. Splitting there keeps both channels
 * batched and keeps protocol chatter out of the document's own history.
 */
export const EVENT_EVENTS = "runtime://events";

/** Normalise anything thrown across IPC into a RuntimeError. */
export function asRuntimeError(value: unknown): RuntimeError {
  if (value && typeof value === "object" && "code" in value) {
    return value as RuntimeError;
  }
  return { code: "shell_error", message: String(value) };
}

export async function start(root?: string | null): Promise<{
  handshake: unknown;
  status: SidecarStatus;
}> {
  return invoke("runtime_start", { root: root ?? null });
}

export async function stop(): Promise<void> {
  return invoke("runtime_stop");
}

export async function status(): Promise<SidecarStatus> {
  return invoke("runtime_status");
}

export async function call<T = unknown>(
  method: string,
  params?: Record<string, unknown>,
): Promise<T> {
  return invoke<T>("runtime_call", { method, params: params ?? null, tag: null });
}

/**
 * A call that can be cancelled while it is still in flight.
 *
 * The protocol's cancel is a FRAME, not a method — `{"kind":"cancel","id":…}`,
 * no response, acted on by the reader thread while the request is still
 * running (§9). The webview never sees the request id, so it hands Rust a tag
 * and cancels by tag. Cancellation is cooperative between ops
 * (`rt_server._checkpoint`): the op in flight finishes, the next one does not
 * start, and `rt_apply` removes the run directory — so a cancelled apply
 * leaves no half-written candidate.
 */
export async function callCancellable<T = unknown>(
  method: string,
  params: Record<string, unknown>,
  tag: string,
): Promise<T> {
  return invoke<T>("runtime_call", { method, params, tag });
}

export const cancel = (tag: string) => invoke<boolean>("runtime_cancel", { tag });

// --- the methods this phase uses --------------------------------------------
// Phase 4 opens the mutation path. The Desktop runs on the HOST entry, which
// is what makes `approval/resolve` reachable here and nowhere else: an agent
// connection does not have the method at all (§4), so "the agent cannot
// approve" is registry membership, not a policy this shell enforces.

export const capabilities = (probeRenderers = false) =>
  call<Capabilities>(
    "capabilities/list",
    probeRenderers ? { probeRenderers: true } : undefined,
  );

export const sessions = () =>
  call<{ sessions: Session[] }>("session/list").then((r) => r.sessions);

export const openPath = (path: string) =>
  call<{ sessionId: string; openedUtc: string; source: Session["source"] }>(
    "workspace/openPath",
    { path },
  );

export const inspect = (sessionId: string) =>
  call<InspectResult>("document/inspect", { sessionId });

/**
 * Full text for a set of addresses, with per-run charPr and colour facts.
 *
 * Bounded at 256 KiB server-side, and the runtime **refuses rather than
 * truncates** (`region_too_large`) — callers chunk.
 */
export const readRegion = (
  sessionId: string,
  regions: Array<{ table?: number; row?: number; col?: number; atPara?: number }>,
) =>
  call<{ sessionId: string; documentHash: string; regions: RegionText[] }>(
    "document/readRegion",
    { sessionId, regions },
  );

export const candidates = (sessionId: string) =>
  call<{ sessionId: string; candidates: Candidate[] }>("candidate/list", {
    sessionId,
  }).then((r) => r.candidates);

// --- the mutation path -------------------------------------------------------

export const proposePlan = (
  sessionId: string,
  ops: Array<Record<string, unknown>>,
  proposer = "rigorloom-desktop",
) =>
  call<{ plan: OperationPlan }>("plan/propose", {
    sessionId,
    backend: "preedit",
    ops,
    proposer,
  }).then((r) => r.plan);

export const validatePlan = (planId: string) =>
  call<{ validation: PlanValidation }>("plan/validate", { planId }).then(
    (r) => r.validation,
  );

export const getPlan = (planId: string) =>
  call<{ plan: OperationPlan }>("plan/get", { planId }).then((r) => r.plan);

export const requestApproval = (planId: string, requestedBy = "rigorloom-desktop") =>
  call<{ approval: ApprovalRecord }>("approval/request", {
    planId,
    requestedBy,
  }).then((r) => r.approval);

export const getApproval = (approvalId: string) =>
  call<{ approval: ApprovalRecord }>("approval/get", { approvalId }).then(
    (r) => r.approval,
  );

/**
 * HOST ONLY, and the whole point of the vermilion moment.
 *
 * The decision binds an exact `planId` AND `planHash`; `resolve_approval`
 * refuses anything else, so a person cannot approve one plan and have another
 * applied. The shell passes both back verbatim from the record it displayed.
 */
export const resolveApproval = (
  approvalId: string,
  planId: string,
  planHash: string,
  decision: "approved" | "rejected",
  approver: string,
) =>
  call<{ approval: ApprovalRecord }>("approval/resolve", {
    approvalId,
    planId,
    planHash,
    decision,
    approver,
  }).then((r) => r.approval);

/** HOST ONLY. Cancellable between ops; see `callCancellable`. */
export const applyPlan = (planId: string, approvalId: string, tag: string) =>
  callCancellable<{ candidate: AppliedCandidate }>(
    "plan/apply",
    { planId, approvalId },
    tag,
  ).then((r) => r.candidate);

export const readReceipt = (sessionId: string, runId: string) =>
  call<{ receipt: Receipt }>("receipt/read", { sessionId, runId }).then(
    (r) => r.receipt,
  );

// --- rendering ---------------------------------------------------------------

export const renderPage = (
  sessionId: string,
  page: number,
  dpi: number,
  runId?: string | null,
) =>
  call<RenderResult>("document/render", {
    sessionId,
    page,
    dpi,
    ...(runId ? { runId } : {}),
  });

/** HOST ONLY. Starts Hancom on the operator's machine, or refuses saying why. */
export const renderPrepare = (sessionId: string) =>
  call<PrepareResult>("document/renderPrepare", { sessionId });

// --- events ------------------------------------------------------------------

export const subscribeEvents = (sessionId: string, after = -1, intervalMs = 250) =>
  call<{ subscriptionId: string; sessionId: string; after: number; intervalMs: number }>(
    "event/subscribe",
    { sessionId, after, intervalMs },
  );

export const unsubscribeEvents = (subscriptionId: string) =>
  call<{ subscriptionId: string; stopped: boolean }>("event/unsubscribe", {
    subscriptionId,
  });

// --- host-side file work the protocol does not do ----------------------------
// `artifact/exportTo` is GAP (§11.5), so writing a candidate outside the
// workspace is the shell's job. It is done in Rust, against a path the user
// chose in a native dialog, and the copy is hashed on the way out so the UI can
// assert the bytes that left equal the bytes the receipt bound.

export const exportCandidate = (
  sessionId: string,
  runId: string,
  candidatePath: string,
  destination: string,
) =>
  invoke<{ path: string; sha256: string; bytes: number; receiptPath: string }>(
    "export_candidate",
    { sessionId, runId, candidatePath, destination },
  );

// --- the dev-mode agent door --------------------------------------------------

export const agentToolStatus = () =>
  invoke<{ available: boolean; script: string | null; reason: string }>("agent_tool_status");

export const runMockAgent = (sessionId: string, marker: string) =>
  invoke<{ exitCode: number; stdout: string; stderr: string }>("run_mock_agent", {
    sessionId,
    marker,
  });

// --- preferences -------------------------------------------------------------

export const loadPrefs = () => invoke<Record<string, unknown>>("prefs_load");
export const savePrefs = (patch: Record<string, unknown>) =>
  invoke<Record<string, unknown>>("prefs_save", { patch });
export const defaultRoot = () => invoke<string>("default_runtime_root");

// --- scripted evidence -------------------------------------------------------
// The launcher's intent, read from the environment on the Rust side because a
// webview cannot see env vars. Absent in every normal run.

export const smokeConfig = () =>
  invoke<{ phase: string | null; corpus: string | null; reportPath: string | null }>(
    "smoke_config",
  );

export const smokeFinish = (report: unknown) => invoke<void>("smoke_finish", { report });

/** A `hold` phase saying "the UI is arranged"; the window stays open. */
export const smokeReady = (detail: unknown) => invoke<void>("smoke_ready", { detail });

// --- subscriptions -----------------------------------------------------------

export function onActivity(handler: (batch: Activity[]) => void): Promise<UnlistenFn> {
  return listen<Activity[]>(EVENT_ACTIVITY, (e) => handler(e.payload));
}

/** Batched `event` notifications from every live subscription. */
export function onEvents(handler: (batch: EventDelivery[]) => void): Promise<UnlistenFn> {
  return listen<EventDelivery[]>(EVENT_EVENTS, (e) => handler(e.payload));
}

export function onStatus(handler: (s: SidecarStatus) => void): Promise<UnlistenFn> {
  return listen<SidecarStatus>(EVENT_STATUS, (e) => handler(e.payload));
}

export function onPanic(
  handler: (p: { location: string; message: string; logPath: string }) => void,
): Promise<UnlistenFn> {
  return listen<{ location: string; message: string; logPath: string }>(
    EVENT_PANIC,
    (e) => handler(e.payload),
  );
}

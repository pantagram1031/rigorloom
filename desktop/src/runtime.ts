/**
 * The webview's view of the Runtime. Thin on purpose.
 *
 * All protocol I/O is in Rust (`src-tauri/src/sidecar.rs`) — spike finding 2.
 * This module does not frame, correlate or tail anything; it invokes commands
 * and subscribes to the batched activity channel.
 */
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { t } from "./i18n/vocabulary";

import type {
  Activity,
  AgentHostStatus,
  AppliedCandidate,
  ApprovalRecord,
  Candidate,
  CandidateCompare,
  Capabilities,
  CorpusFileEntry,
  CredentialStatus,
  EventDelivery,
  ExportResult,
  GeometryResult,
  GuardDiffResult,
  HostEvent,
  HostRunPayload,
  InspectResult,
  ModuleCheckReport,
  ModuleList,
  OpenUploadResult,
  OperationPlan,
  PipelineGateResolveResult,
  PipelineGatesResult,
  PlanValidation,
  PrepareResult,
  ProviderProfile,
  Receipt,
  RegionText,
  RenderResult,
  RuntimeError,
  Session,
  SidecarStatus,
  TaskPackList,
  UiLanguage,
} from "./types";

function currentUiLanguage(): UiLanguage {
  return typeof document !== "undefined" && document.documentElement.lang === "en"
    ? "en"
    : "ko";
}

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

/**
 * The Agent Host's own event log, live while a turn is still running.
 *
 * A third channel rather than a filter on the second, for the same reason the
 * second exists: these are the PROVIDER's events (`provider.request`,
 * `tool.refused`, `runtime.result`), not the document's, and mixing them into
 * `events.jsonl`'s history would make the document's own record untrue.
 * Batched in Rust; see `src-tauri/src/agenthost.rs`.
 */
export const EVENT_AGENT = "agenthost://events";

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export function browserToken(): string {
  if (typeof window === "undefined") return "";
  const injected = (window as { __RIGORLOOM_UI__?: { token?: unknown } }).__RIGORLOOM_UI__
    ?.token;
  if (typeof injected === "string" && injected.length > 0) return injected;
  try {
    const param = new URLSearchParams(window.location.search).get("token");
    if (param) return param;
  } catch {
    // Ignore malformed query strings.
  }
  return "";
}

export function appendTokenQuery(url: string): string {
  const token = browserToken();
  if (!token || url.includes("token=")) return url;
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}token=${encodeURIComponent(token)}`;
}

export function tokenHeaders(extra?: Record<string, string>): Record<string, string> {
  const token = browserToken();
  return {
    ...(token ? { "X-Rigorloom-Token": token } : {}),
    ...(extra ?? {}),
  };
}

async function parseHttpJson<T>(res: Response): Promise<T> {
  const text = await res.text();
  let body: unknown = null;
  if (text.trim().length > 0) {
    try {
      body = JSON.parse(text);
    } catch {
      if (!res.ok) {
        throw { code: "http_error", message: text || `HTTP ${res.status}` };
      }
      throw { code: "invalid_json", message: t("err_invalid_json", currentUiLanguage()) };
    }
  }
  if (!res.ok) {
    if (body && typeof body === "object") {
      const rec = body as { error?: unknown; code?: unknown; message?: unknown };
      if (rec.error && typeof rec.error === "object") throw rec.error;
      if (typeof rec.code === "string") throw rec;
      if (typeof rec.message === "string") {
        throw { code: "http_error", message: rec.message, data: { status: res.status } };
      }
    }
    throw { code: "http_error", message: `HTTP ${res.status}`, data: { status: res.status } };
  }
  if (body && typeof body === "object") {
    const rec = body as { ok?: unknown; error?: unknown };
    if (rec.ok === false && rec.error && typeof rec.error === "object") {
      throw rec.error;
    }
  }
  return body as T;
}

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path, {
    method: "GET",
    headers: tokenHeaders(),
  });
  return parseHttpJson<T>(res);
}

async function apiPost<T>(path: string, payload: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: tokenHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload ?? {}),
  });
  return parseHttpJson<T>(res);
}

async function rpcCall<T>(
  method: string,
  params?: Record<string, unknown> | null,
  tag?: string | null,
): Promise<T> {
  const envelope = await apiPost<{
    ok: boolean;
    result?: T;
    error?: RuntimeError;
  }>("/rpc", {
    method,
    params: params ?? null,
    tag: tag ?? null,
  });
  if (!envelope || envelope.ok !== true) {
    throw envelope?.error ?? {
      code: "rpc_error",
      message: t("err_rpc_failed", currentUiLanguage(), [method]),
    };
  }
  return envelope.result as T;
}

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
  if (!isTauri()) {
    return apiPost("/api/runtime/start", { root: root ?? null });
  }
  return invoke("runtime_start", { root: root ?? null });
}

export async function stop(): Promise<void> {
  if (!isTauri()) {
    await apiPost("/api/runtime/stop", {});
    return;
  }
  return invoke("runtime_stop");
}

export async function status(): Promise<SidecarStatus> {
  if (!isTauri()) {
    return apiGet<SidecarStatus>("/api/runtime/status");
  }
  return invoke("runtime_status");
}

export async function call<T = unknown>(
  method: string,
  params?: Record<string, unknown>,
): Promise<T> {
  if (!isTauri()) {
    return rpcCall<T>(method, params ?? null, null);
  }
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
  if (!isTauri()) {
    return rpcCall<T>(method, params, tag);
  }
  return invoke<T>("runtime_call", { method, params, tag });
}

export const cancel = (tag: string): Promise<boolean> => {
  if (!isTauri()) {
    return apiPost<{ cancelled: boolean }>("/api/runtime/cancel", { tag }).then((r) =>
      Boolean(r.cancelled),
    );
  }
  return invoke<boolean>("runtime_cancel", { tag });
};

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
  runId?: string | null,
) =>
  call<{
    sessionId: string;
    documentHash: string;
    /** Which document answered. Stated on every read, source included (§15.3). */
    subject: { kind: string; runId?: string; sha256: string };
    regions: RegionText[];
  }>("document/readRegion", { sessionId, regions, ...(runId ? { runId } : {}) });

export const candidates = (sessionId: string) =>
  call<{ sessionId: string; candidates: Candidate[] }>("candidate/list", {
    sessionId,
  }).then((r) => r.candidates);

/**
 * Compare a candidate with another candidate or the source (§15.4).
 *
 * The proof half of undo, and it is deliberately a RUNTIME call: a shell that
 * compared two strings it had fetched would be comparing its own memory. Both
 * sides here are re-read by the runtime from bytes their receipts re-verified.
 */
export const compareCandidate = (
  sessionId: string,
  runId: string,
  against: { runId: string } | { source: true },
  regions?: Array<{ table?: number; row?: number; col?: number; atPara?: number }>,
) =>
  call<CandidateCompare>("candidate/compare", {
    sessionId,
    runId,
    against,
    ...(regions && regions.length > 0 ? { regions } : {}),
  });

// --- the mutation path -------------------------------------------------------

/**
 * Build a plan. `baseRunId` is what makes an edit the NEXT one rather than a
 * second first one (§15.2): without it the plan starts from the session source
 * and the candidate it produces does not carry earlier edits. `reverses`
 * declares which candidate this plan undoes, and the receipt records it.
 */
export const proposePlan = (
  sessionId: string,
  ops: Array<Record<string, unknown>>,
  options: { baseRunId?: string | null; reverses?: string | null; replaces?: string | null } = {},
  proposer = "rigorloom-desktop",
) =>
  call<{ plan: OperationPlan }>("plan/propose", {
    sessionId,
    backend: "preedit",
    ops,
    proposer,
    ...(options.baseRunId ? { baseRunId: options.baseRunId } : {}),
    ...(options.reverses ? { reverses: { runId: options.reverses } } : {}),
    // An explicit replacement: the runtime revokes the replaced plan's open
    // approval in the same step (superseded_by_newer_candidate).
    ...(options.replaces ? { replaces: options.replaces } : {}),
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
  reason: string | null = null,
) =>
  call<{ approval: ApprovalRecord }>("approval/resolve", {
    approvalId,
    planId,
    planHash,
    decision,
    approver,
    // The person's words when returning. Its own field, never the approver.
    ...(reason ? { reason } : {}),
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

/**
 * HOST ONLY. Starts Hancom on the operator's machine, or refuses saying why.
 *
 * With a `runId` it converts that CANDIDATE rather than the source — the only
 * honest way to show the page a candidate draws, and the reason E1.2's
 * 다시 그리기 has anywhere to go. Whether this machine can is a separate
 * question, and its answer is the refusal.
 */
export const renderPrepare = (sessionId: string, runId?: string | null) =>
  call<PrepareResult>("document/renderPrepare", {
    sessionId,
    ...(runId ? { runId } : {}),
  });

/**
 * Where the text is on the page, and what each line is addressable as (§12).
 *
 * Zero-based `page`, like `document/render`. Agent-safe, and deliberately NOT
 * folded into the render result: the rects are normalized fractions and are the
 * same at every dpi, so re-asking on a zoom change would re-extract every glyph
 * position for an answer that did not change. The store caches accordingly.
 */
export const pageGeometry = (sessionId: string, page: number, runId?: string | null) =>
  call<GeometryResult>("document/pageGeometry", {
    sessionId,
    page,
    ...(runId ? { runId } : {}),
  });

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
  destination: string | null,
): Promise<ExportResult> => {
  if (!isTauri()) {
    return apiPost<ExportResult>("/api/export", {
      sessionId,
      runId,
      candidatePath,
      destination,
    });
  }
  return invoke<ExportResult>("export_candidate", {
    sessionId,
    runId,
    candidatePath,
    destination: destination ?? "",
  });
};

// --- WP3 browser corpus / upload / guard diff / pipeline gate APIs ----------

export const corpusFiles = (): Promise<CorpusFileEntry[]> =>
  apiGet<{ files: CorpusFileEntry[] }>("/api/corpus-files").then((r) => r.files ?? []);

export const openUpload = (
  filename: string,
  bytesBase64: string,
): Promise<OpenUploadResult> =>
  apiPost<OpenUploadResult>("/api/open-upload", { filename, bytesBase64 });

export const guardDiff = (params: {
  sessionId?: string | null;
  runId?: string | null;
  againstRunId?: string | null;
  planId?: string | null;
  beforeText?: string;
  afterText?: string;
}): Promise<GuardDiffResult> => apiPost<GuardDiffResult>("/api/guard/diff", params);

export const pipelineGates = (workspace: string): Promise<PipelineGatesResult> =>
  apiGet<PipelineGatesResult>(
    `/api/pipeline/gates?workspace=${encodeURIComponent(workspace)}`,
  );

export const resolvePipelineGate = (params: {
  workspace: string;
  gate: string;
  decision: "approved" | "rejected";
  approver?: string;
  reason?: string;
}): Promise<PipelineGateResolveResult> =>
  apiPost<PipelineGateResolveResult>("/api/pipeline/gate-resolve", params);

// --- the dev-mode agent door --------------------------------------------------

export const agentToolStatus = (): Promise<{
  available: boolean;
  script: string | null;
  reason: string;
}> => {
  if (!isTauri()) return apiGet("/api/agent-tool-status");
  return invoke("agent_tool_status");
};

export const runMockAgent = (
  sessionId: string,
  marker: string,
): Promise<{ exitCode: number; stdout: string; stderr: string }> => {
  if (!isTauri()) return apiPost("/api/run-mock-agent", { sessionId, marker });
  return invoke("run_mock_agent", {
    sessionId,
    marker,
  });
};

// --- the Agent Host (Phase 5) -------------------------------------------------
//
// The composer's other end. Everything here crosses into a SEPARATE process
// speaking `serve.py --entry agent`, which is what makes "the agent cannot
// approve" a fact about the registry rather than a promise this shell keeps:
// `approval/resolve` and `plan/apply` are not on that connection at all.
//
// No credential ever crosses this boundary. `credentialSet` is one-way — the
// value goes to the OS store and the webview never asks for it back.

export const agentHostStatus = (): Promise<AgentHostStatus> => {
  if (!isTauri()) return apiGet<AgentHostStatus>("/api/agent-host/status");
  return invoke<AgentHostStatus>("agent_host_status");
};

/** `--capabilities`. Keyless-honest: no document, no network, no key needed. */
export const agentHostCapabilities = (provider: string, storeKey?: string | null) => {
  if (!isTauri()) {
    return apiPost<{
      exitCode: number;
      payload: { ok: boolean; provider?: ProviderProfile; error?: RuntimeError };
      credentialAttached: boolean;
      stderr: string;
    }>("/api/agent-host/capabilities", { provider, storeKey: storeKey ?? null });
  }
  return invoke<{
    exitCode: number;
    payload: { ok: boolean; provider?: ProviderProfile; error?: RuntimeError };
    credentialAttached: boolean;
    stderr: string;
  }>("agent_host_capabilities", { provider, storeKey: storeKey ?? null });
};

/** Write the provider config. References only; a value is refused by name. */
export const agentHostSaveConfig = (
  provider: string,
  settings: Record<string, unknown>,
  hasCredential: boolean,
) => {
  if (!isTauri()) {
    return apiPost<{ path: string; config: Record<string, unknown> }>(
      "/api/agent-host/save-config",
      { provider, settings, hasCredential },
    );
  }
  return invoke<{ path: string; config: Record<string, unknown> }>("agent_host_save_config", {
    provider,
    settings,
    hasCredential,
  });
};

/** Read it back off disk, verbatim. The smoke asserts on what this returns. */
export const agentHostReadConfig = (provider: string) => {
  if (!isTauri()) {
    return apiGet<{ path: string; exists: boolean; config: Record<string, unknown> | null }>(
      `/api/agent-host/read-config?provider=${encodeURIComponent(provider)}`,
    );
  }
  return invoke<{ path: string; exists: boolean; config: Record<string, unknown> | null }>(
    "agent_host_read_config",
    { provider },
  );
};

export const agentHostRun = (params: {
  sessionId: string;
  instruction: string;
  provider: string;
  storeKey?: string | null;
  scenario?: string | null;
  turnId: string;
}) => {
  if (!isTauri()) {
    return apiPost<{
      exitCode: number;
      payload: HostRunPayload;
      credentialAttached: boolean;
      eventsPath: string;
      stderr: string;
      turnId: string;
    }>("/api/agent-host/run", {
      sessionId: params.sessionId,
      instruction: params.instruction,
      provider: params.provider,
      storeKey: params.storeKey ?? null,
      scenario: params.scenario ?? null,
      turnId: params.turnId,
    });
  }
  return invoke<{
    exitCode: number;
    payload: HostRunPayload;
    credentialAttached: boolean;
    eventsPath: string;
    stderr: string;
    turnId: string;
  }>("agent_host_run", {
    sessionId: params.sessionId,
    instruction: params.instruction,
    provider: params.provider,
    storeKey: params.storeKey ?? null,
    scenario: params.scenario ?? null,
    turnId: params.turnId,
  });
};

export const agentHostStop = (): Promise<boolean> => {
  if (!isTauri()) {
    return apiPost<{ stopped?: boolean } | boolean>("/api/agent-host/stop", {}).then((r) =>
      typeof r === "boolean" ? r : Boolean(r.stopped ?? true),
    );
  }
  return invoke<boolean>("agent_host_stop");
};

// --- the credential store -----------------------------------------------------
// One direction. The value goes in; only present/absent comes out.

export const credentialSet = (key: string, secret: string) => {
  if (!isTauri()) {
    return apiPost<{ key: string; state: string; bytes: number }>("/api/credential/set", {
      key,
      secret,
    });
  }
  return invoke<{ key: string; state: string; bytes: number }>("credential_set", { key, secret });
};

export const credentialStatus = (key: string) => {
  if (!isTauri()) {
    return apiGet<CredentialStatus>(
      `/api/credential/status?key=${encodeURIComponent(key)}`,
    );
  }
  return invoke<CredentialStatus>("credential_status", { key });
};

export const credentialDelete = (key: string) => {
  if (!isTauri()) {
    return apiPost<{ key: string; removed: boolean; state: string }>("/api/credential/delete", {
      key,
    });
  }
  return invoke<{ key: string; removed: boolean; state: string }>("credential_delete", { key });
};

// --- 작업 팩 --------------------------------------------------------------------

export const taskPacks = (): Promise<TaskPackList> => {
  if (!isTauri()) return apiGet<TaskPackList>("/api/task-packs");
  return invoke<TaskPackList>("task_packs");
};

/**
 * Every declared module, and what of it is runnable HERE (§13).
 *
 * The runtime's own reading of `enabled.yaml`, which is the reading that
 * governs `module/check`. `task_packs` above is a second reader of the same
 * file through a different child process; the panel prints both rather than
 * choosing, because a disagreement between them is a defect worth seeing.
 */
export const moduleList = () => call<ModuleList>("module/list");

/**
 * Run an enabled module's checkers against the open session (§13).
 *
 * Agent-safe on the wire, and read-only by construction: every checker is
 * handed a scratch COPY of the document in a directory that is deleted in a
 * `finally`, so the session copy, the published candidate and the operator's
 * original are unreachable. It decides nothing — no candidate, no plan state,
 * no approval; it appends one `module.checked` event and returns a report.
 *
 * Not cancellable by tag, deliberately: the bound is per checker and published
 * as `bounds.worstCaseSeconds`, and a half-killed pack would leave the panel
 * showing rows for checkers whose children are still running.
 */
export const moduleCheck = (
  sessionId: string,
  module: string,
  checkers?: string[] | null,
) =>
  call<ModuleCheckReport>("module/check", {
    sessionId,
    module,
    ...(checkers && checkers.length > 0 ? { checkers } : {}),
  });

// --- the window ----------------------------------------------------------------

export const toggleFullscreen = async (): Promise<boolean> => {
  if (!isTauri()) {
    if (typeof document !== "undefined" && document.fullscreenElement) {
      await document.exitFullscreen?.();
      return false;
    }
    return false;
  }
  return invoke<boolean>("toggle_fullscreen");
};

/** Read-only. The harness compares it with what the previous launch saved. */
export const windowGeometry = () => {
  if (!isTauri()) {
    return Promise.resolve(null);
  }
  return invoke<{
    width: number | null;
    height: number | null;
    x: number | null;
    y: number | null;
    maximized: boolean;
    fullscreen: boolean;
    scale: number;
  } | null>("window_geometry");
};

// --- preferences -------------------------------------------------------------

export const loadPrefs = (): Promise<Record<string, unknown>> => {
  if (!isTauri()) return apiGet<Record<string, unknown>>("/api/prefs");
  return invoke<Record<string, unknown>>("prefs_load");
};

export const savePrefs = (patch: Record<string, unknown>): Promise<Record<string, unknown>> => {
  if (!isTauri()) return apiPost<Record<string, unknown>>("/api/prefs", { patch });
  return invoke<Record<string, unknown>>("prefs_save", { patch });
};

export const defaultRoot = (): Promise<string> => {
  if (!isTauri()) {
    return apiGet<{ root: string }>("/api/default-root").then((r) => r.root);
  }
  return invoke<string>("default_runtime_root");
};

// --- scripted evidence -------------------------------------------------------
// The launcher's intent, read from the environment on the Rust side because a
// webview cannot see env vars. Absent in every normal run.

export const smokeConfig = () => {
  if (!isTauri()) {
    return Promise.resolve({
      phase: null,
      corpus: null,
      reportPath: null,
      corpus2: null,
      exportPath: null,
      imeEmpty: false,
      stagedSession: null,
    });
  }
  return invoke<{
    phase: string | null;
    corpus: string | null;
    reportPath: string | null;
    corpus2: string | null;
    exportPath: string | null;
    imeEmpty: boolean;
    /** A session already on disk with its rendered PDF; see the overlay phase. */
    stagedSession: string | null;
  }>("smoke_config");
};

export const smokeFinish = (report: unknown) => {
  if (!isTauri()) return Promise.resolve();
  return invoke<void>("smoke_finish", { report });
};

/** A `hold` phase saying "the UI is arranged"; the window stays open. */
export const smokeReady = (detail: unknown) => {
  if (!isTauri()) return Promise.resolve();
  return invoke<void>("smoke_ready", { detail });
};

/** A second report, also without exiting. The IME harness reads this one. */
export const smokeFinal = (detail: unknown) => {
  if (!isTauri()) return Promise.resolve();
  return invoke<void>("smoke_final", { detail });
};

// --- subscriptions -----------------------------------------------------------

const SSE_CHANNELS = [
  EVENT_ACTIVITY,
  EVENT_EVENTS,
  EVENT_AGENT,
  EVENT_STATUS,
  EVENT_PANIC,
] as const;

let sharedEventSource: EventSource | null = null;
const sseListeners = new Map<string, Set<(payload: unknown) => void>>();

function totalSseListeners(): number {
  let count = 0;
  for (const set of sseListeners.values()) count += set.size;
  return count;
}

function ensureSharedEventSource(): EventSource | null {
  if (isTauri() || typeof EventSource === "undefined") return null;
  if (sharedEventSource && sharedEventSource.readyState !== EventSource.CLOSED) {
    return sharedEventSource;
  }
  const url = appendTokenQuery("/events");
  const es = new EventSource(url);
  for (const channel of SSE_CHANNELS) {
    es.addEventListener(channel, (evt: MessageEvent) => {
      let payload: unknown;
      try {
        payload = JSON.parse(String(evt.data));
      } catch {
        return;
      }
      const bucket = sseListeners.get(channel);
      if (!bucket) return;
      for (const listener of [...bucket]) {
        listener(payload);
      }
    });
  }
  sharedEventSource = es;
  return es;
}

function subscribeChannel<T>(
  channel: string,
  handler: (payload: T) => void,
): Promise<UnlistenFn> {
  if (isTauri()) {
    return listen<T>(channel, (e) => handler(e.payload));
  }
  const bucket = sseListeners.get(channel) ?? new Set<(payload: unknown) => void>();
  const wrapped = (payload: unknown) => handler(payload as T);
  bucket.add(wrapped);
  sseListeners.set(channel, bucket);
  ensureSharedEventSource();
  return Promise.resolve(() => {
    const current = sseListeners.get(channel);
    current?.delete(wrapped);
    if (totalSseListeners() === 0 && sharedEventSource) {
      sharedEventSource.close();
      sharedEventSource = null;
    }
  });
}

export function onActivity(handler: (batch: Activity[]) => void): Promise<UnlistenFn> {
  return subscribeChannel<Activity[]>(EVENT_ACTIVITY, handler);
}

/** Batched `event` notifications from every live subscription. */
export function onEvents(handler: (batch: EventDelivery[]) => void): Promise<UnlistenFn> {
  return subscribeChannel<EventDelivery[]>(EVENT_EVENTS, handler);
}

/** Batched Agent Host events, tailed from the run's JSONL while it runs. */
export function onAgentEvents(
  handler: (batch: Array<{ turnId: string; event: HostEvent }>) => void,
): Promise<UnlistenFn> {
  return subscribeChannel<Array<{ turnId: string; event: HostEvent }>>(EVENT_AGENT, handler);
}

export function onStatus(handler: (s: SidecarStatus) => void): Promise<UnlistenFn> {
  return subscribeChannel<SidecarStatus>(EVENT_STATUS, handler);
};

export function onPanic(
  handler: (p: { location: string; message: string; logPath: string }) => void,
): Promise<UnlistenFn> {
  return subscribeChannel<{ location: string; message: string; logPath: string }>(
    EVENT_PANIC,
    handler,
  );
}

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
  Candidate,
  Capabilities,
  InspectResult,
  RegionText,
  RuntimeError,
  Session,
  SidecarStatus,
} from "./types";

export const EVENT_ACTIVITY = "runtime://activity";
export const EVENT_STATUS = "runtime://status";
export const EVENT_PANIC = "runtime://panic";

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
  return invoke<T>("runtime_call", { method, params: params ?? null });
}

// --- the methods this phase uses --------------------------------------------
// Read-only. `plan/*`, `approval/*` and `plan/apply` exist on the host entry
// and are deliberately not called here: Phase 3 opens and understands a
// document, it does not change one.

export const capabilities = () => call<Capabilities>("capabilities/list");

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

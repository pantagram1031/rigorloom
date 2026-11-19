/**
 * What the chrome says about a document: title, pending count, agent and
 * engine state. Read-only helpers over the workspace store.
 */
import type { WorkspaceState } from "../store";
import type { UiLanguage } from "../types";
import { getSessionDisplayTitle, pathParentFolder } from "../workspace/openHelpers.ts";
import { S } from "../i18n/v2/shell.ts";
import { plainName } from "./names.ts";

export function docTitle(s: WorkspaceState, sessionId: string): string {
  const session = s.sessions.find((x) => x.sessionId === sessionId) ?? null;
  if (!session) return S.t("shell_tab_untitled", s.language);
  return plainName(getSessionDisplayTitle(session, s.openedPaths, s.corpusFiles, s.language) || session.source.name);
}

/** Whether a title is a sample form's catalogue title rather than a file name. */
export function isSampleTitle(s: WorkspaceState, sessionId: string): boolean {
  const session = s.sessions.find((x) => x.sessionId === sessionId);
  return Boolean(session && docTitle(s, sessionId) !== session.source.name);
}

export function docFolder(s: WorkspaceState, sessionId: string): string {
  const path = s.openedPaths[sessionId];
  return path ? pathParentFolder(path) : "";
}

export { pendingCount } from "./counts.ts";

export type EngineState = "ready" | "checking" | "missing" | "stopped";

const MISSING_CODES = new Set([
  "runtime_not_found",
  "runtime_missing",
  "engine_missing",
  "engine_not_found",
  "sidecar_not_found",
  "spawn_failed",
  "python_not_found",
  "sidecar_spawn_failed",
]);

export function engineState(s: WorkspaceState): EngineState {
  if (s.fatal && MISSING_CODES.has(s.fatal.code)) return "missing";
  if (s.phase === "starting" || s.phase === "idle") return "checking";
  if (s.phase === "failed") return "missing";
  if (s.status && !s.status.running) return "stopped";
  return "ready";
}

export function engineLabel(state: EngineState, lang: UiLanguage): string {
  switch (state) {
    case "ready":
      return S.t("shell_status_engine_ready", lang);
    case "checking":
      return S.t("shell_status_engine_checking", lang);
    case "missing":
      return S.t("shell_status_engine_missing", lang);
    case "stopped":
      return S.t("shell_status_engine_stopped", lang);
  }
}

/** Agent connection words for the status bar; `attn` marks an abnormal state. */
export function agentStatus(s: WorkspaceState): { text: string; attn: boolean } {
  const lang = s.language;
  if (s.provider.provider === "mock") {
    const allowed = (s.agentHost as unknown as { mockAllowed?: boolean } | null)?.mockAllowed === true;
    return allowed
      ? { text: S.t("shell_status_agent_test", lang), attn: true }
      : { text: S.t("shell_status_agent_none", lang), attn: false };
  }
  const connected =
    Boolean(s.agentHost?.available) &&
    s.credential?.state === "present" &&
    (s.provider.provider !== "router" || s.provider.router.baseUrl.trim() !== "");
  if (!connected) return { text: S.t("shell_status_agent_none", lang), attn: false };
  const name = s.provider.provider === "anthropic" ? "Anthropic" : s.provider.router.model || s.provider.provider;
  return { text: S.t("shell_status_agent_ready", lang, [name]), attn: false };
}

/** One date format everywhere: `11월 17일 오후 1:13` (J1 defect 36). */
export function formatShellDate(iso: string, lang: UiLanguage): string {
  const ms = Date.parse(iso);
  if (!Number.isFinite(ms)) return "";
  try {
    return new Intl.DateTimeFormat(lang === "ko" ? "ko-KR" : "en-US", {
      month: lang === "ko" ? "long" : "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }).format(new Date(ms));
  } catch {
    return "";
  }
}

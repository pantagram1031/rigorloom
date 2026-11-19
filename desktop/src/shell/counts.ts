/** Dependency-free counts, so node tests can load them. */
import type { WorkspaceState } from "../store";

/**
 * Undecided changes for a document, where the store knows them. The active
 * document's queue is `draft`; parked queues of other documents (trust) are
 * read when present.
 */
export function pendingCount(s: WorkspaceState, sessionId: string): number {
  if (s.draft.sessionId === sessionId) return s.draft.ops.length;
  const parked = (s as unknown as { parkedDrafts?: Record<string, { ops?: unknown[] }> }).parkedDrafts;
  return parked?.[sessionId]?.ops?.length ?? 0;
}

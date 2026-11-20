/**
 * Per-document panel state, outside `store.ts` (J1 §5: `defineDocSlice`).
 *
 * Change decisions live in the canvas document slice.
 */
import type {
  ChangeFilter,
  ChangeSetView,
  TickId,
} from "../model/changes";
import { defineDocSlice } from "../store";

export type { RightTabId as PanelTab } from "../shell/shellState";

export type ConfirmPhase = "idle" | "pruning" | "requesting" | "applying" | "failed";

export interface StyleFinding {
  rule: string;
  message: string;
  excerpt: string;
  at: string | null;
}

/** What the filled 결재란 shows after the draft is gone. */
export interface AppliedRecord {
  revision: number;
  atUtc: string;
  proposer: "agent" | "user" | "test" | "mixed";
  count: number;
  facts: number;
  attn: number;
  checked: boolean;
}

export interface ReturnedRecord {
  count: number;
  reason: string;
  atUtc: string;
  requested: boolean;
}

export interface PanelDocState {
  filter: ChangeFilter;
  sheetOpen: boolean;
  /** The plan and decisions displayed when the sheet opened. */
  sheetFor: string | null;
  ticks: TickId[];
  returnOpen: boolean;
  confirmPhase: ConfirmPhase;
  confirmError: string | null;
  applied: AppliedRecord | null;
  returned: ReturnedRecord | null;
  /** Bumped when a blocked 승인 is pressed, so the footer reason pulses. */
  pulse: number;
  style: { phase: "idle" | "running" | "ready" | "failed"; findings: StyleFinding[]; error: string | null };
  /** Composer context chip, e.g. the selected seat's name. */
  context: string | null;
}

export const PANEL_INITIAL: PanelDocState = {
  filter: "all",
  sheetOpen: false,
  sheetFor: null,
  ticks: [],
  returnOpen: false,
  confirmPhase: "idle",
  confirmError: null,
  applied: null,
  returned: null,
  pulse: 0,
  style: { phase: "idle", findings: [], error: null },
  context: null,
};

export const panelSlice = defineDocSlice<PanelDocState>("panel", PANEL_INITIAL);

// The view the panel last rendered, per document. Key handlers and actions
// read it so they act on exactly what is on screen.
const latest = new Map<string, ChangeSetView | null>();

export function setLatestView(doc: string | null, view: ChangeSetView | null): void {
  if (!doc) return;
  if (view) latest.set(doc, view);
  else latest.delete(doc);
}

export function latestView(doc: string | null): ChangeSetView | null {
  return doc ? latest.get(doc) ?? null : null;
}

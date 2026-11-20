/**
 * WP4's mount point. The shell loads every `<dir>/register.ts` with
 * `import.meta.glob`; this one fills the `rightPanel` slot and binds the
 * review keys (J1 §3 keyboard) through the shared registry.
 */
import "./panel.css";

import { createElement } from "react";

import { getState } from "../store";
import { canDecide, gateState } from "../model/changes";
import { registerCommand } from "../shell/commands";
import { defineContext, register as registerKey } from "../shell/keys";
import { registerSlot, type SlotProps } from "../shell/slots";
import {
  acceptAll,
  decide,
  focusComposer,
  openApproval,
  openReturn,
  runStyleCheck,
  selectedId,
  setTab,
  step,
  undoDecision,
} from "./actions";
import { AgentConnectionSettings } from "../components/OperatorAgentModal";
import { requestEdit } from "./ChangeItemRow";
import { tp } from "./i18n";
import { PANEL_CHORDS, type PanelKeyId } from "./keys";
import { RightPanel } from "./RightPanel";
import { latestView, panelSlice } from "./state";

function doc() {
  return getState().activeSessionId;
}

/** Review keys act only while the 변경 pane is the one showing. */
function reviewing(): boolean {
  const st = panelSlice.get(doc());
  return st.tab === "changes" && !st.sheetOpen && !st.returnOpen && Boolean(latestView(doc()));
}

function onSelected(run: (id: string) => void): () => void {
  return () => {
    const id = selectedId();
    if (id) run(id);
  };
}

const RUN: Record<PanelKeyId, { run: () => void; when?: () => boolean }> = {
  "change.next": { run: () => step(1), when: reviewing },
  "change.prev": { run: () => step(-1), when: reviewing },
  "change.accept": { run: onSelected((id) => decide(id, "accepted")), when: () => reviewing() && canDecide(latestView(doc())) },
  "change.reject": { run: onSelected((id) => decide(id, "rejected")), when: () => reviewing() && canDecide(latestView(doc())) },
  "change.edit": { run: onSelected((id) => requestEdit(id)), when: () => reviewing() && canDecide(latestView(doc())) },
  "change.undo": { run: () => void undoDecision(), when: reviewing },
  "change.acceptAll": { run: () => void acceptAll(), when: reviewing },
  "proposal.return": { run: () => void openReturn(), when: reviewing },
  "approval.open": {
    run: () => {
      if (!openApproval()) {
        // Blocked: the reason pulses; nothing opens.
      }
    },
    when: () => Boolean(latestView(doc())) && !panelSlice.get(doc()).sheetOpen,
  },
  "composer.focus": { run: focusComposer },
  "panel.changes": { run: () => setTab("changes") },
  "panel.agent": { run: () => setTab("agent") },
  "panel.checks": { run: () => setTab("checks") },
  "checks.style": { run: () => void runStyleCheck() },
};

const RightPanelSlot = (_: SlotProps) => createElement(RightPanel);
const AgentSettingsSlot = (_: SlotProps) => createElement(AgentConnectionSettings);

let registered = false;

export function registerPanel(): void {
  if (registered) return;
  registered = true;
  registerSlot("rightPanel", RightPanelSlot, { owner: "panel" });
  registerSlot("settings:agent", AgentSettingsSlot, { owner: "panel" });
  // The keymap's two contexts (shell/keymap.ts) are the panel's: `review`
  // while the 변경 pane is showing, `sheet` while the approval sheet is open.
  // They are exclusive, and the page's own review keys stand down while
  // `review` is active.
  defineContext("review", reviewing);
  defineContext("sheet", () => panelSlice.get(doc()).sheetOpen);
  for (const [id, chords] of Object.entries(PANEL_CHORDS) as [PanelKeyId, readonly string[]][]) {
    const entry = RUN[id];
    registerKey({ id, chords: [...chords], when: entry.when ? () => entry.when!() : undefined, run: entry.run });
  }
  registerCommand({ id: "approval.open", title: (l) => tp("act_approve", l), group: "review", run: () => void openApproval(), keyId: "approval.open", when: () => Boolean(latestView(doc())) });
  registerCommand({ id: "change.acceptAll", title: (l) => tp("act_accept_all", l), group: "review", run: () => void acceptAll(), keyId: "change.acceptAll", when: () => Boolean(latestView(doc())) });
  registerCommand({ id: "checks.style", title: (l) => tp("checks_style_run", l), group: "document", run: () => void runStyleCheck(), keyId: "checks.style", when: () => doc() !== null });
}

/** Whether 승인 is currently possible, for the shell's status bar and palette. */
export function approvalReady(): boolean {
  return gateState(latestView(doc())).canApprove;
}

registerPanel();

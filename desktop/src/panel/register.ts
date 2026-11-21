import "./panel.css";

import { createElement } from "react";

import { AgentConnectionSettings } from "../components/OperatorAgentModal";
import { S } from "../i18n/v2/shell";
import { canDecide } from "../model/changes";
import { showRightTab } from "../shell/bindings";
import { registerCommand } from "../shell/commands";
import { bindKey } from "../shell/keymap";
import { defineContext, overlayOpen } from "../shell/keys";
import { activeTabSessionId, getShell } from "../shell/shellState";
import { registerSlot, type SlotProps } from "../shell/slots";
import {
  acceptAll,
  decide,
  focusComposer,
  openApproval,
  openReturn,
  runStyleCheck,
  selectedId,
  step,
  undoDecision,
} from "./actions";
import { requestEdit } from "./ChangeItemRow";
import { tp } from "./i18n";
import { RightPanel } from "./RightPanel";
import { latestView, panelSlice } from "./state";

function documentReady(): boolean {
  const shell = getShell();
  return activeTabSessionId() !== null &&
    !shell.paletteOpen && !shell.settingsOpen && !shell.appMenuOpen &&
    !shell.tabListOpen && !shell.narrowDrawerOpen;
}

function inPanelOverlay(): boolean {
  const { sheetOpen, returnOpen } = panelSlice.get(activeTabSessionId());
  const active = document.activeElement;
  return sheetOpen || returnOpen || Boolean(active?.closest('[data-testid="approve-sheet"], [data-testid="return-popover"]'));
}

function reviewing(): boolean {
  return documentReady() && !overlayOpen() && !inPanelOverlay() && Boolean(latestView(activeTabSessionId())?.items.length) &&
    Boolean(document.activeElement?.closest('[data-testid="change-list"]'));
}

function onSelected(run: (id: string) => void): () => void {
  return () => {
    const id = selectedId();
    if (id && canDecide(latestView(activeTabSessionId()))) run(id);
  };
}

function focusChangeList(): void {
  showRightTab("changes");
  requestAnimationFrame(() => document.querySelector<HTMLElement>('[data-testid="change-list"]')?.focus());
}

const RightPanelSlot = ({ sessionId }: SlotProps) =>
  sessionId ? createElement(RightPanel, { key: sessionId, sessionId }) : null;

registerSlot("rightPanel", RightPanelSlot, { owner: "panel" });
registerSlot("narrowSheet", RightPanelSlot, { owner: "panel" });
registerSlot("settings:agent", AgentConnectionSettings, { owner: "panel", title: (lang) => S.t("shell_settings_agent", lang) });
defineContext("review", reviewing);
defineContext("sheet", inPanelOverlay);

bindKey("change.next", () => step(1));
bindKey("change.prev", () => step(-1));
bindKey("change.accept", onSelected((id) => decide(id, "accepted")));
bindKey("change.reject", onSelected((id) => decide(id, "rejected")));
bindKey("change.edit", onSelected((id) => requestEdit(id)));
bindKey("change.undo", undoDecision);
bindKey("change.acceptAll", acceptAll);
bindKey("proposal.return", openReturn);
bindKey("approval.open", openApproval, {
  when: () => documentReady() && !overlayOpen() && !inPanelOverlay() && Boolean(latestView(activeTabSessionId())),
  inEditable: false,
});
bindKey("panel.changes", focusChangeList, { when: documentReady });
bindKey("panel.agent", () => showRightTab("agent"), { when: documentReady });
bindKey("panel.checks", () => showRightTab("checks"), { when: documentReady });
bindKey("composer.focus", focusComposer, { when: () => documentReady() && !inPanelOverlay() });
bindKey("checks.style", runStyleCheck, { when: () => documentReady() && !inPanelOverlay() });

const hasChanges = () => Boolean(latestView(activeTabSessionId()));
registerCommand({ id: "approval.open", title: (lang) => tp("wp4_act_approve", lang), group: "review", run: () => void openApproval(), keyId: "approval.open", when: hasChanges });
registerCommand({ id: "change.acceptAll", title: (lang) => tp("wp4_act_accept_all", lang), group: "review", run: () => { focusChangeList(); acceptAll(); }, keyId: "change.acceptAll", when: hasChanges });
registerCommand({ id: "checks.style", title: (lang) => tp("wp4_checks_style_run", lang), group: "document", run: () => void runStyleCheck(), keyId: "checks.style", when: () => activeTabSessionId() !== null });

for (const [id, label, run] of [
  ["change.accept", "wp4_act_accept", onSelected((item) => decide(item, "accepted"))],
  ["change.reject", "wp4_act_reject", onSelected((item) => decide(item, "rejected"))],
  ["change.edit", "wp4_act_edit", onSelected(requestEdit)],
  ["change.undo", "wp4_act_undo", undoDecision],
  ["proposal.return", "wp4_act_return", openReturn],
] as const) {
  registerCommand({ id, title: (lang) => tp(label, lang), group: "review", keyId: id, when: hasChanges,
    run: () => { focusChangeList(); run(); } });
}

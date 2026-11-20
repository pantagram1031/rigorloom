import { wp3t } from "../i18n/v2/wp3";
import { BlanksPane } from "../panes/BlanksPane";
import { FindPane } from "../panes/FindPane";
import { OutlinePane } from "../panes/OutlinePane";
import { showLeftPane } from "../shell/bindings";
import { registerCommand, type CommandGroup } from "../shell/commands";
import { bindKey } from "../shell/keymap";
import { isContextActive, keys, overlayOpen, type KeyBinding } from "../shell/keys";
import { activeTabSessionId, getShell } from "../shell/shellState";
import { registerSlot } from "../shell/slots";
import {
  beginCellEditV2,
  cycleCanvasView,
  decideCanvasItem,
  fitCanvasPage,
  fitCanvasWidth,
  stepCanvasChange,
  stepCanvasZoom,
  undoCanvasDecision,
} from "./actions";
import { CanvasPane, CanvasStatusLeft, CanvasStatusRight } from "./CanvasPane";
import { getCanvasSlice, getPublishedChanges, setCanvasSlice, type CanvasDocSlice } from "./controller";
import { DocumentStrip, DocumentStripStart } from "./DocumentStrip";

let cleanup: (() => void) | null = null;

function documentReady(): boolean {
  const shell = getShell();
  return Boolean(activeTabSessionId()) &&
    !shell.paletteOpen && !shell.settingsOpen && !shell.appMenuOpen &&
    !shell.tabListOpen && !shell.narrowDrawerOpen;
}

function canFind(): boolean {
  const { paletteOpen, settingsOpen } = getShell();
  return activeTabSessionId() !== null && !paletteOpen && !settingsOpen && !isContextActive("sheet");
}

function reviewCanvas(): boolean {
  return documentReady() && !overlayOpen() && getCanvasSlice().view === "marks" &&
    getPublishedChanges().length > 0 && !isContextActive("review") && !isContextActive("sheet");
}

function focusFind(request: NonNullable<CanvasDocSlice["findRequest"]>): void {
  showLeftPane("find", { toggle: false });
  setCanvasSlice({ findRequest: request });
}

function editSelection(): boolean {
  const { selectedChangeId, selectedSeatKey } = getCanvasSlice();
  const change = getPublishedChanges().find((item) => item.id === selectedChangeId);
  const match = (change?.cellKey ?? selectedSeatKey)?.match(/^c:(\d+):(\d+):(\d+)$/);
  return match ? beginCellEditV2(Number(match[1]), Number(match[2]), Number(match[3])) : false;
}

function decideSelection(decision: "accepted" | "rejected" | "pending"): boolean {
  const id = getCanvasSlice().selectedChangeId;
  if (!id) return false;
  decideCanvasItem(id, decision);
  return true;
}

export function registerCanvasModule(): () => void {
  if (cleanup) return cleanup;
  const owner = { owner: "canvas" };
  const bindings = [
    registerSlot("canvas", CanvasPane, owner),
    registerSlot("pane:outline", OutlinePane, owner),
    registerSlot("pane:blanks", BlanksPane, owner),
    registerSlot("pane:find", FindPane, owner),
    registerSlot("stripStart", DocumentStripStart, owner),
    registerSlot("stripEnd", DocumentStrip, owner),
    registerSlot("statusLeft", CanvasStatusLeft, owner),
    registerSlot("statusRight", CanvasStatusRight, owner),
  ];

  const bind = (id: string, run: KeyBinding["run"], when = documentReady) =>
    bindings.push(bindKey(id, run, { when }));
  bind("canvas.cycleView", () => { cycleCanvasView(); });
  bind("canvas.zoomIn", () => stepCanvasZoom(0.1));
  bind("canvas.zoomOut", () => stepCanvasZoom(-0.1));
  bind("canvas.fitWidth", fitCanvasWidth);
  bind("canvas.fitPage", fitCanvasPage);
  bind("canvas.find", () => focusFind("find"), canFind);
  bind("canvas.replace", () => focusFind("replace"), canFind);
  bind("canvas.findNext", () => focusFind(1), canFind);
  bind("canvas.findPrev", () => focusFind(-1), canFind);
  bind("canvas.edit", editSelection);
  bind("canvas.undo", undoCanvasDecision, reviewCanvas);

  const reviewKey = (id: string, chords: string[], run: KeyBinding["run"]) =>
    bindings.push(keys.register({ id, chords, run, when: reviewCanvas }));
  reviewKey("canvas.nextChange", ["J", "ArrowDown", "Alt+ArrowDown"], () => { stepCanvasChange(1); });
  reviewKey("canvas.prevChange", ["K", "ArrowUp", "Alt+ArrowUp"], () => { stepCanvasChange(-1); });
  reviewKey("canvas.acceptSelected", ["Y"], () => decideSelection("accepted"));
  reviewKey("canvas.rejectSelected", ["N"], () => decideSelection("rejected"));
  reviewKey("canvas.restoreSelected", ["U"], () => decideSelection("pending"));
  reviewKey("canvas.editSelected", ["E"], editSelection);

  const command = (
    id: string,
    key: Parameters<typeof wp3t>[0],
    group: CommandGroup,
    run: () => void,
  ) => bindings.push(registerCommand({
    id, title: (lang) => wp3t(key, lang), group, run,
    when: () => activeTabSessionId() !== null,
  }));

  command("canvas.cycleView", "cmd_cycle_view", "view", cycleCanvasView);
  command("canvas.zoomIn", "cmd_zoom_in", "view", () => stepCanvasZoom(0.1));
  command("canvas.zoomOut", "cmd_zoom_out", "view", () => stepCanvasZoom(-0.1));
  command("canvas.fitWidth", "cmd_fit_width", "view", fitCanvasWidth);
  command("canvas.fitPage", "cmd_fit_page", "view", fitCanvasPage);
  command("canvas.find", "cmd_find", "edit", () => focusFind("find"));
  command("canvas.replace", "cmd_replace", "edit", () => focusFind("replace"));

  cleanup = () => {
    for (const off of bindings.reverse()) off();
    cleanup = null;
  };
  return cleanup;
}

export function unregisterCanvasModule(): void {
  cleanup?.();
}

registerCanvasModule();

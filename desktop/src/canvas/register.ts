import { wp3t } from "../i18n/v2/wp3";
import { buildRegionTextMap } from "../workspace/externalPlan";
import { getState } from "../store";
import { BlanksPane } from "../panes/BlanksPane";
import { FindPane } from "../panes/FindPane";
import { OutlinePane } from "../panes/OutlinePane";
import {
  keys,
  registerCommand,
  registerSlot,
  requestFindFocus,
  requestLeftPane,
} from "./_shim";
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
import {
  getCanvasSlice,
  getPublishedChanges,
  setCanvasSlice,
} from "./controller";
import {
  CanvasPane,
  CanvasStatusLeft,
  CanvasStatusRight,
} from "./CanvasPane";

let registered = false;
const cleanupFns: Array<() => void> = [];

/**
 * Register WP3's canvas, left panes, status bar segments, commands, and
 * physical-key bindings into the WP2 slot/key registries (or local shim
 * prior to WP2 shell integration).
 */
export function registerCanvasModule(): () => void {
  if (registered) {
    return unregisterCanvasModule;
  }
  registered = true;

  registerSlot("canvas", CanvasPane);
  registerSlot("pane:outline", OutlinePane);
  registerSlot("pane:blanks", BlanksPane);
  registerSlot("pane:find", FindPane);
  registerSlot("statusLeft", CanvasStatusLeft);
  registerSlot("statusRight", CanvasStatusRight);

  const lang = () => getState().language;

  cleanupFns.push(
    keys.register({
      id: "canvas.cycleView",
      chords: ["KeyV"],
      hint: "V",
      run: () => {
        cycleCanvasView();
      },
    }),
    keys.register({
      id: "canvas.zoomIn",
      chords: ["Ctrl+Equal", "Ctrl+Shift+Equal"],
      when: "always",
      hint: "Ctrl+=",
      run: () => {
        stepCanvasZoom(0.1);
      },
    }),
    keys.register({
      id: "canvas.zoomOut",
      chords: ["Ctrl+Minus"],
      when: "always",
      hint: "Ctrl+-",
      run: () => {
        stepCanvasZoom(-0.1);
      },
    }),
    keys.register({
      id: "canvas.fitWidth",
      chords: ["Ctrl+0"],
      when: "always",
      hint: "Ctrl+0",
      run: () => {
        fitCanvasWidth();
      },
    }),
    keys.register({
      id: "canvas.fitPage",
      chords: ["Ctrl+Shift+0"],
      when: "always",
      hint: "Ctrl+Shift+0",
      run: () => {
        fitCanvasPage();
      },
    }),
    keys.register({
      id: "canvas.nextChange",
      chords: ["KeyJ", "ArrowDown", "Alt+ArrowDown", "Alt+PageDown"],
      hint: "J / Alt+PgDn",
      run: () => {
        stepCanvasChange(1);
      },
    }),
    keys.register({
      id: "canvas.prevChange",
      chords: ["KeyK", "ArrowUp", "Alt+ArrowUp", "Alt+PageUp"],
      hint: "K / Alt+PgUp",
      run: () => {
        stepCanvasChange(-1);
      },
    }),
    keys.register({
      id: "canvas.acceptSelected",
      chords: ["KeyY"],
      hint: "Y",
      run: () => {
        const id = getCanvasSlice().selectedChangeId;
        if (!id) return false;
        decideCanvasItem(id, "accepted");
      },
    }),
    keys.register({
      id: "canvas.rejectSelected",
      chords: ["KeyN"],
      hint: "N",
      run: () => {
        const id = getCanvasSlice().selectedChangeId;
        if (!id) return false;
        decideCanvasItem(id, "rejected");
      },
    }),
    keys.register({
      id: "canvas.restoreSelected",
      chords: ["KeyU"],
      hint: "U",
      run: () => {
        const id = getCanvasSlice().selectedChangeId;
        if (!id) return false;
        const changes = getPublishedChanges();
        const item = changes.find((c) => c.id === id);
        if (!item) return false;
        decideCanvasItem(
          id,
          item.decision === "pending" ? "accepted" : "pending",
        );
      },
    }),
    keys.register({
      id: "canvas.editSelected",
      chords: ["KeyE", "F2"],
      hint: "E / F2",
      run: () => {
        const st = getState();
        const sess = st.sessions.find((s) => s.sessionId === st.activeSessionId);
        const inspect = sess ? st.inspects[sess.sessionId] : null;
        if (!sess || !inspect) return false;

        const slice = getCanvasSlice(sess.sessionId);
        const selected = getPublishedChanges().find(
          (c) => c.id === slice.selectedChangeId,
        );
        const targetKey = selected?.cellKey ?? slice.selectedSeatKey;
        if (!targetKey) return false;
        const m = /^c:(\d+):(\d+):(\d+)$/.exec(targetKey);
        if (!m) return false;
        const texts = st.texts[sess.sessionId] ?? [];
        beginCellEditV2(Number(m[1]), Number(m[2]), Number(m[3]), {
          inspect,
          texts,
        });
      },
    }),
    keys.register({
      id: "canvas.undoDecision",
      chords: ["Ctrl+Z"],
      hint: "Ctrl+Z",
      run: () => {
        if (!undoCanvasDecision()) return false;
      },
    }),
    keys.register({
      id: "canvas.find",
      chords: ["Ctrl+F"],
      when: "always",
      hint: "Ctrl+F",
      run: () => {
        requestFindFocus("find");
      },
    }),
    keys.register({
      id: "canvas.replace",
      chords: ["Ctrl+H"],
      when: "always",
      hint: "Ctrl+H",
      run: () => {
        requestFindFocus("replace");
      },
    }),
    keys.register({
      id: "canvas.findNext",
      chords: ["F3"],
      when: "always",
      hint: "F3",
      run: () => {
        requestFindFocus("find");
        setCanvasSlice((prev) => ({
          ...prev,
          activeFindIndex: prev.activeFindIndex + 1,
        }));
      },
    }),
    keys.register({
      id: "canvas.findPrev",
      chords: ["Shift+F3"],
      when: "always",
      hint: "Shift+F3",
      run: () => {
        requestFindFocus("find");
        setCanvasSlice((prev) => ({
          ...prev,
          activeFindIndex: Math.max(0, prev.activeFindIndex - 1),
        }));
      },
    }),
  );

  const category = wp3t("cmd_category_canvas", lang());
  cleanupFns.push(
    registerCommand({
      id: "canvas.cycleView",
      title: wp3t("cmd_cycle_view", lang()),
      category,
      keybinding: "V",
      run: () => {
        cycleCanvasView();
      },
    }),
    registerCommand({
      id: "canvas.fitWidth",
      title: wp3t("cmd_fit_width", lang()),
      category,
      keybinding: "Ctrl+0",
      run: () => fitCanvasWidth(),
    }),
    registerCommand({
      id: "canvas.fitPage",
      title: wp3t("cmd_fit_page", lang()),
      category,
      keybinding: "Ctrl+Shift+0",
      run: () => fitCanvasPage(),
    }),
    registerCommand({
      id: "canvas.zoomIn",
      title: wp3t("cmd_zoom_in", lang()),
      category,
      keybinding: "Ctrl+=",
      run: () => stepCanvasZoom(0.1),
    }),
    registerCommand({
      id: "canvas.zoomOut",
      title: wp3t("cmd_zoom_out", lang()),
      category,
      keybinding: "Ctrl+-",
      run: () => stepCanvasZoom(-0.1),
    }),
    registerCommand({
      id: "canvas.find",
      title: wp3t("cmd_find", lang()),
      category,
      keybinding: "Ctrl+F",
      run: () => requestFindFocus("find"),
    }),
    registerCommand({
      id: "canvas.replace",
      title: wp3t("cmd_replace", lang()),
      category,
      keybinding: "Ctrl+H",
      run: () => requestFindFocus("replace"),
    }),
    registerCommand({
      id: "canvas.openBlanks",
      title: wp3t("cmd_open_blanks", lang()),
      category,
      run: () => requestLeftPane("blanks"),
    }),
    registerCommand({
      id: "canvas.openOutline",
      title: wp3t("cmd_open_outline", lang()),
      category,
      run: () => requestLeftPane("outline"),
    }),
  );

  // Also ensure active text map helper stays tree-shaken cleanly if unused externally
  void buildRegionTextMap;

  return unregisterCanvasModule;
}

export function unregisterCanvasModule(): void {
  while (cleanupFns.length > 0) {
    const fn = cleanupFns.pop();
    fn?.();
  }
  registered = false;
}

registerCanvasModule();

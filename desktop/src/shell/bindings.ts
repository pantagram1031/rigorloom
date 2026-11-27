/**
 * The shell's own keys, contexts and commands, and the one window key listener.
 */
import { closeTopmostOverlay, toggleFullscreen, toggleTheme, setLanguage } from "../actions";
import { S } from "../i18n/v2/shell";
import * as rt from "../runtime";
import { getState, hasUnsavedWorkForReload, patchDocSlice, reloadWithoutUiVariantQuery } from "../store";
import { registerCommand } from "./commands";
import { defineContext, dispatch, type KeyEventLike, overlayOpen, setBrowserMode } from "./keys";
import { bindKey } from "./keymap";
import { pickAndOpenFile, pickFolder } from "./open";
import {
  activeTabSessionId,
  docLayout,
  dockedSides,
  getShell,
  type LeftPaneId,
  type RightTabId,
  type SettingsSection,
  setShell,
} from "./shellState";
import { activateTabIndex, closeTab, openStartTab, stepTab } from "./tabs";

export function openPalette(query = ""): void {
  try {
    performance.clearMarks("palette-open-start");
    performance.mark("palette-open-start");
  } catch {
    // no performance API
  }
  setShell({ paletteOpen: true, paletteQuery: query, appMenuOpen: false, tabListOpen: false });
}

export function closePalette(): void {
  setShell({ paletteOpen: false, paletteQuery: "" });
}

export function openSettings(section: SettingsSection = "general"): void {
  setShell({ settingsOpen: true, settingsSection: section, paletteOpen: false, appMenuOpen: false, narrowDrawerOpen: false });
}

/** Switch from editor v2 to the previous v1 screens, refusing when work is unsaved. */
export async function openV1(): Promise<void> {
  const lang = getState().language;
  if (hasUnsavedWorkForReload()) {
    const note = S.t("shell_status_finish_edit_first", lang);
    setShell({ statusNotice: note });
    const sid = activeTabSessionId() ?? getState().activeSessionId;
    if (sid) patchDocSlice("canvas.page", { statusNotice: note }, sid);
    return;
  }
  setShell({ statusNotice: null });
  const sid = activeTabSessionId() ?? getState().activeSessionId;
  if (sid) patchDocSlice("canvas.page", { statusNotice: null }, sid);
  await rt.savePrefs({ editorVariant: "v1" });
  reloadWithoutUiVariantQuery();
}

/** Alt+1…5: show a left pane; the same key again collapses the pane. */
export function showLeftPane(pane: LeftPaneId, { toggle = true } = {}): void {
  const sid = activeTabSessionId();
  const shell = getShell();
  if (shell.breakpoint === "narrow" && sid) {
    const current = docLayout.get(sid).leftPane;
    docLayout.patch(sid, { leftPane: pane, landed: true });
    setShell({ narrowDrawerOpen: !(toggle && shell.narrowDrawerOpen && current === pane) });
    return;
  }
  const current = sid ? docLayout.get(sid).leftPane : "files";
  if (toggle && visibleSides().left && current === pane) {
    setShell({ leftOpen: false });
    return;
  }
  if (sid) docLayout.patch(sid, { leftPane: pane, landed: true });
  setShell({ leftOpen: true, lastOpened: "left" });
}

export function showRightTab(tab: RightTabId): void {
  const sid = activeTabSessionId();
  if (!sid) return;
  const s = getShell();
  docLayout.patch(sid, { rightTab: tab });
  setShell({
    rightOpen: true,
    lastOpened: "right",
    narrowDrawerOpen: false,
    ...(s.rightOpen ? {} : { narrowSheetExpanded: false }),
  });
}

function visibleSides() {
  const s = getShell();
  return dockedSides(s.breakpoint, s, activeTabSessionId() !== null);
}

/** Show the left pane if it is not showing; hide it if it is. */
export function toggleLeft(): void {
  if (visibleSides().left) setShell({ leftOpen: false });
  else setShell({ leftOpen: true, lastOpened: "left" });
}

/** Show the right panel if it is not showing; hide it if it is. */
export function toggleRight(): void {
  const shell = getShell();
  if (shell.breakpoint === "narrow" ? shell.rightOpen : visibleSides().right) {
    setShell({ rightOpen: false, narrowSheetExpanded: false });
  } else {
    setShell({ rightOpen: true, lastOpened: "right", narrowSheetExpanded: false });
  }
}

function innerSheetOverlayOpen(): boolean {
  if (overlayOpen()) return true;
  if (typeof document === "undefined" || typeof document.querySelector !== "function") return false;
  return Boolean(
    document.querySelector(
      '#sh-narrow-sheet [role="dialog"]:not([hidden]), #sh-narrow-sheet [role="menu"]:not([hidden]), #sh-narrow-sheet [aria-modal="true"]:not([hidden])',
    ),
  );
}

function focusInNarrowSheet(e?: KeyEventLike): boolean {
  const candidates = [
    e?.target,
    typeof document !== "undefined" ? document.activeElement : null,
  ];
  for (const el of candidates) {
    if (!el || typeof (el as { closest?: unknown }).closest !== "function") continue;
    const closest = (el as { closest: (sel: string) => unknown }).closest.bind(el);
    if (
      closest(
        '[data-testid="approve-sheet"], [data-testid="return-popover"], [role="dialog"]:not([hidden]), [role="menu"]:not([hidden]), [aria-modal="true"]:not([hidden])',
      )
    ) {
      return false;
    }
    if (closest('#sh-narrow-sheet, .sh-narrow-sheet, [data-testid="narrow-sheet-handle"]')) {
      return true;
    }
  }
  return false;
}

/** Esc order (D1 §4): overlays first, then the shell's own layers. */
function escape(e?: KeyEventLike): boolean {
  const s = getShell();
  if (s.paletteOpen) {
    closePalette();
    return true;
  }
  if (s.settingsOpen) {
    setShell({ settingsOpen: false });
    return true;
  }
  if (s.appMenuOpen || s.tabListOpen || s.narrowDrawerOpen) {
    setShell({ appMenuOpen: false, tabListOpen: false, narrowDrawerOpen: false });
    return true;
  }
  if (closeTopmostOverlay()) return true;
  // An Escape a control inside the sheet already handled (a popover closing) stops here.
  if (e?.defaultPrevented) return false;
  if (s.rightOpen && s.narrowSheetExpanded && !innerSheetOverlayOpen() && focusInNarrowSheet(e)) {
    setShell({ narrowSheetExpanded: false });
    return true;
  }
  return false;
}

const PANES: Array<[LeftPaneId, string]> = [
  ["files", "shell.pane.files"],
  ["outline", "shell.pane.outline"],
  ["blanks", "shell.pane.blanks"],
  ["find", "shell.pane.find"],
  ["history", "shell.pane.history"],
];

let installed: (() => void) | null = null;

/** Register the shell's bindings, contexts and commands. Idempotent. */
export function installShellBindings(): () => void {
  if (installed) return installed;
  const offs: Array<() => void> = [];
  const lang = () => getState().language;

  offs.push(defineContext("docOpen", () => activeTabSessionId() !== null));
  offs.push(defineContext("palette", () => getShell().paletteOpen));

  offs.push(bindKey("shell.palette", () => (getShell().paletteOpen ? closePalette() : openPalette())));
  offs.push(bindKey("shell.openFile", () => void pickAndOpenFile()));
  offs.push(bindKey("shell.openFolder", () => void pickFolder()));
  offs.push(bindKey("shell.newTab", () => openStartTab()));
  offs.push(bindKey("shell.closeTab", () => closeTab()));
  offs.push(bindKey("shell.nextTab", () => stepTab(1)));
  offs.push(bindKey("shell.prevTab", () => stepTab(-1)));
  for (let n = 1; n <= 9; n += 1) offs.push(bindKey(`shell.tab${n}`, () => activateTabIndex(n)));
  for (const [pane, id] of PANES) offs.push(bindKey(id, () => showLeftPane(pane)));
  offs.push(bindKey("shell.toggleLeft", () => toggleLeft()));
  offs.push(bindKey("shell.toggleRight", () => toggleRight()));
  offs.push(bindKey("shell.settings", () => openSettings()));
  offs.push(bindKey("shell.fullscreen", () => void toggleFullscreen()));
  // Ctrl+S never creates a 수정본; it pulses 저장됨 (D1 flow b.7).
  offs.push(bindKey("shell.save", () => setShell({ savedPulse: getShell().savedPulse + 1 })));
  offs.push(bindKey("shell.escape", (e) => escape(e)));

  const cmd = (id: string, key: Parameters<typeof S.t>[0], run: () => void, extra: Partial<Parameters<typeof registerCommand>[0]> = {}) =>
    offs.push(registerCommand({ id, title: (l) => S.t(key, l), run, ...extra }));

  cmd("shell.openFile", "shell_cmd_open_file", () => void pickAndOpenFile(), { group: "file", menu: true });
  cmd("shell.openFolder", "shell_cmd_open_folder", () => void pickFolder(), { group: "file", menu: true });
  cmd("shell.newTab", "shell_cmd_new_tab", () => openStartTab(), { group: "file", menu: true });
  cmd("shell.closeTab", "shell_cmd_close_tab", () => closeTab(), {
    group: "file",
    menu: true,
    when: () => getShell().tabs.length > 1 || getShell().activeTab !== "start",
  });
  cmd("shell.nextTab", "shell_cmd_next_tab", () => stepTab(1), { group: "view", when: () => getShell().tabs.length > 1 });
  cmd("shell.prevTab", "shell_cmd_prev_tab", () => stepTab(-1), { group: "view", when: () => getShell().tabs.length > 1 });
  cmd("shell.toggleLeft", "shell_cmd_toggle_left", () => toggleLeft(), { group: "view", menu: true });
  cmd("shell.toggleRight", "shell_cmd_toggle_right", () => toggleRight(), {
    group: "view",
    menu: true,
    when: () => activeTabSessionId() !== null,
  });
  for (const [pane, id] of PANES) {
    cmd(id, `shell_cmd_pane_${pane}` as Parameters<typeof S.t>[0], () => showLeftPane(pane), { group: "view" });
  }
  cmd("shell.save", "shell_cmd_save", () => setShell({ savedPulse: getShell().savedPulse + 1 }), {
    group: "file",
    when: () => activeTabSessionId() !== null,
  });
  cmd("shell.settings", "shell_cmd_settings", () => openSettings(), { group: "help", menu: true });
  cmd("shell.fullscreen", "shell_cmd_fullscreen", () => void toggleFullscreen(), { group: "view", menu: true });
  cmd("shell.theme.light", "shell_cmd_theme_light", () => void toggleTheme("light"), { group: "view", keyId: "" });
  cmd("shell.theme.dark", "shell_cmd_theme_dark", () => void toggleTheme("dark"), { group: "view", keyId: "" });
  cmd("shell.theme.system", "shell_cmd_theme_system", () => void toggleTheme("auto"), { group: "view", keyId: "" });
  cmd("shell.lang.ko", "shell_cmd_language_ko", () => void setLanguage("ko"), {
    group: "view",
    keyId: "",
    when: () => lang() !== "ko",
  });
  cmd("shell.lang.en", "shell_cmd_language_en", () => void setLanguage("en"), {
    group: "view",
    keyId: "",
    when: () => lang() !== "en",
  });
  offs.push(
    registerCommand({
      id: "shell.openV1",
      title: (l) => S.t("shell_cmd_open_v1", l, ["v1"]),
      group: "view",
      keyId: "",
      run: () => openV1(),
    }),
  );

  setBrowserMode(!rt.isTauri());

  const onKey = (e: KeyboardEvent) => {
    dispatch(e);
  };
  window.addEventListener("keydown", onKey);
  offs.push(() => window.removeEventListener("keydown", onKey));

  installed = () => {
    for (const off of offs.splice(0)) off();
    installed = null;
  };
  return installed;
}

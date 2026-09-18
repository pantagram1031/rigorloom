/**
 * Ctrl+K command palette: toolbar actions, inspector tabs, 홈, 설정, recents.
 */
import { useEffect, useMemo } from "react";

import {
  approveAndApply,
  bindFormAndOpen,
  exportApplied,
  openPath,
  openViaDialog,
  runCheck,
  toggleLeftRail,
} from "../actions";
import { filterCommands, workspaceCommands } from "../commands";
import {
  getState,
  goHome,
  selectInspectorTab,
  setCenterMode,
  setChromeMenu,
  setPaletteOpen,
  setState,
  useWorkspace,
} from "../store";
import { Command } from "../ui/Command";

export function runCommand(id: string, recentPath?: string): void {
  setPaletteOpen(false);
  switch (id) {
    case "open":
      void openViaDialog();
      return;
    case "check":
      void runCheck();
      return;
    case "approve":
      selectInspectorTab("review");
      void approveAndApply();
      return;
    case "export":
      void exportApplied();
      return;
    case "history":
      selectInspectorTab("history");
      return;
    case "bind-form":
      void bindFormAndOpen();
      return;
    case "mode-text":
      setCenterMode("text");
      return;
    case "mode-page":
      setCenterMode("page");
      return;
    case "zoom":
      setChromeMenu("zoom");
      return;
    case "rail":
      toggleLeftRail();
      return;
    case "tab-selection":
      selectInspectorTab("selection");
      return;
    case "tab-review":
      selectInspectorTab("review");
      return;
    case "tab-history":
      selectInspectorTab("history");
      return;
    case "tab-agent":
      selectInspectorTab("agent");
      return;
    case "home":
      goHome();
      return;
    case "settings":
      setState({ settingsOpen: true });
      return;
    default:
      if (recentPath) void openPath(recentPath);
  }
}

export function CommandPalette() {
  const open = useWorkspace((s) => s.paletteOpen);
  const recents = useWorkspace((s) => s.recents);
  const items = useMemo(
    () =>
      filterCommands(workspaceCommands({ recents }), "").map((item) => ({
        id: item.id,
        label: item.label,
        shortcut: item.shortcut,
        recentPath: item.recentPath,
        testId: `palette-item-${item.id}`,
      })),
    [recents],
  );

  useEffect(() => {
    if (!open) return;
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="palette-veil"
      data-testid="command-palette"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) setPaletteOpen(false);
      }}
    >
      <Command
        className="palette"
        items={items}
        autoFocus
        queryTestId="palette-query"
        onSelect={(id) => {
          const item = items.find((row) => row.id === id);
          runCommand(id, item?.recentPath);
        }}
      />
    </div>
  );
}

export function toggleCommandPalette(): void {
  setPaletteOpen(!getState().paletteOpen);
}

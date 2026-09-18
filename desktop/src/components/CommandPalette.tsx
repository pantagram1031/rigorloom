/**
 * Ctrl+K command palette: toolbar actions, inspector tabs, 홈, 설정, recents.
 */
import { useEffect, useMemo, useRef, useState } from "react";

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
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  const items = useMemo(
    () => filterCommands(workspaceCommands({ recents }), query),
    [recents, query],
  );

  useEffect(() => {
    if (!open) {
      setQuery("");
      setActive(0);
      return;
    }
    setActive(0);
    const id = window.requestAnimationFrame(() => input.current?.focus());
    return () => window.cancelAnimationFrame(id);
  }, [open]);

  useEffect(() => {
    if (active >= items.length) setActive(Math.max(0, items.length - 1));
  }, [active, items.length]);

  if (!open) return null;

  return (
    <div
      className="palette-veil"
      data-testid="command-palette"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) setPaletteOpen(false);
      }}
    >
      <div
        className="palette"
        role="dialog"
        aria-label="명령"
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setActive((i) => Math.min(items.length - 1, i + 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((i) => Math.max(0, i - 1));
          } else if (e.key === "Enter") {
            e.preventDefault();
            const item = items[active];
            if (item) runCommand(item.id, item.recentPath);
          } else if (e.key === "Escape") {
            e.preventDefault();
            setPaletteOpen(false);
          }
        }}
      >
        <input
          ref={input}
          className="palette-query"
          data-testid="palette-query"
          value={query}
          placeholder="명령 찾기"
          aria-label="명령 찾기"
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
          }}
        />
        <ul className="palette-list" role="listbox">
          {items.map((item, index) => (
            <li key={item.id}>
              <button
                type="button"
                className={`palette-item${index === active ? " is-active" : ""}`}
                role="option"
                aria-selected={index === active}
                data-testid={`palette-item-${item.id}`}
                data-command={item.id}
                onMouseEnter={() => setActive(index)}
                onClick={() => runCommand(item.id, item.recentPath)}
              >
                <span>{item.label}</span>
                {item.shortcut ? <kbd>{item.shortcut}</kbd> : null}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export function toggleCommandPalette(): void {
  setPaletteOpen(!getState().paletteOpen);
}

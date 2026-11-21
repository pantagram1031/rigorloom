import { useEffect, useRef } from "react";

import { useWorkspace } from "../store";
import { S } from "../i18n/v2/shell";
import { type Command, commandTitle, runCommand, useCommandsVersion, visibleCommands } from "./commands";
import { keyHintText } from "./keys";
import { setShell } from "./shellState";

const ORDER: Command["group"][] = ["file", "edit", "view", "document", "review", "help"];

/** The single app menu behind the mark (D1 §2). Rows are commands with `menu: true`. */
export function AppMenu() {
  useCommandsVersion();
  const lang = useWorkspace((s) => s.language);
  const ref = useRef<HTMLDivElement>(null);
  const rows = visibleCommands()
    .filter((c) => c.menu)
    .sort((a, b) => ORDER.indexOf(a.group ?? "help") - ORDER.indexOf(b.group ?? "help"));

  useEffect(() => {
    ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node) && !(e.target as HTMLElement).closest("[data-testid='app-menu']")) {
        setShell({ appMenuOpen: false });
      }
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, []);

  let lastGroup: string | undefined;
  return (
    <div className="sh-menu" role="menu" ref={ref} data-testid="app-menu-list" aria-label={S.t("shell_app_menu", lang)}>
      {rows.map((c) => {
        const sep = lastGroup !== undefined && c.group !== lastGroup;
        lastGroup = c.group;
        const enabled = !c.enabled || c.enabled();
        return (
          <div key={c.id} className={sep ? "sh-menu-group" : undefined}>
            <button
              type="button"
              role="menuitem"
              className="sh-menu-row"
              disabled={!enabled}
              data-testid={`app-menu-${c.id}`}
              onClick={() => {
                setShell({ appMenuOpen: false });
                runCommand(c.id);
              }}
              onKeyDown={(e) => {
                const items = Array.from(ref.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? []);
                const at = items.indexOf(e.currentTarget);
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  items[(at + 1) % items.length]?.focus();
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  items[(at - 1 + items.length) % items.length]?.focus();
                }
              }}
            >
              <span className="sh-menu-label">{commandTitle(c, lang)}</span>
              {c.keyId === "" ? null : <span className="sh-mono">{keyHintText(c.keyId ?? c.id)}</span>}
            </button>
          </div>
        );
      })}
    </div>
  );
}

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { cn } from "./cn";
import { Kbd } from "./Kbd";
import { moveRoving } from "./roving";

export type CommandItemDef = {
  id: string;
  label: string;
  shortcut?: string;
  disabled?: boolean;
  testId?: string;
  recentPath?: string;
};

function filterItems(items: CommandItemDef[], query: string): CommandItemDef[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return items;
  return items.filter((item) => {
    if (item.label.toLowerCase().includes(needle)) return true;
    if (item.shortcut?.toLowerCase().includes(needle)) return true;
    return false;
  });
}

export function Command({
  items,
  onSelect,
  placeholder = "명령 찾기",
  label = "명령",
  className,
  defaultValue = "",
  autoFocus = false,
  queryTestId,
  itemTestId,
}: {
  items: CommandItemDef[];
  onSelect?: (id: string) => void;
  placeholder?: string;
  label?: string;
  className?: string;
  defaultValue?: string;
  autoFocus?: boolean;
  queryTestId?: string;
  itemTestId?: (id: string) => string;
}) {
  const [query, setQuery] = useState(defaultValue);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const filtered = useMemo(() => filterItems(items, query), [items, query]);

  useEffect(() => {
    if (autoFocus) input.current?.focus();
  }, [autoFocus]);

  useEffect(() => {
    if (active >= filtered.length) setActive(Math.max(0, filtered.length - 1));
  }, [active, filtered.length]);

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Home" || e.key === "End") {
      e.preventDefault();
      setActive((i) => moveRoving(filtered.length, i, e.key));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const item = filtered[active];
      if (item && !item.disabled) onSelect?.(item.id);
    }
  };

  return (
    <div className={cn("ui-cmd", className)} role="dialog" aria-label={label} onKeyDown={onKey}>
      <input
        ref={input}
        className="ui-cmd-query"
        data-testid={queryTestId}
        value={query}
        placeholder={placeholder}
        aria-label={placeholder}
        onChange={(e) => {
          setQuery(e.target.value);
          setActive(0);
        }}
      />
      <ul className="ui-cmd-list" role="listbox">
        {filtered.map((item, index) => (
          <li key={item.id}>
            <button
              type="button"
              role="option"
              aria-selected={index === active}
              data-state={index === active ? "active" : "idle"}
              className="ui-cmd-item"
              data-testid={item.testId ?? itemTestId?.(item.id) ?? `palette-item-${item.id}`}
              data-command={item.id}
              disabled={item.disabled}
              onMouseEnter={() => setActive(index)}
              onClick={() => onSelect?.(item.id)}
            >
              <span>{item.label}</span>
              {item.shortcut ? <Kbd>{item.shortcut}</Kbd> : null}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export { filterItems as filterCommandItems };

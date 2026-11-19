/**
 * 명령창 (Ctrl+K, alias Ctrl+Shift+P): commands, open documents, sample forms.
 * Rows carry their key in a keycap; the footer names the three palette keys.
 */
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { S } from "../i18n/v2/shell";
import { getState, useWorkspace } from "../store";
import { corpusFormDisplayInfo } from "../workspace/openHelpers";
import { closePalette } from "./bindings";
import { commandTitle, matchScore, runCommand, useCommandsVersion, visibleCommands } from "./commands";
import { docTitle } from "./docInfo";
import { bindKey } from "./keymap";
import { openSample } from "./open";
import { ChordHint, KeyHint } from "./parts";
import { getShell, setShell, useShell } from "./shellState";
import { activateTab } from "./tabs";
import { paletteRowTid, TID } from "./testids";

interface Row {
  id: string;
  group: "commands" | "docs" | "samples";
  label: string;
  sub?: string;
  keyId?: string;
  disabled?: boolean;
  score: number;
  run: () => void;
}

export function Palette() {
  const open = useShell((s) => s.paletteOpen);
  if (!open) return null;
  return <PaletteBody />;
}

function PaletteBody() {
  useCommandsVersion();
  const lang = useWorkspace((s) => s.language);
  const corpus = useWorkspace((s) => s.corpusFiles);
  const tabs = useShell((s) => s.tabs);
  const query = useShell((s) => s.paletteQuery);
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Budget measure: keydown to the committed palette frame.
  useLayoutEffect(() => {
    inputRef.current?.focus();
    try {
      if (performance.getEntriesByName("palette-open-start", "mark").length > 0) {
        performance.measure("palette-open", "palette-open-start");
        performance.clearMarks("palette-open-start");
      }
    } catch {
      // no performance API
    }
  }, []);

  const rows = useMemo<Row[]>(() => {
    const ws = getState();
    const out: Row[] = [];
    for (const c of visibleCommands()) {
      const label = commandTitle(c, lang);
      const words = [label, ...(c.keywords?.(lang) ?? [])].join(" ");
      const score = matchScore(words, query);
      if (score <= 0) continue;
      out.push({
        id: `cmd:${c.id}`,
        group: "commands",
        label,
        keyId: c.keyId === "" ? undefined : c.keyId ?? c.id,
        disabled: c.enabled ? !c.enabled() : false,
        score,
        run: () => runCommand(c.id),
      });
    }
    for (const tab of tabs) {
      if (tab.kind !== "doc") continue;
      const label = docTitle(ws, tab.sessionId);
      const score = matchScore(label, query);
      if (score <= 0) continue;
      out.push({ id: `doc:${tab.sessionId}`, group: "docs", label, score, run: () => activateTab(tab.id) });
    }
    for (const entry of corpus) {
      const info = corpusFormDisplayInfo(entry, lang);
      const score = matchScore(`${info.title} ${info.filename}`, query);
      if (score <= 0) continue;
      out.push({ id: `sample:${entry.path}`, group: "samples", label: info.title, sub: info.sourceLabel, score, run: () => void openSample(entry) });
    }
    const groupRank = { commands: 0, docs: 1, samples: 2 } as const;
    if (query.trim()) out.sort((a, b) => b.score - a.score || groupRank[a.group] - groupRank[b.group]);
    else out.sort((a, b) => groupRank[a.group] - groupRank[b.group]);
    return out;
  }, [query, tabs, corpus, lang]);

  useEffect(() => setCursor(0), [query]);

  const runAt = (i: number) => {
    const row = rows[i];
    if (!row || row.disabled) return;
    closePalette();
    row.run();
  };

  // Palette keys go through the registry so the footer hints are the bindings.
  const cursorRef = useRef(cursor);
  cursorRef.current = cursor;
  const rowsRef = useRef(rows);
  rowsRef.current = rows;
  useEffect(() => {
    const offs = [
      bindKey("palette.down", () => setCursor((c) => Math.min(c + 1, Math.max(rowsRef.current.length - 1, 0)))),
      bindKey("palette.up", () => setCursor((c) => Math.max(c - 1, 0))),
      bindKey("palette.run", () => runAt(cursorRef.current)),
    ];
    return () => offs.forEach((off) => off());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    listRef.current?.querySelector(`[data-cursor="true"]`)?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  let lastGroup: Row["group"] | null = null;
  const groupLabel = {
    commands: S.t("shell_palette_group_commands", lang),
    docs: S.t("shell_palette_group_docs", lang),
    samples: S.t("shell_palette_group_samples", lang),
  };

  return (
    <div className="sh-scrim sh-scrim--clear" onMouseDown={(e) => e.target === e.currentTarget && closePalette()}>
      <div className="sh-palette" role="dialog" aria-modal="true" aria-label={S.t("shell_palette_label", lang)} data-testid={TID.palette}>
        <input
          ref={inputRef}
          className="sh-palette-input"
          data-testid={TID.paletteInput}
          placeholder={S.t("shell_palette_placeholder", lang)}
          value={query}
          role="combobox"
          aria-expanded="true"
          aria-controls="sh-palette-list"
          aria-activedescendant={rows[cursor] ? `sh-pal-${cursor}` : undefined}
          onChange={(e) => setShell({ paletteQuery: e.target.value })}
        />
        <div className="sh-palette-list" role="listbox" id="sh-palette-list" ref={listRef}>
          {rows.length === 0 ? (
            <div className="sh-palette-empty">{S.t("shell_palette_empty", lang, [query])}</div>
          ) : (
            rows.map((row, i) => {
              const head = !query.trim() && row.group !== lastGroup ? groupLabel[row.group] : null;
              lastGroup = row.group;
              return (
                <div key={row.id}>
                  {head ? <div className="sh-palette-head">{head}</div> : null}
                  <div
                    id={`sh-pal-${i}`}
                    role="option"
                    aria-selected={i === cursor}
                    aria-disabled={row.disabled || undefined}
                    className="sh-palette-row"
                    data-cursor={i === cursor || undefined}
                    data-testid={paletteRowTid(row.id)}
                    onMouseMove={() => i !== cursor && setCursor(i)}
                    onClick={() => runAt(i)}
                  >
                    <span className="sh-palette-label">{row.label}</span>
                    {row.sub ? <span className="sh-palette-sub">{row.sub}</span> : null}
                    {row.keyId ? <KeyHint id={row.keyId} /> : null}
                  </div>
                </div>
              );
            })
          )}
        </div>
        <div className="sh-palette-foot">
          <span><ChordHint chord="Up" /><ChordHint chord="Down" /> {S.t("shell_palette_hint_select", lang)}</span>
          <span><KeyHint id="palette.run" /> {S.t("shell_palette_hint_run", lang)}</span>
          <span><KeyHint id="shell.escape" /> {S.t("shell_palette_hint_close", lang)}</span>
        </div>
      </div>
    </div>
  );
}

/** For tests: is the palette open right now. */
export function paletteIsOpen(): boolean {
  return getShell().paletteOpen;
}

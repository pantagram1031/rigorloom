/**
 * Ctrl+K catalog. Labels only here; CommandPalette maps ids to actions.
 */

export type CommandGroup = "action" | "tab" | "nav" | "recent";

export type CommandDef = {
  id: string;
  label: string;
  shortcut?: string;
  group: CommandGroup;
  recentPath?: string;
};

export function workspaceCommands(input: {
  recents?: Array<{ path: string; name: string }>;
}): CommandDef[] {
  const recents = (input.recents ?? []).filter((row) => row.path && row.name);
  const commands: CommandDef[] = [
    { id: "open", label: "열기", shortcut: "Ctrl+O", group: "action" },
    { id: "check", label: "검사", group: "action" },
    { id: "approve", label: "승인", group: "action" },
    { id: "export", label: "저장/내보내기", shortcut: "Ctrl+S", group: "action" },
    { id: "history", label: "되돌리기", group: "action" },
    { id: "bind-form", label: "양식 연결", group: "action" },
    { id: "mode-text", label: "본문", group: "action" },
    { id: "mode-page", label: "페이지", group: "action" },
    { id: "zoom", label: "배율", group: "action" },
    { id: "rail", label: "구조 레일", shortcut: "Ctrl+B", group: "action" },
    { id: "tab-selection", label: "선택", group: "tab" },
    { id: "tab-review", label: "검토", group: "tab" },
    { id: "tab-history", label: "기록", group: "tab" },
    { id: "tab-agent", label: "에이전트", shortcut: "Ctrl+2", group: "tab" },
    { id: "home", label: "홈", shortcut: "Ctrl+Shift+H", group: "nav" },
    { id: "settings", label: "설정", group: "nav" },
  ];
  for (const recent of recents) {
    commands.push({
      id: `recent:${recent.path}`,
      label: recent.name,
      group: "recent",
      recentPath: recent.path,
    });
  }
  return commands;
}

function fuzzyScore(label: string, query: string): number {
  const hay = label.toLowerCase();
  const needle = query.toLowerCase().trim();
  if (!needle) return 1;
  if (hay === needle) return 400;
  const idx = hay.indexOf(needle);
  if (idx === 0) return 300 - needle.length;
  if (idx > 0) return 200 - idx;
  let from = 0;
  for (const ch of needle) {
    const at = hay.indexOf(ch, from);
    if (at < 0) return 0;
    from = at + 1;
  }
  return Math.max(1, 80 - from);
}

export function filterCommands<T extends { label: string; shortcut?: string }>(
  items: T[],
  query: string,
): T[] {
  const needle = query.trim();
  if (!needle) return items;
  return items
    .map((item) => ({
      item,
      score: Math.max(fuzzyScore(item.label, needle), item.shortcut ? fuzzyScore(item.shortcut, needle) : 0),
    }))
    .filter((row) => row.score > 0)
    .sort((a, b) => b.score - a.score)
    .map((row) => row.item);
}

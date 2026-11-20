import hancomFontSource from "./hancomFontSource.json" with { type: "json" };

export type FontPresence = "installed" | "missing" | "unknown";
export type FontCheckRow = { declared: string; drawnWith: string | null; state: FontPresence | "other" };

export function substitutedFontRows(
  rows: readonly FontCheckRow[],
  fallbackFor: (declared: string) => string | null,
) {
  return rows.filter((row) => row.state === "missing" || row.state === "unknown").map((row) => ({
    ...row,
    drawnWith: row.drawnWith ?? fallbackFor(row.declared),
  }));
}

function officialFontSource() {
  const parsed = new URL(hancomFontSource);
  if (parsed.origin !== "https://www.hancom.com" || parsed.username || parsed.password) {
    throw new Error("Unexpected font distribution host");
  }
  return { href: hancomFontSource, target: "_blank", rel: "noopener noreferrer" } as const;
}

export const FONT_SOURCE_LINK = officialFontSource();

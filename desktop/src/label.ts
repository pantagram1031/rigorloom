/**
 * Turn a value that may have been stored as an error object into a label.
 *
 * `String({ code, message })` is the literal "[object Object]". React will
 * print the same if the object itself is used as a child. Prefer `message`,
 * then other common string fields, then JSON — never the Object toString.
 */
export function labelOf(value: unknown, fallback = ""): string {
  if (value == null || value === "") return fallback;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (typeof value === "object") {
    const rec = value as Record<string, unknown>;
    for (const key of ["message", "reason", "title", "blurb", "detail"] as const) {
      const inner = rec[key];
      if (typeof inner === "string" && inner) return inner;
    }
    try {
      const text = JSON.stringify(value);
      return text && text !== "{}" ? text : fallback;
    } catch {
      return fallback;
    }
  }
  return fallback;
}

/** 1-based table cell address for chrome. Runtime indexes stay 0-based. */
export function humanCellAddress(table: number, row: number, col: number): string {
  return `표 ${table + 1} · ${row + 1}행 ${col + 1}열`;
}

export function quoteKo(text: string): string {
  return `「${text}」`;
}

export function shortHash(value: string | null | undefined, n = 12): string {
  if (!value) return "";
  return value.slice(0, n);
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  return `${Math.round(bytes / 1024)} KB`;
}

export function stampWhen(iso: string | null | undefined): string {
  if (!iso) return "";
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return iso.replace("T", " ").slice(0, 16);
  const d = new Date(then);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function relativeWhen(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return iso;
  const mins = Math.floor((now - then) / 60000);
  if (mins < 1) return "방금";
  if (mins < 60) return `${mins}분 전`;
  if (mins < 24 * 60) return `${Math.floor(mins / 60)}시간 전`;
  const dayDiff = Math.round(
    (new Date(now).setHours(0, 0, 0, 0) - new Date(then).setHours(0, 0, 0, 0)) / 86_400_000,
  );
  if (dayDiff === 1) return "어제";
  if (dayDiff < 7) return `${dayDiff}일 전`;
  return stampWhen(iso);
}

export function trimLabel(text: string, max = 34): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max)}…` : flat;
}

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

/** How a file name is shown: pure, no imports, so the tests can load it alone. */

/**
 * Bidirectional control characters (embeddings, overrides, isolates and the
 * marks). A file name like `보고서\u202Egpj.hwpx` would otherwise show a
 * spoofed extension in the 파일 pane and on its tab (finding 20); a name is
 * shown without them, so it reads in its stored order.
 */
const BIDI_CONTROLS = /[\u061C\u200E\u200F\u202A-\u202E\u2066-\u2069]/g;

export function plainName(name: string): string {
  return name.replace(BIDI_CONTROLS, "");
}

/**
 * Which editor the window shows: the editor v2 shell (default) or the previous
 * v1 screens.
 *
 * Precedence:
 * 1. `?ui=v1|v2` in the address;
 * 2. `editorVariant` ("v1" or "v2") in prefs.json;
 * 3. otherwise "v2".
 *
 * The choice is marked on <html> as `data-ui`, which scopes the v1 palette
 * (v1-tokens.css) to the v1 screens.
 */

export type UiVariant = "v1" | "v2";

/** The preference that chooses between the editor v2 shell and the v1 screens. */
export const EDITOR_VARIANT_PREF = "editorVariant";

/** `?ui=v1` or `?ui=v2`, or null when the address names neither. */
export function uiVariantFromQuery(search: string): UiVariant | null {
  try {
    const ui = new URLSearchParams(search).get("ui");
    return ui === "v1" || ui === "v2" ? ui : null;
  } catch {
    return null;
  }
}

/**
 * Precedence: `?ui=v1|v2` > `editorVariant` ("v1" | "v2") > default v2.
 */
export function resolveUiVariant(query: UiVariant | null, prefs: Record<string, unknown> | null | undefined): UiVariant {
  if (query === "v1" || query === "v2") return query;
  const saved = prefs?.[EDITOR_VARIANT_PREF];
  if (saved === "v1" || saved === "v2") return saved;
  return "v2";
}

/** The key that chose the editor before `editorVariant` (false -> v1, true -> v2). */
const LEGACY_EDITOR_PREF = "devEditorV2";

/**
 * One-time migration of a legacy `devEditorV2` key, for a prefs file that the
 * runtime bridge did not read first (the desktop app loads prefs.json itself).
 *
 * Returns the prefs to use for this launch and the patch to save, or a null
 * patch when there is nothing to migrate. A boolean value becomes
 * `editorVariant` unless that is already "v1" or "v2"; any other value is
 * only removed.
 */
export function migrateLegacyEditorPref(
  prefs: Record<string, unknown> | null | undefined,
): { prefs: Record<string, unknown> | null; patch: Record<string, unknown> | null } {
  if (!prefs || !(LEGACY_EDITOR_PREF in prefs)) return { prefs: prefs ?? null, patch: null };
  const { [LEGACY_EDITOR_PREF]: legacy, ...rest } = prefs;
  const saved = rest[EDITOR_VARIANT_PREF];
  if (typeof legacy === "boolean" && saved !== "v1" && saved !== "v2") {
    const variant: UiVariant = legacy ? "v2" : "v1";
    return {
      prefs: { ...rest, [EDITOR_VARIANT_PREF]: variant },
      patch: { [EDITOR_VARIANT_PREF]: variant, [LEGACY_EDITOR_PREF]: null },
    };
  }
  return { prefs: rest, patch: { [LEGACY_EDITOR_PREF]: null } };
}

let current: UiVariant = "v2";

/** The variant chosen at start (or by the smoke driver since). */
export function uiVariant(): UiVariant {
  return current;
}

/** Record the variant and mark <html> with it. */
export function setUiVariant(variant: UiVariant): void {
  current = variant;
  if (typeof document !== "undefined") document.documentElement.dataset.ui = variant;
}

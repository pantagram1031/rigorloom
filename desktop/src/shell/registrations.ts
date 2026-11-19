/**
 * Loads every package's `register.ts` (J1 §5). Imported once, by `App.tsx`.
 *
 * `desktop/src/<dir>/register.ts` and one level deeper
 * (`desktop/src/canvas/engine/register.ts`) are picked up. Eager, so slots are
 * filled before the first render and the shell never flashes a placeholder for
 * a package that is present.
 */
const modules = import.meta.glob(["../*/register.ts", "../*/*/register.ts"], { eager: true });

/** Which register files were found, for the smoke and for tests. */
export const loadedRegistrations: string[] = Object.keys(modules)
  .map((p) => p.replace(/^\.\.\//, ""))
  .sort();

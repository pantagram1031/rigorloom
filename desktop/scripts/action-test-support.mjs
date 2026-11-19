import { readFileSync } from "node:fs";
export { agentPlanCellAddresses, projectAgentPlan } from "../src/agent/planProjection.ts";
export { opKindLabel, t } from "../src/i18n/vocabulary.ts";
const source = readFileSync(new URL("../src/workspace/reviewSummary.ts", import.meta.url), "utf8");
export const approvalHelpers = source.slice(source.indexOf("export function activeApprovalBinding("), source.indexOf("/** Pending operations")).replaceAll("export ", "");

/**
 * The real `src/workspace/trust.ts` for component render tests that load each
 * module through a stub map. `load(relPath, stubs)` is the test's own loader,
 * with paths relative to this scripts directory.
 */
export function loadTrustModule(load) {
  const vocabulary = load("../src/i18n/vocabulary.ts", {});
  const store = load("../src/store.ts", {
    react: { useSyncExternalStore: (_subscribe, snapshot) => snapshot() },
  });
  return load("../src/workspace/trust.ts", {
    "../i18n/vocabulary.ts": vocabulary,
    "../store.ts": store,
  });
}

/** Store selectors added for the trust fixes, for hand-written store stubs. */
export const trustStoreSelectors = {
  returnedDraftOps: () => [],
  activeDisplayText: (s) => s.texts?.[s.activeSessionId] ?? [],
  activeHeadTexts: () => null,
  showToast: () => {},
};

/* Focused desktop revision-coherence cases against desktop/src/revision.ts.
 *
 * No Tauri, no package install beyond the Desktop TypeScript already declared.
 * Promise completions are explicit — there are no timing sleeps.
 *
 * (a) a read that answers the source while the page names a candidate is refused
 * (b) a superseded click / reverse-order completion is a no-op, not a stale write
 */
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const ts = require(path.join(__dirname, "..", "desktop", "node_modules", "typescript"));

const root = path.join(__dirname, "..");
const cache = new Map();

function loadTs(rel) {
  const file = path.join(root, rel);
  if (cache.has(file)) return cache.get(file);
  const source = fs.readFileSync(file, "utf8");
  const emitted = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
  }).outputText;
  const wrapper = { exports: {} };
  const localRequire = (spec) => {
    if (spec.startsWith("./") || spec.startsWith("../")) {
      const resolved = path.join(path.dirname(file), spec.endsWith(".ts") ? spec : `${spec}.ts`);
      return loadTs(path.relative(root, resolved));
    }
    return require(spec);
  };
  new Function("exports", "module", "require", emitted)(wrapper.exports, wrapper, localRequire);
  cache.set(file, wrapper.exports);
  return wrapper.exports;
}

const {
  displayedRevision,
  captureEditLease,
  leaseIsCurrent,
  subjectMatchesLease,
  prepareParagraphEdit,
  commitParagraphClick,
} = loadTs("desktop/src/revision.ts");

function fail(name, detail) {
  console.error(`FAIL ${name}: ${detail}`);
  process.exitCode = 1;
}
function pass(name) {
  console.log(`PASS ${name}`);
}

function view(overrides = {}) {
  const geometry = overrides.geometry === undefined
    ? { source: { runId: "candidate-a", sha256: "pdf-sha" }, subject: { kind: "candidate", runId: "candidate-a", sha256: "candidate-sha" } }
    : overrides.geometry;
  const render = overrides.render === undefined
    ? { source: { runId: "candidate-a", sha256: "pdf-sha" } }
    : overrides.render;
  return {
    activeSessionId: overrides.activeSessionId ?? "session-a",
    editIntentGeneration: overrides.editIntentGeneration ?? 1,
    geometry,
    render,
    sessions: [{ sessionId: "session-a", source: { sha256: "source-sha" } }],
  };
}

function spanAddress(atPara = 0) {
  return { kind: "anchor", atPara };
}

async function main() {
  // --- displayed revision is the page, not ambient head ---
  const shown = displayedRevision(view());
  if (shown.runId !== "candidate-a" || shown.documentSha256 !== "candidate-sha") {
    fail("displayed_revision_uses_page_subject", JSON.stringify(shown));
  } else pass("displayed_revision_uses_page_subject");

  const sourceView = view({
    geometry: { source: { sha256: "pdf-sha" }, subject: { kind: "session_source", sha256: "source-sha" } },
    render: { source: { sha256: "pdf-sha" } },
  });
  const sourceRev = displayedRevision(sourceView);
  if (sourceRev.runId !== null || sourceRev.documentSha256 !== "source-sha") {
    fail("displayed_revision_source_has_null_run", JSON.stringify(sourceRev));
  } else pass("displayed_revision_source_has_null_run");

  // --- (a) wrong-revision / candidate mismatch ---
  const lease = captureEditLease(view(), 1, 1);
  const mismatch = await prepareParagraphEdit({
    lease,
    spanText: "BETA",
    spanIndex: 0,
    caret: 0,
    address: spanAddress(1),
    readRegion: async (sessionId, regions, runId) => {
      if (runId !== "candidate-a") {
        throw new Error(`readRegion must receive the displayed runId, got ${runId}`);
      }
      return {
        subject: { kind: "session_source", sha256: "source-sha" },
        regions: regions.map(({ atPara }) => ({
          at_para: atPara,
          runs: [{ index: 0, text: "BETA" }],
        })),
      };
    },
  });
  if (mismatch.kind !== "refused" || mismatch.refusal !== "revision_mismatch") {
    fail("wrong_subject_same_text_is_rejected", JSON.stringify(mismatch));
  } else pass("wrong_subject_same_text_is_rejected");

  const opened = await prepareParagraphEdit({
    lease,
    spanText: "GAMMA",
    spanIndex: 0,
    caret: 2,
    address: spanAddress(0),
    readRegion: async (_s, regions, runId) => ({
      subject: { kind: "candidate", runId: "candidate-a", sha256: "candidate-sha" },
      regions: regions.map(({ atPara }) => ({
        at_para: atPara,
        runs: [{ index: 0, text: atPara === 0 ? "GAMMA" : "BETA" }],
      })),
    }),
  });
  if (opened.kind !== "caret" || opened.atPara !== 0 || opened.before !== "GAMMA") {
    fail("candidate_new_text_reopens_for_edit", JSON.stringify(opened));
  } else pass("candidate_new_text_reopens_for_edit");

  // --- (b) superseded / reverse-order completion ---
  const firstState = view({ editIntentGeneration: 1 });
  const firstLease = captureEditLease(firstState, 0, 1);
  const secondState = view({ editIntentGeneration: 2 });
  const secondLease = captureEditLease(secondState, 1, 2);

  let releaseFirst;
  const firstGate = new Promise((resolve) => { releaseFirst = resolve; });
  const firstPrep = prepareParagraphEdit({
    lease: firstLease,
    spanText: "ALPHA",
    spanIndex: 0,
    caret: 0,
    address: spanAddress(0),
    readRegion: async () => {
      await firstGate;
      return {
        subject: { kind: "candidate", runId: "candidate-a", sha256: "candidate-sha" },
        regions: [{ at_para: 0, runs: [{ index: 0, text: "ALPHA" }] }],
      };
    },
  });

  const secondEffect = await prepareParagraphEdit({
    lease: secondLease,
    spanText: "BETA",
    spanIndex: 1,
    caret: 1,
    address: spanAddress(1),
    readRegion: async () => ({
      subject: { kind: "candidate", runId: "candidate-a", sha256: "candidate-sha" },
      regions: [{ at_para: 1, runs: [{ index: 0, text: "BETA" }] }],
    }),
  });
  const secondCommit = commitParagraphClick(secondEffect, secondState);
  if (secondCommit.kind !== "caret" || secondCommit.inlineEdit.atPara !== 1) {
    fail("later_click_commits_current_caret", JSON.stringify(secondCommit));
  } else pass("later_click_commits_current_caret");

  releaseFirst();
  const firstEffect = await firstPrep;
  const firstCommit = commitParagraphClick(firstEffect, secondState);
  if (firstCommit.kind !== "noop") {
    fail("superseded_click_is_noop", JSON.stringify(firstCommit));
  } else pass("superseded_click_is_noop");

  const switched = view({ activeSessionId: "session-b", editIntentGeneration: 1 });
  const late = commitParagraphClick(secondEffect, switched);
  if (late.kind !== "noop") {
    fail("other_session_reply_is_noop", JSON.stringify(late));
  } else pass("other_session_reply_is_noop");

  const replaced = view({ geometry: null, render: null, editIntentGeneration: 2 });
  const replacedCommit = commitParagraphClick(secondEffect, replaced);
  if (replacedCommit.kind !== "noop") {
    fail("replaced_view_reply_is_noop", JSON.stringify(replacedCommit));
  } else pass("replaced_view_reply_is_noop");

  if (!leaseIsCurrent(secondLease, secondState)) {
    fail("current_lease_still_valid", "expected current");
  } else pass("current_lease_still_valid");

  if (subjectMatchesLease(lease, { kind: "session_source", sha256: "source-sha" })) {
    fail("subject_match_rejects_source_for_candidate_lease", "matched");
  } else pass("subject_match_rejects_source_for_candidate_lease");

  if (process.exitCode) {
    console.error("desktop revision-coherence harness failed");
  } else {
    console.log("desktop revision-coherence harness passed");
  }
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 2;
});

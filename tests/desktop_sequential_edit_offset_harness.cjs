/* Sequential same-run edit: offset-drift demonstration and guard.
 *
 * Bug: commitEdit used queuedRun?.text as the splice base for
 * commitRunScopedReplacement, but rangeStart/rangeEnd come from
 * prepareParagraphEdit against the displayed revision (edit.before).
 * When the two strings differ in length the splice lands at the wrong
 * position.
 *
 * This harness:
 *   (1) Imports run_map.ts (pure, no Tauri, no React) to exercise the
 *       splice arithmetic directly.
 *   (2) Reads actions.ts source and asserts the bug pattern is absent —
 *       this assertion FAILS on the tip that has the bug and PASSES after
 *       the fix.
 *   (3) Demonstrates the correct splice behavior with several scenarios,
 *       including a supplementary-plane (emoji) character so length is
 *       measured in UTF-16 units.
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
      const resolved = path.join(
        path.dirname(file),
        spec.endsWith(".ts") ? spec : `${spec}.ts`,
      );
      return loadTs(path.relative(root, resolved));
    }
    return require(spec);
  };
  new Function("exports", "module", "require", emitted)(wrapper.exports, wrapper, localRequire);
  cache.set(file, wrapper.exports);
  return wrapper.exports;
}

const { replaceUtf16Range, commitRunScopedReplacement, utf16Length } =
  loadTs("desktop/src/run_map.ts");

function fail(name, detail) {
  console.error(`FAIL ${name}: ${detail}`);
  process.exitCode = 1;
}
function pass(name) {
  console.log(`PASS ${name}`);
}

// ---------------------------------------------------------------------------
// (1) Source-code structural guard
//
// Fails on the bug tip (where queuedRun?.text is present) and passes after
// the fix (where edit.before is used directly).
// ---------------------------------------------------------------------------
const actionsText = fs.readFileSync(
  path.join(root, "desktop", "src", "actions.ts"),
  "utf8",
);

const BUG_PATTERN = "queuedRun?.text ?? edit.before";
if (actionsText.includes(BUG_PATTERN)) {
  fail(
    "commit_edit_splice_base_is_before_not_queued_text",
    `Found stale-offset pattern '${BUG_PATTERN}' in actions.ts — ` +
      "commitEdit uses queuedRun?.text as the runText base but rangeStart/" +
      "rangeEnd offsets come from the displayed revision (edit.before)",
  );
} else {
  pass("commit_edit_splice_base_is_before_not_queued_text");
}

// ---------------------------------------------------------------------------
// (2) Offset-drift arithmetic: demonstrate why edit.before is the right base
//
// Scenario: run "Hello World" (11 UTF-16 units)
//   First edit:  click "Hello" (rangeStart=0, rangeEnd=5) → queue text = "Hi World"
//   Second edit: click "World" (rangeStart=6, rangeEnd=11) → type "Earth"
//
// Bug:  replaceUtf16Range("Hi World", 6, 11, "Earth")
//       "Hi World" has 8 chars; slice(11) = "" → result = "Hi WorEarth" (WRONG)
//
// Fix:  replaceUtf16Range("Hello World", 6, 11, "Earth") = "Hello Earth" (CORRECT)
// ---------------------------------------------------------------------------
const original = "Hello World"; // edit.before = displayed revision text
const firstQueued = "Hi World";  // queuedRun.text after first edit
const rangeStart = 6;            // offsets from prepareParagraphEdit for "World"
const rangeEnd = 11;

// Prove the bug: stale base gives wrong result
const bugResult = replaceUtf16Range(firstQueued, rangeStart, rangeEnd, "Earth");
if (bugResult !== "Hi WorEarth") {
  // Note: we EXPECT this to be "Hi WorEarth" (wrong) — this proves the
  // bug IS real. If JavaScript string semantics change this fails differently.
  fail("bug_result_is_stale", `expected 'Hi WorEarth', got '${bugResult}'`);
} else {
  pass("bug_result_documented_as_stale_splice");
}

// Prove the fix: using edit.before gives correct result
const fixResult = replaceUtf16Range(original, rangeStart, rangeEnd, "Earth");
if (fixResult !== "Hello Earth") {
  fail("fix_produces_correct_splice", `expected 'Hello Earth', got '${fixResult}'`);
} else {
  pass("fix_produces_correct_splice");
}

// Edge case: rangeEnd at the full string length (entire run is one visual line)
const fullReplace = replaceUtf16Range(original, 0, utf16Length(original), "New Text");
if (fullReplace !== "New Text") {
  fail("full_run_replace", `expected 'New Text', got '${fullReplace}'`);
} else pass("full_run_replace");

// ---------------------------------------------------------------------------
// (3) commitRunScopedReplacement wrapper — correct-base scenarios
// ---------------------------------------------------------------------------
const r1 = commitRunScopedReplacement({
  runText: original,  // edit.before (correct)
  rangeStart: 6,
  rangeEnd: 11,
  replacement: "Earth",
});
if (r1.text !== "Hello Earth" || r1.offsetUnit !== "utf-16") {
  fail("commit_run_scoped_correct_base", JSON.stringify(r1));
} else pass("commit_run_scoped_correct_base");

// Second range — first visual line of the run
const r2 = commitRunScopedReplacement({
  runText: original,
  rangeStart: 0,
  rangeEnd: 5,
  replacement: "Hi",
});
if (r2.text !== "Hi World") {
  fail("commit_run_scoped_first_word", JSON.stringify(r2));
} else pass("commit_run_scoped_first_word");

// Two successive edits using edit.before as base (what the fix does):
// First edit: "Hello World" → "Hi World"  (rangeStart=0, rangeEnd=5)
// Second edit: "Hello World" → "Hello Earth" (rangeStart=6, rangeEnd=11)
// The second op in the queue replaces the first for the same opId; the
// final cumulative op is "Hello Earth" relative to the original.
const firstOp = commitRunScopedReplacement({ runText: original, rangeStart: 0, rangeEnd: 5, replacement: "Hi" }).text;
const secondOp = commitRunScopedReplacement({ runText: original, rangeStart: 6, rangeEnd: 11, replacement: "Earth" }).text;
if (firstOp !== "Hi World" || secondOp !== "Hello Earth") {
  fail("sequential_ops_each_against_original", `firstOp=${firstOp}, secondOp=${secondOp}`);
} else pass("sequential_ops_each_against_original");

// ---------------------------------------------------------------------------
// (4) UTF-16 edge case: emoji in the run — offsets are code-unit counts
// ---------------------------------------------------------------------------
// Run: "ab😀cd" — 'ab' (2) + surrogate pair (2) + 'cd' (2) = 6 UTF-16 units
const emojiRun = "ab\u{1F600}cd"; // ab😀cd
if (utf16Length(emojiRun) !== 6) {
  fail("emoji_utf16_length", `expected 6, got ${utf16Length(emojiRun)}`);
} else pass("emoji_utf16_length");

// Click targets the emoji (UTF-16 units 2..4).
const emojiResult = commitRunScopedReplacement({
  runText: emojiRun,
  rangeStart: 2,
  rangeEnd: 4,
  replacement: "X",
});
if (emojiResult.text !== "abXcd") {
  fail("emoji_splice_correct", `expected 'abXcd', got '${emojiResult.text}'`);
} else pass("emoji_splice_correct");

// Now imagine a prior edit changed emojiRun → "abYcd" (8 chars → 5 chars).
// Using the queued text "abYcd" as base with rangeStart=2, rangeEnd=4 would
// splice at the right index by accident here (both have 'Y'/'😀' at 2),
// but for a different length-changing edit the drift is real.
// Demonstrate: prior edit changed "ab😀cd" → "ab💥cd" (still 6 units, no drift)
// vs. "ab😀cd" → "abWORLDcd" (9 units — drift WOULD occur if base were wrong).
const stretchedQueued = "abWORLDcd"; // queuedRun.text if prior edit stretched the run
const driftResult = replaceUtf16Range(stretchedQueued, 2, 4, "X");
// rangeStart=2,rangeEnd=4 against "abWORLDcd" lands on "WO" — not "😀"
if (driftResult !== "abXRLDcd") {
  fail("drift_documented_for_lengthchanging_prior_edit", `got '${driftResult}'`);
} else pass("drift_documented_for_lengthchanging_prior_edit");

// Fix: using edit.before ("ab😀cd") gives the correct result regardless
const fixedDrift = replaceUtf16Range(emojiRun, 2, 4, "X");
if (fixedDrift !== "abXcd") {
  fail("fixed_drift_for_lengthchanging_prior_edit", `got '${fixedDrift}'`);
} else pass("fixed_drift_for_lengthchanging_prior_edit");

if (process.exitCode) {
  console.error("desktop sequential-edit-offset harness FAILED");
} else {
  console.log("desktop sequential-edit-offset harness passed");
}

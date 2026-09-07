/* Focused card-3 cases against desktop/src/revision.ts (+ run_map.ts).
 *
 * Offset contract: every caret / range number is a UTF-16 code unit, the
 * same unit JavaScript string indexes and HWP/OWPML run text use. Tests
 * include a supplementary-plane character so a Unicode-code-point or
 * grapheme count cannot pass by accident.
 *
 * No Tauri, no package install beyond the Desktop TypeScript already declared.
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
  captureEditLease,
  commitParagraphClick,
  prepareParagraphEdit,
  runTextAfterEdit,
} = loadTs("desktop/src/revision.ts");

const runMap = loadTs("desktop/src/run_map.ts");
const {
  OFFSET_UNIT,
  commitRunScopedReplacement,
  isUtf16Split,
  locateSpanInRuns,
  replaceUtf16Range,
  utf16Length,
  utf16Slice,
} = runMap;

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

function regionOf(runs) {
  return async () => ({
    subject: { kind: "candidate", runId: "candidate-a", sha256: "candidate-sha" },
    regions: [{ at_para: 0, runs }],
  });
}

async function main() {
  const state = view();
  const lease = captureEditLease(state, 0, 1);

  // --- offset unit: UTF-16, not code points, not graphemes ---
  const withEmoji = "ab\u{1F600}cd"; // grinning face: one code point, two UTF-16 units
  if (utf16Length(withEmoji) !== 6) {
    fail("utf16_length_counts_surrogate_pair", `${utf16Length(withEmoji)} vs 6 (JS/UTF-16); code points would be 5`);
  } else pass("utf16_length_counts_surrogate_pair");
  if (withEmoji.length !== 6) {
    fail("js_string_index_is_utf16", `${withEmoji.length}`);
  } else pass("js_string_index_is_utf16");
  if (utf16Slice(withEmoji, 2, 4) !== "\u{1F600}") {
    fail("utf16_slice_keeps_surrogate_pair", JSON.stringify(utf16Slice(withEmoji, 2, 4)));
  } else pass("utf16_slice_keeps_surrogate_pair");
  if (OFFSET_UNIT !== "utf-16") {
    fail("offset_unit_is_documented_utf16", OFFSET_UNIT);
  } else pass("offset_unit_is_documented_utf16");

  // --- wrapped single run: the visual line is a fragment, not the whole run ---
  const wrappedRun = "The first visual line and the second visual line";
  const line1 = "The first visual line and";
  const line2 = "the second visual line";
  const wrappedRuns = [{ index: 0, text: wrappedRun }];

  const locateLine2 = locateSpanInRuns(line2, wrappedRuns);
  if (
    locateLine2.kind !== "hit" ||
    locateLine2.run !== 0 ||
    locateLine2.rangeStart !== wrappedRun.indexOf(line2) ||
    locateLine2.rangeEnd !== wrappedRun.indexOf(line2) + line2.length ||
    locateLine2.offsetUnit !== "utf-16" ||
    locateLine2.spanOffset !== 0
  ) {
    fail("locate_wrapped_line_inside_one_run", JSON.stringify(locateLine2));
  } else pass("locate_wrapped_line_inside_one_run");

  const wrappedPrep = await prepareParagraphEdit({
    lease,
    spanText: line2,
    spanIndex: 1,
    caret: 4,
    address: spanAddress(0),
    readRegion: regionOf(wrappedRuns),
  });
  if (
    wrappedPrep.kind !== "caret" ||
    wrappedPrep.run !== 0 ||
    wrappedPrep.before !== wrappedRun ||
    wrappedPrep.offsetUnit !== "utf-16" ||
    wrappedPrep.rangeStart !== wrappedRun.indexOf(line2) ||
    wrappedPrep.rangeEnd !== wrappedRun.indexOf(line2) + utf16Length(line2) ||
    wrappedPrep.caret !== 4 ||
    wrappedPrep.lease.runId !== "candidate-a"
  ) {
    fail("wrapped_single_run_prepare", JSON.stringify(wrappedPrep));
  } else pass("wrapped_single_run_prepare");

  const wrappedCommit = commitParagraphClick(wrappedPrep, state);
  if (
    wrappedCommit.kind !== "caret" ||
    wrappedCommit.inlineEdit.run !== 0 ||
    wrappedCommit.inlineEdit.rangeStart !== wrappedPrep.rangeStart ||
    wrappedCommit.inlineEdit.offsetUnit !== "utf-16" ||
    wrappedCommit.inlineEdit.runId !== "candidate-a"
  ) {
    fail("wrapped_single_run_commit_keeps_source_map", JSON.stringify(wrappedCommit));
  } else pass("wrapped_single_run_commit_keeps_source_map");

  const spliced = commitRunScopedReplacement({
    runText: wrappedRun,
    rangeStart: wrappedPrep.rangeStart,
    rangeEnd: wrappedPrep.rangeEnd,
    replacement: "the SECOND visual line",
  });
  if (spliced.text !== "The first visual line and the SECOND visual line" || spliced.offsetUnit !== "utf-16") {
    fail("wrapped_range_replace_keeps_other_line", JSON.stringify(spliced));
  } else pass("wrapped_range_replace_keeps_other_line");

  // line 1 of the same run is a different range of the same run
  const locateLine1 = locateSpanInRuns(line1, wrappedRuns);
  if (locateLine1.kind !== "hit" || locateLine1.rangeStart !== 0 || locateLine1.run !== 0) {
    fail("locate_first_wrapped_line", JSON.stringify(locateLine1));
  } else pass("locate_first_wrapped_line");

  // --- multi-run paragraph: only the selected run is addressed ---
  const bold = "BOLD ";
  const plain = "plain rest of the paragraph that wraps";
  const multiRuns = [
    { index: 0, text: bold, charpr: "1" },
    { index: 1, text: plain, charpr: "2" },
  ];
  const selectedSpan = "plain rest of the paragraph";
  const multiPrep = await prepareParagraphEdit({
    lease,
    spanText: selectedSpan,
    spanIndex: 3,
    caret: 6,
    address: spanAddress(0),
    readRegion: regionOf(multiRuns),
  });
  if (
    multiPrep.kind !== "caret" ||
    multiPrep.run !== 1 ||
    multiPrep.before !== plain ||
    multiPrep.rangeStart !== 0 ||
    multiPrep.rangeEnd !== utf16Length(selectedSpan) ||
    multiPrep.offsetUnit !== "utf-16"
  ) {
    fail("multi_run_selects_only_clicked_run", JSON.stringify(multiPrep));
  } else pass("multi_run_selects_only_clicked_run");

  const multiSpliced = commitRunScopedReplacement({
    runText: multiPrep.before,
    rangeStart: multiPrep.rangeStart,
    rangeEnd: multiPrep.rangeEnd,
    replacement: "PLAIN rest of the paragraph",
  });
  if (multiSpliced.text !== "PLAIN rest of the paragraph that wraps") {
    fail("multi_run_range_leaves_unselected_suffix", JSON.stringify(multiSpliced));
  } else pass("multi_run_range_leaves_unselected_suffix");
  if (bold !== "BOLD ") {
    fail("neighbor_run_text_untouched", bold);
  } else pass("neighbor_run_text_untouched");

  const neighborLocate = locateSpanInRuns(bold.trimEnd() + " ", multiRuns);
  if (neighborLocate.kind !== "hit" || neighborLocate.run !== 0) {
    fail("clicking_neighbor_run_addresses_that_run", JSON.stringify(neighborLocate));
  } else pass("clicking_neighbor_run_addresses_that_run");

  // --- the visual LINE is the join of both runs: caret names one run ---
  const fullLine = bold + plain;
  const caretInPlain = bold.length + 6; // inside "plain rest..."
  const fullLocate = locateSpanInRuns(fullLine, multiRuns, caretInPlain);
  if (
    fullLocate.kind !== "hit" ||
    fullLocate.run !== 1 ||
    fullLocate.rangeStart !== 0 ||
    fullLocate.rangeEnd !== plain.length ||
    fullLocate.spanOffset !== bold.length
  ) {
    fail("full_line_caret_selects_plain_run", JSON.stringify(fullLocate));
  } else pass("full_line_caret_selects_plain_run");

  const fullPrep = await prepareParagraphEdit({
    lease,
    spanText: fullLine,
    spanIndex: 5,
    caret: caretInPlain,
    address: spanAddress(0),
    readRegion: regionOf(multiRuns),
  });
  if (
    fullPrep.kind !== "caret" ||
    fullPrep.run !== 1 ||
    fullPrep.rangeText !== plain ||
    fullPrep.before !== plain ||
    fullPrep.rangeStart !== 0 ||
    fullPrep.rangeEnd !== plain.length ||
    fullPrep.caret !== 6
  ) {
    fail("full_line_prepare_edits_selected_run_only", JSON.stringify(fullPrep));
  } else pass("full_line_prepare_edits_selected_run_only");

  const fullSpliced = runTextAfterEdit(fullPrep, "PLAIN rest of the paragraph that wraps");
  if (fullSpliced !== "PLAIN rest of the paragraph that wraps") {
    fail("full_line_set_run_rewrites_only_selected_run", JSON.stringify(fullSpliced));
  } else pass("full_line_set_run_rewrites_only_selected_run");

  const caretInBold = 2;
  const boldPrep = await prepareParagraphEdit({
    lease,
    spanText: fullLine,
    spanIndex: 6,
    caret: caretInBold,
    address: spanAddress(0),
    readRegion: regionOf(multiRuns),
  });
  if (
    boldPrep.kind !== "caret" ||
    boldPrep.run !== 0 ||
    boldPrep.rangeText !== bold ||
    boldPrep.caret !== caretInBold
  ) {
    fail("full_line_caret_in_bold_selects_that_run", JSON.stringify(boldPrep));
  } else pass("full_line_caret_in_bold_selects_that_run");
  if (runTextAfterEdit(boldPrep, "Fine ") !== "Fine ") {
    fail("bold_run_edit_leaves_plain_run_out_of_the_op", runTextAfterEdit(boldPrep, "Fine "));
  } else pass("bold_run_edit_leaves_plain_run_out_of_the_op");

  const noCaretOnJoin = locateSpanInRuns(fullLine, multiRuns, null);
  if (noCaretOnJoin.kind !== "refused" || noCaretOnJoin.refusal !== "cross_run") {
    fail("joined_line_without_caret_is_not_a_silent_first_run", JSON.stringify(noCaretOnJoin));
  } else pass("joined_line_without_caret_is_not_a_silent_first_run");

  // --- cross-run must refuse; never flatten the paragraph ---
  const crossSpan = bold + selectedSpan;
  const crossLocate = locateSpanInRuns(crossSpan, multiRuns);
  if (crossLocate.kind !== "refused" || crossLocate.refusal !== "cross_run") {
    fail("locate_cross_run_is_explicit_refusal", JSON.stringify(crossLocate));
  } else pass("locate_cross_run_is_explicit_refusal");

  const crossPrep = await prepareParagraphEdit({
    lease,
    spanText: crossSpan,
    spanIndex: 4,
    caret: null,
    address: spanAddress(0),
    readRegion: regionOf(multiRuns),
  });
  if (crossPrep.kind !== "refused" || crossPrep.refusal !== "cross_run") {
    fail("prepare_cross_run_does_not_flatten", JSON.stringify(crossPrep));
  } else pass("prepare_cross_run_does_not_flatten");

  const joined = bold + plain;
  if (joined.includes(crossSpan) && locateSpanInRuns(crossSpan, multiRuns).kind === "hit") {
    fail("cross_run_must_not_be_a_hit_on_joined_text", "flattened");
  } else pass("cross_run_must_not_be_a_hit_on_joined_text");

  // A span that sits in two runs as an exact substring of each is multi_run,
  // not a silent pick of the first — even when a caret is supplied.
  const shared = "xx";
  const ambiguous = locateSpanInRuns(shared, [
    { index: 0, text: "xxONE" },
    { index: 1, text: "xxTWO" },
  ], 1);
  if (ambiguous.kind !== "refused" || ambiguous.refusal !== "multi_run") {
    fail("span_in_two_runs_is_multi_run", JSON.stringify(ambiguous));
  } else pass("span_in_two_runs_is_multi_run");

  // --- Hangul + surrogate pair in a multi-run paragraph ---
  const hangulPrefix = "제목: ";
  const hangulBody = "안녕 \u{1F600} 세계";
  const hangulRuns = [
    { index: 0, text: hangulPrefix },
    { index: 1, text: hangulBody },
  ];
  const hangulLine = hangulPrefix + hangulBody;
  if (utf16Length(hangulLine) !== hangulPrefix.length + hangulBody.length) {
    fail("hangul_line_utf16_length", `${utf16Length(hangulLine)}`);
  } else pass("hangul_line_utf16_length");
  const caretAfterHello = hangulPrefix.length + "안녕 ".length; // at the grinning face
  const hangulLocate = locateSpanInRuns(hangulLine, hangulRuns, caretAfterHello);
  if (
    hangulLocate.kind !== "hit" ||
    hangulLocate.run !== 1 ||
    hangulLocate.runText !== hangulBody ||
    hangulLocate.rangeStart !== 0 ||
    hangulLocate.rangeEnd !== hangulBody.length ||
    hangulLocate.spanOffset !== hangulPrefix.length
  ) {
    fail("hangul_caret_selects_body_run", JSON.stringify(hangulLocate));
  } else pass("hangul_caret_selects_body_run");

  const hangulPrep = await prepareParagraphEdit({
    lease,
    spanText: hangulLine,
    spanIndex: 7,
    caret: caretAfterHello,
    address: spanAddress(0),
    readRegion: regionOf(hangulRuns),
  });
  if (
    hangulPrep.kind !== "caret" ||
    hangulPrep.run !== 1 ||
    hangulPrep.rangeText !== hangulBody ||
    hangulPrep.caret !== "안녕 ".length
  ) {
    fail("hangul_prepare_selected_run", JSON.stringify(hangulPrep));
  } else pass("hangul_prepare_selected_run");
  const hangulSpliced = runTextAfterEdit(hangulPrep, "안녕 \u{1F600} 지구");
  if (hangulSpliced !== "안녕 \u{1F600} 지구") {
    fail("hangul_splice_keeps_surrogate_and_leaves_title_run", hangulSpliced);
  } else pass("hangul_splice_keeps_surrogate_and_leaves_title_run");
  if (hangulPrefix !== "제목: ") {
    fail("hangul_neighbor_run_untouched", hangulPrefix);
  } else pass("hangul_neighbor_run_untouched");

  const splitAt = hangulLine.indexOf("\u{1F600}") + 1; // between the two surrogates
  if (!isUtf16Split(hangulLine, splitAt)) {
    fail("is_utf16_split_detects_surrogate_midpoint", String(splitAt));
  } else pass("is_utf16_split_detects_surrogate_midpoint");
  const splitLocate = locateSpanInRuns(hangulLine, hangulRuns, splitAt);
  if (splitLocate.kind !== "refused" || splitLocate.refusal !== "utf16_split") {
    fail("caret_between_surrogates_is_utf16_split", JSON.stringify(splitLocate));
  } else pass("caret_between_surrogates_is_utf16_split");

  // --- UTF-16 range inside a wrapped run that also holds an emoji ---
  const emojiRun = `aa${withEmoji} wrapped`;
  const emojiSpan = withEmoji;
  const emojiLocate = locateSpanInRuns(emojiSpan, [{ index: 0, text: emojiRun }]);
  if (
    emojiLocate.kind !== "hit" ||
    emojiLocate.rangeStart !== 2 ||
    emojiLocate.rangeEnd !== 8
  ) {
    fail("emoji_range_is_utf16_not_codepoints", JSON.stringify(emojiLocate));
  } else pass("emoji_range_is_utf16_not_codepoints");
  const emojiReplaced = replaceUtf16Range(emojiRun, emojiLocate.rangeStart, emojiLocate.rangeEnd, "X");
  if (emojiReplaced !== "aaX wrapped") {
    fail("emoji_range_replace", JSON.stringify(emojiReplaced));
  } else pass("emoji_range_replace");

  // --- revision mismatch still refuses; stale lease still no-ops (#330) ---
  const mismatch = await prepareParagraphEdit({
    lease,
    spanText: line2,
    spanIndex: 1,
    caret: 0,
    address: spanAddress(0),
    readRegion: async () => ({
      subject: { kind: "session_source", sha256: "source-sha" },
      regions: [{ at_para: 0, runs: wrappedRuns }],
    }),
  });
  if (mismatch.kind !== "refused" || mismatch.refusal !== "revision_mismatch") {
    fail("revision_mismatch_still_refused", JSON.stringify(mismatch));
  } else pass("revision_mismatch_still_refused");

  const staleState = view({ editIntentGeneration: 99 });
  const stale = commitParagraphClick(wrappedPrep, staleState);
  if (stale.kind !== "noop") {
    fail("revision_mismatch_stale_commit_is_noop", JSON.stringify(stale));
  } else pass("revision_mismatch_stale_commit_is_noop");

  const refusedCommit = commitParagraphClick(crossPrep, staleState);
  if (refusedCommit.kind !== "noop") {
    fail("stale_cross_run_refusal_is_noop_not_a_write", JSON.stringify(refusedCommit));
  } else pass("stale_cross_run_refusal_is_noop_not_a_write");

  // A current-lease cross-run refusal is a named refusal, not a flatten.
  const liveRefusal = commitParagraphClick(crossPrep, state);
  if (liveRefusal.kind !== "refused" || liveRefusal.overlayPick.refusal !== "cross_run") {
    fail("current_cross_run_commit_names_refusal", JSON.stringify(liveRefusal));
  } else pass("current_cross_run_commit_names_refusal");

  if (process.exitCode) {
    console.error("desktop run-scoped-edit harness failed");
  } else {
    console.log("desktop run-scoped-edit harness passed");
  }
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 2;
});

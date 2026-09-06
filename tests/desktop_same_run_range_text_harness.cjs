/* Same-run sequential edit: the splice base must be the text the range was
 * measured against.
 *
 * `prepareParagraphEdit` measures `rangeStart`/`rangeEnd` against the run
 * text the runtime returned for the DISPLAYED revision. `before`, however, is
 * the A→B baseline of the op — when a `set_run` is already queued on the run
 * it is overridden with that op's `before`. The two strings are the same
 * only while the page shows exactly the revision the first edit was opened
 * against. Whenever they differ (head moved under a persisted queue, or a
 * candidate that already carries the earlier text), splicing into `before`
 * with offsets measured on the displayed text lands at a stale position.
 *
 * Contract under test:
 *   - the caret effect / inline edit carries `rangeText` = displayed run text
 *   - `runTextAfterEdit` splices into `rangeText`, never into `before`
 *   - `fieldTextForRunEdit` shows the slice of `rangeText`
 *
 * Runs through the real `prepareParagraphEdit` -> `commitParagraphClick`
 * path in desktop/src/revision.ts. No Tauri, no React.
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

const revision = loadTs("desktop/src/revision.ts");
const { captureEditLease, commitParagraphClick, prepareParagraphEdit } = revision;
const { fieldTextForRunEdit } = loadTs("desktop/src/run_map.ts");

function fail(name, detail) {
  console.error(`FAIL ${name}: ${detail}`);
  process.exitCode = 1;
}
function pass(name) {
  console.log(`PASS ${name}`);
}
function eq(name, got, want) {
  if (got !== want) fail(name, `got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
  else pass(name);
}

const runTextAfterEdit = revision.runTextAfterEdit;
const hasSplice = typeof runTextAfterEdit === "function";
if (!hasSplice) {
  fail("run_text_after_edit_exported", "revision.ts does not export runTextAfterEdit");
}

const geometry = {
  source: { runId: "candidate-a", sha256: "pdf-sha", candidateSha256: "candidate-sha" },
  subject: { kind: "candidate", runId: "candidate-a", sha256: "candidate-sha" },
};
const state = {
  activeSessionId: "s1",
  editIntentGeneration: 7,
  geometry,
  render: { source: { runId: "candidate-a" } },
  sessions: [{ sessionId: "s1", source: { sha256: "source-sha" } }],
};
const regionOf = (runs) => async () => ({
  subject: { kind: "candidate", runId: "candidate-a", sha256: "candidate-sha" },
  regions: [{ at_para: 3, runs }],
});

/** Click `spanText` in a paragraph whose displayed run reads `displayed`,
 *  with `queuedBefore` as the baseline a queued op already recorded. */
async function click(displayed, spanText, queuedBefore) {
  const lease = captureEditLease(state, 3, 7);
  const effect = await prepareParagraphEdit({
    lease,
    spanText,
    spanIndex: 0,
    caret: 0,
    address: { kind: "anchor", atPara: 3 },
    readRegion: regionOf([{ index: 0, text: displayed }]),
    queuedBefore,
  });
  const commit = commitParagraphClick(effect, state);
  if (commit.kind !== "caret") throw new Error(`expected caret, got ${JSON.stringify(commit)}`);
  return commit.inlineEdit;
}

(async () => {
  // -------------------------------------------------------------------------
  // (1) Displayed text differs from the queued baseline. Offsets are measured
  //     on the displayed text; the splice must land there.
  // -------------------------------------------------------------------------
  {
    const edit = await click("Hi there World", "World", "Hello World");
    eq("moved_head_range_measured_on_displayed_text",
      `${edit.rangeStart}..${edit.rangeEnd}`, "9..14");
    eq("moved_head_before_is_queued_baseline", edit.before, "Hello World");
    eq("moved_head_range_text_is_displayed_text", edit.rangeText, "Hi there World");
    eq("moved_head_field_shows_clicked_line",
      fieldTextForRunEdit(edit.rangeText ?? edit.before, edit.rangeStart, edit.rangeEnd),
      "World");
    if (hasSplice) {
      eq("moved_head_splice_lands_on_displayed_text",
        runTextAfterEdit(edit, "Earth"), "Hi there Earth");
    }
  }

  // -------------------------------------------------------------------------
  // (2) Same run edited twice while the page still shows the source. The
  //     second click measures against the source text; `before` stays the
  //     op baseline; the result replaces the first op relative to that text.
  // -------------------------------------------------------------------------
  {
    const edit = await click("Hello World", "World", "Hello World");
    eq("same_run_second_edit_range", `${edit.rangeStart}..${edit.rangeEnd}`, "6..11");
    eq("same_run_second_edit_range_text", edit.rangeText, "Hello World");
    if (hasSplice) {
      eq("same_run_second_edit_result", runTextAfterEdit(edit, "Earth"), "Hello Earth");
    }
  }

  // -------------------------------------------------------------------------
  // (3) No queued op: `before` and `rangeText` are the same displayed text.
  // -------------------------------------------------------------------------
  {
    const edit = await click("Hello World", "Hello", null);
    eq("fresh_edit_before_equals_range_text", edit.before, edit.rangeText);
    if (hasSplice) {
      eq("fresh_edit_result", runTextAfterEdit(edit, "Hi"), "Hi World");
    }
  }

  // -------------------------------------------------------------------------
  // (4) UTF-16: displayed text carries a surrogate pair before the clicked
  //     line and the baseline does not. Offsets are code units of rangeText.
  // -------------------------------------------------------------------------
  {
    const edit = await click("a\u{1F600}b 안녕 World", "World", "ab 안녕 World");
    eq("utf16_range_measured_on_displayed_text",
      `${edit.rangeStart}..${edit.rangeEnd}`, "8..13");
    if (hasSplice) {
      eq("utf16_splice_keeps_surrogate_pair",
        runTextAfterEdit(edit, "지구"), "a\u{1F600}b 안녕 지구");
    }
  }

  // -------------------------------------------------------------------------
  // (5) Fallbacks: no measured range replaces the whole displayed run; no
  //     rangeText (legacy shape) falls back to `before`.
  // -------------------------------------------------------------------------
  if (hasSplice) {
    eq("no_range_replaces_whole_displayed_run",
      runTextAfterEdit({ before: "Hello World", rangeText: "Hi World" }, "X"), "X");
    eq("no_range_text_falls_back_to_before",
      runTextAfterEdit({ before: "Hello World", rangeStart: 6, rangeEnd: 11 }, "Earth"),
      "Hello Earth");
  }

  if (process.exitCode) console.error("desktop same-run range-text harness FAILED");
  else console.log("desktop same-run range-text harness passed");
})().catch((e) => {
  fail("harness", e && e.stack ? e.stack : String(e));
  console.error("desktop same-run range-text harness FAILED");
});

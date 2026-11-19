// WP2 C0 contracts: key registry (IME guard, editable targets, conflicts),
// slots, per-document slices, i18n/v2 tables.
import assert from "node:assert/strict";
import test from "node:test";

const keysMod = await import("../src/shell/keys.ts");
const slots = await import("../src/shell/slots.ts");
const docStore = await import("../src/store.ts");
const v2 = await import("../src/i18n/v2/index.ts");
const { S } = await import("../src/i18n/v2/shell.ts");

const { register, dispatch, defineContext, conflicts, keyHint, chordCaps, _resetForTest, isComposingEvent } = keysMod;

function ev(code, opts = {}) {
  let prevented = false;
  return {
    code,
    key: opts.key ?? "",
    ctrlKey: !!opts.ctrl,
    altKey: !!opts.alt,
    shiftKey: !!opts.shift,
    metaKey: !!opts.meta,
    isComposing: !!opts.composing,
    keyCode: opts.keyCode ?? 0,
    target: opts.target ?? null,
    preventDefault() {
      prevented = true;
    },
    get prevented() {
      return prevented;
    },
  };
}

const INPUT = { tagName: "INPUT", type: "text" };
const TEXTAREA = { tagName: "TEXTAREA" };
const EDITABLE_DIV = { tagName: "DIV", isContentEditable: true };
const BUTTON = { tagName: "BUTTON" };

test("Korean composition never triggers Y/N/E/U/J/K or anything else", () => {
  _resetForTest();
  defineContext("review", () => true);
  const fired = [];
  for (const [id, key] of [["accept", "Y"], ["exclude", "N"], ["edit", "E"], ["undecide", "U"], ["next", "J"], ["prev", "K"]]) {
    register({ id, chords: [key], when: "review", run: () => fired.push(id) });
  }
  register({ id: "palette", chords: ["Ctrl+K"], run: () => fired.push("palette") });
  for (const code of ["KeyY", "KeyN", "KeyE", "KeyU", "KeyJ", "KeyK"]) {
    assert.equal(dispatch(ev(code, { composing: true, key: "Process" })), false);
    assert.equal(dispatch(ev(code, { keyCode: 229, key: "Process" })), false);
  }
  assert.equal(dispatch(ev("KeyK", { ctrl: true, composing: true })), false);
  assert.deepEqual(fired, []);
  assert.equal(isComposingEvent({ code: "KeyA", keyCode: 229 }), true);
  // Out of composition the same physical keys fire, whatever the 한/영 state (key = 'ㅛ').
  assert.equal(dispatch(ev("KeyY", { key: "ㅛ" })), true);
  assert.deepEqual(fired, ["accept"]);
});

test("single keys are blocked in editable targets; modifier chords are not", () => {
  _resetForTest();
  const fired = [];
  register({ id: "next", chords: ["J"], run: () => fired.push("J") });
  register({ id: "palette", chords: ["Ctrl+K"], run: () => fired.push("palette") });
  register({ id: "undo", chords: ["Ctrl+Z"], inEditable: false, run: () => fired.push("undo") });
  register({ id: "settings", chords: ["F8"], run: () => fired.push("F8") });
  for (const target of [INPUT, TEXTAREA, EDITABLE_DIV]) {
    assert.equal(dispatch(ev("KeyJ", { target })), false);
    assert.equal(dispatch(ev("KeyZ", { ctrl: true, target })), false);
  }
  assert.deepEqual(fired, []);
  assert.equal(dispatch(ev("KeyK", { ctrl: true, target: INPUT })), true);
  assert.equal(dispatch(ev("F8", { target: INPUT })), true);
  assert.equal(dispatch(ev("KeyJ", { target: BUTTON })), true);
  assert.equal(dispatch(ev("KeyJ", { target: { tagName: "INPUT", type: "checkbox" } })), true);
  assert.deepEqual(fired, ["palette", "F8", "J", "J"]);
});

test("Ctrl+Shift+P and Ctrl+K both reach the palette; matching is by physical key", () => {
  _resetForTest();
  let opened = 0;
  register({ id: "shell.palette", chords: ["Ctrl+K", "Ctrl+Shift+P"], run: () => { opened += 1; } });
  const e = ev("KeyP", { ctrl: true, shift: true, key: "ㅔ" });
  assert.equal(dispatch(e), true);
  assert.equal(e.prevented, true);
  assert.equal(dispatch(ev("KeyK", { meta: true })), true);
  assert.equal(dispatch(ev("KeyP", { ctrl: true })), false);
  assert.equal(opened, 2);
  assert.deepEqual(keyHint("shell.palette"), ["Ctrl", "K"]);
});

test("scoped bindings apply only while their context is active and win over global ones", () => {
  _resetForTest();
  let review = false;
  defineContext("review", () => review);
  const fired = [];
  register({ id: "g.enter", chords: ["Enter"], run: () => fired.push("global") });
  register({ id: "r.enter", chords: ["Enter"], when: "review", run: () => fired.push("review") });
  dispatch(ev("Enter"));
  review = true;
  dispatch(ev("NumpadEnter"));
  assert.deepEqual(fired, ["global", "review"]);
});

test("a binding returning false lets the key through", () => {
  _resetForTest();
  register({ id: "maybe", chords: ["Escape"], run: () => false });
  const e = ev("Escape");
  assert.equal(dispatch(e), false);
  assert.equal(e.prevented, false);
});

test("two-stroke chords are supported by the type and the dispatcher", () => {
  _resetForTest();
  const fired = [];
  register({ id: "two", chords: ["Ctrl+K Ctrl+S"], run: () => fired.push("two") });
  assert.equal(dispatch(ev("KeyK", { ctrl: true }), 1000), true);
  assert.equal(dispatch(ev("KeyS", { ctrl: true }), 1200), true);
  assert.deepEqual(fired, ["two"]);
  // Times out.
  dispatch(ev("KeyK", { ctrl: true }), 5000);
  assert.equal(dispatch(ev("KeyS", { ctrl: true }), 9000), false);
  assert.deepEqual(chordCaps("Ctrl+K Ctrl+S"), ["Ctrl", "K", " ", "Ctrl", "S"]);
});

test("conflicts() reports duplicates and prefix clashes in one scope", () => {
  _resetForTest();
  register({ id: "a", chords: ["Ctrl+K"], run() {} });
  register({ id: "b", chords: ["Ctrl+K"], run() {} });
  register({ id: "c", chords: ["Y"], when: "review", run() {} });
  register({ id: "d", chords: ["Y"], when: "sheet", run() {} });
  register({ id: "e", chords: ["Ctrl+K Ctrl+S"], run() {} });
  const found = conflicts().map((c) => c.ids.sort().join("+")).sort();
  assert.deepEqual(found, ["a+b", "a+e", "b+e"]);
});

test("the shell keymap has no duplicate chords", async () => {
  _resetForTest();
  const { SHELL_BINDINGS } = await import("../src/shell/keymap.ts");
  const stub = SHELL_BINDINGS.map((b) => ({ ...b, run() {} }));
  for (const b of stub) register(b);
  assert.deepEqual(conflicts(), []);
  // J1: Ctrl+Shift+P is a permanent alias of the palette.
  const palette = stub.find((b) => b.id === "shell.palette");
  assert.ok(palette.chords.includes("Ctrl+K") && palette.chords.includes("Ctrl+Shift+P"));
  // Every chord parses.
  for (const b of stub) for (const c of [...b.chords, ...(b.browserChords ?? [])]) chordCaps(c);
});

test("slots: register, order, single occupancy, unregister", () => {
  slots._resetSlotsForTest();
  const A = () => null;
  const B = () => null;
  const off = slots.registerSlot("statusRight", A, { order: 50 });
  slots.registerSlot("statusRight", B, { order: 10 });
  assert.deepEqual(slots.slotEntries("statusRight").map((e) => e.component), [B, A]);
  slots.registerSlot("canvas", A);
  slots.registerSlot("canvas", B);
  assert.equal(slots.slotEntries("canvas").length, 1);
  slots.registerSlot("pane:outline", A);
  slots.registerSlot("settings:agent", B);
  assert.deepEqual(slots.slotNames("pane:"), ["pane:outline"]);
  // Re-registering the same component is a no-op (HMR).
  slots.registerSlot("statusRight", A);
  assert.equal(slots.slotEntries("statusRight").length, 2);
  off();
  assert.deepEqual(slots.slotEntries("statusRight").map((e) => e.component), [B]);
  assert.throws(() => slots.registerSlot("sidebar", A));
  assert.throws(() => slots.registerSlot("pane:", A));
});

test("document B shows none of document A's slice state", () => {
  docStore._resetDocsForTest();
  docStore.setState({ activeSessionId: "doc-a" });
  assert.equal(docStore.activeDocId(), "doc-a");
  const decisions = docStore.defineDocSlice("test.decisions", () => ({ accepted: [], excluded: [] }));
  const zoom = docStore.defineDocSlice("test.zoom", 1);
  decisions.patch("doc-a", { accepted: ["1", "2", "3"] });
  zoom.set("doc-a", 1.25);
  assert.deepEqual(decisions.get("doc-b"), { accepted: [], excluded: [] });
  assert.equal(zoom.get("doc-b"), 1);
  assert.deepEqual(decisions.get("doc-a").accepted, ["1", "2", "3"]);
  // Initial values are per document, so mutating one never leaks.
  decisions.get("doc-b").accepted.push("x");
  assert.deepEqual(decisions.get("doc-c").accepted, []);
  assert.notEqual(decisions.get("doc-b"), decisions.get("doc-c"));
  // Reference-stable reads (useSyncExternalStore requires it).
  assert.equal(decisions.get("doc-b"), decisions.get("doc-b"));
  // Updater form and reset.
  zoom.set("doc-b", (z) => z + 0.5);
  assert.equal(zoom.get("doc-b"), 1.5);
  zoom.reset("doc-b");
  assert.equal(zoom.get("doc-b"), 1);
  // Dropping A forgets it.
  docStore.dropDoc("doc-a");
  assert.equal(docStore.getDoc("doc-a"), null);
  assert.deepEqual(decisions.get("doc-a").accepted, []);
  assert.throws(() => docStore.defineDocSlice("test.zoom", 2));
});

test("doc slices: object slices merge, undefined means the active document, null is no document", () => {
  docStore._resetDocsForTest();
  docStore.setState({ activeSessionId: "doc-x" });
  const panel = docStore.defineDocSlice("test.panel", { tab: "agent", sheetOpen: false });
  panel.set(undefined, { tab: "changes" });
  assert.deepEqual(panel.get("doc-x"), { tab: "changes", sheetOpen: false });
  panel.set("doc-x", (prev) => ({ sheetOpen: !prev.sheetOpen }));
  assert.deepEqual(panel.get(), { tab: "changes", sheetOpen: true });
  panel.set(null, { tab: "checks" });
  assert.equal(panel.get(null).tab, "checks");
  assert.equal(panel.get("doc-y").tab, "agent");
  assert.equal(docStore.getDoc(null), null);
  assert.equal(docStore.getDoc("doc-x").slices["test.panel"].tab, "changes");
  assert.equal(docStore.getDoc("doc-x"), docStore.getDoc("doc-x"));
});

test("store.ts re-exports the doc API and binds the active session", async () => {
  const store = await import("../src/store.ts");
  for (const name of ["defineDocSlice", "useDoc", "useActiveDoc", "dropDoc", "ensureDoc", "getDoc"]) {
    assert.equal(typeof store[name], "function", name);
  }
});

test("i18n/v2: shell table has ko/en parity, no Latin in Korean outside names and keys", () => {
  const ALLOWED = /Rigorloom|\.hwpx|\.hwp|\.docx|\.md|PDF|HWPX|A4|Ctrl|Shift|Alt|Enter|Esc|Tab|F\d+/g;
  for (const [key, entry] of Object.entries(S.table)) {
    assert.ok(entry.ko && entry.en, key);
    assert.doesNotMatch(entry.ko.replace(ALLOWED, ""), /[A-Za-z]/, `${key}: ${entry.ko}`);
    assert.doesNotMatch(entry.ko, /[\u{1F300}-\u{1FAFF}]/u, key);
    assert.doesNotMatch(entry.ko, /!/, key);
    // No particle glued to a placeholder (C-copy §1).
    assert.doesNotMatch(entry.ko, /\}(이|가|을|를|은|는|과|와|의|로|으로|에|에서)(?![가-힣])/, `${key}: ${entry.ko}`);
    for (const banned of ["진행합니다", "하는 것이 가능", "해당 ", "에 대한", "되어집"]) {
      assert.ok(!entry.ko.includes(banned), `${key}: ${banned}`);
    }
    const ph = (s) => [...s.matchAll(/\{[^}]+\}/g)].map((m) => m[0]).sort().join();
    assert.equal(ph(entry.ko), ph(entry.en), `${key} placeholders`);
  }
  assert.equal(S.t("shell_tab_close", "ko", ["기안문"]), "탭 닫기 · 기안문");
  assert.throws(() => v2.defineStrings("other", { shell_tab_close: { ko: "x", en: "x" } }));
});

test("i18n/v2: no v2 key collides with vocabulary.ts", async () => {
  const { VOCABULARY } = await import("../src/i18n/vocabulary.ts");
  for (const [wp, table] of v2.allStringTables()) {
    for (const key of Object.keys(table)) {
      assert.ok(!(key in VOCABULARY), `${wp}.${key} collides with vocabulary.ts`);
    }
  }
});

test("keys accept the shapes WP3 and WP4 register: predicate when, code names, 'always'", () => {
  _resetForTest();
  const fired = [];
  let reviewing = false;
  register({ id: "change.accept", chords: ["Y"], when: () => reviewing, run: () => fired.push("Y") });
  register({ id: "canvas.cycleView", chords: ["KeyV"], run: () => fired.push("V") });
  register({ id: "canvas.zoomIn", chords: ["Ctrl+Equal", "Ctrl+Shift+Equal"], when: "always", run: () => fired.push("zoom") });
  register({ id: "canvas.async", chords: ["F9"], run: async () => fired.push("async") });
  dispatch(ev("KeyY"));
  reviewing = true;
  dispatch(ev("KeyY"));
  dispatch(ev("KeyV", { target: INPUT }));
  dispatch(ev("KeyV"));
  dispatch(ev("NumpadAdd", { ctrl: true }));
  dispatch(ev("Equal", { ctrl: true, shift: true }));
  assert.equal(dispatch(ev("F9")), true);
  assert.deepEqual(fired, ["Y", "V", "zoom", "zoom", "async"]);
  // Predicate-scoped bindings are scopes of their own for the conflict check.
  register({ id: "canvas.accept", chords: ["Y"], when: () => true, run() {} });
  assert.deepEqual(conflicts(), []);
  // ... but when both predicates hold at once, the live check names the clash.
  assert.deepEqual(keysMod.activeConflicts().map((c) => c.ids.sort().join("+")), ["canvas.accept+change.accept"]);
  reviewing = false;
  assert.deepEqual(keysMod.activeConflicts(), []);
});

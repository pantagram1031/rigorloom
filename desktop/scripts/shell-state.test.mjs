// WP2 shell state: tab arithmetic, the one-docked rule, breakpoints, and
// per-document chrome that never leaks between documents.
import assert from "node:assert/strict";
import test from "node:test";

const sh = await import("../src/shell/shellState.ts");
const store = await import("../src/store.ts");

const base = () => ({ ...sh.getShell(), tabs: [{ kind: "start", id: "start" }], activeTab: "start" });

test("the first document replaces the Start tab it was opened from", () => {
  const s = sh.withDocTab(base(), "A");
  assert.deepEqual(s.tabs.map((t) => t.id), ["doc:A"]);
  assert.equal(s.activeTab, "doc:A");
  const s2 = sh.withDocTab(s, "B");
  assert.deepEqual(s2.tabs.map((t) => t.id), ["doc:A", "doc:B"]);
  // Re-opening an open document activates it, never duplicates it.
  const s3 = sh.withDocTab(s2, "A");
  assert.deepEqual(s3.tabs.map((t) => t.id), ["doc:A", "doc:B"]);
  assert.equal(s3.activeTab, "doc:A");
});

test("an opening tab is replaced in place by its document", () => {
  let s = base();
  s = { ...s, tabs: [{ kind: "doc", id: "doc:A", sessionId: "A" }, { kind: "opening", id: "opening:1", name: "x.hwpx" }], activeTab: "opening:1" };
  const next = sh.withDocTab(s, "B", { replaceId: "opening:1" });
  assert.deepEqual(next.tabs.map((t) => t.id), ["doc:A", "doc:B"]);
});

test("a preview tab is reused by the next single click and pinned by a double-click", () => {
  let s = sh.withDocTab(base(), "A");
  s = sh.withDocTab(s, "P1", { preview: true });
  s = sh.withDocTab(s, "P2", { preview: true });
  assert.deepEqual(s.tabs.map((t) => t.id), ["doc:A", "doc:P2"]);
  s = sh.withTabPinned(s, "doc:P2");
  s = sh.withDocTab(s, "P3", { preview: true });
  assert.deepEqual(s.tabs.map((t) => t.id), ["doc:A", "doc:P2", "doc:P3"]);
});

test("closing the active tab activates its neighbour; closing the last leaves Start", () => {
  let s = sh.withDocTab(base(), "A");
  s = sh.withDocTab(s, "B");
  s = sh.withDocTab(s, "C");
  s = { ...s, activeTab: "doc:B" };
  s = sh.withTabClosed(s, "doc:B");
  assert.equal(s.activeTab, "doc:C");
  s = sh.withTabClosed(sh.withTabClosed(s, "doc:C"), "doc:A");
  assert.deepEqual(s.tabs.map((t) => t.id), ["start"]);
  assert.equal(s.activeTab, "start");
});

test("tab stepping wraps", () => {
  let s = sh.withDocTab(base(), "A");
  s = sh.withDocTab(s, "B");
  assert.equal(sh.withTabStep(s, 1).activeTab, "doc:A");
  assert.equal(sh.withTabStep(s, -1).activeTab, "doc:A");
});

test("breakpoints follow J1: 1360 both, 900 one, 600 overlay, below narrow", () => {
  assert.equal(sh.breakpointFor(1440), "wide");
  assert.equal(sh.breakpointFor(1360), "wide");
  assert.equal(sh.breakpointFor(1280), "medium");
  assert.equal(sh.breakpointFor(900), "medium");
  assert.equal(sh.breakpointFor(899), "overlay");
  assert.equal(sh.breakpointFor(390), "narrow");
  assert.deepEqual(sh.sideWidths("wide"), { left: 240, right: 360 });
  assert.deepEqual(sh.sideWidths("medium"), { left: 240, right: 340 });
});

test("below 1360 only one side docks: opening the left hides the right and the reverse", () => {
  const both = { leftOpen: true, rightOpen: true };
  assert.deepEqual(sh.dockedSides("wide", { ...both, lastOpened: "left" }, true), { left: true, right: true });
  // 1280 default: right panel docked, left closed.
  assert.deepEqual(sh.dockedSides("medium", { ...both, lastOpened: "right" }, true), { left: false, right: true });
  assert.deepEqual(sh.dockedSides("medium", { ...both, lastOpened: "left" }, true), { left: true, right: false });
  assert.deepEqual(sh.dockedSides("medium", { leftOpen: false, rightOpen: true, lastOpened: "left" }, true), { left: false, right: true });
  // No document: no right panel.
  assert.deepEqual(sh.dockedSides("wide", { ...both, lastOpened: "right" }, false), { left: true, right: false });
  assert.deepEqual(sh.dockedSides("narrow", { ...both, lastOpened: "right" }, true), { left: false, right: false });
});

test("per-document chrome: document B never shows document A's pane or panel tab", () => {
  sh.docLayout.patch("A", { leftPane: "find", rightTab: "changes", landed: true });
  assert.deepEqual(sh.docLayout.get("B"), { leftPane: "outline", rightTab: "agent", landed: false });
  assert.equal(sh.docLayout.get("A").leftPane, "find");
  store.dropDoc("A");
});

test("a document's queued changes never count on another document's tab", async () => {
  const { pendingCount } = await import("../src/shell/counts.ts");
  const s = store.getState();
  const withDraft = { ...s, draft: { ...s.draft, sessionId: "A", ops: [{ opId: "1" }, { opId: "2" }] } };
  assert.equal(pendingCount(withDraft, "A"), 2);
  assert.equal(pendingCount(withDraft, "B"), 0);
  // Trust parks other documents' queues per session; each reads its own.
  const parked = { ...withDraft, parkedDrafts: { B: { ops: [{ opId: "x" }] } } };
  assert.equal(pendingCount(parked, "B"), 1);
  assert.equal(pendingCount(parked, "C"), 0);
});

// WP4: key handling under IME composition, the adapter, and the return payload.
import assert from "node:assert/strict";
import test from "node:test";

const keys = await import("../src/panel/keys.ts");
const adapter = await import("../src/panel/adapter.ts");
const ret = await import("../src/panel/returnCall.ts");
const model = await import("../src/model/changes.ts");

function key(code, extra = {}) {
  const letter = code.startsWith("Key") ? code.slice(3).toLowerCase() : code;
  return {
    code,
    key: extra.key ?? letter,
    ctrlKey: false,
    shiftKey: false,
    altKey: false,
    metaKey: false,
    target: null,
    isComposing: false,
    keyCode: 0,
    ...extra,
  };
}

test("Korean composition never triggers Y/N/E/U/J/K", () => {
  for (const code of ["KeyY", "KeyN", "KeyE", "KeyU", "KeyJ", "KeyK", "KeyR"]) {
    // 두벌식: Y is ㅛ, N is ㅜ ... composing either way.
    assert.equal(keys.matchPanelKey(key(code, { key: "ㅛ", isComposing: true })), null, code);
    assert.equal(keys.matchPanelKey(key(code, { key: "Process", keyCode: 229 })), null, code);
  }
  // Ctrl+Shift+Enter while composing does not approve either.
  assert.equal(keys.matchPanelKey(key("Enter", { key: "Enter", ctrlKey: true, shiftKey: true, isComposing: true })), null);
});

test("letters match the physical key whatever the 한/영 state", () => {
  assert.equal(keys.matchPanelKey(key("KeyY", { key: "ㅛ" })), "change.accept");
  assert.equal(keys.matchPanelKey(key("KeyN", { key: "ㅜ" })), "change.reject");
  assert.equal(keys.matchPanelKey(key("KeyJ", { key: "ㅓ" })), "change.next");
  assert.equal(keys.matchPanelKey(key("KeyK", { key: "ㅏ" })), "change.prev");
  assert.equal(keys.matchPanelKey(key("KeyE", { key: "ㄷ" })), "change.edit");
  assert.equal(keys.matchPanelKey(key("KeyU", { key: "ㅕ" })), "change.undo");
  // Shift+Y is not Y.
  assert.equal(keys.matchPanelKey(key("KeyY", { shiftKey: true })), null);
});

test("single keys never fire in an editable target", () => {
  const input = { tagName: "INPUT", type: "text" };
  const area = { tagName: "TEXTAREA" };
  const editable = { tagName: "DIV", isContentEditable: true };
  const checkbox = { tagName: "INPUT", type: "checkbox" };
  for (const target of [input, area, editable]) {
    assert.equal(keys.matchPanelKey(key("KeyY", { target })), null);
    assert.equal(keys.matchPanelKey(key("KeyN", { target })), null);
  }
  assert.equal(keys.matchPanelKey(key("KeyY", { target: checkbox })), "change.accept");
  // Chords still work from the composer.
  assert.equal(keys.matchPanelKey(key("Enter", { key: "Enter", ctrlKey: true, shiftKey: true, target: area })), "approval.open");
  assert.equal(keys.matchPanelKey(key("KeyL", { ctrlKey: true, target: area })), "composer.focus");
});

test("the approve chord is Ctrl+Shift+Enter, never A or Ctrl+Enter", () => {
  assert.equal(keys.matchPanelKey(key("Enter", { key: "Enter", ctrlKey: true, shiftKey: true })), "approval.open");
  assert.equal(keys.matchPanelKey(key("Enter", { key: "Enter", ctrlKey: true })), null);
  assert.equal(keys.matchPanelKey(key("KeyA")), null);
  assert.equal(keys.matchPanelKey(key("Delete", { key: "Delete" })), null);
});

test("no chord is bound twice", () => {
  const seen = new Map();
  for (const [id, chords] of Object.entries(keys.PANEL_CHORDS)) {
    for (const chord of chords) {
      assert.equal(seen.has(chord), false, `${chord} bound to ${seen.get(chord)} and ${id}`);
      seen.set(chord, id);
    }
  }
});

test("the return reason is stored as the reason, never as the approver", async () => {
  const binding = { approvalId: "ap-1", planId: "pl-1", planHash: "h".repeat(64) };
  const payload = ret.returnPayload(binding, "  날짜를 다시 확인해 주세요. ");
  assert.equal(payload.reason, "날짜를 다시 확인해 주세요.");
  assert.equal(payload.approver, "host-operator");
  assert.equal(payload.decision, "rejected");
  assert.equal("reason" in ret.returnPayload(binding, "   "), false);

  const calls = [];
  const call = async (method, params) => {
    calls.push({ method, params });
    return { approval: { state: "rejected", approver: params.approver, reason: params.reason ?? null } };
  };
  const r = await ret.resolveReturnWith(call, binding, "표 제목이 틀렸습니다");
  assert.equal(r.reasonStored, true);
  assert.equal(calls[0].method, "approval/resolve");
  assert.equal(calls[0].params.reason, "표 제목이 틀렸습니다");
  assert.equal(calls[0].params.approver, "host-operator");

  // A runtime without the field refuses it; the reason is dropped, never moved.
  const strictCalls = [];
  const strict = async (method, params) => {
    strictCalls.push(params);
    if ("reason" in params) throw { code: "unknown_field", message: "unknown" };
    return { approval: { state: "rejected", approver: params.approver } };
  };
  const r2 = await ret.resolveReturnWith(strict, binding, "이유");
  assert.equal(r2.reasonStored, false);
  assert.equal(strictCalls[1].approver, "host-operator");
  assert.equal(JSON.stringify(strictCalls[1]).includes("이유"), false);
});

function indexed(n, op, extra = {}) {
  return {
    ordinal: n,
    originalIndex: n - 1,
    op,
    opId: op.opId,
    fieldLabel: extra.label ?? `칸 ${n}`,
    opKindText: extra.opKindText ?? "빈칸 채움",
    beforeText: extra.before ?? "",
    afterText: extra.after ?? op.text ?? "",
    targetKey: null,
    hardFindings: extra.hard ?? [],
    warnFindings: [],
    hasHardFailure: Boolean(extra.hard?.length),
    isAuditable: extra.auditable ?? true,
    isEmptyBlankFill: (extra.before ?? "") === "",
    previewMode: "diff",
    invertible: true,
  };
}

function input(changes, extra = {}) {
  return {
    language: "ko",
    changes,
    guard: null,
    plan: { planId: "pl-1", planHash: "a".repeat(64), boundSha256: "b".repeat(64), base: null, reverses: null, proposer: "gongmun-walkthrough", createdUtc: "2026-11-19T05:13:00Z" },
    validation: { ok: true, stale: false, hard: [], warn: [] },
    baseRevision: 0,
    baseSha256: "",
    currentRevision: 0,
    stale: null,
    mock: false,
    provider: null,
    ...extra,
  };
}

test("adapter maps addresses, kinds and sources onto ChangeItem", () => {
  const fill = { opId: "op-5", kind: "replace_at_cell", table: 0, row: 1, col: 0, run: 0, mode: "replace", text: "가온공공기록원", before: "", origin: "agent" };
  const del = { opId: "op-1", kind: "replace_at_cell", table: 0, row: 0, col: 0, run: 0, mode: "replace", text: "", before: "[별지 제1호서식]", origin: "agent" };
  const typed = { opId: "op-u", kind: "fill_cell", table: 0, row: 4, col: 0, text: "주무관", before: "", origin: "user" };
  const view = adapter.fromWorkspace(
    input([
      indexed(1, del, { before: "[별지 제1호서식]", after: "", opKindText: "기호 지움" }),
      indexed(2, fill),
      indexed(3, typed),
    ]),
  );
  assert.equal(view.items[0].at, "t0/r0/c0");
  assert.equal(view.items[0].kind, "delete");
  assert.equal(view.items[1].kind, "fill");
  assert.equal(view.items[1].source, "agent");
  assert.equal(view.items[1].decision, "pending");
  assert.equal(view.items[2].source, "user");
  assert.equal(view.items[2].decision, "accepted");
  assert.equal(view.items[0].group, "t0/r0");
  assert.equal(view.base.revision, 0);
  assert.equal(view.stale, null);
  // Without a guard result nothing is claimed, and 승인 waits for the check.
  assert.equal(view.items[1].guard.status, "none");
  assert.equal(view.checking, true);
  const decided = { ...view, items: view.items.map((it) => ({ ...it, decision: "accepted" })) };
  assert.deepEqual(model.gateState(decided).block, { kind: "checking" });
});

test("adapter labels every item 시험용 when the plan is a test plan", () => {
  const op = { opId: "op-5", kind: "fill_cell", table: 0, row: 1, col: 0, text: "x", before: "", origin: "agent" };
  assert.equal(adapter.planIsMock({ proposer: "agenthost-mock" }), true);
  assert.equal(adapter.planIsMock({ proposer: "rigorloom-mock-agent" }), true);
  assert.equal(adapter.planIsMock({ proposer: "gongmun-walkthrough", provenance: "mock" }), true);
  assert.equal(adapter.planIsMock({ proposer: "gongmun-walkthrough" }), false);
  const view = adapter.fromWorkspace(input([indexed(1, op)], { mock: true }));
  assert.equal(view.items[0].source, "test");
  assert.equal(view.provenance.mock, true);
  const accepted = { ...view, items: view.items.map((it) => ({ ...it, decision: "accepted" })) };
  assert.deepEqual(model.requiredTicks(accepted), ["test"]);
});

test("adapter: a plan behind the head is stale, and that disables the gate", () => {
  assert.equal(adapter.staleFromValidation({ hard: [{ code: "plan_behind_head", msg: "", at: "plan" }], stale: false }), "plan_behind_head");
  assert.equal(adapter.staleFromValidation({ hard: [], stale: true }), "source_changed");
  const op = { opId: "op-5", kind: "fill_cell", table: 0, row: 1, col: 0, text: "x", before: "", origin: "agent" };
  const view = adapter.fromWorkspace(input([indexed(1, op)], { stale: "superseded_by_newer_candidate", currentRevision: 2 }));
  assert.deepEqual(view.stale, { reason: "superseded_by_newer_candidate", current: 2 });
  assert.equal(model.canDecide(view), false);
});

test("adapter: guard facts split into 바뀐 사실 and expected", () => {
  const typed = { opId: "op-9", kind: "fill_cell", table: 0, row: 6, col: 1, text: "기록정책과-104(2026. 11. 15.)", before: "", origin: "agent" };
  const ch = indexed(1, typed);
  const paraAdded = {
    paragraph: 3, pass: false, kinds: ["dates"], changes: [], before: "", after: "기록정책과-104(2026. 11. 15.)",
    beforeProtected: [], afterProtected: [{ start: 9, end: 23, kind: "dates", text: "2026. 11. 15.", status: "added" }],
  };
  const summary = (para, status = "changed", id = ch.opId) => ({
    state: "ready", planId: "pl-1", documentDiff: null, rowAudits: { [id]: { status, paragraph: para, addedNumbers: [] } },
    changedFactOpIds: [], needsFixesOpIds: [], errorCode: null,
  });
  // A date typed into an empty blank is expected.
  let g = adapter.guardOf(ch, "fill", summary(paraAdded));
  assert.equal(g.status, "expected");
  // A date that turned into another date is a changed fact.
  const replaced = indexed(1, { ...typed, opId: "op-9" }, { before: "계약 시작일 2026년 1월 1일" });
  const paraChanged = {
    paragraph: 4, pass: false, kinds: ["dates"], changes: [], before: "계약 시작일 2026년 1월 1일", after: "계약 시작일 2027년 1월 1일",
    beforeProtected: [{ start: 7, end: 18, kind: "dates", text: "2026년 1월 1일", status: "removed" }],
    afterProtected: [{ start: 7, end: 18, kind: "dates", text: "2027년 1월 1일", status: "added" }],
  };
  g = adapter.guardOf({ ...replaced, isEmptyBlankFill: false }, "replace", summary(paraChanged));
  assert.equal(g.status, "changed");
  assert.deepEqual([g.facts[0].before, g.facts[0].after], ["2026년 1월 1일", "2027년 1월 1일"]);
  // A negation removed together with guide text is expected, with its clause.
  const guide = { opId: "op-22", kind: "replace_at_cell", table: 0, row: 10, col: 0, run: 1, mode: "replace", text: "", before: "x", origin: "agent" };
  const text = "비고(이 난은 서식에 표시하지 아니한다.) 그 내용을 적는다.";
  const at = text.indexOf("아니한다");
  const paraRemoved = {
    paragraph: 9, pass: false, kinds: ["qualifiers"], changes: [], before: text, after: "",
    beforeProtected: [{ start: at, end: at + 4, kind: "qualifiers", text: "아니한다", status: "removed" }],
    afterProtected: [],
  };
  g = adapter.guardOf({ ...indexed(1, guide, { before: text, after: "" }), isEmptyBlankFill: false }, "delete", summary(paraRemoved, "changed", "op-22"));
  assert.equal(g.status, "expected");
  assert.equal(g.facts[0].word, "아니한다");
  assert.ok(g.facts[0].clause.includes("아니한다"));
  // Kept stays kept; a failed guard is never a pass.
  assert.equal(adapter.guardOf(ch, "fill", summary(null, "kept")).status, "kept");
  assert.equal(adapter.guardOf(ch, "fill", { ...summary(null), state: "unavailable" }).status, "not_checked");
});

test("PLATFORM change sets map onto the same view", () => {
  const view = adapter.fromPlatformChangeSet({
    id: "cs-1",
    base: { kind: "candidate", revision: 1, sha256: "c".repeat(64) },
    status: "stale",
    reason: "superseded_by_newer_candidate",
    head_revision: 2,
    provenance: { mock: true },
    items: [
      { item_id: "i1", address: "t0/r1/c0", kind: "fill", before: "", after: "가온", status: "accepted" },
      { item_id: "i2", address: "p12", kind: "replace", before: "2026", after: "2027" },
    ],
    checks: { guard: { items: [{ item_id: "i2", pass: false, category: "changed", values: [{ kind: "dates", before: "2026", after: "2027" }] }] } },
  });
  assert.equal(view.items[0].decision, "accepted");
  assert.equal(view.items[1].decision, "pending");
  assert.equal(view.items[1].guard.status, "changed");
  assert.equal(view.items[0].source, "test");
  assert.deepEqual(view.stale, { reason: "superseded_by_newer_candidate", current: 2 });
});

// WP4 guard details, the canvas projection adapter, and the return payload.
import assert from "node:assert/strict";
import test from "node:test";

const adapter = await import("../src/panel/adapter.ts");
const ret = await import("../src/panel/returnCall.ts");
const model = await import("../src/model/changes.ts");

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

function input(indexed, extra = {}) {
  const changes = indexed.map((item) => ({
    id: item.opId,
    n: item.ordinal,
    at: `t${item.op.table}/r${item.op.row}/c${item.op.col}`,
    kind: item.opKindText,
    label: item.fieldLabel,
    before: item.beforeText,
    after: item.afterText,
    page: 1,
    source: item.op.origin,
    decision: item.op.origin === "user" ? "accepted" : "pending",
    contentHash: item.opId,
  }));
  return {
    language: "ko",
    indexed,
    changes,
    guard: null,
    plan: { planId: "pl-1", planHash: "a".repeat(64), boundSha256: "b".repeat(64), base: null, reverses: null, proposer: "gongmun-walkthrough", createdUtc: "2026-11-19T05:13:00Z" },
    validation: { ok: true, stale: false, hard: [], warn: [] },
    baseRevision: 0,
    baseSha256: "",
    currentRevision: 0,
    stale: null,
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

test("the adapter preserves each canvas flag in a mixed proposal", () => {
  const op = { opId: "op-5", kind: "fill_cell", table: 0, row: 1, col: 0, text: "x", origin: "agent" };
  const raw = input([indexed(1, op), indexed(2, { ...op, opId: "op-6", row: 2 })]);
  raw.plan.proposer = "agent-with-mock-in-its-name";
  raw.changes[0] = { ...raw.changes[0], source: "test", decision: "accepted" };
  const view = adapter.fromWorkspace(raw);
  assert.deepEqual(view.items.map(({ source, decision }) => [source, decision]), [
    ["test", "accepted"], ["agent", "pending"],
  ]);
  assert.deepEqual(model.requiredTicks(view), ["test"]);
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

test("a typed edit waits until the draft has both a plan and validation", () => {
  const op = { opId: "typed", kind: "fill_cell", table: 0, row: 1, col: 0, text: "Draft", origin: "user" };
  const items = [indexed(1, op)];
  for (const state of [{ plan: null, validation: null }, { validation: null }]) {
    const view = adapter.fromWorkspace(input(items, state));
    assert.equal(view.checking, true);
    assert.deepEqual(model.gateState(view).block, { kind: "checking" });
  }
  const guard = { state: "ready", planId: "pl-1", rowAudits: {} };
  assert.equal(adapter.fromWorkspace(input(items, { guard })).checking, false);
});
test("adapter carries the digest the guard's diff was read from", () => {
  const typed = { opId: "op-u", kind: "fill_cell", table: 0, row: 2, col: 0, text: "1. 관련", before: "", origin: "user" };
  const guard = (digest) => ({ state: "ready", planId: "pl-1", rowAudits: {}, documentDiff: { beforeSha256: digest } });
  const bound = input([indexed(1, typed)]).plan.boundSha256;
  const same = adapter.fromWorkspace(input([indexed(1, typed)], { guard: guard(bound) }));
  assert.equal(same.diffDigest, bound);
  assert.equal(model.gateState(same).canApprove, true);
  const other = adapter.fromWorkspace(input([indexed(1, typed)], { guard: guard("e".repeat(64)) }));
  assert.equal(other.diffDigest, "e".repeat(64));
  assert.deepEqual(model.gateState(other).block, { kind: "diff_mismatch" });
  // An older bridge that states no digest changes nothing.
  const none = adapter.fromWorkspace(input([indexed(1, typed)], { guard: guard(undefined) }));
  assert.equal(none.diffDigest, undefined);
});


test("a refused draft reports its failure ahead of the missing plan", () => {
  const op = { opId: "typed", kind: "fill_cell", table: 0, row: 1, col: 0, text: "Draft", origin: "user" };
  const refusal = { plan: null, validation: null, failureCode: "capability_unavailable" };
  const view = adapter.fromWorkspace(input([indexed(1, op)], refusal));
  assert.deepEqual(model.gateState(view).block, { kind: "failed", code: "capability_unavailable" });
});

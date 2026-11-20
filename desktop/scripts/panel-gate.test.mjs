// WP4 gate rules, without a browser: model/changes.ts is pure.
import assert from "node:assert/strict";
import test from "node:test";

const m = await import("../src/model/changes.ts");

function item(n, extra = {}) {
  const base = {
    id: `op-${n}`,
    n,
    at: `t0/r${n}/c0`,
    kind: "fill",
    label: `칸 ${n}`,
    opName: "빈칸 채움",
    before: "",
    after: `값 ${n}`,
    page: 1,
    source: "agent",
    guard: { status: "none", facts: [] },
    hard: [],
    ...extra,
  };
  base.decision = extra.decision ?? m.defaultDecision(base.source);
  return { ...base, contentHash: m.contentHashOf(base) };
}

function view(items, extra = {}) {
  return {
    id: "plan-1",
    planHash: "a".repeat(64),
    base: { kind: "source", revision: 0, sha256: "b".repeat(64) },
    stale: null,
    items,
    provenance: { agent: "agent", provider: null, mock: false },
    createdUtc: null,
    ...extra,
  };
}

function decideAll(items, records, decision) {
  let next = records;
  for (const it of items) next = m.recordDecision(next, it, decision);
  return next;
}

test("승인 stays disabled until 남음 is 0", () => {
  const items = Array.from({ length: 24 }, (_, i) => item(i + 1));
  let records = {};
  // 23 of 24 accepted: one is still 남음.
  records = decideAll(items.slice(0, 23), records, "accepted");
  let v = view(m.withDecisions(items, records));
  let gate = m.gateState(v);
  assert.equal(gate.canApprove, false);
  assert.deepEqual(gate.block, { kind: "remaining", count: 1 });
  assert.equal(gate.counts.pending, 1);
  // The last one decided: the gate opens.
  records = m.recordDecision(records, items[23], "accepted");
  v = view(m.withDecisions(items, records));
  gate = m.gateState(v);
  assert.equal(gate.canApprove, true);
  assert.equal(gate.block, null);
});

test("a hard finding blocks 승인 even when nothing is 남음", () => {
  const items = [item(1), item(2, { hard: ["글자 모양을 고쳐야 합니다."] })];
  const v = view(m.withDecisions(items, decideAll(items, {}, "accepted")));
  const gate = m.gateState(v);
  assert.equal(gate.canApprove, false);
  assert.deepEqual(gate.block, { kind: "hard", count: 1 });
});

test("all 뺌 leaves nothing to approve", () => {
  const items = [item(1), item(2)];
  const v = view(m.withDecisions(items, decideAll(items, {}, "rejected")));
  assert.deepEqual(m.gateState(v).block, { kind: "none_accepted" });
});

test("a 뺌 item never reaches the applied plan", () => {
  const items = Array.from({ length: 6 }, (_, i) => item(i + 1));
  let records = decideAll(items, {}, "accepted");
  records = m.recordDecision(records, items[2], "rejected");
  const decided = m.withDecisions(items, records);
  const planned = m.idsForApproval(decided);
  assert.equal(planned.includes("op-3"), false);
  assert.deepEqual(m.idsToDrop(decided), ["op-3"]);
  assert.equal(planned.length, 5);
  // 대기 is not 받아들임 either.
  const half = m.withDecisions(items, m.recordDecision({}, items[0], "accepted"));
  assert.deepEqual(m.idsForApproval(half), ["op-1"]);
});

test("a changed item returns to 대기", () => {
  const original = item(5, { after: "가온공공기록원" });
  const records = m.recordDecision({}, original, "accepted");
  assert.equal(m.withDecisions([original], records)[0].decision, "accepted");
  // The agent rewrites the value: same id, different content.
  const rewritten = item(5, { after: "가온기록원" });
  assert.notEqual(rewritten.contentHash, original.contentHash);
  assert.equal(m.withDecisions([rewritten], records)[0].decision, "pending");
  assert.deepEqual(m.pruneDecisions(records, [rewritten]), {});
  // A 뺌 decision is bound the same way.
  const rejected = m.recordDecision({}, original, "rejected");
  assert.equal(m.withDecisions([rewritten], rejected)[0].decision, "pending");
});

test("내 입력 lands already accepted", () => {
  const typed = item(1, { source: "user" });
  assert.equal(m.withDecisions([typed], {})[0].decision, "accepted");
});

test("stale disables Y, N and 승인", () => {
  const items = [item(1), item(2)];
  const accepted = m.withDecisions(items, decideAll(items, {}, "accepted"));
  const stale = view(accepted, { stale: { reason: "superseded_by_newer_candidate", current: 2 } });
  assert.equal(m.canDecide(stale), false);
  const gate = m.gateState(stale);
  assert.equal(gate.canApprove, false);
  assert.deepEqual(gate.block, { kind: "stale" });
  assert.equal(m.canDecide(view(accepted)), true);
});

test("Enter is blocked until the required ticks are set", () => {
  const fact = item(2, {
    guard: { status: "changed", facts: [{ kind: "date", before: "2026년 1월 1일", after: "2027년 1월 1일", expected: false }] },
  });
  const items = [item(1), fact];
  const v = view(m.withDecisions(items, decideAll(items, {}, "accepted")), {
    provenance: { agent: null, provider: "mock", mock: true },
  });
  const gate = m.gateState(v);
  assert.deepEqual(m.requiredTicks(v), ["facts", "test"]);
  assert.equal(m.canConfirm(v, new Set(), gate), false);
  assert.equal(m.canConfirm(v, new Set(["facts"]), gate), false);
  assert.equal(m.canConfirm(v, new Set(["facts", "test"]), gate), true);
  // An expected finding needs no tick.
  const expected = item(3, {
    guard: { status: "expected", facts: [{ kind: "negation", before: "아니한다", after: null, expected: true }] },
  });
  const v2 = view(m.withDecisions([expected], decideAll([expected], {}, "accepted")));
  assert.deepEqual(m.requiredTicks(v2), []);
  assert.equal(m.canConfirm(v2, [], m.gateState(v2)), true);
  // A 뺌 changed fact does not ask for a tick: it will not land.
  const v3 = view(m.withDecisions(items, m.recordDecision(decideAll(items, {}, "accepted"), fact, "rejected")));
  assert.deepEqual(m.requiredTicks(v3), []);
});

test("counts double as filters", () => {
  const items = [
    item(1),
    item(2, { guard: { status: "expected", facts: [{ kind: "negation", before: "아니한다", after: null, expected: true }] } }),
    item(3),
    item(4),
  ];
  let records = m.recordDecision({}, items[0], "accepted");
  records = m.recordDecision(records, items[3], "rejected");
  const decided = m.withDecisions(items, records);
  const c = m.countChanges(decided);
  assert.deepEqual([c.total, c.pending, c.accepted, c.rejected, c.attn], [4, 2, 1, 1, 1]);
  assert.deepEqual(m.filterChanges(decided, "rejected").map((x) => x.n), [4]);
  assert.deepEqual(m.filterChanges(decided, "pending").map((x) => x.n), [2, 3]);
  assert.deepEqual(m.filterChanges(decided, "attn").map((x) => x.n), [2]);
  assert.equal(m.filterChanges(decided, "all").length, 4);
});

test("Y advances to the next undecided change", () => {
  const items = [item(1), item(2), item(3)];
  const decided = m.withDecisions(items, m.recordDecision({}, items[1], "accepted"));
  assert.equal(m.nextPending(decided, "op-1").id, "op-3");
  assert.equal(m.nextPending(decided, "op-3").id, "op-1");
  const all = m.withDecisions(items, decideAll(items, {}, "accepted"));
  assert.equal(m.nextPending(all, "op-1"), null);
});

test("range digest keeps at most seven rows and covers every change", () => {
  const items = Array.from({ length: 24 }, (_, i) => item(i + 1, { group: `g${Math.floor(i / 2)}` }));
  const rows = m.rangeDigest(items);
  assert.ok(rows.length <= 7);
  assert.equal(rows[0].from, 1);
  assert.equal(rows[rows.length - 1].to, 24);
  for (let i = 1; i < rows.length; i += 1) assert.equal(rows[i].from, rows[i - 1].to + 1);
  assert.equal(m.rangeText(10, 12), "10–12");
  assert.equal(m.rangeText(5, 5), "5");
});

test("visible hashes are 12 characters", () => {
  assert.equal(m.shortHash("668bd74a879e784158f8541c4bbd2e05").length, 12);
  assert.equal(m.shortHash(null), "");
});

test("new values typed into a blank get a neutral tag, not 확인", () => {
  const added = item(1, { guard: { status: "expected", facts: [{ kind: "date", before: null, after: "2026. 11. 15.", expected: true }] } });
  const removed = item(2, { guard: { status: "expected", facts: [{ kind: "negation", before: "아니한다", after: null, expected: true }] } });
  assert.equal(m.needsLook(added), false);
  assert.equal(m.hasNewValues(added), true);
  assert.equal(m.needsLook(removed), true);
  assert.equal(m.hasNewValues(removed), false);
  assert.equal(m.countChanges([added, removed]).attn, 1);
});

test("the gate waits for the fact check", () => {
  const items = [item(1)];
  const v = view(m.withDecisions(items, decideAll(items, {}, "accepted")), { checking: true });
  assert.deepEqual(m.gateState(v).block, { kind: "checking" });
  assert.equal(m.canConfirm(v, [], m.gateState(v)), false);
});

test("a failing paragraph no change is tied to asks for the 바뀐 사실 tick", () => {
  const items = [item(1, { decision: "accepted" })];
  const plain = view(items);
  assert.deepEqual(m.requiredTicks(plain), []);
  const untied = view(items, { untied: [{ paragraph: 9, before: "", after: "2. Review" }] });
  assert.deepEqual(m.requiredTicks(untied), ["facts"]);
  const gate = m.gateState(untied);
  assert.equal(m.canConfirm(untied, [], gate), false);
  assert.equal(m.canConfirm(untied, ["facts"], gate), true);
});

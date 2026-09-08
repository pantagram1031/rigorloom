import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../src/actions.ts", import.meta.url), "utf8");
const leaseStart = source.indexOf("interface DraftOwner {");
const leaseEnd = source.indexOf("/** Load a session's inspect", leaseStart);
assert.ok(leaseStart >= 0 && leaseEnd > leaseStart, "draft lease source boundary changed");
const lease = source.slice(leaseStart, leaseEnd);

test("DraftFence is composed from DraftOwner rather than restated", () => {
  assert.ok(lease.includes("interface DraftFence extends DraftOwner"));
  assert.ok(lease.includes("generation: number"));
  assert.match(lease, /function captureDraftFence\(\s*owner: DraftOwner = captureDraftOwner\(\)/);
  assert.ok(lease.includes("...owner"));
  assert.ok(lease.includes("generation: currentPlanGeneration()"));
  assert.match(
    lease,
    /function ownsDraftFence\([\s\S]*return currentPlanGeneration\(\) === fence\.generation && ownsDraft\(fence\)/,
  );
  assert.equal((lease.match(/headCandidate\(state\)\?\.runId/g) || []).length, 2);
  assert.doesNotMatch(lease, /captureDraftFence\(\s*sessionId/);
});

function helpers() {
  const draftA = { ops: [{ opId: "a" }] };
  const draftB = { ops: [{ opId: "b" }] };
  let state = {
    draft: draftA,
    activeSessionId: "session-A",
    head: null,
  };
  let generation = 4;
  const context = vm.createContext({
    getState: () => state,
    headCandidate: (current) => (current.head ? { runId: current.head } : null),
    currentPlanGeneration: () => generation,
  });
  vm.runInContext(
    `${stripTypeScriptTypes(lease)}
globalThis.captureOwner = captureDraftOwner;
globalThis.ownsDraft = ownsDraft;
globalThis.captureFence = captureDraftFence;
globalThis.ownsFence = ownsDraftFence;`,
    context,
  );
  return {
    draftA,
    draftB,
    read: () => state,
    patch: (patch) => {
      state = { ...state, ...patch };
    },
    bump: () => {
      generation += 1;
    },
    generation: () => generation,
    captureOwner: () => context.captureOwner(),
    ownsDraft: (owner) => context.ownsDraft(owner),
    captureFence: (owner) => context.captureFence(owner),
    ownsFence: (fence) => context.ownsFence(fence),
  };
}

test("a freshly captured owner and fence both publish", () => {
  const h = helpers();
  const owner = h.captureOwner();
  const fence = h.captureFence(owner);
  assert.equal(fence.draft, owner.draft);
  assert.equal(fence.sessionId, owner.sessionId);
  assert.equal(fence.headRunId, owner.headRunId);
  assert.equal(fence.generation, h.generation());
  assert.equal(h.ownsDraft(owner), true);
  assert.equal(h.ownsFence(fence), true);
});

test("replacing the draft object fails both owner and fence", () => {
  const h = helpers();
  const owner = h.captureOwner();
  const fence = h.captureFence(owner);
  h.patch({ draft: h.draftB });
  assert.equal(h.ownsDraft(owner), false);
  assert.equal(h.ownsFence(fence), false);
});

test("a generation bump fails only the fence", () => {
  const h = helpers();
  const owner = h.captureOwner();
  const fence = h.captureFence(owner);
  h.bump();
  assert.equal(h.ownsDraft(owner), true);
  assert.equal(h.ownsFence(fence), false);
});

test("session and head replacements fail the shared identity rule", () => {
  for (const patch of [{ activeSessionId: "session-B" }, { head: "run-new" }]) {
    const h = helpers();
    const owner = h.captureOwner();
    const fence = h.captureFence(owner);
    h.patch(patch);
    assert.equal(h.ownsDraft(owner), false);
    assert.equal(h.ownsFence(fence), false);
  }
});

test("a fence copied from an earlier owner keeps that identity, not the live draft", () => {
  const h = helpers();
  const owner = h.captureOwner();
  h.patch({ draft: h.draftB, activeSessionId: "session-B", head: "run-new" });
  const fence = h.captureFence(owner);
  assert.equal(fence.draft, h.draftA);
  assert.equal(fence.sessionId, "session-A");
  assert.equal(fence.headRunId, null);
  assert.equal(h.ownsDraft(owner), false);
  assert.equal(h.ownsFence(fence), false);
});

test("a fence recaptured after a live change would hide owner staleness; composition refuses that", () => {
  const h = helpers();
  const owner = h.captureOwner();
  h.patch({ draft: h.draftB });
  const liveFence = h.captureFence();
  assert.equal(liveFence.draft, h.draftB);
  assert.equal(h.ownsFence(liveFence), true);
  assert.equal(h.ownsDraft(owner), false);
  const boundFence = h.captureFence(owner);
  assert.equal(boundFence.draft, owner.draft);
  assert.equal(h.ownsFence(boundFence), false);
});

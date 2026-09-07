import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import { stripTypeScriptTypes } from "node:module";

const source = readFileSync(new URL("../src/agent/planProjection.ts", import.meta.url), "utf8");
const actionsSource = readFileSync(new URL("../src/actions.ts", import.meta.url), "utf8");
const executable = stripTypeScriptTypes(source).replaceAll("export ", "");
const context = vm.createContext({ Set, Number, Object });
vm.runInContext(
  `${executable}\nglobalThis.projectForTest = projectAgentPlan; globalThis.addressesForTest = agentPlanCellAddresses;`,
  context,
);

function project(ops, beforeCell = () => "before") {
  return JSON.parse(
    JSON.stringify(context.projectForTest({ proposer: "agent-A", ops }, beforeCell)),
  );
}

function fill(opId = "fill-1", params = {}) {
  return {
    opId,
    kind: "fill_cell",
    params: { row: 2, col: 3, text: "new text", ...params },
  };
}

function adoptFixture(authoritative, returnedRegions = []) {
  const adoptStart = actionsSource.indexOf("async function adoptAgentPlan(");
  const adoptEnd = actionsSource.indexOf("\n}\n\n/** Ids are the shell's", adoptStart);
  assert.ok(adoptStart >= 0 && adoptEnd > adoptStart, "adoptAgentPlan source boundary changed");
  const adoptImplementation = actionsSource.slice(adoptStart, adoptEnd + 2);

  let state = {
    inspects: { "session-A": { source: "inspect" } },
    texts: { "session-A": [{ text: "source-before" }] },
    draft: { marker: "existing-draft" },
    approval: { approvalId: "existing-approval" },
    approvalPhase: "pending",
    approvalError: { code: "existing-error" },
  };
  const calls = { reads: [], approvals: [], patches: [] };
  const validation = { planId: authoritative.planId, ok: true };
  const fixtureContext = vm.createContext({ Set, Number, Object });
  vm.runInContext(stripTypeScriptTypes(source).replaceAll("export ", ""), fixtureContext);
  Object.assign(fixtureContext, {
    rt: {
      getPlan: async (planId) => {
        assert.equal(planId, authoritative.planId);
        return authoritative;
      },
      validatePlan: async (planId) => {
        assert.equal(planId, authoritative.planId);
        return validation;
      },
      readRegion: async (sessionId, addresses, runId) => {
        calls.reads.push({ sessionId, addresses: JSON.parse(JSON.stringify(addresses)), runId });
        return { regions: returnedRegions };
      },
      getApproval: async (approvalId) => {
        calls.approvals.push(approvalId);
        return { approvalId, state: "pending" };
      },
    },
    getState: () => state,
    setState: (patch) => {
      calls.patches.push(patch);
      state = { ...state, ...patch };
    },
    seatText: () => "source-before",
    regionTextAt: (regions, address) => {
      const match = regions.find(
        (region) =>
          (region.table ?? 0) === address.table &&
          region.addr?.row === address.row &&
          region.addr?.col === address.col,
      );
      return match?.text ?? null;
    },
  });
  vm.runInContext(
    `${stripTypeScriptTypes(adoptImplementation)}\nglobalThis.adoptForTest = adoptAgentPlan;`,
    fixtureContext,
  );

  return {
    adopt: (approvalId = "approval-new") =>
      fixtureContext.adoptForTest("session-A", authoritative.planId, approvalId),
    read: () => state,
    calls,
    validation,
  };
}

test("unsupported authoritative operation is refused by name", () => {
  assert.throws(
    () => project([{ opId: "delete-1", kind: "delete_guides", params: { color: "#0000FF" } }]),
    (error) => {
      assert.equal(error.code, "agent_plan_projection_unsupported");
      assert.equal(error.data.opId, "delete-1");
      assert.equal(error.data.kind, "delete_guides");
      return true;
    },
  );
});

test("mixed plan is refused atomically instead of projecting its supported prefix", () => {
  let beforeReads = 0;
  assert.throws(
    () =>
      project(
        [fill(), { opId: "run-1", kind: "set_run", params: { atPara: 4, run: 1, text: "x" } }],
        () => {
          beforeReads += 1;
          return "old";
        },
      ),
    (error) => error.code === "agent_plan_projection_unsupported" && error.data.opId === "run-1",
  );
  assert.equal(beforeReads, 0);
});

test("fill_cell projection preserves its address, text, styling, overwrite, and source value", () => {
  const calls = [];
  const result = project(
    [fill("fill-full", { table: 7, charPr: "19", overwrite: true })],
    (table, row, col) => {
      calls.push([table, row, col]);
      return "existing text";
    },
  );

  assert.deepEqual(calls, [[7, 2, 3]]);
  assert.deepEqual(result, [
    {
      opId: "fill-full",
      kind: "fill_cell",
      table: 7,
      row: 2,
      col: 3,
      text: "new text",
      charPr: "19",
      overwrite: true,
      before: "existing text",
      origin: "agent",
      proposer: "agent-A",
    },
  ]);
});

test("address discovery validates first and preserves the exact candidate read targets", () => {
  const addresses = JSON.parse(
    JSON.stringify(
      context.addressesForTest({
        proposer: "agent-A",
        ops: [fill("default"), fill("explicit", { table: 8, row: 0, col: 1 })],
      }),
    ),
  );
  assert.deepEqual(addresses, [
    { table: 0, row: 2, col: 3 },
    { table: 8, row: 0, col: 1 },
  ]);
});

test("candidate-bound adoption reads before from the authoritative base run", async () => {
  const authoritative = {
    planId: "plan-candidate",
    proposer: "agent-A",
    boundSha256: "candidate-sha",
    base: { runId: "run-parent", sha256: "candidate-sha" },
    reverses: null,
    ops: [fill("fill-candidate", { table: 4, overwrite: true })],
  };
  const fixture = adoptFixture(authoritative, [
    { table: 4, addr: { row: 2, col: 3 }, text: "candidate-before" },
  ]);

  const adopted = await fixture.adopt();

  assert.deepEqual(fixture.calls.reads, [
    {
      sessionId: "session-A",
      addresses: [{ table: 4, row: 2, col: 3 }],
      runId: "run-parent",
    },
  ]);
  assert.equal(fixture.read().draft.ops[0].before, "candidate-before");
  assert.equal(fixture.read().draft.ops[0].overwrite, true);
  assert.equal(fixture.read().draft.baseRunId, "run-parent");
  assert.equal(fixture.read().approval.approvalId, "approval-new");
  assert.equal(adopted.plan, authoritative);
  assert.equal(adopted.validation, fixture.validation);
});

test("missing candidate region refuses adoption without replacing draft or approval", async () => {
  const authoritative = {
    planId: "plan-missing-before",
    proposer: "agent-A",
    boundSha256: "candidate-sha",
    base: { runId: "run-parent", sha256: "candidate-sha" },
    reverses: null,
    ops: [fill("fill-missing", { overwrite: true })],
  };
  const fixture = adoptFixture(authoritative, []);
  const originalDraft = fixture.read().draft;
  const originalApproval = fixture.read().approval;

  await assert.rejects(fixture.adopt(), (error) => {
    assert.equal(error.code, "agent_plan_before_unreadable");
    assert.equal(error.data.runId, "run-parent");
    return true;
  });

  assert.equal(fixture.read().draft, originalDraft);
  assert.equal(fixture.read().approval, originalApproval);
  assert.equal(fixture.calls.patches.length, 0);
  assert.equal(fixture.calls.approvals.length, 0);
});

test("unsupported adoption refuses before reading candidate or replacing review state", async () => {
  const authoritative = {
    planId: "plan-unsupported",
    proposer: "agent-A",
    boundSha256: "candidate-sha",
    base: { runId: "run-parent", sha256: "candidate-sha" },
    reverses: null,
    ops: [{ opId: "delete-1", kind: "delete_guides", params: { color: "#0000FF" } }],
  };
  const fixture = adoptFixture(authoritative);
  const originalDraft = fixture.read().draft;
  const originalApproval = fixture.read().approval;

  await assert.rejects(
    fixture.adopt(),
    (error) =>
      error.code === "agent_plan_projection_unsupported" && error.data.kind === "delete_guides",
  );

  assert.equal(fixture.read().draft, originalDraft);
  assert.equal(fixture.read().approval, originalApproval);
  assert.equal(fixture.calls.reads.length, 0);
  assert.equal(fixture.calls.patches.length, 0);
  assert.equal(fixture.calls.approvals.length, 0);
});

test("valid false overwrite is retained and table defaults exactly once", () => {
  assert.deepEqual(project([fill("fill-default", { overwrite: false })]), [
    {
      opId: "fill-default",
      kind: "fill_cell",
      table: 0,
      row: 2,
      col: 3,
      text: "new text",
      overwrite: false,
      before: "before",
      origin: "agent",
      proposer: "agent-A",
    },
  ]);
});

test("valid Runtime fields without a queue representation are refused, never dropped", () => {
  for (const params of [{ lines: ["a", "b"], text: undefined }, { paraPr: "8" }]) {
    assert.throws(
      () => project([fill("lossy", params)]),
      (error) => {
        assert.equal(error.code, "agent_plan_projection_unsupported");
        assert.ok(error.data.unsupportedFields.length > 0);
        return true;
      },
    );
  }
});

test("malformed fill fields are refused rather than coerced into another target", () => {
  assert.throws(
    () => project([fill("bad-address", { row: "2", overwrite: "yes" })]),
    (error) => {
      assert.deepEqual(JSON.parse(JSON.stringify(error.data.invalidFields)), ["row", "overwrite"]);
      return true;
    },
  );
});

test("both agent entry points use the shared authoritative-plan projector", () => {
  const actions = actionsSource;
  const adoptStart = actions.indexOf("async function adoptAgentPlan(");
  const adoptEnd = actions.indexOf("\n}\n\n/** Ids are the shell's", adoptStart);
  const adopt = actions.slice(adoptStart, adoptEnd);
  const mockStart = actions.indexOf("export async function runAgentProposal(");
  const mockEnd = actions.indexOf("\n}\n\n// --- checking", mockStart);
  const mockEntry = actions.slice(mockStart, mockEnd);
  const instructionStart = actions.indexOf("export async function sendInstruction(");
  const instructionEnd = actions.indexOf("\n}\n\n/** Stop the run", instructionStart);
  const instructionEntry = actions.slice(instructionStart, instructionEnd);

  assert.match(adopt, /projectAgentPlan\(authoritative/);
  assert.match(adopt, /agentPlanCellAddresses\(authoritative\)/);
  assert.match(
    adopt,
    /rt\.readRegion\(sessionId, addresses, authoritative\.base\.runId\)/,
  );
  assert.match(adopt, /code: "agent_plan_before_unreadable"/);
  assert.ok(
    adopt.indexOf("projectAgentPlan(authoritative") < adopt.indexOf("setState({"),
    "projection refusal must happen before draft or approval state is replaced",
  );
  assert.match(mockEntry, /await adoptAgentPlan\(/);
  assert.match(mockEntry, /agentPhase: "failed", agentError: rt\.asRuntimeError\(e\)/);
  assert.match(instructionEntry, /await adoptAgentPlan\(/);
  assert.match(
    instructionEntry,
    /patchTurn\(id, \{ phase: "failed", error: rt\.asRuntimeError\(e\) \}\)/,
  );
});

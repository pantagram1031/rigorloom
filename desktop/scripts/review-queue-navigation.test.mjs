import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import { stripTypeScriptTypes } from "node:module";

function exportedFn(src, name) {
  const at = src.indexOf(`export function ${name}(`);
  assert.ok(at >= 0, `${name} missing`);
  const fromFn = src.slice(at);
  const endMatch = fromFn.match(/\r?\n\}\r?\n/);
  assert.ok(endMatch && typeof endMatch.index === "number", `${name} source boundary changed`);
  return fromFn.slice(0, endMatch.index + endMatch[0].length);
}

const source = readFileSync(new URL("../src/components/ReviewQueue.tsx", import.meta.url), "utf8");
const implementation = exportedFn(source, "locateQueuedOp");

function navigate(op, stateOverride = {}) {
  const calls = [];
  const state = {
    activeSessionId: "session-A",
    draft: { sessionId: "session-A", ops: [op] },
    ...stateOverride,
  };
  const context = vm.createContext({
    getState: () => state,
    setView: (value) => calls.push(["view", value]),
    setCenterMode: (value) => calls.push(["mode", value]),
    locateSelection: (value) => calls.push(["selection", value]),
  });
  vm.runInContext(
    `${stripTypeScriptTypes(implementation).replace("export ", "")}\nglobalThis.locateQueuedOpForTest = locateQueuedOp;`,
    context,
  );
  context.locateQueuedOpForTest(op);
  return JSON.parse(JSON.stringify(calls));
}

test("cell queue navigation enters document text view before locating the cell", () => {
  assert.deepEqual(
    navigate({ opId: "cell-op", kind: "fill_cell", table: 2, row: 3, col: 4 }),
    [
      ["view", "document"],
      ["mode", "text"],
      ["selection", { kind: "cell", table: 2, row: 3, col: 4 }],
    ],
  );
});

test("run queue navigation enters document text view before locating its paragraph", () => {
  assert.deepEqual(
    navigate({ opId: "run-op", kind: "set_run", atPara: 9, run: 1 }),
    [
      ["view", "document"],
      ["mode", "text"],
      ["selection", { kind: "paragraph", atPara: 9 }],
    ],
  );
});

test("queue address buttons use the shared navigation path", () => {
  assert.match(source, /onLocate=\{\(\) => locateQueuedOp\(op\)\}/);
});

test("another session's preserved queue cannot navigate in the active document", () => {
  assert.deepEqual(
    navigate(
      { opId: "other-op", kind: "fill_cell", table: 8, row: 8, col: 8 },
      { activeSessionId: "session-B" },
    ),
    [],
  );
  const hunkSource = readFileSync(new URL("../src/components/HunkCard.tsx", import.meta.url), "utf8");
  assert.match(hunkSource, /disabled=\{!locatable\}/);
  assert.match(hunkSource, /다른 문서의 대기열/);
});

const provenanceSource = exportedFn(source, "hunkProvenance");

function project(op, draft, receipts, head) {
  const context = vm.createContext({});
  vm.runInContext(
    `${stripTypeScriptTypes(provenanceSource).replace("export ", "")}\nglobalThis.hunkProvenanceForTest = hunkProvenance;`,
    context,
  );
  return JSON.parse(JSON.stringify(context.hunkProvenanceForTest(op, draft, receipts, head)));
}

test("each hunk projects session, plan, full hash, proposer, backend, base run, and receipt", () => {
  const draft = {
    sessionId: "session-A",
    baseRunId: "run-parent",
    plan: {
      sessionId: "session-A",
      planId: "plan-full",
      planHash: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      proposer: "plan-proposer",
      backend: "preedit",
      base: { runId: "run-parent" },
    },
  };
  assert.deepEqual(
    project(
      { origin: "agent", proposer: "agent-one" },
      draft,
      { "run-head": { runId: "run-head" } },
      "run-head",
    ),
    {
      sessionId: "session-A",
      planId: "plan-full",
      planHash: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      proposer: "agent-one",
      backend: "preedit",
      baseRunId: "run-parent",
      receiptExists: true,
    },
  );
  assert.equal(
    project({ origin: "user" }, { sessionId: "session-A", baseRunId: null, plan: null }, {}, null)
      .receiptExists,
    false,
  );
});

test("the queue renders provenance through per-hunk testids and a copyable full hash", () => {
  const hunkSource = readFileSync(new URL("../src/components/HunkCard.tsx", import.meta.url), "utf8");
  assert.match(hunkSource, /data-testid=\{`queue-provenance-\$\{slug\}`\}/);
  assert.match(hunkSource, /data-testid=\{`queue-prov-session-\$\{slug\}`\}/);
  assert.match(hunkSource, /data-testid=\{`queue-prov-plan-\$\{slug\}`\}/);
  assert.match(hunkSource, /data-testid=\{`queue-prov-hash-\$\{slug\}`\}/);
  assert.match(hunkSource, /data-testid=\{`queue-prov-proposer-\$\{slug\}`\}/);
  assert.match(hunkSource, /data-testid=\{`queue-prov-backend-\$\{slug\}`\}/);
  assert.match(hunkSource, /data-testid=\{`queue-prov-base-\$\{slug\}`\}/);
  assert.match(hunkSource, /data-testid=\{`queue-prov-receipt-\$\{slug\}`\}/);
  assert.match(hunkSource, /data-testid=\{`queue-prov-copy-hash-\$\{slug\}`\}/);
  assert.match(hunkSource, /copyPlanHash\(provenance\.planHash/);
});

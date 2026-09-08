import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import { stripTypeScriptTypes } from "node:module";

const source = readFileSync(new URL("../src/components/ReviewQueue.tsx", import.meta.url), "utf8");
const start = source.indexOf("export function locateQueuedOp(");
const end = source.indexOf("\n}\n", start);
assert.ok(start >= 0 && end > start, "locateQueuedOp source boundary changed");
const implementation = source.slice(start, end + 2);

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
  assert.match(source, /onClick=\{\(\) => locateQueuedOp\(op\)\}/);
});

test("another session's preserved queue cannot navigate in the active document", () => {
  assert.deepEqual(
    navigate(
      { opId: "other-op", kind: "fill_cell", table: 8, row: 8, col: 8 },
      { activeSessionId: "session-B" },
    ),
    [],
  );
  assert.match(source, /disabled=\{!locatable\}/);
  assert.match(source, /다른 문서의 대기열/);
});

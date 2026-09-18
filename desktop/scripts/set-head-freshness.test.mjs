import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import { stripTypeScriptTypes } from "node:module";

const source = readFileSync(new URL("../src/actions.ts", import.meta.url), "utf8");
const headStart = source.indexOf("interface HeadSelectionLease {");
const headEnd = source.indexOf("// --- approval", headStart);
assert.ok(headStart >= 0 && headEnd > headStart, "setHead source boundary changed");
const headImplementation = source.slice(headStart, headEnd).replace(/^export /gm, "");

const receiptStart = source.indexOf("export async function loadReceipt(");
const receiptEnd = source.indexOf("export function openReceipt", receiptStart);
assert.ok(receiptStart >= 0 && receiptEnd > receiptStart, "loadReceipt source boundary changed");
const receiptImplementation = source
  .slice(receiptStart, receiptEnd)
  .replace(/^export /gm, "");

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function fixture() {
  const queuedOps = [{ opId: "queued-op", kind: "set_run", text: "new" }];
  let state = {
    activeSessionId: "session-A",
    head: null,
    applied: { runId: "previous-applied" },
    candidateVerdict: {
      runId: "previous-head",
      report: { marker: "previous" },
    },
    editIntentGeneration: 4,
    draft: { ops: queuedOps },
    receipts: {},
    receiptError: null,
  };
  const reads = [];
  const rebases = [];
  const rt = {
    readReceipt(sessionId, runId) {
      const pending = deferred();
      reads.push({ ...pending, sessionId, runId });
      return pending.promise;
    },
    asRuntimeError(error) {
      return { code: "receipt_failed", message: String(error) };
    },
  };
  const context = vm.createContext({
    rt,
    getState: () => state,
    setState: (patch) => {
      state = { ...state, ...patch };
    },
    setQueue: async (ops, options) => {
      rebases.push({ ops, options });
    },
  });
  vm.runInContext(
    `${stripTypeScriptTypes(receiptImplementation)}
${stripTypeScriptTypes(headImplementation)}
globalThis.invokeSetHead = setHead;`,
    context,
  );

  return {
    read: () => state,
    patch: (patch) => {
      state = { ...state, ...patch };
    },
    select: (runId) => context.invokeSetHead(runId),
    reads,
    rebases,
    receipt: (runId, marker = runId) => ({
      runId,
      sessionId: "session-A",
      checks: { marker },
    }),
  };
}

test("the current head choice publishes its receipt and rebases the queue", async () => {
  const f = fixture();
  const pending = f.select("run-A");

  assert.equal(f.read().head, "run-A");
  assert.equal(f.read().applied, null);
  assert.equal(f.read().candidateVerdict, null);
  assert.equal(f.read().editIntentGeneration, 5);

  f.reads[0].resolve(f.receipt("run-A"));
  await pending;

  assert.equal(f.read().candidateVerdict.runId, "run-A");
  assert.equal(f.read().receipts["run-A"].runId, "run-A");
  assert.equal(f.rebases.length, 1);
  assert.equal(f.rebases[0].options.baseRunId, "run-A");
  assert.equal(f.rebases[0].ops, f.read().draft.ops);
});

test("an older receipt completion cannot replace a newer head or queue base", async () => {
  const f = fixture();
  const older = f.select("run-A");
  const newer = f.select("run-B");

  f.reads[1].resolve(f.receipt("run-B"));
  await newer;
  f.reads[0].resolve(f.receipt("run-A"));
  await older;

  assert.equal(f.read().head, "run-B");
  assert.equal(f.read().candidateVerdict.runId, "run-B");
  assert.equal(f.read().receipts["run-A"], undefined);
  assert.deepEqual(f.rebases.map((row) => row.options.baseRunId), ["run-B"]);
});

test("invocation order fences an A-B-A selection with the same final run id", async () => {
  const f = fixture();
  const firstA = f.select("run-A");
  const middleB = f.select("run-B");
  const latestA = f.select("run-A");

  f.reads[2].resolve(f.receipt("run-A", "latest-A"));
  await latestA;
  f.reads[0].resolve(f.receipt("run-A", "first-A"));
  await firstA;
  f.reads[1].resolve(f.receipt("run-B", "middle-B"));
  await middleB;

  assert.equal(f.read().candidateVerdict.report.marker, "latest-A");
  assert.equal(f.read().receipts["run-A"].checks.marker, "latest-A");
  assert.equal(f.read().receipts["run-B"], undefined);
  assert.deepEqual(f.rebases.map((row) => row.options.baseRunId), ["run-A"]);
});

test("a receipt completion from the previous session publishes nothing", async () => {
  const f = fixture();
  const pending = f.select("run-A");
  f.patch({ activeSessionId: "session-B" });
  f.reads[0].resolve(f.receipt("run-A"));
  await pending;

  assert.equal(f.read().candidateVerdict, null);
  assert.equal(f.read().receipts["run-A"], undefined);
  assert.equal(f.read().receiptError, null);
  assert.equal(f.rebases.length, 0);
});

test("a stale receipt failure cannot cover a newer successful selection", async () => {
  const f = fixture();
  const older = f.select("run-A");
  const newer = f.select("run-B");

  f.reads[1].resolve(f.receipt("run-B"));
  await newer;
  f.reads[0].reject(new Error("late A failure"));
  await older;

  assert.equal(f.read().candidateVerdict.runId, "run-B");
  assert.equal(f.read().receiptError, null);
  assert.deepEqual(f.rebases.map((row) => row.options.baseRunId), ["run-B"]);
});

test("the current receipt failure remains visible and preserves rebase behavior", async () => {
  const f = fixture();
  const pending = f.select("run-A");
  f.reads[0].reject(new Error("current A failure"));
  await pending;

  assert.equal(f.read().candidateVerdict, null);
  assert.equal(f.read().receiptError.code, "receipt_failed");
  assert.deepEqual(f.rebases.map((row) => row.options.baseRunId), ["run-A"]);
});

// --- 기록 panel: the head and the open row are announced, not only coloured ---

import { createRequire } from "node:module";
import ts from "typescript";

const nodeRequire = createRequire(import.meta.url);

/** Transpile one TS/TSX module in this realm with an explicit import map. */
function loadComponentModule(path, stubs) {
  const text = readFileSync(new URL(path, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(text, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  });
  const exports = {};
  const load = (name) => (name in stubs ? stubs[name] : nodeRequire(name));
  vm.runInThisContext(`(function (exports, require) {\n${outputText}\n})`)(exports, load);
  return exports;
}

function renderHistory(statePatch) {
  const store = loadComponentModule("../src/store.ts", {
    react: { useSyncExternalStore: (_subscribe, snapshot) => snapshot() },
  });
  const tag = loadComponentModule("../src/components/Tag.tsx", {});
  const actions = {
    exportApplied: () => {},
    loadReceipt: () => {},
    proposeUndoOf: () => {},
    restoreRun: () => {},
    loadSessionEvents: () => {},
    selectHistory: () => {},
    setHead: () => {},
    compareInspectRefusals: () => ({
      acceptanceRefused: false,
      exit3: false,
      errorRefused: false,
    }),
    runCompareInspect: () => {},
    setCompareAgainst: () => {},
    setCompareLeft: () => {},
    setCompareUseSelection: () => {},
  };
  const { History } = loadComponentModule("../src/components/History.tsx", {
    "../actions": actions,
    "../store": store,
    "../label": {
      relativeWhen: () => "방금",
      stampWhen: (iso) => String(iso ?? ""),
    },
    "./Tag": tag,
    "./EmptyState": {
      EmptyState: ({ title, body, testId }) =>
        nodeRequire("react").createElement("div", { className: "empty-state", "data-testid": testId }, title, body),
      EmptyIconHistory: () => null,
    },
    "./Timeline": {
      Timeline: () => nodeRequire("react").createElement("div", { "data-testid": "timeline" }),
    },
    "./Icon": {
      Icon: ({ name }) => nodeRequire("react").createElement("svg", { "data-icon": name }),
    },
  });
  store.setState({
    activeSessionId: "session-A",
    candidates: {
      "session-A": [
        { runId: "run-1", sha256: "a".repeat(64), base: null, createdUtc: "2026-09-14T01:00:00Z" },
        {
          runId: "run-2",
          sha256: "b".repeat(64),
          base: { runId: "run-1", sha256: "a".repeat(64) },
          createdUtc: "2026-09-14T02:00:00Z",
        },
      ],
    },
    head: null,
    historySelected: null,
    undoError: null,
    inverseProof: null,
    ...statePatch,
  });
  const { renderToStaticMarkup } = nodeRequire("react-dom/server");
  const { createElement } = nodeRequire("react");
  return renderToStaticMarkup(createElement(History));
}

function rowButton(html, runId) {
  const match = html.match(
    new RegExp(`<button class="history-head" data-testid="history-select-${runId}"[^>]*>`),
  );
  assert.ok(match, `history row button for ${runId} not rendered`);
  return match[0];
}

test("the open history row announces its expanded state and names its detail region", () => {
  const html = renderHistory({ historySelected: "run-1" });
  const open = rowButton(html, "run-1");
  assert.match(open, /aria-expanded="true"/);
  assert.match(open, /aria-controls="history-detail-run-1"/);
  assert.match(html, /<div class="history-detail" id="history-detail-run-1"/);
  const closed = rowButton(html, "run-2");
  assert.match(closed, /aria-expanded="false"/);
  // A collapsed row must not point assistive tech at a region that is not in the DOM.
  assert.doesNotMatch(closed, /aria-controls/);
  assert.doesNotMatch(html, /id="history-detail-run-2"/);
});

test("only the head row is announced as current, following the shell's head choice", () => {
  const byDefault = renderHistory({});
  assert.match(rowButton(byDefault, "run-2"), /aria-current="true"/);
  assert.doesNotMatch(rowButton(byDefault, "run-1"), /aria-current/);

  const chosen = renderHistory({ head: "run-1" });
  assert.match(rowButton(chosen, "run-1"), /aria-current="true"/);
  assert.doesNotMatch(rowButton(chosen, "run-2"), /aria-current/);
});

// --- lineage: one walk per published history, not one per notification ---

function loadStore() {
  return loadComponentModule("../src/store.ts", {
    react: { useSyncExternalStore: (_subscribe, snapshot) => snapshot() },
  });
}

function candidate(runId, baseRunId) {
  return {
    runId,
    sha256: `sha-${runId}`,
    base: baseRunId === null ? null : { runId: baseRunId, sha256: `sha-${baseRunId}` },
  };
}

function chain(length) {
  const rows = [];
  for (let i = 0; i < length; i++) rows.push(candidate(`run-${i}`, i === 0 ? null : `run-${i - 1}`));
  return rows;
}

test("lineage order is unchanged for chains, forks, orphans and stranded cycles", () => {
  const { lineage } = loadStore();
  const rows = [
    candidate("r1", null),
    candidate("r2", "r1"),
    candidate("r3", "r1"),
    candidate("orphan", "missing-parent"),
    candidate("c1", "c2"),
    candidate("c2", "c1"),
  ];
  assert.deepEqual(
    lineage(rows).map((row) => row.runId),
    ["r1", "r2", "r3", "orphan", "c1", "c2"],
  );
});

test("an unchanged history is not re-walked across store notifications", () => {
  const store = loadStore();
  let rowReads = 0;
  const rows = new Proxy(chain(50), {
    get(target, key, receiver) {
      if (typeof key === "string" && /^\d+$/.test(key)) rowReads += 1;
      return Reflect.get(target, key, receiver);
    },
  });
  store.setState({ activeSessionId: "session-A", candidates: { "session-A": rows }, head: null });
  assert.equal(store.headCandidate(store.getState())?.runId, "run-49");
  assert.ok(rowReads > 0, "the first selection walks the history");
  const afterFirst = rowReads;
  for (let i = 0; i < 100; i++) {
    store.setState({ composerDraft: { text: `keystroke ${i}` } });
    assert.equal(store.headCandidate(store.getState())?.runId, "run-49");
  }
  assert.equal(rowReads - afterFirst, 0, "later notifications reuse the walked ordering");
});

test("a republished history is walked again and its newest candidate becomes the default head", () => {
  const store = loadStore();
  const first = chain(3);
  store.setState({ activeSessionId: "session-A", candidates: { "session-A": first }, head: null });
  const before = store.lineage(first);
  assert.equal(store.headCandidate(store.getState())?.runId, "run-2");

  const republished = [...first, candidate("run-3", "run-2")];
  store.setState({ candidates: { "session-A": republished } });
  assert.notEqual(store.lineage(republished), before);
  assert.equal(store.headCandidate(store.getState())?.runId, "run-3");
  assert.equal(store.lineage(first), before, "the earlier list keeps its own ordering");
});

test("a straight chain longer than the call stack still orders every candidate", () => {
  const { lineage } = loadStore();
  const rows = chain(20000);
  const ordered = lineage(rows);
  assert.equal(ordered.length, rows.length);
  assert.equal(ordered[0]?.runId, "run-0");
  assert.equal(ordered[ordered.length - 1]?.runId, "run-19999");
});

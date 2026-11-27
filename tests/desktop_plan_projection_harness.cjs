/* Node v20 TypeScript harness for multi-op plan projection, fail-closed refusal,
 * browser transport detection, and re-approval gate invalidation.
 *
 * Uses desktop/node_modules/typescript directly (matching desktop_draft_fence_harness.cjs)
 * so it runs cleanly under Node v20 without --experimental-strip-types.
 */
"use strict";

const assert = require("node:assert/strict");
const Module = require("node:module");
const fs = require("node:fs");
const path = require("node:path");
const ts = require(path.join(__dirname, "..", "desktop", "node_modules", "typescript"));

const root = path.join(__dirname, "..");

const realReact = require(path.join(root, "desktop", "node_modules", "react"));
const originalLoad = Module._load;
Module._load = function fencedLoad(request, parent, isMain) {
  if (request === "react") return realReact;
  if (request === "react/jsx-runtime") {
    return require(path.join(root, "desktop", "node_modules", "react", "jsx-runtime"));
  }
  if (request === "react-dom/server") {
    return require(path.join(root, "desktop", "node_modules", "react-dom", "server"));
  }
  if (request === "@tauri-apps/plugin-dialog") {
    return {
      open: async () => {
        throw new Error("Tauri dialog must not run in browser harness");
      },
      save: async () => {
        throw new Error("Tauri dialog must not run in browser harness");
      },
    };
  }
  if (request === "@tauri-apps/api/webview") {
    return {
      getCurrentWebview: () => {
        throw new Error("Tauri webview must not run in browser harness");
      },
    };
  }
  if (request === "@tauri-apps/api/core") {
    return { invoke: async () => null };
  }
  if (request === "@tauri-apps/api/event") {
    return { listen: async () => () => {} };
  }
  return originalLoad.call(this, request, parent, isMain);
};

// Minimal global window shim for browser-mode runtime helpers without overwriting
// Node globals unnecessarily.
global.window = {
  location: { search: "?token=test-token-123" },
  __RIGORLOOM_UI__: { token: "test-token-123" },
  clearTimeout,
  setTimeout,
  matchMedia: () => ({ matches: false }),
  localStorage: {
    _m: new Map(),
    getItem(k) {
      return this._m.has(k) ? this._m.get(k) : null;
    },
    setItem(k, v) {
      this._m.set(k, String(v));
    },
  },
};

const cache = new Map();
function loadTs(rel) {
  const file = path.join(root, rel);
  if (cache.has(file)) return cache.get(file);
  const source = fs.readFileSync(file, "utf8");
  const emitted = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
  }).outputText;
  const wrapper = { exports: {} };
  const localRequire = (spec) => {
    if (spec.startsWith("./") || spec.startsWith("../")) {
      const base = path.join(path.dirname(file), spec);
      const resolved =
        fs.existsSync(base) && fs.statSync(base).isFile()
          ? base
          : fs.existsSync(`${base}.ts`)
            ? `${base}.ts`
            : fs.existsSync(`${base}.tsx`)
              ? `${base}.tsx`
              : base;
      return loadTs(path.relative(root, resolved));
    }
    return Module._load(spec, wrapper, false);
  };
  new Function("exports", "module", "require", emitted)(wrapper.exports, wrapper, localRequire);
  cache.set(file, wrapper.exports);
  return wrapper.exports;
}

const projection = loadTs("desktop/src/agent/planProjection.ts");
const runtime = loadTs("desktop/src/runtime.ts");
const store = loadTs("desktop/src/store.ts");
const actions = loadTs("desktop/src/actions.ts");
const vocabulary = loadTs("desktop/src/i18n/vocabulary.ts");

function runTest(name, fn) {
  try {
    const res = fn();
    if (res && typeof res.then === "function") {
      return res.then(
        () => console.log(`PASS ${name}`),
        (err) => {
          console.error(`FAIL ${name}: ${err && err.stack ? err.stack : err}`);
          process.exitCode = 1;
        },
      );
    }
    console.log(`PASS ${name}`);
    return Promise.resolve();
  } catch (err) {
    console.error(`FAIL ${name}: ${err && err.stack ? err.stack : err}`);
    process.exitCode = 1;
    return Promise.resolve();
  }
}

async function main() {
  await runTest("all-4-preedit-ops-roundtrip-deep-equal", () => {
    const ops = [
      {
        opId: "op-fill-text",
        kind: "fill_cell",
        params: { row: 1, col: 2, text: "홍길동", charPr: "7", overwrite: true },
      },
      {
        opId: "op-fill-lines",
        kind: "fill_cell",
        params: { table: 0, row: 2, col: 1, lines: ["첫 줄", "둘째 줄"], paraPr: "4" },
      },
      {
        opId: "op-replace-append",
        kind: "replace_at_cell",
        params: {
          table: 0,
          row: 3,
          col: 2,
          run: 1,
          text: " (수정)",
          mode: "append",
          expect: "기존문구",
          charPr: "5",
        },
      },
      {
        opId: "op-set-run",
        kind: "set_run",
        params: { atPara: 9, run: 0, text: "새 문단 내용" },
      },
      {
        opId: "op-del-guides",
        kind: "delete_guides",
        params: { color: "#0000FF", charPrIds: ["11", "12"] },
      },
    ];

    const plan = { proposer: "agent-wp3", ops };
    const projected = projection.projectAgentPlan(
      plan,
      (t, r, c) => `cell-${t}-${r}-${c}`,
      {
        beforeParaRun: (atPara, run) => `para-${atPara}-run-${run}`,
        beforeCellRun: (t, r, c, run) => `cell-${t}-${r}-${c}-run-${run}`,
        guideSummary: () => "파란 안내문 2건",
      },
    );

    assert.equal(projected.length, 5);
    assert.equal(projected[0].origin, "agent");
    assert.equal(projected[0].proposer, "agent-wp3");
    assert.deepEqual(
      ops.map((op) => projection.rebuildPlanOpFromProjection(projected[ops.indexOf(op)])),
      ops,
    );

    assert.equal(projection.projectedAfterText(projected[2]), "cell-0-3-2-run-1 (수정)");
    assert.equal(projection.formatProjectedAddress(projected[4]), "안내문 삭제 · Delete guides");
    assert.equal(projection.projectedAfterText(projected[4]), "(안내문 삭제됨)");
    assert.equal(projection.projectionInverseSupport(projected[4]).invertible, false);
    assert.equal(projection.projectionInverseSupport(projected[2]).invertible, true);
    assert.equal(projection.projectionInverseSupport(projected[3]).invertible, true);

    assert.deepEqual(projection.agentPlanCellAddresses(plan), [
      { table: 0, row: 1, col: 2 },
      { table: 0, row: 2, col: 1 },
      { table: 0, row: 3, col: 2 },
    ]);
    assert.deepEqual(projection.agentPlanReadAddresses(plan), [
      { table: 0, row: 1, col: 2 },
      { table: 0, row: 2, col: 1 },
      { table: 0, row: 3, col: 2 },
      { atPara: 9 },
    ]);
  });

  await runTest("backward-compatible-2arg-projectAgentPlan", () => {
    const plan = {
      proposer: "agent-compat",
      ops: [{ opId: "o1", kind: "fill_cell", params: { row: 0, col: 1, text: "값" } }],
    };
    const rows = projection.projectAgentPlan(plan, () => "이전값");
    assert.equal(rows.length, 1);
    assert.equal(rows[0].before, "이전값");
    assert.equal(rows[0].text, "값");
    assert.deepEqual(projection.rebuildPlanOpFromProjection(rows[0]), plan.ops[0]);
  });

  await runTest("fail-closed-refuses-unsupported-kinds-and-fields-atomically", () => {
    const badPlans = [
      {
        proposer: "agent",
        ops: [
          { opId: "ok-1", kind: "fill_cell", params: { row: 0, col: 0, text: "OK" } },
          { opId: "bad-1", kind: "goto_text", params: { text: "이동" } },
        ],
      },
      {
        proposer: "agent",
        ops: [{ opId: "bad-2", kind: "normalize_clones", params: {} }],
      },
      {
        proposer: "agent",
        ops: [{ opId: "bad-3", kind: "delete_guides", params: { row: 0, col: 1 } }],
      },
      {
        proposer: "agent",
        ops: [
          {
            opId: "bad-4",
            kind: "replace_at_cell",
            params: { row: 0, col: 1, text: "x", mode: "insert_before" },
          },
        ],
      },
    ];
    for (const bad of badPlans) {
      assert.throws(
        () => projection.projectAgentPlan(bad, () => "before"),
        (err) => err && err.code === "agent_plan_projection_unsupported",
      );
    }
  });

  await runTest("transport-shim-detects-browser-and-tauri-modes", () => {
    assert.equal(runtime.isTauri(), false);
    assert.equal(runtime.appendTokenQuery("/events"), "/events?token=test-token-123");
    assert.deepEqual(runtime.tokenHeaders(), { "X-Rigorloom-Token": "test-token-123" });
    global.window.__TAURI_INTERNALS__ = {};
    try {
      assert.equal(runtime.isTauri(), true);
    } finally {
      delete global.window.__TAURI_INTERNALS__;
    }
  });

  await runTest("reapproval-gate-clears-stale-approval-and-blocks-apply", async () => {
    const oldPlan = {
      sessionId: "sess-1",
      planId: "plan-1",
      planHash: "hash-1",
      boundSha256: "sha-before",
      proposer: "user",
      base: null,
      reverses: null,
      ops: [{ opId: "op-1", kind: "fill_cell", params: { table: 0, row: 0, col: 1, text: "v1" } }],
    };
    const oldDraft = {
      ops: [
        {
          opId: "op-1",
          kind: "fill_cell",
          table: 0,
          row: 0,
          col: 1,
          text: "v1",
          before: "",
          origin: "user",
        },
      ],
      plan: oldPlan,
      validation: {
        planId: "plan-1",
        ok: true,
        stale: true,
        boundSha256: "sha-before",
        currentSha256: "sha-after",
        hard: [{ code: "plan_stale", msg: "source changed", at: "plan" }],
        warn: [],
        counts: { hard: 1, warn: 0 },
        preflight: { checks: [], deferred: [], note: "", source: "" },
      },
      sessionId: "sess-1",
      boundSha256: "sha-before",
      phase: "ready",
      error: null,
      rewrittenFromAgent: false,
      baseRunId: null,
      reverses: null,
    };
    store.setState({
      activeSessionId: "sess-1",
      head: null,
      draft: oldDraft,
      approval: {
        approvalId: "appr-1",
        planId: "plan-1",
        planHash: "hash-1",
        state: "approved",
        requestedBy: "host",
        requestedUtc: "2026-11-15T00:00:00Z",
      },
      approvalPhase: "resolved",
      approvalError: null,
      reapprovalPrompt: null,
      applyPhase: "idle",
      applyError: null,
    });

    await actions.applyApproved();
    const after = store.getState();
    assert.equal(after.approval, null);
    assert.equal(after.approvalPhase, "idle");
    assert.equal(after.applyPhase, "idle");
    assert.equal(after.reapprovalPrompt, actions.REAPPROVAL_PROMPT);
  });

  await runTest("adoptAgentPlan-multiop-adoption-and-goto_text-refusal", async () => {
    const actionsSource = fs.readFileSync(
      path.join(root, "desktop/src/actions.ts"),
      "utf8",
    );
    const adoptStart = actionsSource.indexOf("async function adoptAgentPlan(");
    const adoptEnd = actionsSource.indexOf("\n}\n\n/** Ids are the shell's", adoptStart);
    assert.ok(adoptStart >= 0 && adoptEnd > adoptStart);
    const adoptImpl = actionsSource.slice(adoptStart, adoptEnd + 2);
    const leaseImpl = actionsSource.slice(
      actionsSource.indexOf("interface DraftOwner {"),
      actionsSource.indexOf("/** Load a session's inspect"),
    );
    const vm = require("node:vm");
    const planProjSource = fs.readFileSync(
      path.join(root, "desktop/src/agent/planProjection.ts"),
      "utf8",
    );

    const badPlan = {
      planId: "plan-bad-goto",
      proposer: "agent-A",
      boundSha256: "sha-1",
      base: { runId: "run-0", sha256: "sha-1" },
      reverses: null,
      ops: [{ opId: "g1", kind: "goto_text", params: { text: "jump" } }],
    };
    const multiPlan = {
      planId: "plan-multi-ok",
      planHash: "hash-multi",
      proposer: "agent-A",
      boundSha256: "sha-1",
      base: { runId: "run-0", sha256: "sha-1" },
      reverses: null,
      ops: [
        { opId: "o1", kind: "fill_cell", params: { row: 0, col: 1, text: "값1" } },
        { opId: "o2", kind: "replace_at_cell", params: { row: 1, col: 2, text: " (보완)", mode: "append" } },
        { opId: "o3", kind: "set_run", params: { atPara: 5, run: 0, text: "새 문단" } },
        { opId: "o4", kind: "delete_guides", params: { color: "#0000FF" } },
      ],
    };

    for (const authoritative of [badPlan, multiPlan]) {
      let state = {
        activeSessionId: "session-A",
        head: null,
        inspects: { "session-A": { graph: { tables: [] } } },
        texts: { "session-A": [] },
        draft: { marker: "keep-existing" },
        approval: { approvalId: "existing" },
        approvalPhase: "pending",
        approvalError: null,
      };
      const calls = { reads: [], patches: [], approvals: [] };
      const ctx = vm.createContext({
        Set,
        Number,
        Object,
        Array,
        Error,
        RegExp,
        String,
        Boolean,
        t: vocabulary.t,
        opKindLabel: vocabulary.opKindLabel,
      });
      const strip = (s) =>
        ts
          .transpileModule(s, {
            compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext },
          })
          .outputText.replace(/^\s*import\s+[\s\S]*?from\s+["'][^"']+["'];?\s*$/gm, "");
      vm.runInContext(strip(planProjSource).replaceAll("export ", ""), ctx);
      Object.assign(ctx, {
        rt: {
          getPlan: async () => authoritative,
          validatePlan: async (pid) => ({ planId: pid, ok: true }),
          readRegion: async (sid, addresses, runId) => {
            calls.reads.push({ sid, addresses, runId });
            const regions = addresses.map((a) =>
              a.atPara !== undefined
                ? { at_para: a.atPara, text: `para-${a.atPara}`, runs: [{ index: 0, text: `para-${a.atPara}-r0` }] }
                : { table: a.table ?? 0, addr: { row: a.row, col: a.col }, text: `cell-${a.row}-${a.col}` },
            );
            return { regions };
          },
          getApproval: async (aid) => {
            calls.approvals.push(aid);
            return { approvalId: aid, state: "pending" };
          },
        },
        headCandidate: () => null,
        currentPlanGeneration: () => 1,
        getState: () => state,
        setState: (patch) => {
          calls.patches.push(patch);
          state = { ...state, ...patch };
        },
        seatText: () => "source-cell",
        regionTextAt: (regions, address) => {
          const match = regions.find(
            (r) =>
              (r.table ?? 0) === address.table &&
              r.addr?.row === address.row &&
              r.addr?.col === address.col,
          );
          return match?.text ?? null;
        },
      });
      vm.runInContext(
        `${strip(leaseImpl)}\n${strip(adoptImpl)}\nglobalThis.adoptForTest = adoptAgentPlan;`,
        ctx,
      );

      if (authoritative === badPlan) {
        await assert.rejects(
          ctx.adoptForTest("session-A", authoritative.planId, "appr-x"),
          (err) => err.code === "agent_plan_projection_unsupported" && err.data.kind === "goto_text",
        );
        assert.equal(calls.reads.length, 0);
        assert.equal(calls.patches.length, 0);
        assert.equal(state.draft.marker, "keep-existing");
      } else {
        const res = await ctx.adoptForTest("session-A", authoritative.planId, "appr-m");
        assert.equal(res.plan.planId, "plan-multi-ok");
        assert.equal(state.draft.ops.length, 4);
        assert.deepEqual(
          state.draft.ops.map((x) => x.kind),
          ["fill_cell", "replace_at_cell", "set_run", "delete_guides"],
        );
        assert.deepEqual(
          state.draft.ops.map((op, i) => projection.rebuildPlanOpFromProjection(op)),
          multiPlan.ops,
        );
      }
    }
  });

  const existingSuites = [
    "desktop/scripts/draft-owner-fence.test.mjs",
    "desktop/scripts/set-queue-freshness.test.mjs",
    "desktop/scripts/set-head-freshness.test.mjs",
    "desktop/scripts/review-apply-freshness.test.mjs",
    "desktop/scripts/review-queue-navigation.test.mjs",
  ];
  const reviewSummarySrc = fs.readFileSync(
    path.join(root, "desktop/src/workspace/reviewSummary.ts"),
    "utf8",
  );
  const approvalHelpers = reviewSummarySrc
    .slice(
      reviewSummarySrc.indexOf("export function activeApprovalBinding("),
      reviewSummarySrc.indexOf("/** Pending operations"),
    )
    .replaceAll("export ", "");
  const { pathToFileURL } = require("node:url");

  for (const relSuite of existingSuites) {
    const absSuite = path.join(root, relSuite);
    const collected = [];
    const testFn = (name, fn) => collected.push({ name, fn });
    const raw = fs.readFileSync(absSuite, "utf8");
    const rewritten = raw.replaceAll(
      "import.meta.url",
      JSON.stringify(pathToFileURL(absSuite).href),
    );
    const emitted = ts.transpileModule(rewritten, {
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.CommonJS,
        esModuleInterop: true,
      },
    }).outputText;
    const localRequire = (spec) => {
      if (spec === "typescript") return ts;
      if (spec === "node:test") {
        return { __esModule: true, default: testFn, test: testFn };
      }
      if (spec === "node:module") {
        return {
          ...Module,
          stripTypeScriptTypes: (code) =>
            ts.transpileModule(code, {
              compilerOptions: { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext },
            }).outputText,
        };
      }
      if (spec === "../src/store.ts") return store;
      if (spec === "./action-test-support.mjs") {
        return {
          approvalHelpers,
          agentPlanCellAddresses: projection.agentPlanCellAddresses,
          projectAgentPlan: projection.projectAgentPlan,
          opKindLabel: vocabulary.opKindLabel,
          t: vocabulary.t,
          // Mirrors desktop/scripts/action-test-support.mjs.
          loadTrustModule: (load) => {
            const vocab = load("../src/i18n/vocabulary.ts", {});
            const store = load("../src/store.ts", {
              react: { useSyncExternalStore: (_subscribe, snapshot) => snapshot() },
            });
            return load("../src/workspace/trust.ts", {
              "../i18n/vocabulary.ts": vocab,
              "../store.ts": store,
            });
          },
          trustStoreSelectors: {
            returnedDraftOps: () => [],
            activeDisplayText: (s) => (s.texts && s.texts[s.activeSessionId]) || [],
            activeHeadTexts: () => null,
            showToast: () => {},
          },
        };
      }
      return require(spec);
    };
    const mod = { exports: {} };
    new Function("exports", "module", "require", emitted)(mod.exports, mod, localRequire);
    for (const tc of collected) {
      await runTest(`${path.basename(relSuite)} :: ${tc.name}`, tc.fn);
    }
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});

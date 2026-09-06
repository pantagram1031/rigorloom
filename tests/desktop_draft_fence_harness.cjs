/* Focused draft-fence / async-staleness cases against desktop/src/store.ts.
 *
 * Goal: prove that an older in-flight setQueue cannot overwrite the result
 * of a newer one.  The fence is implemented as a module-level generation
 * counter in store.ts (bumpPlanGeneration / currentPlanGeneration).  These
 * tests verify:
 *
 *   (a) bumpPlanGeneration is monotonically increasing
 *   (b) a token captured before a second call becomes stale (≠ current)
 *   (c) an interleaved / out-of-order resolve schedule: newer call B lands
 *       its result; older call A, resolving late, detects stale token and
 *       is a no-op — never overwrites B's draft state
 *   (d) a concurrent error in the older call is also fenced out
 *   (e) the reset helper lets tests run in isolation
 *
 * No Tauri, no package install beyond the Desktop TypeScript already declared.
 * React's useSyncExternalStore is satisfied with a thin stub so store.ts
 * loads in Node.
 */
"use strict";
const Module = require("module");
const fs = require("node:fs");
const path = require("node:path");
const ts = require(path.join(__dirname, "..", "desktop", "node_modules", "typescript"));

const root = path.join(__dirname, "..");

// Stub React so store.ts loads without a DOM.  Only useSyncExternalStore is
// called at import time (it is not — the import only captures the reference).
// The stub is only reached if TypeScript's own emit calls it.
const reactStub = {
  useSyncExternalStore: (_subscribe, getSnapshot) => getSnapshot(),
};
const originalLoad = Module._load;
Module._load = function fencedLoad(request, parent, isMain) {
  if (request === "react") return reactStub;
  return originalLoad.call(this, request, parent, isMain);
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
      const resolved = path.join(
        path.dirname(file),
        spec.endsWith(".ts") ? spec : `${spec}.ts`,
      );
      return loadTs(path.relative(root, resolved));
    }
    return Module._load(spec, wrapper, false);
  };
  new Function("exports", "module", "require", emitted)(wrapper.exports, wrapper, localRequire);
  cache.set(file, wrapper.exports);
  return wrapper.exports;
}

const store = loadTs("desktop/src/store.ts");
const {
  bumpPlanGeneration,
  currentPlanGeneration,
  _resetPlanGenerationForTest,
  getState,
  setState,
  EMPTY_DRAFT,
} = store;

function fail(name, detail) {
  console.error(`FAIL ${name}: ${detail}`);
  process.exitCode = 1;
}
function pass(name) {
  console.log(`PASS ${name}`);
}

// ---------------------------------------------------------------------------
// Simulate the fenced setQueue logic without the Tauri runtime calls.
// This mirrors exactly what actions.ts does: bump → propose → validate → write.
// Each async step carries the captured gen; each fence check mirrors the code
// in setQueue after `await rt.proposePlan` and `await rt.validatePlan`.
// ---------------------------------------------------------------------------
async function simulateSetQueue({
  proposeFn,
  validateFn,
  onSuccess,
  onError,
}) {
  const gen = bumpPlanGeneration();
  try {
    const plan = await proposeFn();
    if (currentPlanGeneration() !== gen) return { fenced: "after_propose" };
    const validation = await validateFn(plan);
    if (currentPlanGeneration() !== gen) return { fenced: "after_validate" };
    onSuccess({ plan, validation });
    return { fenced: null };
  } catch (e) {
    if (currentPlanGeneration() !== gen) return { fenced: "after_error" };
    onError(e);
    return { fenced: null };
  }
}

async function main() {
  // Reset before all tests so each run is independent.
  _resetPlanGenerationForTest();

  // -----------------------------------------------------------------------
  // (a) bumpPlanGeneration is monotonically increasing
  // -----------------------------------------------------------------------
  _resetPlanGenerationForTest();
  const t0 = currentPlanGeneration();
  const g1 = bumpPlanGeneration();
  const g2 = bumpPlanGeneration();
  const g3 = bumpPlanGeneration();
  if (t0 !== 0) {
    fail("initial_generation_is_zero", `got ${t0}`);
  } else pass("initial_generation_is_zero");
  if (g1 !== 1 || g2 !== 2 || g3 !== 3) {
    fail("generation_is_monotone", `got ${g1} ${g2} ${g3}`);
  } else pass("generation_is_monotone");
  if (currentPlanGeneration() !== 3) {
    fail("current_reflects_last_bump", `got ${currentPlanGeneration()}`);
  } else pass("current_reflects_last_bump");

  // -----------------------------------------------------------------------
  // (b) a token captured before a second call is stale
  // -----------------------------------------------------------------------
  _resetPlanGenerationForTest();
  const captured = bumpPlanGeneration();  // simulates call A starting
  bumpPlanGeneration();                    // simulates call B overtaking A
  if (currentPlanGeneration() === captured) {
    fail("older_token_is_stale_after_newer_bump", "tokens matched");
  } else pass("older_token_is_stale_after_newer_bump");
  if (currentPlanGeneration() !== captured + 1) {
    fail("current_is_one_ahead_of_captured", `current=${currentPlanGeneration()} captured=${captured}`);
  } else pass("current_is_one_ahead_of_captured");

  // -----------------------------------------------------------------------
  // (c) interleaved / out-of-order resolve: B lands first, A is a no-op
  //
  // Schedule:
  //   1. Call A starts (gen=1), its propose is pending
  //   2. Call B starts (gen=2), its propose resolves immediately
  //   3. B's validate resolves immediately → B writes its result
  //   4. A's propose resolves (stale: gen 1 ≠ current 2) → A is fenced out
  //   5. State reflects B's result only
  // -----------------------------------------------------------------------
  _resetPlanGenerationForTest();
  let stateA = null;
  let stateB = null;

  let releaseA;
  const aGate = new Promise((resolve) => { releaseA = resolve; });

  const callA = simulateSetQueue({
    proposeFn: async () => { await aGate; return { planId: "plan-A", boundSha256: "sha-A" }; },
    validateFn: async (plan) => ({ ok: true, stale: false, verdict: "ok", boundSha256: plan.boundSha256 }),
    onSuccess: (r) => { stateA = { label: "A", plan: r.plan }; },
    onError: () => { stateA = { label: "A-error" }; },
  });

  const callB = simulateSetQueue({
    proposeFn: async () => ({ planId: "plan-B", boundSha256: "sha-B" }),
    validateFn: async (plan) => ({ ok: true, stale: false, verdict: "ok", boundSha256: plan.boundSha256 }),
    onSuccess: (r) => { stateB = { label: "B", plan: r.plan }; },
    onError: () => { stateB = { label: "B-error" }; },
  });

  // B resolves synchronously in the microtask queue.
  const resultB = await callB;
  if (resultB.fenced !== null) {
    fail("newer_call_is_not_fenced", `fenced=${resultB.fenced}`);
  } else pass("newer_call_is_not_fenced");
  if (!stateB || stateB.plan?.planId !== "plan-B") {
    fail("newer_call_writes_its_result", JSON.stringify(stateB));
  } else pass("newer_call_writes_its_result");

  // Release A — it resolves after B and must be fenced.
  releaseA();
  const resultA = await callA;
  if (resultA.fenced !== "after_propose") {
    fail("older_call_is_fenced_after_propose", `fenced=${resultA.fenced}`);
  } else pass("older_call_is_fenced_after_propose");
  if (stateA !== null) {
    fail("older_call_does_not_write_state", JSON.stringify(stateA));
  } else pass("older_call_does_not_write_state");

  // B's result is still intact — A did not overwrite it.
  if (!stateB || stateB.plan?.planId !== "plan-B") {
    fail("newer_result_survives_older_late_resolve", JSON.stringify(stateB));
  } else pass("newer_result_survives_older_late_resolve");

  // -----------------------------------------------------------------------
  // (d) concurrent error in the older call is also fenced out
  //
  // Schedule:
  //   1. Call C starts (gen=1), its propose will throw after a gate
  //   2. Call D starts (gen=2), resolves cleanly
  //   3. C's gate releases → C's propose throws (gen 1 ≠ current 2) → fenced
  // -----------------------------------------------------------------------
  _resetPlanGenerationForTest();
  let stateC = null;
  let stateD = null;

  let releaseC;
  const cGate = new Promise((resolve) => { releaseC = resolve; });

  const callC = simulateSetQueue({
    proposeFn: async () => { await cGate; throw new Error("runtime error from C"); },
    validateFn: async () => ({ ok: true }),
    onSuccess: () => { stateC = "C-success"; },
    onError: () => { stateC = "C-error-written"; },
  });

  const callD = simulateSetQueue({
    proposeFn: async () => ({ planId: "plan-D", boundSha256: "sha-D" }),
    validateFn: async (plan) => ({ ok: true, stale: false, verdict: "ok", boundSha256: plan.boundSha256 }),
    onSuccess: (r) => { stateD = { label: "D", plan: r.plan }; },
    onError: () => { stateD = "D-error"; },
  });

  await callD;
  if (!stateD || stateD.plan?.planId !== "plan-D") {
    fail("call_d_writes_its_result", JSON.stringify(stateD));
  } else pass("call_d_writes_its_result");

  releaseC();
  const resultC = await callC;
  if (resultC.fenced !== "after_error") {
    fail("older_error_call_is_fenced", `fenced=${resultC.fenced}`);
  } else pass("older_error_call_is_fenced");
  if (stateC !== null) {
    fail("older_error_does_not_write_state", JSON.stringify(stateC));
  } else pass("older_error_does_not_write_state");
  if (!stateD || stateD.plan?.planId !== "plan-D") {
    fail("d_result_survives_c_error", JSON.stringify(stateD));
  } else pass("d_result_survives_c_error");

  // -----------------------------------------------------------------------
  // (e) validate fence: a bump that occurs AFTER propose resolves but
  //     BEFORE validate resolves correctly rejects the older call.
  //
  // Coordinated schedule:
  //   1. E starts (gen=1); its propose is blocked behind eProposeDone
  //   2. eProposeDone is resolved; E's propose result is scheduled as a
  //      microtask but has not yet run
  //   3. We flush the microtask queue once (via `await Promise.resolve()`)
  //      so E's propose-resolved continuation runs and E is now suspended
  //      inside its validateFn (which is blocked behind eValidateGate)
  //   4. F starts (gen=2) and resolves synchronously
  //   5. eValidateGate is released; E's validate returns → E sees gen 1 ≠ 2
  // -----------------------------------------------------------------------
  _resetPlanGenerationForTest();
  let stateE = null;
  let stateF = null;

  let resolveEPropose;
  const eProposeGate = new Promise((resolve) => { resolveEPropose = resolve; });

  let releaseEValidate;
  const eValidateGate = new Promise((resolve) => { releaseEValidate = resolve; });

  const callE = simulateSetQueue({
    proposeFn: async () => { await eProposeGate; return { planId: "plan-E", boundSha256: "sha-E" }; },
    validateFn: async (plan) => { await eValidateGate; return { ok: true, planId: plan.planId }; },
    onSuccess: (r) => { stateE = { label: "E", plan: r.plan }; },
    onError: () => { stateE = "E-error"; },
  });

  // Release E's propose — it will resume on the next microtask tick.
  resolveEPropose();
  // Use a macrotask boundary (setTimeout 0) rather than one or two
  // Promise.resolve() flushes.  The eProposeGate → proposeFn resolves →
  // simulateSetQueue-E continuation → fence check passes → validateFn →
  // eValidateGate chain spans two microtask levels.  All microtasks are
  // guaranteed to drain before the next macrotask fires, so by the time
  // our code resumes E is suspended inside validateFn with gen=1 captured.
  await new Promise((r) => setTimeout(r, 0));

  // Now F starts: bumps gen to 2 and resolves immediately.
  const callF = simulateSetQueue({
    proposeFn: async () => ({ planId: "plan-F", boundSha256: "sha-F" }),
    validateFn: async (plan) => ({ ok: true, verdict: "ok", boundSha256: plan.boundSha256, planId: plan.planId }),
    onSuccess: (r) => { stateF = { label: "F", plan: r.plan }; },
    onError: () => { stateF = "F-error"; },
  });

  await callF;
  if (!stateF || stateF.plan?.planId !== "plan-F") {
    fail("call_f_writes_its_result", JSON.stringify(stateF));
  } else pass("call_f_writes_its_result");

  // Release E's validate gate — E resumes, checks gen (1 ≠ 2) → fenced.
  releaseEValidate();
  const resultE = await callE;
  if (resultE.fenced !== "after_validate") {
    fail("older_call_fenced_after_validate", `fenced=${resultE.fenced}`);
  } else pass("older_call_fenced_after_validate");
  if (stateE !== null) {
    fail("validate_fenced_call_does_not_write_state", JSON.stringify(stateE));
  } else pass("validate_fenced_call_does_not_write_state");
  if (!stateF || stateF.plan?.planId !== "plan-F") {
    fail("f_result_survives_e_validate_fence", JSON.stringify(stateF));
  } else pass("f_result_survives_e_validate_fence");

  // -----------------------------------------------------------------------
  // (f) reset helper isolates runs
  // -----------------------------------------------------------------------
  _resetPlanGenerationForTest();
  if (currentPlanGeneration() !== 0) {
    fail("reset_restores_zero", `got ${currentPlanGeneration()}`);
  } else pass("reset_restores_zero");

  if (process.exitCode) {
    console.error("desktop draft-fence harness FAILED");
  } else {
    console.log("desktop draft-fence harness passed");
  }
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 2;
});

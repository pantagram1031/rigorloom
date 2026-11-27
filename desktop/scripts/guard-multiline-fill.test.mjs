// The guard attribution on the bundled 24-change 기안문 plan.
//
// op-24 fills the empty body blank with eight lines. The guard reports each
// line as its own paragraph (blank → text), and each fails the fact check
// because it carries dates and numbers. Those paragraphs were typed into a
// blank by that one change; they are not untied differences, and the sheet
// must not ask for the 바뀐 사실 tick over them.
//
// Inputs are recorded, not invented: the plan and guard result are
// scripts/fixtures/gongmun-24-guard.json (record-gongmun-guard.py), the
// inspect and region texts are src/fixtures/corpus.json (record-fixture.py).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

import { buildRegionTextMap } from "../src/workspace/externalPlan.ts";
import { requiredGuardAcks } from "../src/workspace/trust.ts";

function loadModules() {
  const cache = new Map();
  function load(relUrl, requires = {}) {
    if (cache.has(relUrl)) return cache.get(relUrl);
    const source = readFileSync(new URL(relUrl, import.meta.url), "utf8");
    const code = ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    const req = (id) => {
      if (id in requires) return requires[id];
      throw new Error(`Unexpected require(${id}) from ${relUrl}`);
    };
    vm.runInThisContext(`(function(exports, require, module) {\n${code}\n})`, { filename: relUrl })(
      module.exports,
      req,
      module,
    );
    cache.set(relUrl, module.exports);
    return module.exports;
  }
  const vocabulary = load("../src/i18n/vocabulary.ts");
  const formTokens = load("../src/i18n/formTokens.ts");
  const wp3 = load("../src/i18n/v2/wp3.ts", {
    "../vocabulary": vocabulary,
    "../vocabulary.ts": vocabulary,
  });
  const planProjection = load("../src/agent/planProjection.ts", {
    "../i18n/vocabulary.ts": vocabulary,
  });
  const fieldLabels = load("../src/workspace/fieldLabels.ts", {
    "../uiVariant.ts": { uiVariant: () => "v1" },
    "../i18n/vocabulary.ts": vocabulary,
    "../i18n/formTokens.ts": formTokens,
    "../i18n/v2/wp3.ts": wp3,
    "../i18n/v2/wp3": wp3,
  });
  const guardHelper = load("../src/workspace/guardHelper.ts", {
    react: { useSyncExternalStore: (_s, get) => get() },
    "../agent/planProjection": planProjection,
    "../i18n/vocabulary": vocabulary,
    "../i18n/formTokens.ts": formTokens,
    "./fieldLabels": fieldLabels,
    "../runtime": {
      guardDiff: async () => {
        throw new Error("pass the guard result explicitly");
      },
      asRuntimeError: (err) => ({ code: "guard_unavailable", message: String(err) }),
    },
  });
  return { planProjection, guardHelper };
}

const { planProjection, guardHelper } = loadModules();
const recorded = JSON.parse(readFileSync(new URL("./fixtures/gongmun-24-guard.json", import.meta.url), "utf8"));
const corpus = JSON.parse(readFileSync(new URL("../src/fixtures/corpus.json", import.meta.url), "utf8"));

/** The queue `adoptAgentPlan` builds for this plan on the session source. */
function adoptedDraft(plan) {
  const regions = corpus.regions;
  const cellRegion = (table, row, col) =>
    regions.find((r) => (r.table ?? 0) === table && r.addr?.row === row && r.addr?.col === col);
  const beforeCell = (table, row, col) => {
    const region = cellRegion(table, row, col);
    if (region?.text !== undefined) return region.text;
    const cell = corpus.inspect.graph.tables
      .find((t) => t.index === table)
      ?.cells.find((c) => c.addr.row === row && c.addr.col === col);
    return cell?.textPreview ?? "";
  };
  const beforeCellRun = (table, row, col, run) => {
    const match = cellRegion(table, row, col);
    if (run !== undefined && match?.runs) {
      const hit = match.runs.find((r) => r.index === run);
      if (hit) return hit.text;
    }
    return match?.text ?? beforeCell(table, row, col);
  };
  const ops = planProjection.projectAgentPlan(plan, beforeCell, {
    beforeCellRun,
    beforeParaRun: () => "",
    guideSummary: () => "",
  });
  return {
    ops,
    plan,
    validation: { ok: true, stale: false, hard: [], warn: [] },
    sessionId: plan.sessionId,
    boundSha256: plan.boundSha256,
    phase: "ready",
    error: null,
    rewrittenFromAgent: false,
    baseRunId: null,
    reverses: null,
  };
}

async function summarize() {
  const draft = adoptedDraft(recorded.plan);
  const textMap = buildRegionTextMap(corpus.regions);
  const changes = guardHelper.buildIndexedChanges(draft, corpus.inspect, textMap, "ko");
  const summary = await guardHelper.runAuthoritativeGuardDiff(
    recorded.plan.sessionId,
    draft,
    changes,
    async () => recorded.guard,
  );
  return { draft, changes, summary };
}

const BODY_LINES = recorded.plan.ops
  .find((op) => op.opId === "op-24")
  .params.lines.map((line) => line.replace(/\s+/g, " ").trim())
  .filter(Boolean);

test("the recorded inputs are the bundled plan on the bundled form", () => {
  assert.equal(recorded.plan.ops.length, 24);
  assert.equal(recorded.plan.boundSha256, corpus.source.sha256);
  assert.equal(BODY_LINES.length, 7);
  // The guard does report the body lines as failing paragraphs.
  const failing = recorded.guard.changed.filter((p) => p.pass === false).map((p) => p.after.replace(/\s+/g, " ").trim());
  for (const line of BODY_LINES) assert.ok(failing.includes(line), line);
});

test("every paragraph of the multi-line body fill is tied to op-24", async () => {
  const { summary } = await summarize();
  assert.equal(summary.state, "ready");
  const tied = (summary.paragraphsByOp["op-24"] ?? []).map((p) => p.after.replace(/\s+/g, " ").trim());
  assert.deepEqual([...tied].sort(), [...BODY_LINES].sort());
});

test("no untied paragraphs remain and no fact tick is required", async () => {
  const { summary } = await summarize();
  assert.deepEqual(
    (summary.unattributedFailing ?? []).map((p) => `${p.paragraph}: ${p.after || p.before}`),
    [],
  );
  assert.deepEqual(summary.changedFactOpIds, []);
  assert.equal(requiredGuardAcks(summary).total, 0);
});

test("a failing paragraph no line of the fill produced stays untied", async () => {
  const guard = structuredClone(recorded.guard);
  const stray = {
    paragraph: 999,
    pass: false,
    edited: true,
    kinds: ["numbers"],
    changes: [],
    before: "",
    after: "3. 예산: 1,200만 원",
    beforeProtected: [],
    afterProtected: [{ kind: "numbers", text: "1,200", status: "added" }],
  };
  guard.changed.push(stray);
  guard.allParagraphs.push(stray);
  const draft = adoptedDraft(recorded.plan);
  const changes = guardHelper.buildIndexedChanges(draft, corpus.inspect, buildRegionTextMap(corpus.regions), "ko");
  const summary = await guardHelper.runAuthoritativeGuardDiff(recorded.plan.sessionId, draft, changes, async () => guard);
  assert.deepEqual(
    (summary.unattributedFailing ?? []).map((p) => p.paragraph),
    [999],
  );
  assert.equal(requiredGuardAcks(summary).total, 1);
});

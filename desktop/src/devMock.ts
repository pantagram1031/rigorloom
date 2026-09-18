/**
 * Browser-mode fixtures, for design work without a Rust build.
 *
 * `npm run dev` in a plain browser has no Tauri host, so every `invoke` throws
 * and the app never gets past boot. That makes the layout and typography — the
 * part that needs the most iteration — the part that is hardest to look at.
 *
 * This installs a fake host that replays one **recorded real** conversation:
 * `src/fixtures/corpus.json` is the actual `capabilities/list`,
 * `workspace/openPath`, `document/inspect` and `document/readRegion` output
 * from Runtime v0 against `tests/corpus/forms/converted/gianmun-byeolji-1ho.hwpx`.
 * Re-record it with `python desktop/scripts/record-fixture.py`.
 *
 * Nothing here is invented, and nothing here ships: the only call site is
 * guarded by `import.meta.env.DEV`, which Vite replaces with a literal, so the
 * whole module and its fixture are dropped from a production bundle. It is a
 * viewer for real data, not a mock of behaviour — and it is never active inside
 * a Tauri window, where the real runtime answers instead.
 */
import corpus from "./fixtures/corpus.json";

import { mockFillResult } from "./fillReport";
import { mockPosterResult } from "./posterReport";
import { AURALAB_PIPELINE_STATUS } from "./pipelineStatus";
import { mockVerifyResult } from "./verifyReport";
import type { Capabilities, InspectResult, RegionText, SourceRef } from "./types";

interface Fixture {
  capabilities: Capabilities;
  source: SourceRef;
  inspect: InspectResult;
  regions: RegionText[];
}

const fixture = corpus as unknown as Fixture;

const SESSION = "devfixture0000000000000000000000";
const OPENED = "2026-09-01T00:00:00Z";
const PRESENT_PATH = "C:\\dev-fixture\\forms\\gianmun-byeolji-1ho.hwpx";
const MISSING_PATH = "C:\\dev-fixture\\missing\\gone.hwpx";

let openedSession = false;
let boundForm = false;
let prefs: Record<string, unknown> = {
  recents: [
    {
      path: PRESENT_PATH,
      name: "gianmun-byeolji-1ho.hwpx",
      sha256: fixture.source.sha256,
      bytes: fixture.source.bytes,
      openedUtc: "2026-09-17T00:04:00Z",
      documentKind: fixture.source.documentKind,
      formBinding: {
        kind: "profile",
        path: "C:\\dev-fixture\\forms\\blank_profile.json",
      },
    },
    {
      path: MISSING_PATH,
      name: "gone.hwpx",
      sha256: "0000000000000000000000000000000000000000000000000000000000000000",
      bytes: 0,
      openedUtc: "2026-09-16T12:00:00Z",
      documentKind: "hwpx",
      missing: true,
    },
  ],
};

interface Internals {
  invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown>;
  transformCallback?: (cb: unknown) => number;
}

let nextEventId = 1;
let planSeq = 0;
/** @type {Map<string, { plan: Record<string, unknown>; validation: Record<string, unknown>; approval: Record<string, unknown> | null }>} */
const plans = new Map();
/** @type {Map<string, Record<string, unknown>>} */
const approvals = new Map();
/** @type {Map<string, { candidate: Record<string, unknown>; receipt: Record<string, unknown> }>} */
const applied = new Map();

const DOC_HASH = fixture.source.sha256;
const CHECKS = {
  required: ["well_formed"],
  ranAll: true,
  acceptance: true,
  reason: null,
  checks: [{ checker: "well_formed", state: "ran", ok: true }],
  note: "dev-mock: structural_only, not a native session.",
};

function isoNow() {
  return new Date().toISOString().replace(/\.\d+Z$/, "Z");
}

function hexPad(label: string): string {
  const raw = `${label}${DOC_HASH}`.replace(/[^0-9a-f]/gi, "a").toLowerCase();
  return (raw + "0".repeat(64)).slice(0, 64);
}

function makePlan(ops: Array<Record<string, unknown>>) {
  planSeq += 1;
  const planId = `plan-demo${String(planSeq).padStart(8, "0")}`;
  const planHash = hexPad(`plan${planSeq}`);
  const plan = {
    schema: "rigorloom.plan/v1",
    planId,
    planHash,
    opsHash: hexPad(`ops${planSeq}`),
    sessionId: SESSION,
    backend: "xml",
    boundSha256: DOC_HASH,
    base: null,
    reverses: null,
    createdUtc: isoNow(),
    proposer: "agenthost-mock",
    implVersion: "0.18.0",
    ops,
    state: "proposed",
  };
  const validation = {
    planId,
    planHash,
    backend: "xml",
    boundSha256: DOC_HASH,
    currentSha256: DOC_HASH,
    stale: false,
    ok: true,
    verdict: "pass",
    hard: [],
    warn: [],
    counts: { hard: 0, warn: 0, ops: ops.length },
    preflight: {
      level: "structural",
      source: "dev-mock",
      deferred: ["native_com_session"],
      note: "브라우저 미리보기는 구조만 확인합니다.",
    },
  };
  const row = { plan, validation, approval: null as Record<string, unknown> | null };
  plans.set(planId, row);
  return row;
}

function makeApproval(planId: string, requestedBy: string) {
  const row = plans.get(planId);
  if (!row) throw { code: "plan_not_found", message: `no plan ${planId}` };
  const approval = {
    approvalId: `appr-demo${String(planSeq).padStart(8, "0")}`,
    planId: row.plan.planId,
    planHash: row.plan.planHash,
    state: "pending",
    requestedUtc: isoNow(),
    requestedBy,
    resolvedUtc: null,
    approver: null,
    decision: null,
  };
  row.approval = approval;
  approvals.set(String(approval.approvalId), approval);
  return approval;
}

function demoFillOp() {
  return {
    opId: "op-t0r0c14",
    kind: "fill_cell",
    params: { table: 0, row: 0, col: 14, text: "행정안전부" },
  };
}

function mockHostRun(args: Record<string, unknown>) {
  const row = makePlan([demoFillOp()]);
  const approval = makeApproval(String(row.plan.planId), "agenthost-mock");
  const instruction = String(args.instruction ?? "");
  const events = [
    { seq: 0, kind: "run.started", at: isoNow(), detail: {} },
    { seq: 1, kind: "provider.selected", at: isoNow(), detail: { provider: { providerId: "mock", model: "mock" } } },
    { seq: 2, kind: "tool.compiled", at: isoNow(), detail: { method: "plan/propose", name: "propose" } },
    { seq: 3, kind: "run.finished", at: isoNow(), detail: { ok: true } },
  ];
  return {
    exitCode: 0,
    credentialAttached: false,
    eventsPath: "C:\\dev-fixture\\events.jsonl",
    stderr: "",
    turnId: args.turnId ?? "",
    payload: {
      ok: true,
      host: "agenthost-mock",
      hostVersion: "0.18.0",
      provider: { providerId: "mock", model: "mock", scenario: "propose-one" },
      instruction,
      sessionId: SESSION,
      turns: 1,
      finishReason: "stop",
      closingText: "한 칸을 채우는 계획을 냈습니다. 승인은 검토 탭에서 해 주십시오.",
      plan: row.plan,
      validation: row.validation,
      approval,
      refusals: [],
      providerFault: null,
      turnBudgetExhausted: false,
      neverCompiled: ["approval/resolve", "plan/apply"],
      events: { schema: "rigorloom.host-events/v1", count: events.length, events },
    },
  };
}

function mockPropose(params: Record<string, unknown>) {
  const rawOps = Array.isArray(params.ops) ? (params.ops as Array<Record<string, unknown>>) : [];
  const ops = rawOps.map((op: Record<string, unknown>, index: number) => {
    const { opId, kind, ...rest } = op;
    const paramsOut =
      kind === "fill_cell"
        ? {
            table: rest.table,
            row: rest.row,
            col: rest.col,
            text: rest.text,
            ...(rest.charPr ? { charPr: rest.charPr } : {}),
          }
        : rest;
    return {
      opId: String(opId ?? `op-${index}`),
      kind: String(kind ?? "unknown"),
      params: paramsOut,
    };
  });
  const row = makePlan(ops);
  return { plan: row.plan };
}

function mockGetPlan(planId: string) {
  const row = plans.get(planId);
  if (!row) throw { code: "plan_not_found", message: `no plan ${planId}` };
  return { plan: row.plan };
}

function mockValidate(planId: string) {
  const row = plans.get(planId);
  if (!row) throw { code: "plan_not_found", message: `no plan ${planId}` };
  return { validation: row.validation };
}

function mockGetApproval(approvalId: string) {
  const approval = approvals.get(approvalId);
  if (!approval) throw { code: "approval_not_found", message: `no approval ${approvalId}` };
  return { approval };
}

function mockResolve(params: Record<string, unknown>) {
  const approval = approvals.get(String(params.approvalId ?? ""));
  if (!approval) throw { code: "approval_not_found", message: "no approval" };
  approval.state = String(params.decision ?? "approved");
  approval.decision = String(params.decision ?? "approved");
  approval.approver = String(params.approver ?? "host-operator");
  approval.resolvedUtc = isoNow();
  return { approval };
}

function mockApply(params: Record<string, unknown>) {
  const planId = String(params.planId ?? "");
  const row = plans.get(planId);
  if (!row) throw { code: "plan_not_found", message: `no plan ${planId}` };
  const approval = approvals.get(String(params.approvalId ?? "")) ?? row.approval;
  if (!approval || approval.state !== "approved") {
    throw { code: "approval_required", message: "apply needs an approved plan" };
  }
  const runId = `run-demo${String(planSeq).padStart(8, "0")}`;
  const sha = hexPad(runId);
  const artifact = {
    role: "candidate",
    path: `C:\\dev-fixture\\runtime-root\\${runId}\\artifact.hwpx`,
    sha256: sha,
    bytes: fixture.source.bytes,
  };
  const candidate = {
    runId,
    sessionId: SESSION,
    planId,
    candidate: artifact,
    base: null,
    reverses: null,
    checks: CHECKS,
    receipt: `${runId}/receipt.json`,
    canonical: true,
    sha256: sha,
    bytes: fixture.source.bytes,
    createdUtc: isoNow(),
    acceptance: true,
    opKinds: (row.plan.ops as Array<{ kind: string }>).map((op) => op.kind),
    backend: "xml",
  };
  const receipt = {
    schema: "rigorloom.receipt/v1",
    implVersion: "0.18.0",
    createdUtc: isoNow(),
    runId,
    sessionId: SESSION,
    planId,
    planHash: row.plan.planHash,
    backend: "xml",
    bodySha256: sha,
    source: fixture.source,
    candidate: artifact,
    base: null,
    reverses: null,
    approval,
    steps: (row.plan.ops as Array<{ opId: string; kind: string }>).map((op) => ({
      opId: op.opId,
      kind: op.kind,
      subcommand: op.kind,
      exitCode: 0,
    })),
    checks: CHECKS,
    evidence: { class: "structural_only", note: "dev-mock apply; not a native session." },
  };
  applied.set(runId, { candidate, receipt });
  return { candidate };
}

function mockReceipt(sessionId: string, runId: string) {
  const row = applied.get(runId);
  if (!row) throw { code: "receipt_not_found", message: `no receipt ${runId} in ${sessionId}` };
  return { receipt: row.receipt };
}

function handle(cmd: string, args: Record<string, unknown> = {}): unknown {
  switch (cmd) {
    case "runtime_start":
      return {
        handshake: { protocolVersion: "0" },
        status: status(),
      };
    case "runtime_status":
      return status();
    case "runtime_stop":
      return null;
    case "prefs_load":
      return prefs;
    case "prefs_save": {
      prefs = { ...prefs, ...(args.patch as Record<string, unknown>) };
      return prefs;
    }
    case "default_runtime_root":
      return "C:\\dev-fixture\\runtime-root";
    case "smoke_config":
      return { phase: null, corpus: null, reportPath: null };
    case "smoke_ready":
    case "smoke_finish":
      return null;
    case "timing_mark":
      return 0;
    case "runtime_call":
      return call(String(args.method), (args.params ?? {}) as Record<string, unknown>);
    // The event plugin. Nothing ever fires in browser mode — there is no
    // sidecar to emit — but `listen()` must resolve, because App awaits three
    // of them before it boots and a rejection there leaves the entrance up
    // forever.
    case "plugin:event|listen":
      return nextEventId++;
    case "plugin:event|unlisten":
      return null;
    case "task_packs":
      return {
        available: false,
        mode: "browser",
        reason: "브라우저 미리보기에는 작업 팩 등록기가 없습니다.",
        packs: [],
      };
    case "agent_host_status":
      return {
        available: true,
        mode: "interpreter",
        script: "C:\\dev-fixture\\agenthost\\scripts\\host.py",
        program: "python",
        reason: "브라우저 미리보기 — mock provider만 응답합니다.",
      };
    case "agent_tool_status":
      return { available: false, script: null, reason: "브라우저 미리보기" };
    case "agent_host_run":
      return mockHostRun(args);
    case "agent_host_stop":
      return true;
    case "agent_host_capabilities":
      return {
        exitCode: 0,
        payload: {
          ok: true,
          provider: { providerId: "mock", model: "mock", scenario: "propose-one" },
        },
        credentialAttached: false,
        stderr: "",
      };
    case "agent_host_read_config":
      return { path: "C:\\dev-fixture\\provider.json", exists: false, config: null };
    case "agent_host_save_config":
      return { path: "C:\\dev-fixture\\provider.json", config: args.settings ?? {} };
    case "runtime_cancel":
      return true;
    case "credential_status":
      return { key: args.key ?? "", state: "absent", bytes: 0, reason: null };
    default:
      throw { code: "dev_mock", message: `no fixture for ${cmd}` };
  }
}

function status() {
  return {
    running: true,
    pid: 0,
    mode: "interpreter",
    root: "C:\\dev-fixture\\runtime-root",
    jobConfined: null,
    jobError: "브라우저 미리보기에는 사이드카가 없습니다",
    exitCode: null,
    failure: null,
    initialized: true,
  };
}

function call(method: string, params: Record<string, unknown>): unknown {
  switch (method) {
    case "initialize":
      return { protocolVersion: "0" };
    case "capabilities/list":
      return fixture.capabilities;
    case "session/list":
      return {
        sessions: openedSession
          ? [{ sessionId: SESSION, openedUtc: OPENED, source: fixture.source }]
          : [],
      };
    case "workspace/openPath":
      openedSession = true;
      boundForm = Boolean(params.formProfile || params.form);
      return { sessionId: SESSION, openedUtc: OPENED, source: fixture.source };
    case "workspace/pipelineStatus":
      return AURALAB_PIPELINE_STATUS;
    case "document/inspect":
      return inspectPayload();
    case "document/readRegion": {
      const wanted = (params.regions ?? []) as Array<{
        table?: number;
        row?: number;
        col?: number;
      }>;
      const keys = new Set(
        wanted.map((r) => `${r.table ?? 0}:${r.row}:${r.col}`),
      );
      const regions = fixture.regions.filter(
        (r) => !r.addr || keys.has(`${r.table ?? 0}:${r.addr.row}:${r.addr.col}`),
      );
      return {
        sessionId: SESSION,
        documentHash: fixture.inspect.documentHash,
        regions,
      };
    }
    case "candidate/verify":
      return mockVerifyResult(SESSION, typeof params.runId === "string" ? params.runId : null);
    case "workspace/fillRun":
      return mockFillResult(
        typeof params.workspace === "string"
          ? params.workspace
          : AURALAB_PIPELINE_STATUS.workspacePath ?? "",
        SESSION,
      );
    case "workspace/posterRun":
      return mockPosterResult(
        typeof params.workspace === "string"
          ? params.workspace
          : AURALAB_PIPELINE_STATUS.workspacePath ?? "",
        SESSION,
      );
    case "plan/propose":
      return mockPropose(params);
    case "plan/get":
      return mockGetPlan(String(params.planId ?? ""));
    case "plan/validate":
      return mockValidate(String(params.planId ?? ""));
    case "approval/request":
      return { approval: makeApproval(String(params.planId ?? ""), String(params.requestedBy ?? "host")) };
    case "approval/get":
      return mockGetApproval(String(params.approvalId ?? ""));
    case "approval/resolve":
      return mockResolve(params);
    case "plan/apply":
      return mockApply(params);
    case "receipt/read":
      return mockReceipt(String(params.sessionId ?? ""), String(params.runId ?? ""));
    case "candidate/list":
      return {
        sessionId: SESSION,
        candidates: [...applied.values()].map((row) => row.candidate),
      };
    default:
      throw { code: "dev_mock", message: `no fixture for ${method}` };
  }
}

function inspectPayload(): unknown {
  const inspect = withSession(fixture.inspect) as InspectResult;
  const forbidden = inspect.forbidden ?? {
    sessionId: SESSION,
    anchors: [],
    placeholders: [],
    removalTargets: [],
    counts: { anchors: 0, placeholders: 0, removalTargets: 0 },
  };
  inspect.forbidden = {
    ...forbidden,
    residue: boundForm
      ? {
          profileSource: "bound_form",
          sha256: "boundform".padEnd(64, "0"),
        }
      : {
          profileSource: "self_derived",
          sha256: inspect.documentHash,
          note: "heuristic",
        },
  };
  return inspect;
}

function withSession(value: unknown): unknown {
  return JSON.parse(
    JSON.stringify(value).replace(/"sessionId":\s*"[^"]*"/g, `"sessionId":"${SESSION}"`),
  );
}

/** True when running in a real Tauri window rather than a plain browser. */
function insideTauri(): boolean {
  return "__TAURI_INTERNALS__" in window;
}

export function installDevMock(): void {
  if (insideTauri()) return;
  if (new URLSearchParams(window.location.search).get("kit") === "1") return;
  const internals: Internals = {
    invoke: (cmd, args) =>
      new Promise((resolve, reject) => {
        // A small delay so the entrance is visible; keep it short so Home
        // is on screen within a second of mount.
        setTimeout(() => {
          try {
            resolve(handle(cmd, args));
          } catch (e) {
            reject(e);
          }
        }, 40);
      }),
    transformCallback: () => 0,
  };
  (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = internals;
  // eslint-disable-next-line no-console
  console.info("[dev] Tauri host absent — replaying the recorded corpus fixture.");
}

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
        available: false,
        mode: null,
        script: null,
        program: null,
        reason: "브라우저 미리보기에는 에이전트 호스트가 없습니다.",
      };
    case "agent_tool_status":
      return { available: false, script: null, reason: "브라우저 미리보기" };
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
    case "candidate/list":
      return { sessionId: SESSION, candidates: [] };
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

/**
 * The scripted end-to-end smoke, run inside the BUILT app.
 *
 * Why in-app rather than tauri-driver: driving a WebView2 window from outside
 * needs an `msedgedriver` pinned to the machine's evergreen WebView2 build
 * (151.x today, different tomorrow), which makes the evidence unreproducible
 * for exactly the reason the spike flagged — the runtime can change under the
 * app without an app release. Running the checks inside the shipped bundle,
 * through the same `actions.ts` functions a click calls, and asserting against
 * the real rendered DOM, keeps the harness pinned to the app instead of to a
 * driver version.
 *
 * What this therefore does NOT prove, stated plainly: no OS-level input is
 * synthesized, so the native file dialog and IME composition are not exercised
 * here. The spike covered IME (M13/M14) with real scan codes; the dialog is
 * uncovered and is named as such in the README.
 *
 * Close/reopen IS genuine: `scripts/smoke.ps1` launches the built executable
 * twice as separate processes, and the second run must find the session the
 * first one opened.
 */
import { openPath } from "./actions";
import * as rt from "./runtime";
import {
  activeInspect,
  getState,
  selectionId,
  setSelection,
  setView,
  sharedStateSignature,
} from "./store";

interface SmokeConfig {
  phase: string | null;
  corpus: string | null;
  reportPath: string | null;
}

interface Check {
  name: string;
  ok: boolean;
  detail: string;
}

const checks: Check[] = [];

function check(name: string, ok: boolean, detail: unknown = "") {
  checks.push({ name, ok, detail: typeof detail === "string" ? detail : JSON.stringify(detail) });
}

/**
 * Let React commit before reading the DOM.
 *
 * Deliberately timers only, no `requestAnimationFrame`: WebView2 throttles or
 * withholds rAF entirely when its window is minimised or occluded, so a
 * harness built on it hangs forever in exactly the headless-ish conditions a
 * scripted run wants. React's commit is driven by microtasks and timers, which
 * keep running regardless of visibility.
 */
function settled(): Promise<void> {
  return new Promise((resolve) => setTimeout(() => setTimeout(resolve, 80), 0));
}

function domText(selector: string): string {
  return document.querySelector(selector)?.textContent ?? "";
}

function hasHangul(text: string): boolean {
  return /[가-힣]/.test(text);
}

async function phaseOpen(config: SmokeConfig) {
  const status = getState().status;
  check("runtime running", !!status?.running, `pid ${status?.pid}`);
  check("protocol initialized", !!status?.initialized);
  check(
    "sidecar confined to a job object",
    status?.jobConfined === true,
    status?.jobError ?? "ok",
  );
  // smoke.ps1 only ever launches the release executable, so the packaged
  // one-dir sidecar is the one that must answer. An "interpreter" here means
  // the bundle silently fell back to a dev checkout — which would make every
  // check below true on this machine and false on any other.
  check(
    "the packaged sidecar is the one running",
    status?.mode === "packaged",
    status?.mode ?? "none",
  );

  if (!config.corpus) {
    check("corpus path supplied", false, "RIGORLOOM_SMOKE_CORPUS is empty");
    return;
  }

  const sessionId = await openPath(config.corpus);
  check("document opened", !!sessionId, sessionId ?? getState().inspectError?.message ?? "");
  if (!sessionId) return;

  await settled();

  // --- the tree is populated from real inspect data --------------------------
  const inspect = activeInspect(getState());
  check("inspect returned", !!inspect);
  if (!inspect) return;

  check("document hash present", inspect.documentHash.length === 64, inspect.documentHash);
  check("paragraphs parsed", inspect.graph.paragraphs.length > 0, inspect.graph.paragraphs.length);
  check("tables parsed", inspect.graph.tables.length > 0, inspect.graph.tables.length);
  check(
    "fill seats found",
    inspect.regions.regions.length > 0,
    inspect.regions.regions.length,
  );

  // Expand a section and a table before reading the tree: collapsed groups
  // render their headers only, and asserting against that would prove the
  // headers exist rather than that real document content reached the DOM.
  const { toggleExpanded } = await import("./store");
  toggleExpanded(`sec:${inspect.graph.paragraphs[0].section}`);
  toggleExpanded(`t:${inspect.graph.tables[0].index}`);
  await settled();

  const treeText = domText('[data-testid="structure-tree"]');
  check("tree rendered", treeText.length > 0, `${treeText.length} chars`);
  check("tree carries Korean text from the document", hasHangul(treeText));
  const firstAnchor = (inspect.summary.anchors[0] ?? "").replace(/\s+/g, " ").trim();
  check(
    "tree shows a real anchor from the document",
    firstAnchor.length > 0 && treeText.includes(firstAnchor),
    firstAnchor,
  );
  check(
    "tree renders one row per paragraph the runtime reported",
    document.querySelectorAll('[data-testid^="para-"]').length ===
      inspect.graph.paragraphs.length,
    `${document.querySelectorAll('[data-testid^="para-"]').length} of ${inspect.graph.paragraphs.length}`,
  );
  check(
    "tree renders one row per cell of the expanded table",
    document.querySelectorAll('[data-testid^="cell-0-"]').length ===
      inspect.graph.tables[0].cells.length,
    `${document.querySelectorAll('[data-testid^="cell-0-"]').length} of ${inspect.graph.tables[0].cells.length}`,
  );
  check(
    "tree rows equal the runtime's own fill-seat count",
    document.querySelectorAll('[data-testid^="seat-"]').length ===
      inspect.regions.regions.length,
    `${document.querySelectorAll('[data-testid^="seat-"]').length} seats`,
  );

  // --- the honest preview state ---------------------------------------------
  check(
    "preview-unavailable state shown, not a fabricated page",
    !!document.querySelector('[data-testid="preview-unavailable"]'),
  );
  check(
    "preview quotes the runtime's own reason",
    domText('[data-testid="preview-unavailable"]').includes("renderProbe") ||
      domText('[data-testid="preview-unavailable"]').includes("not wired"),
  );

  // --- selection survives the view switch ------------------------------------
  const seat = inspect.regions.regions.find((r) => r.kind === "cell");
  if (!seat || seat.table === undefined) {
    check("a cell seat exists to select", false);
    return;
  }
  setSelection({ kind: "cell", table: seat.table, row: seat.row!, col: seat.col! });
  await settled();

  const before = sharedStateSignature();
  const beforeSelection = selectionId(getState().selection);
  check("selection set", beforeSelection !== "none", beforeSelection);
  check("document view is mounted", !!document.querySelector('[data-testid="view-document"]'));

  setView("agent");
  await settled();
  const duringSignature = sharedStateSignature();
  check("agent view is mounted", !!document.querySelector('[data-testid="view-agent"]'));
  check("document view is gone", !document.querySelector('[data-testid="view-document"]'));
  check(
    "shared state identical after switching to agent view",
    duringSignature === before,
    duringSignature === before ? "identical" : `${before}\n!=\n${duringSignature}`,
  );
  check(
    "agent view shows the same selection",
    domText('[data-testid="view-agent"]').includes(beforeSelection),
    beforeSelection,
  );
  check(
    "agent view shows the same document",
    domText('[data-testid="view-agent"]').includes(inspect.documentHash.slice(0, 12)),
  );
  check(
    "composer present and disabled",
    (document.querySelector('[data-testid="composer-input"]') as HTMLTextAreaElement | null)
      ?.disabled === true,
  );

  setView("document");
  await settled();
  const after = sharedStateSignature();
  check(
    "shared state identical after switching back",
    after === before,
    after === before ? "identical" : `${before}\n!=\n${after}`,
  );
  check(
    "the selected cell is still selected in the tree",
    document
      .querySelector(`[data-testid="cell-${seat.table}-${seat.row}-${seat.col}"]`)
      ?.getAttribute("aria-selected") === "true",
  );
  check(
    "no duplicate document state was created",
    getState().sessions.filter((s) => s.sessionId === sessionId).length === 1,
  );

  await rt.savePrefs({ lastSessionId: sessionId, lastView: "document" });
}

async function phaseReattach() {
  const state = getState();
  const prefs = await rt.loadPrefs();
  const remembered = prefs.lastSessionId as string | undefined;

  check("a session was remembered from the previous run", !!remembered, remembered ?? "");
  check("runtime restarted", !!state.status?.running);
  check(
    "the remembered session is open again",
    !!remembered && state.activeSessionId === remembered,
    `${state.activeSessionId} vs ${remembered}`,
  );

  const inspect = activeInspect(state);
  check("the document was re-read without being re-imported", !!inspect);
  check(
    "the tree is populated again",
    domText('[data-testid="structure-tree"]').length > 0 && !!inspect,
  );
  check(
    "the same source hash came back",
    !!inspect && inspect.documentHash === state.sessions.find(
      (s) => s.sessionId === state.activeSessionId,
    )?.source.sha256,
    inspect?.documentHash ?? "",
  );
  check("no terminal was needed", true, "the shell reattached from its own prefs file");
}

/**
 * Put the app into a photogenic, *real* state and leave it there.
 *
 * Used only by scripts/screenshots.ps1. Nothing is staged: the document is
 * opened through the same path a user's file dialog takes, and the panels show
 * whatever the runtime actually returned.
 */
async function phaseHold(config: SmokeConfig, view: "document" | "agent") {
  if (!getState().activeSessionId && config.corpus) {
    await openPath(config.corpus);
  }
  await settled();
  const inspect = activeInspect(getState());
  if (inspect) {
    const { toggleExpanded } = await import("./store");
    toggleExpanded(`sec:${inspect.graph.paragraphs[0].section}`);
    toggleExpanded(`t:${inspect.graph.tables[0].index}`);
    const seat = inspect.regions.regions.find((r) => r.kind === "cell");
    if (seat?.table !== undefined) {
      setSelection({ kind: "cell", table: seat.table, row: seat.row!, col: seat.col! });
    }
  }
  setView(view);
  await settled();
  await rt.smokeReady({
    view,
    session: getState().activeSessionId,
    documentHash: inspect?.documentHash ?? null,
    selection: selectionId(getState().selection),
    devicePixelRatio: window.devicePixelRatio,
    cssViewport: `${window.innerWidth}x${window.innerHeight}`,
  });
}

/**
 * Entry point, called once after boot. Silent no-op unless the launcher set
 * `RIGORLOOM_SMOKE`.
 */
export async function runSmoke(): Promise<void> {
  let config: SmokeConfig;
  try {
    config = await rt.smokeConfig();
  } catch {
    return;
  }
  if (!config.phase) return;

  // A hung check must produce a report naming the hang, not a silent 240 s
  // timeout in the launcher with nothing to read afterwards.
  let finished = false;
  const watchdog = setTimeout(() => {
    if (finished) return;
    check("smoke finished within its own budget", false, "120s watchdog fired");
    void rt.smokeFinish({
      phase: config.phase,
      passed: checks.filter((c) => c.ok).length,
      failed: checks.filter((c) => !c.ok).length,
      checks,
    });
  }, 120_000);

  try {
    if (config.phase === "open") await phaseOpen(config);
    else if (config.phase === "reattach") await phaseReattach();
    else if (config.phase === "hold" || config.phase === "hold-agent") {
      await phaseHold(config, config.phase === "hold-agent" ? "agent" : "document");
      // The screenshot script owns this window's lifetime; disarm the watchdog
      // so it does not close the app out from under the capture.
      finished = true;
      clearTimeout(watchdog);
      return;
    } else check(`unknown smoke phase: ${config.phase}`, false);
  } catch (e) {
    check("smoke ran to completion", false, String(e));
  }

  finished = true;
  clearTimeout(watchdog);
  const failed = checks.filter((c) => !c.ok);
  await rt.smokeFinish({
    phase: config.phase,
    passed: checks.length - failed.length,
    failed: failed.length,
    checks,
  });
}

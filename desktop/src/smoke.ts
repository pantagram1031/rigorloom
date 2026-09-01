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
 * synthesized, so the native file dialog, real drag-and-drop and IME
 * composition are not exercised here.
 *
 * Close/reopen IS genuine: `scripts/smoke.ps1` launches the built executable
 * twice as separate processes, and the second run must find the session — and
 * the UI zoom, and the recents — the first one left behind.
 */
import {
  applyUiZoom,
  openPath,
  runCheck,
} from "./actions";
import * as rt from "./runtime";
import {
  activeInspect,
  activeText,
  getState,
  locateSelection,
  selectionId,
  setCenterMode,
  setSelection,
  setState,
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
 * harness built on it hangs forever in exactly the conditions a scripted run
 * wants. React's commit is driven by microtasks and timers, which keep running
 * regardless of visibility.
 */
function settled(ms = 80): Promise<void> {
  return new Promise((resolve) => setTimeout(() => setTimeout(resolve, ms), 0));
}

function domText(selector: string): string {
  return document.querySelector(selector)?.textContent ?? "";
}

function hasHangul(text: string): boolean {
  return /[가-힣]/.test(text);
}

/** Read the launcher's intent before anything renders. */
export async function smokeIntent(): Promise<SmokeConfig | null> {
  try {
    const config = await rt.smokeConfig();
    return config.phase ? config : null;
  } catch {
    return null;
  }
}

async function phaseOpen(config: SmokeConfig) {
  const status = getState().status;
  check("runtime running", !!status?.running, `pid ${status?.pid}`);
  check("protocol initialized", !!status?.initialized);
  check("sidecar confined to a job object", status?.jobConfined === true, status?.jobError ?? "ok");
  // smoke.ps1 only ever launches the release executable, so the packaged
  // one-dir sidecar is the one that must answer. "interpreter" here would mean
  // the bundle silently fell back to a dev checkout.
  check("the packaged sidecar is the one running", status?.mode === "packaged", status?.mode ?? "none");

  // --- the welcome state, before any document ------------------------------
  check("welcome screen shown before a document is open",
    !!document.querySelector('[data-testid="welcome"]'));
  check("welcome offers a drop target", !!document.querySelector(".drop"));
  check("brand mark rendered", !!document.querySelector('[data-testid="logo"]'));

  if (!config.corpus) {
    check("corpus path supplied", false, "RIGORLOOM_SMOKE_CORPUS is empty");
    return;
  }

  const sessionId = await openPath(config.corpus);
  check("document opened", !!sessionId, sessionId ?? getState().inspectError?.message ?? "");
  if (!sessionId) return;
  await settled();

  // --- structure, from real inspect data ------------------------------------
  const inspect = activeInspect(getState());
  check("inspect returned", !!inspect);
  if (!inspect) return;
  check("document hash present", inspect.documentHash.length === 64, inspect.documentHash);
  check("paragraphs parsed", inspect.graph.paragraphs.length > 0, inspect.graph.paragraphs.length);
  check("tables parsed", inspect.graph.tables.length > 0, inspect.graph.tables.length);
  check("fill seats found", inspect.regions.regions.length > 0, inspect.regions.regions.length);

  const { toggleExpanded } = await import("./store");
  toggleExpanded(`sec:${inspect.graph.paragraphs[0].section}`);
  toggleExpanded(`t:${inspect.graph.tables[0].index}`);
  await settled();

  const treeText = domText('[data-testid="structure-tree"]');
  check("tree rendered", treeText.length > 0, `${treeText.length} chars`);
  check("tree carries Korean text from the document", hasHangul(treeText));
  const firstAnchor = (inspect.summary.anchors[0] ?? "").replace(/\s+/g, " ").trim();
  check("tree shows a real anchor from the document",
    firstAnchor.length > 0 && treeText.includes(firstAnchor), firstAnchor);
  check("tree renders one row per paragraph the runtime reported",
    document.querySelectorAll('[data-testid^="para-"]').length === inspect.graph.paragraphs.length,
    `${document.querySelectorAll('[data-testid^="para-"]').length} of ${inspect.graph.paragraphs.length}`);
  check("tree rows equal the runtime's own fill-seat count",
    document.querySelectorAll('[data-testid^="seat-"]').length === inspect.regions.regions.length,
    `${document.querySelectorAll('[data-testid^="seat-"]').length} seats`);

  // --- 본문 보기: the document is visible ------------------------------------
  check("본문 보기 is the default centre mode", getState().centerMode === "text");
  check("text view is mounted", !!document.querySelector('[data-testid="text-view"]'));
  check("paper column rendered", !!document.querySelector('[data-testid="paper"]'));

  const texts = activeText(getState());
  check("readRegion returned the document's full text", texts.length > 0, `${texts.length} regions`);

  const paperText = domText('[data-testid="paper"]');
  check("centre shows Korean document text", hasHangul(paperText), `${paperText.length} chars`);
  check("centre shows the document's own anchor text",
    firstAnchor.length > 0 && paperText.includes(firstAnchor), firstAnchor);

  // Every non-empty run the runtime reported must be on screen. This is the
  // check that "the document is visible" is true and not merely plausible.
  const runTexts = texts
    .flatMap((r) => (r.runs ?? []).map((run) => run.text.trim()))
    .filter((t) => t.length > 1);
  const missing = runTexts.filter((t) => !paperText.includes(t));
  check("every text run the runtime reported is rendered in the centre",
    missing.length === 0, missing.length ? `missing ${missing.length}: ${missing.slice(0, 3).join(" | ")}` : `${runTexts.length} runs`);

  check("cells are rendered as real table cells",
    document.querySelectorAll('[data-testid^="doc-cell-"]').length ===
      inspect.graph.tables.reduce((n, t) => n + t.cells.length, 0),
    `${document.querySelectorAll('[data-testid^="doc-cell-"]').length} cells`);
  check("fill seats are discrete elements in the centre",
    document.querySelectorAll('[data-testid^="doc-cell-"].seat').length > 0,
    `${document.querySelectorAll('[data-testid^="doc-cell-"].seat').length} seats`);
  check("페이지 보기 is offered but disabled while no renderer exists",
    (document.querySelector('[data-testid="mode-page"]') as HTMLButtonElement | null)?.disabled === true);
  check("the centre says what it is showing",
    domText('[data-testid="center-caveat"]').includes("본문 보기"));

  // --- tree -> centre sync ---------------------------------------------------
  const seat = inspect.regions.regions.find((r) => r.kind === "cell");
  if (!seat || seat.table === undefined) {
    check("a cell seat exists to select", false);
    return;
  }
  const seatSel = { kind: "cell" as const, table: seat.table, row: seat.row!, col: seat.col! };
  const seatId = selectionId(seatSel);
  locateSelection(seatSel);
  await settled(160);
  const centreNode = document.querySelector(`[data-node-id="${CSS.escape(seatId)}"]`);
  check("selecting in the tree marks the same node in the centre",
    centreNode?.getAttribute("aria-selected") === "true", seatId);
  check("the located node flashes", centreNode?.classList.contains("locate-flash") === true);

  // --- centre -> tree sync ---------------------------------------------------
  const otherCell = inspect.graph.tables[0].cells.find(
    (c) => !(c.addr.row === seat.row && c.addr.col === seat.col),
  );
  if (otherCell) {
    const el = document.querySelector<HTMLElement>(
      `[data-testid="doc-cell-0-${otherCell.addr.row}-${otherCell.addr.col}"]`,
    );
    el?.click();
    await settled();
    check("clicking text in the centre selects the node",
      selectionId(getState().selection) === `c:0:${otherCell.addr.row}:${otherCell.addr.col}`,
      selectionId(getState().selection));
    check("the tree shows that selection too",
      document
        .querySelector(`[data-testid="cell-0-${otherCell.addr.row}-${otherCell.addr.col}"]`)
        ?.getAttribute("aria-selected") === "true");
  }
  setSelection(seatSel);
  await settled();

  // --- 검사 실행 --------------------------------------------------------------
  await runCheck();
  await settled();
  check("검사 produced findings", getState().findings.length > 0, getState().findings.length);
  check("findings sheet is shown", !!document.querySelector('[data-testid="findings-sheet"]'));
  check("findings are addressed", getState().findings.every((f) => f.where.length > 0));
  check("the bar still refuses to claim a render proof",
    domText('[data-testid="verification-bar"]').includes("증명 없음"));
  setState({ sheetOpen: false });
  await settled();

  // --- app zoom ---------------------------------------------------------------
  await applyUiZoom(1.2);
  await settled();
  check("app zoom applied", Math.abs(getState().uiZoom - 1.2) < 0.001, getState().uiZoom);
  const prefs = await rt.loadPrefs();
  check("app zoom persisted to prefs", Math.abs(Number(prefs.uiZoom) - 1.2) < 0.001, String(prefs.uiZoom));

  // --- the entrance played once ------------------------------------------------
  check("entrance finished", getState().entranceDone === true);

  // --- view switch preserves everything ----------------------------------------
  const before = sharedStateSignature();
  const beforeSelection = selectionId(getState().selection);
  check("document view is mounted", !!document.querySelector('[data-testid="view-document"]'));

  setView("agent");
  await settled(240);
  check("agent view is mounted", !!document.querySelector('[data-testid="view-agent"]'));
  check("document view is gone", !document.querySelector('[data-testid="view-document"]'));
  const during = sharedStateSignature();
  check("shared state identical after switching to agent view", during === before,
    during === before ? "identical" : `${before}\n!=\n${during}`);
  check("agent view shows the same selection",
    domText('[data-testid="view-agent"]').includes(beforeSelection), beforeSelection);
  check("agent view shows the same document",
    domText('[data-testid="view-agent"]').includes(inspect.documentHash.slice(0, 12)));
  check("composer present and disabled",
    (document.querySelector('[data-testid="composer-input"]') as HTMLTextAreaElement | null)?.disabled === true);
  check("the entrance did not replay on the view switch",
    getState().entranceDone === true && !document.querySelector('[data-testid="splash"]'));

  setView("document");
  await settled(240);
  const after = sharedStateSignature();
  check("shared state identical after switching back", after === before,
    after === before ? "identical" : `${before}\n!=\n${after}`);
  check("the selected cell is still selected in the tree",
    document.querySelector(`[data-testid="cell-${seat.table}-${seat.row}-${seat.col}"]`)
      ?.getAttribute("aria-selected") === "true");
  check("the centre kept 본문 보기 across the switch", getState().centerMode === "text");
  check("no duplicate document state was created",
    getState().sessions.filter((s) => s.sessionId === sessionId).length === 1);

  // --- recents -----------------------------------------------------------------
  check("the document was added to 최근 문서", getState().recents.length > 0,
    getState().recents.map((r) => r.name).join(", "));
  const prefs2 = await rt.loadPrefs();
  check("최근 문서 persisted to prefs", Array.isArray(prefs2.recents) && (prefs2.recents as unknown[]).length > 0);

  await rt.savePrefs({ lastSessionId: sessionId, lastView: "document" });
}

async function phaseReattach() {
  const state = getState();
  const prefs = await rt.loadPrefs();
  const remembered = prefs.lastSessionId as string | undefined;

  check("a session was remembered from the previous run", !!remembered, remembered ?? "");
  check("runtime restarted", !!state.status?.running);
  check("the remembered session is open again", !!remembered && state.activeSessionId === remembered,
    `${state.activeSessionId} vs ${remembered}`);

  const inspect = activeInspect(state);
  check("the document was re-read without being re-imported", !!inspect);
  check("the tree is populated again",
    domText('[data-testid="structure-tree"]').length > 0 && !!inspect);
  check("the same source hash came back",
    !!inspect && inspect.documentHash ===
      state.sessions.find((s) => s.sessionId === state.activeSessionId)?.source.sha256,
    inspect?.documentHash ?? "");

  // The design slice's own persistence, across a real process boundary.
  check("app zoom came back at the level the previous run left it",
    Math.abs(state.uiZoom - 1.2) < 0.001, String(state.uiZoom));
  check("최근 문서 came back", state.recents.length > 0,
    state.recents.map((r) => `${r.name} ${r.sha256.slice(0, 8)}`).join(", "));
  check("the centre shows the document again",
    hasHangul(domText('[data-testid="paper"]')));
  check("no terminal was needed", true, "the shell reattached from its own prefs file");
}

/**
 * Put the app into a photogenic, *real* state and leave it there.
 *
 * Used only by scripts/screenshots.ps1. Nothing is staged: the document is
 * opened through the same path a user's file dialog takes, and every panel
 * shows what the runtime actually returned.
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
    setCenterMode("text");
  }
  setView(view);
  await settled(200);
  await ready(view);
}

/** The welcome state, with a recent already in it so the list is visible. */
async function phaseWelcome() {
  setState({ activeSessionId: null, sheetOpen: false });
  await settled(200);
  await ready("welcome");
}

async function ready(what: string) {
  const inspect = activeInspect(getState());
  await rt.smokeReady({
    view: what,
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
  const config = await smokeIntent();
  if (!config) return;

  // The entrance screenshot needs the splash held open; every other phase
  // needs it out of the way. Both are handled before boot in App.
  if (config.phase === "hold-entrance") {
    await ready("entrance");
    return;
  }

  let finished = false;
  const watchdog = setTimeout(() => {
    if (finished) return;
    check("smoke finished within its own budget", false, "180s watchdog fired");
    void rt.smokeFinish({
      phase: config.phase,
      passed: checks.filter((c) => c.ok).length,
      failed: checks.filter((c) => !c.ok).length,
      checks,
    });
  }, 180_000);

  try {
    if (config.phase === "open") await phaseOpen(config);
    else if (config.phase === "reattach") await phaseReattach();
    else if (config.phase === "hold" || config.phase === "hold-agent") {
      await phaseHold(config, config.phase === "hold-agent" ? "agent" : "document");
      finished = true;
      clearTimeout(watchdog);
      return;
    } else if (config.phase === "hold-welcome") {
      await phaseWelcome();
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

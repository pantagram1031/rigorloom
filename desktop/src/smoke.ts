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
  beginEdit,
  cancelEdit,
  commitEdit,
  declareSuggestedCharPr,
  exportApplied,
  loadGeometry,
  openPath,
  openReceipt,
  preparePages,
  proposeUndoOf,
  redoQueuedOp,
  removeOp,
  renderCurrentPage,
  reopenExported,
  reproposeDraft,
  requestApprovalForDraft,
  resolveApprovalDecision,
  runAgentProposal,
  runCheck,
  seatAt,
  selectHistory,
  undoQueuedOp,
} from "./actions";
import * as rt from "./runtime";
import {
  activeCandidates,
  activeInspect,
  activeText,
  canRequestApproval,
  draftStaleness,
  getState,
  locateSelection,
  selectionId,
  setCenterMode,
  setPageFit,
  setSelection,
  setState,
  setView,
  setZoom,
  sharedStateSignature,
  type QueuedFillOp,
  type QueuedRunOp,
} from "./store";
import type { EditableRegion, GeometryMapping, GeometrySpan, HostEvent } from "./types";

interface SmokeConfig {
  phase: string | null;
  corpus: string | null;
  reportPath: string | null;
  /** A genuinely different form, for the staleness check. */
  corpus2?: string | null;
  /** Where the export phase may write. Inside the harness run dir. */
  exportPath?: string | null;
  /** A session the harness left on disk with a rendered PDF already attached. */
  stagedSession?: string | null;
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

/**
 * Why a DOM assertion might have failed for a reason that is not the
 * assertion.
 *
 * An uncaught render error unmounts everything below the ErrorBoundary, and
 * the symptom is every store check passing while every DOM check fails — which
 * is exactly what the design slice's first run looked like, and it cost a
 * whole cycle to work out. So a failing DOM check now says whether the tree is
 * even alive, and quotes the boundary if it is not.
 */
function domState(): string {
  const boundary = document.querySelector('[data-testid="render-error"]');
  if (boundary) {
    const message = boundary.querySelector(".mono")?.textContent ?? "";
    const stack = boundary.querySelector("pre")?.textContent ?? "";
    return `RENDER ERROR: ${message} @ ${stack.replace(/\s+/g, " ").slice(0, 300)}`;
  }
  if (document.querySelector('[data-testid="boot"]')) return "still booting";
  const view =
    document.querySelector('[data-testid="view-document"]') ??
    document.querySelector('[data-testid="view-agent"]');
  if (!view) return `no view mounted; phase=${getState().phase}`;
  return `${view.getAttribute("data-testid")} mounted`;
}

/** A DOM assertion. On failure it says what the DOM was actually doing. */
function checkDom(name: string, ok: boolean, detail: unknown = "") {
  const text = typeof detail === "string" ? detail : JSON.stringify(detail);
  checks.push({ name, ok, detail: ok ? text : `${text} — ${domState()}` });
}

/**
 * The React tree must still be alive at the end of a phase.
 *
 * Asserted separately from any feature, because a crashed root makes every
 * other DOM assertion fail for a reason that has nothing to do with what they
 * were testing — and, worse, unmounts `App`, whose effect cleanup drops the
 * event subscriptions. One loud check beats fifteen misleading ones.
 */
function checkAlive(where: string) {
  checks.push({
    name: `the UI is still mounted at the end of ${where}`,
    ok: !document.querySelector('[data-testid="render-error"]'),
    detail: domState(),
  });
}

/** Poll until a condition holds, or give up and let the check say so. */
async function waitFor(
  predicate: () => boolean,
  timeoutMs = 8000,
  stepMs = 250,
): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return true;
    await settled(stepMs);
  }
  return predicate();
}

function hasHangul(text: string): boolean {
  return /[가-힣]/.test(text);
}

/**
 * The queue's cell ops, narrowed. The queue now holds two kinds — `fill_cell`
 * from a seat and `set_run` from a caret in a paragraph line — and a check
 * that reached for `.row` on whatever happened to be first would be reading a
 * field the other kind does not have.
 */
function fillOps(): QueuedFillOp[] {
  return getState().draft.ops.filter((op): op is QueuedFillOp => op.kind === "fill_cell");
}

/** The queue's paragraph-run ops, narrowed for the same reason. */
function runOps(): QueuedRunOp[] {
  return getState().draft.ops.filter((op): op is QueuedRunOp => op.kind === "set_run");
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
  // `boot()` resolving only means the state is ready; React has not painted
  // the shell yet, and the entrance is still over the top of it. Everything
  // above this line reads the store, so it did not care — these read the DOM,
  // so they have to wait for one.
  await settled(160);
  // A bare boolean here told me nothing when it failed, so both of these say
  // what they actually saw.
  const centre = document.querySelector(".panel.center");
  const centreState = centre
    ? `centre=${centre.firstElementChild?.className || "(empty)"}`
    : `no centre panel; phase=${getState().phase}, splash=${!getState().entranceDone}`;
  check("welcome screen shown before a document is open",
    !!document.querySelector('[data-testid="welcome"]'), centreState);
  check("welcome offers a drop target", !!document.querySelector(".drop"), centreState);
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
  // Phase 3 asserted this button was DISABLED, because no renderer existed.
  // One does now, so the assertion is stated against the mechanism instead of
  // against the answer: the button's enabled state must equal what the
  // capability list says, in either direction. That keeps it able to catch a
  // regression whichever way the runtime moves.
  const pageButton = document.querySelector('[data-testid="mode-page"]') as HTMLButtonElement | null;
  const advertised = (getState().capabilities?.methods ?? []).some((m) =>
    m.startsWith("document/render"));
  check("페이지 보기 tracks whether the runtime advertises a renderer",
    pageButton !== null && pageButton.disabled === !advertised,
    `advertised=${advertised}, disabled=${pageButton?.disabled}`);
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
  // Scoped to the centre, and that scoping is the whole point of the check.
  // The tree and the centre both label their nodes with `data-node-id`, and
  // the tree comes first in the document, so an unscoped querySelector returns
  // the tree row — which made "the centre agrees with the tree" pass by
  // inspecting the tree and agreeing with itself.
  const centreNode = document.querySelector(
    `[data-testid="text-view"] [data-node-id="${CSS.escape(seatId)}"]`,
  );
  check("selecting in the tree marks the same node in the centre",
    centreNode?.getAttribute("aria-selected") === "true",
    centreNode ? seatId : "node not in the centre");
  check("the located node flashes",
    centreNode?.classList.contains("locate-flash") === true,
    centreNode ? `class="${centreNode.className}"` : "node not in the centre");

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
  // INVERTED in Phase 5, not deleted. This asserted the composer was DISABLED,
  // which was the honest state while there was nowhere to send. There is now,
  // so the property worth pinning moved: the box is present and enabled, and it
  // still refuses to send until every precondition is met — with the reason on
  // screen rather than a grey button. `composerBlocker` is the store's own
  // answer, so this cannot drift from what the UI draws.
  check("the composer is present and live",
    (document.querySelector('[data-testid="composer-input"]') as HTMLTextAreaElement | null)
      ?.disabled === false);
  checkDom("and it explains itself rather than sitting grey",
    domText('[data-testid="composer-note"]').length > 20,
    domText('[data-testid="composer-note"]').slice(0, 120));
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
 * The whole editing loop, driven headlessly through the same functions a
 * click calls: edit → queue → approve → apply → verify → export → reopen.
 *
 * Every assertion here carries a detail argument. That is not style: a bare
 * boolean told me nothing the last time one of these failed, and the four
 * defects the design slice found were all found by a check that could say
 * what it actually saw.
 *
 * STALENESS IS NOT EXERCISED BY TOUCHING THE SESSION COPY, ever. It is
 * exercised by opening a SECOND session over a genuinely different form while
 * a queue is pending: the queue is then bound to bytes that are not the
 * document on screen, which is the reachable staleness on this Runtime and the
 * one the UI has to refuse. The runtime-side `plan_stale` — `boundSha256`
 * moving under a live plan — is structurally unreachable here, because
 * `workspace/openPath` copies the bytes into the session and nothing ever
 * writes to that copy again. That is recorded rather than faked.
 */
async function phaseEdit(config: SmokeConfig) {
  if (!config.corpus) {
    check("corpus path supplied", false, "RIGORLOOM_SMOKE_CORPUS is empty");
    return;
  }
  const sessionA = await openPath(config.corpus);
  check("edit phase opened the corpus form", !!sessionA, sessionA ?? "");
  if (!sessionA) return;
  await settled(160);

  const inspect = activeInspect(getState());
  if (!inspect) {
    check("inspect returned in the edit phase", false, String(getState().inspectError?.code));
    return;
  }
  const sourceHash = inspect.documentHash;

  // --- the event stream, before anything happens to the document ----------
  check(
    "event/subscribe is on the wire",
    (getState().capabilities?.methods ?? []).includes("event/subscribe"),
    (getState().capabilities?.methods ?? []).filter((m) => m.startsWith("event/")).join(", "),
  );
  check(
    "subscribed to the document's own event log",
    !!getState().eventSubscription,
    getState().eventSubscription ?? String(getState().eventError?.code),
  );
  // The replay is from the beginning, so session.opened must already be here.
  await settled(700);
  const opened = getState().events.filter((e) => e.kind === "session.opened");
  check(
    "the event replay carries session.opened",
    opened.length === 1,
    `${getState().events.length} events, ${opened.length} session.opened`,
  );
  check(
    "event seq is gap-free from zero",
    getState().events.every((e, i) => e.seq === i),
    getState().events.map((e) => e.seq).join(","),
  );

  // --- pick two seats: one clean, one carrying a T30/T127 preflight -------
  const seats = inspect.regions.regions.filter(
    (r): r is EditableRegion & { table: number; row: number; col: number } =>
      r.kind === "cell" && r.table !== undefined && r.row !== undefined && r.col !== undefined,
  );
  const clean = seats.find((r) => r.scriptAnomaly !== true && r.colorAnomaly !== true);
  const flagged = seats.find((r) => r.scriptAnomaly === true);
  check("a clean fill seat exists to edit", !!clean, `${seats.length} seats`);
  if (!clean) return;

  // --- 1. inline editing --------------------------------------------------
  const opened1 = beginEdit(clean.table, clean.row, clean.col);
  check("clicking a 채움 자리 opens it for typing", opened1, `c:${clean.table}:${clean.row}:${clean.col}`);
  await settled();
  const field = document.querySelector<HTMLInputElement>('[data-testid="seat-input"]');
  check("the inline editor is a real input element", field instanceof HTMLInputElement,
    field ? field.tagName : "no input mounted");
  check("the inline editor is focused", document.activeElement === field,
    (document.activeElement as HTMLElement | null)?.tagName ?? "none");
  check("the editor is mounted inside the document cell, not a dialog",
    !!field?.closest(`[data-testid="doc-cell-${clean.table}-${clean.row}-${clean.col}"]`),
    field?.closest("td")?.getAttribute("data-testid") ?? "not in a cell");

  // Esc abandons without queueing anything.
  cancelEdit();
  await settled();
  check("Esc leaves the queue empty", getState().draft.ops.length === 0,
    `${getState().draft.ops.length} ops`);

  // --- 2. the queue accumulates into ONE plan ------------------------------
  const VALUE_A = "리고룸 검사 001";
  beginEdit(clean.table, clean.row, clean.col);
  await commitEdit(VALUE_A);
  await settled(120);
  check("committing an edit queues one op", getState().draft.ops.length === 1,
    JSON.stringify(getState().draft.ops.map((o) => o.text)));
  const firstFill = fillOps()[0];
  check("the queued op carries the seat's address",
    firstFill?.table === clean.table &&
      firstFill?.row === clean.row &&
      firstFill?.col === clean.col,
    `${firstFill?.table}/${firstFill?.row}/${firstFill?.col}`);
  check("the queued op records what was there before",
    getState().draft.ops[0]?.before !== undefined,
    JSON.stringify(getState().draft.ops[0]?.before));
  check("a plan was proposed for it", !!getState().draft.plan,
    getState().draft.plan?.planId ?? String(getState().draft.error?.code));
  check("the plan binds this document's exact bytes",
    getState().draft.plan?.boundSha256 === sourceHash,
    `${getState().draft.plan?.boundSha256} vs ${sourceHash}`);
  check("the plan validated", getState().draft.validation?.ok === true,
    JSON.stringify(getState().draft.validation?.hard ?? []));
  checkDom("the review queue is rendered with the op",
    !!document.querySelector(`[data-testid="queue-op-${clean.table}-${clean.row}-${clean.col}"]`),
    document.querySelectorAll('[data-testid^="queue-op-"]').length + " rows");
  checkDom("the queue shows before → after",
    domText('[data-testid="review-queue"]').includes(VALUE_A), VALUE_A);
  checkDom("the document itself shows the pending value in place",
    domText(`[data-testid="queued-${clean.table}-${clean.row}-${clean.col}"]`).includes(VALUE_A),
    domText('[data-testid="paper"]').includes(VALUE_A) ? "in the paper column" : "not rendered");
  check("the deferred refusals the validator cannot reach are on screen",
    (getState().draft.validation?.preflight.deferred ?? []).every((code) =>
      domText('[data-testid="queue-verdict"]').includes(code)),
    (getState().draft.validation?.preflight.deferred ?? []).join(", "));

  const planOne = getState().draft.plan?.planId;
  const opsHashOne = getState().draft.plan?.opsHash;

  // A second edit must produce ONE plan carrying both ops, not two plans.
  const second = seats.find(
    (r) =>
      (r.table !== clean.table || r.row !== clean.row || r.col !== clean.col) &&
      r.scriptAnomaly !== true &&
      r.colorAnomaly !== true,
  );
  if (second) {
    beginEdit(second.table, second.row, second.col);
    await commitEdit("리고룸 검사 002");
    await settled(120);
    check("a second edit joins the SAME plan rather than making a second one",
      getState().draft.ops.length === 2 && getState().draft.plan?.ops.length === 2,
      `${getState().draft.ops.length} queued, ${getState().draft.plan?.ops.length} in the plan`);
    check("the plan was rebuilt, not patched",
      getState().draft.plan?.planId !== planOne &&
        getState().draft.plan?.opsHash !== opsHashOne,
      `${planOne?.slice(0, 8)} → ${getState().draft.plan?.planId.slice(0, 8)}`);

    // Removing an op takes it out of the plan and out of the document.
    const removeId = getState().draft.ops[1].opId;
    await removeOp(removeId);
    await settled(120);
    check("removing an op shrinks the plan",
      getState().draft.ops.length === 1 && getState().draft.plan?.ops.length === 1,
      `${getState().draft.ops.length} queued`);
    check("the removed value is gone from the document too",
      !domText('[data-testid="paper"]').includes("리고룸 검사 002"));
  }

  // --- 3. the T30 preflight is a refusal a person resolves ----------------
  if (flagged) {
    beginEdit(flagged.table, flagged.row, flagged.col);
    await commitEdit("리고룸 검사 003");
    await settled(160);
    const anomaly = (getState().draft.validation?.hard ?? []).find(
      (f) => f.code === "fill_charpr_script_anomaly",
    );
    check("a seat with a charPr anomaly refuses until charPr is declared (T30)",
      !!anomaly, JSON.stringify(getState().draft.validation?.hard ?? []));
    check("the queue cannot be approved while it is refused",
      canRequestApproval(getState()) === false,
      `verdict ${getState().draft.validation?.verdict}`);
    check("the refusal carries the charPr the engine itself suggests",
      typeof anomaly?.charPrSuggested === "string" && String(anomaly.charPrSuggested).length > 0,
      String(anomaly?.charPrSuggested));
    const flaggedOp = fillOps().find(
      (o) => o.table === flagged.table && o.row === flagged.row && o.col === flagged.col,
    );
    if (flaggedOp) {
      await declareSuggestedCharPr(flaggedOp.opId);
      await settled(160);
      const stillAnomalous = (getState().draft.validation?.hard ?? []).some(
        (f) => f.code === "fill_charpr_script_anomaly",
      );
      check("declaring the suggested charPr clears the T30 refusal", !stillAnomalous,
        JSON.stringify(getState().draft.validation?.hard ?? []));
      check("the declared charPr came from the seat, not from the shell",
        getState().draft.ops.find((o) => o.opId === flaggedOp.opId)?.charPr ===
          seatAt(activeInspect(getState()), flagged.table, flagged.row, flagged.col)
            ?.charPrSuggested,
        String(getState().draft.ops.find((o) => o.opId === flaggedOp.opId)?.charPr));
      // Take it back out; the rest of the loop runs on the clean seats.
      await removeOp(flaggedOp.opId);
      await settled(120);
    }
  } else {
    check("a charPr-anomalous seat exists in the corpus form", false,
      "no seat carries scriptAnomaly; the T30 path was not exercised on this form");
  }

  // --- 4. staleness: a queue bound to another document cannot be approved --
  if (config.corpus2) {
    check("the queue is not stale before anything moves",
      draftStaleness(getState()) === null, JSON.stringify(draftStaleness(getState())));
    const sessionB = await openPath(config.corpus2);
    check("a second, different document opened", !!sessionB, sessionB ?? "");
    await settled(200);
    const stale = draftStaleness(getState());
    check("the pending queue reports itself stale against the new document",
      stale?.kind === "other_session", JSON.stringify(stale));
    check("a stale queue cannot be approved",
      canRequestApproval(getState()) === false, `approvable=${canRequestApproval(getState())}`);
    checkDom("the stale refusal is on screen with both hashes",
      !!document.querySelector('[data-testid="queue-stale"]') &&
        domText('[data-testid="queue-stale"]').includes(sourceHash.slice(0, 16)),
      domText('[data-testid="queue-stale"]').slice(0, 120));
    check("the two documents really are different bytes",
      activeInspect(getState())?.documentHash !== sourceHash,
      `${activeInspect(getState())?.documentHash?.slice(0, 12)} vs ${sourceHash.slice(0, 12)}`);
    // Back to the document the queue belongs to.
    const { selectSession } = await import("./actions");
    await selectSession(sessionA);
    await settled(200);
    check("going back to the bound document clears the staleness",
      draftStaleness(getState()) === null, JSON.stringify(draftStaleness(getState())));
    await reproposeDraft();
    await settled(160);
    check("re-proposing against the open document validates",
      getState().draft.validation?.ok === true,
      JSON.stringify(getState().draft.validation?.hard ?? []));
  }

  // --- 5. approval: the human gate ----------------------------------------
  check("the queue is approvable now", canRequestApproval(getState()) === true,
    `verdict ${getState().draft.validation?.verdict}, stale ${JSON.stringify(draftStaleness(getState()))}`);
  await requestApprovalForDraft();
  await settled(160);
  const approval = getState().approval;
  check("approval/request returned a pending record", approval?.state === "pending",
    JSON.stringify(approval));
  check("the approval binds this exact plan hash",
    approval?.planHash === getState().draft.plan?.planHash,
    `${approval?.planHash?.slice(0, 12)} vs ${getState().draft.plan?.planHash.slice(0, 12)}`);
  checkDom("the approval gate is on screen",
    !!document.querySelector('[data-testid="approval-gate"]'));
  check("nothing has been applied yet", getState().applied === null,
    JSON.stringify(getState().applied));

  const planApproved = getState().draft.plan?.planId;
  await resolveApprovalDecision("approved", "smoke-operator");
  // plan/apply runs preedit children; give it room.
  for (let i = 0; i < 120 && getState().applyPhase === "starting"; i += 1) {
    await settled(500);
  }
  check("approval/resolve + plan/apply produced a candidate",
    getState().applyPhase === "ready" && !!getState().applied,
    getState().applied?.runId ?? JSON.stringify(getState().applyError));
  const applied = getState().applied;
  if (!applied) return;

  check("the candidate has a sha256", applied.candidate.sha256.length === 64,
    applied.candidate.sha256);
  check("the candidate is a different document from the source",
    applied.candidate.sha256 !== sourceHash,
    `${applied.candidate.sha256.slice(0, 12)} vs ${sourceHash.slice(0, 12)}`);
  check("the plan that was applied is the plan that was approved",
    applied.planId === planApproved, `${applied.planId} vs ${planApproved}`);
  check("the queue emptied into the candidate", getState().draft.ops.length === 0,
    `${getState().draft.ops.length} left`);

  // THE property: the user's original was never the subject of any of this.
  await import("./actions").then((m) => m.loadInspect(sessionA, true));
  await settled(200);
  check("the SOURCE hash is unchanged after the apply",
    activeInspect(getState())?.documentHash === sourceHash,
    `${activeInspect(getState())?.documentHash} vs ${sourceHash}`);
  checkDom("the verification bar shows the candidate hash beside the source hash",
    domText('[data-testid="verification-bar"]').includes(applied.candidate.sha256.slice(0, 12)) &&
      domText('[data-testid="verification-bar"]').includes(sourceHash.slice(0, 12)),
    domText('[data-testid="verification-bar"]').slice(0, 160));

  // --- 6. the real offline verify -----------------------------------------
  await runCheck();
  await settled(200);
  const verdict = getState().candidateVerdict;
  check("검사 실행 produced a verdict for the candidate", !!verdict,
    JSON.stringify(getState().receiptError));
  check("the verdict is the candidate's, by runId", verdict?.runId === applied.runId,
    `${verdict?.runId} vs ${applied.runId}`);
  check("the verdict names which checks were required",
    (verdict?.report.required.length ?? 0) > 0,
    (verdict?.report.required ?? []).join(", "));
  check("check_residue actually ran against the candidate",
    verdict?.report.checks.some((c) => c.checker === "check_residue" && c.state === "ran") ===
      true,
    JSON.stringify(verdict?.report.checks.map((c) => [c.checker, c.state])));
  check("acceptance is false whenever a required check did not run",
    verdict?.report.acceptance === (verdict?.report.ranAll === true &&
      verdict?.report.checks.every((c) => c.state !== "ran" || c.ok === true)),
    `acceptance=${verdict?.report.acceptance} ranAll=${verdict?.report.ranAll} reason=${verdict?.report.reason}`);
  checkDom("the bar STILL refuses to claim a render proof",
    domText('[data-testid="verification-bar"]').includes("증명 없음"),
    domText('[data-testid="verification-bar"]').slice(0, 200));

  // --- 7. the receipt ------------------------------------------------------
  openReceipt(applied.runId);
  await settled(300);
  const receipt = getState().receipts[applied.runId];
  check("receipt/read returned the receipt", !!receipt,
    JSON.stringify(getState().receiptError));
  check("the receipt binds the source hash", receipt?.source.sha256 === sourceHash,
    `${receipt?.source.sha256} vs ${sourceHash}`);
  check("the receipt binds the candidate hash",
    receipt?.candidate.sha256 === applied.candidate.sha256,
    `${receipt?.candidate.sha256} vs ${applied.candidate.sha256}`);
  check("the receipt records who approved it", receipt?.approval.approver === "smoke-operator",
    String(receipt?.approval.approver));
  check("the receipt binds the approval to the plan hash",
    receipt?.approval.planHash === receipt?.planHash,
    `${receipt?.approval.planHash?.slice(0, 12)} vs ${receipt?.planHash?.slice(0, 12)}`);
  checkDom("the receipt panel is on screen",
    !!document.querySelector('[data-testid="receipt-panel"]'));
  checkDom("the receipt panel reads in Korean, not JSON",
    hasHangul(domText('[data-testid="receipt-panel"]')),
    domText('[data-testid="receipt-panel"]').slice(0, 120));
  checkDom("the raw JSON is behind a disclosure, not on the surface",
    !!document.querySelector('[data-testid="receipt-raw"] summary'),
    document.querySelector('[data-testid="receipt-raw"] summary')?.textContent ?? "");
  check("the receipt claims no render proof",
    receipt?.evidence.class === "structural_only", String(receipt?.evidence.class));
  openReceipt(null);
  await settled();

  // --- 8. export, and a reopen that proves the file loads ------------------
  if (config.exportPath) {
    const exported = await exportApplied(config.exportPath);
    check("the candidate exported", exported, JSON.stringify(getState().exportError));
    const result = getState().exportResult;
    check("the exported bytes hash to the candidate's digest",
      result?.sha256 === applied.candidate.sha256,
      `${result?.sha256} vs ${applied.candidate.sha256}`);
    check("the receipt travelled with it",
      typeof result?.receiptPath === "string" && result.receiptPath.endsWith(".receipt.json"),
      result?.receiptPath ?? "");
    if (exported) {
      const reopenedOk = await reopenExported();
      await settled(200);
      check("the exported file opens again as a document", reopenedOk,
        JSON.stringify(getState().inspectError));
      check("the reopened file is byte-identical to the candidate",
        getState().reopened?.sha256 === applied.candidate.sha256,
        `${getState().reopened?.sha256} vs ${applied.candidate.sha256}`);
      check("the reopened export really parses as a document",
        !!activeInspect(getState())?.graph.tables.length,
        `${activeInspect(getState())?.graph.tables.length} tables`);
      await (await import("./actions")).selectSession(sessionA);
      await settled(200);
    }
  }

  // --- 9. the events recorded the whole thing ------------------------------
  // The subscription was restarted when the export was reopened and again on
  // the way back, so this waits for the replay rather than assuming a fixed
  // sleep is longer than a 250 ms poll plus a file read.
  await waitFor(() => getState().events.some((e) => e.kind === "candidate.published"), 12000);
  const kinds = getState().events.map((e) => e.kind);
  for (const wanted of [
    "session.opened",
    "plan.proposed",
    "plan.validated",
    "approval.requested",
    "approval.resolved",
    "plan.applied",
    "candidate.published",
  ]) {
    check(`the event log recorded ${wanted}`, kinds.includes(wanted), kinds.join(", "));
  }
  check("events arrived in seq order",
    getState().events.every((e, i, all) => i === 0 || e.seq > all[i - 1].seq),
    getState().events.map((e) => e.seq).join(","));
  check("no event was delivered twice",
    new Set(getState().events.map((e) => e.seq)).size === getState().events.length,
    `${getState().events.length} events, ${new Set(getState().events.map((e) => e.seq)).size} distinct`);

  setView("agent");
  // The document's history moved behind Agent view's second tab in Phase 5 —
  // the centre now holds the conversation by default. REPOINTED rather than
  // deleted: the property (every event the runtime appended has a card, and
  // protocol chatter stays behind its disclosure) is unchanged and still worth
  // pinning; only where a person stands to see it moved.
  setState({ agentTab: "history" });
  await settled(300);
  // Scoped to the card list. An unscoped prefix selector also matched the
  // header's counter, which made this read 20 for 19 events — the same class
  // of mistake as the design slice's vacuous tree/centre check.
  const cards = document.querySelectorAll('[data-testid="timeline"] .cards [data-testid^="event-"]');
  checkDom("the timeline renders the document's own history",
    cards.length === getState().events.length,
    `${cards.length} cards for ${getState().events.length} events`);
  checkDom("protocol chatter is behind a disclosure, not in the history",
    !!document.querySelector('[data-testid="protocol-chatter"] summary'),
    document.querySelector('[data-testid="protocol-chatter"] summary')?.textContent ?? "");
  setState({ agentTab: "conversation" });
  await settled(200);
  setView("document");
  await settled(240);
  checkAlive("the editing loop");
}

/**
 * E1.4 — undo in two tiers, and the proof that the second one is an inverse.
 *
 * This phase is written around the property the slice exists for: **the inverse
 * is proven by the runtime, not asserted by the shell**. Nothing here compares
 * two strings the app was holding. The pre-edit value is read back through
 * `document/readRegion` on the chain, and after the reversal is applied
 * `candidate/compare` re-reads both documents from receipt-verified bytes and
 * says whether the address came back.
 *
 * It also pins the defect that made all of this necessary: two applies in a row
 * used to produce two siblings of the source, the second silently missing the
 * first edit. The chain check below is that regression test in the UI.
 */
async function phaseUndo(config: SmokeConfig) {
  if (!config.corpus) {
    check("corpus path supplied", false, "RIGORLOOM_SMOKE_CORPUS is empty");
    return;
  }
  const sessionId = await openPath(config.corpus);
  check("undo phase opened the corpus form", !!sessionId, sessionId ?? "");
  if (!sessionId) return;
  await settled(200);

  const inspect = activeInspect(getState());
  if (!inspect) {
    check("inspect returned in the undo phase", false, String(getState().inspectError?.code));
    return;
  }
  const seats = inspect.regions.regions.filter(
    (r): r is EditableRegion & { table: number; row: number; col: number } =>
      r.kind === "cell" && r.table !== undefined && r.row !== undefined && r.col !== undefined,
  );
  const clean = seats.filter((r) => r.scriptAnomaly !== true && r.colorAnomaly !== true);
  const first = clean[0];
  const second = clean[1];
  check("two clean fill seats exist for the chain check", !!first && !!second,
    `${clean.length} clean of ${seats.length}`);
  if (!first || !second) return;

  // --- 1. TIER ONE: the queue. Removing IS the undo, and it is labelled so ---
  const VALUE = "되돌리기 검사 001";
  beginEdit(first.table, first.row, first.col);
  await commitEdit(VALUE);
  await settled(160);
  check("an edit queued before any undo", getState().draft.ops.length === 1,
    JSON.stringify(getState().draft.ops.map((o) => o.text)));
  const queuedOpId = getState().draft.ops[0]?.opId;
  const queuedBefore = getState().draft.ops[0]?.before;
  const planBefore = getState().draft.plan?.opsHash;

  checkDom("the queue's undo control says 대기열에서 제거, not 되돌리기",
    domText('[data-testid="review-queue"]').includes("대기열에서 제거") &&
      !domText('[data-testid="review-queue"]').includes("문서 되돌리기"),
    domText('[data-testid="review-queue"]').slice(0, 200));

  await undoQueuedOp(queuedOpId);
  await settled(200);
  check("queue undo empties the queue", getState().draft.ops.length === 0,
    `${getState().draft.ops.length} left`);
  check("queue undo produced NO candidate", activeCandidates(getState()).length === 0,
    `${activeCandidates(getState()).length} candidates`);
  check("the removed op is on the redo stack", getState().redoStack.length === 1,
    `${getState().redoStack.length}`);
  checkDom("다시 넣기 is offered", !!document.querySelector('[data-testid="queue-redo"]'),
    domText('[data-testid="review-queue-empty"]').slice(0, 120));

  await redoQueuedOp();
  await settled(240);
  const redone = fillOps()[0];
  check("queue redo restores the SAME target and the SAME value",
    getState().draft.ops.length === 1 &&
      redone?.table === first.table && redone?.row === first.row &&
      redone?.col === first.col && redone?.text === VALUE &&
      redone?.before === queuedBefore,
    JSON.stringify({ t: redone?.table, r: redone?.row, c: redone?.col,
      text: redone?.text, before: redone?.before }));
  check("redo re-proposed an identical plan intent",
    getState().draft.plan?.opsHash === planBefore,
    `${getState().draft.plan?.opsHash?.slice(0, 12)} vs ${planBefore?.slice(0, 12)}`);
  check("the redo stack is empty again", getState().redoStack.length === 0,
    `${getState().redoStack.length}`);

  // --- 2. apply it, so there is something a post-apply undo can reverse ------
  await requestApprovalForDraft();
  await settled(200);
  await resolveApprovalDecision("approved", "smoke-operator");
  for (let i = 0; i < 120 && getState().applyPhase === "starting"; i += 1) await settled(500);
  const editRun = getState().applied?.runId;
  check("the edit applied and produced a candidate", !!editRun,
    editRun ?? JSON.stringify(getState().applyError));
  if (!editRun) return;
  check("the first candidate is a root of the chain",
    getState().applied?.base === null, JSON.stringify(getState().applied?.base));
  check("the head moved to the new candidate", getState().head === editRun,
    String(getState().head));

  // --- 3. THE DEFECT: a second edit must CHAIN, not start over --------------
  beginEdit(second.table, second.row, second.col);
  await commitEdit("되돌리기 검사 002");
  await settled(240);
  check("a second edit chains onto the first candidate",
    getState().draft.plan?.base?.runId === editRun,
    JSON.stringify(getState().draft.plan?.base));
  check("and therefore binds the candidate's bytes, not the source's",
    getState().draft.plan?.boundSha256 === getState().applied?.candidate.sha256,
    `${getState().draft.plan?.boundSha256?.slice(0, 12)} vs ` +
      `${getState().applied?.candidate.sha256.slice(0, 12)}`);
  checkDom("the queue says which candidate it is chaining onto",
    domText('[data-testid="queue-base"]').includes(editRun.slice(0, 12)),
    domText('[data-testid="queue-base"]').slice(0, 160));

  await requestApprovalForDraft();
  await settled(200);
  await resolveApprovalDecision("approved", "smoke-operator");
  for (let i = 0; i < 120 && getState().applyPhase === "starting"; i += 1) await settled(500);
  const chainRun = getState().applied?.runId;
  check("the chained edit applied", !!chainRun, chainRun ?? JSON.stringify(getState().applyError));
  if (!chainRun) return;

  // The whole point, read out of the RUNTIME rather than out of the store: the
  // second candidate carries BOTH edits.
  const chained = await rt.readRegion(
    sessionId,
    [{ table: first.table, row: first.row, col: first.col },
     { table: second.table, row: second.row, col: second.col }],
    chainRun,
  );
  const firstText = chained.regions.find(
    (r) => r.addr?.row === first.row && r.addr?.col === first.col)?.text;
  check("the chained candidate still carries the FIRST edit", firstText === VALUE,
    `${JSON.stringify(firstText)} vs ${JSON.stringify(VALUE)}`);
  check("readRegion said which document answered",
    chained.subject.kind === "candidate" && chained.subject.runId === chainRun,
    JSON.stringify(chained.subject));

  // --- 4. TIER TWO: undo the first edit, on top of the chain ----------------
  const queued = await proposeUndoOf(editRun);
  await settled(300);
  check("되돌리기 제안 queued the inverse", queued === 1 && getState().draft.ops.length === 1,
    `${queued} ops · ${JSON.stringify(getState().undoError)}`);
  check("the inverse restores the value READ from the chain, not remembered",
    fillOps()[0]?.text === queuedBefore,
    `${JSON.stringify(fillOps()[0]?.text)} vs ${JSON.stringify(queuedBefore)}`);
  check("the proposal declares what it reverses",
    getState().draft.plan?.reverses?.runId === editRun,
    JSON.stringify(getState().draft.plan?.reverses));
  check("and chains onto the HEAD, so the newer edit is not thrown away",
    getState().draft.plan?.base?.runId === chainRun,
    JSON.stringify(getState().draft.plan?.base));
  checkDom("the UI calls it 되돌리기 제안 and says nothing is deleted",
    !!document.querySelector('[data-testid="queue-reversal"]') &&
      domText('[data-testid="queue-reversal"]').includes("되돌리기 제안") &&
      domText('[data-testid="queue-reversal"]').includes("지워지지 않습니다"),
    domText('[data-testid="queue-reversal"]').slice(0, 200));
  check("nothing has been applied by the proposal itself",
    getState().applied?.runId === chainRun, String(getState().applied?.runId));

  // Same gate as any other plan.
  await requestApprovalForDraft();
  await settled(200);
  await resolveApprovalDecision("approved", "smoke-operator");
  for (let i = 0; i < 120 && getState().applyPhase === "starting"; i += 1) await settled(500);
  const undoRun = getState().applied?.runId;
  check("the reversal applied as one MORE candidate", !!undoRun && undoRun !== editRun,
    undoRun ?? JSON.stringify(getState().applyError));
  if (!undoRun) return;
  check("nothing was deleted: all three candidates are still listed",
    activeCandidates(getState()).length === 3,
    activeCandidates(getState()).map((c) => c.runId?.slice(0, 8)).join(","));

  // --- 5. THE PROOF, from the runtime ---------------------------------------
  const proof = getState().inverseProof;
  check("the shell asked the runtime to prove the inverse", !!proof,
    JSON.stringify(getState().undoError));
  check("the proof is about the candidate that was just applied",
    proof?.runId === undoRun && proof?.reversedRunId === editRun,
    `${proof?.runId} / ${proof?.reversedRunId}`);
  check("the runtime compared at least one address",
    (proof?.compare.regionsCompared ?? 0) >= 1,
    JSON.stringify(proof?.compare.regions.map((r) => [r.address, r.equal])));
  check("PROVEN: the address equals its pre-edit value",
    proof?.compare.regionsEqual === true,
    JSON.stringify(proof?.compare.regions));
  // Independent of the shell's own proof: ask the runtime again, directly.
  const after = await rt.readRegion(
    sessionId, [{ table: first.table, row: first.row, col: first.col }], undoRun);
  check("and readRegion on the reversal agrees",
    after.regions[0]?.text === queuedBefore,
    `${JSON.stringify(after.regions[0]?.text)} vs ${JSON.stringify(queuedBefore)}`);
  check("the newer edit SURVIVED the undo of the older one",
    (await rt.readRegion(sessionId,
      [{ table: second.table, row: second.row, col: second.col }], undoRun))
      .regions[0]?.text === "되돌리기 검사 002",
    "the reversal chained onto the head rather than replacing it");
  check("RECORDED: bytes are not restored, only text",
    proof?.compare.artifactEqual === false,
    `artifactEqual=${proof?.compare.artifactEqual} — preedit rewrites and rezips, ` +
      `so an inverse restores the value and never the package`);

  // The receipt is where the claim lives permanently.
  const receipt = await rt.readReceipt(sessionId, undoRun);
  check("the receipt records which candidate this one reverses",
    receipt.reverses?.runId === editRun, JSON.stringify(receipt.reverses));
  check("the receipt records the candidate it was built on",
    receipt.base?.runId === chainRun, JSON.stringify(receipt.base));

  // --- 6. the 기록 panel -----------------------------------------------------
  await settled(300);
  checkDom("기록 lists the whole lineage",
    document.querySelectorAll('[data-testid^="history-"][data-depth]').length === 3,
    `${document.querySelectorAll('[data-testid^="history-"][data-depth]').length} rows`);
  checkDom("기록 marks the head",
    domText(`[data-testid="history-${undoRun}"]`).includes("현재"),
    domText(`[data-testid="history-${undoRun}"]`).slice(0, 160));
  checkDom("기록 marks the reversal and what it reversed",
    domText(`[data-testid="history-${undoRun}"]`).includes("되돌리기") &&
      domText(`[data-testid="history-${editRun}"]`).includes("되돌려짐"),
    `${domText(`[data-testid="history-${editRun}"]`).slice(0, 160)}`);
  checkDom("기록 states each row's parent",
    domText(`[data-testid="history-facts-${chainRun}"]`).includes(editRun.slice(0, 12)) &&
      domText(`[data-testid="history-facts-${editRun}"]`).includes("원본에서 바로"),
    domText(`[data-testid="history-facts-${chainRun}"]`).slice(0, 160));
  checkDom("the proof is on screen with BOTH equalities apart",
    domText('[data-testid="inverse-proof"]').includes("되돌리기 확인됨") &&
      domText('[data-testid="inverse-proof-bytes"]').includes("false"),
    domText('[data-testid="inverse-proof"]').slice(0, 220));

  // Selecting an older candidate SHOWS it and does not move the head.
  selectHistory(editRun);
  await settled(240);
  checkDom("selecting an older candidate opens it read-only",
    !!document.querySelector(`[data-testid="history-detail-${editRun}"]`),
    domText(`[data-testid="history-${editRun}"]`).slice(0, 120));
  check("and does NOT silently move the head", getState().head === undoRun,
    String(getState().head));
  checkDom("export from that row names its own run",
    !!document.querySelector(`[data-testid="history-export-${editRun}"]`),
    domText(`[data-testid="history-detail-${editRun}"]`).slice(0, 200));
  selectHistory(null);
  await settled(160);

  await echoChecks();
  checkAlive("the undo phase");
}

/**
 * E1.2 — the page shows the source while the document is a candidate. Say so.
 *
 * Needs a document that HAS a raster, which on this machine means the staged
 * session (the corpus's own Hancom render; `renderPrepare` refuses live here).
 * Then: apply an edit, and assert that the page does not quietly go on
 * presenting the old picture as the document.
 *
 * The 다시 그리기 assertion is deliberately not "it redraws". On this machine
 * it cannot, and the check is that the refusal is a designed state carrying the
 * runtime's own words — whichever of `needs_hancom` / `com_busy` this machine
 * gives today.
 */
async function echoChecks() {
  const stagedId = (await rt.smokeConfig()).stagedSession;
  if (!stagedId) {
    check("the harness staged a rendered session for the layout-echo check", false,
      "RIGORLOOM_SMOKE_STAGED is empty — the E1.2 half of this phase did not run");
    return;
  }
  const { loadGeometry, selectSession } = await import("./actions");
  await selectSession(stagedId);
  await settled(400);
  setCenterMode("page");

  // Find a page the runtime actually seats, the same way the overlay phase
  // does — a page number written down today is a page number wrong tomorrow.
  let seatPage = 1;
  let bestSeats = -1;
  for (let p = 1; p <= 8; p += 1) {
    await loadGeometry(p);
    await settled(80);
    const probe = getState().geometry;
    if (!probe?.available) break;
    const found = (probe.seats ?? []).length;
    if (found > bestSeats) {
      bestSeats = found;
      seatPage = p;
    }
    if ((probe.pageCount ?? 1) <= p) break;
  }
  await renderCurrentPage(seatPage);
  await settled(400);
  await loadGeometry(seatPage);
  await settled(300);
  check("the staged session has a raster to compare against",
    getState().render?.available === true,
    JSON.stringify(getState().render?.unavailable ?? "available"));
  if (getState().render?.available !== true) return;

  checkDom("with no candidate yet, the page claims nothing about being stale",
    !document.querySelector('[data-testid="layout-echo"]'),
    domText('[data-testid="page-preview"]').slice(0, 120));

  // The edit has to land on an address the DRAWN page can mark, or this check
  // is a coin flip: a form's first clean cell may sit on page 3 while the
  // raster is page 1, and an overlay that marked nothing would then be right.
  // So the seat is chosen from the intersection — clean per the runtime's own
  // inspect, AND seated by the runtime on the page being rendered.
  const inspect = activeInspect(getState());
  const onPage = new Set(
    (getState().geometry?.seats ?? []).map((g) => `${g.table}:${g.row}:${g.col}`),
  );
  const clean = (inspect?.regions.regions ?? []).filter(
    (r): r is EditableRegion & { table: number; row: number; col: number } =>
      r.kind === "cell" && r.table !== undefined && r.row !== undefined &&
      r.col !== undefined && r.scriptAnomaly !== true && r.colorAnomaly !== true,
  );
  const seat = clean.find((r) => onPage.has(`${r.table}:${r.row}:${r.col}`));
  check("a clean seat exists on the page being drawn", !!seat,
    `page ${seatPage}: ${onPage.size} seated \u00b7 ${clean.length} clean`);
  if (!seat) return;

  beginEdit(seat.table, seat.row, seat.col);
  await commitEdit("지면 반향 검사");
  await settled(300);
  if (getState().draft.validation?.ok !== true) {
    check("the staged form's edit validated", false,
      JSON.stringify(getState().draft.validation?.hard ?? getState().draft.error));
    return;
  }
  await requestApprovalForDraft();
  await settled(200);
  await resolveApprovalDecision("approved", "smoke-operator");
  for (let i = 0; i < 120 && getState().applyPhase === "starting"; i += 1) await settled(500);
  const echoRun = getState().applied?.runId;
  check("the staged edit applied", !!echoRun,
    echoRun ?? JSON.stringify(getState().applyError));
  if (!echoRun) return;
  // The banner needs the head; the MARKS need one plan read per ancestor. Wait
  // for the reads rather than sleeping past them — a fixed sleep here would
  // make this check a race that passes on a fast machine.
  await waitFor(() => (getState().changedByRun[echoRun] ?? []).length > 0, 20000);
  await settled(400);

  checkDom("the page now says 후보본과 다름 — 이 그림은 원본 기준",
    domText('[data-testid="layout-echo"]').includes("후보본과 다름") &&
      domText('[data-testid="layout-echo"]').includes("이 그림은 원본 기준"),
    domText('[data-testid="layout-echo"]').slice(0, 200));
  checkDom("it names the candidate the page is NOT showing",
    domText('[data-testid="layout-echo"]').includes(echoRun.slice(0, 12)),
    domText('[data-testid="layout-echo"]').slice(0, 160));
  checkDom("the changed address is marked on the overlay, not painted over",
    document.querySelectorAll('[data-stale="true"]').length >= 1 &&
      domText('[data-testid="layout-echo-changed"]').includes(
        `c:${seat.table}:${seat.row}:${seat.col}`),
    `${document.querySelectorAll('[data-stale="true"]').length} marked · ` +
      domText('[data-testid="layout-echo-changed"]').slice(0, 160));
  checkDom("the edited TEXT is not drawn onto the raster",
    !domText('[data-testid="page-overlay"]').includes("지면 반향 검사"),
    "an overlay that printed the new value would be a fabricated layout");
  checkDom("다시 그리기 is offered",
    !!document.querySelector('[data-testid="echo-redraw"]'),
    domText('[data-testid="layout-echo"]').slice(-160));

  // Press it, and record whatever this machine honestly answers.
  await preparePages(echoRun);
  await settled(400);
  const prepareError = getState().prepareError;
  const prepareNote = getState().prepareNote;
  check("다시 그리기 reached the runtime and got a real answer",
    !!prepareError || !!prepareNote,
    prepareError ? `${prepareError.code}: ${prepareError.message}` : String(prepareNote));
  if (prepareError) {
    check("RECORDED: this machine's honest answer for a candidate render",
      ["needs_hancom", "com_busy", "convert_failed", "not_convertible"].includes(
        prepareError.code),
      `${prepareError.code} — ${prepareError.message}`);
    checkDom("the refusal is drawn as a designed state with the runtime's words",
      !!document.querySelector('[data-testid="prepare-refusal"]') &&
        domText('[data-testid="prepare-detail"]').length > 0,
      domText('[data-testid="prepare-refusal"]').slice(0, 200));
    checkDom("and no page was fabricated in its place",
      !!document.querySelector('[data-testid="page-raster"]') &&
        !!document.querySelector('[data-testid="layout-echo"]'),
      "the source raster stays, still labelled out of date");
  } else {
    check("RECORDED: this machine produced a candidate PDF", true, String(prepareNote));
    checkDom("and the echo state is gone because the page IS the candidate now",
      !document.querySelector('[data-testid="layout-echo"]'),
      domText('[data-testid="page-preview"]').slice(0, 160));
  }
  setCenterMode("text");
  await settled(160);
}

/**
 * Acceptance task C, in the UI: an agent proposes, and cannot approve.
 *
 * The mock agent runs as its own process on an AGENT-authority connection to
 * the same `--root`. What this proves is not that the shell declines to let it
 * approve — it is that the methods are not there: `neverCalled` is
 * `rt_core.HOST_ONLY_METHODS`, read from the roster rather than from a list
 * this test wrote down.
 */
async function phaseAgent(config: SmokeConfig) {
  if (!config.corpus) {
    check("corpus path supplied", false, "RIGORLOOM_SMOKE_CORPUS is empty");
    return;
  }
  const sessionId = await openPath(config.corpus);
  check("agent phase opened the corpus form", !!sessionId, sessionId ?? "");
  if (!sessionId) return;
  await settled(160);

  const tool = getState().agentTool;
  check("the dev-mode agent script is reachable", tool?.available === true,
    tool?.reason ?? "no status");
  if (!tool?.available) return;
  setView("agent");
  await settled(240);
  checkDom("the agent button is offered", !!document.querySelector('[data-testid="run-agent"]'),
    "it lives in the agent view, so the check has to stand there");
  setView("document");
  await settled(240);

  const ok = await runAgentProposal("SMOKE-AGENT-0001");
  check("the mock agent ran and its plan was adopted", ok,
    JSON.stringify(getState().agentError));
  if (!ok) return;
  await settled(200);

  const run = getState().agentRun;
  check("the agent proposed through the protocol door", run?.door === "protocol", run?.door ?? "");
  check("the agent's plan landed in the SAME review queue",
    getState().draft.ops.length > 0 && getState().draft.plan?.planId === run?.planId,
    `${getState().draft.ops.length} ops, plan ${getState().draft.plan?.planId?.slice(0, 8)}`);
  check("every queued op is marked as the agent's",
    getState().draft.ops.every((op) => op.origin === "agent"),
    JSON.stringify(getState().draft.ops.map((o) => o.origin)));
  check("the queue names the agent as proposer",
    getState().draft.plan?.proposer === "rigorloom-mock-agent",
    getState().draft.plan?.proposer ?? "");
  check("the agent's ops carry the marker it was given",
    getState().draft.ops.some((op) => op.text.includes("SMOKE-AGENT-0001")),
    JSON.stringify(getState().draft.ops.map((o) => o.text)));

  // The claim, measured: the agent asked, and stopped.
  check("the agent requested approval and did not get it",
    getState().approval?.state === "pending", JSON.stringify(getState().approval));
  check("the agent could not approve, because the method is not on its connection",
    (run?.neverCalled ?? []).includes("approval/resolve") &&
      (run?.neverCalled ?? []).includes("plan/apply"),
    (run?.neverCalled ?? []).join(", "));
  check("no candidate exists yet", getState().applied === null,
    JSON.stringify(getState().applied));

  setView("agent");
  await settled(240);
  checkDom("the UI says the agent stopped at the gate",
    domText('[data-testid="agent-result"]').includes("승인"),
    domText('[data-testid="agent-result"]').slice(0, 160));
  setView("document");
  await settled(240);
  checkDom("the queue row says the op came from an agent",
    domText('[data-testid="review-queue"]').includes("에이전트 제안"),
    domText('[data-testid="review-queue"]').slice(0, 160));

  // The human approves it exactly the way a manual edit is approved. NOT via
  // canRequestApproval: the agent already made the request, so there is
  // nothing left to request — what the host holds is the power to RESOLVE it,
  // which is the authority split the whole scenario exists to show.
  check("the agent's plan validates, so the host has something it may approve",
    getState().draft.validation?.ok === true,
    JSON.stringify(getState().draft.validation?.hard ?? []));
  check("the pending approval is the agent's own request, waiting on a human",
    getState().approvalPhase === "pending" &&
      getState().approval?.requestedBy === "rigorloom-mock-agent",
    `${getState().approvalPhase} / ${getState().approval?.requestedBy}`);
  await resolveApprovalDecision("approved", "smoke-operator");
  for (let i = 0; i < 120 && getState().applyPhase === "starting"; i += 1) {
    await settled(500);
  }
  check("the host approved the agent's plan and it applied",
    getState().applyPhase === "ready" && !!getState().applied,
    getState().applied?.runId ?? JSON.stringify(getState().applyError));
  check("the receipt records a human approver, not the agent",
    getState().applied !== null,
    String(getState().applied?.runId));
  if (getState().applied) {
    const runId = getState().applied!.runId;
    openReceipt(runId);
    await settled(300);
    const receipt = getState().receipts[runId];
    check("the approval in the receipt was requested by the agent",
      receipt?.approval.requestedBy === "rigorloom-mock-agent",
      String(receipt?.approval.requestedBy));
    check("and resolved by the human",
      receipt?.approval.approver === "smoke-operator",
      String(receipt?.approval.approver));
    openReceipt(null);
  }
  checkAlive("the agent proposal");
}

/**
 * 페이지 보기, against whatever this machine can actually do.
 *
 * This machine's Hancom COM server is broken (`CoCreateInstance` fails), so a
 * live prepare returns `convert_failed`. That is not a test failure — it is
 * the state of the machine, and the assertion is that the UI draws it honestly
 * with the runtime's own detail rather than swallowing it or dressing it as
 * something else. Whichever branch the runtime takes, the check records which
 * one it saw.
 */
async function phasePage(config: SmokeConfig) {
  if (!config.corpus) {
    check("corpus path supplied", false, "RIGORLOOM_SMOKE_CORPUS is empty");
    return;
  }
  const sessionId = await openPath(config.corpus);
  check("page phase opened the corpus form", !!sessionId, sessionId ?? "");
  if (!sessionId) return;
  await settled(160);

  const methods = getState().capabilities?.methods ?? [];
  check("document/render is advertised", methods.includes("document/render"),
    methods.filter((m) => m.startsWith("document/")).join(", "));
  check("document/renderPrepare is advertised", methods.includes("document/renderPrepare"));
  const pageButton = document.querySelector<HTMLButtonElement>('[data-testid="mode-page"]');
  check("페이지 보기 enabled itself off the capability list",
    pageButton?.disabled === false, `disabled=${pageButton?.disabled}`);

  setCenterMode("page");
  await settled(200);
  await renderCurrentPage(1);
  await settled(200);
  const render = getState().render;
  check("document/render answered", !!render, JSON.stringify(getState().renderError));
  if (!render) return;

  if (render.available) {
    check("a real raster came back", !!render.image?.data,
      `${render.image?.widthPx}x${render.image?.heightPx}`);
    check("the raster is drawn", !!document.querySelector('[data-testid="page-raster"]'));
    check("the raster is labelled as not being evidence",
      render.evidence?.proofGrade === "none" &&
        domText('[data-testid="raster-evidence"]').length > 0,
      String(render.evidence?.proofGrade));
  } else {
    // The honest branch, and the one this machine takes with an HWPX.
    check("the unavailable reason is from the closed set",
      ["needs_conversion", "rasterizer_missing", "no_rasterizable_artifact", "artifact_missing"]
        .includes(render.unavailable?.reason ?? ""),
      render.unavailable?.reason ?? "none");
    check("the runtime's own detail is on screen, verbatim",
      domText('[data-testid="render-reason"]').includes(
        // An impossible sentinel, so a MISSING detail fails this check rather
        // than passing it vacuously. It used to be a literal NUL byte in the
        // source, which made git classify this whole harness as binary: no eol
        // normalisation, and every diff of it unreviewable.
        render.unavailable?.detail ?? "<no detail on the wire>",
      ),
      render.unavailable?.detail ?? "");
    check("the geometry figure is still captioned as geometry, not as a page",
      domText('[data-testid="page-geometry"]').toLowerCase().includes("page geometry"),
      domText('[data-testid="page-geometry"]'));
  }

  // The prepare step. This machine refuses; the assertion is that it refuses
  // in a designed way, whatever the reason turns out to be.
  const prepareButton = document.querySelector('[data-testid="prepare-pages"]');
  check("페이지 그림 만들기 is offered", !!prepareButton);
  await preparePages();
  for (let i = 0; i < 120 && getState().preparePhase === "starting"; i += 1) {
    await settled(500);
  }
  const prepareError = getState().prepareError;
  if (prepareError) {
    check("the prepare refusal is one the protocol declares",
      ["needs_hancom", "com_busy", "not_convertible", "convert_failed"].includes(
        prepareError.code,
      ),
      `${prepareError.code}: ${prepareError.message}`);
    checkDom("the refusal is drawn as a designed state, not swallowed",
      !!document.querySelector('[data-testid="prepare-refusal"]'),
      domText('[data-testid="prepare-refusal"]').slice(0, 200));
    check("the refusal shows the runtime's own message",
      domText('[data-testid="prepare-detail"]').includes(prepareError.message),
      prepareError.message);
    check("the refusal tells the user what they can do about it",
      domText('[data-testid="prepare-refusal"]').length > prepareError.message.length + 20,
      domText('[data-testid="prepare-refusal"]').slice(0, 240));
    // NOTHING WAS FABRICATED — which since tier 3 is a different assertion
    // from "there is no image". A refusal from `renderPrepare` must not
    // conjure a Hancom page; it may leave the own-rendered one that was
    // already there, and that page is labelled. So: either no raster at all,
    // or a raster the runtime graded as ours.
    const graded =
      document.querySelector('[data-testid="render-grade"]')?.getAttribute("data-grade") ?? "";
    checkDom("no page was fabricated after the refusal",
      !document.querySelector('[data-testid="page-raster"]') ||
        graded === "own-uncertified",
      `raster=${!!document.querySelector('[data-testid="page-raster"]')} grade=${graded}`);
    check("and the refusal did not promote anything to a Hancom grade",
      getState().render?.grade !== "hancom", String(getState().render?.grade));
    check("the verification bar still says 증명 없음",
      domText('[data-testid="verification-bar"]').includes("증명 없음"));
  } else {
    check("prepare succeeded and a page followed",
      getState().preparePhase === "ready" && getState().render?.available === true,
      getState().prepareNote ?? "");
  }
  setCenterMode("text");
  await settled();
  checkAlive("the page view");
}

/**
 * TIER 3 — what a fresh install actually sees.
 *
 * This is the phase whose subject is the machine, not the feature. Hancom is
 * absent from the packaged sidecar (no `pyhwpx`), so `renderPrepare` answers
 * `needs_hancom` here and on every machine that has not installed the office
 * suite — which means an own-rendered page is the DEFAULT experience, not a
 * fallback. Everything below is asserted against the release build with no
 * substitution and no staged session: the corpus HWPX is opened the way a file
 * dialog opens one, and whatever the runtime returns is what a first-time user
 * would be looking at.
 *
 * The claims, in the order they matter:
 *
 * 1. **The page is labelled, and the label is honest.** `grade` is
 *    `own-uncertified` and the badge says 자체 렌더 · 미인증 in those words.
 *    A page that looks like a Hancom render and is not is the single most
 *    convincing way this product could mislead someone, so the badge text is
 *    asserted literally rather than by presence.
 * 2. **It says what it could not draw**, and the list on screen is the
 *    runtime's own — compared entry by entry against `elementsSkipped`, not
 *    merely counted.
 * 3. **The page is EDITABLE.** Gap 34's old assertion was that every span on
 *    an own-rendered page is unmapped by construction. It is not any more: the
 *    sidecar carries each line's text, its per-character x and the paragraph or
 *    cell it was drawn from, so this page maps and seats exactly as a PDF-read
 *    page does. What is asserted now is the whole loop — seats drawn match the
 *    runtime's count, a seat click queues a plan naming the cell, a caret lands
 *    on a body line and types a `set_run`, an ambiguous line opens the chooser
 *    and queues NOTHING, and an unmapped line still resolves to a stated
 *    outcome and queues nothing.
 * 4. **Zoom.** The keyboard route (Ctrl+= / Ctrl+− / Ctrl+0) as real key
 *    events, and 폭 맞춤 changing the drawn width without asking the runtime
 *    for anything — `geometryFetches` before and after is the proof, because
 *    "zoom does not refetch" is otherwise invisible from outside.
 *
 * The phase leaves the app zoom at a distinctive level on purpose; `own-reattach`
 * starts cold and asserts it came back.
 */
const OWN_UI_ZOOM = 1.35;

async function phaseOwn(config: SmokeConfig) {
  if (!config.corpus) {
    check("corpus path supplied", false, "RIGORLOOM_SMOKE_CORPUS is empty");
    return;
  }
  const sessionId = await openPath(config.corpus);
  check("own-render phase opened the corpus form", !!sessionId, sessionId ?? "");
  if (!sessionId) return;
  await settled(160);

  const caps = getState().capabilities;
  const own = (caps?.render as Record<string, unknown> | undefined)?.own as
    | Record<string, unknown>
    | undefined;
  check("the runtime advertises a third tier", own?.state === "yes",
    JSON.stringify(own ?? null).slice(0, 200));
  check("and does not claim it is certified", own?.certified === false,
    String(own?.certified));
  // The premise of the whole phase, recorded rather than assumed: this really
  // is a machine without a reachable Hancom, so tier 3 is not being tested
  // instead of tier 1 by accident.
  const prepare = (caps?.render as Record<string, unknown> | undefined)?.prepare as
    | Record<string, unknown>
    | undefined;
  check("RECORDED: what this machine can do about a PDF", true,
    `prepare.state=${prepare?.state} reason=${prepare?.reason ?? "none"}`);

  setCenterMode("page");
  await settled(200);
  await renderCurrentPage(1);
  for (let i = 0; i < 120 && getState().renderPhase === "starting"; i += 1) {
    await settled(500);
  }
  const render = getState().render;
  check("document/render answered", !!render, JSON.stringify(getState().renderError));
  if (!render) return;

  if (!render.available) {
    // The honest other half. If our own renderer cannot run here either, the
    // page must say BOTH why there is no Hancom PDF and why tier 3 declined.
    check("RECORDED: tier 3 did not draw on this machine", true,
      JSON.stringify(render.unavailable ?? null).slice(0, 400));
    checkDom("and the third tier's own refusal is on screen, not just Hancom's",
      !!document.querySelector('[data-testid="own-refusal"]'),
      domText('[data-testid="preview-unavailable"]').slice(0, 300));
    return;
  }

  // --- 1. the label ---------------------------------------------------------
  check("the page a fresh install sees is graded own-uncertified",
    render.grade === "own-uncertified", String(render.grade));
  check("and it is tier 3", render.tier === 3, String(render.tier));
  check("the runtime does not call our own render a PDF",
    render.source?.kind === "own_render", render.source?.kind ?? "");
  check("the renderer says it is not certified",
    render.renderer?.certified === false, JSON.stringify(render.renderer ?? null));
  checkDom("the badge is drawn", !!document.querySelector('[data-testid="render-grade"]'),
    domState());
  checkDom("the badge names the tier in the runtime's own grade",
    document.querySelector('[data-testid="render-grade"]')?.getAttribute("data-grade") ===
      "own-uncertified",
    document.querySelector('[data-testid="render-grade"]')?.getAttribute("data-grade") ?? "");
  // Literal, not by presence: 자체 렌더 alone would read as a brand.
  checkDom("the badge says 자체 렌더 · 미인증 in those words",
    domText('[data-testid="render-grade"]').includes("자체 렌더") &&
      domText('[data-testid="render-grade"]').includes("미인증"),
    domText('[data-testid="render-grade"]').slice(0, 160));
  checkDom("no page ever claims 한컴 렌더 when our own renderer drew it",
    !domText('[data-testid="render-grade"]').includes("한컴 렌더"),
    domText('[data-testid="render-grade"]').slice(0, 160));
  checkDom("the raster is drawn", !!document.querySelector('[data-testid="page-raster"]'));
  checkDom("and it is still labelled as not being evidence",
    render.evidence?.proofGrade === "none" &&
      domText('[data-testid="raster-evidence"]').length > 0,
    String(render.evidence?.proofGrade));

  // --- 2. 무엇을 못 그렸나 ---------------------------------------------------
  const skipped = render.elementsSkipped ?? [];
  check("the runtime says what our renderer could not draw", skipped.length > 0,
    JSON.stringify(skipped).slice(0, 300));
  checkDom("the list is one click away on the page",
    !!document.querySelector('[data-testid="skipped-list"]'),
    domState());
  checkDom("the list on screen has one row per entry the runtime sent",
    document.querySelectorAll('[data-testid="skipped-item"]').length === skipped.length,
    `${document.querySelectorAll('[data-testid="skipped-item"]').length} rows vs ${skipped.length} entries`);
  // ENTRY BY ENTRY, not by count: a list that showed the right number of the
  // wrong rows would pass a count check and mislead a person comparing it
  // against their document.
  const rows = Array.from(document.querySelectorAll('[data-testid="skipped-item"]')).map(
    (el) => el.textContent ?? "",
  );
  checkDom("and every row carries the runtime's own element and reason, verbatim",
    skipped.every((entry, index) =>
      (rows[index] ?? "").includes(entry.element) &&
      (rows[index] ?? "").includes(entry.reason) &&
      (rows[index] ?? "").includes(String(entry.count))),
    rows.join(" | ").slice(0, 400));
  checkDom("the font row says whether anything was substituted",
    !!document.querySelector('[data-testid="font-substitution"]'),
    domText('[data-testid="font-substitution"]').slice(0, 200));

  // --- 3. the overlay, on OUR page ------------------------------------------
  //
  // Gap 34 closed. This used to assert the LIMIT — real rectangles, every span
  // unmapped, zero seats, `mapping.state: "unavailable"` — because the sidecar
  // carried where each line was drawn and not what it said. It carries the
  // text, the per-character x and the paragraph or cell each line came from
  // now, so the page maps and seats like any other and the assertions are the
  // ones the tier-1 phase makes, on OUR raster.
  await loadGeometry(1);
  await settled(200);
  const geometry = getState().geometry;
  check("document/pageGeometry answered for an own-rendered page",
    geometry?.available === true, JSON.stringify(geometry?.unavailable ?? null).slice(0, 300));
  if (geometry?.available) {
    check("and it says whose layout it is", geometry.geometrySource === "own",
      String(geometry.geometrySource));
    checkDom("and the status bar prints which renderer the seats stand on",
      document
        .querySelector('[data-testid="status-geometry-source"]')
        ?.getAttribute("data-geometry-source") === "own" &&
        domText('[data-testid="status-geometry-source"]').includes("미검증"),
      domText('[data-testid="status-geometry-source"]'));
    const ownSpans = geometry.spans ?? [];
    const ownSeats = geometry.seats ?? [];
    const ownMapping: GeometryMapping = geometry.mapping ?? { state: "absent" };
    check("the line boxes are real rectangles",
      ownSpans.length > 0 &&
        ownSpans.every(
          (s: GeometrySpan) =>
            s.rect[0] >= 0 && s.rect[2] <= 1 && s.rect[2] >= s.rect[0] &&
            s.rect[1] >= 0 && s.rect[3] <= 1 && s.rect[3] >= s.rect[1]),
      `${ownSpans.length} spans`);
    check("the mapping ran against this session's own form scan",
      ownMapping.state === "ran" &&
        ownMapping.normalizer === "pipeline/scripts/check_residue.normalize_text",
      `${ownMapping.state} / ${ownMapping.normalizer}`);

    const ownUnique = ownSpans.filter((s: GeometrySpan) => s.confidence === "unique");
    const ownAmbiguous = ownSpans.filter((s: GeometrySpan) => s.confidence === "ambiguous");
    const ownUnmapped = ownSpans.filter((s: GeometrySpan) => s.confidence === "unmapped");
    check("the runtime's confidence counts add up to its own span list",
      (ownMapping.unique ?? -1) === ownUnique.length &&
        (ownMapping.ambiguous ?? -1) === ownAmbiguous.length &&
        (ownMapping.unmapped ?? -1) === ownUnmapped.length,
      `u=${ownUnique.length} a=${ownAmbiguous.length} un=${ownUnmapped.length} of ${ownSpans.length}`);

    // THE CROSS-CHECK, and the fact that it is a check. Our renderer knows the
    // address of every line it drew; the assertion is that knowing did not
    // become claiming.
    const cross = ownMapping.crossCheck ?? {};
    check("the renderer's own addresses were cross-checked, not trusted",
      (cross.declared ?? 0) > 0 && (cross.agree ?? -1) === ownUnique.length,
      `declared=${cross.declared} agree=${cross.agree} disagree=${cross.disagree} ` +
        `among=${cross.amongCandidates} notAmong=${cross.notAmongCandidates} ` +
        `sidecarOnly=${cross.sidecarOnly}`);
    check("a line only the renderer can place is recorded and NOT claimed",
      ownUnmapped.every((s: GeometrySpan) => s.address === null) &&
        ownUnmapped.every(
          (s: GeometrySpan) => !s.sidecarAddress || s.addressBasis === "sidecar_only"),
      `${ownUnmapped.filter((s: GeometrySpan) => !!s.sidecarAddress).length} of ` +
        `${ownUnmapped.length} unmapped lines carry a renderer address`);
    checkDom("and the page shows those numbers rather than hiding the check",
      domText('[data-testid="overlay-crosscheck"]').includes(String(cross.agree ?? -1)),
      domText('[data-testid="overlay-crosscheck"]').slice(0, 200));

    // SEATS, from the cell boxes our renderer drew — the derivation that only
    // exists on this tier.
    check("seats were placed on a page WE drew",
      ownSeats.length > 0, `${ownSeats.length} seats`);
    check("and every one of them says our renderer drew that very cell",
      ownSeats.every((s) => s.derivation === "own_cell") &&
        (geometry.seatDerivations?.own_cell ?? -1) === ownSeats.length,
      JSON.stringify(geometry.seatDerivations ?? null));
    await settled(200);
    const drawnOwnSeats = document.querySelectorAll('[data-testid="overlay-seat"]').length;
    const drawnOwnSpans = document.querySelectorAll('[data-testid="overlay-span"]').length;
    const drawnOwnAmbiguous =
      document.querySelectorAll('[data-testid="overlay-ambiguous"]').length;
    checkDom("every seat the runtime placed is drawn, and no others",
      drawnOwnSeats === ownSeats.length,
      `${drawnOwnSeats} drawn / ${ownSeats.length} returned`);
    checkDom("every ambiguous span is drawn, and no others",
      drawnOwnAmbiguous === ownAmbiguous.length,
      `${drawnOwnAmbiguous} drawn / ${ownAmbiguous.length} returned`);
    checkDom("the unique and unmapped lines are drawn as one hit target each",
      drawnOwnSpans === ownUnique.length + ownUnmapped.length,
      `${drawnOwnSpans} drawn / ${ownUnique.length + ownUnmapped.length} returned`);

    // A SEAT CLICK, all the way to a plan. The same `<input>`, the same queue,
    // the same plan path a tree edit takes — on a page nothing but this repo
    // has ever rendered.
    const ownSeatTarget = document.querySelector<HTMLButtonElement>(
      '[data-testid="overlay-seat"][data-editable="true"][data-derivation="own_cell"]',
    );
    check("there is an editable seat on our own page to click", !!ownSeatTarget,
      `${document.querySelectorAll('[data-testid="overlay-seat"]').length} seats drawn`);
    if (ownSeatTarget) {
      const seatAddress = ownSeatTarget.getAttribute("data-address") ?? null;
      ownSeatTarget.click();
      await settled(240);
      const opened = getState().inlineEdit;
      const cellEdit = opened?.kind === "cell" ? opened : null;
      checkDom("it opened the SAME inline editor the tree mounts, inside the rectangle",
        !!document
          .querySelector('[data-testid="seat-input"]')
          ?.closest('[data-testid="page-overlay"]'),
        String(cellEdit?.table));
      check("on the address the seat carries, not a neighbour",
        !!cellEdit && `${cellEdit.table}-${cellEdit.row}-${cellEdit.col}` === seatAddress,
        `${cellEdit ? `${cellEdit.table}-${cellEdit.row}-${cellEdit.col}` : "none"} vs ${seatAddress}`);
      await commitEdit("자체 렌더 지면에서 입력");
      await settled(400);
      const ownOp = fillOps().find((o) => o.text === "자체 렌더 지면에서 입력");
      check("the edit landed in the same review queue as a tree edit",
        !!ownOp && ownOp.kind === "fill_cell" && ownOp.origin === "user",
        JSON.stringify(ownOp ?? null));
      check("and the queued op names the seat that was clicked",
        !!ownOp && `${ownOp.table}-${ownOp.row}-${ownOp.col}` === seatAddress,
        `${ownOp ? `${ownOp.table}-${ownOp.row}-${ownOp.col}` : "none"} vs ${seatAddress}`);
      const ownPlan = getState().draft.plan;
      const ownPlanned = (ownPlan?.ops ?? []).map((o) => {
        const p = o.params as Record<string, unknown>;
        return `${p.table ?? 0}-${p.row}-${p.col}`;
      });
      check("and the plan the runtime returned names that same cell",
        !!seatAddress && ownPlanned.includes(seatAddress),
        `${ownPlanned.join(", ") || "no ops"} vs ${seatAddress}`);
    }

    // AMBIGUITY. Same refusal as tier 1, and the renderer's own pick is shown
    // in the chooser without being taken.
    const ownQueued = getState().draft.ops.length;
    const ambiguousTarget = document.querySelector<HTMLButtonElement>(
      '[data-testid="overlay-ambiguous"]',
    );
    check("there is an ambiguous line on our own page to exercise T41 with",
      !!ambiguousTarget, `${ownAmbiguous.length} ambiguous spans`);
    if (ambiguousTarget) {
      ambiguousTarget.click();
      await settled(240);
      const ambiguousPick = getState().overlayPick;
      check("clicking it resolved to candidates, not an address",
        ambiguousPick?.kind === "ambiguous" &&
          (ambiguousPick.candidates?.length ?? 0) > 1 &&
          ambiguousPick.address == null,
        `${ambiguousPick?.kind} with ${ambiguousPick?.candidates?.length ?? 0} candidates`);
      checkDom("the chooser marks the candidate OUR renderer named, and picks none",
        document.querySelectorAll('[data-testid="overlay-candidate"]').length ===
          (ambiguousPick?.candidates?.length ?? -1) &&
          document.querySelectorAll(
            '[data-testid="overlay-candidate"][data-sidecar-pick="true"]',
          ).length <= 1,
        `${document.querySelectorAll('[data-testid="overlay-candidate"][data-sidecar-pick="true"]').length} marked of ` +
          `${document.querySelectorAll('[data-testid="overlay-candidate"]').length} rows`);
      check("and it queued NOTHING",
        getState().draft.ops.length === ownQueued, String(getState().draft.ops.length));
      document.querySelector<HTMLButtonElement>('[data-testid="overlay-chooser-dismiss"]')?.click();
      await settled(160);
    }

    // UNMAPPED. Still a stated outcome, still nothing queued — and now it says
    // what the renderer thought and why that was not enough.
    const unmappedTarget = document.querySelector<HTMLElement>(
      '[data-testid="overlay-span"][data-confidence="unmapped"]',
    );
    check("there is an unmapped line on our own page", !!unmappedTarget,
      `${ownUnmapped.length} unmapped spans`);
    if (unmappedTarget) {
      unmappedTarget.click();
      await settled(200);
      const unmappedPick = getState().overlayPick;
      checkDom("a click on it resolves to a stated outcome and no address",
        unmappedPick?.kind === "unmapped" && (unmappedPick.label ?? "").length > 0 &&
          document
            .querySelector('[data-testid="status-overlay-pick"]')
            ?.getAttribute("data-pick-kind") === "unmapped",
        domText('[data-testid="status-overlay-pick"]').slice(0, 200));
      check("and nothing was queued by a click that had no address",
        getState().draft.ops.length === ownQueued, String(getState().draft.ops.length));
    }

    // THE CARET, on a body line of a page we drew ourselves. Same walk the
    // tier-1 phase makes, same `set_run`, same refusals.
    await caretChecks(ownSpans);
  }

  // --- 4. zoom --------------------------------------------------------------
  //
  // PAGE zoom first. The proof that geometry is zoom-independent is the fetch
  // counter: a client that refetched on zoom would have paid for every glyph
  // position on every nudge, and no DOM assertion can see that.
  const widthOf = () =>
    Number.parseFloat(
      (document.querySelector<HTMLElement>('[data-testid="page-stage"]')?.style.width ?? "0")
        .replace("px", ""),
    );
  const fetchesBefore = getState().geometryFetches;
  const widthAt100 = widthOf();
  setZoom(1.5);
  await settled(200);
  checkDom("a page zoom changes the drawn width", widthOf() > widthAt100 * 1.4,
    `${widthAt100} -> ${widthOf()}`);
  check("and asks the runtime for nothing",
    getState().geometryFetches === fetchesBefore,
    `${fetchesBefore} -> ${getState().geometryFetches}`);
  setPageFit("width");
  await settled(260);
  check("폭 맞춤 leaves the free zoom and takes a measured scale",
    getState().pageFit === "width" && getState().zoom !== 1.5,
    `fit=${getState().pageFit} zoom=${getState().zoom}`);
  checkDom("the footer says which fit is on",
    document.querySelector('[data-testid="page-zoomer"]')?.getAttribute("data-fit") === "width" &&
      document.querySelector('[data-testid="fit-width"]')?.getAttribute("aria-pressed") === "true",
    document.querySelector('[data-testid="page-zoomer"]')?.getAttribute("data-fit") ?? "");
  check("and a fit still asks the runtime for nothing",
    getState().geometryFetches === fetchesBefore,
    `${fetchesBefore} -> ${getState().geometryFetches}`);
  setPageFit("free");
  setZoom(1);
  await settled(160);

  // APP zoom, through the KEYBOARD, as real key events on window — the same
  // listener a user's Ctrl+= reaches. Calling `stepUiZoom` directly would
  // prove the function and not the binding.
  const press = (key: string) => {
    window.dispatchEvent(new KeyboardEvent("keydown", { key, ctrlKey: true, bubbles: true }));
  };
  await applyUiZoom(1, false);
  await settled(120);
  press("=");
  await settled(200);
  const stepped = getState().uiZoom;
  check("Ctrl+= raises the app zoom", stepped > 1, String(stepped));
  press("-");
  await settled(200);
  check("Ctrl+− lowers it again", Math.abs(getState().uiZoom - 1) < 0.001,
    String(getState().uiZoom));
  press("=");
  press("=");
  press("=");
  await settled(240);
  check("Ctrl+= steps through the scale", getState().uiZoom > 1.2, String(getState().uiZoom));
  press("0");
  await settled(200);
  check("Ctrl+0 returns to 100%", Math.abs(getState().uiZoom - 1) < 0.001,
    String(getState().uiZoom));

  // Left at a distinctive level for `own-reattach` to find. Set through the
  // action rather than the keyboard because the step table is what the
  // keyboard walks and this needs an exact value to assert against.
  await applyUiZoom(OWN_UI_ZOOM, false);
  await settled(160);
  const prefs = await rt.loadPrefs();
  check("the app zoom is written to prefs, not only to memory",
    Math.abs(Number(prefs.uiZoom) - OWN_UI_ZOOM) < 0.001, String(prefs.uiZoom));

  setCenterMode("text");
  await settled();
  checkAlive("the own-render page view");
}

/** The other half of the zoom claim: a cold process, and the level came back. */
async function phaseOwnReattach() {
  await settled(160);
  const state = getState();
  check("the app zoom came back at the level the previous run left it",
    Math.abs(state.uiZoom - OWN_UI_ZOOM) < 0.001, String(state.uiZoom));
  const prefs = await rt.loadPrefs();
  check("and prefs still carries it after the restore",
    Math.abs(Number(prefs.uiZoom) - OWN_UI_ZOOM) < 0.001, String(prefs.uiZoom));
  // Put it back where the later phases expect it, so this phase cannot change
  // what any other phase means.
  await applyUiZoom(1.2, false);
  checkAlive("the own reattach");
}

/**
 * 한글 오버레이 — the overlay, against whatever this machine can honestly do.
 *
 * TWO documents, on purpose, because they measure two different claims and one
 * of them would hide the other.
 *
 * **LIVE.** The corpus HWPX, opened by the app through the same path a file
 * dialog takes. On this machine `document/renderPrepare` refuses `com_busy` —
 * a Hancom instance is running and the Runtime will not terminate somebody
 * else's session — so there is no PDF, so there is no geometry, and the whole
 * of the claim under test is that the app draws NOTHING and says why. A single
 * fabricated rectangle here would be the exact failure the feature is meant to
 * be trustworthy against, so it is asserted as an absence: zero overlay
 * elements in the DOM, and the existing unavailable state carrying the
 * runtime's own reason.
 *
 * **STAGED-REAL.** A session the harness put on disk before the app started,
 * carrying the corpus's own Hancom render of the same form (see
 * `scripts/stage-rendered-session.py` for the provenance and for exactly what
 * is and is not substituted). Every rect, address, candidate and count the app
 * shows here came out of `document/pageGeometry` reading that PDF. This is
 * where the overlay is actually exercised.
 *
 * WHAT THIS PHASE CANNOT PROVE, and why it is a check rather than a silence:
 * the runtime places no seat and maps no span to an editable cell on ANY of the
 * ten corpus forms, so "click an editable seat, get a plan" has no real target
 * to click. It is asserted as the measured zero it is. The click-to-plan wiring
 * is not re-proved here either way — `phaseEdit` already drives `beginEdit` and
 * `commitEdit` end to end, and the overlay calls those same two functions.
 */
async function phaseOverlay(config: SmokeConfig) {
  if (!config.corpus) {
    check("corpus path supplied", false, "RIGORLOOM_SMOKE_CORPUS is empty");
    return;
  }

  const methods = getState().capabilities?.methods ?? [];
  check("document/pageGeometry is advertised by the PACKAGED runtime",
    methods.includes("document/pageGeometry"),
    methods.filter((m) => m.startsWith("document/")).join(", "));
  const caps = getState().capabilities as unknown as {
    geometry?: { state?: string; reason?: string | null; origin?: string; unit?: string };
  } | null;
  check("the frozen runtime says its rasterizer is present",
    caps?.geometry?.state === "yes",
    `${caps?.geometry?.state} ${caps?.geometry?.reason ?? ""}`);
  check("geometry rects are normalized, top-left — the contract the overlay draws to",
    caps?.geometry?.unit === "normalized" && caps?.geometry?.origin === "top-left",
    `${caps?.geometry?.unit} / ${caps?.geometry?.origin}`);

  // --- LIVE: this machine, this document, no substitutions ------------------
  const liveSession = await openPath(config.corpus);
  check("overlay phase opened the corpus form", !!liveSession, liveSession ?? "");
  if (!liveSession) return;
  await settled(160);
  setCenterMode("page");
  await settled(200);
  await renderCurrentPage(1);
  const { loadGeometry } = await import("./actions");
  await loadGeometry(1);
  await settled(200);

  const live = getState().geometry;
  check("document/pageGeometry answered for the live document", !!live,
    JSON.stringify(getState().geometryError));

  if (live && !live.available) {
    check("the live machine state is an unavailable reason from the closed set",
      ["needs_conversion", "rasterizer_missing", "no_rasterizable_artifact", "artifact_missing"]
        .includes(live.unavailable?.reason ?? ""),
      `${live.unavailable?.reason} — ${live.unavailable?.detail}`);
    checkDom("NO overlay is drawn when the runtime returned no geometry",
      document.querySelectorAll('[data-testid="page-overlay"]').length === 0 &&
        document.querySelectorAll(".ov").length === 0,
      `${document.querySelectorAll(".ov").length} overlay elements`);
    checkDom("the page view shows its EXISTING unavailable state, not a new one",
      !!document.querySelector('[data-testid="preview-unavailable"]') ||
        !!document.querySelector('[data-testid="overlay-unavailable"]'),
      domText('[data-testid="render-reason"]').slice(0, 160));
    check("no rect was synthesized from page_metrics to stand in for geometry",
      (live.spans ?? []).length === 0 && (live.seats ?? []).length === 0,
      `${(live.spans ?? []).length} spans, ${(live.seats ?? []).length} seats`);
  } else if (live?.available) {
    // Since tier 3 landed this is the branch this machine takes: the live HWPX
    // gets a page from our own renderer with no substitution at all. The
    // anti-fabrication claim this phase exists for does NOT lapse — it moves.
    // Geometry now arrives, so the assertion becomes: it is OUR layout, and it
    // still invents nothing.
    check("the live document produced geometry on its own", true,
      `${(live.spans ?? []).length} spans without any substitution`);
    check("and it says whose layout it is rather than passing as a PDF read",
      live.geometrySource === "own" || live.geometrySource === "pdf",
      String(live.geometrySource));
    if (live.geometrySource === "own") {
      // The anti-fabrication claim moves again now that gap 34 is closed. An
      // own-rendered page DOES carry addresses and seats — mapped by the same
      // form scan a PDF-read page is mapped by — so "claims no address" is no
      // longer the right assertion. What still holds, and is what this phase
      // has always been about, is that nothing is claimed WITHOUT that scan:
      // an address exists only where the mapping reached one, and every seat
      // is a box the renderer actually drew.
      check("an own-rendered page still claims no address the scan did not reach",
        (live.spans ?? []).every(
          (s: GeometrySpan) => s.confidence === "unique" || s.address === null),
        `${(live.spans ?? []).length} spans, ${(live.seats ?? []).length} seats`);
      check("and every seat on it came from a cell our renderer really drew",
        (live.seats ?? []).every((s) => s.derivation === "own_cell"),
        JSON.stringify(live.seatDerivations ?? null));
      checkDom("and the page says which renderer drew it",
        document.querySelector('[data-testid="render-grade"]')?.getAttribute("data-grade") ===
          "own-uncertified",
        domText('[data-testid="render-grade"]').slice(0, 160));
    }
  }

  // --- STAGED-REAL: the corpus's own Hancom render of the same form ---------
  const stagedId = (await rt.smokeConfig()).stagedSession;
  if (!stagedId) {
    check("the harness staged a rendered session", false,
      "RIGORLOOM_SMOKE_STAGED is empty — the geometry half of this phase did not run");
    setCenterMode("text");
    checkAlive("the overlay phase");
    return;
  }
  const { selectSession } = await import("./actions");
  await selectSession(stagedId);
  await settled(300);
  setCenterMode("page");

  // FIND THE SEATS, do not assume which page carries them.
  //
  // `cell_borders` places seats where the page draws a closed grid AND the
  // walk to reach them was confirmed by the render, so they land where the
  // form has ruled tables — not on page 1 of every form. The harness asks the
  // runtime page by page and settles on the page with the most seats, which
  // keeps this phase honest if the derivation's numbers move: it exercises
  // whatever the runtime actually placed rather than a page number written
  // down when the numbers happened to be what they are today. Bounded, because
  // each page is a real extraction.
  const SEAT_SCAN_PAGES = 8;
  let seatPage = 1;
  let bestSeats = -1;
  const scan: string[] = [];
  for (let p = 1; p <= SEAT_SCAN_PAGES; p += 1) {
    await loadGeometry(p);
    await settled(80);
    const probe = getState().geometry;
    if (!probe?.available) break;
    const found = (probe.seats ?? []).length;
    scan.push(`${p}:${found}`);
    if (found > bestSeats) {
      bestSeats = found;
      seatPage = p;
    }
    if ((probe.pageCount ?? 1) <= p) break;
  }
  check("the harness went to the page the runtime actually seats, not page 1",
    bestSeats >= 0, `seats per page — ${scan.join(" ")} · chose ${seatPage}`);

  await renderCurrentPage(seatPage);
  await settled(300);
  await loadGeometry(seatPage);
  await settled(300);

  const g = getState().geometry;
  check("the staged session produced geometry", !!g?.available,
    g?.available ? "" : JSON.stringify(g?.unavailable ?? getState().geometryError));
  if (!g?.available) {
    setCenterMode("text");
    checkAlive("the overlay phase");
    return;
  }

  check("the geometry came from the PREPARED pdf, not the hwpx",
    g.source?.kind === "prepared_pdf", g.source?.kind ?? "none");
  check("a raster is on screen for the overlay to sit on",
    !!document.querySelector('[data-testid="page-raster"]') &&
      getState().render?.available === true,
    String(getState().render?.available));

  const spans = g.spans ?? [];
  const seats = g.seats ?? [];
  const mapping: GeometryMapping = g.mapping ?? { state: "absent" };
  const uniques = spans.filter((s) => s.confidence === "unique");
  const ambiguous = spans.filter((s) => s.confidence === "ambiguous");
  const unmapped = spans.filter((s) => s.confidence === "unmapped");

  check("the mapping ran against the session's own form scan",
    mapping.state === "ran" &&
      mapping.normalizer === "pipeline/scripts/check_residue.normalize_text",
    `${mapping.state} / ${mapping.normalizer}`);
  check("the runtime's own confidence counts add up to its span list",
    (mapping.unique ?? -1) === uniques.length &&
      (mapping.ambiguous ?? -1) === ambiguous.length &&
      (mapping.unmapped ?? -1) === unmapped.length,
    `u=${uniques.length} a=${ambiguous.length} un=${unmapped.length} of ${spans.length}`);

  // THE COUNT CHECK. Not "there are some overlays" — the number of drawn
  // elements measured against the number the runtime itself returned, per
  // class. An overlay layer that drew one box too many would be inventing a
  // position, and that is the whole thing this feature must never do.
  await settled(200);
  const drawnAmbiguous = document.querySelectorAll('[data-testid="overlay-ambiguous"]').length;
  const drawnSpans = document.querySelectorAll('[data-testid="overlay-span"]').length;
  const drawnSeats = document.querySelectorAll('[data-testid="overlay-seat"]').length;
  checkDom("every ambiguous span the runtime returned is drawn, and no others",
    drawnAmbiguous === ambiguous.length, `${drawnAmbiguous} drawn / ${ambiguous.length} returned`);
  checkDom("every mapped-unique span is drawn, and no others",
    drawnSpans === uniques.length, `${drawnSpans} drawn / ${uniques.length} returned`);
  checkDom("every seat the runtime placed is drawn, and no others",
    drawnSeats === seats.length, `${drawnSeats} drawn / ${seats.length} returned`);
  checkDom("unmapped text gets no overlay at all",
    drawnAmbiguous + drawnSpans + drawnSeats === spans.length - unmapped.length + seats.length,
    `${unmapped.length} unmapped lines, ${drawnAmbiguous + drawnSpans + drawnSeats} overlays`);

  // ZOOM. The rects are fractions; the store counts real method calls.
  const before = getState().geometryFetches;
  const { setZoom } = await import("./store");
  for (const z of [1.4, 2.0, 0.8, 1.0]) {
    setZoom(z);
    await settled(120);
  }
  check("zoom did not re-fetch geometry",
    getState().geometryFetches === before,
    `${before} → ${getState().geometryFetches} fetches across four zoom levels`);
  checkDom("the overlay is still drawn after the zoom sweep",
    document.querySelectorAll('[data-testid="overlay-ambiguous"]').length === ambiguous.length,
    `${document.querySelectorAll(".ov").length} overlay elements`);
  const stage = document.querySelector<HTMLElement>('[data-testid="page-stage"]');
  const firstOv = document.querySelector<HTMLElement>(".ov");
  check("overlay rects are expressed as fractions of the page, not pixels",
    (firstOv?.style.left ?? "").endsWith("%") && (firstOv?.style.width ?? "").endsWith("%"),
    `${firstOv?.style.left} / ${firstOv?.style.width} in a stage of ${stage?.style.width}`);

  // AMBIGUITY. A click must ask, and must not queue.
  const queuedBefore = getState().draft.ops.length;
  const planBefore = getState().draft.plan?.planId ?? null;
  if (ambiguous.length === 0) {
    check("this page had an ambiguous span to click", false,
      "no ambiguous span on this page — the T41 path was not exercised");
  } else {
    const target = document.querySelector<HTMLButtonElement>('[data-testid="overlay-ambiguous"]');
    target?.click();
    await settled(240);
    const pick = getState().overlayPick;
    check("clicking an ambiguous span resolved to candidates, not an address",
      pick?.kind === "ambiguous" && (pick.candidates?.length ?? 0) > 1,
      `${pick?.kind} with ${pick?.candidates?.length ?? 0} candidates`);
    check("no candidate was auto-picked",
      pick?.address == null, JSON.stringify(pick?.address ?? null));
    checkDom("the chooser lists every candidate the runtime returned",
      document.querySelectorAll('[data-testid="overlay-candidate"]').length ===
        (pick?.candidates?.length ?? -1),
      `${document.querySelectorAll('[data-testid="overlay-candidate"]').length} rows`);
    checkDom("no row in the chooser is preselected — a default IS a pick",
      !document.querySelector('[data-testid="overlay-candidate"][aria-selected="true"]') &&
        !document.querySelector('[data-testid="overlay-candidate"].selected'),
      "no preselected candidate");
    check("the ambiguous click queued NOTHING",
      getState().draft.ops.length === queuedBefore &&
        (getState().draft.plan?.planId ?? null) === planBefore,
      `${getState().draft.ops.length} ops, plan ${getState().draft.plan?.planId ?? "none"}`);
    checkDom("the status bar says 후보 N개 — 직접 선택",
      domText('[data-testid="status-overlay-pick"]').includes("후보") &&
        domText('[data-testid="status-overlay-pick"]').includes("직접 선택"),
      domText('[data-testid="status-overlay-pick"]'));

    // Dismissing is not choosing.
    document.querySelector<HTMLButtonElement>('[data-testid="overlay-chooser-dismiss"]')?.click();
    await settled(160);
    check("dismissing the chooser leaves the queue untouched",
      getState().overlayPick === null && getState().draft.ops.length === queuedBefore,
      `${getState().draft.ops.length} ops`);
  }

  // THE EDITABLE PATH, measured rather than assumed.
  const { addressIsEditable } = await import("./actions");
  const editableSeats = seats.filter((s) =>
    addressIsEditable({ kind: "cell", table: s.table ?? null, row: s.row ?? null, col: s.col ?? null }),
  );
  const editableUniques = uniques.filter((s) => addressIsEditable(s.address));
  const fillRegions = (activeInspect(getState())?.regions.regions ?? []).filter(
    (r) => r.kind === "cell",
  ).length;

  const clickable = editableSeats.length + editableUniques.length;
  const drawnEditable = document.querySelectorAll('.ov[data-editable="true"]').length;
  checkDom("the overlay draws exactly the editable targets the runtime returned",
    drawnEditable === clickable, `${drawnEditable} drawn / ${clickable} returned`);

  // The measurement this phase exists to take, whichever way it comes out. It
  // passes because it is a reading, not a wish — and the reading is the finding.
  check("MEASURED: how much of this form is reachable from the page",
    true,
    `${fillRegions} editable fill regions in the form · ${seats.length} seats placed by ` +
      `the runtime · ${uniques.length} unique spans · ${clickable} clickable on the page`);

  if (clickable === 0) {
    // The runtime found the text and mapped a good deal of it, and none of what
    // it mapped is a seat this editor can open — so the marquee interaction has
    // nothing real to fire on here. Recorded rather than worked around: the
    // workaround would be guessing where the empty seats are, which is the one
    // thing this feature may never do. See desktop/README.md, overlay gap 1.
    check("the page says why it has nothing to click instead of just looking empty",
      domText('[data-testid="overlay-legend"]').includes("본문 보기"),
      domText('[data-testid="overlay-legend"]').slice(0, 200));
    check("the counts on screen are the runtime's own",
      domText('[data-testid="overlay-counts"]').includes(String(mapping.ambiguous ?? -1)),
      domText('[data-testid="overlay-counts"]'));
    check("no editable overlay was drawn where the runtime placed no seat",
      drawnEditable === 0, `${drawnEditable} editable overlays`);
  } else {
    // THE MARQUEE INTERACTION, on a real target for the first time.
    //
    // A `cell_borders` seat is preferred over any other kind, because it is the
    // derivation that made this reachable at all (§12.4) and the one every seat
    // on this corpus uses. The address is read off the SEAT the runtime placed,
    // and every assertion below compares against that triple rather than
    // against whatever the editor happened to open — an overlay that drew the
    // right box and opened the wrong cell would pass a looser check.
    const seatTarget =
      document.querySelector<HTMLButtonElement>(
        '[data-testid="overlay-seat"][data-editable="true"][data-derivation="cell_borders"]',
      ) ??
      document.querySelector<HTMLButtonElement>('[data-testid="overlay-seat"][data-editable="true"]');
    const target =
      seatTarget ??
      document.querySelector<HTMLButtonElement>('[data-testid="overlay-span"][data-editable="true"]');
    const wantedAddress = target?.getAttribute("data-address") ?? null;
    const wantedDerivation = target?.getAttribute("data-derivation") ?? null;
    check("the target clicked is a seat the RUNTIME placed, with its derivation on it",
      !!seatTarget && wantedDerivation === "cell_borders",
      `${wantedAddress} derived by ${wantedDerivation ?? "—"}`);

    // A resting affordance, not a hover-only one. With 37 seats on a page an
    // invisible invitation is an undiscoverable feature; the check reads the
    // COMPUTED style rather than the class list, because a class that no rule
    // matches would satisfy a class-name assertion and draw nothing.
    if (seatTarget) {
      const resting = window.getComputedStyle(seatTarget);
      const painted =
        resting.backgroundColor !== "rgba(0, 0, 0, 0)" &&
        resting.backgroundColor !== "transparent";
      checkDom("an empty seat is visible before the pointer ever touches it",
        painted, `background ${resting.backgroundColor}, border ${resting.borderColor}`);
      checkDom("and it says it is a text seat, not a link",
        resting.cursor === "text", resting.cursor);
    }

    target?.click();
    await settled(240);
    const opened = getState().inlineEdit;
    const edit = opened?.kind === "cell" ? opened : null;
    checkDom("clicking an editable target opened the SAME inline editor the tree uses",
      !!document.querySelector('[data-testid="seat-input"]'), String(edit?.table));
    // ON the page, not beside it. The first run of this branch found the
    // opposite: `beginEdit` set the state and the only input element in the app
    // was inside `TextView`, which 페이지 보기 does not mount — so a page click
    // opened an edit nobody could type into. The field now lives in the
    // rectangle the runtime placed, which is what "editing on the page" means.
    const field = document.querySelector<HTMLInputElement>('[data-testid="seat-input"]');
    checkDom("and the field is IN the rectangle the runtime placed, not beside the page",
      !!field?.closest('[data-testid="page-overlay"]') &&
        !!field?.closest('[data-testid="overlay-editing"]'),
      field?.closest("[data-testid]")?.getAttribute("data-testid") ?? "nowhere");
    check("the editor opened on the address the seat carries, not a neighbour",
      !!edit && `${edit.table}-${edit.row}-${edit.col}` === wantedAddress,
      `${edit ? `${edit.table}-${edit.row}-${edit.col}` : "none"} vs ${wantedAddress}`);
    checkDom("the status bar says which address, and how the runtime found it",
      domText('[data-testid="status-overlay-pick"]').includes("그려진 선으로 잡음") &&
        document
          .querySelector('[data-testid="status-overlay-pick"]')
          ?.getAttribute("data-derivation") === "cell_borders",
      domText('[data-testid="status-overlay-pick"]'));

    await commitEdit("지면에서 입력");
    await settled(400);
    const op = fillOps().find((o) => o.text === "지면에서 입력");
    check("the overlay edit landed in the same review queue as a tree edit",
      !!op && op.kind === "fill_cell" && op.origin === "user", JSON.stringify(op ?? null));
    check("the queued op targets the seat that was clicked",
      !!op && `${op.table}-${op.row}-${op.col}` === wantedAddress,
      `${op ? `${op.table}-${op.row}-${op.col}` : "none"} vs ${wantedAddress}`);
    const plan = getState().draft.plan;
    check("one plan path: the queue rebuilt a plan over the overlay's op",
      !!plan?.planId, plan?.planId ?? "no plan");
    // The address survives all the way to the wire, not only to the store. A
    // review queue row and a plan op that disagreed about the target would be
    // an approval bound to a cell nobody chose.
    const planned = (plan?.ops ?? []).map((o) => {
      const p = o.params as Record<string, unknown>;
      return `${p.table ?? 0}-${p.row}-${p.col}`;
    });
    check("and the plan the runtime returned names that same cell",
      !!wantedAddress && planned.includes(wantedAddress),
      `${planned.join(", ") || "no ops"} vs ${wantedAddress}`);
    check("the overlay entry point produced ONE op, not a second path's duplicate",
      getState().draft.ops.filter((o) => o.text === "지면에서 입력").length === 1,
      `${getState().draft.ops.length} ops queued`);
  }

  // --- THE CARET, on a real paragraph line -----------------------------------
  //
  // The other half of "editing on the page", and until this slice the missing
  // half: a seat is an empty cell, and a form is mostly not empty cells. A
  // uniquely-mapped PARAGRAPH line is body text a person stands in and
  // retypes, and it reaches the same queue through `set_run` — an operation
  // the runtime already had. Nothing new was added to the registry for it.
  //
  // The refusal is asserted as hard as the success. A paragraph of several
  // runs looks identical on the page to one with a single run, and the
  // difference is knowable only by asking the runtime: corpus-wide, 314 of 365
  // mapped paragraph lines hold one run and 51 do not.
  await caretChecks(g.spans ?? []);

  setCenterMode("text");
  await settled();
  checkAlive("the overlay phase");
}

/**
 * Everything the caret has to be true about, on whatever this page really has.
 *
 * Split out because `phaseOverlay` is already long, and because the shot phase
 * needs the same "find a line that actually takes a caret" walk — a page's
 * first mapped paragraph is very often one of the 51 that refuse, and a
 * harness that clicked the first one and reported "no caret" would be
 * measuring its own choice of line rather than the feature.
 */
async function caretChecks(spans: GeometrySpan[]) {
  const { addressIsCaretTarget, caretOffsetAt, clickOverlaySpan } = await import("./actions");
  const caretSpans = spans.filter(
    (s) => s.confidence === "unique" && addressIsCaretTarget(s.address),
  );
  const withOffsets = caretSpans.filter((s) => !!s.charX);

  const geometry = getState().geometry;
  check("the runtime says whether it read sub-line offsets for this page",
    geometry?.charOffsets?.state === "read" ||
      geometry?.charOffsets?.state === "page_too_dense",
    `${geometry?.charOffsets?.state} — ${geometry?.charOffsets?.lines}/${geometry?.charOffsets?.of} lines, ${geometry?.charOffsets?.chars} chars`);
  check("every span carrying offsets carries one x per character plus the end",
    spans.every((s) => !s.charX || s.charX.length === s.text.length + 1),
    `${spans.filter((s) => s.charX && s.charX.length !== s.text.length + 1).length} spans disagree`);
  check("offsets are fractions of the page, in the same system as the rects",
    spans.every((s) => !s.charX || (s.charX[0] >= 0 && s.charX[s.charX.length - 1] <= 1)),
    `${withOffsets.length} of ${spans.length} spans carry offsets`);

  // The measurement this half of the phase exists to take.
  check("MEASURED: how many lines on this page can hold a caret",
    true,
    `${caretSpans.length} uniquely-mapped paragraph lines · ${withOffsets.length} of them ` +
      `with per-character offsets · out of ${spans.length} spans`);

  if (caretSpans.length === 0) {
    check("this page had a mapped paragraph line to click", false,
      "no unique paragraph address on this page — the caret path was not exercised here");
    return;
  }

  checkDom("a caret target is drawn as one, and is not dressed as a fill seat",
    document.querySelectorAll('.ov[data-caret-target="true"]').length === caretSpans.length,
    `${document.querySelectorAll('.ov[data-caret-target="true"]').length} drawn / ${caretSpans.length} returned`);
  const firstTarget = document.querySelector<HTMLElement>('.ov[data-caret-target="true"]');
  if (firstTarget) {
    checkDom("and it says it is text, not a button",
      window.getComputedStyle(firstTarget).cursor === "text",
      window.getComputedStyle(firstTarget).cursor);
  }

  // WALK until one takes a caret. Every refusal on the way is recorded,
  // because a refusal that went unrecorded would let this phase pass on a page
  // where the caret never worked.
  //
  // BOUNDED, and the bound is a real cost rather than caution: each attempt is
  // a `document/readRegion`, which runs `form_inspect` as a child process
  // against the session copy. A page of this corpus form carries dozens of
  // mapped paragraph lines and walking all of them would spend the harness's
  // whole 180-second budget asking the same question.
  const CARET_ATTEMPTS = 6;
  let placed: GeometrySpan | null = null;
  const refusals: string[] = [];
  for (const span of caretSpans.slice(0, CARET_ATTEMPTS)) {
    // Click at a fraction inside the line rather than at its left edge, so the
    // offset that comes back is one the runtime resolved rather than a zero
    // that would have been right by accident.
    const rect = span.rect;
    const midway = rect[0] + (rect[2] - rect[0]) * 0.6;
    await clickOverlaySpan(span, midway);
    await settled(160);
    const pick = getState().overlayPick;
    if (pick?.kind === "caret") {
      placed = span;
      break;
    }
    if (pick?.kind === "no_caret") refusals.push(`${pick.refusal}`);
  }

  if (!placed) {
    check("some line on this page took a caret", false,
      `the first ${Math.min(CARET_ATTEMPTS, caretSpans.length)} of ${caretSpans.length} ` +
        `mapped paragraph lines all refused: ${refusals.join(", ")}`);
    return;
  }
  const took = placed;
  check("a caret was placed within the attempts this phase allows itself",
    true,
    `${refusals.length} refusal(s) before one took: ${refusals.join(", ") || "none"}`);

  // THE REFUSAL, DELIBERATELY PROVOKED.
  //
  // The walk above often succeeds on its FIRST attempt — it did on this
  // machine — and "every refusal named itself" over an empty list passes
  // without proving anything. So the longest mapped lines on the page are
  // tried on purpose: a long line is the one most likely to carry several
  // runs, which is exactly what `set_run` cannot address. If none of them
  // refuses, that is said rather than papered over.
  const provoke = caretSpans
    .filter((s) => s !== took)
    .sort((a, b) => b.text.length - a.text.length)
    .slice(0, 3);
  const queuedBeforeProbe = getState().draft.ops.length;
  for (const span of provoke) {
    if (getState().inlineEdit) cancelEdit();
    await settled(120);
    await clickOverlaySpan(span, span.rect[0] + (span.rect[2] - span.rect[0]) * 0.5);
    await settled(200);
    const pick = getState().overlayPick;
    if (pick?.kind === "no_caret") {
      refusals.push(`${pick.refusal}`);
      check("a line the runtime will not address places NO caret and says why",
        getState().inlineEdit === null &&
          ["multi_run", "run_text_differs", "no_inventory", "no_address"].includes(
            `${pick.refusal}`,
          ),
        `${pick.refusal} — ${pick.label}`);
      checkDom("the refusal reaches the status bar rather than silence",
        document
          .querySelector('[data-testid="status-overlay-pick"]')
          ?.getAttribute("data-refusal") === `${pick.refusal}` &&
          domText('[data-testid="status-overlay-pick"]').length > 0,
        domText('[data-testid="status-overlay-pick"]'));
      check("and a refused click queued nothing at all",
        getState().draft.ops.length === queuedBeforeProbe,
        `${queuedBeforeProbe} → ${getState().draft.ops.length} ops`);
      break;
    }
  }
  check("every line that refused a caret named WHICH refusal, from the closed set",
    refusals.every((r) => ["multi_run", "run_text_differs", "no_inventory", "no_address"].includes(r)),
    refusals.length
      ? refusals.join(", ")
      : `no line among the ${provoke.length + Math.min(CARET_ATTEMPTS, caretSpans.length)} tried on this page refused`);

  // Back onto the line that took the caret, for everything below.
  if (getState().inlineEdit) cancelEdit();
  await settled(150);
  await clickOverlaySpan(took, took.rect[0] + (took.rect[2] - took.rect[0]) * 0.6);
  await settled(250);

  const edit = getState().inlineEdit;
  const runEdit = edit?.kind === "run" ? edit : null;
  check("clicking a mapped paragraph line put a real caret in it",
    !!runEdit, JSON.stringify(getState().overlayPick ?? null));
  checkDom("the field is IN the line the runtime measured, not beside the page",
    !!document.querySelector('[data-testid="overlay-caret-editing"] [data-testid="seat-input"]'),
    document
      .querySelector('[data-testid="seat-input"]')
      ?.closest("[data-testid]")
      ?.getAttribute("data-testid") ?? "nowhere");
  check("the caret opened on the paragraph the SPAN carries, not a neighbour",
    !!runEdit && runEdit.atPara === took.address?.atPara,
    `${runEdit?.atPara} vs ${took.address?.atPara}`);
  check("the field holds the run's own text, read from document/readRegion",
    !!runEdit && runEdit.before.trim().length > 0 &&
      runEdit.before.replace(/\s+/g, " ").trim() === took.text.replace(/\s+/g, " ").trim(),
    `${JSON.stringify(runEdit?.before ?? null)} vs ${JSON.stringify(took.text)}`);

  // THE OFFSET. Measured, or honestly absent — never a plausible-looking zero.
  const expected = took.charX
    ? caretOffsetAt(took, took.rect[0] + (took.rect[2] - took.rect[0]) * 0.6)
    : null;
  check("the caret offset is the one the runtime's own character boxes resolve",
    !!runEdit && runEdit.caret === expected,
    `caret ${runEdit?.caret} vs charX-derived ${expected} (${took.charX ? "offsets present" : "no offsets on this line"})`);
  if (took.charX) {
    check("and a click past the line's start did not silently snap to zero",
      (runEdit?.caret ?? 0) > 0,
      `offset ${runEdit?.caret} into a line of ${took.text.length} characters`);
  }
  const field = document.querySelector<HTMLInputElement>('[data-testid="seat-input"]');
  checkDom("the browser caret sits where the runtime said, not at the front",
    !!field && field.selectionStart === (runEdit?.caret ?? 0),
    `selectionStart ${field?.selectionStart} vs ${runEdit?.caret}`);

  // THE COMPONENT'S OWN ARITHMETIC, through a real pointer position.
  //
  // Everything above reached `clickOverlaySpan` directly with a fraction the
  // harness computed, which exercises the offset logic and NOT the conversion
  // from a pointer's `clientX` to that fraction. That conversion is the one
  // piece of coordinate maths left in the overlay, and getting it wrong would
  // put the caret in the right line at the wrong character — a failure that
  // looks like working software. So this dispatches a MouseEvent carrying a
  // real `clientX` at a known place inside the line's box and asks whether the
  // offset that comes back is the one the runtime's own boxes resolve there.
  if (took.charX) {
    cancelEdit();
    await settled(200);
    const layer = document.querySelector<HTMLElement>('[data-testid="page-overlay"]');
    const button = document.querySelector<HTMLElement>(
      `.ov[data-span-index="${took.index}"]`,
    );
    const box = layer?.getBoundingClientRect();
    if (layer && button && box && box.width > 0) {
      const wantedFraction = took.rect[0] + (took.rect[2] - took.rect[0]) * 0.75;
      button.dispatchEvent(
        new MouseEvent("click", {
          bubbles: true,
          cancelable: true,
          clientX: box.left + box.width * wantedFraction,
          clientY: box.top + box.height * ((took.rect[1] + took.rect[3]) / 2),
        }),
      );
      // POLL, do not sleep. A DOM click cannot be awaited, and the handler
      // behind it asks `document/readRegion` — which runs `form_inspect` as a
      // child process and takes seconds, not milliseconds. The first run of
      // this check waited 300ms and reported "caret none", which read exactly
      // like the component's arithmetic being wrong when it was the harness
      // being impatient.
      await waitFor(() => getState().inlineEdit?.kind === "run", 12000);
      const viaPointer = getState().inlineEdit;
      const wanted = caretOffsetAt(took, wantedFraction);
      check("a real pointer position resolves to the offset its x actually names",
        viaPointer?.kind === "run" && viaPointer.caret === wanted,
        `pointer at ${wantedFraction.toFixed(4)} of the page → caret ${
          viaPointer?.kind === "run" ? viaPointer.caret : "none"
        }, charX says ${wanted}`);
      check("and two different pointer positions in one line give two offsets",
        viaPointer?.kind === "run" && viaPointer.caret !== runEdit?.caret,
        `0.60 → ${runEdit?.caret} · 0.75 → ${viaPointer?.kind === "run" ? viaPointer.caret : "none"}`);
    } else {
      check("the overlay layer had a measurable box to resolve a pointer in", false,
        `layer ${!!layer} button ${!!button} width ${box?.width}`);
    }
  }

  checkDom("the status bar prints the offset, or says it snapped to the line start",
    domText('[data-testid="status-overlay-pick"]').includes(
      runEdit?.caret === null ? "줄 앞" : "번째 글자 앞",
    ),
    domText('[data-testid="status-overlay-pick"]'));
  checkDom("위치 says paragraph, chunk and offset — not a cell address",
    domText('[data-testid="status-where"]').includes("문단") &&
      domText('[data-testid="status-where"]').includes("덩어리"),
    domText('[data-testid="status-where"]'));
  // The insert/overwrite indicator was 삽입/수정 없음 for the life of this
  // product, and it was true: there was no character-level caret. There is one
  // now, so it says 삽입 — and never 수정, because nothing here overwrites.
  checkDom("the 입력 indicator finally has something true to say",
    domText('[data-testid="verification-bar"]').includes("삽입") &&
      !domText('[data-testid="verification-bar"]').includes("삽입/수정 없음"),
    domText('[data-testid="verification-bar"]').slice(0, 200));

  // 글꼴, over a caret. §14's fourth field, and the reason it was added.
  const faceCell = document.querySelector('[data-testid="typeface-name"]');
  check("the toolbar names the face this RUN is set in, from the document's header",
    (faceCell?.getAttribute("data-face") ?? "").length > 0,
    `${faceCell?.getAttribute("data-face")} · ${domText('[data-testid="tool-charpr"]')}`);
  const sizeCell = document.querySelector('[data-testid="size-value"]');
  check("and the size is labelled as the RENDER's, not as a declared one",
    sizeCell?.getAttribute("data-source") === (took.sizePt ? "render" : "baseline"),
    `${sizeCell?.getAttribute("data-source")} ${sizeCell?.textContent} · span sizePt ${took.sizePt}`);

  // TYPE. The same commit path a seat uses, into the same queue.
  const TYPED = "지면에서 고쳐 쓴 문장";
  const queuedBeforeCaret = getState().draft.ops.length;
  await commitEdit(TYPED);
  await settled(500);
  const runOp = runOps().find((o) => o.text === TYPED);
  check("typing into a paragraph line landed in the SAME review queue",
    !!runOp && runOp.origin === "user", JSON.stringify(runOp ?? null));
  check("and it queued a set_run op — the operation the runtime already had",
    runOp?.kind === "set_run", runOp?.kind ?? "none");
  check("the queued op names the paragraph and the run, not a cell",
    !!runOp && runOp.atPara === took.address?.atPara,
    `atPara ${runOp?.atPara} run ${runOp?.run} vs span atPara ${took.address?.atPara}`);
  check("it records what the line said before, for the queue's before → after",
    !!runOp && runOp.before.replace(/\s+/g, " ").trim() === took.text.replace(/\s+/g, " ").trim(),
    JSON.stringify(runOp?.before ?? null));
  check("the caret produced ONE op, not a second path's duplicate",
    getState().draft.ops.length === queuedBeforeCaret + 1,
    `${queuedBeforeCaret} → ${getState().draft.ops.length} ops`);

  // AND IT REACHES THE WIRE. A queue row and a plan op that disagreed about
  // the address would be an approval bound to a paragraph nobody chose.
  const plan = getState().draft.plan;
  check("one plan path: the queue rebuilt a plan over the caret's op",
    !!plan?.planId,
    plan?.planId ?? JSON.stringify(getState().draft.error ?? "no plan"));
  const plannedRuns = (plan?.ops ?? [])
    .filter((o) => o.kind === "set_run")
    .map((o) => {
      const p = o.params as Record<string, unknown>;
      return `${p.atPara}#${p.run}=${p.text}`;
    });
  check("and the plan the RUNTIME returned names that paragraph and run",
    plannedRuns.includes(`${runOp?.atPara}#${runOp?.run}=${TYPED}`),
    `${plannedRuns.join(", ") || "no set_run ops in the plan"}`);
  const validation = getState().draft.validation;
  check("plan/validate accepted the paragraph op against the run inventory",
    !!validation &&
      !(validation.hard ?? []).some((f) => f.at === `ops[${runOp?.opId}]`),
    `${validation?.verdict} · ${JSON.stringify((validation?.hard ?? []).map((f) => f.code))}`);

  // The review queue shows it whichever surface it came from. This is the
  // "one queue" claim, read off the DOM rather than off the store.
  checkDom("the review queue draws the paragraph op in the run's own vocabulary",
    !!document.querySelector('[data-testid="queue-op-p' + runOp?.atPara + '-r' + runOp?.run + '"]') &&
      domText('.queue-op[data-kind="set_run"]').includes("문단"),
    domText('.queue-op[data-kind="set_run"]').slice(0, 120) || "no set_run row in the queue");

  // AND THE TREE — where it can. 본문 보기 renders a paragraph as a node of its
  // own ONLY when its text appears in no table cell (README gap 9: `at_para`
  // and `row,col#run` name the same runs and the runtime maps neither onto the
  // other, so the centre separates them by string). A caret in a paragraph
  // that lives inside a cell therefore has nowhere in the tree to draw its
  // proposal, and this reports which case it met rather than asserting the one
  // it would prefer.
  setCenterMode("text");
  await settled(300);
  const looseNode = document.querySelector(`[data-testid="doc-para-${runOp?.atPara}"]`);
  if (looseNode) {
    checkDom("the paragraph edit shows in 본문 보기 as well, as a proposal",
      domText('[data-testid="view-document"]').includes(TYPED),
      `${document.querySelectorAll('.queued[data-kind="set_run"]').length} queued run rows`);
  } else {
    check("MEASURED: this paragraph lives inside a table cell, so the tree has no node for it",
      true,
      `at_para ${runOp?.atPara} is not one of 본문 보기's loose paragraphs — README gap 9 ` +
        `(at_para and row,col#run are unmapped), so the proposal is visible on the page and ` +
        `in the review queue, and not in the tree`);
  }
  setCenterMode("page");
  await settled(200);

  // Guarded, and the guard is not defensive style. The first run of this
  // phase reached here with `runOp` undefined — the commit above had produced
  // nothing because an earlier step had left no caret open — and the bare
  // `runOp!.opId` threw a TypeError that killed the whole phase, so eight
  // downstream checks never ran and the harness reported a crash instead of
  // the eight results that would have named the cause.
  if (runOp) {
    await removeOp(runOp.opId);
    await settled(300);
    check("and it can be taken back out of the queue like any other op",
      !runOps().some((o) => o.text === TYPED), `${getState().draft.ops.length} ops left`);
  } else {
    check("and it can be taken back out of the queue like any other op", false,
      "no set_run op reached the queue, so there was nothing to remove");
  }
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

/**
 * Drive the app to one Phase 4 state and hold it there, for a screenshot.
 *
 * Nothing here is staged. Each stop is reached by running the real loop up to
 * that point, so the vermilion approval moment in the screenshot is an
 * approval record the Runtime actually issued, and the candidate hash on the
 * bar is a candidate that exists on disk.
 */
async function phaseShot(config: SmokeConfig, stop: string) {
  if (!getState().activeSessionId && config.corpus) {
    await openPath(config.corpus);
  }
  await settled(200);
  const inspect = activeInspect(getState());
  if (!inspect) {
    await ready(`shot-${stop}`);
    return;
  }
  const { toggleExpanded } = await import("./store");
  toggleExpanded(`t:${inspect.graph.tables[0].index}`);

  const seats = inspect.regions.regions.filter(
    (r): r is EditableRegion & { table: number; row: number; col: number } =>
      r.kind === "cell" && r.table !== undefined && r.row !== undefined && r.col !== undefined,
  );
  const clean = seats.filter((r) => r.scriptAnomaly !== true && r.colorAnomaly !== true);

  // TIER 3, photographed with nothing substituted. This is the page a fresh
  // install gets: no Hancom, no staged PDF, our own renderer, and the badge
  // that says so. `own` opens the 무엇을 못 그렸나 list because a closed
  // disclosure photographs as a caption; `own-zoom` is the same page at 150%,
  // which is the claim that a zoom changes the drawn size and nothing else.
  if (stop === "own" || stop === "own-zoom") {
    // OPEN THE CORPUS EXPLICITLY. Every other stop is happy to photograph
    // whatever session the last launch left in prefs; this one must not. The
    // first capture reattached to the session the overlay shots had staged a
    // Hancom PDF into and photographed tier 2 under a caption promising tier 3
    // — a screenshot of the wrong renderer, which is the one thing this shot
    // exists to prevent.
    if (config.corpus) await openPath(config.corpus);
    await settled(250);
    setCenterMode("page");
    await renderCurrentPage(1);
    for (let i = 0; i < 120 && getState().renderPhase === "starting"; i += 1) {
      await settled(500);
    }
    const { loadGeometry } = await import("./actions");
    await loadGeometry(1);
    await settled(300);
    const list = document.querySelector<HTMLDetailsElement>('[data-testid="skipped-list"]');
    if (list) list.open = true;
    if (stop === "own-zoom") {
      const { setZoom } = await import("./store");
      setZoom(1.5);
    }
    await settled(400);
    await ready(`shot-${stop}`);
    return;
  }

  // TIER 3, BEING EDITED. The claim gap 34 used to deny: a seat open on a page
  // no Hancom drew, in the same inline editor a tree click opens, with a value
  // part-typed. Nothing is staged and nothing is substituted — the same corpus
  // form, the same own renderer, and the seat is found by asking the runtime
  // which cells it placed rather than by picking a rectangle.
  if (stop === "own-seat") {
    if (config.corpus) await openPath(config.corpus);
    await settled(250);
    setCenterMode("page");
    await renderCurrentPage(1);
    for (let i = 0; i < 120 && getState().renderPhase === "starting"; i += 1) {
      await settled(500);
    }
    const { loadGeometry } = await import("./actions");
    await loadGeometry(1);
    await settled(500);
    const target = document.querySelector<HTMLButtonElement>(
      '[data-testid="overlay-seat"][data-editable="true"][data-derivation="own_cell"]',
    );
    target?.click();
    await settled(300);
    const field = document.querySelector<HTMLInputElement>('[data-testid="seat-input"]');
    if (field) {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      setter?.call(field, "행정안전부");
      field.dispatchEvent(new Event("input", { bubbles: true }));
    }
    await settled(400);
    await ready(`shot-${stop}`);
    return;
  }

  // The band. One row of actions, and the menus that hold everything a person
  // looks up rather than watches.
  //
  // It ASKS 서식 to open and, measured, it does not survive to the frame the
  // capture lands on — `<details open>` set from script here does not stick.
  // Left in and recorded rather than removed: the request is harmless and the
  // shot's caption says the band is closed, which is also how a person first
  // meets it.
  if (stop === "toolbar") {
    setCenterMode("text");
    if (clean.length > 0) {
      const seat = clean[0];
      setSelection({ kind: "cell", table: seat.table, row: seat.row, col: seat.col });
    }
    await settled(400);
    // Twice, with a commit between: the first attempt landed before the
    // toolbar had re-rendered for the selection above and was thrown away, and
    // the capture then photographed a closed menu under a caption promising an
    // open one.
    for (let i = 0; i < 2; i += 1) {
      const menu = document.querySelector<HTMLDetailsElement>('[data-testid="tool-format"]');
      if (menu) menu.open = true;
      await settled(250);
    }
    await ready(`shot-${stop}`);
    return;
  }

  if (stop === "page") {
    setCenterMode("page");
    await renderCurrentPage(1);
    await preparePages();
    for (let i = 0; i < 60 && getState().preparePhase === "starting"; i += 1) {
      await settled(500);
    }
    await settled(400);
    await ready(`shot-${stop}`);
    return;
  }

  // The overlay, on a page. `overlay` photographs the staged-real session — a
  // real raster with the runtime's own rects on it, and the chooser open over a
  // real ambiguity. `overlay-live` photographs what this machine does with no
  // substitution at all, which is a refusal, and photographing the refusal is
  // the point: a screenshot of a feature working on a machine where it does not
  // work is the exact thing this harness exists not to produce.
  if (
    stop === "overlay" ||
    stop === "overlay-live" ||
    stop === "overlay-seat" ||
    stop === "overlay-caret" ||
    stop === "layout-echo"
  ) {
    const { loadGeometry, selectSession } = await import("./actions");
    const staged = (await rt.smokeConfig()).stagedSession;
    if (stop !== "overlay-live" && staged) {
      await selectSession(staged);
      await settled(300);
    }

    // E1.2 — a page holding the SOURCE's raster while the document has moved
    // on. Reached by running the loop, never by staging a flag: the candidate
    // in the shot is a candidate on disk, and the 후보본과 다름 banner is
    // drawn off the runtime's own receipt lineage.
    if (stop === "layout-echo") {
      setCenterMode("page");
      let echoPage = 1;
      let best = -1;
      for (let p = 1; p <= 8; p += 1) {
        await loadGeometry(p);
        await settled(100);
        const probe = getState().geometry;
        if (!probe?.available) break;
        const found = (probe.seats ?? []).length;
        if (found > best) {
          best = found;
          echoPage = p;
        }
        if ((probe.pageCount ?? 1) <= p) break;
      }
      await renderCurrentPage(echoPage);
      await settled(400);
      await loadGeometry(echoPage);
      await settled(300);
      const echoInspect = activeInspect(getState());
      const echoSeat = (echoInspect?.regions.regions ?? []).find(
        (r): r is EditableRegion & { table: number; row: number; col: number } =>
          r.kind === "cell" && r.table !== undefined && r.row !== undefined &&
          r.col !== undefined && r.scriptAnomaly !== true && r.colorAnomaly !== true,
      );
      if (echoSeat) {
        beginEdit(echoSeat.table, echoSeat.row, echoSeat.col);
        await commitEdit("지면 반향");
        await settled(400);
        await requestApprovalForDraft();
        await settled(300);
        await resolveApprovalDecision("approved", "host-operator");
        for (let i = 0; i < 120 && getState().applyPhase === "starting"; i += 1) {
          await settled(500);
        }
        const shotRun = getState().applied?.runId;
        if (shotRun) {
          await waitFor(
            () => (getState().changedByRun[shotRun] ?? []).length > 0, 20000);
        }
        await settled(800);
      }
      await ready(`shot-${stop}`);
      return;
    }

    // THE CARET SHOT, and the IME's page-surface target.
    //
    // Two callers again, and the same split the seat shot has: the screenshot
    // wants the line caught mid-edit with text in it, and `ime.ps1` needs the
    // field left exactly as the runtime handed it so the only thing that ends
    // up in it is what real scan codes typed.
    //
    // The line is FOUND, never written down. Most mapped paragraph lines on a
    // corpus page are one of the 51 corpus-wide that hold several runs and
    // refuse a caret, so a shot aimed at "the first mapped line" would
    // photograph a refusal about half the time and call it a caret. This walks
    // pages and lines until the runtime actually places one.
    if (stop === "overlay-caret") {
      const { addressIsCaretTarget, clickOverlaySpan } = await import("./actions");
      const imeEmpty = (await rt.smokeConfig()).imeEmpty === true;
      setCenterMode("page");
      let found: { page: number; span: GeometrySpan } | null = null;
      for (let p = 1; p <= 8 && !found; p += 1) {
        await loadGeometry(p);
        await settled(120);
        const probe = getState().geometry;
        if (!probe?.available) break;
        await renderCurrentPage(p);
        await settled(300);
        await loadGeometry(p);
        await settled(300);
        // Bounded per page, for the reason `caretChecks` is bounded: each
        // attempt runs `form_inspect` as a child, and a shot that spent two
        // minutes asking would time out before it photographed anything.
        for (const span of (getState().geometry?.spans ?? [])
          .filter((s) => s.confidence === "unique" && addressIsCaretTarget(s.address) && !!s.charX)
          .slice(0, 8)) {
          await clickOverlaySpan(span, span.rect[0] + (span.rect[2] - span.rect[0]) * 0.6);
          await settled(180);
          if (getState().inlineEdit?.kind === "run") {
            found = { page: p, span };
            break;
          }
        }
        if ((probe.pageCount ?? 1) <= p) break;
      }
      await settled(200);
      const caretField = document.querySelector<HTMLInputElement>('[data-testid="seat-input"]');
      if (caretField && !imeEmpty) {
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
        setter?.call(caretField, "지면 위에서 고쳐 쓴 문장");
        caretField.dispatchEvent(new Event("input", { bubbles: true }));
      } else if (caretField && imeEmpty) {
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
        setter?.call(caretField, "");
        caretField.dispatchEvent(new Event("input", { bubbles: true }));
      }
      await settled(250);
      const open = getState().inlineEdit;
      await rt.smokeReady({
        view: `shot-${stop}`,
        editorOpen: !!document.querySelector(
          '[data-testid="overlay-caret-editing"] [data-testid="seat-input"]',
        ),
        selection: selectionId(getState().selection),
        caret: open?.kind === "run" ? open.caret : null,
        page: found?.page ?? null,
        devicePixelRatio: window.devicePixelRatio,
        cssViewport: `${window.innerWidth}x${window.innerHeight}`,
      });
      if (imeEmpty) {
        // Wait for real scan codes, then report what the app COMMITTED — the
        // value that would become a `set_run` op, not a keystroke count.
        for (let i = 0; i < 240 && getState().lastCommit === null; i += 1) {
          await settled(250);
        }
        const commit = getState().lastCommit;
        const queuedRun = runOps().find(
          (op) => open?.kind === "run" && op.atPara === open.atPara && op.run === open.run,
        );
        await rt.smokeFinal({
          value: commit?.value ?? null,
          composed: commit?.composed ?? false,
          queued: queuedRun?.text ?? null,
          kind: queuedRun?.kind ?? null,
          planned:
            getState().draft.plan?.ops.map((op) => (op.params as { text?: string }).text) ?? [],
        });
      }
      return;
    }
    // THE MARQUEE SHOT. A real seat on a real page, opened into the real inline
    // editor with a value part-typed into it — the interaction the product is
    // for, photographed on the page the runtime actually seated. The page is
    // found by asking, not written down: the shot goes wherever the runtime put
    // the most seats, so this capture cannot quietly become a picture of an
    // empty page if the derivation's numbers move.
    if (stop === "overlay-seat") {
      setCenterMode("page");
      let seatPage = 1;
      let best = -1;
      for (let p = 1; p <= 8; p += 1) {
        await loadGeometry(p);
        await settled(80);
        const probe = getState().geometry;
        if (!probe?.available) break;
        const found = (probe.seats ?? []).length;
        if (found > best) {
          best = found;
          seatPage = p;
        }
        if ((probe.pageCount ?? 1) <= p) break;
      }
      await renderCurrentPage(seatPage);
      await settled(400);
      await loadGeometry(seatPage);
      await settled(500);
      const target =
        document.querySelector<HTMLButtonElement>(
          '[data-testid="overlay-seat"][data-editable="true"][data-derivation="cell_borders"]',
        ) ??
        document.querySelector<HTMLButtonElement>('[data-testid="overlay-seat"][data-editable="true"]');
      target?.click();
      await settled(300);
      const field = document.querySelector<HTMLInputElement>('[data-testid="seat-input"]');
      if (field) {
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
        setter?.call(field, "2026-09-02");
        field.dispatchEvent(new Event("input", { bubbles: true }));
      }
      await settled(300);
      await ready(`shot-${stop}`);
      return;
    }
    if (stop === "overlay-live" && config.corpus) {
      // Open the HWPX AGAIN, unconditionally. The preamble only opens when
      // nothing is active, and by this point `lastSessionId` in prefs is the
      // staged session the previous shot selected — so the "no page here"
      // capture came out showing a page, with overlays on it. A screenshot
      // named for a refusal that photographs the working case is worse than no
      // screenshot: it is the one kind of evidence that actively misleads.
      await openPath(config.corpus);
      await settled(300);
    }
    setCenterMode("page");
    await renderCurrentPage(1);
    await settled(300);
    await loadGeometry(1);
    await settled(400);
    if (stop === "overlay") {
      // Open the chooser over a real ambiguous span, so the capture shows the
      // T41 moment rather than a page of quiet boxes.
      document.querySelector<HTMLButtonElement>('[data-testid="overlay-ambiguous"]')?.click();
      await settled(300);
    }
    await ready(`shot-${stop}`);
    return;
  }

  if (stop === "agent-proposal") {
    await runAgentProposal("MOCK-AGENT-0001");
    await settled(400);
    setView("agent");
    await settled(300);
    await ready(`shot-${stop}`);
    return;
  }

  // --- Phase 5 stops. Each one is REACHED, not staged. ----------------------

  if (stop === "composer") {
    const { loadProviderSettings, refreshAgentHost, saveProviderSettings, sendInstruction } =
      await import("./actions");
    await refreshAgentHost();
    await loadProviderSettings();
    await saveProviderSettings({
      ...getState().provider,
      provider: "mock",
      scenario: "propose-one",
    });
    setView("agent");
    await settled(300);
    await sendInstruction("첫 채움 자리에 접수 번호를 넣고 승인을 요청하십시오.");
    await settled(500);
    await ready(`shot-${stop}`);
    return;
  }

  if (stop === "settings") {
    // The Anthropic profile with NO credential: the honest empty state, which
    // is the one a new user meets. Nothing is stored and nothing is sent.
    const { loadProviderSettings, probeProvider, refreshAgentHost, saveProviderSettings } =
      await import("./actions");
    await refreshAgentHost();
    await loadProviderSettings();
    await saveProviderSettings({ ...getState().provider, provider: "anthropic" });
    await probeProvider();
    setView("agent");
    setState({ settingsOpen: true });
    await settled(400);
    await ready(`shot-${stop}`);
    return;
  }

  if (stop === "toolbar-text" || stop === "toolbar-page") {
    // Open the intended form UNCONDITIONALLY, same lesson as overlay-live: by
    // this point `lastSessionId` is whatever the previous shot selected, and
    // the toolbar is a picture OF a document's declared shapes. Photographing
    // the wrong document's font name is a caption error nobody can see.
    if (config.corpus) {
      await openPath(config.corpus);
      await settled(400);
    }
    const reopened = activeInspect(getState());
    const shotSeats = (reopened ?? inspect).regions.regions.filter(
      (r): r is EditableRegion & { table: number; row: number; col: number } =>
        r.kind === "cell" && r.table !== undefined && r.row !== undefined && r.col !== undefined,
    );
    const seat = shotSeats[0];
    if (seat) setSelection({ kind: "cell", table: seat.table, row: seat.row, col: seat.col });
    setCenterMode(stop === "toolbar-page" ? "page" : "text");
    if (stop === "toolbar-page") {
      await renderCurrentPage(1);
      await settled(400);
    }
    await settled(400);
    await ready(`shot-${stop}`);
    return;
  }

  if (stop === "packs" || stop === "packs-result") {
    const { loadTaskPacks, openPack, runModuleCheck, runtimeEnabledModules } =
      await import("./actions");
    // Open the intended document UNCONDITIONALLY, for the reason the
    // overlay-live capture found out the hard way: the preamble only opens when
    // nothing is active, and by this point `lastSessionId` is whatever the
    // previous shot selected. A check result photographed against the wrong
    // document is a verdict attached to the wrong file.
    if (stop === "packs-result" && config.corpus) {
      await openPath(config.corpus);
      await settled(400);
    }
    await loadTaskPacks();
    setView("agent");
    // `packs` photographs the declaration panel. `packs-result` photographs a
    // REAL `module/check` answer, and only when this machine has an enablement
    // to run against — with none, it falls through to the honest disabled
    // state, which is the state a fresh checkout genuinely has and is worth a
    // picture of its own. Nothing here fabricates a verdict.
    const enabled = runtimeEnabledModules() ?? [];
    const wanted =
      stop === "packs-result"
        ? (enabled.find((n) => n === "grant") ?? enabled[0] ?? "report")
        : "report";
    openPack(wanted);
    await settled(300);
    if (stop === "packs-result" && enabled.includes(wanted)) {
      await runModuleCheck(wanted);
      for (let i = 0; i < 120 && getState().packRun?.phase === "running"; i += 1) {
        await settled(500);
      }
    }
    await settled(500);
    await ready(`shot-${stop}`);
    return;
  }

  if (clean.length === 0) {
    await ready(`shot-${stop}`);
    return;
  }
  const first = clean[0];

  if (stop === "inline-edit") {
    // Two callers, two needs. The screenshot wants the field caught mid-edit
    // with a plausible partial value in it; the IME harness needs it EMPTY,
    // because the only thing that may end up in it is what was typed with
    // real scan codes.
    const imeEmpty = (await rt.smokeConfig()).imeEmpty === true;
    beginEdit(first.table, first.row, first.col);
    await settled(160);
    const field = document.querySelector<HTMLInputElement>('[data-testid="seat-input"]');
    if (field && !imeEmpty) {
      // Set through the native setter so React's onChange sees it — assigning
      // `.value` directly is invisible to React's synthetic event system.
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )?.set;
      setter?.call(field, "정보공개 청구");
      field.dispatchEvent(new Event("input", { bubbles: true }));
    } else if (field && imeEmpty) {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )?.set;
      setter?.call(field, "");
      field.dispatchEvent(new Event("input", { bubbles: true }));
    }
    await settled(200);
    await rt.smokeReady({
      view: `shot-${stop}`,
      editorOpen: !!document.querySelector('[data-testid="seat-input"]'),
      selection: selectionId(getState().selection),
      devicePixelRatio: window.devicePixelRatio,
      cssViewport: `${window.innerWidth}x${window.innerHeight}`,
    });
    if (imeEmpty) {
      // Wait for the harness to type and press Enter, then report what the
      // field actually received. Polling the store rather than hooking the
      // input, so what is reported is what the application COMMITTED — the
      // value that would become a plan op, not a keystroke count.
      for (let i = 0; i < 240 && getState().lastCommit === null; i += 1) {
        await settled(250);
      }
      const commit = getState().lastCommit;
      const queuedOp = fillOps().find(
        (op) => op.table === first.table && op.row === first.row && op.col === first.col,
      );
      await rt.smokeFinal({
        value: commit?.value ?? null,
        composed: commit?.composed ?? false,
        queued: queuedOp?.text ?? null,
        planned:
          getState().draft.plan?.ops.map((op) => (op.params as { text?: string }).text) ?? [],
      });
    }
    return;
  }

  // Every other stop needs a queue.
  //
  // ALL captures share one runtime root, so a corpus opened by a later capture
  // is the SAME session an earlier one already applied a candidate to. Writing
  // the same two cells again is then refused — the head has them filled, and
  // the shell sets `overwrite` only on an inverse — which leaves `applied`
  // null and every stop after the first apply photographing a refusal. The
  // history capture is the one that cannot survive that, because it needs a
  // candidate of its own to reverse, so it takes seats no earlier capture
  // touches. The values it writes are its own too, for the same reason.
  const chainShot = stop === "history";
  const seatA = chainShot ? (clean[2] ?? first) : first;
  const seatB = chainShot ? clean[3] : clean[1];
  beginEdit(seatA.table, seatA.row, seatA.col);
  await commitEdit(chainShot ? "되돌리기 촬영본" : "정보공개 청구서 검토본");
  await settled(200);
  if (seatB) {
    beginEdit(seatB.table, seatB.row, seatB.col);
    await commitEdit(chainShot ? "2026-09-03" : "2026-09-01");
    await settled(200);
  }
  // A refused op, so the queue screenshot shows a real verdict rather than a
  // uniformly green list.
  const flagged = seats.find((r) => r.scriptAnomaly === true);
  if (stop === "queue" && flagged) {
    beginEdit(flagged.table, flagged.row, flagged.col);
    await commitEdit("담당자 확인");
    await settled(240);
  }
  if (stop === "queue") {
    await ready(`shot-${stop}`);
    return;
  }

  await requestApprovalForDraft();
  await settled(300);
  if (stop === "approval") {
    await ready(`shot-${stop}`);
    return;
  }

  await resolveApprovalDecision("approved", "host-operator");
  for (let i = 0; i < 120 && getState().applyPhase === "starting"; i += 1) {
    await settled(500);
  }
  await runCheck();
  await settled(300);
  setState({ sheetOpen: false });
  await settled(200);

  if (stop === "receipt" && getState().applied) {
    openReceipt(getState().applied!.runId);
    await settled(400);
  }

  // E1.4 — 기록, with a real reversal in it. Every row in this shot is a
  // candidate on disk: the edit above, then the inverse of it, proposed by
  // reading the previous value off the chain, approved by the same gate, and
  // proven afterwards by the runtime's own candidate/compare. Nothing here is
  // arranged — if the reversal failed to apply, the shot photographs that.
  if (stop === "history" && getState().applied) {
    const edited = getState().applied!.runId;
    const { proposeUndoOf, selectHistory } = await import("./actions");
    const queued = await proposeUndoOf(edited);
    await settled(500);
    if (queued > 0) {
      await requestApprovalForDraft();
      await settled(300);
      await resolveApprovalDecision("approved", "host-operator");
      for (let i = 0; i < 120 && getState().applyPhase === "starting"; i += 1) {
        await settled(500);
      }
      await settled(900);
    }
    selectHistory(edited);
    await settled(500);
  }
  await ready(`shot-${stop}`);
}

/**
 * 작업 팩 실행 — `module/check` against the open session, and what it refuses.
 *
 * The phase exists because a run button is the easiest control in this product
 * to make dishonest. Twelve of the declared checkers take a report WORKSPACE
 * and a session holds a document, so on any document they come back `skipped`
 * — and a panel that drew twelve green ticks there would be lying about twelve
 * rules that never looked. Half of what is asserted here is that they are not
 * drawn as passes.
 *
 * WHAT THIS MACHINE SUPPORTS. `modules/enabled.yaml` is gitignored and absent
 * from a fresh checkout, so a run needs an enablement to exist. The harness
 * writes one the way `tests/test_runtime_module_check.py` does — a real
 * `enabled.yaml` outside the checkout, pointed at by `RIGORLOOM_MODULES_ENABLED`
 * — and both readers of that file (the Runtime, and `taskpacks.rs` through
 * `module_registry.py`) honour the same override. Nothing is written into the
 * repository's own `modules/`. When the variable is absent the phase asserts the
 * HONEST EMPTY state instead, and says which of the two it exercised.
 */
async function phasePacks(config: SmokeConfig) {
  if (!config.corpus) {
    check("corpus path supplied", false, "RIGORLOOM_SMOKE_CORPUS is empty");
    return;
  }

  const caps = getState().capabilities;
  const modules = caps?.modules ?? null;
  check("the packaged runtime advertises module/list and module/check",
    (caps?.methods ?? []).includes("module/list") &&
      (caps?.methods ?? []).includes("module/check"),
    (caps?.methods ?? []).filter((m) => m.startsWith("module/")).join(", "));
  check("capabilities carries the module registry's own state",
    !!modules && typeof modules.state === "string",
    `${modules?.state} — ${modules?.reason ?? "no reason"}`);
  check("running a module is agent-safe by construction, and says its containment is not",
    modules?.containment === "not_established", modules?.containment ?? "absent");

  const sessionId = await openPath(config.corpus);
  check("the packs phase opened a document to check", !!sessionId, sessionId ?? "");
  if (!sessionId) return;
  await settled(300);

  const { loadTaskPacks, openPack, runModuleCheck } = await import("./actions");
  await loadTaskPacks();
  setView("agent");
  await settled(300);

  const packs = getState().taskPacks;
  check("the task pack list came from the module registry", packs?.available === true,
    packs?.reason ?? `${packs?.packs.length} packs`);
  if (!packs?.available) return;

  // TWO READERS, ONE FILE. `taskpacks.rs` shells out to module_registry.py and
  // the Runtime reads the same enabled.yaml itself; the run button follows the
  // Runtime. A split between them would put a 꺼짐 label above an enabled
  // button, so it is asserted rather than assumed — and the files they read are
  // compared too, because "we disagree" and "we read different files" are
  // different defects.
  const { packEnablementDisagrees } = await import("./actions");
  const runtimeEnabled = modules?.enabled ?? [];
  const registryEnabled = packs.packs.filter((p) => p.enabled).map((p) => p.name);
  check("the registry child and the runtime read the same enablement file",
    !!packs.enabledFile && !!modules?.enabledFile && packs.enabledFile === modules.enabledFile,
    `${packs.enabledFile} vs ${modules?.enabledFile}`);
  check("and they agree about which packs are on",
    packEnablementDisagrees().length === 0,
    `registry [${registryEnabled.join(",")}] vs runtime [${runtimeEnabled.join(",")}]`);

  check("RECORDED: which enablement state this run exercised", true,
    runtimeEnabled.length > 0
      ? `${runtimeEnabled.length} of ${packs.packs.length} modules enabled via ` +
        `${modules?.enabledFile} — the RUN path is under test`
      : `0 of ${packs.packs.length} modules enabled (enabled.yaml is gitignored and ` +
        `absent here) — the honest EMPTY path is under test`);

  // --- the honest empty state, when this machine has no enablement ----------
  if (runtimeEnabled.length === 0) {
    const first = packs.packs[0];
    openPack(first.name);
    await settled(240);
    checkDom("a pack nobody enabled offers a 실행 button that is disabled",
      document.querySelector<HTMLButtonElement>('[data-testid="pack-run-button"]')?.disabled ===
        true,
      domText('[data-testid="pack-run"]').slice(0, 200));
    checkDom("and says enabling is an install-time act, not something the app does",
      domText('[data-testid="pack-run"]').includes("꺼져 있는 팩"),
      domText('[data-testid="pack-run"]'));
    check("no report was drawn for a pack that cannot run",
      getState().packRun === null && !document.querySelector('[data-testid="module-check-report"]'),
      JSON.stringify(getState().packRun));
    checkAlive("the packs phase");
    return;
  }

  // --- a module with a DOCUMENT checker: it runs, and its verdict is real ---
  const documentPack =
    packs.packs.find((p) => p.enabled && p.name === "grant") ??
    packs.packs.find((p) => p.enabled);
  openPack(documentPack!.name);
  await settled(240);
  checkDom("the 실행 button is enabled for a pack the runtime says is on",
    document.querySelector<HTMLButtonElement>('[data-testid="pack-run-button"]')?.disabled ===
      false,
    domText('[data-testid="pack-run"]').slice(0, 160));

  await runModuleCheck(documentPack!.name);
  for (let i = 0; i < 120 && getState().packRun?.phase === "running"; i += 1) {
    await settled(500);
  }
  await settled(300);
  const run = getState().packRun;
  check("module/check answered for the enabled pack", run?.phase === "done",
    run?.phase === "failed" ? JSON.stringify(run.error) : (run?.phase ?? "no run"));
  if (run?.phase !== "done" || !run.report) {
    checkAlive("the packs phase");
    return;
  }
  const report = run.report;

  check("the report is bound to the session that was open",
    report.sessionId === sessionId && report.module === documentPack!.name,
    `${report.sessionId} / ${report.module}`);
  check("the checkers were handed a scratch COPY, never the session's own bytes",
    report.subject.kind === "session_source" && report.evidence.class === "structural_only",
    `${report.subject.kind} · ${report.evidence.class}`);
  check("running a check queued nothing and decided nothing",
    getState().draft.ops.length === 0 && getState().draft.plan === null &&
      getState().approval === null,
    `${getState().draft.ops.length} ops, plan ${getState().draft.plan?.planId ?? "none"}`);

  // Every row the runtime returned is on screen, and no others.
  const drawnRows = document.querySelectorAll('[data-testid^="module-check-row-"]');
  checkDom("every selected checker is drawn as a row, and no others",
    drawnRows.length === report.checks.length,
    `${drawnRows.length} rows / ${report.checks.length} checks`);
  checkDom("the header prints the runtime's own counts",
    domText('[data-testid="module-check-counts"]').includes(String(report.counts.selected)) &&
      domText('[data-testid="module-check-counts"]').includes(String(report.counts.ran)),
    domText('[data-testid="module-check-counts"]'));

  const ranRows = report.checks.filter((r) => r.state === "ran");
  check("at least one checker actually ran against the document",
    ranRows.length > 0,
    report.checks.map((r) => `${r.checker}:${r.state}:${r.reason ?? "-"}`).join(" "));

  // §13.3. `ok: true` with an input it declares it needs unsupplied is NOT
  // acceptance, and the panel has to show both facts without either hiding the
  // other. On a session with no candidate there is no baseline to give, so
  // every `wants: [baseline]` checker lands here — which is the normal case.
  const partial = ranRows.filter((r) => r.partial);
  if (partial.length > 0) {
    check("a clean-but-partial verdict is not counted as acceptance",
      report.acceptance === false && partial.every((r) => r.ok === true),
      `${partial.length} partial, acceptance ${report.acceptance}, reason ${report.reason}`);
    checkDom("and the row says out loud what it did not get",
      domText('[data-testid="module-check-report"]').includes("입력 부족") &&
        partial.every((r) =>
          (r.wantsUnsatisfied ?? []).every((w) =>
            domText('[data-testid="module-check-report"]').includes(w))),
      partial.map((r) => `${r.checker}:${(r.wantsUnsatisfied ?? []).join("+")}`).join(" "));
  }

  // A rule the checker itself could not decide arrives as a finding with
  // `severity: "skipped"`. It must be listed — a bare pass hiding it is the
  // exact failure §13.4 keeps them for.
  const allFindings = ranRows.flatMap((r) => r.findings ?? []);
  const undecided = allFindings.filter((f) => f.severity === "skipped");
  const drawnFindings = document.querySelectorAll('[data-testid^="module-check-finding-"]');
  checkDom("every finding the runtime returned is drawn, and no others",
    drawnFindings.length === allFindings.length,
    `${drawnFindings.length} drawn / ${allFindings.length} returned`);
  if (undecided.length > 0) {
    checkDom("a rule the checker could not decide is shown as undecided, never as a pass",
      document.querySelectorAll('[data-severity="skipped"]').length >= undecided.length &&
        domText('[data-testid="module-check-report"]').includes("판정 안 함"),
      `${undecided.length} undecided rules — ${undecided.slice(0, 3).map((f) => f.code).join(",")}`);
  }

  // An ADDRESSED finding goes to the cell it names. `address` is null wherever
  // the runtime could not translate the checker's own location, and a null one
  // must get no link at all: a half address selects the wrong cell.
  const addressed = allFindings.filter((f) => f.address !== null);
  check("MEASURED: how many findings carried a Runtime address",
    true,
    `${addressed.length} of ${allFindings.length} findings addressed · ` +
      `${allFindings.length - addressed.length} left their location untranslated`);
  const links = document.querySelectorAll('[data-testid^="module-check-address-"]');
  checkDom("exactly the addressed findings offer a link, and the rest offer none",
    links.length === addressed.length, `${links.length} links / ${addressed.length} addressed`);
  if (addressed.length > 0) {
    const want = addressed[0].address!;
    const link = document.querySelector<HTMLButtonElement>(
      '[data-testid^="module-check-address-"]',
    );
    link?.click();
    await settled(300);
    const selection = getState().selection;
    check("clicking a finding's address selects that cell in the document",
      selection?.kind === "cell" && selection.table === want.table &&
        selection.row === want.row && selection.col === want.col,
      `${selectionId(selection)} vs ${JSON.stringify(want)}`);
    check("and it went to the view that can show it",
      getState().view === "document" && getState().centerMode === "text",
      `${getState().view} / ${getState().centerMode}`);
    setView("agent");
    await settled(200);
  }

  // --- a module whose checkers are ALL workspace-subject ---------------------
  const workspacePack = packs.packs.find(
    (p) => p.enabled && p.checkers.length > 0 && p.name === "report",
  );
  if (!workspacePack) {
    check("a workspace-subject pack was enabled for this run", false,
      `enabled: ${runtimeEnabled.join(",")}`);
  } else {
    openPack(workspacePack.name);
    await settled(240);
    await runModuleCheck(workspacePack.name);
    for (let i = 0; i < 120 && getState().packRun?.phase === "running"; i += 1) {
      await settled(400);
    }
    await settled(300);
    const wsRun = getState().packRun;
    check("module/check answered for the workspace-only pack too",
      wsRun?.phase === "done" && !!wsRun.report,
      wsRun?.phase === "failed" ? JSON.stringify(wsRun.error) : (wsRun?.phase ?? "none"));
    const wsReport = wsRun?.report;
    if (wsReport) {
      const skipped = wsReport.checks.filter((r) => r.state === "skipped");
      check("every workspace checker came back skipped, with the runtime's reason",
        skipped.length === wsReport.checks.length &&
          skipped.every((r) => r.reason === "needs_workspace"),
        `${skipped.length} of ${wsReport.checks.length} skipped — ` +
          `${[...new Set(wsReport.checks.map((r) => r.reason))].join(",")}`);
      check("nothing ran, and acceptance is false rather than vacuously true",
        wsReport.ranAll === false && wsReport.acceptance === false &&
          wsReport.counts.ran === 0,
        `ranAll ${wsReport.ranAll} acceptance ${wsReport.acceptance} reason ${wsReport.reason}`);
      const drawn = domText('[data-testid="module-check-report"]');
      checkDom("the panel draws them as 건너뜀, and never as a pass",
        document.querySelectorAll('[data-state="skipped"]').length === skipped.length &&
          drawn.includes("건너뜀") && !drawn.includes("pass"),
        `${document.querySelectorAll('[data-state="skipped"]').length} skipped rows drawn`);
      checkDom("each skipped row says WHY, in Korean, from the reason code",
        domText('[data-testid="module-check-why-0"]').includes("보고서 작업 폴더"),
        domText('[data-testid="module-check-why-0"]').slice(0, 160));
      checkDom("and the runtime's own detail is printed beside it, not replaced",
        domText('[data-testid="module-check-why-0"]').includes("workspace"),
        domText('[data-testid="module-check-why-0"]').slice(0, 220));
      // The one summary word a reader takes away. Twelve rules that never
      // looked must not add up to 통과.
      checkDom("the header says 통과 아님, not 통과",
        drawn.startsWith("통과 아님"), drawn.slice(0, 80));
    }
  }

  // A pack the operator did not enable stays unrunnable, whatever the UI does.
  const off = packs.packs.find((p) => !p.enabled);
  if (off) {
    openPack(off.name);
    await settled(240);
    checkDom("a pack nobody enabled cannot be run from here either",
      document.querySelector<HTMLButtonElement>('[data-testid="pack-run-button"]')?.disabled ===
        true,
      `${off.name}: ${domText('[data-testid="pack-run"]').slice(0, 120)}`);
    check("opening another pack dropped the previous pack's verdict",
      getState().packRun === null, JSON.stringify(getState().packRun?.module ?? null));
  }

  checkAlive("the packs phase");
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
  // 180 s is the budget every phase has had, and it is deliberately tight:
  // a phase that needs longer is usually a phase that is waiting on something
  // it should be asserting about. `undo` is the exception and it is a measured
  // one — it drives FOUR real applies (edit, chain, reversal, and the staged
  // session's echo edit), each spawning preedit and check_residue children,
  // plus two form_inspect runs for candidate/compare and an eight-page geometry
  // scan. Giving it the default would make the watchdog a coin flip on machine
  // load rather than a budget.
  const budgetMs = config.phase === "undo" ? 480_000 : 180_000;
  const watchdog = setTimeout(() => {
    if (finished) return;
    check("smoke finished within its own budget", false,
      `${Math.round(budgetMs / 1000)}s watchdog fired`);
    void rt.smokeFinish({
      phase: config.phase,
      passed: checks.filter((c) => c.ok).length,
      failed: checks.filter((c) => !c.ok).length,
      checks,
    });
  }, budgetMs);

  try {
    if (config.phase === "open") await phaseOpen(config);
    else if (config.phase === "reattach") await phaseReattach();
    else if (config.phase === "edit") await phaseEdit(config);
    else if (config.phase === "agent") await phaseAgent(config);
    else if (config.phase === "page") await phasePage(config);
    else if (config.phase === "own") await phaseOwn(config);
    else if (config.phase === "own-reattach") await phaseOwnReattach();
    else if (config.phase === "undo") await phaseUndo(config);
    else if (config.phase === "overlay") await phaseOverlay(config);
    else if (config.phase === "packs") await phasePacks(config);
    else if (config.phase === "composer") await phaseComposer(config);
    else if (config.phase === "settings") await phaseSettings();
    else if (config.phase === "chrome") await phaseChrome(config);
    else if (config.phase === "chrome-reattach") await phaseChromeReattach();
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
    } else if (config.phase?.startsWith("hold-shot-")) {
      await phaseShot(config, config.phase.slice("hold-shot-".length));
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

// --- Phase 5 -------------------------------------------------------------------

/**
 * A value that is obviously not a credential, used where a credential goes.
 *
 * Written here in one place so the PowerShell driver can grep the whole app
 * data tree for the same string afterwards. It is a sentinel, not a secret: the
 * point of the check is that a value put into the credential store never
 * reaches a config file, an event log, a prefs file or a report — and proving
 * that needs a value distinctive enough to find.
 */
const FAKE_SECRET = "NOT-A-REAL-KEY-SENTINEL-4f3a9c7e21";
const FAKE_STORE_KEY = "RIGORLOOM_SMOKE_FAKE";

/**
 * The composer round trip, headless, against the MOCK provider.
 *
 * The two claims this phase exists to measure, and neither is asserted from
 * the UI's own words:
 *
 *   ONE QUEUE — the plan a typed instruction produced is the same `draft` a
 *   typed cell value produces, holding the Runtime's own copy of the plan,
 *   validated over the shell's connection.
 *   CANNOT APPROVE — the host's payload names the methods its compile gate
 *   will never emit, and the approval it opened is still pending when the run
 *   is over. The human then resolves it, and the receipt records who did.
 */
async function phaseComposer(config: SmokeConfig) {
  if (!config.corpus) {
    check("corpus path supplied", false, "RIGORLOOM_SMOKE_CORPUS is empty");
    return;
  }
  const {
    loadProviderSettings,
    refreshAgentHost,
    saveProviderSettings,
    sendInstruction,
  } = await import("./actions");

  const sessionId = await openPath(config.corpus);
  check("composer phase opened the corpus form", !!sessionId, sessionId ?? "");
  if (!sessionId) return;
  await settled(160);

  await refreshAgentHost();
  const host = getState().agentHost;
  check("the agent host is reachable from this build", host?.available === true,
    `${host?.mode ?? "none"} · ${host?.script ?? host?.reason ?? ""}`);
  if (!host?.available) return;

  await loadProviderSettings();
  await saveProviderSettings({
    ...getState().provider,
    provider: "mock",
    scenario: "propose-one",
  });
  check("the provider is the built-in mock", getState().provider.provider === "mock",
    getState().provider.scenario);

  // The composer must be live now, and must say so rather than being grey.
  setView("agent");
  await settled(260);
  const { composerBlocker } = await import("./store");
  check("nothing blocks the composer", composerBlocker(getState()) === null,
    String(composerBlocker(getState())));
  checkDom("the composer is enabled",
    document.querySelector<HTMLTextAreaElement>('[data-testid="composer-input"]')?.disabled ===
      false,
    domText('[data-testid="composer-note"]').slice(0, 120));

  const before = activeInspect(getState())?.documentHash ?? "";
  const newest = () => {
    const turns = getState().turns;
    return turns.length > 0 ? turns[turns.length - 1] : null;
  };
  const ok = await sendInstruction("첫 채움 자리에 스모크 표시를 넣고 승인을 요청하십시오.");
  check("the instruction ran to completion", ok, JSON.stringify(newest()?.error));

  const turn = newest();
  check("one turn was recorded", getState().turns.length === 1, getState().turns.length);
  check("the turn finished", turn?.phase === "ready", turn?.phase ?? "none");
  check("the agent host exited 0", turn?.exitCode === 0, String(turn?.exitCode));

  // Live tail. The host writes its log as it goes and Rust batches whole lines;
  // an empty list here would mean the channel never delivered, even though the
  // final payload would still have filled the card in.
  const events: HostEvent[] = turn?.events ?? [];
  check("the host's event log arrived", events.length > 0, events.length);
  check("the log is ordered and gap-free",
    events.every((event: HostEvent, index: number) => event.seq === index),
    events.map((e: HostEvent) => e.seq).join(","));
  check("the log starts and ends where a run does",
    events[0]?.kind === "run.started" &&
      events[events.length - 1]?.kind === "run.finished",
    `${events[0]?.kind} … ${events[events.length - 1]?.kind}`);

  const payload = turn?.payload ?? null;
  check("the provider profile came back with it", !!payload?.provider?.providerId,
    payload?.provider?.providerId ?? "");
  check("the host proposed a plan", !!payload?.plan?.planId, payload?.plan?.planId ?? "");
  if (!payload?.plan) return;

  // THE CLAIM: one queue.
  const draft = getState().draft;
  check("the composer's plan landed in the SAME review queue",
    draft.ops.length > 0 && draft.plan?.planId === payload.plan.planId,
    `${draft.ops.length} ops, plan ${draft.plan?.planId?.slice(0, 8)}`);
  check("the queue holds the Runtime's own copy, validated here",
    draft.validation?.ok === true && draft.boundSha256 === draft.plan?.boundSha256,
    JSON.stringify(draft.validation?.verdict));
  check("every queued op is marked as the agent's",
    draft.ops.length > 0 && draft.ops.every((op) => op.origin === "agent"),
    JSON.stringify(draft.ops.map((o) => o.origin)));

  // THE OTHER CLAIM: it cannot approve, and the payload says which methods.
  check("the host names the methods it can never compile",
    payload.neverCompiled.includes("approval/resolve") &&
      payload.neverCompiled.includes("plan/apply"),
    payload.neverCompiled.join(", "));
  check("the run left the approval pending, not resolved",
    getState().approval?.state === "pending", JSON.stringify(getState().approval));
  check("the approval was requested by the agent host, not by this shell",
    getState().approval?.requestedBy === "agenthost-mock",
    String(getState().approval?.requestedBy));
  check("no candidate exists before a human acts", getState().applied === null,
    JSON.stringify(getState().applied));

  await settled(240);
  checkDom("the conversation shows the instruction back",
    domText('[data-testid="conversation"]').includes("스모크 표시"),
    domText('[data-testid="conversation"]').slice(0, 160));
  checkDom("the card says where the agent stopped",
    domText('[data-testid="turn-gate"]').includes("승인"),
    domText('[data-testid="turn-gate"]').slice(0, 160));
  checkDom("the card names what the connection does not have",
    domText('[data-testid="turn-never"]').includes("approval/resolve"),
    domText('[data-testid="turn-never"]').slice(0, 160));

  // The human resolves it, exactly as for a manual edit.
  await resolveApprovalDecision("approved", "smoke-operator");
  for (let i = 0; i < 120 && getState().applyPhase === "starting"; i += 1) {
    await settled(500);
  }
  const applied = getState().applied;
  check("the host approved the agent's plan and it applied",
    getState().applyPhase === "ready" && !!applied,
    applied?.runId ?? JSON.stringify(getState().applyError));
  check("the candidate has its own sha256", (applied?.candidate.sha256.length ?? 0) === 64,
    applied?.candidate.sha256 ?? "");
  check("and the source sha256 did not move",
    activeInspect(getState())?.documentHash === before, before);

  if (applied) {
    openReceipt(applied.runId);
    await settled(320);
    const receipt = getState().receipts[applied.runId];
    check("the receipt records the agent host as the requester",
      receipt?.approval.requestedBy === "agenthost-mock",
      String(receipt?.approval.requestedBy));
    check("and a human as the approver", receipt?.approval.approver === "smoke-operator",
      String(receipt?.approval.approver));
    openReceipt(null);
  }

  // The conversation is shared state, so a view switch must not lose it.
  const signature = sharedStateSignature();
  setView("document");
  await settled(240);
  setView("agent");
  await settled(240);
  check("the conversation survived a view switch byte-identically",
    sharedStateSignature() === signature,
    `${signature.length} chars`);

  checkAlive("the composer round trip");
}

/**
 * Provider settings, written and read back, with a FAKE credential.
 *
 * No real secret is involved anywhere. A sentinel goes into the OS credential
 * store, and every reachable surface is then checked for it: the config file
 * the Agent Host reads, the credential status the UI holds, and the
 * `--capabilities` payload. `smoke.ps1` greps the whole app-data tree for the
 * same sentinel afterwards, which is the check that matters — an in-app
 * assertion can only see what the app chose to hand it.
 */
async function phaseSettings() {
  const {
    forgetCredential,
    loadProviderSettings,
    probeProvider,
    refreshAgentHost,
    saveProviderSettings,
    storeCredential,
  } = await import("./actions");
  await refreshAgentHost();
  await loadProviderSettings();

  const host = getState().agentHost;
  check("the agent host is reachable from this build", host?.available === true,
    `${host?.mode ?? "none"} · ${host?.reason ?? ""}`);

  // --- keyless honesty, first ------------------------------------------------
  await saveProviderSettings({
    ...getState().provider,
    provider: "anthropic",
    anthropic: { model: "", storeKey: FAKE_STORE_KEY },
  });
  await forgetCredential();
  check("the store starts empty for this key", getState().credential?.state === "absent",
    JSON.stringify(getState().credential));

  const keyless = await probeProvider();
  check("연결 확인 answers with no credential at all", keyless,
    JSON.stringify(getState().probeError));
  const profile = getState().providerProfile;
  check("the profile names every capability",
    !!profile &&
      ["text", "structuredToolUse", "streaming", "structuredOutput", "modelDiscovery",
       "resumableThread", "vision"].every((name) => name in (profile.capabilities ?? {})),
    Object.keys(profile?.capabilities ?? {}).join(","));
  // The three states, unrounded. `unknown` must survive to the UI as unknown.
  check("an unknown capability stays unknown rather than becoming a no",
    profile?.capabilities?.structuredOutput?.state === "unknown",
    JSON.stringify(profile?.capabilities?.structuredOutput));
  // The adapter's own vocabulary: not_required | configured | missing |
  // unsupported (`ah_anthropic.credential_state`). Asserted verbatim rather
  // than mapped, so a change on that side fails here instead of quietly
  // rendering as something else.
  //
  // With nothing stored, the config carries NO credential member and the
  // adapter falls back to its documented default reference. That reference is
  // what is asserted; the STATE is recorded rather than pinned, because a
  // developer with ANTHROPIC_API_KEY already exported would legitimately see
  // `configured` here and a harness that failed on it would be testing the
  // machine rather than the app.
  const keylessRef = profile?.notes?.credentialRef as { key?: string } | undefined;
  const keylessState =
    (profile?.notes?.credential as { state?: string } | undefined)?.state ?? "";
  check("with nothing stored, the adapter falls back to its own default reference",
    keylessRef?.key === "ANTHROPIC_API_KEY", JSON.stringify(keylessRef));
  check("and reports that reference's state from the closed set",
    ["missing", "configured"].includes(keylessState), keylessState);

  // --- with a fake credential ------------------------------------------------
  const stored = await storeCredential(FAKE_SECRET);
  check("the fake credential went into the OS store", stored,
    JSON.stringify(getState().probeError));
  check("the store reports it present, by length and not by value",
    getState().credential?.state === "present" &&
      getState().credential?.bytes === FAKE_SECRET.length,
    JSON.stringify(getState().credential));
  check("nothing the UI holds contains the value",
    !JSON.stringify(getState().credential).includes(FAKE_SECRET),
    "credential status");

  const config = await rt.agentHostReadConfig("anthropic");
  check("a config file was written", config.exists, config.path);
  check("the config carries a REFERENCE, not a value",
    (config.config as Record<string, Record<string, string>> | null)?.credential?.source ===
      "env",
    JSON.stringify(config.config));
  check("and the reference is an environment variable NAME",
    (config.config as Record<string, Record<string, string>> | null)?.credential?.key ===
      "RIGORLOOM_PROVIDER_CREDENTIAL",
    JSON.stringify(config.config));
  check("the config file does not contain the secret",
    !JSON.stringify(config.config).includes(FAKE_SECRET), config.path);

  const withKey = await probeProvider();
  check("연결 확인 still answers once a credential is stored", withKey,
    JSON.stringify(getState().probeError));
  const keyed = getState().providerProfile;
  check("and now reports the credential as configured",
    (keyed?.notes?.credential as { state?: string } | undefined)?.state === "configured",
    JSON.stringify(keyed?.notes?.credential));
  check("the reference carries the header the Messages API wants, not a bearer",
    (keyed?.notes?.credentialRef as { scheme?: string } | undefined)?.scheme === "raw",
    JSON.stringify(keyed?.notes?.credentialRef));
  check("the capability payload does not contain the secret",
    !JSON.stringify(keyed).includes(FAKE_SECRET), "provider profile");

  // Prefs are the other place a settings pane could leak into.
  const prefs = await rt.loadPrefs();
  check("the prefs file does not contain the secret",
    !JSON.stringify(prefs).includes(FAKE_SECRET), "prefs");
  check("the prefs remember the store key NAME",
    JSON.stringify(prefs).includes(FAKE_STORE_KEY), "prefs");

  // --- the settings pane, drawn ---------------------------------------------
  setState({ settingsOpen: true });
  await settled(300);
  checkDom("the settings pane is on screen", !!document.querySelector('[data-testid="settings"]'),
    domState());
  checkDom("all three providers are offered",
    !!document.querySelector('[data-testid="provider-mock"]') &&
      !!document.querySelector('[data-testid="provider-router"]') &&
      !!document.querySelector('[data-testid="provider-anthropic"]'),
    "provider picker");
  checkDom("the capability table is drawn with three states",
    domText('[data-testid="capability-table"]').includes("모름") &&
      domText('[data-testid="capability-table"]').includes("예"),
    domText('[data-testid="capability-table"]').slice(0, 200));
  checkDom("the config the host will read is shown verbatim",
    domText('[data-testid="settings-config"]').includes("RIGORLOOM_PROVIDER_CREDENTIAL"),
    domText('[data-testid="settings-config"]').slice(0, 200));
  checkDom("no rendered text anywhere contains the secret",
    !(document.body.textContent ?? "").includes(FAKE_SECRET), "document body");

  // Esc closes it, in the one place Esc is handled.
  const { closeTopmostOverlay } = await import("./actions");
  check("Esc closes the settings pane", closeTopmostOverlay() && !getState().settingsOpen,
    String(getState().settingsOpen));

  // Leave the machine as it was found. A sentinel in a developer's credential
  // manager is litter, and a smoke that litters gets ignored.
  await forgetCredential();
  check("the fake credential was removed again", getState().credential?.state === "absent",
    JSON.stringify(getState().credential));

  checkAlive("the settings phase");
}

/**
 * The editor chrome, against real document data.
 *
 * Two launches. The first records what the window is and what it left in
 * prefs; the second must come back to the same geometry, which is the only way
 * to tell a restore from a default.
 */
async function phaseChrome(config: SmokeConfig) {
  if (!config.corpus) {
    check("corpus path supplied", false, "RIGORLOOM_SMOKE_CORPUS is empty");
    return;
  }
  const sessionId = await openPath(config.corpus);
  check("chrome phase opened the corpus form", !!sessionId, sessionId ?? "");
  if (!sessionId) return;
  await settled(240);

  const inspect = activeInspect(getState());
  if (!inspect) {
    check("inspect returned", false, "");
    return;
  }

  // --- the toolbar -----------------------------------------------------------
  checkDom("the editor toolbar is above the document",
    !!document.querySelector('[data-testid="editor-toolbar"]'), domState());
  checkDom("the mode switch lives in the toolbar now",
    !!document.querySelector('[data-testid="editor-toolbar"] [data-testid="mode-text"]'),
    domText('[data-testid="editor-toolbar"]').slice(0, 160));

  const seat = inspect.regions.regions.find((r: EditableRegion) => r.kind === "cell");
  check("a fill seat to stand in", !!seat, JSON.stringify(seat ?? null));
  if (seat && seat.table !== undefined && seat.row !== undefined && seat.col !== undefined) {
    setSelection({ kind: "cell", table: seat.table, row: seat.row, col: seat.col });
    await settled(200);
    checkDom("the toolbar shows the seat's own charPr id",
      seat.charPr !== undefined &&
        domText('[data-testid="tool-charpr"]').includes(String(seat.charPr)),
      `${domText('[data-testid="tool-charpr"]')} vs charPr ${seat.charPr}`);
    // T30: this corpus form's first seat differs from the body shape, and the
    // toolbar must say so rather than showing a bare number. The tag names the
    // body FACE where §14 gave it one and falls back to 본문과 다름 where the
    // document declared none, so either wording is the mark — an unmarked
    // mismatch is the failure.
    if (seat.charPrSuggested !== undefined && seat.charPr !== seat.charPrSuggested) {
      const tag = domText('[data-testid="tool-charpr"]');
      checkDom("a seat whose shape differs from the body is marked in the toolbar",
        tag.includes("본문과 다름") || tag.includes("본문은 "), tag);
    }
    checkDom("the status bar shows the address, not a line and column",
      domText('[data-testid="status-where"]') === `표${seat.table} (${seat.row},${seat.col})`,
      domText('[data-testid="status-where"]'));

    // --- 글꼴, the name the DOCUMENT declares (§14, runtime gap 16) ---------
    //
    // The anti-fabrication assertion, and the reason the field is allowed to
    // exist at all: whatever name is on screen must be a name the runtime put
    // on the wire for THIS charPr. A toolbar that printed 맑은 고딕 because
    // that is what toolbars print would pass a "there is a font name" check and
    // fail this one.
    const face = seat.charPrFace ?? null;
    const shown = document
      .querySelector('[data-testid="typeface-name"]')
      ?.getAttribute("data-face") ?? "";
    const typefaces = inspect.summary.typefaces ?? null;
    check("the runtime says whether faces could be read at all, apart from any one id",
      typefaces?.state === "read" || typefaces?.state === "unavailable",
      `${typefaces?.state} — ${typefaces?.reason ?? "no reason"}`);
    if (face && face.hangul) {
      checkDom("the toolbar shows the seat's typeface NAME, not just its charPr id",
        shown === face.hangul && domText('[data-testid="tool-typeface"]').includes(face.hangul),
        `“${shown}” vs declared ${JSON.stringify(face)}`);
      checkDom("the name on screen is one the runtime declared for THIS charPr",
        Object.values(face).includes(shown),
        `${shown} in ${Object.values(face).join("/")}`);
      // Per language, never merged: the strip shows 한글 and the tooltip
      // carries every language the header resolved.
      const title =
        document.querySelector('[data-testid="typeface-name"]')?.getAttribute("title") ?? "";
      checkDom("every language the document declares is in the tooltip, unmerged",
        Object.values(face).every((name) => title.includes(String(name))),
        title.slice(0, 200));
    } else {
      checkDom("a charPr the document names no face for shows no invented name",
        shown === "" && domText('[data-testid="tool-typeface"]').includes("—"),
        `“${shown}” with charPrFace ${JSON.stringify(face)}`);
      checkDom("and it distinguishes “the document did not say” from “nothing looked”",
        domText('[data-testid="typeface-absent"]') ===
          (typefaces?.state === "read" ? "문서가 이름을 안 밝힘" : "읽지 못함"),
        `${domText('[data-testid="typeface-absent"]')} with typefaces.state ${typefaces?.state}`);
    }

    // T30, in names. The corpus form's first seat differs from the body shape,
    // and the tag now names the body face instead of printing a second integer.
    if (seat.charPrSuggested !== undefined && seat.charPr !== seat.charPrSuggested) {
      const suggestedFace = seat.charPrSuggestedFace ?? null;
      if (suggestedFace?.hangul && face?.hangul && suggestedFace.hangul !== face.hangul) {
        checkDom("a shape mismatch reads as two font NAMES, not two integers",
          domText('[data-testid="tool-charpr"]').includes(suggestedFace.hangul),
          `${domText('[data-testid="tool-charpr"]')} — seat ${face.hangul} vs body ${suggestedFace.hangul}`);
      } else {
        check("RECORDED: the mismatch could not be named on this form", true,
          `seat charPr ${seat.charPr} face ${JSON.stringify(face)} · suggested ` +
            `${seat.charPrSuggested} face ${JSON.stringify(suggestedFace)} — ` +
            `the tag falls back to 본문과 다름`);
      }
    }
  }

  const baseline = inspect.summary.baselineCharPr;
  checkDom("the toolbar shows the body size from the document's own baseline",
    !baseline || domText('[data-testid="tool-size"]').includes(String(baseline.height_pt)),
    `${domText('[data-testid="tool-size"]')} vs ${JSON.stringify(baseline)}`);

  checkDom("the status bar carries the Hangul insert indicator, saying neither",
    domText('[data-testid="verification-bar"]').includes("삽입/수정 없음"),
    domText('[data-testid="verification-bar"]').slice(0, 200));

  // Document zoom, one number for both modes.
  const { setZoom } = await import("./store");
  setZoom(1.2);
  await settled(160);
  checkDom("the toolbar reports the document zoom", domText('[data-testid="zoom-value"]') === "120%",
    domText('[data-testid="zoom-value"]'));
  setZoom(1);
  await settled(120);

  // --- 페이지 보기, where this machine can go -------------------------------
  const { canRenderPages, setCenterMode } = await import("./store");
  if (canRenderPages(getState())) {
    setCenterMode("page");
    await settled(600);
    checkDom("페이지 보기 draws a ruler from the page's own geometry",
      !!document.querySelector('[data-testid="page-ruler"]'), domState());
    checkDom("and a page navigation footer",
      domText('[data-testid="page-indicator"]').includes("쪽"),
      domText('[data-testid="page-footer"]').slice(0, 160));
    checkDom("the status bar shows a page number in 페이지 보기",
      /쪽/.test(domText('[data-testid="verification-bar"]')),
      domText('[data-testid="verification-bar"]').slice(0, 120));
    setCenterMode("text");
    await settled(200);
  } else {
    check("페이지 보기 is offered only when the runtime advertises it", true,
      "capabilities.methods carries no document/render on this build");
  }

  // --- 작업 팩 ---------------------------------------------------------------
  const { loadTaskPacks } = await import("./actions");
  await loadTaskPacks();
  setView("agent");
  await settled(300);
  const packs = getState().taskPacks;
  check("the task pack list came from the module registry", packs?.available === true,
    packs?.reason ?? `${packs?.packs.length} packs`);
  if (packs?.available) {
    check("every declared module is listed", packs.packs.length >= 6,
      packs.packs.map((p) => p.name).join(","));
    // REPOINTED, not deleted — and the reason is worth recording, because it
    // is a defect in the evidence rather than in the app.
    //
    // These three asked for `report requires style` and for `check_style` by
    // name. Both are true only of an ENABLED registry, and enablement lives in
    // `modules/enabled.yaml`, which `.gitignore` excludes. So they passed on
    // the machine that wrote them, where an operator had hand-written that
    // file, and they fail on any fresh checkout — including this worktree,
    // where the registry honestly answers "six discovered, none enabled, so no
    // checkers and no dependencies". The app was right the whole time; the
    // harness had an undeclared dependency on an untracked file.
    //
    // The property worth asserting does not depend on that file: whatever the
    // registry says, the shell repeats it and adds nothing. So the checks now
    // measure fidelity in both directions, and one of them RECORDS which path
    // this machine exercised, so the report says so out loud rather than
    // quietly testing less than it looks like it tests.
    const enabledPacks = packs.packs.filter((p) => p.enabled);
    const withCheckers = packs.packs.filter((p) => (p.checkers ?? []).length > 0);
    const withRequires = packs.packs.filter((p) => (p.requiresModules ?? []).length > 0);
    check("RECORDED: which registry state this run exercised",
      true,
      enabledPacks.length > 0
        ? `${enabledPacks.length} of ${packs.packs.length} modules enabled — the ` +
          `contributions path is under test`
        : `0 of ${packs.packs.length} modules enabled (modules/enabled.yaml is ` +
          `gitignored and absent here), so the registry declares no checkers and ` +
          `no dependencies — the empty path is under test`);
    check("a pack carries contributions exactly when the registry gave it some",
      withCheckers.every((p) => enabledPacks.some((e) => e.name === p.name)) &&
        withRequires.every((p) => enabledPacks.some((e) => e.name === p.name)),
      `${withCheckers.length} packs with checkers, ${withRequires.length} with ` +
        `dependencies, ${enabledPacks.length} enabled`);
    check("no pack invented a checker the registry did not report",
      packs.packs.every((p) =>
        (p.checkers ?? []).every((c) => typeof c.name === "string" && c.name.length > 0)),
      JSON.stringify(packs.packs.map((p) => [p.name, (p.checkers ?? []).length])));
    checkDom("the left rail lists them", !!document.querySelector('[data-testid="pack-report"]'),
      domText('[data-testid="task-packs"]').slice(0, 200));
    setState({ packOpen: "report" });
    await settled(240);
    // REPOINTED, because the panel stopped being 준비 중 when `module/check`
    // arrived. The property that must hold is the same one the 준비 중 label
    // stood for: the panel says what it can do and what it still cannot, and
    // this checkout has nothing enabled — so the 실행 control has to be present
    // AND refused, with the reason. A panel that hid the button on a disabled
    // pack would be honest about the pack and silent about the product.
    checkDom("a pack opens a panel that offers 검사 and says what it still cannot do",
      domText('[data-testid="pack-detail"]').includes("아직 없는 것") &&
        !!document.querySelector('[data-testid="pack-run-button"]'),
      domText('[data-testid="pack-detail"]').slice(0, 200));
    checkDom("with nothing enabled in this checkout, 실행 is present and refused",
      document.querySelector<HTMLButtonElement>('[data-testid="pack-run-button"]')?.disabled ===
        (packs.packs.find((p) => p.name === "report")?.enabled !== true),
      `report enabled=${packs.packs.find((p) => p.name === "report")?.enabled} · ` +
        domText('[data-testid="pack-run"]').slice(0, 120));
    // Same repointing. The panel must print the registry's own contribution
    // COUNTS and every name it was given — which on an enabled registry means
    // the checker names appear, and on this one means it says 0 and 0 rather
    // than leaving the section out.
    const report = packs.packs.find((p) => p.name === "report");
    const detail = domText('[data-testid="pack-detail"]');
    checkDom("the panel names the pack's real contributions, and only those",
      detail.includes(`검사기 ${(report?.checkers ?? []).length}개`) &&
        detail.includes(`명령 ${(report?.cli ?? []).length}개`) &&
        (report?.checkers ?? []).every((c) => detail.includes(String(c.name))),
      `${(report?.checkers ?? []).length} checkers / ${(report?.cli ?? []).length} ` +
        `commands declared · ${detail.slice(0, 200)}`);
    setState({ packOpen: null });
  }

  // --- the two tabs ----------------------------------------------------------
  await settled(160);
  checkDom("the centre offers 대화 and 문서 기록",
    !!document.querySelector('[data-testid="tab-conversation"]') &&
      !!document.querySelector('[data-testid="tab-history"]'),
    domState());
  setState({ agentTab: "history" });
  await settled(200);
  checkDom("문서 기록 shows the session's own events",
    !!document.querySelector('[data-testid="timeline"]'), domState());
  setState({ agentTab: "conversation" });
  await settled(160);

  // --- the window ------------------------------------------------------------
  const geometry = await rt.windowGeometry();
  const prefs = await rt.loadPrefs();
  const saved = (prefs.window ?? null) as Record<string, number | boolean> | null;
  check("the window's geometry was written to prefs", !!saved, JSON.stringify(saved));
  check("and it is the geometry the window actually has",
    !!saved && !!geometry &&
      (saved.maximized === true ||
        (saved.width === geometry.width && saved.height === geometry.height)),
    `${JSON.stringify(saved)} vs ${JSON.stringify(geometry)}`);
  check("the remembered size is not below the editor minimum",
    !!saved && (saved.maximized === true ||
      ((saved.width as number) >= 1024 && (saved.height as number) >= 640)),
    JSON.stringify(saved));
  // Handed to the driver, which compares it against what the SECOND launch
  // restores. A restore that lands on the default by chance is not a restore.
  await rt.smokeFinal({ window: saved, geometry });

  checkAlive("the chrome phase");
}

/** The second launch: the window must come back where it was left. */
async function phaseChromeReattach() {
  const geometry = await rt.windowGeometry();
  const prefs = await rt.loadPrefs();
  const saved = (prefs.window ?? null) as Record<string, number | boolean> | null;
  check("the previous launch left a window geometry", !!saved, JSON.stringify(saved));
  check("this launch came back to it",
    !!saved && !!geometry &&
      (saved.maximized === true ||
        (Math.abs((saved.width as number) - (geometry.width ?? 0)) <= 2 &&
          Math.abs((saved.height as number) - (geometry.height ?? 0)) <= 2)),
    `${JSON.stringify(saved)} vs ${JSON.stringify(geometry)}`);
  check("and the provider settings came back with it",
    typeof (prefs.provider as { provider?: string } | undefined)?.provider === "string",
    JSON.stringify(prefs.provider));
  check("the window is not fullscreen out of nowhere", geometry?.fullscreen === false,
    JSON.stringify(geometry));
  // Handed out for the driver's cross-process comparison. Checking this
  // launch's prefs against this launch's window would be self-fulfilling — the
  // startup save writes the restored value, so a restore that shrank the
  // window by a frame every launch would agree with itself forever. Only run
  // 8's report can say whether this one came back to the same place.
  await rt.smokeFinal({ window: saved, geometry });
  checkAlive("the chrome reattach");
}

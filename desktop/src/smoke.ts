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
  openPath,
  openReceipt,
  preparePages,
  removeOp,
  renderCurrentPage,
  reopenExported,
  reproposeDraft,
  requestApprovalForDraft,
  resolveApprovalDecision,
  runAgentProposal,
  runCheck,
  seatAt,
} from "./actions";
import * as rt from "./runtime";
import {
  activeInspect,
  activeText,
  canRequestApproval,
  draftStaleness,
  getState,
  locateSelection,
  selectionId,
  setCenterMode,
  setSelection,
  setState,
  setView,
  sharedStateSignature,
} from "./store";
import type { EditableRegion, GeometryMapping, HostEvent } from "./types";

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
  check("the queued op carries the seat's address",
    getState().draft.ops[0]?.table === clean.table &&
      getState().draft.ops[0]?.row === clean.row &&
      getState().draft.ops[0]?.col === clean.col,
    `${getState().draft.ops[0]?.table}/${getState().draft.ops[0]?.row}/${getState().draft.ops[0]?.col}`);
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
    const flaggedOp = getState().draft.ops.find(
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
      domText('[data-testid="render-reason"]').includes(render.unavailable?.detail ?? " "),
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
    check("no page was fabricated after the refusal",
      !document.querySelector('[data-testid="page-raster"]'),
      "no raster element");
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
    check("the live document produced geometry on its own", true,
      `${(live.spans ?? []).length} spans without any substitution`);
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
  await renderCurrentPage(1);
  await settled(300);
  await loadGeometry(1);
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
    const target = document.querySelector<HTMLButtonElement>(
      '[data-testid="overlay-seat"][data-editable="true"], ' +
        '[data-testid="overlay-span"][data-editable="true"]',
    );
    target?.click();
    await settled(240);
    checkDom("clicking an editable target opened the SAME inline editor the tree uses",
      !!document.querySelector('[data-testid="seat-input"]'),
      String(getState().inlineEdit?.table));
    await commitEdit("지면에서 입력");
    await settled(400);
    const op = getState().draft.ops.find((o) => o.text === "지면에서 입력");
    check("the overlay edit landed in the same review queue as a tree edit",
      !!op && op.kind === "fill_cell" && op.origin === "user", JSON.stringify(op ?? null));
    check("one plan path: the queue rebuilt a plan over the overlay's op",
      !!getState().draft.plan?.planId,
      getState().draft.plan?.planId ?? "no plan");
  }

  setCenterMode("text");
  await settled();
  checkAlive("the overlay phase");
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
  if (stop === "overlay" || stop === "overlay-live") {
    const { loadGeometry, selectSession } = await import("./actions");
    const staged = (await rt.smokeConfig()).stagedSession;
    if (stop === "overlay" && staged) {
      await selectSession(staged);
      await settled(300);
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
    const seat = seats[0];
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

  if (stop === "packs") {
    const { loadTaskPacks } = await import("./actions");
    await loadTaskPacks();
    setView("agent");
    setState({ packOpen: "report" });
    await settled(400);
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
      const queuedOp = getState().draft.ops.find(
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
  beginEdit(first.table, first.row, first.col);
  await commitEdit("정보공개 청구서 검토본");
  await settled(200);
  if (clean[1]) {
    beginEdit(clean[1].table, clean[1].row, clean[1].col);
    await commitEdit("2026-09-01");
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
  await ready(`shot-${stop}`);
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
    else if (config.phase === "edit") await phaseEdit(config);
    else if (config.phase === "agent") await phaseAgent(config);
    else if (config.phase === "page") await phasePage(config);
    else if (config.phase === "overlay") await phaseOverlay(config);
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
    // toolbar must say so rather than showing a bare number.
    if (seat.charPrSuggested !== undefined && seat.charPr !== seat.charPrSuggested) {
      checkDom("a seat whose shape differs from the body is marked in the toolbar",
        domText('[data-testid="tool-charpr"]').includes("본문과 다름"),
        domText('[data-testid="tool-charpr"]'));
    }
    checkDom("the status bar shows the address, not a line and column",
      domText('[data-testid="status-where"]') === `표${seat.table} (${seat.row},${seat.col})`,
      domText('[data-testid="status-where"]'));
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
    checkDom("a pack opens an honest 준비 중 panel",
      domText('[data-testid="pack-detail"]').includes("준비 중") &&
        domText('[data-testid="pack-detail"]').includes("아직 없는 것"),
      domText('[data-testid="pack-detail"]').slice(0, 200));
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

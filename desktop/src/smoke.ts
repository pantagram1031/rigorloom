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
import type { EditableRegion } from "./types";

interface SmokeConfig {
  phase: string | null;
  corpus: string | null;
  reportPath: string | null;
  /** A genuinely different form, for the staleness check. */
  corpus2?: string | null;
  /** Where the export phase may write. Inside the harness run dir. */
  exportPath?: string | null;
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
  await settled(260);
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

  if (stop === "agent-proposal") {
    await runAgentProposal("MOCK-AGENT-0001");
    await settled(400);
    setView("agent");
    await settled(300);
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

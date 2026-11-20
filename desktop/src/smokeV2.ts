/**
 * The scripted Tauri smoke on the v2 editor (shell, canvas, panel test ids).
 *
 * `open` and `edit` are ported here; they are the launch, open, type, approve
 * and export path WP8's CI smoke runs. The other phases in `smoke.ts` still
 * drive the v1 screens (`?ui=v1` semantics) until each is ported; App renders
 * the v1 screens only for those (see `smokeNeedsLegacy`).
 *
 * The checks keep the v1 phases' names where the claim is the same, so the
 * PowerShell driver's reports stay comparable across the switch.
 */
import { exportApplied, openPath, reopenExported, selectSession } from "./actions";
import { activeDisplayText, activeInspect, getState } from "./store";

export interface SmokeKit {
  check(name: string, ok: boolean, detail?: unknown): void;
  settled(ms?: number): Promise<void>;
  waitFor(predicate: () => boolean, timeoutMs?: number, stepMs?: number): Promise<boolean>;
  domText(selector: string): string;
  hasHangul(text: string): boolean;
  ready(what: string): Promise<void>;
}

export interface SmokeV2Config {
  phase: string | null;
  corpus: string | null;
  exportPath?: string | null;
}

export const V2_SMOKE_PHASES: ReadonlySet<string> = new Set(["open", "edit"]);

const $ = (sel: string) => document.querySelector<HTMLElement>(sel);
const count = (sel: string) => document.querySelectorAll(sel).length;

/** Runtime facts every launch must hold, read from the store (same as v1). */
function runtimeChecks(k: SmokeKit) {
  const status = getState().status;
  k.check("runtime running", !!status?.running, `pid ${status?.pid}`);
  k.check("protocol initialized", !!status?.initialized);
  k.check("sidecar confined to a job object", status?.jobConfined === true, status?.jobError ?? "ok");
  k.check("the packaged sidecar is the one running", status?.mode === "packaged", status?.mode ?? "none");
}

async function openCorpus(k: SmokeKit, config: SmokeV2Config): Promise<string | null> {
  if (!config.corpus) {
    k.check("corpus path supplied", false, "RIGORLOOM_SMOKE_CORPUS is empty");
    return null;
  }
  const sessionId = await openPath(config.corpus);
  k.check("document opened", !!sessionId, sessionId ?? getState().inspectError?.message ?? "");
  if (!sessionId) return null;
  const painted = await k.waitFor(() => !!$('[data-testid="paper"]') && count("[data-cell-key]") > 0, 20000);
  k.check("the page is drawn on the canvas", painted, `${count("[data-cell-key]")} cells`);
  return sessionId;
}

export async function phaseOpenV2(config: SmokeV2Config, k: SmokeKit) {
  runtimeChecks(k);

  // --- Start, before any document -------------------------------------------
  const started = await k.waitFor(() => !!$('[data-testid="start"]'), 15000);
  k.check("Start is shown before a document is open", started, getState().phase);
  k.check("Start carries the boundary sentence", k.hasHangul(k.domText('[data-testid="start"]')));
  k.check("Start offers 파일 열기", !!$('[data-testid="start-open-file"]'));
  k.check("brand mark rendered", !!$('[data-testid="titlebar"] svg'));

  const sessionId = await openCorpus(k, config);
  if (!sessionId) return;
  await k.settled(200);

  // --- structure, from real inspect data ------------------------------------
  const inspect = activeInspect(getState());
  k.check("inspect returned", !!inspect);
  if (!inspect) return;
  k.check("document hash present", inspect.documentHash.length === 64, inspect.documentHash);
  k.check("paragraphs parsed", inspect.graph.paragraphs.length > 0, inspect.graph.paragraphs.length);
  k.check("tables parsed", inspect.graph.tables.length > 0, inspect.graph.tables.length);
  k.check("fill seats found", inspect.regions.regions.length > 0, inspect.regions.regions.length);

  // --- the page --------------------------------------------------------------
  const paperText = k.domText('[data-testid="paper"]');
  k.check("centre shows Korean document text", k.hasHangul(paperText), `${paperText.length} chars`);
  const runTexts = activeDisplayText(getState())
    .flatMap((r) => (r.runs ?? []).map((run) => run.text.trim()))
    .filter((t) => t.length > 1);
  const squash = (s: string) => s.replace(/\s+/g, "");
  const flat = squash(paperText);
  const missing = runTexts.filter((t) => !flat.includes(squash(t)));
  k.check("every text run the runtime reported is rendered in the centre", missing.length === 0,
    missing.length ? `missing ${missing.length}: ${missing.slice(0, 3).join(" | ")}` : `${runTexts.length} runs`);
  const cells = inspect.graph.tables.reduce((n, t) => n + t.cells.length, 0);
  k.check("cells are rendered as real table cells", count("[data-cell-key]") >= cells, `${count("[data-cell-key]")} of ${cells}`);
  k.check("empty blanks carry the seat fill", count(".rl-cell--blank") > 0, `${count(".rl-cell--blank")} blanks`);

  // --- the workspace around it ----------------------------------------------
  k.check("the tab names the document", !!$(`[data-testid="tab-${sessionId}"]`), sessionId);
  k.check("the window title names the document", document.title.endsWith("— Rigorloom"), document.title);
  k.check("the 변경 panel is mounted", !!$('[data-testid="right-panel"]'));
  k.check("the status bar is mounted", !!$('[data-testid="statusbar"]'));
  const blanksTab = $('[data-testid="pane-tab-blanks"]');
  blanksTab?.click();
  await k.settled(160);
  k.check("the 빈칸 pane lists the document's blanks", count('[data-testid^="blank-seat-"]') > 0,
    `${count('[data-testid^="blank-seat-"]')} rows`);
  k.check("no failed slot", count("[data-slot-failed]") === 0, `${count("[data-slot-failed]")} failed`);
  await k.ready("document");
}

/** Type into a React-controlled field the way a person's keystrokes would land. */
function typeInto(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value")?.set?.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
}

export async function phaseEditV2(config: SmokeV2Config, k: SmokeKit) {
  runtimeChecks(k);
  const sessionId = await openCorpus(k, config);
  if (!sessionId) return;
  const inspect = activeInspect(getState());
  if (!inspect) {
    k.check("inspect returned", false);
    return;
  }

  // --- 1. type one value into an empty blank, on the page -------------------
  const VALUE = "리고룸 검사 001";
  const blank = $(".rl-cell--blank[data-cell-key]");
  k.check("an empty blank is on the page", !!blank, `${count(".rl-cell--blank")} blanks`);
  if (!blank) return;
  const key = blank.getAttribute("data-cell-key") ?? "";
  blank.click();
  const opened = await k.waitFor(() => !!$('[data-testid="seat-input"]'), 5000);
  k.check("a click on a blank opens the in-place editor", opened, key);
  const field = $('[data-testid="seat-input"]') as HTMLInputElement | HTMLTextAreaElement | null;
  if (!field) return;
  k.check("the editor sits inside the blank it edits", !!field.closest(`[data-cell-key="${key}"]`), key);
  typeInto(field, VALUE);
  field.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true }));
  const queued = await k.waitFor(() => !!$('[data-testid="change-row-1"]'), 10000);
  k.check("the value lands in the 변경 pane", queued && k.domText('[data-testid="change-row-1"]').includes(VALUE),
    k.domText('[data-testid="change-row-1"]').slice(0, 120));
  k.check("the page shows the value with its margin number",
    k.domText(`[data-cell-key="${key}"]`).includes(VALUE) && !!$('[data-testid="mark-1"]'), key);

  // --- 2. the gate: 결재란, sheet, 승인 --------------------------------------
  const gateOpen = await k.waitFor(() => !($('[data-testid="approve"]') as HTMLButtonElement | null)?.disabled, 120000, 500);
  k.check("승인 opens once the plan is checked", gateOpen, k.domText('[data-testid="gate-footer"]').slice(0, 120));
  if (!gateOpen) return;
  $('[data-testid="approve"]')?.click();
  const sheet = await k.waitFor(() => !!$('[data-testid="approve-sheet"]'), 5000);
  k.check("the approval sheet opens", sheet);
  k.check("the sheet states the guard's scope", !!$('[data-testid="guard-scope"]'));
  k.check("the sheet shows no full hash", !/[0-9a-f]{13,}/.test(k.domText('[data-testid="approve-sheet"]')));
  const confirmable = await k.waitFor(() => !($('[data-testid="approve-confirm"]') as HTMLButtonElement | null)?.disabled, 60000, 500);
  k.check("승인 in the sheet is enabled", confirmable);
  $('[data-testid="approve-confirm"]')?.click();
  const applied = await k.waitFor(() => !!$('[data-testid="applied-footer"]'), 120000, 500);
  k.check("the 결재란 fills in after 승인", applied && k.domText('[data-testid="gate-approved"]').includes("직접 승인"),
    k.domText('[data-testid="applied-footer"]').slice(0, 160));
  const outcome = getState().applyOutcomes?.[sessionId];
  const candidate = outcome?.applied ?? null;
  k.check("a new 수정본 exists", !!candidate?.runId, JSON.stringify(outcome?.error ?? null));
  const shown = await k.waitFor(() => k.domText(`[data-cell-key="${key}"]`).includes(VALUE), 15000);
  k.check("the page shows 수정본 1 with the value", shown && k.domText('[data-testid="strip-version"]').includes("1"),
    k.domText('[data-testid="strip-version"]'));

  // --- 3. export, and a reopen that proves the file loads -------------------
  if (config.exportPath && candidate) {
    const exported = await exportApplied(config.exportPath);
    k.check("the candidate exported", exported, JSON.stringify(getState().exportError));
    const result = getState().exportResult;
    k.check("the exported bytes hash to the candidate's digest", result?.sha256 === candidate.candidate.sha256,
      `${result?.sha256} vs ${candidate.candidate.sha256}`);
    k.check("the receipt travelled with it",
      typeof result?.receiptPath === "string" && result.receiptPath.endsWith(".receipt.json"), result?.receiptPath ?? "");
    if (exported) {
      const reopenedOk = await reopenExported();
      await k.settled(200);
      k.check("the exported file opens again as a document", reopenedOk, JSON.stringify(getState().inspectError));
      k.check("the reopened file is byte-identical to the candidate", getState().reopened?.sha256 === candidate.candidate.sha256,
        `${getState().reopened?.sha256} vs ${candidate.candidate.sha256}`);
      await selectSession(sessionId);
      await k.settled(200);
    }
  }

  // --- 4. the events recorded the whole thing -------------------------------
  await k.waitFor(() => getState().events.some((e) => e.kind === "candidate.published"), 12000);
  const kinds = getState().events.map((e) => e.kind);
  for (const wanted of ["session.opened", "plan.proposed", "plan.validated", "approval.requested", "approval.resolved", "plan.applied", "candidate.published"]) {
    k.check(`the event log recorded ${wanted}`, kinds.includes(wanted), kinds.join(", "));
  }
  k.check("no failed slot", count("[data-slot-failed]") === 0, `${count("[data-slot-failed]")} failed`);
  await k.ready("document");
}

export async function runV2Phase(config: SmokeV2Config, k: SmokeKit): Promise<void> {
  if (config.phase === "open") await phaseOpenV2(config, k);
  else if (config.phase === "edit") await phaseEditV2(config, k);
}

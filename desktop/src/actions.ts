/**
 * Everything the app can do, as plain functions over the one store.
 *
 * Kept out of components so the scripted smoke drives the same code path a
 * click does — a smoke that exercised its own private path would prove nothing
 * about the app.
 */
import { open as openFileDialog } from "@tauri-apps/plugin-dialog";
import { getCurrentWebview } from "@tauri-apps/api/webview";

import * as rt from "./runtime";
import {
  getState,
  setState,
  setSelection,
  showToast,
} from "./store";
import type { Finding, InspectResult, Recent, RegionText } from "./types";

const MAX_RECENTS = 8;
export const ZOOM_MIN = 0.5;
export const ZOOM_MAX = 2.0;
const ZOOM_STEPS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.35, 1.5, 1.75, 2.0];

/** Load a session's inspect once and cache it. */
export async function loadInspect(sessionId: string, force = false): Promise<boolean> {
  if (!force && getState().inspects[sessionId]) {
    setState({ inspectPhase: "ready", inspectError: null });
    return true;
  }
  setState({ inspectPhase: "starting", inspectError: null });
  try {
    const result = await rt.inspect(sessionId);
    setState({
      inspects: { ...getState().inspects, [sessionId]: result },
      inspectPhase: "ready",
      inspectError: null,
    });
    return true;
  } catch (e) {
    setState({ inspectPhase: "failed", inspectError: rt.asRuntimeError(e) });
    return false;
  }
}

/**
 * Fetch the document's full text for the centre column.
 *
 * `graph.paragraphs[].text` is already complete, so only table cells need
 * `document/readRegion` — and they genuinely do: `textPreview` in the graph is
 * truncated for anything long, and the runtime flags that with `truncated`.
 * readRegion additionally returns per-run `color_value` and `color_anomaly`,
 * which is the only place the real colour of a run is available.
 *
 * The response is bounded at 256 KiB and the runtime **refuses rather than
 * truncates** (`region_too_large`). So the request is chunked, and a chunk that
 * is still refused is dropped rather than retried forever — the cells it
 * covered fall back to their graph preview, which the UI marks as a preview.
 */
const REGION_CHUNK = 40;

export async function loadText(sessionId: string, force = false): Promise<boolean> {
  if (!force && getState().texts[sessionId]) {
    setState({ textPhase: "ready", textError: null });
    return true;
  }
  const inspect = getState().inspects[sessionId];
  if (!inspect) return false;

  const wanted = inspect.graph.tables.flatMap((t) =>
    t.cells.map((c) => ({ table: t.index, row: c.addr.row, col: c.addr.col })),
  );
  if (wanted.length === 0) {
    setState({ texts: { ...getState().texts, [sessionId]: [] }, textPhase: "ready" });
    return true;
  }

  setState({ textPhase: "starting", textError: null });
  const collected: RegionText[] = [];
  let refused: unknown = null;
  for (let i = 0; i < wanted.length; i += REGION_CHUNK) {
    const chunk = wanted.slice(i, i + REGION_CHUNK);
    try {
      const res = await rt.readRegion(sessionId, chunk);
      collected.push(...res.regions);
    } catch (e) {
      // Honest partial: keep what came back, remember why the rest did not.
      refused = e;
    }
  }
  setState({
    texts: { ...getState().texts, [sessionId]: collected },
    textPhase: "ready",
    textError: refused ? rt.asRuntimeError(refused) : null,
  });
  return true;
}

async function loadCandidates(sessionId: string) {
  try {
    const list = await rt.candidates(sessionId);
    setState({ candidates: { ...getState().candidates, [sessionId]: list } });
  } catch {
    // `candidate/list` is not load-bearing for a read-only phase. Absence is
    // not failure — the bar already renders an explicit empty state.
  }
}

/** Make a session active. Selection is cleared only when the document changes. */
export async function selectSession(sessionId: string) {
  const previous = getState().activeSessionId;
  setState({
    activeSessionId: sessionId,
    ...(previous !== sessionId
      ? { selection: null, page: 1, findings: [], checkedAt: null, checkPhase: "idle" as const }
      : {}),
  });
  await rt.savePrefs({ lastSessionId: sessionId });
  await loadInspect(sessionId);
  await loadText(sessionId);
  await loadCandidates(sessionId);
  rememberRecent(sessionId);
}

export async function refreshSessions(): Promise<void> {
  try {
    setState({ sessions: await rt.sessions() });
  } catch (e) {
    setState({ fatal: rt.asRuntimeError(e) });
  }
}

// --- recents ----------------------------------------------------------------

/**
 * Remember a document so the welcome screen can offer it back.
 *
 * Keyed on the source path, because that is what reopening needs; the hash
 * rides along so the list can show it and so a moved-but-identical file is
 * recognisable. Persisted in the shell's prefs file, not in the runtime root —
 * a recent is a shell affordance, not a runtime fact.
 */
export function rememberRecent(sessionId: string) {
  const session = getState().sessions.find((s) => s.sessionId === sessionId);
  const path = getState().openedPaths[sessionId];
  if (!session || !path) return;
  const entry: Recent = {
    path,
    name: session.source.name,
    sha256: session.source.sha256,
    bytes: session.source.bytes,
    openedUtc: new Date().toISOString().replace(/\.\d+Z$/, "Z"),
  };
  const next = [entry, ...getState().recents.filter((r) => r.path !== path)].slice(
    0,
    MAX_RECENTS,
  );
  setState({ recents: next });
  void rt.savePrefs({ recents: next });
}

// --- opening ----------------------------------------------------------------

/**
 * Open a document by absolute path. `workspace/openPath` is host-only, and it
 * validates, copies into the session and records the SHA-256 — the source
 * itself is never touched.
 */
export async function openPath(path: string): Promise<string | null> {
  try {
    const opened = await rt.openPath(path);
    const openedPaths = { ...getState().openedPaths, [opened.sessionId]: path };
    setState({ openedPaths });
    // Persisted so a relaunch can still name where a session came from; the
    // Runtime deliberately does not keep the source path.
    await rt.savePrefs({ openedPaths });
    await refreshSessions();
    await selectSession(opened.sessionId);
    return opened.sessionId;
  } catch (e) {
    setState({ inspectPhase: "failed", inspectError: rt.asRuntimeError(e) });
    return null;
  }
}

/** The native file dialog. No web upload, no localhost. */
export async function openViaDialog(): Promise<string | null> {
  const chosen = await openFileDialog({
    multiple: false,
    directory: false,
    title: "한글 문서 열기",
    filters: [{ name: "한글 문서", extensions: ["hwpx", "hwp"] }],
  });
  if (typeof chosen !== "string") return null;
  return openPath(chosen);
}

const SUPPORTED = /\.(hwpx|hwp)$/i;

/** Files dropped on the window. Anything unsupported is refused out loud. */
export async function openDropped(paths: string[]): Promise<void> {
  setState({ dragOver: false });
  const usable = paths.filter((p) => SUPPORTED.test(p));
  if (usable.length === 0) {
    showToast("한글 문서(.hwpx, .hwp)만 열 수 있습니다", 2000);
    return;
  }
  for (const path of usable.slice(0, 1)) {
    await openPath(path);
  }
  if (usable.length > 1) {
    showToast(`${usable.length}개 중 첫 문서만 열었습니다`, 2000);
  }
}

// --- checking ---------------------------------------------------------------

/**
 * 검사 실행 — re-read the document and report what this build can actually
 * check.
 *
 * This is NOT `verify/*`: those methods are GAP, and the domain layer's
 * `candidate_verify` is deliberately not on the wire (it needs an applied
 * candidate, which a read-only phase never produces). Claiming otherwise would
 * be the exact dishonesty the verification bar exists to prevent, so the bar
 * keeps saying the render proof and the checkers did not run.
 *
 * What it does do is real: it re-runs `document/inspect` and re-reads every
 * region, then reports the preflight facts the engine itself computed —
 * `color_anomaly` (T127: the blue body text that once shipped as clean),
 * `scriptAnomaly` (T30), and guide text still sitting in a fill seat. Every
 * finding carries its address, so selecting one navigates the document.
 */
export async function runCheck(): Promise<void> {
  const sessionId = getState().activeSessionId;
  if (!sessionId) return;
  setState({ checkPhase: "starting", sheetOpen: true });

  await loadInspect(sessionId, true);
  await loadText(sessionId, true);

  const inspect = getState().inspects[sessionId];
  if (!inspect) {
    setState({ checkPhase: "failed" });
    return;
  }
  const findings = collectFindings(inspect, getState().texts[sessionId] ?? []);
  setState({
    findings,
    checkPhase: "ready",
    checkedAt: new Date().toISOString().replace(/\.\d+Z$/, "Z"),
  });
  await loadCandidates(sessionId);
}

export function collectFindings(inspect: InspectResult, texts: RegionText[]): Finding[] {
  const out: Finding[] = [];

  for (const region of inspect.regions.regions) {
    if (region.kind !== "cell" || region.table === undefined) continue;
    const where = `표 ${region.table} R${region.row}C${region.col}`;
    const selection = {
      kind: "cell" as const,
      table: region.table,
      row: region.row!,
      col: region.col!,
    };
    if (region.colorAnomaly) {
      out.push({
        code: "color_anomaly",
        severity: "hard",
        where,
        selection,
        message: "글자색이 본문 기준과 다릅니다. 이대로 채우면 색이 남습니다.",
      });
    }
    if (region.scriptAnomaly) {
      out.push({
        code: "fill_charpr_script_anomaly",
        severity: "warn",
        where,
        selection,
        message: `글자 속성이 본문 기준과 다릅니다. charPr ${region.charPr} → ${region.charPrSuggested} 권장.`,
      });
    }
  }

  // Runs carry the colour the document really has; a seat can look clean at
  // cell level and still contain a coloured run.
  for (const region of texts) {
    for (const run of region.runs ?? []) {
      if (!run.color_anomaly) continue;
      const isCell = region.addr !== undefined;
      out.push({
        code: "run_color_anomaly",
        severity: "warn",
        where: isCell
          ? `표 ${region.table} R${region.addr!.row}C${region.addr!.col} #${run.index}`
          : `문단 ${region.at_para} #${run.index}`,
        selection: isCell
          ? {
              kind: "cell",
              table: region.table ?? 0,
              row: region.addr!.row,
              col: region.addr!.col,
            }
          : region.at_para !== undefined
            ? { kind: "paragraph", atPara: region.at_para }
            : null,
        message: `본문 기준과 다른 색(${run.color_value ?? "알 수 없음"})으로 쓰인 글이 있습니다: "${trimRun(run.text)}"`,
      });
    }
  }

  for (const target of inspect.summary.scriptAnomalyTargets) {
    const where = `표 ${target.table} R${target.addr.row}C${target.addr.col}`;
    if (out.some((f) => f.where === where && f.code.includes("script"))) continue;
    out.push({
      code: "script_anomaly_target",
      severity: "warn",
      where,
      selection: {
        kind: "cell",
        table: target.table,
        row: target.addr.row,
        col: target.addr.col,
      },
      message: `글자 속성 ${target.differing.join(", ")}이(가) 기준과 다릅니다. charPr ${target.charpr} → ${target.charpr_suggested}.`,
    });
  }

  if (out.length === 0) {
    out.push({
      code: "clean",
      severity: "info",
      where: "문서 전체",
      selection: null,
      message: "이 빌드가 볼 수 있는 범위에서는 걸리는 것이 없습니다. 렌더 증명과 제출 검사는 아직 실행할 수 없습니다.",
    });
  }
  return out;
}

function trimRun(text: string, max = 24): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max)}…` : flat;
}

// --- copy -------------------------------------------------------------------

/**
 * Ctrl+C. Defers to a real text selection when the user made one — the paper
 * column is selectable and dragging across it should behave like text — and
 * otherwise copies whatever the selected node contains.
 *
 * Returns false when it did nothing, so the key handler can let the event
 * through to the browser's own copy.
 */
export async function copySelection(): Promise<boolean> {
  const dom = window.getSelection()?.toString() ?? "";
  if (dom.trim().length > 0) return false;

  const state = getState();
  const selection = state.selection;
  const sessionId = state.activeSessionId;
  if (!selection || !sessionId) return false;

  const texts = state.texts[sessionId] ?? [];
  const inspect = state.inspects[sessionId];
  let text: string | null = null;
  let label = "";

  if (selection.kind === "cell") {
    const region = texts.find(
      (r) =>
        r.addr?.row === selection.row &&
        r.addr?.col === selection.col &&
        (r.table ?? 0) === selection.table,
    );
    text =
      region?.text ??
      inspect?.graph.tables
        .find((t) => t.index === selection.table)
        ?.cells.find((c) => c.addr.row === selection.row && c.addr.col === selection.col)
        ?.textPreview ??
      null;
    label = `표 ${selection.table} R${selection.row}C${selection.col}`;
  } else if (selection.kind === "paragraph") {
    text =
      inspect?.graph.paragraphs.find((p) => p.at_para === selection.atPara)?.text ?? null;
    label = `문단 ${selection.atPara}`;
  }

  if (text === null || text.length === 0) {
    showToast("복사할 글이 없습니다", 1400);
    return true;
  }
  await writeClipboard(text);
  showToast(`${label} 복사됨`, 1400);
  return true;
}

async function writeClipboard(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    return;
  } catch {
    // Fall through: some webview configurations refuse the async API.
  }
  const scratch = document.createElement("textarea");
  scratch.value = text;
  scratch.setAttribute("readonly", "");
  scratch.style.position = "fixed";
  scratch.style.opacity = "0";
  document.body.appendChild(scratch);
  scratch.select();
  try {
    document.execCommand("copy");
  } finally {
    document.body.removeChild(scratch);
  }
}

// --- UI zoom ----------------------------------------------------------------

/**
 * Scale the whole app. Uses the webview's own zoom rather than root font-size
 * so vector chrome, the paper column and the logo scale together and text
 * stays crisply re-rasterised rather than resampled.
 *
 * Independent of `zoom`, which is the page-preview scale.
 */
export async function applyUiZoom(factor: number, announce = true): Promise<void> {
  const clamped = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, factor));
  setState({ uiZoom: clamped });
  try {
    await getCurrentWebview().setZoom(clamped);
  } catch {
    // A webview that refuses zoom must not break the app; the store still
    // holds the value and the next launch will try again.
  }
  await rt.savePrefs({ uiZoom: clamped });
  if (announce) showToast(`${Math.round(clamped * 100)}%`);
}

export function stepUiZoom(direction: 1 | -1): void {
  const current = getState().uiZoom;
  const index = ZOOM_STEPS.findIndex((z) => Math.abs(z - current) < 0.001);
  const from = index === -1 ? ZOOM_STEPS.indexOf(1) : index;
  const next = ZOOM_STEPS[Math.min(ZOOM_STEPS.length - 1, Math.max(0, from + direction))];
  void applyUiZoom(next);
}

export const resetUiZoom = () => void applyUiZoom(1);

// --- lifecycle --------------------------------------------------------------

/**
 * Start the runtime and restore what the last run was doing.
 *
 * Objective: close and reopen without a terminal. The Runtime already persists
 * sessions on disk under `--root`, so reattaching is remembering the root and
 * the session id and then calling `session/list`.
 */
export async function boot(): Promise<void> {
  setState({ phase: "starting", phaseNote: "런타임을 시작하는 중", fatal: null });
  try {
    const prefs = await rt.loadPrefs();
    const root = (prefs.root as string | undefined) ?? (await rt.defaultRoot());

    // Restore chrome before the window is shown, so nothing visibly resizes.
    const savedZoom = Number(prefs.uiZoom);
    if (Number.isFinite(savedZoom) && savedZoom !== 1) {
      await applyUiZoom(savedZoom, false);
    }
    if (Array.isArray(prefs.recents)) setState({ recents: prefs.recents as Recent[] });
    if (prefs.openedPaths && typeof prefs.openedPaths === "object") {
      setState({ openedPaths: prefs.openedPaths as Record<string, string> });
    }

    const { status } = await rt.start(root);
    setState({ status, root: status.root ?? root, phaseNote: "능력을 확인하는 중" });

    setState({ capabilities: await rt.capabilities() });
    setState({ phaseNote: "열린 문서를 찾는 중" });
    await refreshSessions();

    const remembered = prefs.lastSessionId as string | undefined;
    const sessions = getState().sessions;
    const target =
      (remembered && sessions.find((s) => s.sessionId === remembered)?.sessionId) ??
      sessions[0]?.sessionId;

    setState({ view: prefs.lastView === "agent" ? "agent" : "document" });

    if (target) {
      setState({ phaseNote: "문서를 다시 읽는 중" });
      await selectSession(target);
    }
    setState({ phase: "ready", phaseNote: "" });
  } catch (e) {
    setState({ phase: "failed", fatal: rt.asRuntimeError(e) });
  }
}

/** A dead sidecar must be recoverable without losing document state. */
export async function restartRuntime(): Promise<void> {
  const keepSession = getState().activeSessionId;
  setState({ phase: "starting", phaseNote: "런타임을 다시 시작하는 중", fatal: null });
  try {
    const { status } = await rt.start(getState().root);
    setState({ status, capabilities: await rt.capabilities() });
    await refreshSessions();
    if (keepSession && getState().sessions.some((s) => s.sessionId === keepSession)) {
      setState({ activeSessionId: keepSession });
    }
    setState({ phase: "ready", phaseNote: "" });
  } catch (e) {
    setState({ phase: "failed", fatal: rt.asRuntimeError(e) });
  }
}

export { setSelection };

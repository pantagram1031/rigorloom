/**
 * Report-pipeline header shape the Desktop displays. Copied from
 * `workspace/pipelineStatus`; never recomputed here.
 */
import type { PipelineGate, PipelineStatus } from "./types";

export const EMPTY_FILL_INPUTS = {
  complete: false,
  missing: [] as string[],
  formPath: null,
  contentPath: null,
  buildYamlPath: null,
  formProfilePath: null,
  baselinePath: null,
};

export const EMPTY_POSTER_INPUTS = {
  complete: false,
  missing: [] as string[],
  contentPath: null,
  figuresPath: null,
  formPath: null,
};

export const PIPELINE_NOT_FOUND: PipelineStatus = {
  found: false,
  workspacePath: null,
  slug: null,
  mode: null,
  subject: null,
  updated: null,
  canonicalOutput: null,
  stages: [],
  nextGate: null,
  fillInputs: EMPTY_FILL_INPUTS,
  posterInputs: EMPTY_POSTER_INPUTS,
};

/** Dev-mock / tests: the AURALAB classroom header, field-for-field. */
export const AURALAB_PIPELINE_STATUS: PipelineStatus = {
  found: true,
  workspacePath: "C:\\Users\\user\\Downloads\\ReportWorkspace project\\reports\\report-auralab-classroom",
  slug: "report-auralab-classroom",
  mode: "autonomous",
  subject: "physics",
  updated: "2026-09-16T21:39:00",
  canonicalOutput: "output/out.hwpx",
  stages: [
    { id: "0", label: "form_intake", status: "done", gate: { name: "topic_pick", state: "auto_approved", by: "autonomous", at: "2026-09-16T18:13:13" } },
    { id: "1", label: "research", status: "done", gate: null },
    { id: "2", label: "design", status: "done", gate: { name: "design", state: "auto_approved", by: "autonomous", at: "2026-09-16T18:25:36" } },
    { id: "2.5", label: "layout_plan", status: "done", gate: { name: "layout", state: "auto_approved", by: "script", at: "2026-09-16T18:25:39" } },
    { id: "3", label: "sim", status: "done", gate: { name: "sane", state: "auto_approved", by: "script", at: "2026-09-16T18:27:25" } },
    { id: "4", label: "write", status: "done", gate: { name: "draft", state: "auto_approved", by: "autonomous", at: "2026-09-16T18:34:52" } },
    { id: "4.5", label: "content_audit", status: "done", gate: { name: "content_audit", state: "auto_approved", by: "script", at: "2026-09-16T21:34:33" } },
    { id: "5", label: "assemble", status: "done", gate: null },
    { id: "5.3", label: "format_check", status: "done", gate: { name: "format_check", state: "auto_approved", by: "script", at: "2026-09-16T21:38:37" } },
    { id: "5.5", label: "understand", status: "done", gate: { name: "understand", state: "auto_approved", by: "script", at: "2026-09-16T21:38:40" } },
    { id: "5.7", label: "final_panel", status: "done", gate: { name: "final_panel", state: "auto_approved", by: "script", at: "2026-09-16T21:38:43" } },
    { id: "6", label: "return", status: "done", gate: { name: "submission_preflight", state: "auto_approved", by: "script", at: "2026-09-16T21:38:59" } },
  ],
  nextGate: null,
  fillInputs: {
    complete: true,
    missing: [],
    formPath: "C:\\Users\\user\\Downloads\\ReportWorkspace project\\reports\\report-auralab-classroom\\output\\form_copy.hwpx",
    contentPath: "C:\\Users\\user\\Downloads\\ReportWorkspace project\\reports\\report-auralab-classroom\\bundle\\content.md",
    buildYamlPath: "C:\\Users\\user\\Downloads\\ReportWorkspace project\\reports\\report-auralab-classroom\\build.yaml",
    formProfilePath: "C:\\Users\\user\\Downloads\\ReportWorkspace project\\reports\\report-auralab-classroom\\form_profile.json",
    baselinePath: null,
  },
  posterInputs: {
    complete: true,
    missing: [],
    contentPath: "C:\\Users\\user\\Downloads\\ReportWorkspace project\\reports\\report-auralab-classroom\\poster\\poster_content.md",
    figuresPath: "C:\\Users\\user\\Downloads\\ReportWorkspace project\\reports\\report-auralab-classroom\\bundle\\figures",
    formPath: "C:\\Users\\user\\Downloads\\ReportWorkspace project\\reports\\report-auralab-classroom\\poster\\form.pptx",
  },
};

export function stagesDone(status: PipelineStatus): { done: number; total: number } {
  const total = status.stages.length;
  const done = status.stages.filter((row) => row.status === "done").length;
  return { done, total };
}

export function gateStateLabel(gate: PipelineGate | null): string {
  if (!gate) return "없음";
  if (gate.state === "auto_approved") return "자동 승인";
  if (gate.state === "approved") return "승인";
  if (gate.state === "pending") return "대기";
  if (gate.state === "rejected") return "거절";
  return gate.state ? String(gate.state) : "없음";
}

export function gateTone(
  gate: PipelineGate | null,
): "ok" | "warn" | "bad" | "none" {
  if (!gate || !gate.state) return "none";
  if (gate.state === "auto_approved" || gate.state === "approved") return "ok";
  if (gate.state === "pending") return "warn";
  if (gate.state === "rejected") return "bad";
  return "none";
}

export function stripSummary(status: PipelineStatus): string {
  const { done, total } = stagesDone(status);
  const next = status.nextGate?.gate?.name ?? status.nextGate?.stageId ?? "없음";
  const slug = status.slug ?? "—";
  const mode = status.mode ?? "—";
  return `${slug} · ${mode} · ${done}/${total} 단계 완료 · 다음 게이트 ${next}`;
}

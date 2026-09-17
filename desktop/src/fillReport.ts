/**
 * Fill-loop display helpers. Proof grade is copied from fill_report; a contact
 * sheet is never labelled as rendering proof beyond that grade.
 */
import type { Capabilities, FillResult, PipelineStatus } from "./types";

export const FILL_FOOTER =
  "접촉면의 증명 등급은 fill_report가 보고한 값입니다. 렌더링 증명이 아닙니다.";

export function proofGradeLabel(grade: string | null | undefined): string {
  return `증명 등급: ${grade || "none"}`;
}

export function hancomAvailable(capabilities: Capabilities | null | undefined): boolean {
  if (!capabilities) return false;
  const com = capabilities.backends?.com;
  if (!com || com.state !== "available") return false;
  const tool = capabilities.tools?.fill_report;
  if (tool && tool.state !== "available") return false;
  return (capabilities.methods ?? []).includes("workspace/fillRun");
}

export function canRunFill(
  status: PipelineStatus | null | undefined,
  capabilities: Capabilities | null | undefined,
): boolean {
  return Boolean(status?.found && status.fillInputs?.complete && hancomAvailable(capabilities));
}

/** Dev-mock: a converged hancom loop with one inlined contact sheet. */
export function mockFillResult(workspacePath: string, sessionId: string | null): FillResult {
  const sheet =
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";
  const layoutQa = {
    checker: "layout_qa",
    state: "ran",
    ok: true,
    hard: [],
    warn: [],
    counts: { hard: 0, warn: 0 },
  };
  const verifyFormat = {
    checker: "verify_format",
    state: "ran",
    ok: true,
    verdict: "pass",
    hard: [],
    warn: [],
    counts: { hard: 0, warn: 0 },
  };
  return {
    workspacePath,
    sessionId,
    state: "converged",
    converged: true,
    proofGrade: "hancom",
    pageCount: 20,
    iterations: 1,
    verdict: {
      state: "converged",
      proof_grade: "hancom",
      page_count: 20,
      converged: true,
    },
    outputs: [
      {
        role: "hwpx",
        path: `${workspacePath}\\output\\out.hwpx`,
        sha256: "aa".padEnd(64, "0"),
        bytes: 2048,
      },
      {
        role: "pdf",
        path: `${workspacePath}\\output\\out.pdf`,
        sha256: "bb".padEnd(64, "0"),
        bytes: 1024,
      },
      {
        role: "verdict",
        path: `${workspacePath}\\output\\verdict_v06.json`,
        sha256: "cc".padEnd(64, "0"),
        bytes: 128,
      },
    ],
    contactSheets: [
      {
        path: `${workspacePath}\\output\\proof\\sheet-1.png`,
        sha256: "dd".padEnd(64, "0"),
        bytes: 70,
        mediaType: "image/png",
        data: sheet,
      },
    ],
    layoutQa,
    verifyFormat,
    checks: {
      required: ["layout_qa", "verify_format"],
      ranAll: true,
      acceptance: true,
      reason: null,
      note: "layout QA is copied from fill_report; verify_format is the pipeline checker. Neither is a render proof.",
      checks: [layoutQa, verifyFormat],
    },
  };
}

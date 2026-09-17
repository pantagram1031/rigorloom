/**
 * Offline-checker rows from `candidate/verify`. Verdicts are copied, never
 * recomputed: unavailable stays unavailable, never pass.
 */
import type { CheckRow } from "./types";
import type { VerifyFinding, VerifyResult, VerifyTarget } from "./types";

export const VERIFY_FOOTER =
  "이 검사는 바이트와 오프라인 규칙만 봅니다. 렌더링 증명이 아닙니다.";

export type CheckerVerdict = "pass" | "warn" | "fail" | "unavailable";

export function checkerFindings(row: CheckRow): VerifyFinding[] {
  const hard = (Array.isArray(row.hard) ? row.hard : []) as VerifyFinding[];
  const warn = (Array.isArray(row.warn) ? row.warn : []) as VerifyFinding[];
  return [...hard, ...warn];
}

export function checkerCounts(row: CheckRow): { hard: number; warn: number } {
  const listed = checkerFindings(row);
  const hardListed = (Array.isArray(row.hard) ? row.hard.length : 0);
  const warnListed = (Array.isArray(row.warn) ? row.warn.length : 0);
  const counts = row.counts as { hard?: number; warn?: number } | undefined;
  return {
    hard: typeof counts?.hard === "number" ? counts.hard : hardListed,
    warn: typeof counts?.warn === "number" ? counts.warn : warnListed || listed.length - hardListed,
  };
}

export function checkerVerdict(row: CheckRow): CheckerVerdict {
  if (String(row.state ?? "") !== "ran") return "unavailable";
  const { hard, warn } = checkerCounts(row);
  if (row.ok === false || hard > 0) return "fail";
  if (warn > 0) return "warn";
  return "pass";
}

export function verdictLabel(verdict: CheckerVerdict): string {
  if (verdict === "pass") return "통과";
  if (verdict === "warn") return "주의";
  if (verdict === "fail") return "실패";
  return "미실행";
}

export function verdictTone(verdict: CheckerVerdict): "ok" | "warn" | "bad" | "none" {
  if (verdict === "pass") return "ok";
  if (verdict === "warn") return "warn";
  if (verdict === "fail") return "bad";
  return "none";
}

export function isVerifySource(target: VerifyTarget | null | undefined): boolean {
  return Boolean(target && "source" in target && target.source);
}

export function verifyTargetLabel(result: Pick<VerifyResult, "target" | "runId">): string {
  if (isVerifySource(result.target) || !result.runId) return "원본";
  return `후보본 ${result.runId}`;
}

export function worstVerifyVerdict(rows: CheckRow[]): CheckerVerdict | null {
  if (rows.length === 0) return null;
  const order: CheckerVerdict[] = ["fail", "unavailable", "warn", "pass"];
  const seen = new Set(rows.map(checkerVerdict));
  return order.find((item) => seen.has(item)) ?? null;
}

/** Dev-mock: one pass, one warn with two findings, one unavailable. */
export function mockVerifyResult(sessionId: string, runId: string | null): VerifyResult {
  return {
    sessionId,
    runId,
    target: runId ? { runId } : { source: true },
    checkedUtc: "2026-09-18T00:00:00Z",
    candidate: runId
      ? {
          role: "candidate",
          path: "artifact.hwpx",
          sha256: "ab".padEnd(64, "0"),
          bytes: 12,
        }
      : null,
    checks: {
      required: ["check_residue"],
      ranAll: true,
      acceptance: true,
      reason: null,
      note: "acceptance asserts that every required check RAN and was clean; a check that could not run is reported unavailable and never counted as a pass.",
      checks: [
        {
          checker: "check_residue",
          state: "ran",
          ok: true,
          verdict: "pass",
          counts: { hard: 0, warn: 0 },
          hard: [],
          warn: [],
        },
        {
          checker: "verify_format",
          state: "ran",
          ok: true,
          verdict: "warn",
          counts: { hard: 0, warn: 2 },
          hard: [],
          warn: [
            { code: "F2", msg: "안내 색 정의가 header.xml에 남아 있습니다.", at: "header.xml", page: null },
            { code: "F3", msg: "본문 서식이 기준과 다릅니다.", at: "Contents/section0.xml", page: 1 },
          ],
        },
        {
          checker: "layout_qa",
          state: "unavailable",
          ok: null,
          verdict: null,
          reason: "layout_qa needs a PDF that only Hancom produces",
        },
      ],
    },
  };
}

/**
 * Poster-line display helpers. The PNG is a preview, never a render proof.
 * Verifier rows reuse the P2 checker vocabulary.
 */
import type { Capabilities, PipelineStatus, PosterResult } from "./types";

export const POSTER_FOOTER =
  "미리보기 이미지, 증명 아님. 게이트는 poster-verify가 보고한 값입니다.";

export const POSTER_PREVIEW_LABEL = "미리보기 이미지, 증명 아님";

export function canRunPoster(
  status: PipelineStatus | null | undefined,
  capabilities: Capabilities | null | undefined,
): boolean {
  const methods = capabilities?.methods ?? [];
  return Boolean(
    status?.found &&
      status.posterInputs?.complete &&
      methods.includes("workspace/posterRun"),
  );
}

/** Dev-mock: a verified poster with a tiny PNG and one pass + one warn row. */
export function mockPosterResult(workspacePath: string, sessionId: string | null): PosterResult {
  const png =
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";
  const pass = {
    checker: "form mtime unchanged",
    state: "ran",
    ok: true,
    hard: [],
    warn: [],
    counts: { hard: 0, warn: 0 },
    name: "form mtime unchanged",
    passed: true,
    detail: "",
  };
  const warn = {
    checker: "pictures >= 1",
    state: "ran",
    ok: true,
    hard: [],
    warn: [{ code: "pictures", msg: "form logo counted" }],
    counts: { hard: 0, warn: 1 },
    name: "pictures >= 1",
    passed: true,
    detail: "pictures=1",
  };
  return {
    workspacePath,
    sessionId,
    state: "warn",
    outputs: [
      {
        role: "pptx",
        path: `${workspacePath}\\poster\\poster_v1.pptx`,
        sha256: "ee".padEnd(64, "0"),
        bytes: 4096,
      },
      {
        role: "png",
        path: `${workspacePath}\\poster\\poster_v1.png`,
        sha256: "ff".padEnd(64, "0"),
        bytes: 70,
      },
    ],
    verify: [pass, warn],
    preview: {
      path: `${workspacePath}\\poster\\poster_v1.png`,
      sha256: "ff".padEnd(64, "0"),
      bytes: 70,
      mediaType: "image/png",
      data: png,
      label: POSTER_PREVIEW_LABEL,
    },
    ok: true,
  };
}

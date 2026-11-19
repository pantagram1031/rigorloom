/**
 * Shell calls that are not in `runtime.ts` (frozen after trust).
 *
 * The 문서 폴더 listing is served by `rt_workspace.register_routes` (WPS) at
 * `GET /api/workspace/list?path=<relative>`; until that module lands the route
 * answers 404 and the 파일 pane leaves the section out rather than guessing.
 */
import * as rt from "../runtime";

export interface WorkspaceEntry {
  name: string;
  /** Path relative to the listing root, `/`-separated. */
  path: string;
  kind: "dir" | "file";
}

export interface WorkspaceListing {
  root: string;
  path: string;
  entries: WorkspaceEntry[];
}

export async function listWorkspace(path = ""): Promise<WorkspaceListing | null> {
  if (rt.isTauri()) return null;
  try {
    const url = `/api/workspace/list${path ? `?path=${encodeURIComponent(path)}` : ""}`;
    const res = await fetch(url, { headers: rt.tokenHeaders() });
    if (!res.ok) return null;
    // rt_workspace (WPS) answers `rootName` and per-entry `relPath`.
    type Raw = { name?: unknown; path?: unknown; relPath?: unknown; kind?: unknown };
    const body = (await res.json()) as { ok?: boolean; root?: unknown; rootName?: unknown; path?: unknown; entries?: Raw[] };
    if (body.ok === false || !Array.isArray(body.entries)) return null;
    const entries: WorkspaceEntry[] = [];
    for (const e of body.entries) {
      const rel = typeof e?.path === "string" ? e.path : typeof e?.relPath === "string" ? e.relPath : null;
      if (!e || typeof e.name !== "string" || rel === null || (e.kind !== "dir" && e.kind !== "file")) continue;
      entries.push({ name: e.name, path: rel, kind: e.kind });
    }
    return {
      root: String(body.root ?? body.rootName ?? ""),
      path: String(body.path ?? path),
      entries,
    };
  } catch {
    return null;
  }
}

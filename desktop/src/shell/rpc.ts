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
    const body = (await res.json()) as Partial<WorkspaceListing> & { ok?: boolean };
    if (body.ok === false || !Array.isArray(body.entries)) return null;
    return {
      root: String(body.root ?? ""),
      path: String(body.path ?? path),
      entries: body.entries.filter(
        (e): e is WorkspaceEntry =>
          Boolean(e) && typeof e.name === "string" && typeof e.path === "string" && (e.kind === "dir" || e.kind === "file"),
      ),
    };
  } catch {
    return null;
  }
}

import { useMemo } from "react";

import { wp3t } from "../i18n/v2/wp3";
import {
  extractDocumentOutline,
  type OutlineNode,
} from "../model/page";
import {
  activeInspect,
  activeSession,
  activeDisplayText,
  useWorkspace,
} from "../store";
import { buildRegionTextMap } from "../workspace/externalPlan";
import { useCanvasChanges } from "../canvas/changes";
import {
  canvas,
  scrollCanvasToTarget,
  setCanvasSlice,
  useCanvasSlice,
} from "../canvas/controller";
import "./panes.css";

export function OutlinePane() {
  const session = useWorkspace(activeSession);
  const inspect = useWorkspace(activeInspect);
  const texts = useWorkspace(activeDisplayText);
  const language = useWorkspace((s) => s.language);
  const slice = useCanvasSlice(session?.sessionId);

  const textMap = useMemo(() => buildRegionTextMap(texts), [texts]);

  const changes = useCanvasChanges(session?.sessionId ?? null, textMap);

  const nodes = useMemo(() => {
    if (!inspect) return [];
    return extractDocumentOutline(inspect, textMap, changes, language);
  }, [inspect, textMap, changes, language]);

  const pageGroups = useMemo(() => {
    const byPage = new Map<number, OutlineNode[]>();
    for (const node of nodes) {
      const list = byPage.get(node.page) ?? [];
      list.push(node);
      byPage.set(node.page, list);
    }
    return [...byPage.entries()].sort((a, b) => a[0] - b[0]);
  }, [nodes]);

  const handleSelectNode = (node: OutlineNode) => {
    if (node.itemIds.length > 0) {
      canvas.select(node.itemIds[0], { fromCanvas: false });
    }
    if (node.cellKey) {
      setCanvasSlice({ selectedSeatKey: node.cellKey });
    }
    const atPara = node.address?.startsWith("p")
      ? Number(node.address.slice(1))
      : null;
    scrollCanvasToTarget({
      itemId: node.itemIds[0] ?? null,
      cellKey: node.cellKey ?? null,
      atPara: Number.isFinite(atPara) ? atPara : null,
    });
  };

  return (
    <section
      className="rl-pane rl-pane--outline"
      data-testid="pane-outline"
      data-docked="true"
      aria-label={wp3t("pane_outline_title", language)}
    >
      {nodes.length === 0 ? (
        <div className="rl-pane-empty" data-testid="outline-empty">
          {wp3t("outline_empty", language)}
        </div>
      ) : (
        <div className="rl-pane-scroll">
          {pageGroups.map(([pageNum, groupNodes]) => {
            const groupChangeCount = new Set(groupNodes.flatMap((n) => n.itemIds)).size;
            return (
              <div key={pageNum} className="rl-outline-page-group">
                <div className="rl-pane-group-hdr rl-num">
                  {groupChangeCount > 0
                    ? wp3t("outline_page_header_count", language, [
                        pageNum,
                        groupChangeCount,
                      ])
                    : wp3t("outline_page_header", language, [pageNum])}
                </div>
                <ul className="rl-outline-list" role="list">
                  {groupNodes.map((node) => {
                    const isActive =
                      (slice.selectedChangeId !== null &&
                        node.itemIds.includes(slice.selectedChangeId)) ||
                      (slice.selectedSeatKey !== null &&
                        node.cellKey === slice.selectedSeatKey);

                    return (
                      <li key={node.id} className="rl-outline-row">
                        <button
                          type="button"
                          className={`rl-outline-btn rl-outline-btn--d${node.depth}${
                            isActive ? " rl-outline-btn--active" : ""
                          }`}
                          data-testid={`outline-node-${node.id}`}
                          data-active={isActive ? "true" : undefined}
                          onClick={() => handleSelectNode(node)}
                        >
                          <span className="rl-outline-title">{node.title}</span>
                          <span className="rl-outline-meta">
                            {node.hasFact ? (
                              <span
                                className="rl-outline-dot rl-outline-dot--fact"
                                data-fact="true"
                                title={wp3t("mark_fact_changed", language)}
                                aria-label={wp3t("mark_fact_changed", language)}
                              />
                            ) : null}
                            {node.hasWarning ? (
                              <span
                                className="rl-outline-dot rl-outline-dot--attn"
                                aria-hidden="true"
                              />
                            ) : null}
                            {node.markRange ? (
                              <span
                                className={`rl-outline-range rl-num${
                                  node.allDecided
                                    ? " rl-outline-range--decided"
                                    : " rl-outline-range--pending"
                                }`}
                                data-accent={!node.allDecided ? "true" : undefined}
                              >
                                {node.markRange}
                              </span>
                            ) : null}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

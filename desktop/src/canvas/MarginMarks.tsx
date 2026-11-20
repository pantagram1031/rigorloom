import { wp3t } from "../i18n/v2/wp3";
import type { CanvasChangeRef } from "../model/page";
import type { UiLanguage } from "../types";

export interface MeasuredMarkPos {
  itemId: string;
  topPx: number;
  heightPx: number;
}

export interface MarginGroup {
  id: string;
  items: CanvasChangeRef[];
  label: string;
  topPx: number;
  heightPx: number;
  status: "fact" | "stale" | "test" | "pending" | "rejected" | "accepted";
  isSelected: boolean;
}

export function groupMeasuredMarks(
  changes: readonly CanvasChangeRef[],
  positions: ReadonlyMap<string, MeasuredMarkPos>,
  selectedChangeId: string | null,
  zoom: number,
): MarginGroup[] {
  const entries: Array<{ item: CanvasChangeRef; topPx: number; heightPx: number }> = [];
  for (const ch of changes) {
    const pos = positions.get(ch.id);
    if (!pos) continue;
    entries.push({
      item: ch,
      topPx: pos.topPx * zoom,
      heightPx: Math.max(18, pos.heightPx * zoom),
    });
  }
  entries.sort((a, b) => a.topPx - b.topPx || a.item.n - b.item.n);

  const clusters: Array<{
    items: CanvasChangeRef[];
    topPx: number;
    bottomPx: number;
  }> = [];

  for (const entry of entries) {
    const prev = clusters[clusters.length - 1];
    if (prev && Math.abs(entry.topPx - prev.topPx) <= 10 * zoom) {
      prev.items.push(entry.item);
      prev.bottomPx = Math.max(prev.bottomPx, entry.topPx + entry.heightPx);
    } else {
      clusters.push({
        items: [entry.item],
        topPx: entry.topPx,
        bottomPx: entry.topPx + entry.heightPx,
      });
    }
  }

  // Prevent badge overlap when adjacent clusters sit very close vertically.
  let lastBottom = -Infinity;
  const groups: MarginGroup[] = [];

  for (const cluster of clusters) {
    const sorted = [...cluster.items].sort((a, b) => a.n - b.n);
    const first = sorted[0];
    const last = sorted[sorted.length - 1];
    const isContiguous = last.n - first.n + 1 === sorted.length;
    const label =
      sorted.length === 1
        ? String(first.n)
        : isContiguous
          ? `${first.n}–${last.n}`
          : sorted.map((c) => c.n).join(",");

    const hasFact = sorted.some((c) => c.isFactChanged);
    const hasStale = sorted.some((c) => c.isStale);
    const hasTest = sorted.some((c) => c.source === "test");
    const hasPending = sorted.some((c) => c.decision === "pending");
    const allRejected = sorted.every((c) => c.decision === "rejected");

    const status: MarginGroup["status"] = hasFact
      ? "fact"
      : hasStale
        ? "stale"
        : hasTest
          ? "test"
          : hasPending
            ? "pending"
            : allRejected
              ? "rejected"
              : "accepted";

    const adjustedTop = Math.max(cluster.topPx, lastBottom + 2);
    const heightPx = Math.max(18, cluster.bottomPx - cluster.topPx);
    lastBottom = adjustedTop + 18;

    groups.push({
      id: `mg-${first.n}`,
      items: sorted,
      label,
      topPx: adjustedTop,
      heightPx,
      status,
      isSelected: sorted.some((c) => c.id === selectedChangeId),
    });
  }

  return groups;
}

export interface MarginMarksProps {
  changes: readonly CanvasChangeRef[];
  positions: ReadonlyMap<string, MeasuredMarkPos>;
  selectedChangeId: string | null;
  zoom: number;
  gutterWidthPx: number;
  drying?: boolean;
  language: UiLanguage;
  onSelect: (itemId: string) => void;
}

export function MarginMarks({
  changes,
  positions,
  selectedChangeId,
  zoom,
  gutterWidthPx,
  drying = false,
  language,
  onSelect,
}: MarginMarksProps) {
  const groups = groupMeasuredMarks(changes, positions, selectedChangeId, zoom);
  if (groups.length === 0) return null;

  return (
    <div
      className={`rl-margin-layer${drying ? " rl-margin-layer--drying" : ""}`}
      data-testid="margin-marks"
      style={{ width: `${Math.max(44, gutterWidthPx)}px` }}
      aria-hidden={false}
    >
      {groups.map((grp) => {
        const first = grp.items[0];
        const sourceAttr =
          grp.status === "pending"
            ? "agent"
            : grp.status === "test"
              ? "test"
              : undefined;
        return (
          <button
            key={grp.id}
            type="button"
            className={`rl-margin-mark rl-margin-mark--${grp.status}${
              grp.isSelected ? " rl-margin-mark--selected" : ""
            }`}
            style={{
              top: `${grp.topPx}px`,
              height: `${grp.heightPx}px`,
            }}
            data-testid={`mark-${first.n}`}
            data-mark-ids={grp.items.map((i) => i.id).join(" ")}
            data-mark-range={grp.label}
            data-selected={grp.isSelected ? "true" : undefined}
            data-fact={grp.status === "fact" ? "true" : undefined}
            data-source={sourceAttr}
            aria-pressed={grp.isSelected}
            aria-label={wp3t("margin_mark_aria", language, [grp.label])}
            onClick={(e) => {
              e.stopPropagation();
              onSelect(first.id);
            }}
          >
            <span className="rl-margin-num">{grp.label}</span>
            <span className="rl-margin-bar" aria-hidden="true" />
          </button>
        );
      })}
    </div>
  );
}

import { wp3t } from "../i18n/v2/wp3";
import type { CanvasChangeRef } from "../model/page";
import type { UiLanguage } from "../types";

export interface ScrollMapTick {
  item: CanvasChangeRef;
  topPct: number;
}

export interface ScrollMapProps {
  ticks: readonly ScrollMapTick[];
  selectedChangeId: string | null;
  thumbTopPct: number;
  thumbHeightPct: number;
  language: UiLanguage;
  onSelect: (itemId: string) => void;
}

export function ScrollMap({
  ticks,
  selectedChangeId,
  thumbTopPct,
  thumbHeightPct,
  language,
  onSelect,
}: ScrollMapProps) {
  if (ticks.length === 0) return null;

  return (
    <div
      className="rl-scrollmap"
      data-testid="scroll-map"
      aria-label={wp3t("scrollmap_aria_label", language)}
    >
      <div
        className="rl-scrollmap-thumb"
        style={{
          top: `${Math.max(0, Math.min(95, thumbTopPct))}%`,
          height: `${Math.max(8, Math.min(100, thumbHeightPct))}%`,
        }}
        aria-hidden="true"
      />
      {ticks.map(({ item, topPct }) => {
        const isSelected = item.id === selectedChangeId;
        const kind = item.isFactChanged
          ? "fact"
          : item.isStale || item.source === "test"
            ? "attn"
            : item.decision === "pending"
              ? "pending"
              : "decided";

        return (
          <button
            key={item.id}
            type="button"
            className={`rl-scrollmap-tick rl-scrollmap-tick--${kind}${
              isSelected ? " rl-scrollmap-tick--selected" : ""
            }`}
            style={{ top: `${Math.max(1, Math.min(98, topPct))}%` }}
            data-testid={`scrollmap-tick-${item.n}`}
            data-fact={kind === "fact" ? "true" : undefined}
            data-source={kind === "pending" ? "agent" : undefined}
            aria-label={wp3t("margin_mark_aria", language, [item.n])}
            onClick={(e) => {
              e.stopPropagation();
              onSelect(item.id);
            }}
          />
        );
      })}
    </div>
  );
}

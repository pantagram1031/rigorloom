import type { CSSProperties } from "react";
import type { CanvasChangeRef } from "../model/page";

export function ReviewMark({ change, zoom, selected }: {
  change: CanvasChangeRef;
  zoom: number;
  selected: boolean;
}) {
  return (
    <span className="rl-review-mark" data-fact={change.isFactChanged || undefined}
      data-selected={selected || undefined} data-decision={change.decision}
      style={{ "--review-pixel": `${1 / zoom}px` } as CSSProperties} aria-hidden="true" />
  );
}

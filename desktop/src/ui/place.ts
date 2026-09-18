export type LayerSide = "top" | "bottom" | "left" | "right";
export type LayerAlign = "start" | "center" | "end";

export type Box = {
  top: number;
  left: number;
  bottom: number;
  right: number;
  width: number;
  height: number;
};

const MARGIN = 8;

const OPPOSITE: Record<LayerSide, LayerSide> = {
  top: "bottom",
  bottom: "top",
  left: "right",
  right: "left",
};

/**
 * Position a layer next to a trigger. Flips to the opposite side on overflow,
 * then clamps within the viewport with an 8 px margin, for all four sides.
 * `gap` is the air between them.
 */
export function placeLayer(
  trigger: Box,
  layer: { width: number; height: number },
  side: LayerSide,
  align: LayerAlign = "center",
  gap = 8,
  viewport = { width: 1280, height: 800 },
): { top: number; left: number; side: LayerSide } {
  let next: LayerSide = side;
  let top = 0;
  let left = 0;

  const along = (start: number, size: number, span: number) => {
    if (align === "start") return start;
    if (align === "end") return start + size - span;
    return start + (size - span) / 2;
  };

  const place = (s: LayerSide) => {
    if (s === "top") {
      top = trigger.top - layer.height - gap;
      left = along(trigger.left, trigger.width, layer.width);
    } else if (s === "bottom") {
      top = trigger.bottom + gap;
      left = along(trigger.left, trigger.width, layer.width);
    } else if (s === "left") {
      left = trigger.left - layer.width - gap;
      top = along(trigger.top, trigger.height, layer.height);
    } else {
      left = trigger.right + gap;
      top = along(trigger.top, trigger.height, layer.height);
    }
  };

  const overflows = (s: LayerSide) => {
    place(s);
    if (s === "top") return top < MARGIN;
    if (s === "bottom") return top + layer.height > viewport.height - MARGIN;
    if (s === "left") return left < MARGIN;
    return left + layer.width > viewport.width - MARGIN;
  };

  if (overflows(next)) {
    next = OPPOSITE[next];
    place(next);
  }

  left = Math.min(Math.max(MARGIN, left), Math.max(MARGIN, viewport.width - layer.width - MARGIN));
  top = Math.min(Math.max(MARGIN, top), Math.max(MARGIN, viewport.height - layer.height - MARGIN));
  return { top, left, side: next };
}

/** Inline style for a portaled layer so leftover absolute `bottom`/`right` cannot clip it. */
export function layerFixedStyle(coords: { top: number; left: number }): {
  position: "fixed";
  top: number;
  left: number;
  right: "auto";
  bottom: "auto";
} {
  return {
    position: "fixed",
    top: coords.top,
    left: coords.left,
    right: "auto",
    bottom: "auto",
  };
}

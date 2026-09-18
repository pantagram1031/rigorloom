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

/**
 * Position a layer next to a trigger. Flips on overflow so the layer never
 * covers the trigger's box. `gap` is the air between them.
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

  place(next);
  if (next === "top" && top < 8) {
    next = "bottom";
    place(next);
  } else if (next === "bottom" && top + layer.height > viewport.height - 8) {
    next = "top";
    place(next);
  } else if (next === "left" && left < 8) {
    next = "right";
    place(next);
  } else if (next === "right" && left + layer.width > viewport.width - 8) {
    next = "left";
    place(next);
  }

  left = Math.min(Math.max(8, left), Math.max(8, viewport.width - layer.width - 8));
  top = Math.min(Math.max(8, top), Math.max(8, viewport.height - layer.height - 8));
  return { top, left, side: next };
}

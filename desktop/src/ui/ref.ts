import type { ForwardedRef, MutableRefObject, RefObject } from "react";

export type SlotRef<T> = MutableRefObject<T | null>;

export function assignRef<T>(
  ref: ForwardedRef<T> | RefObject<T | null> | SlotRef<T> | null | undefined,
  value: T | null,
): void {
  if (!ref) return;
  if (typeof ref === "function") {
    ref(value);
    return;
  }
  (ref as SlotRef<T>).current = value;
}

export function mergeRefs(...refs: unknown[]) {
  return (value: HTMLElement | null) => {
    for (const ref of refs) assignRef(ref as ForwardedRef<HTMLElement>, value);
  };
}

import { useEffect, useRef, useState } from "react";

import { TABBABLE, trapTabIndex } from "./roving";
import type { SlotRef } from "./ref";

export function useOpenState(
  open: boolean | undefined,
  defaultOpen: boolean,
  onOpenChange?: (next: boolean) => void,
): [boolean, (next: boolean) => void] {
  const [uncontrolled, setUncontrolled] = useState(defaultOpen);
  const controlled = open !== undefined;
  const value = controlled ? open : uncontrolled;
  const set = (next: boolean) => {
    if (!controlled) setUncontrolled(next);
    onOpenChange?.(next);
  };
  return [value, set];
}

export type LayerOpts = {
  open: boolean;
  onClose: () => void;
  triggerRef: SlotRef<HTMLElement>;
  contentRef: SlotRef<HTMLElement>;
  /** Modal: trap focus + lock scroll. Non-modal: outside click closes. */
  modal?: boolean;
};

/**
 * Outside-click / Esc / focus return for floating layers.
 * Modal layers also trap Tab and lock body scroll.
 */
export function useLayer({
  open,
  onClose,
  triggerRef,
  contentRef,
  modal = false,
}: LayerOpts): void {
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const prevFocus = useRef<HTMLElement | null>(null);
  const wasOpen = useRef(false);

  useEffect(() => {
    if (!open) return;
    prevFocus.current = (typeof document !== "undefined" ? document.activeElement : null) as HTMLElement | null;
    const root = contentRef.current;
    if (root) {
      const first = root.querySelector<HTMLElement>(TABBABLE);
      (first ?? root).focus();
    }
    if (!modal || typeof document === "undefined") return;
    const body = document.body;
    const prevOverflow = body.style.overflow;
    body.style.overflow = "hidden";
    return () => {
      body.style.overflow = prevOverflow;
    };
  }, [open, modal, contentRef]);

  useEffect(() => {
    if (!open || typeof document === "undefined") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (!modal || e.key !== "Tab") return;
      const root = contentRef.current;
      if (!root) return;
      const list = Array.from(root.querySelectorAll<HTMLElement>(TABBABLE)).filter(
        (el) => !el.hasAttribute("disabled"),
      );
      const index = list.indexOf(document.activeElement as HTMLElement);
      const trapped = trapTabIndex(list.length, index, e.shiftKey);
      if (trapped === null) return;
      e.preventDefault();
      list[trapped]?.focus();
    };
    const onPointer = (e: MouseEvent) => {
      if (modal) return;
      const t = e.target as Node | null;
      if (!t) return;
      if (contentRef.current?.contains(t)) return;
      if (triggerRef.current?.contains(t)) return;
      onCloseRef.current();
    };
    document.addEventListener("keydown", onKey, true);
    const listenId = window.setTimeout(() => {
      document.addEventListener("mousedown", onPointer);
    }, 0);
    return () => {
      window.clearTimeout(listenId);
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("mousedown", onPointer);
    };
  }, [open, modal, contentRef, triggerRef]);

  useEffect(() => {
    if (open) {
      wasOpen.current = true;
      return;
    }
    if (!wasOpen.current) return;
    wasOpen.current = false;
    const el = prevFocus.current ?? triggerRef.current;
    el?.focus?.();
  }, [open, triggerRef]);
}

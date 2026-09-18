import type { ReactNode } from "react";
import { createPortal } from "react-dom";

/** Mount floating layers on document.body (or an explicit container). */
export function Portal({
  children,
  container,
  disabled,
}: {
  children: ReactNode;
  container?: Element | null;
  disabled?: boolean;
}) {
  if (disabled) return <>{children}</>;
  if (typeof document === "undefined") return <>{children}</>;
  return createPortal(children, container ?? document.body);
}

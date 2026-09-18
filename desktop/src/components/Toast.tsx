/**
 * Small top-right confirmations. Errors stay until closed; the rest fade at 4 s.
 * Hashes never appear here.
 */
import { Toast as KitToast, ToastViewport } from "../ui/Toast";
import { dismissToast, useWorkspace } from "../store";

export function Toast() {
  const toasts = useWorkspace((s) => s.toasts);
  if (toasts.length === 0) return null;
  return (
    <ToastViewport className="toast-stack" data-testid="toast-stack">
      {toasts.map((toast) => (
        <KitToast
          key={toast.id}
          variant={toast.sticky ? "destructive" : "default"}
          data-testid="toast"
          data-sticky={toast.sticky ? "true" : "false"}
          onClose={toast.sticky ? () => dismissToast(toast.id) : undefined}
        >
          {toast.text}
        </KitToast>
      ))}
    </ToastViewport>
  );
}

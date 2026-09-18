/**
 * Small top-right confirmations. Errors stay until closed; the rest fade at 4 s.
 */
import { dismissToast, useWorkspace } from "../store";

export function Toast() {
  const toasts = useWorkspace((s) => s.toasts);
  if (toasts.length === 0) return null;
  return (
    <div className="toast-stack" data-testid="toast-stack">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`toast${toast.sticky ? " is-error" : ""}`}
          role={toast.sticky ? "alert" : "status"}
          aria-live={toast.sticky ? "assertive" : "polite"}
          data-testid="toast"
          data-sticky={toast.sticky ? "true" : "false"}
        >
          <span>{toast.text}</span>
          {toast.sticky ? (
            <button
              type="button"
              className="toast-close"
              data-testid={`toast-close-${toast.id}`}
              aria-label="닫기"
              onClick={() => dismissToast(toast.id)}
            >
              ×
            </button>
          ) : null}
        </div>
      ))}
    </div>
  );
}

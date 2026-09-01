/**
 * A transient confirmation, for changes that are visible everywhere and so
 * need no permanent chrome — the UI zoom level being the only current caller.
 */
import { useWorkspace } from "../store";

export function Toast() {
  const toast = useWorkspace((s) => s.toast);
  if (!toast) return null;
  return (
    <div className="toast" role="status" aria-live="polite" data-testid="toast">
      {toast.text}
    </div>
  );
}

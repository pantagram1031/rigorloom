import { Component, type ReactNode, useSyncExternalStore } from "react";

import { useWorkspace } from "../store";
import { S } from "../i18n/v2/shell";
import {
  type SlotName,
  slotEntries,
  slotsVersion,
  subscribeSlots,
} from "./slots";

/** Re-render when any registration changes. */
export function useSlotsVersion(): number {
  return useSyncExternalStore(subscribeSlots, slotsVersion, slotsVersion);
}

class SlotBoundary extends Component<{ name: string; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: unknown) {
    // One package failing must not take the shell down with it.
    console.error(`slot ${this.props.name} failed`, error);
  }
  render() {
    if (this.state.failed) return <SlotFailed name={this.props.name} />;
    return this.props.children;
  }
}

function SlotFailed({ name }: { name: string }) {
  const lang = useWorkspace((s) => s.language);
  return (
    <div className="sh-slot-empty" data-testid={`slot-failed-${name}`} data-slot-failed={name}>
      {S.t("shell_slot_failed", lang)}
    </div>
  );
}

/**
 * Render a slot's entries. With nothing registered, renders `fallback` if
 * given, else a quiet placeholder carrying `data-slot-empty` for tests.
 */
export function Slot({
  name,
  sessionId,
  fallback,
  quiet = false,
}: {
  name: SlotName;
  sessionId: string | null;
  fallback?: ReactNode;
  /** Render nothing at all when empty (status bar, strip ends). */
  quiet?: boolean;
}) {
  useSlotsVersion();
  const entries = slotEntries(name).filter((e) => !e.when || e.when(sessionId));
  if (entries.length === 0) {
    if (fallback !== undefined) return <>{fallback}</>;
    if (quiet) return null;
    return <div className="sh-slot-empty" data-slot-empty={name} data-testid={`slot-empty-${name.replace(":", "-")}`} />;
  }
  return (
    <>
      {entries.map((entry) => {
        const C = entry.component;
        return (
          <SlotBoundary key={entry.seq} name={name}>
            <C sessionId={sessionId} />
          </SlotBoundary>
        );
      })}
    </>
  );
}

/**
 * Shared semantic data attributes and IME composition guard for v2 UI primitives
 * (J1 §4, §5; ADVISOR-RULING §D).
 */

/** Button visual hierarchy. At most one visible `primary` button may appear per window. */
export type DataVariant = "primary" | "outline" | "ghost";

/** Proposal / change provenance exposed on rows, tags, and marks. */
export type DataSource = "agent" | "user" | "test" | "revert";

export interface PrincipleDataProps {
  /** Emits `data-variant` (`primary` | `outline` | `ghost`). */
  variant?: DataVariant;
  /** Emits `data-docked=""` on non-floating regions (enforces zero box-shadow). */
  docked?: boolean;
  /** Emits `data-floating=""` on elevated overlays (`Menu`, `Popover`, `Tooltip`, modal `Sheet`). */
  floating?: boolean;
  /** Emits `data-fact=""` (only scope permitted to render `--fact` crimson). */
  fact?: boolean;
  /** Emits `data-source` (`agent` | `user` | `test` | `revert`). */
  source?: DataSource;
  /** Emits `data-accent=""` on tab count badges permitted to use `--accent`. */
  accent?: boolean;
}

export interface PrincipleDataAttributes {
  "data-variant"?: DataVariant;
  "data-docked"?: "";
  "data-floating"?: "";
  "data-fact"?: "";
  "data-source"?: DataSource;
  "data-accent"?: "";
}

/** Build canonical `data-*` attributes without leaking `"false"` strings into the DOM. */
export function principleAttributes(props: PrincipleDataProps): PrincipleDataAttributes {
  const attrs: PrincipleDataAttributes = {};
  if (props.variant) attrs["data-variant"] = props.variant;
  if (props.docked) attrs["data-docked"] = "";
  if (props.floating) attrs["data-floating"] = "";
  if (props.fact) attrs["data-fact"] = "";
  if (props.source) attrs["data-source"] = props.source;
  if (props.accent) attrs["data-accent"] = "";
  return attrs;
}

export interface ComposingLikeEvent {
  isComposing?: boolean;
  keyCode?: number;
  key?: string;
  nativeEvent?: {
    isComposing?: boolean;
    keyCode?: number;
    key?: string;
  };
}

/**
 * Returns true when an IME composition session is active (Hangul syllable assembly).
 * All interactive UI primitives ignore navigation/action keys while composing.
 */
export function isImeComposing(event: ComposingLikeEvent | null | undefined): boolean {
  if (!event) return false;
  const native = event.nativeEvent;
  return Boolean(
    event.isComposing ||
      native?.isComposing ||
      event.keyCode === 229 ||
      native?.keyCode === 229 ||
      event.key === "Process" ||
      native?.key === "Process",
  );
}

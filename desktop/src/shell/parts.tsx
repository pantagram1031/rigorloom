/**
 * Small shell-local pieces. Replaced by WP1b's `ui/*` primitives when they land;
 * the attributes (`data-variant`) already follow the primitives' contract.
 */
import type { ReactNode } from "react";
import { plainName } from "./names";

import { chordCaps } from "./keys";
import { useKeyHint } from "./keys";

export function Keycaps({ caps, className = "" }: { caps: string[] | null; className?: string }) {
  if (!caps || caps.length === 0) return null;
  return (
    <span className={`sh-keys ${className}`.trim()} aria-hidden="true">
      {caps.map((c, i) => (c === " " ? <span key={i} className="sh-keys-gap" /> : <kbd key={i} className="sh-key">{c}</kbd>))}
    </span>
  );
}

export function KeyHint({ id, className }: { id: string; className?: string }) {
  const caps = useKeyHint(id);
  return <Keycaps caps={caps} className={className} />;
}

export function ChordHint({ chord }: { chord: string }) {
  return <Keycaps caps={chordCaps(chord)} />;
}

type IconName = "close" | "chevronDown" | "paneLeft" | "paneRight" | "minimize" | "maximize" | "more" | "search";

/** 16 px glyphs, 1 px stroke on pixel centres, square caps (D1 §5 Iconography). */
export function Icon({ name, size = 16 }: { name: IconName; size?: number }) {
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 16 16",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1,
    strokeLinecap: "square" as const,
    strokeLinejoin: "miter" as const,
    "aria-hidden": true,
    focusable: false,
  };
  switch (name) {
    case "search":
      return <svg {...common}><circle cx="7" cy="7" r="4" /><path d="m10 10 3.5 3.5" /></svg>;
    case "close":
      return (
        <svg {...common}>
          <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" />
        </svg>
      );
    case "chevronDown":
      return (
        <svg {...common}>
          <path d="M4.5 6.5l3.5 3.5 3.5-3.5" />
        </svg>
      );
    case "paneLeft":
      return (
        <svg {...common}>
          <rect x="2.5" y="3.5" width="11" height="9" />
          <path d="M6.5 3.5v9" />
        </svg>
      );
    case "paneRight":
      return (
        <svg {...common}>
          <rect x="2.5" y="3.5" width="11" height="9" />
          <path d="M9.5 3.5v9" />
        </svg>
      );
    case "minimize":
      return (
        <svg {...common}>
          <path d="M3.5 8.5h9" />
        </svg>
      );
    case "maximize":
      return (
        <svg {...common}>
          <rect x="3.5" y="3.5" width="9" height="9" />
        </svg>
      );
    case "more":
      return (
        <svg {...common}>
          <path d="M3.5 8h1M7.5 8h1M11.5 8h1" />
        </svg>
      );
  }
}

/** A text button. `primary` is the one ink fill a window may carry. */
export function Btn({
  children,
  variant = "outline",
  onClick,
  disabled,
  testId,
  title,
  className = "",
}: {
  children: ReactNode;
  variant?: "primary" | "outline" | "quiet";
  onClick?: () => void;
  disabled?: boolean;
  testId?: string;
  title?: string;
  className?: string;
}) {
  return (
    <button
      type="button"
      className={`sh-btn sh-btn--${variant} ${className}`.trim()}
      data-variant={variant}
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
      title={title}
    >
      {children}
    </button>
  );
}

/** File name with the extension dimmed (J1 §3 IA: tabs). */
/** A file name, without bidi controls and isolated from the text around it. */
export function FileName({ name: raw }: { name: string }) {
  const name = plainName(raw);
  const dot = name.lastIndexOf(".");
  if (dot <= 0 || dot < name.length - 6) {
    return (
      <bdi className="sh-fname">{name}</bdi>
    );
  }
  return (
    <bdi className="sh-fname">
      {name.slice(0, dot)}
      <span className="sh-fname-ext">{name.slice(dot)}</span>
    </bdi>
  );
}

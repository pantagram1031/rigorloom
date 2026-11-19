import type { JSX, SVGProps } from "react";

export const ICON_NAMES = [
  "panelLeft",
  "panelRight",
  "winMinimize",
  "winMaximize",
  "winRestore",
  "winClose",
  "plus",
  "close",
  "chevronDown",
  "chevronUp",
  "chevronRight",
  "chevronLeft",
  "moreHorizontal",
  "search",
  "folder",
  "folderOpen",
  "fileDoc",
  "outline",
  "blanks",
  "history",
  "settings",
  "copy",
  "check",
  "arrowUpRight",
  "returnArrow",
  "zoomIn",
  "zoomOut",
  "dot",
] as const;

export type IconName = (typeof ICON_NAMES)[number];

export interface IconProps extends Omit<SVGProps<SVGSVGElement>, "name"> {
  name: IconName;
  /** 16 px (1 px stroke on pixel centers) or 20 px touch variant (1.25 px stroke). */
  size?: 16 | 20 | number;
  label?: string;
}

function renderGlyph(name: IconName): JSX.Element {
  switch (name) {
    case "panelLeft":
      return (
        <>
          <rect x={2.5} y={2.5} width={11} height={11} />
          <path d="M6.5 2.5V13.5" />
        </>
      );
    case "panelRight":
      return (
        <>
          <rect x={2.5} y={2.5} width={11} height={11} />
          <path d="M9.5 2.5V13.5" />
        </>
      );
    case "winMinimize":
      return <path d="M3.5 8.5H12.5" />;
    case "winMaximize":
      return <rect x={3.5} y={3.5} width={9} height={9} />;
    case "winRestore":
      return (
        <>
          <rect x={3.5} y={5.5} width={7} height={7} />
          <path d="M5.5 5.5V3.5H12.5V10.5H10.5" />
        </>
      );
    case "winClose":
      return <path d="M4 4L12 12M12 4L4 12" />;
    case "plus":
      return <path d="M8.5 3.5V13.5M3.5 8.5H13.5" />;
    case "close":
      return <path d="M4.5 4.5L11.5 11.5M11.5 4.5L4.5 11.5" />;
    case "chevronDown":
      return <path d="M4.5 6.5L8 10L11.5 6.5" />;
    case "chevronUp":
      return <path d="M4.5 9.5L8 6L11.5 9.5" />;
    case "chevronRight":
      return <path d="M6.5 4.5L10 8L6.5 11.5" />;
    case "chevronLeft":
      return <path d="M9.5 4.5L6 8L9.5 11.5" />;
    case "moreHorizontal":
      return <path d="M3.5 8.5H4.5M7.5 8.5H8.5M11.5 8.5H12.5" />;
    case "search":
      return (
        <>
          <circle cx={7} cy={7} r={4.5} />
          <path d="M10.5 10.5L13.5 13.5" />
        </>
      );
    case "folder":
      return <path d="M2.5 4.5H6.5L8 6.5H13.5V12.5H2.5Z" />;
    case "folderOpen":
      return (
        <>
          <path d="M2.5 12.5V4.5H6.5L8 6.5H13.5V8.5" />
          <path d="M2.5 12.5L4 8.5H14.5L13 12.5Z" />
        </>
      );
    case "fileDoc":
      return (
        <>
          <rect x={3.5} y={2.5} width={9} height={11} />
          <path d="M5.5 6.5H10.5M5.5 9.5H9.5" />
        </>
      );
    case "outline":
      return <path d="M2.5 4.5H13.5M5.5 8.5H13.5M5.5 12.5H11.5M2.5 8.5H3.5M2.5 12.5H3.5" />;
    case "blanks":
      return (
        <>
          <rect x={2.5} y={3.5} width={11} height={9} />
          <path d="M2.5 7.5H13.5M7.5 3.5V12.5" />
        </>
      );
    case "history":
      return (
        <>
          <path d="M4.5 2.5V13.5" />
          <rect x={3.5} y={3.5} width={2} height={2} />
          <rect x={3.5} y={9.5} width={2} height={2} />
          <path d="M7.5 4.5H13.5M7.5 10.5H12.5" />
        </>
      );
    case "settings":
      return (
        <>
          <path d="M2.5 5.5H13.5M2.5 10.5H13.5" />
          <rect x={5.5} y={4} width={2} height={3} />
          <rect x={9.5} y={9} width={2} height={3} />
        </>
      );
    case "copy":
      return (
        <>
          <rect x={5.5} y={5.5} width={8} height={8} />
          <path d="M3.5 10.5H2.5V2.5H10.5V3.5" />
        </>
      );
    case "check":
      return <path d="M3.5 8.5L6.5 11.5L12.5 4.5" />;
    case "arrowUpRight":
      return <path d="M5.5 3.5H12.5V10.5M12.5 3.5L4.5 11.5" />;
    case "returnArrow":
      return <path d="M6.5 4.5L3.5 7.5L6.5 10.5M3.5 7.5H11.5V12.5H8.5" />;
    case "zoomIn":
      return (
        <>
          <circle cx={7} cy={7} r={4.5} />
          <path d="M7 5V9M5 7H9M10.5 10.5L13.5 13.5" />
        </>
      );
    case "zoomOut":
      return (
        <>
          <circle cx={7} cy={7} r={4.5} />
          <path d="M5 7H9M10.5 10.5L13.5 13.5" />
        </>
      );
    case "dot":
      return <circle cx={8} cy={8} r={3} fill="currentColor" stroke="none" />;
  }
}

/**
 * 16 px hairline icon set (D1 §5 Iconography).
 *
 * 1 px stroke on pixel centers, square caps, miter joins, no fills except `dot`.
 * At `size={20}` (touch), stroke scales proportionally (`vectorEffect` off,
 * `strokeWidth={1}` on 16 viewBox -> exact 1.25 px rendered stroke at 20 px).
 */
export function Icon({ name, size = 16, label, className = "", ...rest }: IconProps) {
  const isDecorative = !label;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1}
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={`rl-icon ${className}`.trim()}
      data-icon={name}
      role={isDecorative ? undefined : "img"}
      aria-label={label}
      aria-hidden={isDecorative ? true : undefined}
      {...rest}
    >
      {renderGlyph(name)}
    </svg>
  );
}

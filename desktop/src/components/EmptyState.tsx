/**
 * Designed empty: icon, one title, one sentence, one optional action.
 * Never a grey prose wall, and never a raw object as a child.
 */
import type { ReactNode } from "react";

import { labelOf } from "../label";

export function EmptyState({
  icon,
  title,
  body,
  action,
  testId,
}: {
  icon?: ReactNode;
  title: string;
  body: string;
  action?: { label: string; onClick: () => void };
  testId?: string;
}) {
  return (
    <div className="empty-state" data-testid={testId}>
      {icon ? (
        <div className="empty-state-icon" aria-hidden="true">
          {icon}
        </div>
      ) : null}
      <p className="empty-state-title">{labelOf(title)}</p>
      <p className="empty-state-body">{labelOf(body)}</p>
      {action ? (
        <button type="button" className="action" onClick={action.onClick}>
          {labelOf(action.label)}
        </button>
      ) : null}
    </div>
  );
}

export function EmptyIconInbox() {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="M4 8.5h20v13H4z" />
      <path d="M4 8.5 14 15l10-6.5" />
    </svg>
  );
}

export function EmptyIconChat() {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="M6 7h16v11H11l-5 3.5V7z" />
    </svg>
  );
}

export function EmptyIconHistory() {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" fill="none" stroke="currentColor" strokeWidth="1.6">
      <circle cx="14" cy="15" r="8" />
      <path d="M14 11v4.5l3 2" />
      <path d="M9 6.5 7 8.5" />
    </svg>
  );
}

export function EmptyIconDoc() {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="M8 5h8l5 5v13H8z" />
      <path d="M16 5v5h5" />
    </svg>
  );
}

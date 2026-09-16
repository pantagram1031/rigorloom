/**
 * Designed empty: icon, one title, one sentence, one optional action.
 * Never a grey prose wall, and never a raw object as a child.
 */
import type { ReactNode } from "react";

import { labelOf } from "../label";
import { Icon } from "./Icon";

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
  return <Icon name="list" size={20} />;
}

export function EmptyIconChat() {
  return <Icon name="bot" size={20} />;
}

export function EmptyIconHistory() {
  return <Icon name="history" size={20} />;
}

export function EmptyIconDoc() {
  return <Icon name="open" size={20} />;
}

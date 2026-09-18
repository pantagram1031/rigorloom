/**
 * Designed empty: icon, one title, one sentence, one optional action.
 * Never a grey prose wall, and never a raw object as a child.
 */
import type { ReactNode } from "react";

import { labelOf } from "../label";
import { EmptyState as KitEmpty } from "../ui/EmptyState";
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
    <KitEmpty
      className="empty-state"
      icon={icon}
      title={labelOf(title)}
      body={labelOf(body)}
      action={
        action
          ? { label: labelOf(action.label), onClick: action.onClick }
          : undefined
      }
      testId={testId}
    />
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

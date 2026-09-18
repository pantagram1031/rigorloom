import type { ReactNode } from "react";

import { cn } from "./cn";
import { Button } from "./Button";

export function EmptyState({
  icon,
  title,
  body,
  action,
  testId,
  className,
}: {
  icon?: ReactNode;
  title: string;
  body: string;
  action?: { label: string; onClick: () => void };
  testId?: string;
  className?: string;
}) {
  return (
    <div className={cn(className, "ui-empty")} data-testid={testId}>
      {icon ? (
        <div className="ui-empty-icon" aria-hidden="true">
          {icon}
        </div>
      ) : null}
      <p className="ui-empty-title">{title}</p>
      <p className="ui-empty-body">{body}</p>
      {action ? (
        <Button variant="secondary" onClick={action.onClick}>
          {action.label}
        </Button>
      ) : null}
    </div>
  );
}

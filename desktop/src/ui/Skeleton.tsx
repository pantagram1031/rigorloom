import { cn } from "./cn";

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("ui-skeleton", className)} aria-hidden="true" />;
}

/** Quiet placeholders while content is in flight. Adopted from the app skeleton. */
export function SkeletonRows({
  rows = 7,
  testId,
}: {
  rows?: number;
  testId?: string;
}) {
  return (
    <div className="ui-skeleton-list" data-testid={testId} aria-hidden="true">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="ui-skeleton-row" />
      ))}
    </div>
  );
}

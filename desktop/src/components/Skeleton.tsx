/** Quiet placeholders while open/inspect are in flight. No spinner text. */
export function SkeletonRows({
  rows = 7,
  testId,
}: {
  rows?: number;
  testId?: string;
}) {
  return (
    <div className="skeleton-list" data-testid={testId} aria-hidden="true">
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          className="skeleton-row"
          style={{ width: `${84 - (i % 4) * 12}%` }}
        />
      ))}
    </div>
  );
}

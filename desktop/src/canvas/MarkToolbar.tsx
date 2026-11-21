import { wp3t } from "../i18n/v2/wp3";
import type { CanvasChangeDecision, CanvasChangeRef } from "../model/page";
import type { UiLanguage } from "../types";

export interface MarkToolbarAnchor {
  topPx: number;
  leftPx: number;
}

export interface MarkToolbarProps {
  item: CanvasChangeRef;
  anchor: MarkToolbarAnchor | null;
  canEdit: boolean;
  language: UiLanguage;
  onDecide: (itemId: string, decision: CanvasChangeDecision) => void;
  onEdit: (item: CanvasChangeRef) => void;
}

export function MarkToolbar({
  item,
  anchor,
  canEdit,
  language,
  onDecide,
  onEdit,
}: MarkToolbarProps) {
  if (!anchor) return null;

  const isStale = Boolean(item.isStale);
  const isRejected = item.decision === "rejected";
  const isAccepted = item.decision === "accepted";

  return (
    <div
      className="rl-mark-toolbar"
      data-testid="mark-toolbar"
      data-item-id={item.id}
      style={{
        top: `${Math.max(4, anchor.topPx)}px`,
        left: `${Math.max(8, anchor.leftPx)}px`,
      }}
      role="toolbar"
      aria-label={item.label}
      onClick={(e) => e.stopPropagation()}
    >
      {isRejected ? (
        <button
          type="button"
          className="rl-mark-btn"
          data-testid="mark-restore" title="U"
          disabled={isStale}
          onClick={() => onDecide(item.id, "pending")}
        >
          <span>{wp3t("mark_restore", language)}</span>
        </button>
      ) : (
        <>
          <button
            type="button"
            className={`rl-mark-btn${isAccepted ? " rl-mark-btn--active" : ""}`}
            data-testid="mark-accept" title="Y"
            disabled={isStale}
            aria-pressed={isAccepted}
            onClick={() => onDecide(item.id, "accepted")}
          >
            <span>{wp3t("mark_accept", language)}</span>
          </button>

          <button
            type="button"
            className="rl-mark-btn"
            data-testid="mark-reject" title="N"
            disabled={isStale}
            onClick={() => onDecide(item.id, "rejected")}
          >
            <span>{wp3t("mark_reject", language)}</span>
          </button>
        </>
      )}

      {canEdit ? (
        <button
          type="button"
          className="rl-mark-btn"
          data-testid="mark-edit" title="E"
          onClick={() => onEdit(item)}
        >
          <span>{wp3t("mark_edit", language)}</span>
        </button>
      ) : null}
    </div>
  );
}

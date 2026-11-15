import type { ReactNode } from "react";
import { t } from "../i18n/vocabulary";
import { useWorkspace } from "../store";

export interface DetailDisclosureProps {
  label?: string;
  children: ReactNode;
  open?: boolean;
  onToggle?: (open: boolean) => void;
  testId?: string;
  inline?: boolean;
}

export function DetailDisclosure({
  label,
  children,
  open,
  onToggle,
  testId,
  inline = false,
}: DetailDisclosureProps) {
  const language = useWorkspace((s) => s.language);
  return (
    <details
      className={inline ? "detail-disclosure detail-disclosure--inline" : "detail-disclosure"}
      open={open}
      data-testid={testId}
      onToggle={
        onToggle
          ? (e) => {
              onToggle(e.currentTarget.open);
            }
          : undefined
      }
    >
      <summary>{label ?? t("detail_label", language)}</summary>
      <div className="detail-disclosure-body">{children}</div>
    </details>
  );
}

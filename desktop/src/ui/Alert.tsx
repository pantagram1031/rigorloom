import { forwardRef, type HTMLAttributes, type ReactNode } from "react";

import { cn } from "./cn";

export type AlertVariant = "info" | "warning" | "destructive";

export type AlertProps = HTMLAttributes<HTMLDivElement> & {
  variant?: AlertVariant;
  title?: ReactNode;
  icon?: ReactNode;
};

export const Alert = forwardRef<HTMLDivElement, AlertProps>(function Alert(
  { variant = "info", title, icon, className, children, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      role="alert"
      data-variant={variant}
      className={cn("ui-alert", `ui-alert-${variant}`, className)}
      {...rest}
    >
      {icon ? (
        <span className="ui-alert-icon" aria-hidden="true">
          {icon}
        </span>
      ) : null}
      <div className="ui-alert-body">
        {title ? <div className="ui-alert-title">{title}</div> : null}
        {children ? <div className="ui-alert-desc">{children}</div> : null}
      </div>
    </div>
  );
});

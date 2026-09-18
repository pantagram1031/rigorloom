import { forwardRef, type HTMLAttributes, type ReactNode } from "react";

import { cn } from "./cn";

export type ItemProps = Omit<HTMLAttributes<HTMLDivElement>, "title"> & {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  trailing?: ReactNode;
  active?: boolean;
};

/** Row with leading icon, title, description, trailing slot. */
export const Item = forwardRef<HTMLDivElement, ItemProps>(function Item(
  { icon, title, description, trailing, active, className, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      className={cn("ui-item", className)}
      data-state={active ? "active" : "idle"}
      {...rest}
    >
      {icon ? (
        <span className="ui-item-icon" aria-hidden="true">
          {icon}
        </span>
      ) : null}
      <span className="ui-item-text">
        <span className="ui-item-title">{title}</span>
        {description ? <span className="ui-item-desc">{description}</span> : null}
      </span>
      {trailing ? <span className="ui-item-trailing">{trailing}</span> : null}
    </div>
  );
});

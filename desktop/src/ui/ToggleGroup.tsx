import {
  createContext,
  forwardRef,
  useContext,
  useMemo,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { cn } from "./cn";
import { mergeRefs } from "./ref";
import { moveRoving } from "./roving";

type ToggleCtx = {
  value: string;
  setValue: (value: string) => void;
  register: (el: HTMLButtonElement | null, value: string) => void;
  items: () => HTMLButtonElement[];
};

const Ctx = createContext<ToggleCtx | null>(null);

function useToggle(): ToggleCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("ToggleGroupItem must be used inside ToggleGroup");
  return ctx;
}

export type ToggleGroupProps = Omit<HTMLAttributes<HTMLDivElement>, "onChange"> & {
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  children?: ReactNode;
};

/** Segmented single-select control. */
export function ToggleGroup({
  value,
  defaultValue = "",
  onValueChange,
  className,
  children,
  onKeyDown,
  ...rest
}: ToggleGroupProps) {
  const controlled = value !== undefined;
  const [uncontrolled, setUncontrolled] = useState(defaultValue);
  const current = controlled ? value : uncontrolled;
  const nodes = useRef<Map<string, HTMLButtonElement>>(new Map());

  const ctx = useMemo<ToggleCtx>(
    () => ({
      value: current,
      setValue: (next) => {
        if (!controlled) setUncontrolled(next);
        onValueChange?.(next);
      },
      register: (el, itemValue) => {
        if (!el) nodes.current.delete(itemValue);
        else nodes.current.set(itemValue, el);
      },
      items: () => [...nodes.current.values()],
    }),
    [current, controlled, onValueChange],
  );

  const onListKey = (e: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown?.(e);
    if (e.defaultPrevented) return;
    if (!["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
    e.preventDefault();
    const list = ctx.items();
    const index = list.findIndex((el) => el === document.activeElement);
    const next = moveRoving(list.length, index < 0 ? 0 : index, e.key);
    const el = list[next];
    if (!el) return;
    el.focus();
    const v = el.dataset.value;
    if (v) ctx.setValue(v);
  };

  return (
    <Ctx.Provider value={ctx}>
      <div
        role="group"
        className={cn("ui-toggle-group", className)}
        onKeyDown={onListKey}
        {...rest}
      >
        {children}
      </div>
    </Ctx.Provider>
  );
}

export type ToggleGroupItemProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "value"> & {
  value: string;
};

export const ToggleGroupItem = forwardRef<HTMLButtonElement, ToggleGroupItemProps>(function ToggleGroupItem(
  { value, className, disabled, children, ...rest },
  ref,
) {
  const ctx = useToggle();
  const on = ctx.value === value;
  return (
    <button
      ref={mergeRefs(ref, (node: HTMLButtonElement | null) => ctx.register(node, value))}
      type="button"
      aria-pressed={on}
      data-state={on ? "on" : "off"}
      data-value={value}
      className={cn("ui-toggle", className)}
      disabled={disabled}
      onClick={() => ctx.setValue(value)}
      {...rest}
    >
      {children}
    </button>
  );
});

import {
  createContext,
  forwardRef,
  useContext,
  useId,
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

type RadioCtx = {
  name: string;
  value: string;
  setValue: (value: string) => void;
  register: (el: HTMLButtonElement | null, value: string) => void;
  items: () => HTMLButtonElement[];
};

const Ctx = createContext<RadioCtx | null>(null);

function useRadio(): RadioCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("RadioGroupItem must be used inside RadioGroup");
  return ctx;
}

export type RadioGroupProps = Omit<HTMLAttributes<HTMLDivElement>, "onChange"> & {
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  name?: string;
  children?: ReactNode;
};

export function RadioGroup({
  value,
  defaultValue = "",
  onValueChange,
  name,
  className,
  children,
  onKeyDown,
  ...rest
}: RadioGroupProps) {
  const uid = useId();
  const controlled = value !== undefined;
  const [uncontrolled, setUncontrolled] = useState(defaultValue);
  const current = controlled ? value : uncontrolled;
  const nodes = useRef<Map<string, HTMLButtonElement>>(new Map());

  const ctx = useMemo<RadioCtx>(
    () => ({
      name: name ?? uid,
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
    [name, uid, current, controlled, onValueChange],
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
        role="radiogroup"
        className={cn("ui-radio-group", className)}
        onKeyDown={onListKey}
        {...rest}
      >
        {children}
      </div>
    </Ctx.Provider>
  );
}

export type RadioGroupItemProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "role" | "value"> & {
  value: string;
};

export const RadioGroupItem = forwardRef<HTMLButtonElement, RadioGroupItemProps>(function RadioGroupItem(
  { value, className, disabled, children, ...rest },
  ref,
) {
  const ctx = useRadio();
  const checked = ctx.value === value;
  return (
    <button
      ref={mergeRefs(ref, (node: HTMLButtonElement | null) => ctx.register(node, value))}
      type="button"
      role="radio"
      aria-checked={checked}
      data-state={checked ? "checked" : "unchecked"}
      data-value={value}
      tabIndex={checked || (!ctx.value && ctx.items()[0]?.dataset.value === value) ? 0 : -1}
      className={cn("ui-radio", className)}
      disabled={disabled}
      onClick={() => ctx.setValue(value)}
      {...rest}
    >
      <span className="ui-radio-dot" aria-hidden="true" />
      {children ? <span className="ui-radio-label">{children}</span> : null}
    </button>
  );
});

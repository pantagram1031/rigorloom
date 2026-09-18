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

type TabsCtx = {
  value: string;
  setValue: (value: string) => void;
  baseId: string;
  register: (el: HTMLButtonElement | null, value: string) => void;
  items: () => HTMLButtonElement[];
};

const Ctx = createContext<TabsCtx | null>(null);

function useTabs(): TabsCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("Tabs parts must be used inside Tabs");
  return ctx;
}

export type TabsProps = HTMLAttributes<HTMLDivElement> & {
  value?: string;
  defaultValue: string;
  onValueChange?: (value: string) => void;
  children?: ReactNode;
};

export function Tabs({
  value,
  defaultValue,
  onValueChange,
  className,
  children,
  ...rest
}: TabsProps) {
  const baseId = useId();
  const controlled = value !== undefined;
  const [uncontrolled, setUncontrolled] = useState(defaultValue);
  const current = controlled ? value : uncontrolled;
  const nodes = useRef<Map<string, HTMLButtonElement>>(new Map());

  const ctx = useMemo<TabsCtx>(
    () => ({
      value: current,
      setValue: (next) => {
        if (!controlled) setUncontrolled(next);
        onValueChange?.(next);
      },
      baseId,
      register: (el, itemValue) => {
        if (!el) nodes.current.delete(itemValue);
        else nodes.current.set(itemValue, el);
      },
      items: () => [...nodes.current.values()],
    }),
    [current, controlled, onValueChange, baseId],
  );

  return (
    <Ctx.Provider value={ctx}>
      <div className={cn("ui-tabs", className)} {...rest}>
        {children}
      </div>
    </Ctx.Provider>
  );
}

export function TabsList({
  className,
  children,
  onKeyDown,
  ...rest
}: HTMLAttributes<HTMLDivElement>) {
  const ctx = useTabs();
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
    <div role="tablist" className={cn("ui-tabs-list", className)} onKeyDown={onListKey} {...rest}>
      {children}
    </div>
  );
}

export type TabsTriggerProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "value"> & {
  value: string;
};

export const TabsTrigger = forwardRef<HTMLButtonElement, TabsTriggerProps>(function TabsTrigger(
  { value, className, disabled, children, ...rest },
  ref,
) {
  const ctx = useTabs();
  const active = ctx.value === value;
  const panelId = `${ctx.baseId}-panel-${value}`;
  const tabId = `${ctx.baseId}-tab-${value}`;
  return (
    <button
      ref={mergeRefs(ref, (node: HTMLButtonElement | null) => ctx.register(node, value))}
      type="button"
      role="tab"
      id={tabId}
      aria-selected={active}
      aria-controls={panelId}
      data-state={active ? "active" : "inactive"}
      data-value={value}
      tabIndex={active ? 0 : -1}
      className={cn("ui-tabs-trigger", className)}
      disabled={disabled}
      onClick={() => ctx.setValue(value)}
      {...rest}
    >
      {children}
    </button>
  );
});

export type TabsContentProps = HTMLAttributes<HTMLDivElement> & {
  value: string;
  forceMount?: boolean;
};

export function TabsContent({ value, className, children, forceMount, ...rest }: TabsContentProps) {
  const ctx = useTabs();
  const active = ctx.value === value;
  const panelId = `${ctx.baseId}-panel-${value}`;
  const tabId = `${ctx.baseId}-tab-${value}`;
  if (!active && !forceMount) return null;
  return (
    <div
      role="tabpanel"
      id={panelId}
      aria-labelledby={tabId}
      hidden={!active}
      data-state={active ? "active" : "inactive"}
      className={cn("ui-tabs-content", className)}
      tabIndex={0}
      {...rest}
    >
      {children}
    </div>
  );
}

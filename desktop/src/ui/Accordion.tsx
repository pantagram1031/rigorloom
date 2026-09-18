import {
  createContext,
  useContext,
  useState,
  type ReactNode,
} from "react";

import { cn } from "./cn";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "./Collapsible";

type AccordionType = "single" | "multiple";

type AccordionCtx = {
  type: AccordionType;
  value: string[];
  toggle: (item: string) => void;
};

const Ctx = createContext<AccordionCtx | null>(null);

function useAccordion(): AccordionCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("Accordion parts must be used inside Accordion");
  return ctx;
}

export type AccordionProps = {
  type?: AccordionType;
  value?: string | string[];
  defaultValue?: string | string[];
  onValueChange?: (value: string | string[]) => void;
  className?: string;
  children?: ReactNode;
};

function asList(v: string | string[] | undefined): string[] {
  if (v == null || v === "") return [];
  return Array.isArray(v) ? v : [v];
}

export function Accordion({
  type = "single",
  value,
  defaultValue,
  onValueChange,
  className,
  children,
}: AccordionProps) {
  const controlled = value !== undefined;
  const [uncontrolled, setUncontrolled] = useState<string[]>(asList(defaultValue));
  const current = controlled ? asList(value) : uncontrolled;

  const toggle = (item: string) => {
    let next: string[];
    if (type === "single") {
      next = current.includes(item) ? [] : [item];
    } else {
      next = current.includes(item) ? current.filter((x) => x !== item) : [...current, item];
    }
    if (!controlled) setUncontrolled(next);
    onValueChange?.(type === "single" ? (next[0] ?? "") : next);
  };

  return (
    <Ctx.Provider value={{ type, value: current, toggle }}>
      <div className={cn("ui-accordion", className)}>{children}</div>
    </Ctx.Provider>
  );
}

export function AccordionItem({
  value,
  className,
  children,
}: {
  value: string;
  className?: string;
  children?: ReactNode;
}) {
  const ctx = useAccordion();
  const open = ctx.value.includes(value);
  return (
    <Collapsible open={open} onOpenChange={() => ctx.toggle(value)} className={cn("ui-accordion-item", className)}>
      {children}
    </Collapsible>
  );
}

export function AccordionTrigger({
  className,
  children,
}: {
  className?: string;
  children?: ReactNode;
}) {
  return <CollapsibleTrigger className={cn("ui-accordion-trigger", className)}>{children}</CollapsibleTrigger>;
}

export function AccordionContent({
  className,
  children,
}: {
  className?: string;
  children?: ReactNode;
}) {
  return <CollapsibleContent className={cn("ui-accordion-content", className)}>{children}</CollapsibleContent>;
}

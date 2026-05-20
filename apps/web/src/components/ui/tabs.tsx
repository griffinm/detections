import * as React from "react";
import { cn } from "@/lib/utils";

export interface TabItem<T extends string = string> {
  value: T;
  label: React.ReactNode;
  count?: number;
}

interface TabsProps<T extends string> {
  value: T;
  onChange: (value: T) => void;
  items: ReadonlyArray<TabItem<T>>;
  className?: string;
}

export function Tabs<T extends string>({
  value,
  onChange,
  items,
  className,
}: TabsProps<T>) {
  return (
    <div
      role="tablist"
      className={cn("flex gap-1 border-b border-border", className)}
    >
      {items.map((item) => {
        const active = item.value === value;
        return (
          <button
            key={item.value}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(item.value)}
            className={cn(
              "-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium transition-colors",
              active
                ? "border-foreground text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {item.label}
            {item.count !== undefined ? (
              <span
                className={cn(
                  "rounded-full px-1.5 py-0.5 text-xs",
                  active
                    ? "bg-foreground/10 text-foreground"
                    : "bg-muted text-muted-foreground",
                )}
              >
                {item.count}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

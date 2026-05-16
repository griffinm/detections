import { cn } from "@/lib/utils";

export function ClassBadge({
  name,
  color,
  className,
}: {
  name: string;
  color: string;
  className?: string;
}) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-sm", className)}>
      <span
        className="h-3 w-3 shrink-0 rounded-sm border border-border"
        style={{ backgroundColor: color }}
      />
      <span className="truncate">{name}</span>
    </span>
  );
}

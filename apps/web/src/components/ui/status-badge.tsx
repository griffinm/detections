import { cn } from "@/lib/utils";

// Covers clip-processing statuses and training-run statuses so every table
// renders them identically.
const STATUS_STYLES: Record<string, string> = {
  pending: "bg-muted text-muted-foreground",
  queued: "bg-muted text-muted-foreground",
  cancelled: "bg-muted text-muted-foreground",
  extracting: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  running: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  detecting:
    "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  done: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  succeeded: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  failed: "bg-destructive/20 text-destructive",
};

const PULSING = new Set(["extracting", "detecting", "running"]);

export function StatusBadge({
  status,
  className,
}: {
  status: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium",
        STATUS_STYLES[status] ?? "bg-muted text-muted-foreground",
        PULSING.has(status) && "animate-pulse",
        className,
      )}
    >
      {status}
    </span>
  );
}

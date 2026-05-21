import { Menu } from "lucide-react";
import { ThemeToggle } from "./ThemeToggle";

interface TopbarProps {
  onOpenNav: () => void;
}

export function Topbar({ onOpenNav }: TopbarProps) {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-background px-4 sm:px-6">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onOpenNav}
          className="-ml-1 rounded-md p-2 text-muted-foreground hover:bg-accent hover:text-accent-foreground lg:hidden"
          aria-label="Open navigation"
        >
          <Menu className="h-5 w-5" />
        </button>
      </div>
      <div className="flex items-center gap-2">
        <ThemeToggle />
      </div>
    </header>
  );
}

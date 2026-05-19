import { NavLink } from "react-router-dom";
import {
  BarChart3,
  Clapperboard,
  Cpu,
  GraduationCap,
  HardDrive,
  LayoutDashboard,
  Layers,
  Settings,
  Tag,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";

const navItems = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/clips", label: "Clips", icon: Clapperboard },
  { to: "/labeling", label: "Labeling", icon: Tag },
  { to: "/classes", label: "Classes", icon: Layers },
  { to: "/models", label: "Models", icon: Cpu },
  { to: "/training", label: "Training", icon: GraduationCap },
  { to: "/metrics", label: "Metrics", icon: BarChart3 },
  { to: "/system/disk", label: "System", icon: HardDrive },
  { to: "/settings", label: "Settings", icon: Settings },
] as const;

interface SidebarProps {
  /** Drawer open state — only relevant below the `lg` breakpoint. */
  open: boolean;
  onClose: () => void;
}

export function Sidebar({ open, onClose }: SidebarProps) {
  return (
    <>
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/60 lg:hidden"
          onClick={onClose}
          aria-hidden
        />
      )}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex w-56 flex-col border-r border-sidebar-border bg-sidebar transition-transform duration-200",
          "lg:static lg:z-auto lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex h-14 shrink-0 items-center justify-between border-b border-sidebar-border px-4">
          <span className="text-sm font-semibold text-sidebar-foreground">
            video-detection
          </span>
          <button
            type="button"
            onClick={onClose}
            className="-mr-1 rounded-md p-1.5 text-sidebar-foreground hover:bg-sidebar-accent lg:hidden"
            aria-label="Close navigation"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto p-2">
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              onClick={onClose}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                  isActive
                    ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                    : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                )
              }
            >
              <Icon className="h-4 w-4 shrink-0" />
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
    </>
  );
}

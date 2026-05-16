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

export function Sidebar() {
  return (
    <aside className="flex w-56 flex-col border-r border-sidebar-border bg-sidebar">
      <div className="flex h-14 items-center border-b border-sidebar-border px-4">
        <span className="text-sm font-semibold text-sidebar-foreground">
          video-detection
        </span>
      </div>
      <nav className="flex-1 space-y-0.5 p-2">
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                isActive
                  ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                  : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
              )
            }
          >
            <Icon className="h-4 w-4 shrink-0" />
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}

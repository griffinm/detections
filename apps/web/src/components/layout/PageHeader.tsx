import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ChevronLeft } from "lucide-react";

interface Crumb {
  label: string;
  to: string;
}

/**
 * Standard page heading: optional breadcrumb trail, a title, inline meta
 * (badges/counts), and right-aligned actions. Every route uses this so the
 * heading row looks and wraps the same everywhere.
 */
export function PageHeader({
  title,
  meta,
  description,
  actions,
  breadcrumbs,
}: {
  title: ReactNode;
  meta?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  breadcrumbs?: Crumb[];
}) {
  return (
    <div className="space-y-1.5">
      {breadcrumbs && breadcrumbs.length > 0 && (
        <nav className="flex flex-wrap items-center gap-1.5 text-sm text-muted-foreground">
          <ChevronLeft className="h-4 w-4 shrink-0" />
          {breadcrumbs.map((crumb, i) => (
            <span key={crumb.to} className="flex items-center gap-1.5">
              {i > 0 && <span aria-hidden>/</span>}
              <Link
                to={crumb.to}
                className="transition-colors hover:text-foreground"
              >
                {crumb.label}
              </Link>
            </span>
          ))}
        </nav>
      )}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h1 className="text-xl font-bold tracking-tight sm:text-2xl">{title}</h1>
        {meta}
        {actions && (
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {actions}
          </div>
        )}
      </div>
      {description && (
        <p className="max-w-prose text-sm text-muted-foreground">
          {description}
        </p>
      )}
    </div>
  );
}

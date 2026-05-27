import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";

type LabelingTab = "queue" | "groups" | "similarity" | "tracks" | "clip";

interface Props {
  /** Which sub-page is active. */
  current: LabelingTab;
}

const TABS: ReadonlyArray<{ value: LabelingTab; label: string; to: string }> = [
  { value: "queue", label: "Frame queue", to: "/labeling" },
  { value: "groups", label: "Predicted groups", to: "/labeling/groups" },
  { value: "similarity", label: "Similarity clusters", to: "/labeling/similarity" },
  { value: "tracks", label: "Tracks", to: "/labeling/tracks" },
  { value: "clip", label: "By clip", to: "/clips" },
];

/**
 * Top-of-page navigation for the labeling section. "By clip" goes to the
 * clip list because the bulk-label-clip page is keyed on a specific clip id.
 */
export function LabelingTabs({ current }: Props) {
  return (
    <nav role="tablist" className="flex gap-1 border-b border-border">
      {TABS.map((tab) => {
        const active = tab.value === current;
        return (
          <Link
            key={tab.value}
            to={tab.to}
            role="tab"
            aria-selected={active}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors",
              active
                ? "border-foreground text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}

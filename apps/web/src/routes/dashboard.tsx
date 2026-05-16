import { Clapperboard, Eye, ScanLine, Target } from "lucide-react";
import { useMetricsSummary } from "@/hooks/useMetrics";

interface StatCardProps {
  label: string;
  value: string | number;
  icon: typeof Clapperboard;
}

function StatCard({ label, value, icon: Icon }: StatCardProps) {
  return (
    <div className="rounded-lg border border-border bg-card p-6 text-card-foreground">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-muted-foreground">{label}</p>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </div>
      <p className="mt-2 text-2xl font-bold">{value}</p>
    </div>
  );
}

export function Dashboard() {
  const { data: summary } = useMetricsSummary();
  const accuracy = summary?.last7d_class_accuracy;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Clips" value={summary?.clips ?? "—"} icon={Clapperboard} />
        <StatCard
          label="Detections"
          value={summary?.detections ?? "—"}
          icon={ScanLine}
        />
        <StatCard
          label="Pending Review"
          value={summary?.pending_review ?? "—"}
          icon={Eye}
        />
        <StatCard
          label="Accuracy (7d)"
          value={accuracy == null ? "—" : `${(accuracy * 100).toFixed(1)}%`}
          icon={Target}
        />
      </div>
      <div className="rounded-lg border border-border bg-card p-6">
        <h2 className="mb-4 text-sm font-semibold">Recent Activity</h2>
        <p className="text-sm text-muted-foreground">
          Drop a video into the inbox folder to get started.
        </p>
      </div>
    </div>
  );
}

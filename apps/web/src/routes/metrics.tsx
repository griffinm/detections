import { useState } from "react";
import { Link } from "react-router-dom";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { useModels } from "@/hooks/useModels";
import {
  useAccuracy,
  useCalibration,
  usePerClassMetrics,
  useRecentChanges,
  useTracksAccuracy,
  type AccuracyPoint,
} from "@/hooks/useMetrics";

const SERIES_COLORS = [
  "#3b82f6",
  "#22c55e",
  "#f59e0b",
  "#a855f7",
  "#ef4444",
  "#14b8a6",
];

const pct = (value: number | null | undefined): string =>
  value == null ? "—" : `${(value * 100).toFixed(1)}%`;

/** Pivot the long-form accuracy rows into one row per period, one key per model. */
function pivotAccuracy(points: AccuracyPoint[]): {
  rows: Record<string, number | string>[];
  seriesIds: string[];
} {
  const periods = [...new Set(points.map((p) => p.period))].sort();
  const seriesIds = [
    ...new Set(points.map((p) => p.model_version_id ?? "unknown")),
  ];
  const rows = periods.map((period) => {
    const row: Record<string, number | string> = {
      period: new Date(period).toLocaleDateString(),
    };
    for (const point of points) {
      if (point.period === period) {
        row[point.model_version_id ?? "unknown"] = point.class_top1;
      }
    }
    return row;
  });
  return { rows, seriesIds };
}

function AccuracySection() {
  const [bucket, setBucket] = useState<"day" | "week">("day");
  const { data: points = [], isPending } = useAccuracy(bucket);
  const { data: models = [] } = useModels();

  const modelName = (id: string): string => {
    if (id === "unknown") return "user / unversioned";
    return models.find((m) => m.id === id)?.name ?? `${id.slice(0, 8)}…`;
  };

  const { rows, seriesIds } = pivotAccuracy(points);

  return (
    <Card
      title="Class accuracy over time"
      actions={
        <div className="flex gap-1">
          {(["day", "week"] as const).map((option) => (
            <button
              key={option}
              onClick={() => setBucket(option)}
              className={cn(
                "rounded px-2 py-0.5 text-xs",
                bucket === option
                  ? "bg-accent"
                  : "text-muted-foreground hover:bg-muted",
              )}
            >
              {option}
            </button>
          ))}
        </div>
      }
    >
      {isPending ? (
        <div className="h-64 animate-pulse rounded bg-muted" />
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No reviewed detections yet — review some in the labeling UI.
        </p>
      ) : (
        <ResponsiveContainer width="100%" height={256}>
          <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
            <XAxis dataKey="period" tick={{ fontSize: 11 }} />
            <YAxis
              domain={[0, 1]}
              tickFormatter={pct}
              tick={{ fontSize: 11 }}
              width={48}
            />
            <Tooltip formatter={(value: number) => pct(value)} />
            {seriesIds.map((id, i) => (
              <Line
                key={id}
                type="monotone"
                dataKey={id}
                name={modelName(id)}
                stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
                strokeWidth={2}
                connectNulls
                dot={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </Card>
  );
}

function TrackAccuracySection() {
  const [bucket, setBucket] = useState<"day" | "week">("day");
  const { data: points = [], isPending } = useTracksAccuracy(bucket);
  const { data: models = [] } = useModels();

  const modelName = (id: string): string => {
    if (id === "unknown") return "user / unversioned";
    return models.find((m) => m.id === id)?.name ?? `${id.slice(0, 8)}…`;
  };

  const { rows, seriesIds } = pivotAccuracy(points);

  return (
    <Card
      title="Track top-1 class accuracy"
      actions={
        <div className="flex gap-1">
          {(["day", "week"] as const).map((option) => (
            <button
              key={option}
              onClick={() => setBucket(option)}
              className={cn(
                "rounded px-2 py-0.5 text-xs",
                bucket === option
                  ? "bg-accent"
                  : "text-muted-foreground hover:bg-muted",
              )}
            >
              {option}
            </button>
          ))}
        </div>
      }
    >
      {isPending ? (
        <div className="h-64 animate-pulse rounded bg-muted" />
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No reviewed tracks yet. Review a track on{" "}
          <Link to="/labeling/tracks" className="underline">
            /labeling/tracks
          </Link>{" "}
          to populate this chart.
        </p>
      ) : (
        <ResponsiveContainer width="100%" height={256}>
          <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
            <XAxis dataKey="period" tick={{ fontSize: 11 }} />
            <YAxis
              domain={[0, 1]}
              tickFormatter={pct}
              tick={{ fontSize: 11 }}
              width={48}
            />
            <Tooltip formatter={(value: number) => pct(value)} />
            {seriesIds.map((id, i) => (
              <Line
                key={id}
                type="monotone"
                dataKey={id}
                name={modelName(id)}
                stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
                strokeWidth={2}
                connectNulls
                dot={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </Card>
  );
}


function PerClassSection() {
  const { data: metrics = [], isPending } = usePerClassMetrics();
  return (
    <Card title="Per-class precision & recall">
      {isPending ? (
        <div className="h-24 animate-pulse rounded bg-muted" />
      ) : metrics.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No reviewed detections yet.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[420px] text-sm">
            <thead className="text-left text-xs uppercase text-muted-foreground">
              <tr>
                <th className="py-1.5 font-medium">Class</th>
                <th className="py-1.5 font-medium">Precision</th>
                <th className="py-1.5 font-medium">Recall</th>
                <th className="py-1.5 font-medium">Predicted</th>
                <th className="py-1.5 font-medium">Actual</th>
              </tr>
            </thead>
            <tbody>
              {metrics.map((m) => (
                <tr key={m.class_id} className="border-t border-border">
                  <td className="py-1.5">{m.class_name}</td>
                  <td className="py-1.5 tabular-nums">{pct(m.precision)}</td>
                  <td className="py-1.5 tabular-nums">{pct(m.recall)}</td>
                  <td className="py-1.5 tabular-nums text-muted-foreground">
                    {m.n_predicted}
                  </td>
                  <td className="py-1.5 tabular-nums text-muted-foreground">
                    {m.n_actual}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function CalibrationSection() {
  const { data, isPending } = useCalibration();
  return (
    <Card title="Calibration (reliability diagram)">
      {isPending ? (
        <div className="h-64 animate-pulse rounded bg-muted" />
      ) : !data || data.bins.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No scored detections yet.
        </p>
      ) : (
        <>
          <p className="mb-2 text-sm">
            ECE{" "}
            <span
              className={cn(
                "font-semibold tabular-nums",
                data.ece > 0.05 ? "text-destructive" : "text-green-600",
              )}
            >
              {data.ece.toFixed(3)}
            </span>
            {data.ece > 0.05 && (
              <span className="text-muted-foreground"> — poorly calibrated</span>
            )}
          </p>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart
              data={data.bins}
              margin={{ top: 8, right: 16, bottom: 8, left: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis
                dataKey="mean_confidence"
                type="number"
                domain={[0, 1]}
                tickFormatter={pct}
                tick={{ fontSize: 11 }}
              />
              <YAxis
                domain={[0, 1]}
                tickFormatter={pct}
                tick={{ fontSize: 11 }}
                width={48}
              />
              <Tooltip formatter={(value: number) => pct(value)} />
              <ReferenceLine
                segment={[
                  { x: 0, y: 0 },
                  { x: 1, y: 1 },
                ]}
                stroke="#94a3b8"
                strokeDasharray="4 4"
              />
              <Line
                type="monotone"
                dataKey="empirical_accuracy"
                name="empirical accuracy"
                stroke="#3b82f6"
                strokeWidth={2}
              />
            </LineChart>
          </ResponsiveContainer>
        </>
      )}
    </Card>
  );
}

function ChangesSection() {
  const { data: changes = [], isPending } = useRecentChanges();
  const transition = (from: string | null, to: string | null): string | null =>
    from || to ? `${from ?? "∅"} → ${to ?? "∅"}` : null;

  return (
    <Card title="What changed — recent reassignments">
      {isPending ? (
        <div className="h-24 animate-pulse rounded bg-muted" />
      ) : changes.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No corrections recorded yet.
        </p>
      ) : (
        <ul className="space-y-1 text-sm">
          {changes.map((change) => (
            <li
              key={`${change.detection_id}-${change.at}`}
              className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-border py-1.5 first:border-t-0"
            >
              <span className="text-muted-foreground">
                {new Date(change.at).toLocaleString()}
              </span>
              <span>
                {transition(change.from_class, change.to_class) ??
                  transition(change.from_subclass, change.to_subclass) ??
                  change.reason}
              </span>
              <span className="rounded bg-muted px-1 text-[10px] text-muted-foreground">
                {change.reason === "retrain_reassign" ? "retrain" : "manual"}
              </span>
              {change.frame_id && (
                <Link
                  to={`/labeling/${change.frame_id}`}
                  className="ml-auto text-xs text-muted-foreground hover:text-foreground"
                >
                  frame →
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function MetricsPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Metrics"
        description="Detection accuracy over time, per class, per model version."
      />
      <AccuracySection />
      <TrackAccuracySection />
      <div className="grid gap-4 lg:grid-cols-2">
        <PerClassSection />
        <CalibrationSection />
      </div>
      <ChangesSection />
    </div>
  );
}

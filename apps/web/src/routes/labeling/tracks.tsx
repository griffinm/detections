import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/layout/PageHeader";
import { Select } from "@/components/ui/select";
import { StatusBadge } from "@/components/ui/status-badge";
import { LabelingTabs } from "@/components/labeling/LabelingTabs";
import { DetectionThumbStrip } from "@/components/labeling/DetectionTileGrid";
import { useClasses } from "@/hooks/useClasses";
import { useSubclasses } from "@/hooks/useSubclasses";
import { useClipsList } from "@/hooks/useClips";
import { useClipTracks, type TrackRead } from "@/hooks/useBulkLabeling";
import { formatClipName } from "@/lib/format";

interface TrackCardProps {
  track: TrackRead;
  className: string | null;
  subclassName: string | null;
}

function TrackCard({ track, className, subclassName }: TrackCardProps) {
  // The clip detail page has thumbnails of detections; here we don't have the
  // detection ids until the user opens the track. Keep the card compact.
  return (
    <Link
      to={`/labeling/tracks/${track.id}`}
      className="block rounded-lg border border-border bg-card p-4 transition-colors hover:bg-muted"
    >
      <div className="flex items-baseline gap-2">
        <h3 className="truncate text-base font-semibold">
          {subclassName ?? className ?? "(no class)"}
        </h3>
        {subclassName && className && (
          <span className="truncate text-xs text-muted-foreground">{className}</span>
        )}
        <span className="ml-auto">
          <StatusBadge status={track.reviewed ? "done" : "pending"} />
        </span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span>
          {track.n_detections} detection{track.n_detections === 1 ? "" : "s"}
        </span>
        <span>
          frames {track.first_frame_index}–{track.last_frame_index}
        </span>
        {track.confidence_subclass !== null && (
          <span>conf {Math.round(track.confidence_subclass * 100)}%</span>
        )}
        {track.source === "user" && <span className="italic">user-split</span>}
      </div>
    </Link>
  );
}

export function LabelingTracks() {
  const { data: clipsPage } = useClipsList({ status: "done" });
  const clips = useMemo(() => clipsPage?.items ?? [], [clipsPage]);
  const [clipId, setClipId] = useState<string>("");
  useEffect(() => {
    if (!clipId && clips.length > 0) {
      setClipId(clips[0].id);
    }
  }, [clipId, clips]);

  const { data: classes = [] } = useClasses();
  const { data: tracks = [], isPending } = useClipTracks(clipId || undefined);
  const [classFilter, setClassFilter] = useState<string>("");
  const [reviewFilter, setReviewFilter] = useState<"all" | "unreviewed" | "reviewed">(
    "unreviewed",
  );

  const classById = useMemo(
    () => Object.fromEntries(classes.map((c) => [c.id, c])),
    [classes],
  );
  // We need a per-class sub-class map for display — fetch the union by
  // iterating once across the visible tracks' classes.
  const visibleClassIds = useMemo(() => {
    const ids = new Set<string>();
    for (const t of tracks) if (t.class_id) ids.add(t.class_id);
    return Array.from(ids);
  }, [tracks]);

  const visible = useMemo(
    () =>
      tracks
        .filter((t) => !classFilter || t.class_id === classFilter)
        .filter((t) =>
          reviewFilter === "all"
            ? true
            : reviewFilter === "reviewed"
              ? t.reviewed
              : !t.reviewed,
        )
        .sort((a, b) => a.first_frame_index - b.first_frame_index),
    [tracks, classFilter, reviewFilter],
  );

  return (
    <div className="space-y-4">
      <PageHeader
        title="Tracks"
        description="One sequence of detections per physical object within a clip. Apply once, label all members."
      />
      <LabelingTabs current="tracks" />

      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          Clip
          <Select
            value={clipId}
            onChange={(e) => setClipId(e.target.value)}
            className="h-8 text-xs"
          >
            <option value="" disabled>
              Pick a clip…
            </option>
            {clips.map((c) => (
              <option key={c.id} value={c.id}>
                {formatClipName(c.filename)}
              </option>
            ))}
          </Select>
        </label>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          Class
          <Select
            value={classFilter}
            onChange={(e) => setClassFilter(e.target.value)}
            className="h-8 text-xs"
          >
            <option value="">All</option>
            {classes
              .filter((c) => c.is_active)
              .map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
          </Select>
        </label>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          Status
          <Select
            value={reviewFilter}
            onChange={(e) =>
              setReviewFilter(e.target.value as "all" | "unreviewed" | "reviewed")
            }
            className="h-8 text-xs"
          >
            <option value="unreviewed">Unreviewed</option>
            <option value="reviewed">Reviewed</option>
            <option value="all">All</option>
          </Select>
        </label>
        <span className="ml-auto text-xs text-muted-foreground">
          {visible.length} of {tracks.length} tracks
        </span>
      </div>

      {!clipId ? (
        <p className="text-sm text-muted-foreground">Pick a clip to list its tracks.</p>
      ) : isPending ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-lg bg-muted" />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {tracks.length === 0
            ? "This clip has no tracks yet. Pre-Phase-9 clips need to be backfilled from the System page."
            : "No tracks match the current filter."}
        </p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {visible.map((t) => (
            <TrackCard
              key={t.id}
              track={t}
              className={t.class_id ? (classById[t.class_id]?.name ?? null) : null}
              // Pulling sub-class names here would require loading sub-classes
              // for every class; the detail page resolves the full name.
              subclassName={null}
            />
          ))}
        </div>
      )}
    </div>
  );
}

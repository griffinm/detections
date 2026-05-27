import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, CheckCircle2, Scissors, Combine, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { LabelingTabs } from "@/components/labeling/LabelingTabs";
import { DetectionThumbStrip } from "@/components/labeling/DetectionTileGrid";
import { useClasses } from "@/hooks/useClasses";
import { useSubclasses } from "@/hooks/useSubclasses";
import { useClipTracks } from "@/hooks/useBulkLabeling";
import {
  useTrack,
  useTrackPatch,
  useTrackSplit,
  useTrackMerge,
  useTrackDelete,
  type TrackRead,
  type TrackMember,
} from "@/hooks/useBulkLabeling";

interface FocusedFrameProps {
  member: TrackMember | null;
}

function FocusedFramePreview({ member }: FocusedFrameProps) {
  if (!member) {
    return (
      <aside className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
        Click a frame thumbnail to preview it here.
      </aside>
    );
  }
  return (
    <aside className="space-y-3">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        Frame {member.frame_index}
      </div>
      <div className="overflow-hidden rounded border border-border bg-muted">
        <img
          src={`/api/detections/${member.id}/crop?size=512`}
          alt={`Detection on frame ${member.frame_index}`}
          className="block h-auto w-full"
        />
      </div>
      <Link
        to={`/labeling/${member.frame_id}`}
        target="_blank"
        rel="noreferrer"
        className="text-xs text-muted-foreground hover:text-foreground"
      >
        Open this frame ↗
      </Link>
    </aside>
  );
}

export function LabelingTrackDetail() {
  const { id = "" } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: detail, isPending } = useTrack(id);
  const { data: classes = [] } = useClasses();
  const track: TrackRead | null = detail?.track ?? null;
  const members = detail?.members ?? [];

  // Same-clip tracks drive the Merge picker. The list is keyed on the open
  // track's clip_id, so it loads as soon as `detail` arrives.
  const { data: siblingTracks = [] } = useClipTracks(track?.clip_id ?? undefined);

  const { data: subclasses = [] } = useSubclasses(track?.class_id ?? undefined);
  const activeSubclasses = subclasses.filter((s) => s.is_active);

  const [targetClass, setTargetClass] = useState<string>("");
  const [targetSubclass, setTargetSubclass] = useState<string>("");
  useEffect(() => {
    if (track) {
      setTargetClass(track.class_id ?? "");
      setTargetSubclass(track.subclass_id ?? "");
    }
  }, [track]);

  const [focusedMemberId, setFocusedMemberId] = useState<string | null>(null);
  useEffect(() => {
    if (members.length > 0 && !members.some((m) => m.id === focusedMemberId)) {
      setFocusedMemberId(members[0].id);
    }
  }, [focusedMemberId, members]);
  const focusedMember = members.find((m) => m.id === focusedMemberId) ?? null;

  const patch = useTrackPatch();
  const split = useTrackSplit();
  const merge = useTrackMerge();
  const remove = useTrackDelete();

  const [splitOpen, setSplitOpen] = useState(false);
  const [mergeOpen, setMergeOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [mergeTarget, setMergeTarget] = useState<string>("");

  const className = useMemo(() => {
    const cls = classes.find((c) => c.id === track?.class_id);
    return cls?.name ?? "(no class)";
  }, [classes, track]);
  const predictedSubclassName = useMemo(
    () =>
      activeSubclasses.find((s) => s.id === track?.predicted_subclass_id)?.name ??
      "—",
    [activeSubclasses, track],
  );
  const currentSubclassName = useMemo(
    () =>
      activeSubclasses.find((s) => s.id === track?.subclass_id)?.name ?? "—",
    [activeSubclasses, track],
  );

  // Merge candidates: same clip, same class, not soft-deleted, not this track,
  // and frame ranges don't overlap (the server enforces this too — we just
  // hide it from the list to keep the picker honest).
  const mergeCandidates = useMemo(
    () =>
      track
        ? siblingTracks.filter(
            (t) =>
              t.id !== track.id &&
              t.class_id === track.class_id &&
              (t.last_frame_index < track.first_frame_index ||
                t.first_frame_index > track.last_frame_index),
          )
        : [],
    [siblingTracks, track],
  );
  useEffect(() => {
    if (mergeCandidates.length > 0 && !mergeTarget) {
      setMergeTarget(mergeCandidates[0].id);
    }
  }, [mergeCandidates, mergeTarget]);

  if (isPending || !track) {
    return (
      <div className="space-y-4">
        <PageHeader title="Track" />
        <LabelingTabs current="tracks" />
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    );
  }

  const apply = () => {
    const wants: {
      class_id?: string | null;
      subclass_id?: string | null;
      reviewed?: boolean;
    } = {};
    if (targetClass !== (track.class_id ?? "")) wants.class_id = targetClass || null;
    if (targetSubclass !== (track.subclass_id ?? ""))
      wants.subclass_id = targetSubclass || null;
    wants.reviewed = true;
    patch.mutate(
      { trackId: track.id, patch: wants },
      {
        onSuccess: (result) =>
          toast.success(
            `Applied to ${result.updated_detections} detection${
              result.updated_detections === 1 ? "" : "s"
            }`,
          ),
        onError: () => toast.error("Failed to update track"),
      },
    );
  };

  const memberThumbs = members.map((m) => m.id);

  return (
    <div className="space-y-4">
      <PageHeader
        title={`Track on frames ${track.first_frame_index}–${track.last_frame_index}`}
        meta={
          <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            <Link
              to="/labeling/tracks"
              className="inline-flex items-center gap-1 hover:text-foreground"
            >
              <ArrowLeft className="h-3 w-3" /> All tracks
            </Link>
            <Link
              to={`/clips/${track.clip_id}`}
              className="hover:text-foreground"
            >
              Clip
            </Link>
            <StatusBadge status={track.reviewed ? "done" : "pending"} />
            <span>
              {track.n_detections} detection{track.n_detections === 1 ? "" : "s"}
            </span>
          </div>
        }
      />
      <LabelingTabs current="tracks" />

      <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
        <div className="space-y-4">
          <div className="rounded-lg border border-border bg-card p-4 text-sm">
            <div className="grid gap-2 sm:grid-cols-2">
              <div>
                <div className="text-xs uppercase tracking-wide text-muted-foreground">
                  Class
                </div>
                <div>{className}</div>
              </div>
              <div>
                <div className="text-xs uppercase tracking-wide text-muted-foreground">
                  Sub-class
                </div>
                <div>
                  {currentSubclassName}
                  {track.predicted_subclass_id &&
                    track.predicted_subclass_id !== track.subclass_id && (
                      <span className="ml-2 text-xs text-muted-foreground">
                        (predicted: {predictedSubclassName})
                      </span>
                    )}
                </div>
              </div>
              <div>
                <div className="text-xs uppercase tracking-wide text-muted-foreground">
                  Confidence
                </div>
                <div>
                  {track.confidence_subclass !== null
                    ? `${Math.round(track.confidence_subclass * 100)}%`
                    : "—"}
                </div>
              </div>
              <div>
                <div className="text-xs uppercase tracking-wide text-muted-foreground">
                  Source
                </div>
                <div>{track.source}</div>
              </div>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-4">
            <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
              Apply to whole track
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Select
                value={targetClass}
                onChange={(e) => setTargetClass(e.target.value)}
                className="h-8 text-xs"
              >
                <option value="">(no class)</option>
                {classes
                  .filter((c) => c.is_active)
                  .map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
              </Select>
              <Select
                value={targetSubclass}
                onChange={(e) => setTargetSubclass(e.target.value)}
                className="h-8 text-xs"
                disabled={activeSubclasses.length === 0}
              >
                <option value="">(no sub-class)</option>
                {activeSubclasses.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </Select>
              <Button onClick={apply} disabled={patch.isPending}>
                <CheckCircle2 className="h-4 w-4" /> Apply
              </Button>
              <div className="ml-auto flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setSplitOpen(true)}
                  disabled={!focusedMember || track.n_detections < 2}
                >
                  <Scissors className="h-3.5 w-3.5" /> Split here
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setMergeOpen(true)}
                  disabled={mergeCandidates.length === 0}
                >
                  <Combine className="h-3.5 w-3.5" /> Merge with…
                </Button>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => setDeleteOpen(true)}
                >
                  <Trash2 className="h-3.5 w-3.5" /> Delete
                </Button>
              </div>
            </div>
          </div>

          <div>
            <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
              Member frames
            </div>
            <div className="flex flex-wrap gap-2">
              {members.map((m) => {
                const isFocused = m.id === focusedMemberId;
                return (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => setFocusedMemberId(m.id)}
                    className={
                      "overflow-hidden rounded border-2 transition-colors " +
                      (isFocused
                        ? "border-foreground"
                        : "border-border hover:border-muted-foreground")
                    }
                    title={`Frame ${m.frame_index}`}
                  >
                    <img
                      src={`/api/detections/${m.id}/crop?size=192`}
                      alt={`Frame ${m.frame_index}`}
                      width={96}
                      height={96}
                      className="block h-24 w-24 object-cover"
                      loading="lazy"
                      decoding="async"
                    />
                  </button>
                );
              })}
            </div>
            {memberThumbs.length === 0 && (
              <DetectionThumbStrip detectionIds={[]} />
            )}
          </div>
        </div>

        <FocusedFramePreview member={focusedMember} />
      </div>

      <Dialog open={splitOpen} onOpenChange={setSplitOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Split this track</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            The current focus is on frame {focusedMember?.frame_index}. Split
            here puts every detection from frame {focusedMember?.frame_index}{" "}
            onward into a new track.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSplitOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                if (!focusedMember) return;
                split.mutate(
                  {
                    trackId: track.id,
                    pivot_frame_index: focusedMember.frame_index,
                  },
                  {
                    onSuccess: (newDetail) => {
                      toast.success("Track split");
                      setSplitOpen(false);
                      navigate(`/labeling/tracks/${newDetail.track.id}`);
                    },
                    onError: (err) =>
                      toast.error((err as Error).message ?? "Split failed"),
                  },
                );
              }}
            >
              Split
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={mergeOpen} onOpenChange={setMergeOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Merge another track into this one</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            Pick a same-class track whose frame range doesn't overlap.
          </p>
          <Select
            value={mergeTarget}
            onChange={(e) => setMergeTarget(e.target.value)}
            className="h-8 text-xs"
          >
            {mergeCandidates.map((t) => (
              <option key={t.id} value={t.id}>
                Frames {t.first_frame_index}–{t.last_frame_index} ·{" "}
                {t.n_detections} detection{t.n_detections === 1 ? "" : "s"}
              </option>
            ))}
          </Select>
          <DialogFooter>
            <Button variant="outline" onClick={() => setMergeOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                if (!mergeTarget) return;
                merge.mutate(
                  { trackId: track.id, other_track_id: mergeTarget },
                  {
                    onSuccess: () => {
                      toast.success("Tracks merged");
                      setMergeOpen(false);
                    },
                    onError: (err) =>
                      toast.error((err as Error).message ?? "Merge failed"),
                  },
                );
              }}
            >
              Merge
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete this track?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            Every detection in the track will be soft-deleted. The detection
            audit ledger preserves the history.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                remove.mutate(track.id, {
                  onSuccess: () => {
                    toast.success("Track deleted");
                    navigate("/labeling/tracks");
                  },
                  onError: () => toast.error("Delete failed"),
                });
              }}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

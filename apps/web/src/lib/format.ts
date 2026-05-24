/** Human-readable byte size (binary units). */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  if (bytes < 1024 ** 4) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
  return `${(bytes / 1024 ** 4).toFixed(2)} TB`;
}

/** Clip duration as `m:ss`. */
export function formatDuration(sec: number | null): string {
  if (sec == null) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/** Display name for a clip — the source filename is often a GUID, so the
 * UI surfaces the clip's timestamp instead. Format: `M/dd/yyyy h:mm:ss AM/PM`. */
export function formatClipName(timestamp: string | Date | null | undefined): string {
  if (!timestamp) return "—";
  const d = typeof timestamp === "string" ? new Date(timestamp) : timestamp;
  if (Number.isNaN(d.getTime())) return "—";
  const month = d.getMonth() + 1;
  const day = String(d.getDate()).padStart(2, "0");
  const year = d.getFullYear();
  let hours = d.getHours();
  const ampm = hours >= 12 ? "PM" : "AM";
  hours = hours % 12 || 12;
  const minutes = String(d.getMinutes()).padStart(2, "0");
  const seconds = String(d.getSeconds()).padStart(2, "0");
  return `${month}/${day}/${year} ${hours}:${minutes}:${seconds} ${ampm}`;
}

/** Elapsed wall-clock time, e.g. "1h 04m", "7m 23s", "48s". */
export function formatElapsed(sec: number | null): string {
  if (sec == null || sec < 0) return "—";
  const total = Math.floor(sec);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}h ${m.toString().padStart(2, "0")}m`;
  if (m > 0) return `${m}m ${s.toString().padStart(2, "0")}s`;
  return `${s}s`;
}

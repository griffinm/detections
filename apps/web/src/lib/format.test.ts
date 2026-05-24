import { describe, expect, it } from "vitest";
import { formatBytes, formatClipName } from "./format";

describe("formatBytes", () => {
  it("formats bytes", () => expect(formatBytes(512)).toBe("512 B"));
  it("formats kilobytes", () => expect(formatBytes(1536)).toBe("1.5 KB"));
  it("formats megabytes", () => expect(formatBytes(5 * 1024 ** 2)).toBe("5.0 MB"));
  it("formats gigabytes", () => expect(formatBytes(3 * 1024 ** 3)).toBe("3.00 GB"));
  it("formats terabytes", () => expect(formatBytes(2 * 1024 ** 4)).toBe("2.00 TB"));
});

describe("formatClipName", () => {
  it("formats a local Date as M/dd/yyyy h:mm:ss AM/PM", () => {
    const d = new Date(2026, 4, 23, 15, 7, 5); // May 23 2026 3:07:05 PM local
    expect(formatClipName(d)).toBe("5/23/2026 3:07:05 PM");
  });
  it("handles midnight as 12 AM", () => {
    const d = new Date(2026, 0, 9, 0, 0, 0);
    expect(formatClipName(d)).toBe("1/09/2026 12:00:00 AM");
  });
  it("handles noon as 12 PM", () => {
    const d = new Date(2026, 0, 9, 12, 30, 45);
    expect(formatClipName(d)).toBe("1/09/2026 12:30:45 PM");
  });
  it("returns dash for null/empty", () => {
    expect(formatClipName(null)).toBe("—");
    expect(formatClipName(undefined)).toBe("—");
    expect(formatClipName("not-a-date")).toBe("—");
  });
});

import { describe, expect, it } from "vitest";
import { formatBytes } from "./format";

describe("formatBytes", () => {
  it("formats bytes", () => expect(formatBytes(512)).toBe("512 B"));
  it("formats kilobytes", () => expect(formatBytes(1536)).toBe("1.5 KB"));
  it("formats megabytes", () => expect(formatBytes(5 * 1024 ** 2)).toBe("5.0 MB"));
  it("formats gigabytes", () => expect(formatBytes(3 * 1024 ** 3)).toBe("3.00 GB"));
  it("formats terabytes", () => expect(formatBytes(2 * 1024 ** 4)).toBe("2.00 TB"));
});

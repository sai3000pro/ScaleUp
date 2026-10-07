import { describe, expect, it } from "vitest";

import { cameraSummary } from "@/lib/cameraStatus";

describe("cameraSummary", () => {
  // @spec CAP-PERM-005
  it("names the reason when the camera could not be opened", () => {
    expect(cameraSummary("denied", "idle", false)).toMatch(/permission denied/);
    expect(cameraSummary("missing", "idle", false)).toMatch(/No camera was found/);
  });

  // @spec CAP-PERM-004
  it("tells the learner audio practice is unaffected by a camera failure", () => {
    expect(cameraSummary("denied", "idle", false)).toMatch(/audio practice is unaffected/);
    expect(cameraSummary("missing", "idle", false)).toMatch(/audio practice is unaffected/);
  });

  it("reports model state once the camera is open, and the mock when it runs", () => {
    expect(cameraSummary("active", "tracking", false)).toBe("Tracking your hand");
    expect(cameraSummary("idle", "idle", false)).toBe("Technique camera is off");
    expect(cameraSummary("denied", "idle", true)).toMatch(/^Mock landmarks/);
  });
});

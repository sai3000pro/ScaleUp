import { describe, expect, it } from "vitest";

import {
  CAPTURE_FAILURE_LABEL,
  CaptureError,
  classifyCaptureFailure,
} from "@/lib/pitchDetection";

describe("microphone capture failure states", () => {
  it("distinguishes a permission denial from missing hardware", () => {
    expect(classifyCaptureFailure(new DOMException("blocked", "NotAllowedError"))).toBe("permission_denied");
    expect(classifyCaptureFailure(new DOMException("no device", "NotFoundError"))).toBe("unavailable");
  });

  it("reports unsupported browser capture when the media API is absent", () => {
    expect(classifyCaptureFailure(new Error("missing"), false)).toBe("unsupported");
  });

  it("exposes stable labels and actionable typed error copy", () => {
    const failure = new CaptureError("permission_denied");

    expect(CAPTURE_FAILURE_LABEL.permission_denied).toBe("Microphone permission denied");
    expect(failure.message).toContain("fixture performance");
  });
});

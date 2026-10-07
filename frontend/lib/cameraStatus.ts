import type { VisualTrackingStatus } from "@/lib/visualTracking";

export type CameraStatus = "idle" | "loading" | "active" | "denied" | "missing";

const TRACKING_LABEL: Record<VisualTrackingStatus, string> = {
  idle: "Technique camera is off",
  loading: "Loading hand-tracking model…",
  tracking: "Tracking your hand",
  unavailable: "Hand model unavailable (offline?) — audio practice is unaffected",
};

const CAMERA_FAILURE_LABEL: Record<"denied" | "missing", string> = {
  denied: "Camera permission denied — audio practice is unaffected",
  missing: "No camera was found on this device — audio practice is unaffected",
};

/**
 * The one line under the technique controls. A camera that could not be opened
 * is reported as such, with the reason, rather than as a camera that is merely
 * off: the learner pressed the button and must be able to see why nothing
 * happened.
 *
 * @spec CAP-PERM-004, CAP-PERM-005
 */
export function cameraSummary(camera: CameraStatus, tracking: VisualTrackingStatus, mockMode: boolean): string {
  if (mockMode) return "Mock landmarks — a camera-free demo of the metric pipeline";
  if (camera === "denied" || camera === "missing") return CAMERA_FAILURE_LABEL[camera];
  if (camera === "loading" && tracking === "idle") return "Opening camera…";
  return TRACKING_LABEL[tracking];
}

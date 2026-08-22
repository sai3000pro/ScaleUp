import type { Metadata } from "next";

import { LandingRoute } from "@/components/landing/LandingRoute";

/**
 * The application root is the public argument for the product.
 *
 * It renders without a session and is not exchanged for another destination
 * when one exists — `/courses` is one click away, and that is where the primary
 * action sends a signed-in reader.
 *
 * @spec LAND-ROUTE-001
 */
export const metadata: Metadata = {
  title: "Learn Any Instrument — practice that measures itself",
  description:
    "Pick a skill, play it, and get scored on pitch, rhythm, dynamics and posture — then coached about it. Unpractised technique fades and returns as a quest.",
};

export default function Home() {
  return <LandingRoute />;
}

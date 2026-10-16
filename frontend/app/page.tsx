import type { Metadata } from "next";

import { LandingRoute } from "@/components/landing/LandingRoute";
import { landingMetadata } from "@/lib/landingMetadata";

/**
 * The application root is the public argument for the product.
 *
 * It renders without a session and is not exchanged for another destination
 * when one exists — `/courses` is one click away, and that is where the primary
 * action sends a signed-in reader.
 *
 * @spec LAND-ROUTE-001, LAND-ROUTE-005
 */
export const metadata: Metadata = landingMetadata;

export default function Home() {
  return <LandingRoute />;
}

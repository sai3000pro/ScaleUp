"use client";

/**
 * Chooses where the landing page's primary action goes, and nothing else.
 *
 * The session lives in a client store, so this is the one thing on the page
 * that cannot be decided on the server. It is kept in its own component so the
 * page itself stays a document: `LandingPage` takes a destination and a label
 * and knows nothing about authentication.
 *
 * The page is NOT exchanged for another destination when a session exists. A
 * learner who follows a link to the argument should see the argument.
 *
 * @spec LAND-ROUTE-002, LAND-ROUTE-003
 */
import { LandingPage } from "@/components/landing/LandingPage";
import { useAuthStore } from "@/stores/useAuthStore";

export function LandingRoute() {
  const user = useAuthStore((state) => state.user);
  const signedIn = Boolean(user);

  return (
    <LandingPage
      primaryHref={signedIn ? "/courses" : "/login"}
      primaryLabel={signedIn ? "Back to your courses" : "Start playing"}
      signedIn={signedIn}
    />
  );
}

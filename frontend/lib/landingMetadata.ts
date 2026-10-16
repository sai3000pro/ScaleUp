import type { Metadata } from "next";

/**
 * The public page's document metadata, including what a link to it unfurls as.
 *
 * A shared link renders as a card only when the page declares Open Graph and
 * Twitter metadata; without them it is a bare URL. The image is rendered by
 * app/opengraph-image.tsx, which Next registers against these entries.
 *
 * @spec LAND-ROUTE-005
 */
export const LANDING_TITLE = "ScaleUp — practice that measures itself";
export const LANDING_DESCRIPTION =
  "Pick a skill, play it, and get scored on pitch, rhythm, dynamics and posture — then coached about it. Unpractised technique fades and returns as a quest.";

export const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export const landingMetadata: Metadata = {
  title: LANDING_TITLE,
  description: LANDING_DESCRIPTION,
  openGraph: {
    type: "website",
    siteName: "ScaleUp",
    title: LANDING_TITLE,
    description: LANDING_DESCRIPTION,
    url: "/",
  },
  twitter: {
    card: "summary_large_image",
    title: LANDING_TITLE,
    description: LANDING_DESCRIPTION,
  },
};

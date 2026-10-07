import { describe, expect, it } from "vitest";

import {
  LANDING_DESCRIPTION,
  LANDING_TITLE,
  landingMetadata,
} from "@/lib/landingMetadata";

// @spec LAND-ROUTE-005
describe("the landing page's social preview", () => {
  it("declares an Open Graph card and a large-image Twitter card", () => {
    const og = landingMetadata.openGraph;
    expect(og).toBeDefined();
    expect(og?.title).toBe(LANDING_TITLE);
    expect(og?.description).toBe(LANDING_DESCRIPTION);
    expect(og?.url).toBe("/");
    expect(landingMetadata.twitter).toMatchObject({
      card: "summary_large_image",
      title: LANDING_TITLE,
    });
  });

  it("keeps the card copy within what the networks render untruncated", () => {
    expect(LANDING_TITLE.length).toBeLessThanOrEqual(70);
    expect(LANDING_DESCRIPTION.length).toBeLessThanOrEqual(200);
  });
});

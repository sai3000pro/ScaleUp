import { ImageResponse } from "next/og";

import { LANDING_DESCRIPTION } from "@/lib/landingMetadata";

/**
 * The card image a shared link to the root unfurls with. Rendered from markup
 * at request time, so it needs no asset and repaints with the copy.
 *
 * @spec LAND-ROUTE-005
 */
export const runtime = "edge";
export const alt = "ScaleUp — practice that measures itself";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "flex-end",
        padding: 72,
        background: "linear-gradient(135deg, #fdfbfb 0%, #fbe6ee 100%)",
        color: "#1c181a",
        fontFamily: "sans-serif",
      }}
    >
      <div
        style={{
          fontSize: 40,
          letterSpacing: 6,
          textTransform: "uppercase",
          color: "#b8496f",
        }}
      >
        ScaleUp
      </div>
      <div
        style={{
          fontSize: 76,
          fontWeight: 300,
          letterSpacing: -2,
          marginTop: 16,
        }}
      >
        Practice that measures itself.
      </div>
      <div
        style={{
          fontSize: 30,
          marginTop: 24,
          color: "#655c60",
          maxWidth: 1000,
        }}
      >
        {LANDING_DESCRIPTION}
      </div>
    </div>,
    size,
  );
}

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // The dev server binds to localhost, but tooling (and the Chrome extension,
  // which refuses `localhost`) reaches it via 127.0.0.1. Without this, Next
  // treats /_next/* as cross-origin, the client bundle never executes, and the
  // page sits on its SSR'd HTML forever with no hydration and no error.
  allowedDevOrigins: ["127.0.0.1"],
};

export default nextConfig;

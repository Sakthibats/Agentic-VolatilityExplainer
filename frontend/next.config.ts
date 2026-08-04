import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static export to `out/` — the app is entirely client-side and talks to the
  // backend only over NEXT_PUBLIC_API_URL, so there is no server to deploy.
  output: "export",
};

export default nextConfig;

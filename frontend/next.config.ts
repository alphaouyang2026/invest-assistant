import type { NextConfig } from "next";

// Where the backend is, seen from the Next server: `backend:8000` inside
// docker compose, localhost when both run on the host.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // The dev server serves its scripts only to origins it counts as its own;
  // the README opens the app at 127.0.0.1, which it does not, and without
  // this every page would render its outline and never load its data.
  allowedDevOrigins: ["127.0.0.1"],
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }];
  },
};

export default nextConfig;

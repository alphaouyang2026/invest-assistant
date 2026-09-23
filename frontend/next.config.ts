import type { NextConfig } from "next";

// Where the backend is, seen from the Next server: `backend:8000` inside
// docker compose, localhost when both run on the host.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }];
  },
};

export default nextConfig;

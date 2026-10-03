import type { NextConfig } from "next";

const API_ORIGIN = process.env.CLIPSIEVE_API_ORIGIN || "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ destination: `${API_ORIGIN}/api/:path*`, source: "/api/:path*" }];
  },
};

export default nextConfig;

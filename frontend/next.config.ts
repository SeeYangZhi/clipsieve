import type { NextConfig } from "next";

const API_ORIGIN = process.env.CLIPSIEVE_API_ORIGIN || "http://localhost:8000";

const nextConfig: NextConfig = {
  // The API, including the SSE event stream, is proxied through the rewrite
  // below. Next's gzip holds a text/event-stream back until the response ends
  // (verified: events arrived only on close, with Content-Encoding: gzip), so
  // compression stays off here; a production proxy can compress static assets.
  compress: false,
  async rewrites() {
    return [{ destination: `${API_ORIGIN}/api/:path*`, source: "/api/:path*" }];
  },
};

export default nextConfig;

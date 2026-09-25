import type { NextConfig } from "next";

// The browser only ever talks to this Next server. /api/* is proxied to FastAPI, so the
// API port is never published and the session cookie stays same-origin + httpOnly.
const API_URL = process.env.KILA_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  devIndicators: false,
  experimental: {
    // /api/* rewrites default to a 30 s socket-inactivity timeout. A cold load of a large model
    // can be silent for longer than that before the first token, so allow 10 minutes.
    // (The API also sends SSE keep-alive comments every 10 s.)
    proxyTimeout: 600_000,
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
        ],
      },
    ];
  },
};

export default nextConfig;

/** @type {import('next').NextConfig} */
const API_BASE = process.env.BACKEND_ORIGIN || "http://localhost:8000";

const nextConfig = {
  reactStrictMode: true,
  // Self-contained server output for a slim Docker runtime image.
  output: "standalone",
  // Proxy /api/* to the FastAPI backend so the browser stays same-origin in
  // local dev (`npm run dev`). In Docker, nginx routes /api -> api instead, so
  // this rewrite is never hit there.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${API_BASE}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;

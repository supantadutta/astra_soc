/** @type {import('next').NextConfig} */
const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // Proxy API + SSE stream to the backend so the browser talks to one origin.
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API}/api/:path*` },
    ];
  },
};

export default nextConfig;

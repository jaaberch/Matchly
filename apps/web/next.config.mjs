/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The API is a separate service; the browser talks to it directly using
  // NEXT_PUBLIC_API_BASE_URL, so there is no rewrite proxy to keep in sync.
  eslint: { ignoreDuringBuilds: true },
};

export default nextConfig;

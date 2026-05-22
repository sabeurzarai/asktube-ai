/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",

  // Allow YouTube thumbnail images to load in production
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "i.ytimg.com" },
      { protocol: "https", hostname: "img.youtube.com" },
    ],
  },
};

export default nextConfig;

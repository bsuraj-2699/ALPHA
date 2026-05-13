/** @type {import('next').NextConfig} */
const path = require("path");

const nextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  eslint: {
    ignoreDuringBuilds: true,
  },
  // Monorepo: trace server bundles from the repository root (fixes noisy
  // "multiple lockfiles" warnings and helps Vercel include the right files).
  outputFileTracingRoot: path.join(__dirname, "..", ".."),
};

module.exports = nextConfig;

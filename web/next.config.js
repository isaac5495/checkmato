/** @type {import('next').NextConfig} */
const path = require("path");
const nextConfig = {
  outputFileTracingRoot: path.join(__dirname),
  output: "export", // static build served by FastAPI at :8000 (single process)
  images: { unoptimized: true },
  trailingSlash: true,
};

module.exports = nextConfig;

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  devIndicators: false,
  // STATIC_EXPORT=1: plain files the FastAPI container serves from the same origin
  ...(process.env.STATIC_EXPORT === "1" ? { output: "export" as const, trailingSlash: true } : {}),
};

export default nextConfig;

import type { NextConfig } from "next";

/**
 * Security headers on every page.
 *
 * CSP: scripts and styles only from this site (Next inlines small bootstrap scripts and
 * styles, hence 'unsafe-inline' — there is no third-party script anywhere); images from this
 * site plus data:/blob: (camera captures, QR codes, review crops); API calls only to this site
 * (the browser never talks to the FastAPI server directly). No framing — the portal cannot be
 * embedded to clickjack a teacher into approving something.
 *
 * Permissions-Policy: camera and geolocation are allowed for this site only (selfie
 * attendance), everything else off.
 */
const isProd = process.env.NODE_ENV === "production";

const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isProd ? "" : " 'unsafe-eval'"}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "media-src 'self' blob:",
  `connect-src 'self'${isProd ? "" : " ws: wss:"}`,
  "worker-src 'self'",
  "manifest-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(self), geolocation=(self), microphone=(), payment=(), usb=(), interest-cohort=()" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  ...(isProd && process.env.ATTENDANCE_INSECURE_COOKIES !== "1"
    ? [{ key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" }]
    : []),
];

const nextConfig: NextConfig = {
  poweredByHeader: false,
  experimental: {
    // Selfie and enrollment frames are posted through the proxy; leave room above 10 MB.
    proxyClientMaxBodySize: "20mb",
  },
  async headers() {
    return [
      { source: "/:path*", headers: securityHeaders },
      // The service worker must be revalidated on every load so updates roll out.
      { source: "/sw.js", headers: [{ key: "Cache-Control", value: "no-cache" }] },
    ];
  },
};

export default nextConfig;

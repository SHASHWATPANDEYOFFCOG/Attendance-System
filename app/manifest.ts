import type { MetadataRoute } from "next";

/** Installable app: students can add the portal to their phone's home screen. */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Attendance Register",
    short_name: "Attendance",
    description: "Mark attendance, see your percentage, apply for leave.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#F4F5F0",
    theme_color: "#16304F",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/maskable-192.png", sizes: "192x192", type: "image/png", purpose: "maskable" },
      { src: "/icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}

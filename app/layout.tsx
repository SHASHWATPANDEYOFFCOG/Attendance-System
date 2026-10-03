import type { Metadata, Viewport } from "next";
import { Barlow_Condensed, IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";

import "./globals.css";
import { RegisterServiceWorker } from "@/components/pwa";
import { UiProvider } from "@/components/toast";

/* A deliberate pairing, not Inter for everything:
     Barlow Condensed — condensed grotesque; uppercase letterspaced labels and headings
     IBM Plex Sans    — body copy
     IBM Plex Mono    — ALL data, tabular figures, so columns of numbers line up */
const label = Barlow_Condensed({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-label-loaded",
  display: "swap",
});
const sans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-sans-loaded",
  display: "swap",
});
const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-mono-loaded",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "Attendance Register", template: "%s · Attendance Register" },
  description: "Occlusion-robust attendance for scheduled sessions",
  applicationName: "Attendance Register",
  appleWebApp: { capable: true, title: "Attendance", statusBarStyle: "default" },
  icons: {
    icon: [{ url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" }],
    apple: [{ url: "/icons/apple-touch-icon.png", sizes: "180x180" }],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#16304F" },
    { media: "(prefers-color-scheme: dark)", color: "#11161D" },
  ],
};

/**
 * Applies the stored theme before first paint.
 *
 * Without this the page renders light and then flips — a flash of the wrong theme, which is
 * especially unpleasant in a dim room, which is exactly where a door kiosk lives.
 */
const THEME_BOOTSTRAP = `
(function () {
  try {
    var t = localStorage.getItem('att_theme');
    if (t === 'dark' || t === 'light') document.documentElement.setAttribute('data-theme', t);
  } catch (e) {}
})();
`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${label.variable} ${sans.variable} ${mono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      </head>
      <body className="flex min-h-full flex-col">
        <UiProvider>{children}</UiProvider>
        <RegisterServiceWorker />
      </body>
    </html>
  );
}

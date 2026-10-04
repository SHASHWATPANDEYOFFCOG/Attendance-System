import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import "./globals.css";
import { RegisterServiceWorker } from "@/components/pwa";
import { UiProvider } from "@/components/toast";

/* Geist for everything readable (tight tracking at display sizes, see .headline / .display),
   Geist Mono for data and figures so columns of numbers line up. Variable fonts: one file
   each, every weight. */
const sans = Geist({ subsets: ["latin"], variable: "--font-sans-loaded", display: "swap" });
const mono = Geist_Mono({ subsets: ["latin"], variable: "--font-mono-loaded", display: "swap" });

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
  document.documentElement.classList.add('js');
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
      className={`${sans.variable} ${mono.variable} h-full antialiased`}
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

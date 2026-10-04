"use client";

import { useEffect } from "react";

/** Registers the service worker (production only — it would cache-confuse the dev server). */
export function RegisterServiceWorker() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js").catch(() => {
      /* not fatal: the portal works without it */
    });
  }, []);
  return null;
}

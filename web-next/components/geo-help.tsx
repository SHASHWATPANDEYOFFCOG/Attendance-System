/**
 * Getting the browser's location, with instructions a student can follow when it fails.
 * Android Chrome and iPhone Safari bury the setting in different places, so both are spelled
 * out rather than "enable location in your settings".
 */
export type Fix = { lat: number; lng: number; accuracy: number };

export type GeoFailure = "denied" | "unavailable" | "timeout" | "unsupported" | "insecure";

export function getLocation(timeoutMs = 20000): Promise<Fix> {
  return new Promise((resolve, reject) => {
    if (typeof window !== "undefined" && !window.isSecureContext) return reject("insecure" as GeoFailure);
    if (!("geolocation" in navigator)) return reject("unsupported" as GeoFailure);
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy }),
      (err) =>
        reject((err.code === err.PERMISSION_DENIED ? "denied" : err.code === err.TIMEOUT ? "timeout" : "unavailable") as GeoFailure),
      { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: 0 },
    );
  });
}

export function LocationHelp({ reason }: { reason: GeoFailure }) {
  if (reason === "insecure") {
    return (
      <p className="m-0 text-[13.5px]">
        Location only works over a secure (https) connection. Open the portal from its https
        address.
      </p>
    );
  }
  if (reason === "unsupported") {
    return <p className="m-0 text-[13.5px]">This browser cannot share your location. Use Chrome or Safari on your phone.</p>;
  }
  if (reason === "timeout" || reason === "unavailable") {
    return (
      <div className="text-[13.5px]">
        <p className="m-0">Your phone could not find its location.</p>
        <ul className="mb-0 mt-1 pl-5">
          <li>Turn on Location / GPS in your quick settings.</li>
          <li>Step closer to a window or out of a basement room, then try again.</li>
        </ul>
      </div>
    );
  }
  return (
    <div className="grid gap-2 text-[13.5px]">
      <p className="m-0"><strong>Location access is blocked for this site.</strong> Allow it, then reload this page:</p>
      <div>
        <span className="label block">Android · Chrome</span>
        Tap the <strong>lock / tune icon</strong> left of the address → <strong>Permissions</strong> →{" "}
        <strong>Location</strong> → <strong>Allow</strong>. If that is greyed out, open phone{" "}
        <strong>Settings → Location</strong> and turn it on.
      </div>
      <div>
        <span className="label block">iPhone · Safari</span>
        Tap <strong>aA</strong> in the address bar → <strong>Website Settings</strong> → <strong>Location</strong> →{" "}
        <strong>Allow</strong>. Also check <strong>Settings → Privacy &amp; Security → Location Services</strong> is on, and{" "}
        <strong>Safari Websites</strong> is set to <strong>While Using the App</strong>.
      </div>
    </div>
  );
}

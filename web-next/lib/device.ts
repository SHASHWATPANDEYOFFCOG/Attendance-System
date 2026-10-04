/** The cookie that marks this browser as a paired tablet. httpOnly: page scripts never see it. */
export const DEVICE_COOKIE = "att_device";

/** A paired tablet stays paired for a year, or until its authority revokes or re-pairs it. */
export const DEVICE_MAX_AGE = 60 * 60 * 24 * 365;

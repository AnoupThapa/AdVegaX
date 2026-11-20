/**
 * Choices and quick checks for organization settings. The API re-validates everything
 * (ISO 4217 currency, IANA time zone, name 1–120 characters).
 */

export const NAME_MAX_LENGTH = 120;

export type Option = { readonly value: string; readonly label: string };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Organization IDs in URLs are a claim (PHASE_01C_PLAN §4.4); malformed ones are not sent. */
export function isOrganizationId(value: string): boolean {
  return UUID.test(value);
}

function supported(key: "currency" | "timeZone"): string[] {
  try {
    return Intl.supportedValuesOf(key);
  } catch {
    return [];
  }
}

/** Every ISO 4217 currency the browser knows, labelled "AUD — Australian Dollar". */
export function currencyOptions(include: string = ""): Option[] {
  const codes = new Set(supported("currency"));
  if (include) codes.add(include);
  let names: Intl.DisplayNames | null = null;
  try {
    names = new Intl.DisplayNames(undefined, { type: "currency" });
  } catch {
    names = null;
  }
  return [...codes].sort().map((code) => {
    const name = names?.of(code);
    return { value: code, label: name && name !== code ? `${code} — ${name}` : code };
  });
}

/** IANA time zones, plus `include` (e.g. the saved value) when the browser lists it differently. */
export function timeZoneOptions(include: string = ""): Option[] {
  const zones = new Set(supported("timeZone"));
  if (include) zones.add(include);
  return [...zones].sort().map((zone) => ({ value: zone, label: zone.replaceAll("_", " ") }));
}

/** The browser's own time zone, a sensible default for a new organization. */
export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch {
    return "";
  }
}

export function nameErrors(name: string): string[] {
  const value = name.trim();
  if (!value) return ["Enter a name for the organization."];
  if (value.length > NAME_MAX_LENGTH) return [`Use at most ${NAME_MAX_LENGTH} characters.`];
  return [];
}

export function requiredChoice(value: string, message: string): string[] {
  return value ? [] : [message];
}

/** Dates from the API (ISO 8601) in the reader's locale; invalid input is shown as received. */
export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
    date,
  );
}

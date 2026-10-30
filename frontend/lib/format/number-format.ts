/**
 * A cached `Intl.NumberFormat`. Creating one is slow (it loads locale data), and a report page
 * formats hundreds of figures, so every page used to spend most of its time here on a phone.
 * Output is identical to creating a new formatter each time.
 */
const cache = new Map<string, Intl.NumberFormat>();

export function numberFormat(
  locale: string | undefined,
  options?: Intl.NumberFormatOptions,
): Intl.NumberFormat {
  const key = `${locale ?? ""}|${options ? JSON.stringify(options) : ""}`;
  let format = cache.get(key);
  if (!format) {
    format = new Intl.NumberFormat(locale, options);
    cache.set(key, format);
  }
  return format;
}

/**
 * Details some platforms need before the person is sent to them (tasks 2A-10, 2B-08).
 * Shopify: the store address. WooCommerce: the store's web address (WordPress may live in a
 * sub-folder). The API validates both again; this only helps people type them.
 */

export type FieldCheck = { readonly value: string } | { readonly error: string };

export type ConnectField = {
  readonly name: string;
  readonly label: string;
  readonly hint: string;
  readonly placeholder: string;
  /** Normalizes what people paste, or explains why it cannot be used. */
  readonly check: (raw: string) => FieldCheck;
};

const SHOP = /^[a-z0-9][a-z0-9-]*\.myshopify\.com$/;

/**
 * Accepts what people paste — "your-store", "your-store.myshopify.com" or a full store URL —
 * and returns the store address, or null when it cannot be one.
 */
export function normalizeShopDomain(raw: string): string | null {
  let value = raw.trim().toLowerCase();
  if (!value) return null;
  value = value.replace(/^https?:\/\//, "").split(/[/?#]/)[0] ?? "";
  if (!value.includes(".")) value = `${value}.myshopify.com`;
  return SHOP.test(value) && value.length <= 255 ? value : null;
}

const HOST_LABEL = /^(?!-)[a-z0-9-]{1,63}(?<!-)$/;
const PATH_SEGMENT = /^[A-Za-z0-9._~-]{1,100}$/;
// Parts of a pasted WordPress address that are not the site itself.
const WORDPRESS_TAILS = new Set(["wp-admin", "wp-json", "wp-login.php", "index.php"]);

export const STORE_URL_ERRORS = {
  empty: "Enter your store's web address, for example shop.example.com.",
  https: "Your store must use a secure address (https://). Switch on HTTPS for the site first.",
  invalid: "Enter a web address like shop.example.com or example.com/shop.",
  credentials: "Remove the user name or password from the address.",
  port: "Use the store's normal web address, without a port number.",
} as const;

/**
 * A WooCommerce store's address: "shop.example.com", "https://example.com/shop/wp-admin/" …
 * → "https://shop.example.com" or "https://example.com/shop". HTTPS only (Q10b); public host
 * names only — the API also refuses private and internal addresses.
 */
export function checkStoreUrl(raw: string): FieldCheck {
  let text = raw.trim();
  if (!text) return { error: STORE_URL_ERRORS.empty };
  if (/\s|\\/.test(text) || text.length > 2048) return { error: STORE_URL_ERRORS.invalid };
  const lowered = text.toLowerCase();
  if (lowered.startsWith("http://")) return { error: STORE_URL_ERRORS.https };
  if (lowered.startsWith("https://")) text = text.slice("https://".length);
  else if (lowered.includes("://") || lowered.startsWith("//"))
    return { error: STORE_URL_ERRORS.invalid };
  const [address = ""] = text.split(/[?#]/);
  const slash = address.indexOf("/");
  const authority = slash === -1 ? address : address.slice(0, slash);
  const path = slash === -1 ? "" : address.slice(slash);
  if (authority.includes("@")) return { error: STORE_URL_ERRORS.credentials };
  const [hostPart = "", port] = authority.split(":");
  if (port !== undefined && port !== "443") return { error: STORE_URL_ERRORS.port };
  const host = hostPart.toLowerCase().replace(/\.$/, "");
  const labels = host.split(".");
  if (
    labels.length < 2 ||
    host.length > 253 ||
    !labels.every((l) => HOST_LABEL.test(l)) ||
    /^[0-9]+$/.test(labels.at(-1) ?? "")
  ) {
    return { error: STORE_URL_ERRORS.invalid };
  }
  const segments: string[] = [];
  for (const segment of path.split("/").filter(Boolean)) {
    if (WORDPRESS_TAILS.has(segment.toLowerCase())) break;
    if (segment === "." || segment === ".." || !PATH_SEGMENT.test(segment))
      return { error: STORE_URL_ERRORS.invalid };
    segments.push(segment);
  }
  if (segments.length > 5) return { error: STORE_URL_ERRORS.invalid };
  return { value: `https://${host}${segments.map((s) => `/${s}`).join("")}` };
}

export const CONNECT_FIELDS: Readonly<Record<string, readonly ConnectField[]>> = {
  shopify: [
    {
      name: "shop_domain",
      label: "Store address",
      hint: "Your Shopify store's address, for example your-store.myshopify.com.",
      placeholder: "your-store.myshopify.com",
      check: (raw) => {
        const value = normalizeShopDomain(raw);
        return value
          ? { value }
          : { error: "Enter a store address like your-store.myshopify.com." };
      },
    },
  ],
  woocommerce: [
    {
      name: "store_url",
      label: "Store address",
      hint: "Your store's web address, for example shop.example.com or example.com/shop. It must use https://.",
      placeholder: "shop.example.com",
      check: checkStoreUrl,
    },
  ],
};

/** What each platform's own approval page looks like, in one sentence. */
export const CONNECT_NOTES: Readonly<Record<string, string>> = {
  woocommerce:
    "Your store opens its own WordPress page. Sign in there as an administrator and approve read-only access. AdVegaX can read your store but never change it.",
};

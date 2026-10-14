/**
 * Details some platforms need before the person is sent to them (task 2A-10).
 * Shopify: the store address. The API validates it again; this only helps people type it.
 */

export type ConnectField = {
  readonly name: string;
  readonly label: string;
  readonly hint: string;
  readonly placeholder: string;
};

export const CONNECT_FIELDS: Readonly<Record<string, readonly ConnectField[]>> = {
  shopify: [
    {
      name: "shop_domain",
      label: "Store address",
      hint: "Your Shopify store's address, for example your-store.myshopify.com.",
      placeholder: "your-store.myshopify.com",
    },
  ],
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

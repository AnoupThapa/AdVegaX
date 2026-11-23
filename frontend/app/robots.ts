import type { MetadataRoute } from "next";

/** Only the public home page is meant for search engines; the application behind sign-in is not. */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: ["/$"], disallow: ["/"] }],
  };
}

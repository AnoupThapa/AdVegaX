import type { Metadata, Viewport } from "next";
import { connection } from "next/server";
import type { ReactNode } from "react";

import { SiteHeader } from "@/components/layout/SiteHeader";
import { SkipLink } from "@/components/layout/SkipLink";

import { Providers } from "./providers";

import "@fontsource-variable/cormorant-garamond";
import "@fontsource-variable/montserrat";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "AdVegaX", template: "%s · AdVegaX" },
  description: "Advertise smarter. Grow faster. Profit-first advertising for online stores.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  // Render per request so every response carries a fresh CSP nonce (see proxy.ts).
  await connection();
  return (
    <html lang="en">
      <body>
        <Providers>
          <SkipLink />
          <SiteHeader />
          <main id="main" tabIndex={-1}>
            {children}
          </main>
        </Providers>
      </body>
    </html>
  );
}

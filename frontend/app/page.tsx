import type { Metadata } from "next";

import { HomeGate } from "@/features/home/HomeGate";
import { Landing } from "@/features/home/Landing";

// The only page meant for search engines; everything behind sign-in stays noindex (root layout).
export const metadata: Metadata = {
  title: { absolute: "AdVegaX — advertising and growth for online stores" },
  description:
    "See what your advertising really earns after costs, get explained suggestions, and approve changes with a full audit record.",
  robots: { index: true, follow: true },
  openGraph: {
    title: "AdVegaX — advertising and growth for online stores",
    description:
      "See what your advertising really earns after costs, get explained suggestions, and approve changes with a full audit record.",
    type: "website",
  },
};

export default function HomePage() {
  return <HomeGate landing={<Landing />} />;
}

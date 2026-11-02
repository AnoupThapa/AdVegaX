import type { Metadata } from "next";

import { ProductsPage } from "@/features/stores/ProductsPage";

export const metadata: Metadata = { title: "Products" };

export default function Page() {
  return <ProductsPage />;
}

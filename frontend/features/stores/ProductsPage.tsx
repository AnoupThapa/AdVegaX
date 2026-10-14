"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageHeading } from "@/components/ui/PageHeading";
import { SelectField } from "@/components/ui/SelectField";
import { TextField } from "@/components/ui/TextField";
import { useCurrentOrganization } from "@/features/organizations/OrganizationShell";
import { ApiError, messageFor } from "@/lib/api/errors";
import { AVAILABILITY_LABELS } from "@/lib/format/availability";
import { formatMoney } from "@/lib/format/money";

import { useProducts, useStore, type Store, type Variant } from "./api";
import { COST_REASON, COST_SOURCE, PRODUCT_STATUS } from "./labels";
import { StoreNotFound } from "./StorePage";
import styles from "./stores.module.css";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const STATUS_OPTIONS = [
  { value: "", label: "All (not deleted)" },
  ...Object.entries(PRODUCT_STATUS).map(([value, label]) => ({ value, label })),
];

function stock(variant: Variant): string {
  const { inventory } = variant;
  const count = inventory.available;
  if (inventory.availability === "available" && count !== null) {
    return new Intl.NumberFormat().format(count);
  }
  if (inventory.tracked === false) return "Not tracked";
  return AVAILABILITY_LABELS.not_synchronized;
}

function cost(variant: Variant, store: Store): { text: string; note: string } {
  const c = variant.cost;
  if (c.availability === "available" && c.unit_cost) {
    return {
      text: formatMoney(c.unit_cost, store.currency, store.currency_minor_units),
      note: (c.source && COST_SOURCE[c.source]) ?? "",
    };
  }
  return { text: (c.reason && COST_REASON[c.reason]) || AVAILABILITY_LABELS.unavailable, note: "" };
}

function Products({ store }: { store: Store }) {
  const org = useCurrentOrganization();
  const [draft, setDraft] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const products = useProducts(org.id, store.id, q, status);
  const items = products.data?.pages.flatMap((page) => page.items) ?? [];

  function search(event: FormEvent) {
    event.preventDefault();
    setQ(draft.trim());
  }

  return (
    <>
      <form className={styles.toolbar} onSubmit={search} role="search">
        <TextField
          label="Search by name or SKU"
          value={draft}
          maxLength={100}
          required
          onChange={(event) => setDraft(event.target.value)}
        />
        <Button type="submit" variant="secondary">
          Search
        </Button>
        {q ? (
          <Button
            variant="link"
            onClick={() => {
              setDraft("");
              setQ("");
            }}
          >
            Clear search
          </Button>
        ) : null}
        <SelectField
          label="Status"
          options={STATUS_OPTIONS}
          value={status}
          onChange={(event) => setStatus(event.target.value)}
        />
      </form>
      {products.error ? <Alert tone="error">{messageFor(products.error)}</Alert> : null}
      {products.isPending ? <p role="status">Loading products…</p> : null}
      {products.data && items.length === 0 ? (
        <p>{q || status ? "No products match." : "No products have been imported yet."}</p>
      ) : null}
      {items.length ? (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <caption>
              Stock is the total across locations. Costs come from the platform; a product without
              one shows why instead of 0.
            </caption>
            <thead>
              <tr>
                <th scope="col">Product</th>
                <th scope="col">Variant</th>
                <th scope="col" className={styles.num}>
                  Price
                </th>
                <th scope="col" className={styles.num}>
                  Stock
                </th>
                <th scope="col" className={styles.num}>
                  Unit cost
                </th>
              </tr>
            </thead>
            <tbody>
              {items.flatMap((product) =>
                (product.variants.length ? product.variants : [null]).map((variant, index) => {
                  const unit = variant ? cost(variant, store) : null;
                  return (
                    <tr key={variant?.id ?? product.id}>
                      {index === 0 ? (
                        <th scope="rowgroup" rowSpan={Math.max(1, product.variants.length)}>
                          {product.title}
                          <br />
                          <span className={styles.muted}>
                            {PRODUCT_STATUS[product.status] ?? product.status}
                          </span>
                        </th>
                      ) : null}
                      <td>
                        {variant ? (
                          <>
                            {variant.title ?? "—"}
                            {variant.sku ? (
                              <span className={styles.muted}> · SKU {variant.sku}</span>
                            ) : null}
                          </>
                        ) : (
                          <span className={styles.missing}>No variants</span>
                        )}
                      </td>
                      <td className={styles.num}>
                        {variant?.price
                          ? formatMoney(variant.price, store.currency, store.currency_minor_units)
                          : AVAILABILITY_LABELS.unavailable}
                      </td>
                      <td className={styles.num}>{variant ? stock(variant) : "—"}</td>
                      <td className={styles.num}>
                        {unit ? (
                          <>
                            {unit.text}
                            {unit.note ? (
                              <>
                                <br />
                                <span className={styles.muted}>{unit.note}</span>
                              </>
                            ) : null}
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  );
                }),
              )}
            </tbody>
          </table>
        </div>
      ) : null}
      {products.hasNextPage ? (
        <p>
          <Button
            variant="secondary"
            busy={products.isFetchingNextPage}
            onClick={() => void products.fetchNextPage()}
          >
            Show more products
          </Button>
        </p>
      ) : null}
    </>
  );
}

function Detail({ storeId }: { storeId: string }) {
  const org = useCurrentOrganization();
  const store = useStore(org.id, storeId);
  if (store.error) {
    if (store.error instanceof ApiError && store.error.status === 404) return <StoreNotFound />;
    return <Alert tone="error">{messageFor(store.error)}</Alert>;
  }
  if (!store.data) return <p role="status">Loading store…</p>;
  return (
    <section aria-labelledby="products-title">
      <p>
        <Link href={`/orgs/${org.id}/stores/${storeId}`}>
          ← {store.data.name ?? store.data.domain}
        </Link>
      </p>
      <PageHeading id="products-title">Products</PageHeading>
      <Products store={store.data} />
    </section>
  );
}

export function ProductsPage() {
  const params = useParams<{ storeId: string }>();
  const id = params.storeId ?? "";
  if (!UUID.test(id)) return <StoreNotFound />;
  return <Detail storeId={id} />;
}

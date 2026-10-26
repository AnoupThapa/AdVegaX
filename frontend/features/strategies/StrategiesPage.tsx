"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageHeading } from "@/components/ui/PageHeading";
import { SelectField } from "@/components/ui/SelectField";
import { TextField } from "@/components/ui/TextField";
import styles from "@/features/advertising/advertising.module.css";
import { providerName } from "@/features/advertising/labels";
import { ScrollTable } from "@/features/overview/Shared";
import { useCurrentOrganization } from "@/features/organizations/OrganizationShell";
import type { Organization } from "@/features/organizations/api";
import { formatDateTime } from "@/features/organizations/options";
import { canManageStrategies } from "@/features/organizations/permissions";
import { useProducts, useStores } from "@/features/stores/api";
import { ApiError, messageFor } from "@/lib/api/errors";
import { formatMoney } from "@/lib/format/money";

import { useGenerateStrategy, useStrategies, type StrategySummary } from "./api";
import { OBJECTIVES, PERIODS, PLATFORMS, STATUS, errorReasons, statusLabel } from "./labels";
import own from "./strategies.module.css";

type Filter = "" | "draft" | "ready" | "archived";
const FILTERS: ReadonlyArray<{ value: Filter; label: string }> = [
  { value: "", label: "Drafts and ready" },
  { value: "draft", label: "Drafts" },
  { value: "ready", label: "Ready" },
  { value: "archived", label: "Archived" },
];

/** Problems with the request the API would refuse anyway, said before it is sent. */
function formErrors(values: {
  product: string;
  platforms: string[];
  amount: string;
}): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!values.product) errors.product = "Choose a product.";
  if (values.platforms.length === 0) errors.platforms = "Choose at least one platform.";
  if (!/^\d+(\.\d+)?$/.test(values.amount.trim()) || /^0+(\.0+)?$/.test(values.amount.trim())) {
    errors.amount = "Enter an amount above 0, for example 50 or 49.90.";
  }
  return errors;
}

function NewStrategy({ org }: { org: Organization }) {
  const router = useRouter();
  const stores = useStores(org.id);
  const [storeId, setStoreId] = useState("");
  const [search, setSearch] = useState("");
  const [product, setProduct] = useState("");
  const [platforms, setPlatforms] = useState<string[]>([...PLATFORMS]);
  const [objective, setObjective] = useState("");
  const [amount, setAmount] = useState("");
  const [period, setPeriod] = useState<"daily" | "monthly">("daily");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const generate = useGenerateStrategy(org.id);

  const store = storeId || stores.data?.[0]?.id || "";
  const products = useProducts(org.id, store, search.trim(), "active");
  const listed = products.data?.pages.flatMap((page) => page.items) ?? [];

  if (stores.error) return <Alert tone="error">{messageFor(stores.error)}</Alert>;
  if (!stores.data) return <p role="status">Loading…</p>;
  if (stores.data.length === 0) {
    return (
      <p className={styles.muted}>Connect a store first: strategies are made for its products.</p>
    );
  }

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const found = formErrors({ product, platforms, amount });
    setErrors(found);
    if (Object.keys(found).length) return;
    generate.mutate(
      {
        product_id: product,
        platforms: PLATFORMS.filter((p) => platforms.includes(p)),
        objective: (objective || null) as "sales" | "leads" | "awareness" | null,
        budget: { amount: amount.trim(), period },
      },
      { onSuccess: (created) => router.push(`/orgs/${org.id}/strategies/${created.id}`) },
    );
  };

  const error = generate.error;
  return (
    <section aria-labelledby="new-strategy" className={styles.section}>
      <h2 id="new-strategy">New strategy</h2>
      <p className={styles.muted}>
        AdVegaX&apos;s planner writes a draft from your own figures — sales, margin, stock, ad
        results and the funnel. You set the budget; AdVegaX works out each platform&apos;s amount.
        Every answer is checked before you see it, and nothing is created at Google or Meta.
      </p>
      <form className={own.form} onSubmit={submit} noValidate>
        {stores.data.length > 1 ? (
          <SelectField
            label="Store"
            options={stores.data.map((s) => ({ value: s.id, label: s.name ?? s.domain }))}
            value={store}
            onChange={(e) => {
              setStoreId(e.target.value);
              setProduct("");
            }}
          />
        ) : null}
        <TextField
          label="Find a product"
          hint="Type part of its name; only active products are listed."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <SelectField
          label="Product"
          placeholder={products.isLoading ? "Loading…" : "Choose a product"}
          options={listed.map((p) => ({ value: p.id, label: p.title }))}
          value={product}
          onChange={(e) => setProduct(e.target.value)}
          errors={errors.product ? [errors.product] : []}
          required
        />
        <fieldset
          className={own.choices}
          aria-describedby={errors.platforms ? "platforms-error" : undefined}
        >
          <legend>Platforms</legend>
          {PLATFORMS.map((p) => (
            <label key={p}>
              <input
                type="checkbox"
                checked={platforms.includes(p)}
                onChange={(e) =>
                  setPlatforms((now) =>
                    e.target.checked ? [...now, p] : now.filter((x) => x !== p),
                  )
                }
              />{" "}
              {providerName(p)}
            </label>
          ))}
          {errors.platforms ? (
            <p id="platforms-error" className={styles.missing}>
              {errors.platforms}
            </p>
          ) : null}
        </fieldset>
        <SelectField
          label="Objective"
          options={[
            { value: "", label: "Let the planner choose" },
            ...Object.entries(OBJECTIVES).map(([value, label]) => ({ value, label })),
          ]}
          value={objective}
          onChange={(e) => setObjective(e.target.value)}
        />
        <div className={own.row}>
          <TextField
            label={`Budget (${org.default_currency})`}
            inputMode="decimal"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            errors={errors.amount ? [errors.amount] : []}
            required
          />
          <SelectField
            label="Budget period"
            options={[
              { value: "daily", label: "Per day" },
              { value: "monthly", label: "Per month" },
            ]}
            value={period}
            onChange={(e) => setPeriod(e.target.value as "daily" | "monthly")}
          />
        </div>
        {error ? (
          <Alert tone="error" requestId={error instanceof ApiError ? error.requestId : null}>
            <p>{messageFor(error)}</p>
            {error instanceof ApiError && error.details.length ? (
              <ul className={own.reasons}>
                {errorReasons(error.details).map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            ) : null}
          </Alert>
        ) : null}
        {generate.isPending ? (
          <p role="status">Writing and checking the strategy — this can take up to a minute.</p>
        ) : null}
        <div>
          <Button type="submit" busy={generate.isPending}>
            Create strategy
          </Button>
        </div>
      </form>
    </section>
  );
}

function StrategyTable({ org, items }: { org: Organization; items: readonly StrategySummary[] }) {
  return (
    <ScrollTable label="Campaign strategies">
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">Product</th>
            <th scope="col">Platforms</th>
            <th scope="col">Objective</th>
            <th scope="col">Budget</th>
            <th scope="col">Status</th>
            <th scope="col">Last changed</th>
          </tr>
        </thead>
        <tbody>
          {items.map((s) => (
            <tr key={s.id}>
              <th scope="row">
                <Link href={`/orgs/${org.id}/strategies/${s.id}`}>
                  {s.product_title ?? "Product no longer in the store"}
                </Link>
              </th>
              <td>{s.platforms.map(providerName).join(", ")}</td>
              <td>{OBJECTIVES[s.objective] ?? s.objective}</td>
              <td className={styles.num}>
                {formatMoney(s.budget.amount, s.budget.currency, s.budget.currency_minor_units)}{" "}
                {PERIODS[s.budget.period]}
              </td>
              <td>
                <span className={`${styles.status} ${styles[STATUS[s.status]?.tone ?? "off"]}`}>
                  {statusLabel(s.status)}
                </span>
              </td>
              <td>{formatDateTime(s.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollTable>
  );
}

/** Campaign strategies: make one for a product, and the ones made so far (Phase 8). */
export function StrategiesPage() {
  const org = useCurrentOrganization();
  const [filter, setFilter] = useState<Filter>("");
  const list = useStrategies(org.id, filter);
  const manage = canManageStrategies(org.role);
  return (
    <section aria-labelledby="strategies-title">
      <PageHeading id="strategies-title">Campaign strategies</PageHeading>
      {manage ? <NewStrategy org={org} /> : null}
      <section aria-labelledby="strategy-list" className={styles.section}>
        <h2 id="strategy-list">Strategies</h2>
        <SelectField
          label="Show"
          options={FILTERS}
          value={filter}
          onChange={(e) => setFilter(e.target.value as Filter)}
        />
        {list.error ? (
          <Alert tone="error">{messageFor(list.error)}</Alert>
        ) : !list.data ? (
          <p role="status">Loading…</p>
        ) : list.data.length === 0 ? (
          <p className={styles.muted}>
            {manage
              ? "No strategies here yet. Make one above."
              : "No strategies here yet. Members who plan campaigns can make one."}
          </p>
        ) : (
          <StrategyTable org={org} items={list.data} />
        )}
      </section>
    </section>
  );
}

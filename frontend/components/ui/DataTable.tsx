"use client";

import { useMemo, useState, type ReactNode } from "react";

import { EmptyState } from "./EmptyState";
import { SelectField } from "./SelectField";
import styles from "./data-table.module.css";

export type SortDirection = "ascending" | "descending";

export type Column<Row> = {
  /** Unique within the table; also the key used by `defaultSort`. */
  readonly key: string;
  /** The column's title. Plain text: it is also the label shown beside a value on phones. */
  readonly header: string;
  readonly cell: (row: Row) => ReactNode;
  /** Right-aligned, with digits of equal width. Use for money, counts and percentages. */
  readonly numeric?: boolean;
  /** The cell names its row for screen readers (`<th scope="row">`). One per table, usually the first. */
  readonly rowHeader?: boolean;
  /** Gives the column a sort button. Return `null` for "no value": those rows always sort last. */
  readonly sortValue?: (row: Row) => string | number | null | undefined;
};

type DataTableProps<Row> = {
  /** What the table is. Shown above it; also the name of the scrollable region. */
  readonly caption: string;
  /** Keep the caption for assistive technology only, when a heading already says it. */
  readonly captionHidden?: boolean;
  readonly columns: readonly Column<Row>[];
  readonly rows: readonly Row[];
  readonly getRowKey: (row: Row) => string;
  /** Shown instead of the table when there are no rows. */
  readonly empty?: ReactNode;
  /**
   * How a narrow screen is handled. "scroll" (default) keeps the columns and scrolls sideways
   * inside the table's own box; "stack" turns each row into a labelled card.
   */
  readonly layout?: "scroll" | "stack";
  readonly defaultSort?: { readonly key: string; readonly direction: SortDirection };
};

function compare(
  a: string | number | null | undefined,
  b: string | number | null | undefined,
): number {
  const aMissing = a === null || a === undefined;
  const bMissing = b === null || b === undefined;
  if (aMissing || bMissing) return Number(aMissing) - Number(bMissing); // missing values last
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

/**
 * A data table: real `<table>` markup with a caption and header cells, optional sorting, and one
 * way of handling narrow screens. It does not fetch, filter or page: pass it the rows to show.
 */
export function DataTable<Row>({
  caption,
  captionHidden = false,
  columns,
  rows,
  getRowKey,
  empty,
  layout = "scroll",
  defaultSort,
}: DataTableProps<Row>) {
  const [sort, setSort] = useState(defaultSort ?? null);

  const shown = useMemo(() => {
    const column = sort ? columns.find((c) => c.key === sort.key) : undefined;
    if (!sort || !column?.sortValue) return rows;
    const value = column.sortValue;
    const factor = sort.direction === "ascending" ? 1 : -1;
    return rows
      .map((row, index) => ({ row, index }))
      .sort((x, y) => {
        const a = value(x.row);
        const b = value(y.row);
        const missing = (v: unknown) => v === null || v === undefined;
        // Missing values stay last in both directions; ties keep their original order.
        if (missing(a) || missing(b)) return compare(a, b) || x.index - y.index;
        return compare(a, b) * factor || x.index - y.index;
      })
      .map(({ row }) => row);
  }, [rows, columns, sort]);

  if (rows.length === 0) {
    return <>{empty ?? <EmptyState title="Nothing to show yet" />}</>;
  }

  function toggle(key: string) {
    setSort((current) =>
      current?.key === key && current.direction === "ascending"
        ? { key, direction: "descending" }
        : { key, direction: "ascending" },
    );
  }

  const sortable = columns.filter((column) => column.sortValue);
  const stacked = layout === "stack";
  // On phones a stacked table hides its header row, so its sort buttons go with it; this menu
  // takes their place (it is hidden from the screen and from assistive technology above 40 rem).
  const sortOptions = [
    { value: "", label: "Original order" },
    ...sortable.flatMap((column) => [
      { value: `${column.key}:ascending`, label: `${column.header}, ascending` },
      { value: `${column.key}:descending`, label: `${column.header}, descending` },
    ]),
  ];

  return (
    <>
      {stacked && sortable.length ? (
        <div className={styles.stackSort}>
          <SelectField
            label="Sort by"
            options={sortOptions}
            value={sort ? `${sort.key}:${sort.direction}` : ""}
            onChange={(event) => {
              const [key, direction] = event.target.value.split(":");
              setSort(key ? { key, direction: direction as SortDirection } : null);
            }}
          />
        </div>
      ) : null}
      <div
        className={`${styles.wrap} ${stacked ? styles.stackWrap : ""} ${stacked && sortable.length ? styles.stackSortable : ""}`}
        role="region"
        aria-label={caption}
        // A scrollable box must be reachable by keyboard so its content can be scrolled.
        tabIndex={layout === "scroll" ? 0 : undefined}
      >
        <table className={styles.table}>
          <caption className={captionHidden ? "visually-hidden" : styles.caption}>
            {caption}
          </caption>
          <thead>
            <tr>
              {columns.map((column) => {
                const sorted = sort?.key === column.key ? sort.direction : undefined;
                return (
                  <th
                    key={column.key}
                    scope="col"
                    className={column.numeric ? styles.numeric : undefined}
                    aria-sort={column.sortValue ? (sorted ?? "none") : undefined}
                  >
                    {column.sortValue ? (
                      <button
                        type="button"
                        className={styles.sort}
                        onClick={() => toggle(column.key)}
                      >
                        {column.header}
                        <span aria-hidden="true" className={styles.arrow}>
                          {sorted === "ascending" ? "▲" : sorted === "descending" ? "▼" : "↕"}
                        </span>
                      </button>
                    ) : (
                      column.header
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {shown.map((row) => (
              <tr key={getRowKey(row)}>
                {columns.map((column) =>
                  column.rowHeader ? (
                    <th
                      key={column.key}
                      scope="row"
                      data-label={column.header}
                      className={column.numeric ? styles.numeric : undefined}
                    >
                      {column.cell(row)}
                    </th>
                  ) : (
                    <td
                      key={column.key}
                      data-label={column.header}
                      className={column.numeric ? styles.numeric : undefined}
                    >
                      {column.cell(row)}
                    </td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

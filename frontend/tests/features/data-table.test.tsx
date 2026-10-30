import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DataTable, type Column } from "@/components/ui/DataTable";

import { click } from "../support/forms";

type Row = { id: string; name: string; spend: number | null; status: string };

const ROWS: Row[] = [
  { id: "1", name: "Gloves - Search", spend: 24, status: "Active" },
  { id: "2", name: "Boots - Shopping", spend: 3.5, status: "Paused" },
  { id: "3", name: "Aprons - Display", spend: null, status: "Active" },
  { id: "4", name: "Brushes 10", spend: 100, status: "Active" },
  { id: "5", name: "Brushes 2", spend: 7, status: "Paused" },
];

const COLUMNS: Column<Row>[] = [
  {
    key: "name",
    header: "Campaign",
    rowHeader: true,
    cell: (r) => r.name,
    sortValue: (r) => r.name,
  },
  {
    key: "spend",
    header: "Spend",
    numeric: true,
    cell: (r) => (r.spend === null ? "Not available" : `A$${r.spend.toFixed(2)}`),
    sortValue: (r) => r.spend,
  },
  { key: "status", header: "Status", cell: (r) => r.status },
];

function renderTable(props: Partial<React.ComponentProps<typeof DataTable<Row>>> = {}) {
  return render(
    <DataTable<Row>
      caption="Campaigns"
      columns={COLUMNS}
      rows={ROWS}
      getRowKey={(r) => r.id}
      {...props}
    />,
  );
}

const names = () =>
  within(screen.getByRole("table"))
    .getAllByRole("rowheader")
    .map((cell) => cell.textContent);

describe("DataTable", () => {
  it("is a real table with a caption, column headers and a row header per row", () => {
    renderTable();
    const table = screen.getByRole("table", { name: "Campaigns" });
    expect(within(table).getAllByRole("columnheader")).toHaveLength(3);
    expect(within(table).getAllByRole("rowheader")).toHaveLength(5);
    expect(within(table).getAllByRole("row")).toHaveLength(6); // header + 5
  });

  it("puts the table in a labelled, keyboard-reachable scroll region", () => {
    renderTable();
    const region = screen.getByRole("region", { name: "Campaigns" });
    expect(region).toHaveAttribute("tabindex", "0");
  });

  it("does not make the stacked layout a tab stop", () => {
    renderTable({ layout: "stack" });
    expect(screen.getByRole("region", { name: "Campaigns" })).not.toHaveAttribute("tabindex");
  });

  it("can hide the caption visually and keep it for screen readers", () => {
    renderTable({ captionHidden: true });
    expect(screen.getByText("Campaigns", { selector: "caption" })).toHaveClass("visually-hidden");
  });

  it("labels every cell with its column title for the stacked layout", () => {
    renderTable({ layout: "stack" });
    const row = screen.getAllByRole("row")[1] as HTMLElement;
    expect(within(row).getByText("A$24.00")).toHaveAttribute("data-label", "Spend");
  });

  it("marks numeric columns for right alignment", () => {
    renderTable();
    expect(screen.getByText("A$24.00").className).toMatch(/numeric/);
    expect(screen.getAllByText("Active", { selector: "td" })[0]?.className).not.toMatch(/numeric/);
  });

  it("only offers sorting on columns that define it, and announces the sort order", () => {
    renderTable();
    expect(screen.queryByRole("button", { name: /Status/ })).toBeNull();
    const spend = screen.getByRole("columnheader", { name: /Spend/ });
    expect(spend).toHaveAttribute("aria-sort", "none");
    click(within(spend).getByRole("button"));
    expect(spend).toHaveAttribute("aria-sort", "ascending");
    click(within(spend).getByRole("button"));
    expect(spend).toHaveAttribute("aria-sort", "descending");
  });

  it("sorts numbers numerically and keeps rows without a value last in both directions", () => {
    renderTable();
    const spend = screen.getByRole("columnheader", { name: /Spend/ });
    click(within(spend).getByRole("button"));
    expect(names()).toEqual([
      "Boots - Shopping",
      "Brushes 2",
      "Gloves - Search",
      "Brushes 10",
      "Aprons - Display",
    ]);
    click(within(spend).getByRole("button"));
    expect(names()).toEqual([
      "Brushes 10",
      "Gloves - Search",
      "Brushes 2",
      "Boots - Shopping",
      "Aprons - Display",
    ]);
  });

  it("sorts text with embedded numbers naturally (2 before 10)", () => {
    renderTable({ defaultSort: { key: "name", direction: "ascending" } });
    expect(names()).toEqual([
      "Aprons - Display",
      "Boots - Shopping",
      "Brushes 2",
      "Brushes 10",
      "Gloves - Search",
    ]);
  });

  it("offers a Sort by menu in the stacked layout, because its header row is hidden on phones", () => {
    renderTable({ layout: "stack" });
    const menu = screen.getByLabelText("Sort by");
    expect(menu).toHaveValue("");
    fireEvent.change(menu, { target: { value: "spend:descending" } });
    expect(names()[0]).toBe("Brushes 10");
    expect(screen.getByRole("columnheader", { name: /Spend/ })).toHaveAttribute(
      "aria-sort",
      "descending",
    );
    fireEvent.change(menu, { target: { value: "" } });
    expect(names()[0]).toBe("Gloves - Search");
  });

  it("has no Sort by menu in the scrolling layout, where the header buttons are visible", () => {
    renderTable();
    expect(screen.queryByLabelText("Sort by")).toBeNull();
  });

  it("never changes the rows it was given", () => {
    const rows = [...ROWS];
    renderTable({ rows, defaultSort: { key: "spend", direction: "descending" } });
    expect(rows.map((r) => r.id)).toEqual(["1", "2", "3", "4", "5"]);
  });

  it("shows the empty state instead of an empty table", () => {
    renderTable({ rows: [], empty: <p>No campaigns yet.</p> });
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByText("No campaigns yet.")).toBeVisible();
  });

  it("has a sensible default empty state", () => {
    renderTable({ rows: [] });
    expect(screen.getByText("Nothing to show yet")).toBeVisible();
  });
});

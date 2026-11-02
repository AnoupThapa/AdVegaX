import { act, fireEvent, render, screen } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider, useToast, type ToastInput } from "@/components/ui/Toast";

import { click } from "../support/forms";

const holder: { api: ReturnType<typeof useToast> | null } = { api: null };

/** Hands the toast API to the test once rendered. */
function Grab() {
  const api = useToast();
  useEffect(() => {
    holder.api = api;
  }, [api]);
  return null;
}

const toast = {
  show: (input: ToastInput) => holder.api!.show(input),
  dismiss: (id: number) => holder.api!.dismiss(id),
};

function setup() {
  return render(
    <ToastProvider>
      <Grab />
      <p>page</p>
    </ToastProvider>,
  );
}

function show(input: ToastInput) {
  let id = 0;
  act(() => {
    id = toast.show(input);
  });
  return id;
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("Toast", () => {
  it("shows a message politely (role=status) with its title", () => {
    setup();
    show({ tone: "success", title: "Saved", message: "Your settings were saved." });
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Saved");
    expect(status).toHaveTextContent("Your settings were saved.");
  });

  it("announces problems at once (role=alert) and keeps them until dismissed", () => {
    setup();
    show({ tone: "danger", message: "Could not save." });
    expect(screen.getByRole("alert")).toHaveTextContent("Could not save.");
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(screen.getByRole("alert")).toBeInTheDocument();
    click(screen.getByRole("button", { name: "Dismiss notification" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("removes success messages by itself after about five seconds", () => {
    setup();
    show({ tone: "success", message: "Done." });
    act(() => {
      vi.advanceTimersByTime(4900);
    });
    expect(screen.getByRole("status")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("honours a custom duration, and null to keep it", () => {
    setup();
    show({ message: "Quick", durationMs: 1000 });
    show({ message: "Sticky", durationMs: null });
    act(() => {
      vi.advanceTimersByTime(1100);
    });
    expect(screen.queryByText("Quick")).toBeNull();
    expect(screen.getByText("Sticky")).toBeInTheDocument();
  });

  it("pauses the timer while the pointer is over it", () => {
    setup();
    show({ tone: "success", message: "Read me" });
    const status = screen.getByRole("status");
    fireEvent.pointerEnter(status);
    act(() => {
      vi.advanceTimersByTime(30_000);
    });
    expect(screen.getByText("Read me")).toBeInTheDocument();
    fireEvent.pointerLeave(status);
    act(() => {
      vi.advanceTimersByTime(5100);
    });
    expect(screen.queryByText("Read me")).toBeNull();
  });

  it("dismisses with Escape", () => {
    setup();
    show({ tone: "danger", message: "Press escape" });
    fireEvent.keyDown(screen.getByRole("alert"), { key: "Escape" });
    expect(screen.queryByText("Press escape")).toBeNull();
  });

  it("shows at most three, dropping the oldest", () => {
    setup();
    for (const n of [1, 2, 3, 4]) show({ message: `Message ${n}`, durationMs: null });
    expect(screen.queryByText("Message 1")).toBeNull();
    expect(screen.getAllByRole("status")).toHaveLength(3);
    expect(screen.getByText("Message 4")).toBeInTheDocument();
  });

  it("can dismiss one by id", () => {
    setup();
    const id = show({ message: "Remove me", durationMs: null });
    act(() => toast.dismiss(id));
    expect(screen.queryByText("Remove me")).toBeNull();
  });

  it("leaves the page content alone and adds no landmark for an empty region", () => {
    const { container } = setup();
    expect(screen.getByText("page")).toBeInTheDocument();
    expect(container.querySelector("[role=region]")).toBeNull();
  });

  it("explains itself when used outside the provider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Grab />)).toThrow("useToast must be used inside ToastProvider");
    spy.mockRestore();
  });
});

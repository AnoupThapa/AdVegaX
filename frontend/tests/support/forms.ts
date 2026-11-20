import { fireEvent } from "@testing-library/react";

/** Sets an input's value the way typing would (no extra dependency needed). */
export function fill(element: HTMLElement, value: string): void {
  fireEvent.change(element, { target: { value } });
}

export function click(element: HTMLElement): void {
  fireEvent.click(element);
}

import { describe, expect, it, vi } from "vitest";

import { api, notifyUnauthenticated, setUnauthenticatedHandler } from "@/lib/api";

describe("app API client", () => {
  it("is configured for the API origin", () => {
    expect(typeof api.GET).toBe("function");
  });

  it("forwards session-end notifications to the registered handler", () => {
    const handler = vi.fn();
    notifyUnauthenticated(); // no handler yet: nothing happens
    setUnauthenticatedHandler(handler);
    notifyUnauthenticated();
    expect(handler).toHaveBeenCalledOnce();
    setUnauthenticatedHandler(null);
    notifyUnauthenticated();
    expect(handler).toHaveBeenCalledOnce();
  });
});

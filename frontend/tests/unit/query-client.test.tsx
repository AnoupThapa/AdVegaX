import { useQueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Providers } from "@/app/providers";
import { ApiError, NETWORK_ERROR } from "@/lib/api/errors";
import * as apiModule from "@/lib/api";
import { createQueryClient, shouldRetryQuery } from "@/lib/query/query-client";

describe("query retry policy", () => {
  it("retries network and server failures at most twice, never 4xx", () => {
    expect(shouldRetryQuery(0, new ApiError(0, NETWORK_ERROR))).toBe(true);
    expect(shouldRetryQuery(1, new ApiError(503, "SERVICE_UNAVAILABLE"))).toBe(true);
    expect(shouldRetryQuery(2, new ApiError(503, "SERVICE_UNAVAILABLE"))).toBe(false);
    expect(shouldRetryQuery(0, new ApiError(401, "UNAUTHENTICATED"))).toBe(false);
    expect(shouldRetryQuery(0, new ApiError(404, "NOT_FOUND"))).toBe(false);
    expect(shouldRetryQuery(0, new Error("boom"))).toBe(false);
  });

  it("never retries mutations", () => {
    const client = createQueryClient();
    expect(client.getDefaultOptions().mutations?.retry).toBe(false);
  });
});

describe("Providers", () => {
  afterEach(() => vi.restoreAllMocks());

  it("clears cached data when the session ends and unregisters on unmount", () => {
    const register = vi.spyOn(apiModule, "setUnauthenticatedHandler");
    let cache: ReturnType<typeof useQueryClient> | null = null;
    function Probe() {
      cache = useQueryClient();
      return <p>ready</p>;
    }
    const { unmount } = render(
      <Providers>
        <Probe />
      </Providers>,
    );
    expect(screen.getByText("ready")).toBeInTheDocument();
    cache!.setQueryData(["me"], { email: "a@example.com" });

    const handler = register.mock.calls.at(-1)?.[0];
    expect(typeof handler).toBe("function");
    handler?.();
    expect(cache!.getQueryData(["me"])).toBeUndefined();

    unmount();
    expect(register.mock.calls.at(-1)?.[0]).toBeNull();
  });
});

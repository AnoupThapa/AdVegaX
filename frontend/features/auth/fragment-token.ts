"use client";

import { useEffect, useRef, useState } from "react";

const TOKEN_PATTERN = /^[A-Za-z0-9_-]{16,256}$/;

/**
 * Reads a single-use token from the URL fragment (`#token=…`, PHASE_01C_PLAN §4.3) and
 * immediately removes it from the address bar and history. Fragments never reach servers,
 * logs or Referer headers; removing it keeps it out of screenshots and shared links.
 *
 * Returns `undefined` while reading, `null` when there is no valid token.
 */
export function readAndClearFragmentToken(): string | null {
  const hash = window.location.hash.replace(/^#/, "");
  const token = new URLSearchParams(hash).get("token");
  if (hash) {
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${window.location.search}`,
    );
  }
  return token && TOKEN_PATTERN.test(token) ? token : null;
}

export function useFragmentToken(): string | null | undefined {
  // The first read clears the fragment, so it is kept in a ref: React may run effects twice
  // in development (Strict Mode) and the second run must not see an empty fragment.
  const firstRead = useRef<string | null | undefined>(undefined);
  const [token, setToken] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    if (firstRead.current === undefined) {
      firstRead.current = readAndClearFragmentToken();
    }
    setToken(firstRead.current);
  }, []);
  return token;
}

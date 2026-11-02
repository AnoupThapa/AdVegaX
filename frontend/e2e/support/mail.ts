import { expect } from "@playwright/test";

import { MAILPIT, WEB } from "./env";

type Kind = "verify-email" | "reset-password" | "invitations/accept";

interface Summary {
  ID: string;
  Created: string;
}

/**
 * Waits for the newest email to `to` that contains a `${WEB}/<kind>#token=…` link and returns
 * the link. Email is delivered by the background worker, so this polls Mailpit.
 */
export async function emailLink(to: string, kind: Kind): Promise<string> {
  const pattern = new RegExp(`${escape(WEB)}/${escape(kind)}#token=[A-Za-z0-9_-]+`);
  const found: { link: string | null } = { link: null };
  await expect
    .poll(
      async () => {
        found.link = await findLink(to, pattern);
        return found.link !== null;
      },
      { message: `email with a ${kind} link for ${to}`, timeout: 30_000, intervals: [500] },
    )
    .toBe(true);
  if (!found.link) throw new Error(`no ${kind} email for ${to}`);
  return found.link;
}

async function findLink(to: string, pattern: RegExp): Promise<string | null> {
  const query = encodeURIComponent(`to:"${to}"`);
  const response = await fetch(`${MAILPIT}/api/v1/search?query=${query}`);
  if (!response.ok) return null;
  const { messages } = (await response.json()) as { messages: Summary[] };
  const newestFirst = [...messages].sort((a, b) => b.Created.localeCompare(a.Created));
  for (const message of newestFirst) {
    const detail = await fetch(`${MAILPIT}/api/v1/message/${message.ID}`);
    if (!detail.ok) continue;
    const body = (await detail.json()) as { Text?: string; HTML?: string };
    const match = `${body.Text ?? ""}\n${body.HTML ?? ""}`.match(pattern);
    if (match) return match[0];
  }
  return null;
}

function escape(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");
}

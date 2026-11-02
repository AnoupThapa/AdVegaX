import AxeBuilder from "@axe-core/playwright";
import { test as base, expect, type BrowserContext, type Page } from "@playwright/test";

/** A person using the app in their own browser (separate cookies and memory). */
export interface Person {
  readonly label: string;
  readonly page: Page;
  readonly context: BrowserContext;
  /** Security-policy violations, script errors and unexpected console errors seen so far. */
  readonly problems: string[];
  /** Declares API failures this test provokes on purpose (for example a reused link → 400). */
  expectFailedRequests(status: number): void;
}

const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];

// Expected while signed out or after access ends: the browser logs failed 401/403/404 loads.
const EXPECTED_CONSOLE = /status of 40[1349]/;

export const test = base.extend<{ newPerson: (label: string) => Promise<Person> }>({
  newPerson: async ({ browser }, use) => {
    const people: Person[] = [];
    await use(async (label) => {
      const context = await browser.newContext();
      const page = await context.newPage();
      const problems: string[] = [];
      const allowed = new Set<number>();
      await page.addInitScript(() => {
        document.addEventListener("securitypolicyviolation", (event) => {
          console.error(`CSP-VIOLATION ${event.violatedDirective} ${event.blockedURI}`);
        });
      });
      page.on("console", (message) => {
        const text = message.text();
        if (/CSP-VIOLATION|Content Security Policy/i.test(text)) problems.push(`CSP: ${text}`);
        else if (message.type() === "error" && !EXPECTED_CONSOLE.test(text)) {
          const status = Number(/status of (\d{3})/.exec(text)?.[1]);
          if (!allowed.has(status)) problems.push(`console: ${text}`);
        }
      });
      page.on("pageerror", (error) => problems.push(`script error: ${error.message}`));
      const person: Person = {
        label,
        page,
        context,
        problems,
        expectFailedRequests: (status) => allowed.add(status),
      };
      people.push(person);
      return person;
    });
    for (const person of people) {
      expect(person.problems, `browser problems for ${person.label}`).toEqual([]);
      await person.context.close();
    }
  },
});

export { expect };

/**
 * Accessibility gate (PHASE_01C_PLAN §8): no serious or critical axe violations. Minor ones are
 * recorded as annotations so they show in the report. Also checks that nothing was written to
 * browser storage or readable cookies.
 */
export async function expectAccessible(page: Page, label: string): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
  const describe = (v: (typeof results.violations)[number]) =>
    `${v.impact ?? "unknown"} ${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`;
  const blocking = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  for (const minor of results.violations.filter((v) => !blocking.includes(v))) {
    test
      .info()
      .annotations.push({ type: "axe (minor)", description: `${label}: ${describe(minor)}` });
  }
  expect(blocking.map(describe), `axe on "${label}"`).toEqual([]);
  await expectNoBrowserStorage(page, label);
}

export async function expectNoBrowserStorage(page: Page, label: string): Promise<void> {
  const stored = await page.evaluate(() => ({
    localStorage: Object.keys(window.localStorage),
    sessionStorage: Object.keys(window.sessionStorage),
    readableCookies: document.cookie,
  }));
  expect(stored, `browser storage on "${label}"`).toEqual({
    localStorage: [],
    sessionStorage: [],
    readableCookies: "",
  });
}

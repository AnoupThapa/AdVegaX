import type { SVGProps } from "react";

/** One icon set for the whole app: 24×24 outline icons drawn with `currentColor`, no dependency. */
const PATHS = {
  overview: "M4 13h6V4H4v9Zm0 7h6v-5H4v5Zm10 0h6V11h-6v9Zm0-16v5h6V4h-6Z",
  reports: "M6 3h9l4 4v14H6V3Zm8 0v5h5M9 13h7M9 17h7M9 9h2",
  funnel: "M3 5h18l-7 8v6l-4 2v-8L3 5Z",
  strategies: "M4 19V9l5 4 4-8 3 6 4-3v11H4Z",
  creatives: "M4 5h16v14H4V5Zm0 11 4-4 3 3 4-5 5 6M8.5 9.5h.01",
  recommendations: "M12 3a6 6 0 0 0-3.5 10.9V17h7v-3.1A6 6 0 0 0 12 3ZM9.5 20.5h5",
  changes: "M7 4v13m0 0-3-3m3 3 3-3M17 20V7m0 0-3 3m3-3 3 3",
  stores: "M4 9l1.5-5h13L20 9M4 9v11h16V9M4 9h16M9 20v-6h6v6",
  advertising: "M4 10v4h3l7 4V6L7 10H4Zm12-1a4 4 0 0 1 0 6",
  analytics: "M5 20V10m5 10V4m5 16v-7m5 7H3",
  connections: "M9 15 15 9M8 12l-2 2a3.5 3.5 0 0 0 5 5l2-2M16 12l2-2a3.5 3.5 0 0 0-5-5l-2 2",
  members:
    "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Zm-6 9v-1a5 5 0 0 1 10 0v1M16 4.5a3.5 3.5 0 0 1 0 7M18 14a5 5 0 0 1 3 5v1",
  settings: "M4 7h9m4 0h3M4 17h3m4 0h9M15 5v4M9 15v4",
  billing: "M3 6h18v12H3V6Zm0 4h18M7 15h4",
  clients: "M4 20V8l8-4 8 4v12M9 20v-6h6v6M8 10h.01M12 10h.01M16 10h.01",
  menu: "M4 7h16M4 12h16M4 17h16",
  close: "M6 6l12 12M18 6 6 18",
  chevron: "m9 6 6 6-6 6",
  check: "m5 12 5 5 9-10",
  shield: "M12 3 5 6v5c0 4.500 3 8 7 10 4-2 7-5.500 7-10V6l-7-3Zm-3 9 2.500 2.500L15.500 10",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z",
  alert: "M12 3 2.5 20h19L12 3Zm0 6v5m0 3h.01",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-10v6m0-9h.01",
  bolt: "M13 3 5 13h6l-1 8 8-10h-6l1-8Z",
} as const;

export type IconName = keyof typeof PATHS;

type IconProps = { readonly name: IconName; readonly size?: number } & Omit<
  SVGProps<SVGSVGElement>,
  "name" | "children"
>;

/** Decorative by default (`aria-hidden`): the visible text next to it carries the meaning. */
export function Icon({ name, size = 20, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      <path d={PATHS[name]} />
    </svg>
  );
}

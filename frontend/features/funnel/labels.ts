/**
 * Plain words for the funnel (7-07). Every count and rate comes from the API already
 * calculated (funnel-v1); this file only formats it — no page computes a formula.
 */

import { providerName } from "@/features/advertising/labels";
import type { MetricDefinition } from "@/features/overview/api";
import { definitionsByKey } from "@/features/overview/labels";
import { formatDay } from "@/features/stores/dates";
import { formatRatio } from "@/lib/format/money";

import type { FunnelFinding, FunnelStep } from "./api";

const SOURCES: Readonly<Record<string, string>> = {
  ads: "Google Ads and Meta",
  google_analytics: "Google Analytics",
  stores: "Your stores",
};

export function stageSource(definition: MetricDefinition, provider?: string): string {
  const source = definition.sources[0] ?? "";
  if (source === "platform" && provider) return `Reported by ${providerName(provider)}`;
  return SOURCES[source] ?? source;
}

export const FUNNEL_VIEWS = [
  { value: "whole", label: "Whole business" },
  { value: "platforms", label: "By ad platform" },
  { value: "channels", label: "By Google Analytics channel" },
  { value: "campaigns", label: "By campaign" },
  { value: "landing-pages", label: "By landing page" },
] as const;

export type FunnelView = (typeof FUNNEL_VIEWS)[number]["value"];

/** "Product views → Adds to cart", or the store conversion rate's own name. */
export function stepLabel(step: FunnelStep, definitions: readonly MetricDefinition[]): string {
  if (step.kind === "store_conversion") return "Store conversion rate (store orders per visit)";
  const define = definitionsByKey(definitions);
  return `${define(step.from_stage).label} → ${define(step.to_stage).label}`;
}

export const DIFFERENT_SOURCES =
  "Different sources — no rate. Ad clicks and website visits are counted differently.";

function subject(finding: FunnelFinding): string {
  if (finding.view === "platform" && finding.subject) return ` (${providerName(finding.subject)})`;
  if (finding.view === "channel" && finding.subject) return ` (${finding.subject} channel)`;
  return "";
}

/** "Adds to cart fell from 25.0% to 15.0% of Product views compared with 1 Oct – 7 Oct." */
export function findingText(
  finding: FunnelFinding,
  definitions: readonly MetricDefinition[],
  previousFrom: string,
  previousTo: string,
): string {
  const define = definitionsByKey(definitions);
  const later = define(finding.to_stage).label;
  const earlier = define(finding.from_stage).label.toLowerCase();
  return `${later}${subject(finding)} fell from ${formatRatio(finding.previous_rate)} to ${formatRatio(finding.rate)} of ${earlier}, compared with ${formatDay(previousFrom)} to ${formatDay(previousTo)}. It is also below its usual ${formatRatio(finding.baseline_rate)}.`;
}

import Link from "next/link";

import { Icon, type IconName } from "@/components/ui/Icon";

import styles from "./landing.module.css";

const STEPS: readonly { readonly title: string; readonly body: string }[] = [
  {
    title: "Connect",
    body: "Link your store, your ad accounts and Google Analytics. Connections only read data; you choose which accounts belong to which organization.",
  },
  {
    title: "Understand",
    body: "Sales, ad spend and profit are put side by side, with the funnel from first click to purchase. Where a figure is missing, it says so instead of showing zero.",
  },
  {
    title: "Decide",
    body: "AdVegaX proposes changes and strategies with the reasons, assumptions and risks written out. Nothing is sent to an ad platform on its own say-so.",
  },
  {
    title: "Act, with a record",
    body: "A person approves each change, or sets the limits within which automation may act. Every change is logged with who approved it and why.",
  },
];

const CONTROLS: readonly {
  readonly icon: IconName;
  readonly title: string;
  readonly body: string;
}[] = [
  {
    icon: "shield",
    title: "Separate organizations",
    body: "Each organization's data is isolated in the database itself, not only in the application.",
  },
  {
    icon: "members",
    title: "Roles that match the job",
    body: "Owner, Admin, Manager, Analyst and Viewer, enforced on the server for every request.",
  },
  {
    icon: "changes",
    title: "An audit log you can read",
    body: "Changes to ad accounts, members and settings are recorded and visible to owners and admins.",
  },
  {
    icon: "eye",
    title: "Figures you can check",
    body: "Each metric has a plain-language definition. Money is calculated in code, never estimated by the AI.",
  },
];

const PLATFORMS = ["Shopify", "WooCommerce", "Google Ads", "Meta Ads", "Google Analytics 4"];

/** The public home page for visitors who are not signed in. Only states what the product does. */
export function Landing() {
  return (
    <div className={styles.landing}>
      <section className={styles.hero} aria-labelledby="hero-title">
        <div className={styles.heroText}>
          <p className={styles.eyebrow}>For online stores that advertise</p>
          <h1 id="hero-title" className={styles.heroTitle}>
            Know what your advertising really earns, and change it with a record.
          </h1>
          <p className={styles.lead}>
            AdVegaX brings your store, ad accounts and analytics into one place, shows profit after
            ad spend, and proposes changes that a person approves before anything reaches an ad
            platform.
          </p>
          <div className={styles.actions}>
            <Link href="/sign-up" className={styles.primaryAction}>
              Create an account
            </Link>
            <Link href="/sign-in" className={styles.secondaryAction}>
              Sign in
            </Link>
          </div>
        </div>
        <figure className={styles.shot}>
          {/* eslint-disable-next-line @next/next/no-img-element -- a fixed local screenshot */}
          <img
            src="/product/overview-800.webp"
            srcSet="/product/overview-480.webp 480w, /product/overview-800.webp 800w, /product/overview.webp 1200w"
            sizes="(min-width: 64rem) 46vw, calc(100vw - 2rem)"
            width={1200}
            height={820}
            alt="The Overview page of a demo organization: sales, ad spend and profit figures, each with a link to how it is calculated."
            fetchPriority="high"
          />
          <figcaption>Overview page of the demo organization (simulated data).</figcaption>
        </figure>
      </section>

      <section className={styles.band} aria-labelledby="how-title">
        <h2 id="how-title">How it works</h2>
        <ol className={styles.steps}>
          {STEPS.map((step) => (
            <li key={step.title}>
              <h3>{step.title}</h3>
              <p>{step.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className={styles.split} aria-labelledby="review-title">
        <div>
          <h2 id="review-title">Every suggestion explains itself</h2>
          <p>
            A recommendation names the ad or campaign it is about, the change it proposes, the
            result it expects, the assumptions behind that, and how confident it is. You approve it,
            reject it, or ask for a different one.
          </p>
          <p>
            Automation is optional and bounded: an owner chooses which kinds of change it may make
            and the limits it must stay within.
          </p>
        </div>
        <figure className={styles.shot}>
          {/* eslint-disable-next-line @next/next/no-img-element -- a fixed local screenshot */}
          <img
            src="/product/recommendations-800.webp"
            srcSet="/product/recommendations-480.webp 480w, /product/recommendations-800.webp 800w, /product/recommendations.webp 1200w"
            sizes="(min-width: 64rem) 46vw, calc(100vw - 2rem)"
            width={1200}
            height={820}
            alt="The Recommendations page of a demo organization, listing proposed changes with their reasons."
            loading="lazy"
            decoding="async"
          />
          <figcaption>Recommendations in the demo organization (simulated data).</figcaption>
        </figure>
      </section>

      <section className={styles.band} aria-labelledby="control-title">
        <h2 id="control-title">Built so you stay in control</h2>
        <ul className={styles.controls}>
          {CONTROLS.map((item) => (
            <li key={item.title}>
              <Icon name={item.icon} size={22} />
              <div>
                <h3>{item.title}</h3>
                <p>{item.body}</p>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className={styles.platforms} aria-labelledby="platforms-title">
        <h2 id="platforms-title">Works with</h2>
        <ul className={styles.platformList}>
          {PLATFORMS.map((name) => (
            <li key={name}>{name}</li>
          ))}
        </ul>
        <p className={styles.note}>
          More platforms can be added later without changing how the rest of AdVegaX works.
        </p>
      </section>

      <section className={styles.closing} aria-labelledby="closing-title">
        <h2 id="closing-title">Start with an account</h2>
        <p>Create an organization, invite your team, and connect your first platform.</p>
        <div className={styles.actions}>
          <Link href="/sign-up" className={styles.primaryAction}>
            Create an account
          </Link>
          <Link href="/sign-in" className={styles.secondaryAction}>
            Sign in
          </Link>
        </div>
      </section>
    </div>
  );
}

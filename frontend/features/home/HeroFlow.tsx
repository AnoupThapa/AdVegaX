import { Icon, type IconName } from "@/components/ui/Icon";

import styles from "./hero-flow.module.css";

const SOURCES: readonly {
  readonly name: string;
  readonly what: string;
  readonly icon: IconName;
}[] = [
  { name: "Your store", what: "Orders and product costs", icon: "stores" },
  { name: "Google Ads", what: "Spend and conversions", icon: "advertising" },
  { name: "Meta", what: "Spend and conversions", icon: "advertising" },
  { name: "Google Analytics", what: "Visits and the funnel", icon: "analytics" },
];

// Connector paths in a 100 × 100 box (stretched to the column): from each source's middle on
// the left edge to the panel's middle on the right edge.
const PATHS = [12.5, 37.5, 62.5, 87.5].map((y) => `M 0 ${y} C 45 ${y}, 55 50, 100 50`);

/**
 * The home page's one moment of motion (Phase 19): the four sources draw their lines into one
 * panel, the panel appears, and its profit line draws itself. It plays once and is static for
 * anyone who asks for less motion. An illustration only: it shows no figures.
 */
export function HeroFlow() {
  return (
    <figure className={styles.flow}>
      <ul className={styles.sources} aria-label="What AdVegaX reads">
        {SOURCES.map((s) => (
          <li key={s.name} className={styles.source}>
            <Icon name={s.icon} size={20} />
            <span>
              <span className={styles.sourceName}>{s.name}</span>
              <span className={styles.sourceWhat}>{s.what}</span>
            </span>
          </li>
        ))}
      </ul>
      <svg
        className={styles.wires}
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        aria-hidden="true"
        focusable="false"
      >
        {PATHS.map((d) => (
          <g key={d}>
            <path d={d} pathLength={1} className={styles.wire} />
            <path d={d} pathLength={1} className={styles.pulse} />
          </g>
        ))}
      </svg>
      <div className={styles.panel}>
        <p className={styles.panelTitle}>Profit after ad spend</p>
        <p className={styles.panelNote}>One figure, worked out from all four, every day</p>
        <svg
          className={styles.chart}
          viewBox="0 0 200 80"
          preserveAspectRatio="none"
          aria-hidden="true"
          focusable="false"
        >
          <line x1="0" x2="200" y1="78" y2="78" className={styles.axis} />
          {[18, 34, 50, 66, 82, 98, 114, 130, 146, 162, 178].map((x, i) => (
            <rect
              key={x}
              x={x}
              width="8"
              y={66 - (i % 3) * 3}
              height={12 + (i % 3) * 3}
              className={styles.spend}
            />
          ))}
          <polyline
            points="0,62 20,58 40,60 60,50 80,52 100,40 120,42 140,30 160,33 180,20 200,14"
            pathLength={1}
            className={styles.profit}
          />
        </svg>
        <ul className={styles.panelKey} aria-hidden="true">
          <li>
            <span className={styles.keyLine} /> Profit
          </li>
          <li>
            <span className={styles.keyBar} /> Ad spend
          </li>
        </ul>
      </div>
      <figcaption className="visually-hidden">
        Your store, Google Ads, Meta and Google Analytics feed one figure: profit after ad spend.
      </figcaption>
    </figure>
  );
}

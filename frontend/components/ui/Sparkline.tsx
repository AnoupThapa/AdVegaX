import styles from "./ui.module.css";

type SparklineProps = {
  /** One value per day, oldest first; `null` where the day has no figure (drawn as a gap). */
  readonly values: readonly (number | null)[];
};

const WIDTH = 120;
const HEIGHT = 32;
const PAD = 2;

/**
 * A tiny trend line. Purely visual and hidden from assistive technology: the same numbers are
 * in the day-by-day table on the page. It only draws what it is given and never fills gaps.
 */
export function Sparkline({ values }: SparklineProps) {
  const present = values.filter((v): v is number => v !== null);
  if (present.length < 2) return null;
  const min = Math.min(...present);
  const max = Math.max(...present);
  const span = max - min || 1;
  const step = (WIDTH - 2 * PAD) / (values.length - 1);
  const y = (v: number) => HEIGHT - PAD - ((v - min) / span) * (HEIGHT - 2 * PAD);

  // Consecutive days with data form one line; a missing day breaks it.
  const runs: string[] = [];
  let current: string[] = [];
  values.forEach((v, i) => {
    if (v === null) {
      if (current.length) runs.push(current.join(" "));
      current = [];
    } else {
      current.push(`${(PAD + i * step).toFixed(1)},${y(v).toFixed(1)}`);
    }
  });
  if (current.length) runs.push(current.join(" "));

  return (
    <svg
      className={styles.sparkline}
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      width={WIDTH}
      height={HEIGHT}
      aria-hidden="true"
      focusable="false"
    >
      {runs.map((points) => (
        <polyline
          key={points}
          points={points}
          fill="none"
          stroke="currentColor"
          strokeWidth={1.75}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      ))}
    </svg>
  );
}

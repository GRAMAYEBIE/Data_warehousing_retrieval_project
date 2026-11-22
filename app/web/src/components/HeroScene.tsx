import { useReducedMotion } from "framer-motion";

// Abstract Manhattan-like street grid behind the hero. Each trip is an arc from a pickup to
// a dropoff: the arc draws itself, an amber dot travels along it, and the dropoff zone
// answers with a ripple. Clouds drift slowly. Decorative only (aria-hidden), pure SVG and
// CSS, and completely still when the visitor asks for reduced motion.
const AVENUES = Array.from({ length: 14 }, (_, i) => 20 + i * 70);
const STREETS = Array.from({ length: 11 }, (_, i) => -40 + i * 32);
const TRIPS = [
  { d: "M150 200 C 240 70, 360 70, 430 150", len: 360, dur: 6.5, delay: 0 },
  { d: "M520 30 C 600 120, 690 170, 800 112", len: 340, dur: 7, delay: 1.4 },
  { d: "M300 222 C 380 140, 560 150, 650 60", len: 430, dur: 7.5, delay: 2.8 },
  { d: "M720 228 C 790 160, 850 120, 930 168", len: 260, dur: 6, delay: 4.2 },
  { d: "M560 210 C 610 170, 660 190, 720 228", len: 190, dur: 5.5, delay: 3.4 },
];

export default function HeroScene() {
  const reduce = useReducedMotion();
  return (
    <svg
      aria-hidden="true"
      className="hero-scene pointer-events-none absolute inset-0 h-full w-full"
      viewBox="0 0 960 240"
      preserveAspectRatio="xMidYMid slice"
    >
      <defs>
        <linearGradient id="hero-fade" x1="0" x2="1">
          <stop offset="0%" stopColor="rgb(var(--surface))" stopOpacity="0.94" />
          <stop offset="42%" stopColor="rgb(var(--surface))" stopOpacity="0.5" />
          <stop offset="100%" stopColor="rgb(var(--surface))" stopOpacity="0" />
        </linearGradient>
        <radialGradient id="hero-glow" cx="78%" cy="40%" r="45%">
          <stop offset="0%" stopColor="rgb(var(--primary))" stopOpacity="0.1" />
          <stop offset="100%" stopColor="rgb(var(--primary))" stopOpacity="0" />
        </radialGradient>
        <filter id="cloud-blur" x="-20%" y="-50%" width="140%" height="200%">
          <feGaussianBlur stdDeviation="10" />
        </filter>
      </defs>
      <rect width="960" height="240" fill="url(#hero-glow)" />
      <g transform="rotate(-29 480 120)" stroke="rgb(var(--grid-line))">
        {AVENUES.map((x, i) => (
          <line key={`a${x}`} x1={x} y1={-200} x2={x} y2={440} strokeWidth={i % 3 === 0 ? 1.6 : 1} strokeOpacity={i % 3 === 0 ? 0.26 : 0.16} />
        ))}
        {STREETS.map((y) => (
          <line key={`s${y}`} x1={-240} y1={y} x2={1200} y2={y} strokeWidth={0.7} strokeOpacity={0.14} />
        ))}
      </g>

      {TRIPS.map((t) => (
        <g key={t.d}>
          <path
            d={t.d}
            fill="none"
            stroke="rgb(var(--primary))"
            strokeWidth={2}
            strokeLinecap="round"
            strokeOpacity={0.6}
            className="hero-trip"
            style={{
              ["--len" as string]: t.len,
              strokeDasharray: t.len,
              strokeDashoffset: 0,
              animationDuration: `${t.dur}s`,
              animationDelay: `${t.delay}s`,
            }}
          />
          {!reduce && (
            <circle r={3.4} fill="rgb(var(--accent))" stroke="rgb(var(--surface))" strokeWidth={1.4}>
              <animateMotion dur={`${t.dur}s`} begin={`${t.delay}s`} repeatCount="indefinite" path={t.d} keyPoints="0;1;1" keyTimes="0;0.55;1" calcMode="linear" />
              <animate attributeName="opacity" dur={`${t.dur}s`} begin={`${t.delay}s`} repeatCount="indefinite" values="0;1;1;0;0" keyTimes="0;0.08;0.55;0.62;1" />
            </circle>
          )}
          {(() => {
            const end = t.d.trim().split(/[ ,]+/).slice(-2).map(Number);
            return (
              <g>
                <circle cx={end[0]} cy={end[1]} r={3} fill="rgb(var(--accent))" />
                {!reduce && (
                  <circle cx={end[0]} cy={end[1]} r={3} fill="none" stroke="rgb(var(--accent))" strokeWidth={1.4}>
                    <animate attributeName="r" values="3;16;16" keyTimes="0;0.3;1" dur={`${t.dur}s`} begin={`${t.delay + t.dur * 0.55}s`} repeatCount="indefinite" />
                    <animate attributeName="opacity" values="0.8;0;0" keyTimes="0;0.3;1" dur={`${t.dur}s`} begin={`${t.delay + t.dur * 0.55}s`} repeatCount="indefinite" />
                  </circle>
                )}
              </g>
            );
          })()}
        </g>
      ))}

      <g fill="rgb(var(--surface))" filter="url(#cloud-blur)" opacity={0.8}>
        <ellipse className="hero-cloud" cx={0} cy={50} rx={90} ry={22} style={{ animationDuration: "70s" }} />
        <ellipse className="hero-cloud" cx={0} cy={176} rx={120} ry={26} style={{ animationDuration: "95s", animationDelay: "-40s" }} />
        <ellipse className="hero-cloud" cx={0} cy={112} rx={70} ry={18} style={{ animationDuration: "120s", animationDelay: "-80s" }} />
      </g>
      <rect width="960" height="240" fill="url(#hero-fade)" />
    </svg>
  );
}

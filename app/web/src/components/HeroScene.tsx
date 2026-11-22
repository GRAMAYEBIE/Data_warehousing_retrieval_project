// Abstract Manhattan-like street grid behind the hero: thin blue streets, trip arcs from a
// pickup to a dropoff that draw themselves, amber dots pulsing at busy zones, soft clouds
// drifting. Decorative only (aria-hidden), low opacity, pure SVG + CSS keyframes, and
// still when the visitor asks for reduced motion.
const AVENUES = Array.from({ length: 13 }, (_, i) => 40 + i * 72);
const STREETS = Array.from({ length: 9 }, (_, i) => 14 + i * 26);
const TRIPS = [
  { d: "M112 196 C 210 70, 330 70, 400 144", len: 360, delay: 0 },
  { d: "M472 40 C 560 120, 640 170, 760 118", len: 340, delay: 1.6 },
  { d: "M256 222 C 330 150, 520 160, 616 66", len: 420, delay: 3.1 },
  { d: "M688 222 C 760 160, 820 120, 904 170", len: 260, delay: 4.4 },
  { d: "M40 92 C 120 40, 200 40, 256 92", len: 250, delay: 2.4 },
];
const ZONES = [
  [400, 144],
  [616, 66],
  [256, 92],
  [760, 118],
  [904, 170],
];

export default function HeroScene() {
  return (
    <svg
      aria-hidden="true"
      className="hero-scene pointer-events-none absolute inset-0 h-full w-full"
      viewBox="0 0 960 240"
      preserveAspectRatio="xMidYMid slice"
    >
      <defs>
        <linearGradient id="hero-fade" x1="0" x2="1">
          <stop offset="0%" stopColor="rgb(var(--surface))" stopOpacity="0.92" />
          <stop offset="40%" stopColor="rgb(var(--surface))" stopOpacity="0.45" />
          <stop offset="100%" stopColor="rgb(var(--surface))" stopOpacity="0" />
        </linearGradient>
        <filter id="cloud-blur" x="-20%" y="-50%" width="140%" height="200%">
          <feGaussianBlur stdDeviation="10" />
        </filter>
      </defs>
      <g transform="rotate(-29 480 120)" stroke="rgb(var(--grid-line))" strokeOpacity="0.2">
        {AVENUES.map((x) => (
          <line key={`a${x}`} x1={x} y1={-160} x2={x} y2={400} strokeWidth={1.2} />
        ))}
        {STREETS.map((y) => (
          <line key={`s${y}`} x1={-200} y1={y * 1.6 - 60} x2={1160} y2={y * 1.6 - 60} strokeWidth={0.7} />
        ))}
      </g>
      <g fill="none" stroke="rgb(var(--primary))" strokeWidth={1.6} strokeLinecap="round">
        {TRIPS.map((t) => (
          <path
            key={t.d}
            d={t.d}
            className="hero-trip"
            style={{ ["--len" as string]: t.len, strokeDasharray: t.len, strokeDashoffset: 0, animationDelay: `${t.delay}s` }}
            strokeOpacity={0.55}
          />
        ))}
      </g>
      <g fill="rgb(var(--accent))">
        {ZONES.map(([x, y], i) => (
          <circle key={`${x}-${y}`} cx={x} cy={y} r={2.6} className="hero-zone" style={{ animationDelay: `${i * 0.5}s` }} />
        ))}
      </g>
      <g fill="rgb(var(--surface))" filter="url(#cloud-blur)" opacity={0.85}>
        <ellipse className="hero-cloud" cx={0} cy={54} rx={90} ry={22} style={{ animationDuration: "70s" }} />
        <ellipse className="hero-cloud" cx={0} cy={170} rx={120} ry={26} style={{ animationDuration: "95s", animationDelay: "-40s" }} />
        <ellipse className="hero-cloud" cx={0} cy={112} rx={70} ry={18} style={{ animationDuration: "120s", animationDelay: "-80s" }} />
      </g>
      <rect width="960" height="240" fill="url(#hero-fade)" />
    </svg>
  );
}

import { motion } from "framer-motion";

// Original illustration (drawn here, no external image): a yellow cab driving at night
// in front of a city skyline. Wheels turn, the road runs, a few windows light up.

const BUILDINGS = [
  { x: 0, w: 46, h: 120 },
  { x: 50, w: 34, h: 165 },
  { x: 88, w: 52, h: 95 },
  { x: 144, w: 30, h: 205, spire: true },
  { x: 178, w: 58, h: 140 },
  { x: 240, w: 38, h: 180 },
  { x: 282, w: 62, h: 110 },
  { x: 348, w: 36, h: 150 },
  { x: 388, w: 54, h: 125 },
  { x: 446, w: 40, h: 172 },
  { x: 490, w: 50, h: 100 },
];
const HORIZON = 228;

function windows() {
  const list: { x: number; y: number; on: boolean; blink: boolean }[] = [];
  BUILDINGS.forEach((b, bi) => {
    for (let y = HORIZON - b.h + 14; y < HORIZON - 12; y += 15) {
      for (let x = b.x + 7; x < b.x + b.w - 8; x += 11) {
        const seed = (x * 7 + y * 13 + bi * 31) % 17;
        list.push({ x, y, on: seed < 7, blink: seed === 3 });
      }
    }
  });
  return list;
}
const WINDOWS = windows();

export default function TaxiScene({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 540 300" className={className} role="img" aria-label="A yellow New York taxi driving at night">
      <defs>
        <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#0A1628" />
          <stop offset="100%" stopColor="#16304F" />
        </linearGradient>
        <linearGradient id="cab" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#FFD64D" />
          <stop offset="100%" stopColor="#E9A800" />
        </linearGradient>
        <linearGradient id="glass" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#3A5E86" />
          <stop offset="100%" stopColor="#0F2038" />
        </linearGradient>
        <linearGradient id="beam" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#FFF4C2" stopOpacity="0.75" />
          <stop offset="100%" stopColor="#FFF4C2" stopOpacity="0" />
        </linearGradient>
        <radialGradient id="moon" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0%" stopColor="#FFE9A3" stopOpacity="0.9" />
          <stop offset="100%" stopColor="#FFE9A3" stopOpacity="0" />
        </radialGradient>
        <pattern id="checks" width="8" height="8" patternUnits="userSpaceOnUse">
          <rect width="8" height="8" fill="#FFE07A" />
          <rect width="4" height="4" fill="#0A1628" />
          <rect x="4" y="4" width="4" height="4" fill="#0A1628" />
        </pattern>
      </defs>

      <rect width="540" height="300" rx="28" fill="url(#sky)" />
      <circle cx="455" cy="62" r="70" fill="url(#moon)" />
      <circle cx="455" cy="62" r="18" fill="#FFE9A3" opacity="0.9" />

      {/* Skyline, drifting slowly (parallax). */}
      <motion.g
        animate={{ x: [0, -12, 0] }}
        transition={{ duration: 18, repeat: Infinity, ease: "easeInOut" }}
      >
        {BUILDINGS.map((b) => (
          <g key={b.x}>
            <rect x={b.x} y={HORIZON - b.h} width={b.w} height={b.h} fill="#122A47" />
            {b.spire && <path d={`M${b.x + b.w / 2} ${HORIZON - b.h - 34} l6 34 h-12 z`} fill="#122A47" />}
          </g>
        ))}
        {WINDOWS.map((w) =>
          w.blink ? (
            <motion.rect
              key={`${w.x}-${w.y}`}
              x={w.x}
              y={w.y}
              width="5"
              height="7"
              rx="1"
              fill="#FFC93C"
              animate={{ opacity: [0.15, 0.9, 0.15] }}
              transition={{ duration: 3 + (w.x % 5), repeat: Infinity }}
            />
          ) : (
            <rect key={`${w.x}-${w.y}`} x={w.x} y={w.y} width="5" height="7" rx="1" fill="#FFC93C" opacity={w.on ? 0.55 : 0.08} />
          ),
        )}
      </motion.g>

      {/* Road with running lane marks. */}
      <rect x="0" y={HORIZON} width="540" height={300 - HORIZON} fill="#0B1424" />
      <rect x="0" y={HORIZON} width="540" height="3" fill="#F7B500" opacity="0.5" />
      <motion.g
        animate={{ x: [0, -60] }}
        transition={{ duration: 0.6, repeat: Infinity, ease: "linear" }}
      >
        {Array.from({ length: 12 }, (_, i) => (
          <rect key={i} x={i * 60} y="266" width="32" height="5" rx="2.5" fill="#E2E8F0" opacity="0.55" />
        ))}
      </motion.g>

      {/* Speed lines. */}
      {[176, 192, 208].map((y, i) => (
        <motion.rect
          key={y}
          y={y}
          height="2.5"
          rx="1.25"
          fill="#FFC93C"
          initial={{ x: 120, width: 0, opacity: 0 }}
          animate={{ x: [120, 40], width: [0, 70, 0], opacity: [0, 0.7, 0] }}
          transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.35, ease: "easeOut" }}
        />
      ))}

      {/* The cab, gently bouncing. */}
      <motion.g
        animate={{ y: [0, -2, 0] }}
        transition={{ duration: 0.5, repeat: Infinity, ease: "easeInOut" }}
      >
        <ellipse cx="272" cy="258" rx="140" ry="9" fill="#000" opacity="0.35" />
        <path d="M414 196 L540 168 L540 226 Z" fill="url(#beam)" />
        <path
          d="M140 236 L140 206 Q142 192 158 190 L208 186 L236 152 Q242 145 253 145 L322 145 Q335 145 343 153 L372 186 L398 192 Q414 196 414 212 L414 236 Q414 244 405 244 L149 244 Q140 244 140 236 Z"
          fill="url(#cab)"
        />
        <path d="M218 186 L242 158 Q245 153 252 153 L282 153 L282 186 Z" fill="url(#glass)" />
        <path d="M290 153 L320 153 Q328 153 333 159 L357 186 L290 186 Z" fill="url(#glass)" />
        <path d="M246 160 L262 160 L248 178 Z" fill="#fff" opacity="0.18" />
        <rect x="150" y="206" width="258" height="9" fill="url(#checks)" />
        <line x1="286" y1="186" x2="286" y2="242" stroke="#0A1628" strokeOpacity="0.25" strokeWidth="2" />
        <rect x="262" y="194" width="14" height="3" rx="1.5" fill="#0A1628" opacity="0.4" />
        <rect x="300" y="194" width="14" height="3" rx="1.5" fill="#0A1628" opacity="0.4" />
        <rect x="140" y="200" width="6" height="12" rx="2" fill="#F0564A" />
        <ellipse cx="410" cy="206" rx="5" ry="6" fill="#FFF4C2" />
        <rect x="266" y="128" width="44" height="17" rx="4" fill="#FFF4C2" stroke="#0A1628" strokeOpacity="0.2" />
        <text x="288" y="141" textAnchor="middle" fontSize="11" fontWeight="800" fill="#0A1628" fontFamily="Inter, sans-serif">
          TAXI
        </text>

        {[198, 356].map((cx) => (
          <g key={cx}>
            <circle cx={cx} cy="244" r="29" fill="#0B1424" />
            <motion.g
              style={{ transformBox: "fill-box", transformOrigin: "center" }}
              animate={{ rotate: 360 }}
              transition={{ duration: 0.6, repeat: Infinity, ease: "linear" }}
            >
              <circle cx={cx} cy="244" r="23" fill="#1A1A1A" />
              <circle cx={cx} cy="244" r="11" fill="#94A3B8" />
              {[0, 60, 120].map((a) => (
                <line
                  key={a}
                  x1={cx + 11 * Math.cos((a * Math.PI) / 180)}
                  y1={244 + 11 * Math.sin((a * Math.PI) / 180)}
                  x2={cx - 11 * Math.cos((a * Math.PI) / 180)}
                  y2={244 - 11 * Math.sin((a * Math.PI) / 180)}
                  stroke="#475569"
                  strokeWidth="2.5"
                />
              ))}
              <circle cx={cx} cy="244" r="3.5" fill="#E2E8F0" />
            </motion.g>
          </g>
        ))}
      </motion.g>
    </svg>
  );
}

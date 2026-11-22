import { motion, useReducedMotion } from "framer-motion";
import { Check } from "lucide-react";
import { useEffect, useState } from "react";

// The guardrail chain an answer goes through, shown while it is produced. The API answers
// in one response, so the steps advance on a timed, indeterminate sequence that stops at
// the last step until the answer arrives (the component is then replaced).
const STEPS: { name: string; detail: string; at: number }[] = [
  { name: "Plan", detail: "The model turns the question into a plan of governed measures", at: 0 },
  { name: "Validate", detail: "Code checks the plan against the catalogue and the question", at: 2.2 },
  { name: "Query", detail: "An approved SQL template runs read-only on published data", at: 4.4 },
  { name: "Explain", detail: "The model explains; every number is checked against the result", at: 5.6 },
];

export default function ThinkingCard() {
  const reduce = useReducedMotion();
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = setInterval(() => setSeconds((Date.now() - started) / 1000), 200);
    return () => clearInterval(timer);
  }, []);
  const current = STEPS.reduce((acc, step, i) => (seconds >= step.at ? i : acc), 0);

  return (
    <div className="card p-4" role="status" aria-live="polite" aria-label={`Working: ${STEPS[current].name}`}>
      <ol className="flex items-center gap-2">
        {STEPS.map((step, i) => {
          const state = i < current ? "done" : i === current ? "active" : "next";
          return (
            <li key={step.name} className="flex flex-1 items-center gap-2">
              <span
                className={`relative grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs font-semibold transition-colors duration-300 ${
                  state === "done"
                    ? "bg-good text-white"
                    : state === "active"
                      ? "bg-accent text-accent-ink"
                      : "border border-line bg-surface text-ink-3"
                }`}
              >
                {state === "active" && !reduce && (
                  <motion.span
                    className="absolute inset-0 rounded-full ring-2 ring-accent/60"
                    animate={{ scale: [1, 1.45], opacity: [0.8, 0] }}
                    transition={{ duration: 1.2, repeat: Infinity, ease: "easeOut" }}
                  />
                )}
                {state === "done" ? <Check size={13} strokeWidth={3} aria-hidden="true" /> : i + 1}
              </span>
              <span className={`text-sm ${state === "next" ? "text-ink-3" : "font-medium text-ink"}`}>{step.name}</span>
              {i < STEPS.length - 1 && (
                <span className="relative mx-1 h-px flex-1 overflow-hidden bg-line">
                  <motion.span
                    className="absolute inset-y-0 left-0 bg-good"
                    initial={false}
                    animate={{ width: i < current ? "100%" : "0%" }}
                    transition={{ duration: reduce ? 0 : 0.4, ease: "easeOut" }}
                  />
                </span>
              )}
            </li>
          );
        })}
      </ol>
      <p className="mt-3 text-xs text-ink-2">
        {STEPS[current].detail}… <span className="num text-ink-3">{Math.floor(seconds)} s</span>
      </p>
    </div>
  );
}

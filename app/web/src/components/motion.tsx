import { animate, motion, useMotionValue, useReducedMotion, useTransform } from "framer-motion";
import { type ReactNode, useEffect } from "react";

// Shared motion vocabulary: short, eased, purposeful, and switched off when the visitor
// asks the system for reduced motion.
export const ease = [0.22, 1, 0.36, 1] as const;
export const spring = { type: "spring", stiffness: 420, damping: 36, mass: 0.9 } as const;

export function Reveal({
  children,
  delay = 0,
  y = 8,
  className = "",
}: {
  children: ReactNode;
  delay?: number;
  y?: number;
  className?: string;
}) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={reduce ? false : { opacity: 0, y }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.38, delay, ease }}
    >
      {children}
    </motion.div>
  );
}

export const stagger = {
  hidden: {},
  show: { transition: { staggerChildren: 0.05, delayChildren: 0.05 } },
};
export const rise = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0, transition: { duration: 0.32, ease } },
};

// A number that counts up to its value; the final text is exactly the formatted
// governed value.
export function CountUp({ value, format }: { value: number; format: (n: number) => string }) {
  const reduce = useReducedMotion();
  const current = useMotionValue(reduce ? value : 0);
  const text = useTransform(current, (n) => format(n));
  useEffect(() => {
    if (reduce) {
      current.set(value);
      return undefined;
    }
    const controls = animate(current, value, { duration: 0.6, ease: "easeOut" });
    return () => controls.stop();
  }, [value, reduce, current]);
  return <motion.span>{text}</motion.span>;
}

// Text that appears word by word, fast: the full text is in the DOM from the start (for
// screen readers and copy), only its opacity is animated.
export function WordReveal({ text, className = "" }: { text: string; className?: string }) {
  const reduce = useReducedMotion();
  if (reduce) return <p className={className}>{text}</p>;
  const words = text.split(/(\s+)/);
  const step = Math.min(0.025, 0.6 / Math.max(words.length, 1));
  return (
    <p className={className}>
      {words.map((word, i) =>
        /^\s+$/.test(word) ? (
          word
        ) : (
          <motion.span
            key={i}
            initial={{ opacity: 0, filter: "blur(2px)" }}
            animate={{ opacity: 1, filter: "blur(0px)" }}
            transition={{ duration: 0.25, delay: i * step }}
          >
            {word}
          </motion.span>
        ),
      )}
    </p>
  );
}

import { animate, motion, useMotionValue, useReducedMotion, useTransform } from "framer-motion";
import { type ReactNode, useEffect } from "react";

// Shared motion vocabulary: short, eased, and switched off when the visitor asks the system
// for reduced motion.
export const ease = [0.22, 1, 0.36, 1] as const;

export function Reveal({ children, delay = 0, className = "" }: { children: ReactNode; delay?: number; className?: string }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={reduce ? false : { opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay, ease }}
    >
      {children}
    </motion.div>
  );
}

export const stagger = {
  hidden: {},
  show: { transition: { staggerChildren: 0.07, delayChildren: 0.15 } },
};
export const rise = {
  hidden: { opacity: 0, y: 16, scale: 0.98 },
  show: { opacity: 1, y: 0, scale: 1, transition: { duration: 0.45, ease } },
};

// A number that counts up to its value (for indicator tiles); the final text is exactly
// the formatted governed value.
export function CountUp({ value, format }: { value: number; format: (n: number) => string }) {
  const reduce = useReducedMotion();
  const current = useMotionValue(reduce ? value : 0);
  const text = useTransform(current, (n) => format(n));
  useEffect(() => {
    if (reduce) return;
    const controls = animate(current, value, { duration: 1.1, ease });
    return () => controls.stop();
  }, [value, reduce, current]);
  return <motion.span>{text}</motion.span>;
}

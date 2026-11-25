import { motion } from "framer-motion";
import { spring } from "./motion";

// Segmented control: one choice among a few (measure, borough, month, day type).
export default function Tabs<T extends string>({
  label,
  id,
  items,
  value,
  onChange,
}: {
  label: string;
  id: string;
  items: [T, string][];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="inline-flex flex-wrap rounded-input bg-tint p-1" role="tablist" aria-label={label}>
      {items.map(([key, text]) => (
        <button
          key={key}
          role="tab"
          aria-selected={value === key}
          onClick={() => onChange(key)}
          className={`relative rounded-[8px] px-3 py-1 text-xs font-medium transition-colors ${value === key ? "text-ink" : "text-ink-2 hover:text-ink"}`}
        >
          {value === key && <motion.span layoutId={id} className="absolute inset-0 rounded-[8px] bg-surface shadow-soft" transition={spring} />}
          <span className="relative">{text}</span>
        </button>
      ))}
    </div>
  );
}

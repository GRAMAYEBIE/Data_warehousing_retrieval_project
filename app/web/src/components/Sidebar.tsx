import { motion } from "framer-motion";
import {
  Activity,
  ArrowUpRight,
  BarChart3,
  CarTaxiFront,
  FileBarChart2,
  Laptop,
  Lock,
  MessagesSquare,
  Moon,
  Sun,
} from "lucide-react";
import type { ReactNode } from "react";
import type { CatalogView, Health } from "../api/client";
import { useConfig } from "../lib/config";
import { DATA_OWNER } from "../lib/measures";
import { type Theme, useTheme } from "../lib/theme";
import { spring } from "./motion";

export type Page = "ask" | "reports";

export function BrandMark({ size = 32 }: { size?: number }) {
  return (
    <span
      className="grid shrink-0 place-items-center rounded-[9px] bg-accent text-accent-ink"
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <CarTaxiFront size={size * 0.56} strokeWidth={2.2} />
    </span>
  );
}

type Props = {
  page: Page;
  onPage: (page: Page) => void;
  health?: Health;
  catalog?: CatalogView;
};

export default function Sidebar({ page, onPage, health, catalog }: Props) {
  const config = useConfig();
  return (
    <aside className="sticky top-0 hidden h-screen w-[248px] shrink-0 flex-col border-r border-line bg-surface lg:flex">
      <div className="flex h-16 items-center gap-2.5 px-5">
        <BrandMark />
        <div className="leading-tight">
          <div className="font-display text-[15px] font-semibold">MetroMove Insight</div>
          <div className="text-xs text-ink-3">NYC taxi analytics</div>
        </div>
      </div>

      <nav className="mt-2 flex flex-col gap-0.5 px-3" aria-label="Main">
        <div className="label px-2.5 pb-1.5 pt-2">Assistant</div>
        <NavItem active={page === "ask"} onClick={() => onPage("ask")} icon={<MessagesSquare size={16} />}>
          Ask a question
        </NavItem>
        <NavItem active={page === "reports"} onClick={() => onPage("reports")} icon={<FileBarChart2 size={16} />}>
          Report builder
        </NavItem>
        <div className="label px-2.5 pb-1.5 pt-5">Platform</div>
        <LinkItem href={config.supersetUrl} icon={<BarChart3 size={16} />}>
          Dashboards
        </LinkItem>
        {config.showPlatformHealth && (
          <LinkItem href={config.grafanaUrl} icon={<Activity size={16} />} badge={<Lock size={12} aria-label="Administrators only" />}>
            Platform health
          </LinkItem>
        )}
      </nav>

      <div className="mt-auto space-y-3 p-3">
        <StatusCard health={health} catalog={catalog} />
        <div className="flex items-center justify-between px-2">
          <span className="text-xs text-ink-3">Data owner · {DATA_OWNER}</span>
          <ThemeSwitch />
        </div>
      </div>
    </aside>
  );
}

export function StatusCard({ health, catalog }: { health?: Health; catalog?: CatalogView }) {
  const ready = health?.status === "ok" && health.model_available;
  const months = health?.complete_months ?? [];
  return (
    <div className="rounded-card border border-line bg-page/60 p-3.5" aria-live="polite">
      <div className="flex items-center gap-2 text-sm font-medium">
        <span className="relative flex h-2.5 w-2.5" aria-hidden="true">
          {ready && <span className="blink absolute inline-flex h-full w-full rounded-full bg-good/60" />}
          <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${!health ? "bg-ink-3" : ready ? "bg-good" : "bg-bad"}`} />
        </span>
        {!health ? "Connecting…" : ready ? "Assistant ready" : "Assistant offline"}
      </div>
      <dl className="mt-2.5 space-y-1.5 text-xs">
        <Row label="Model" value={health?.model ?? "-"} />
        <Row label="Data" value={months.length ? `${months[0]} → ${months[months.length - 1]}` : "-"} />
        <Row label="Publication" value={catalog?.published_run ?? "-"} mono />
      </dl>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-ink-3">{label}</dt>
      <dd className={`num truncate font-medium text-ink ${mono ? "font-mono text-[11px]" : ""}`}>{value}</dd>
    </div>
  );
}

function NavItem({ active, onClick, icon, children }: { active: boolean; onClick: () => void; icon: ReactNode; children: ReactNode }) {
  return (
    <button
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={`relative flex h-9 w-full items-center gap-2.5 rounded-input px-2.5 text-left text-sm transition-colors duration-150 ${
        active ? "font-medium text-primary-strong" : "text-ink-2 hover:bg-tint hover:text-ink"
      }`}
    >
      {active && <motion.span layoutId="nav-active" className="absolute inset-0 rounded-input bg-primary/10" transition={spring} />}
      <span className="relative">{icon}</span>
      <span className="relative">{children}</span>
    </button>
  );
}

function LinkItem({ href, icon, badge, children }: { href: string; icon: ReactNode; badge?: ReactNode; children: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="group flex h-9 items-center gap-2.5 rounded-input px-2.5 text-sm text-ink-2 transition-colors duration-150 hover:bg-tint hover:text-ink"
    >
      {icon}
      <span className="flex-1">{children}</span>
      {badge && <span className="text-ink-3">{badge}</span>}
      <ArrowUpRight size={14} className="text-ink-3 opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
      <span className="sr-only">(opens in a new tab)</span>
    </a>
  );
}

const NEXT: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };
const ICON: Record<Theme, ReactNode> = { system: <Laptop size={15} />, light: <Sun size={15} />, dark: <Moon size={15} /> };

export function ThemeSwitch() {
  const [theme, setTheme] = useTheme();
  return (
    <button
      className="btn-ghost h-8 w-8 p-0"
      onClick={() => setTheme(NEXT[theme])}
      aria-label={`Colour theme: ${theme}. Switch to ${NEXT[theme]}`}
      title={`Theme: ${theme}`}
    >
      {ICON[theme]}
    </button>
  );
}

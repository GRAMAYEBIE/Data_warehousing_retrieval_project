import { useEffect, useState } from "react";

// Light, dark, or the system's choice. The choice is a per-visitor convenience kept in the
// browser; when storage is unavailable the interface simply follows the system.
export type Theme = "light" | "dark" | "system";
const KEY = "insight-theme";

function stored(): Theme {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

function apply(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
}

export function useTheme(): [Theme, (theme: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(stored);
  useEffect(() => {
    apply(theme);
    try {
      if (theme === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, theme);
    } catch {
      /* storage blocked: the choice lasts for this visit only */
    }
  }, [theme]);
  return [theme, setTheme];
}

// Whether the page currently renders dark (explicit choice or system), for chart colours
// that cannot be expressed as CSS variables.
export function useIsDark(): boolean {
  const query = typeof window !== "undefined" ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  const read = () => {
    const forced = document.documentElement.getAttribute("data-theme");
    return forced ? forced === "dark" : Boolean(query?.matches);
  };
  const [dark, setDark] = useState(read);
  useEffect(() => {
    const update = () => setDark(read());
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    query?.addEventListener("change", update);
    return () => {
      observer.disconnect();
      query?.removeEventListener("change", update);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return dark;
}

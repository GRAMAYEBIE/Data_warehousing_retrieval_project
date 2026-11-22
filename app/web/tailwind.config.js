/** @type {import('tailwindcss').Config} */

// Every colour is a role backed by a CSS variable (src/index.css): one place for the
// tokens, and the dark theme is a second set of values for the same names.
const role = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        page: role("page"),
        surface: role("surface"),
        tint: role("tint"),
        line: role("line"),
        "line-strong": role("line-strong"),
        ink: role("ink"),
        "ink-2": role("ink-2"),
        "ink-3": role("ink-3"),
        primary: role("primary"),
        "primary-strong": role("primary-strong"),
        accent: role("accent"),
        "accent-ink": role("accent-ink"),
        bad: role("bad"),
        "bad-ink": role("bad-ink"),
        good: role("good"),
        "good-ink": role("good-ink"),
        s1: role("series-1"),
        s2: role("series-2"),
        s3: role("series-3"),
      },
      fontFamily: {
        sans: ["'Inter Variable'", "Inter", "system-ui", "-apple-system", "'Segoe UI'", "sans-serif"],
        display: ["'Plus Jakarta Sans Variable'", "'Inter Variable'", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      borderRadius: {
        card: "12px",
        input: "10px",
      },
      boxShadow: {
        soft: "0 1px 2px rgb(var(--shadow) / 0.04), 0 8px 24px rgb(var(--shadow) / 0.06)",
        raised: "0 1px 2px rgb(var(--shadow) / 0.04), 0 16px 40px rgb(var(--shadow) / 0.1)",
      },
    },
  },
  plugins: [],
};

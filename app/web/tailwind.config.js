/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // MetroMove Insight: New York night blue, taxi yellow, and two signal colours.
        night: {
          950: "#060E1A",
          900: "#0A1628",
          800: "#0F2038",
          700: "#16304F",
          600: "#1F4E79",
          500: "#2E6DA4",
        },
        taxi: { 300: "#FFDB70", 400: "#FFC93C", 500: "#F7B500", 600: "#D99A00" },
        mint: { 50: "#ECFDF8", 100: "#D1FAEE", 500: "#14B8A6", 600: "#0D9488", 700: "#0F766E" },
        coral: { 50: "#FFF1F0", 100: "#FFE0DD", 500: "#F0564A", 600: "#D93B30" },
        sky: { 50: "#EEF6FF", 100: "#DCEBFF", 500: "#3B82F6" },
        mist: "#F4F7FB",
      },
      fontFamily: {
        sans: ["'Inter Variable'", "Inter", "system-ui", "sans-serif"],
      },
      boxShadow: {
        soft: "0 1px 2px rgba(10,22,40,0.04), 0 8px 24px -8px rgba(10,22,40,0.12)",
        lift: "0 2px 4px rgba(10,22,40,0.06), 0 16px 40px -12px rgba(10,22,40,0.25)",
        glow: "0 0 0 1px rgba(247,181,0,0.35), 0 8px 28px -6px rgba(247,181,0,0.45)",
      },
      backgroundImage: {
        "taxi-gradient": "linear-gradient(135deg, #FFC93C 0%, #F7B500 55%, #E8A100 100%)",
        "night-gradient": "linear-gradient(180deg, #0A1628 0%, #0F2038 60%, #16304F 100%)",
        "hero-glow":
          "radial-gradient(60% 80% at 15% 0%, rgba(247,181,0,0.18) 0%, transparent 60%), radial-gradient(50% 70% at 100% 10%, rgba(46,109,164,0.20) 0%, transparent 60%)",
        checker:
          "repeating-linear-gradient(90deg, #0A1628 0 6px, #F7B500 6px 12px)",
      },
      keyframes: {
        "fade-up": {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          from: { backgroundPosition: "-400px 0" },
          to: { backgroundPosition: "400px 0" },
        },
        "pulse-dot": {
          "0%, 100%": { transform: "scale(1)", opacity: "1" },
          "50%": { transform: "scale(1.6)", opacity: "0.4" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.35s ease-out both",
        shimmer: "shimmer 1.6s linear infinite",
        "pulse-dot": "pulse-dot 1.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

/** @type {import('tailwindcss').Config} */

// Every colour is a CSS variable so that light and dark are one set of class
// names with two sets of values (see src/index.css). Semantic red/amber/green
// exist only for risk tiers - nothing else in the product may use them, or the
// colour stops meaning "this vehicle needs attention".
const withVar = (name) => `rgb(var(${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        canvas: withVar("--canvas"),
        surface: withVar("--surface"),
        raised: withVar("--raised"),
        hairline: withVar("--hairline"),
        ink: withVar("--ink"),
        muted: withVar("--muted"),
        faint: withVar("--faint"),
        accent: {
          DEFAULT: withVar("--accent"),
          soft: withVar("--accent-soft"),
          ink: withVar("--accent-ink"),
        },
        risk: {
          red: withVar("--risk-red"),
          "red-soft": withVar("--risk-red-soft"),
          amber: withVar("--risk-amber"),
          "amber-soft": withVar("--risk-amber-soft"),
          green: withVar("--risk-green"),
          "green-soft": withVar("--risk-green-soft"),
        },
      },
      fontFamily: {
        sans: [
          "Inter var",
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        mono: ["JetBrains Mono", "SFMono-Regular", "Consolas", "monospace"],
      },
      fontSize: {
        kpi: ["2.5rem", { lineHeight: "1", letterSpacing: "-0.03em" }],
        display: ["1.75rem", { lineHeight: "1.15", letterSpacing: "-0.02em" }],
        label: ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.06em" }],
      },
      borderRadius: {
        card: "0.875rem",
        panel: "1rem",
      },
      boxShadow: {
        // Shadows are for overlays only. Static cards use a hairline border.
        overlay: "0 24px 60px -20px rgb(0 0 0 / 0.28), 0 4px 12px -6px rgb(0 0 0 / 0.14)",
        pop: "0 12px 32px -12px rgb(0 0 0 / 0.22)",
      },
      keyframes: {
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        shimmer: "shimmer 1.8s infinite",
      },
      transitionTimingFunction: {
        "out-soft": "cubic-bezier(0.22, 1, 0.36, 1)",
      },
    },
  },
  plugins: [],
};

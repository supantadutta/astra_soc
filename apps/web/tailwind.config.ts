import type { Config } from "tailwindcss";

/**
 * ASTRASOC design tokens — a premium cyber-defense command center.
 * Deep obsidian base, layered navy surfaces, electric cyan accent,
 * teal (healthy), violet (AI), amber (warning), red/magenta (critical).
 */
const config: Config = {
  content: [
    "./src/app/**/*.{ts,tsx}",
    "./src/components/**/*.{ts,tsx}",
    "./src/lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        obsidian: "#05070d",
        void: "#03040a",
        navy: {
          900: "#0a0f1c",
          800: "#0d1526",
          700: "#111d33",
          600: "#16273f",
          500: "#1d3352",
        },
        cyan: {
          DEFAULT: "#22d3ee",
          glow: "#0ff4ff",
        },
        teal: { DEFAULT: "#2dd4bf" },
        violet: { DEFAULT: "#a78bfa", glow: "#8b5cf6" },
        amber: { DEFAULT: "#f59e0b" },
        crit: { DEFAULT: "#f43f5e", glow: "#ff2d6f" },
        ink: {
          100: "#e6f0ff",
          200: "#c7d5ee",
          300: "#9fb3d1",
          400: "#6f83a6",
          500: "#4a5a78",
        },
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(34,211,238,0.25), 0 0 24px -6px rgba(34,211,238,0.35)",
        "glow-violet": "0 0 0 1px rgba(167,139,250,0.25), 0 0 24px -6px rgba(139,92,246,0.4)",
        "glow-crit": "0 0 0 1px rgba(244,63,94,0.3), 0 0 24px -6px rgba(255,45,111,0.5)",
        panel: "0 8px 40px -12px rgba(0,0,0,0.6)",
      },
      backgroundImage: {
        grid: "linear-gradient(rgba(34,211,238,0.045) 1px, transparent 1px), linear-gradient(90deg, rgba(34,211,238,0.045) 1px, transparent 1px)",
        radar: "radial-gradient(circle at center, rgba(34,211,238,0.12), transparent 60%)",
      },
      backgroundSize: { grid: "40px 40px" },
      keyframes: {
        pulseGlow: {
          "0%,100%": { opacity: "0.6", transform: "scale(1)" },
          "50%": { opacity: "1", transform: "scale(1.08)" },
        },
        scan: {
          "0%": { transform: "translateY(-100%)" },
          "100%": { transform: "translateY(100%)" },
        },
        streamdown: {
          "0%": { transform: "translateY(-10px)", opacity: "0" },
          "10%": { opacity: "1" },
          "100%": { transform: "translateY(0)", opacity: "1" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-400px 0" },
          "100%": { backgroundPosition: "400px 0" },
        },
      },
      animation: {
        pulseGlow: "pulseGlow 2.2s ease-in-out infinite",
        scan: "scan 6s linear infinite",
        streamdown: "streamdown 0.35s ease-out",
        shimmer: "shimmer 1.4s linear infinite",
      },
    },
  },
  plugins: [],
};

export default config;

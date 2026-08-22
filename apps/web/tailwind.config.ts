import type { Config } from "tailwindcss";

/**
 * Matchly's visual language: dark, high-contrast, video-first.
 * A pitch-green accent carries every primary action; everything else stays
 * out of the way of the video.
 */
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        pitch: {
          50: "#ecfdf3",
          100: "#d1fadf",
          300: "#6ce9a6",
          400: "#32d583",
          500: "#12b76a",
          600: "#039855",
          700: "#027a48",
        },
        ink: {
          900: "#0a0d10",
          800: "#111417",
          700: "#181c21",
          600: "#22272e",
          500: "#2e353e",
          400: "#4a545f",
          300: "#7a858f",
          200: "#aab3bc",
          100: "#e4e8ec",
        },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
      },
      borderRadius: {
        xl: "0.875rem",
        "2xl": "1.25rem",
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-in": "fade-in 200ms ease-out",
      },
    },
  },
  plugins: [],
};

export default config;

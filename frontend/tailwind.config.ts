import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))"
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))"
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))"
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))"
        }
      },
      fontFamily: {
        sans: ["var(--font-inter)", "Inter", "ui-sans-serif", "system-ui"]
      },
      boxShadow: {
        glow: "0 0 48px rgba(34, 211, 238, 0.24)",
        "glow-pink": "0 0 64px rgba(236, 72, 153, 0.28)",
        "glow-red": "0 0 70px rgba(239, 68, 68, 0.26)",
        "cinema-card": "0 26px 95px rgba(0, 0, 0, 0.46)",
        "cinema-card-hover": "0 34px 120px rgba(0, 0, 0, 0.58)"
      },
      backgroundImage: {
        "cinema-radial":
          "radial-gradient(circle at top left, rgba(236,72,153,.26), transparent 32%), radial-gradient(circle at 78% 18%, rgba(37,99,235,.24), transparent 28%), radial-gradient(circle at 45% 100%, rgba(34,211,238,.18), transparent 36%)"
      }
    }
  },
  plugins: []
};

export default config;
